import json
import time
from phases.phase3_hard.storage import connect
from phases.phase3_hard.guardrails import redact_pii

MAX_ENTRIES = 20000


def _schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, ts REAL, actor TEXT, event TEXT, details TEXT)")


def record(principal, event, details=None):
    serialized = redact_pii(json.dumps(details or {}, ensure_ascii=False))[0]
    with connect() as db:
        _schema(db)
        db.execute("INSERT INTO audit(ts,actor,event,details) VALUES (?,?,?,?)",
                   (time.time(), principal.audit_id, event, serialized))
        db.execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT ?)", (MAX_ENTRIES,))


def recent(principal, limit=100):
    """Export the requested newest entries, independently of the displayed page."""
    from core.access import require_admin
    require_admin(principal)
    with connect() as db:
        _schema(db)
        return [dict(row) for row in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(max(int(limit),1),MAX_ENTRIES),))]


def page(principal, number=0, page_size=100, through_id=None):
    """Keep a browsing snapshot stable when new events arrive between pages."""
    from core.access import require_admin
    require_admin(principal)
    size = min(max(int(page_size),1),1000)
    with connect() as db:
        _schema(db)
        latest = db.execute('SELECT COALESCE(MAX(id),0) FROM audit').fetchone()[0]
        anchor = latest if through_id is None else min(max(int(through_id),0),latest)
        total = db.execute('SELECT COUNT(*) FROM audit WHERE id<=?',(anchor,)).fetchone()[0]
        pages = max(1,(total+size-1)//size)
        number = min(max(int(number),0),pages-1)
        rows = [dict(row) for row in db.execute(
            'SELECT * FROM audit WHERE id<=? ORDER BY id DESC LIMIT ? OFFSET ?',
            (anchor,size,number*size))]
    return {'records':rows,'total':total,'number':number,'pages':pages,'through_id':anchor}
