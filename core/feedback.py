"""Pseudonymous feedback belongs to an issued response and its signed-in owner."""
import json
import time
import uuid
from core.access import require_admin
from phases.phase3_hard.storage import connect
from phases.phase3_hard.guardrails import redact_pii

def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS chat_responses (id TEXT PRIMARY KEY, actor TEXT NOT NULL, created REAL NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, sources TEXT NOT NULL, status TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS feedback (response_id TEXT PRIMARY KEY, actor TEXT NOT NULL, vote TEXT NOT NULL, note TEXT NOT NULL, updated REAL NOT NULL)')

def issue(principal,result):
    identity = str(uuid.uuid4())
    with connect() as db:
        _schema(db)
        db.execute('INSERT INTO chat_responses VALUES (?,?,?,?,?,?,?)',(identity,principal.audit_id,time.time(),
            redact_pii(result.query)[0][:4000],redact_pii(result.answer)[0][:12000],
            json.dumps([{k:s.get(k,'') for k in ('doc_name','locator')} for s in result.sources]),result.status))
        db.execute('DELETE FROM chat_responses WHERE created<? OR id NOT IN (SELECT id FROM chat_responses ORDER BY created DESC LIMIT 10000)',(time.time()-90*86400,))
        db.execute('DELETE FROM feedback WHERE response_id NOT IN (SELECT id FROM chat_responses)')
    return identity

def submit(principal,identity,vote,note=''):
    if vote not in {'helpful','incorrect','missing_information'} or not isinstance(note,str) or len(note)>500:
        raise ValueError('Invalid feedback')
    with connect() as db:
        _schema(db)
        row = db.execute('SELECT actor FROM chat_responses WHERE id=?',(identity,)).fetchone()
        if not row or row['actor']!=principal.audit_id:
            raise PermissionError('Feedback is available only for your own recent answers.')
        db.execute('INSERT OR REPLACE INTO feedback VALUES (?,?,?,?,?)',(identity,principal.audit_id,vote,redact_pii(note)[0],time.time()))

def recent(principal):
    require_admin(principal)
    with connect() as db:
        _schema(db)
        return [dict(row) for row in db.execute('SELECT f.*,r.question,r.answer,r.sources,r.status FROM feedback f JOIN chat_responses r ON r.id=f.response_id ORDER BY updated DESC LIMIT 500')]
