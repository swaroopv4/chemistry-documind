"""Document policy is enforced before retrieval and before displaying answers."""
import hashlib
import re
import time
from phases.phase3_hard.storage import connect


def _schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS documents (
        name TEXT PRIMARY KEY, visibility TEXT NOT NULL DEFAULT 'private',
        label TEXT NOT NULL, chunks INTEGER DEFAULT 0, updated REAL)""")
    columns = {row[1] for row in db.execute('PRAGMA table_info(documents)')}
    if 'ocr_pages' not in columns:
        db.execute('ALTER TABLE documents ADD COLUMN ocr_pages INTEGER NOT NULL DEFAULT 0')


def list_documents():
    with connect() as db:
        _schema(db)
        return [dict(row) for row in db.execute("SELECT * FROM documents ORDER BY name")]


def sync_names(names):
    with connect() as db:
        _schema(db)
        for name in names:
            label = "Document " + hashlib.sha256(name.encode()).hexdigest()[:8]
            db.execute("INSERT OR IGNORE INTO documents(name,label,updated) VALUES (?,?,?)", (name, label, time.time()))


def set_policy(name, visibility, label, principal):
    from core.access import require_admin
    from core.audit import record
    from phases.phase3_hard.guardrails import redact_pii
    require_admin(principal)
    if visibility not in {"private", "published"} or not name:
        raise ValueError("Invalid document policy")
    label = redact_pii(label.strip())[0]
    if not label or len(label) > 100:
        raise ValueError("Student source label must contain 1–100 characters")
    sync_names([name])
    with connect() as db:
        _schema(db)
        if visibility=='published' and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_versions'").fetchone():
            version = db.execute('SELECT state FROM document_versions WHERE name=?',(name,)).fetchone()
            if version and version['state']!='success':
                raise ValueError('Only successfully ingested versions can be published. Resolve the document job first.')
        db.execute("UPDATE documents SET visibility=?, label=?, updated=? WHERE name=?",
                   (visibility, label, time.time(), name))
    from phases.phase3_hard.cache import clear_cache
    clear_cache()
    from core.redis_cache import clear_answers
    clear_answers()
    record(principal, "document_policy", {"document": name, "visibility": visibility, "label": label})


def record_ingestion(name, chunks,ocr_pages=0):
    # Never publish implicitly. A file unknown to the catalog starts private.
    sync_names([name])
    with connect() as db:
        _schema(db)
        db.execute("UPDATE documents SET chunks=?,updated=?,ocr_pages=? WHERE name=?", (chunks, time.time(),ocr_pages,name))


def published():
    return {row["name"]: row["label"] for row in list_documents() if row["visibility"] == "published"}


def student_sources(sources):
    from phases.phase3_hard.guardrails import redact_pii
    allowed = published()
    result = []
    for source in sources:
        original = source.get("_internal_doc_name", source.get("doc_name", ""))
        if original not in allowed:
            continue
        locator = source.get('locator','')
        if not isinstance(locator,str) or not re.fullmatch(r'(?:page|slide) \d+(?: notes)?',locator):
            try:
                locator = f"passage {max(0,int(source.get('chunk_index',0)))+1}"
            except (ValueError,TypeError):
                locator = 'passage'
        result.append({**source, "_internal_doc_name": original, "doc_name": allowed[original],
                       "text": redact_pii(source.get("text", ""))[0],
                       "locator": locator})
    return result


def sources_allowed(sources):
    allowed = published()
    return bool(sources) and all(source.get("_internal_doc_name", source.get("doc_name")) in allowed
        and source.get("doc_name") == allowed[source.get("_internal_doc_name", source.get("doc_name"))]
        for source in sources)


def remove_policy(name, principal):
    from core.access import require_admin
    require_admin(principal)
    with connect() as db:
        _schema(db)
        db.execute("DELETE FROM documents WHERE name=?", (name,))
