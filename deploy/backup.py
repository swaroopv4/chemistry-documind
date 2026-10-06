"""Server-operator backup/restore CLI. Never prints the encryption key."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from core import backups
from core.access import Principal

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['export','verify','restore'])
    parser.add_argument('archive')
    parser.add_argument('--key-file')
    parser.add_argument('--destination')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    if args.action=='export':
        path = Path(args.archive)
        if path.exists():
            raise SystemExit('Existing archive preserved; choose a new filename.')
        payload,manifest = backups.export(Principal('server-operator','admin'))
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as handle:
            handle.write(payload)
        path.chmod(0o600)
    else:
        secret = Path(args.key_file).read_bytes().strip() if args.key_file else backups.key()
        payload = Path(args.archive).read_bytes()
        if args.action=='restore':
            if not args.destination:
                raise SystemExit('--destination must be a new directory.')
            manifest = backups.restore(payload,secret,args.destination)
        else:
            _,manifest = backups.inspect(payload,secret)
    print(f"{args.action} completed: {len(manifest['files'])} verified files. Credentials and remote vectors excluded.")
