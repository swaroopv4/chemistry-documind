"""Independent, persistent BM25 index shared by the app and ingestion worker."""
from contextlib import contextmanager,nullcontext
import hashlib
import json
import re
import tempfile
import time
import unicodedata
import uuid

from phases.phase3_hard.storage import connect
from phases.phase3_hard.guardrails import redact_pii

TOKEN_VERSION = 'chem-tokens-v1'
STOPWORDS = set('a an and are as at be been by can could do does for from how i if in into is it its me of on or our please reported show tell than that the their these this to us was were what when where which who why with would you your'.split())
ELEMENTS = set('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split())
WORDS = re.compile(r'[^\W_]+(?:[-.][^\W_]+)*', re.UNICODE)


def terms(text):
    """Encode tokens for safe FTS syntax; preserve CO versus Co and H2O/C1/O1."""
    result = []
    for word in WORDS.findall(unicodedata.normalize('NFKC', text)):
        if word.casefold() in STOPWORDS:
            continue
        parts = re.findall(r'([A-Z][a-z]?)(\d*)', word)
        formula = bool(parts) and ''.join(symbol+count for symbol,count in parts) == word and all(symbol in ELEMENTS for symbol,count in parts)
        value = ('chem:' + word) if formula else ('word:' + word.casefold())
        result.append('t' + value.encode('utf-8').hex())
    return result


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS keyword_chunks (id INTEGER PRIMARY KEY, vector_id TEXT UNIQUE NOT NULL, doc_name TEXT NOT NULL, tokens TEXT NOT NULL, metadata TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS keyword_doc ON keyword_chunks(doc_name)')
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS keyword_fts USING fts5(tokens, content='keyword_chunks', content_rowid='id')")
    db.execute("CREATE TRIGGER IF NOT EXISTS keyword_insert AFTER INSERT ON keyword_chunks BEGIN INSERT INTO keyword_fts(rowid,tokens) VALUES (new.id,new.tokens); END")
    db.execute("CREATE TRIGGER IF NOT EXISTS keyword_delete AFTER DELETE ON keyword_chunks BEGIN INSERT INTO keyword_fts(keyword_fts,rowid,tokens) VALUES ('delete',old.id,old.tokens); END")
    db.execute('CREATE TABLE IF NOT EXISTS keyword_documents (name TEXT PRIMARY KEY, changed REAL NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS keyword_state (id INTEGER PRIMARY KEY, synced REAL, vectors INTEGER, token_version TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS keyword_rebuild_lock (id INTEGER PRIMARY KEY, token TEXT NOT NULL, expires REAL NOT NULL)')


def safe_metadata(metadata):
    text = redact_pii(str(metadata.get('text', '')))[0]
    return {'text': text, 'doc_name': metadata.get('doc_name', ''),
            'page_num': metadata.get('page_num', 0), 'chunk_index': metadata.get('chunk_index', 0),
            'locator': redact_pii(str(metadata.get('locator', f"page {metadata.get('page_num',0)}")))[0],
            'file_type': metadata.get('file_type', 'pdf'),
            **({'ocr':True,'ocr_confidence':metadata.get('ocr_confidence',0.)} if metadata.get('ocr') else {})}


def text_digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _insert(db, vector_id, metadata):
    metadata = safe_metadata(metadata)
    if not metadata['doc_name'] or not metadata['text'].strip():
        return False
    db.execute('INSERT INTO keyword_chunks(vector_id,doc_name,tokens,metadata) VALUES (?,?,?,?)',
               (vector_id, metadata['doc_name'], ' '.join(terms(metadata['text'])), json.dumps(metadata)))
    return True


def remove_document(name):
    with connect() as db:
        _schema(db)
        db.execute('DELETE FROM keyword_chunks WHERE doc_name=?', (name,))
        db.execute('INSERT OR REPLACE INTO keyword_documents VALUES (?,?)', (name,time.time()))


def replace_document(name, chunks):
    with connect() as db:
        _schema(db)
        db.execute('DELETE FROM keyword_chunks WHERE doc_name=?', (name,))
        for chunk in chunks:
            if chunk.doc_name != name:
                raise ValueError('Unexpected document in keyword ingestion')
            _insert(db, f'{name}_{chunk.chunk_index}', chunk.to_pinecone_metadata())
        db.execute('INSERT OR REPLACE INTO keyword_documents VALUES (?,?)', (name,time.time()))


def coverage(question, text):
    query, found = set(terms(question)), set(terms(text))
    if not query:
        return 0.
    chemical = {term for term in query if bytes.fromhex(term[1:]).decode('utf-8').startswith('chem:')}
    if chemical and not chemical.intersection(found):
        return 0.
    return len(query.intersection(found))/len(query)


def search(question, limit=20, filter_doc=None, allowed_docs=None, connection=None):
    query = list(dict.fromkeys(terms(question)))[:64]
    if not query or allowed_docs == []:
        return []
    clauses, args = ['keyword_fts MATCH ?'], [' OR '.join(query)]
    if filter_doc:
        clauses.append('k.doc_name=?')
        args.append(filter_doc)
    if allowed_docs is not None:
        clauses.append('k.doc_name IN (SELECT value FROM json_each(?))')
        args.append(json.dumps(allowed_docs))
    with (connect() if connection is None else nullcontext(connection)) as db:
        _schema(db)
        rows = db.execute('SELECT k.vector_id,k.metadata,bm25(keyword_fts) AS distance FROM keyword_fts JOIN keyword_chunks k ON k.id=keyword_fts.rowid WHERE '+
                          ' AND '.join(clauses)+' ORDER BY distance,k.vector_id LIMIT ?', (*args,min(1000,limit*5))).fetchall()
    result = []
    for row in rows:
        metadata = json.loads(row['metadata'])
        matched = coverage(question, metadata['text'])
        if matched < .5:
            continue
        result.append({**metadata, 'id':row['vector_id'], 'score':0.,
                       'bm25_score':-row['distance'], 'lexical_coverage':matched,
                       '_keyword_digest':text_digest(metadata['text'])})
        if len(result) >= limit:
            break
    return result


def status():
    with connect() as db:
        _schema(db)
        count = db.execute('SELECT count(*),count(DISTINCT doc_name) FROM keyword_chunks').fetchone()
        row = db.execute('SELECT synced,vectors FROM keyword_state WHERE id=1').fetchone()
    return {'chunks':count[0], 'documents':count[1], 'last_full_sync':row['synced'] if row else None}


@contextmanager
def _rebuild_lock():
    token = uuid.uuid4().hex
    with connect() as db:
        _schema(db)
        db.execute('DELETE FROM keyword_rebuild_lock WHERE expires<?', (time.time(),))
        if db.execute('SELECT 1 FROM keyword_rebuild_lock').fetchone():
            raise ValueError('A keyword rebuild is already running. Try again later.')
        db.execute('INSERT INTO keyword_rebuild_lock VALUES (1,?,?)', (token,time.time()+3600))
    try:
        yield
    finally:
        with connect() as db:
            db.execute('DELETE FROM keyword_rebuild_lock WHERE token=?', (token,))


def rebuild_from_pinecone(principal, index=None, max_vectors=100000):
    """Read vectors without re-embedding; atomically swap only after a full scan.

    Preserve ingestions/deletions committed while the remote scan was running.
    Failed/over-limit scans retain the previous keyword corpus.
    """
    from core.access import require_admin
    from core.vector_store import get_index, NAMESPACE, vector_ids
    from core import catalog, redis_cache, audit
    from phases.phase3_hard.cache import corpus_update
    require_admin(principal)
    index = get_index() if index is None else index
    with _rebuild_lock(), corpus_update(), tempfile.TemporaryFile(mode='w+t',encoding='utf-8') as snapshot:
        started, scanned, ids = time.time(), 0, set()
        for batch in index.list(namespace=NAMESPACE):
            batch = vector_ids(batch)
            scanned += len(batch)
            if scanned > max_vectors:
                raise ValueError(f'Rebuild exceeded {max_vectors:,} vectors; the previous keyword index was retained.')
            fetched = index.fetch(ids=batch,namespace=NAMESPACE)
            for vector_id, vector in fetched.vectors.items():
                metadata = safe_metadata(vector.metadata or {})
                if vector_id in ids or not metadata['doc_name'] or not metadata['text'].strip():
                    continue
                ids.add(vector_id)
                snapshot.write(json.dumps([vector_id,metadata])+'\n')
        snapshot.seek(0)
        with connect() as db:
            _schema(db)
            db.execute('DELETE FROM keyword_chunks WHERE doc_name NOT IN (SELECT name FROM keyword_documents WHERE changed>=?)',(started,))
            changed = {row[0] for row in db.execute('SELECT name FROM keyword_documents WHERE changed>=?',(started,))}
            for line in snapshot:
                vector_id, metadata = json.loads(line)
                if metadata['doc_name'] not in changed:
                    _insert(db,vector_id,metadata)
            db.execute('INSERT OR REPLACE INTO keyword_state VALUES (1,?,?,?)',(time.time(),scanned,TOKEN_VERSION))
            names = [row[0] for row in db.execute('SELECT DISTINCT doc_name FROM keyword_chunks')]
        catalog.sync_names(names)  # Existing vectors are discovered privately, never auto-published.
        with connect() as db:
            db.execute('UPDATE documents SET chunks=(SELECT count(*) FROM keyword_chunks WHERE keyword_chunks.doc_name=documents.name)')
    redis_cache.clear_answers()
    result = {**status(),'scanned_vectors':scanned}
    audit.record(principal,'keyword_index_rebuilt',result)
    return result
