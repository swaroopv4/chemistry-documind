"""Encrypted, consistent SQLite snapshots; restore into a new directory only."""
from datetime import datetime,timezone
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile
from cryptography.fernet import Fernet,InvalidToken
from core.access import require_admin
from phases.phase3_hard.storage import data_dir

MAX_ARCHIVE = 128*1024*1024

def key():
    supplied = os.getenv('BACKUP_ENCRYPTION_KEY')
    if supplied:
        return supplied.encode('ascii')
    path = data_dir()/'.backup-key'
    if not path.exists():
        try:
            with path.open('xb') as handle:
                handle.write(Fernet.generate_key())
            path.chmod(0o600)
        except FileExistsError:
            pass
    return path.read_bytes().strip()

def _safe_name(name):
    path = Path(name)
    return not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name and (name in {'state.sqlite3','documind.db'} or
        len(path.parts)==2 and path.parts[0] in {'logs','reports'} and path.suffix in {'.json','.jsonl','.csv'})

def export(principal):
    require_admin(principal)
    from core.versions import document_lock
    root = data_dir().resolve()
    configured = os.getenv('DOCUMIND_DB')
    if configured and Path(configured).resolve()!=root/'documind.db':
        raise ValueError('Set DOCUMIND_DB to the data directory documind.db before exporting; custom metrics paths are not included.')
    files = [path for path in root.iterdir() if path.name in {'state.sqlite3','documind.db'} and path.is_file()]
    files += [path for folder in ('logs','reports') for path in (root/folder).glob('*') if path.is_file() and _safe_name(path.relative_to(root).as_posix())]
    if any(path.is_symlink() or root not in path.resolve().parents for path in files):
        raise ValueError('Backup contains an unexpected path')
    if sum(path.stat().st_size for path in files)>MAX_ARCHIVE:
        raise ValueError('Backup exceeds 128 MB. Archive older reports first.')
    payload,manifest = io.BytesIO(),{'version':1,'created':datetime.now(timezone.utc).isoformat(),'files':{},
        'excluded':['API keys','OAuth secrets','backup key','original uploads','Redis queue','Pinecone vectors']}
    with document_lock('maintenance:backup'),tempfile.TemporaryDirectory() as folder,zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = path.relative_to(root).as_posix()
            if path.suffix in {'.db','.sqlite3'}:
                destination = Path(folder)/path.name
                with closing(sqlite3.connect(path)) as source,closing(sqlite3.connect(destination)) as target:
                    source.backup(target)
                content = destination.read_bytes()
            else:
                content = path.read_bytes()
            manifest['files'][name] = {'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}
            archive.writestr(name,content)
        archive.writestr('manifest.json',json.dumps(manifest,indent=2))
    encrypted = Fernet(key()).encrypt(payload.getvalue())
    return encrypted,manifest

def inspect(content,secret):
    if len(content)>MAX_ARCHIVE*2:
        raise ValueError('Backup is too large')
    try:
        decrypted = Fernet(secret).decrypt(content)
    except (InvalidToken,ValueError,TypeError):
        raise ValueError('Backup authentication failed. Check the separate backup key.') from None
    with zipfile.ZipFile(io.BytesIO(decrypted)) as archive:
        members = archive.infolist()
        if len(members)>1000 or sum(item.file_size for item in members)>MAX_ARCHIVE*2 or len({item.filename for item in members})!=len(members):
            raise ValueError('Invalid backup archive')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('version')!=1 or set(manifest.get('files',{}))!={item.filename for item in members if item.filename!='manifest.json'}:
            raise ValueError('Backup manifest mismatch')
        files = {}
        for name,expected in manifest['files'].items():
            if not _safe_name(name):
                raise ValueError('Unsafe backup filename')
            value = archive.read(name)
            if len(value)!=expected['bytes'] or hashlib.sha256(value).hexdigest()!=expected['sha256']:
                raise ValueError('Backup checksum mismatch')
            files[name] = value
        return files,manifest

def restore(content,secret,destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Restore requires a new directory; existing data is never overwritten.')
    files,manifest = inspect(content,secret)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='documind-restore-',dir=destination.parent) as folder:
        stage = Path(folder)
        for name,value in files.items():
            path = stage/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(value)
            if path.suffix in {'.db','.sqlite3'}:
                with closing(sqlite3.connect(path)) as db:
                    if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                        raise ValueError('Restored database failed integrity checks')
        destination.mkdir()
        for child in stage.iterdir():
            child.rename(destination/child.name)
    return manifest
