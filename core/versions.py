"""File hashes, immutable named versions and cross-process ingestion leases."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time
import uuid
from core.settings import get_settings
from phases.phase3_hard.storage import connect


class ExistingUpload(ValueError):
    def __init__(self,row):
        self.document,self.job_id,self.state = row['name'],row['job_id'],row['state']
        super().__init__(f"This file and parsing configuration already exist as {self.document} ({self.state}).")


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS document_versions (name TEXT PRIMARY KEY, family TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT, signature TEXT, job_id TEXT, state TEXT NOT NULL, created REAL NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS version_hash ON document_versions(sha256,signature,state)')
    db.execute('CREATE TABLE IF NOT EXISTS document_locks (name TEXT PRIMARY KEY, token TEXT NOT NULL, expires REAL NOT NULL)')


def signature(size,overlap):
    settings = get_settings()
    return hashlib.sha256(json.dumps([size,overlap,settings['ocr_enabled'],settings['ocr_max_pages'],'parser-ocr-v2']).encode()).hexdigest()


def plan(name,content,size,overlap,job_id=None):
    from core import catalog
    from core.batch import validate_batch
    validate_batch([(name,content)])
    if not isinstance(size,int) or not 1<=size<=800 or not isinstance(overlap,int) or not 0<=overlap<size:
        raise ValueError('Invalid chunk size or overlap')
    family = Path(name.replace('\\','/')).name
    digest,parse,job_id = hashlib.sha256(content).hexdigest(),signature(size,overlap),job_id or str(uuid.uuid4())
    known = {row['name'] for row in catalog.list_documents()}
    with connect() as db:
        _schema(db)
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM document_locks WHERE name='maintenance:backup' AND expires>?",(time.time(),)).fetchone():
            raise ValueError('A backup is being prepared. Please retry the upload shortly.')
        duplicate = db.execute("SELECT * FROM document_versions WHERE sha256=? AND signature=? AND state IN ('queued','processing','uncertain','success') ORDER BY created DESC LIMIT 1",(digest,parse)).fetchone()
        if duplicate:
            raise ExistingUpload(dict(duplicate))
        latest = db.execute('SELECT max(version) FROM document_versions WHERE family=?',(family,)).fetchone()[0] or (1 if family in known else 0)
        version = latest+1
        path = Path(family)
        canonical = family if version==1 else f'{path.stem}__v{version}{path.suffix}'
        while canonical in known or db.execute('SELECT 1 FROM document_versions WHERE name=?',(canonical,)).fetchone():
            version += 1
            canonical = f'{path.stem}__v{version}{path.suffix}'
        db.execute('INSERT INTO document_versions VALUES (?,?,?,?,?,?,?,?)',(canonical,family,version,digest,parse,job_id,'queued',time.time()))
        return {'name':canonical,'family':family,'version':version,'job_id':job_id}


def set_state(name,state):
    with connect() as db:
        _schema(db)
        db.execute('UPDATE document_versions SET state=? WHERE name=?',(state,name))


def history(principal):
    from core.access import require_admin
    require_admin(principal)
    with connect() as db:
        _schema(db)
        return [dict(row) for row in db.execute('SELECT * FROM document_versions ORDER BY created DESC LIMIT 1000')]


def reconcile_failure(name,principal):
    """Never assume that a missing/PENDING Redis result means a job failed."""
    from core.access import require_admin
    from core.pipeline import get_ingest_status
    from core.audit import record
    require_admin(principal)
    row = next((row for row in history(principal) if row['name']==name),None)
    if not row or row['state'] not in {'queued','processing','uncertain'}:
        raise ValueError('Select a pending document version.')
    status = get_ingest_status(row['job_id'])
    if status.state not in {'FAILURE','REVOKED'}:
        raise ValueError('The job has no confirmed terminal failure. Keep tracking it; its reservation was preserved.')
    with document_lock(name):
        set_state(name,'failed')
    record(principal,'document_job_failure_resolved',{'document':name,'job_id':row['job_id']})


def stage_private(planned,principal):
    from core import catalog
    rows = catalog.list_documents()
    names = {planned['family'],planned['name']}
    with connect() as db:
        _schema(db)
        names.update(row[0] for row in db.execute('SELECT name FROM document_versions WHERE family=?',(planned['family'],)))
    for row in rows:
        if row['name'] in names:
            catalog.set_policy(row['name'],'private',row['label'],principal)
    catalog.sync_names([planned['name']])


@contextmanager
def document_lock(name):
    token = uuid.uuid4().hex
    with connect() as db:
        _schema(db)
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM document_locks WHERE expires<?',(time.time(),))
        if name=='maintenance:backup':
            if db.execute('SELECT 1 FROM document_locks LIMIT 1').fetchone() or db.execute("SELECT 1 FROM document_versions WHERE state IN ('queued','processing','uncertain') LIMIT 1").fetchone():
                raise ValueError('Finish or resolve pending document jobs before creating a backup.')
        elif db.execute("SELECT 1 FROM document_locks WHERE name='maintenance:backup'").fetchone():
            raise ValueError('A backup is being prepared. Please retry shortly.')
        if db.execute('SELECT 1 FROM document_locks WHERE name=?',(name,)).fetchone():
            raise ValueError('Another operation is processing this document. Wait for it to finish.')
        db.execute('INSERT INTO document_locks VALUES (?,?,?)',(name,token,time.time()+3600))
    try:
        yield
    finally:
        with connect() as db:
            db.execute('DELETE FROM document_locks WHERE name=? AND token=?',(name,token))


def prepare_path(path,size,overlap,job_id=None):
    path = Path(path)
    if not path.is_file():
        return {'name':path.name,'version':0} # Parser reports missing files; SDK-boundary tests can mock it.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with connect() as db:
        _schema(db)
        row = db.execute('SELECT * FROM document_versions WHERE name=?',(path.name,)).fetchone()
    if row and row['sha256']==digest and row['signature']==signature(size,overlap):
        if row['state']=='success' or job_id is None:
            raise ExistingUpload(dict(row))
        if job_id and row['job_id']!=job_id:
            raise ValueError('This ingestion job was superseded. Its write was rejected.')
        return dict(row)
    return plan(path.name,path.read_bytes(),size,overlap,job_id)
