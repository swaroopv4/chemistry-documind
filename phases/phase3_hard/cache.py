from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid

from .storage import connect


@dataclass
class CacheHit:
    answer: str
    sources: list[dict]
    similarity: float
    question: str


def enabled() -> bool:
    return os.getenv("CACHE_ENABLED", "true").lower() in {"true", "yes", "1"}


def current_scope(top_k: int, filter_doc: str | None, audience="admin") -> str | None:
    if not enabled():
        return None
    try:
        from core.settings import get_settings
        settings = get_settings()
        if settings['cache_strategy'] == 'disabled':
            return None
        from core.embeddings import EMBEDDING_MODEL, EMBEDDING_DIM
        from core.vector_store import INDEX_NAME, NAMESPACE
        from core.generation import LLM_MODEL, SYSTEM_PROMPT
        from core.retrieval import mode, VERSION
        with connect() as db:
            db.execute("DELETE FROM mutations WHERE expires < ?", (time.time(),))
            if db.execute("SELECT 1 FROM mutations LIMIT 1").fetchone():
                return None
            revision = db.execute("SELECT revision FROM corpus WHERE id=1").fetchone()[0]
        config = [revision, top_k, filter_doc, INDEX_NAME, NAMESPACE, EMBEDDING_MODEL,
                  EMBEDDING_DIM, LLM_MODEL, SYSTEM_PROMPT,
                  os.getenv("GUARDRAILS_ENABLED", "true"), os.getenv("MIN_RETRIEVAL_SCORE", "0.25"),
                  os.getenv("GROQ_API_KEY", ""), os.getenv("PINECONE_API_KEY", ""),
                  audience, settings, "uci-citations-memory-v2", mode(), VERSION]
        return hashlib.sha256(json.dumps(config).encode()).hexdigest()
    except (OSError, sqlite3.Error):
        return None  # monitoring/cache failure must not prevent normal retrieval


@contextmanager
def corpus_update():
    """Disable cache during writes; invalidate after success or partial failure."""
    token = uuid.uuid4().hex
    with connect() as db:
        db.execute("UPDATE corpus SET revision=revision+1 WHERE id=1")
        db.execute("INSERT INTO mutations VALUES (?, ?)", (token, time.time() + 3600))
        db.execute("DELETE FROM cache")
    try:
        yield
    finally:
        with connect() as db:
            db.execute("UPDATE corpus SET revision=revision+1 WHERE id=1")
            # Pinecone writes are eventually consistent. Briefly suppress
            # caching while newly written/deleted vectors become visible.
            delay = max(0., float(os.getenv("CACHE_INVALIDATION_DELAY_SECONDS", "30")))
            if delay:
                db.execute("UPDATE mutations SET expires=? WHERE token=?", (time.time() + delay, token))
            else:
                db.execute("DELETE FROM mutations WHERE token=?", (token,))
            db.execute("DELETE FROM cache")


def clear_cache() -> None:
    with connect() as db:
        db.execute("UPDATE corpus SET revision=revision+1 WHERE id=1")
        db.execute("DELETE FROM cache")


def _signature(question: str) -> tuple:
    return (tuple(re.findall(r"[-+]?\d+(?:\.\d+)?", question)),
            bool(re.search(r"\b(?:not|no|without|except)\b|n['’]t\b", question, re.I)))


def cache_lookup(embedding: list[float], question: str, scope: str | None) -> CacheHit | None:
    if scope is None:
        return None
    threshold = float(os.getenv("CACHE_SIMILARITY_THRESHOLD", "0.92"))
    if not 0 <= threshold <= 1:
        raise ValueError("CACHE_SIMILARITY_THRESHOLD must be between 0 and 1")
    from core.settings import get_settings
    settings = get_settings()
    cutoff = time.time() - settings['cache_ttl']
    norm = math.sqrt(sum(x*x for x in embedding))
    best = None
    best_id = None
    if not norm:
        return None
    try:
        with connect() as db:
            rows = db.execute("SELECT * FROM cache WHERE scope=? AND created>=?", (scope, cutoff)).fetchall()
        for row in rows:
            if _signature(question) != _signature(row["question"]):
                continue
            sources = json.loads(row["sources"])
            # Chemical identifiers and atom/site questions are often dangerously
            # similar: require an exact normalized question for structural files.
            if any(s.get("file_type") in {"cif", "mol2"} for s in sources) and question.casefold() != row["question"].casefold():
                continue
            vector = json.loads(row["embedding"])
            if len(vector) != len(embedding):
                continue
            denominator = norm * math.sqrt(sum(x*x for x in vector))
            similarity = sum(x*y for x, y in zip(vector, embedding)) / denominator if denominator else 0
            if similarity >= threshold and (best is None or similarity > best.similarity):
                best = CacheHit(row["answer"], sources, min(1., similarity), row["question"])
                best_id = row['id']
        if best_id:
            with connect() as db:
                db.execute("CREATE TABLE IF NOT EXISTS cache_usage (id TEXT PRIMARY KEY,last_used REAL,hits INTEGER)")
                db.execute("INSERT INTO cache_usage VALUES (?,?,1) ON CONFLICT(id) DO UPDATE SET last_used=excluded.last_used,hits=hits+1", (best_id, time.time()))
        return best
    except (OSError, sqlite3.Error, json.JSONDecodeError):
        return None


def cache_store(embedding: list[float], question: str, answer: str, sources: list[dict],
                scope: str | None, top_k: int, filter_doc: str | None, audience="admin") -> None:
    if scope is None or not sources:
        return
    try:
        # A query started before an ingestion must not populate the new cache.
        if scope != current_scope(top_k, filter_doc, audience):
            return
        from core.settings import get_settings
        settings = get_settings()
        cache_id = hashlib.sha256((scope + question).encode()).hexdigest()
        with connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (cache_id, scope, question, json.dumps(embedding), answer, json.dumps(sources), time.time()))
            db.execute("CREATE TABLE IF NOT EXISTS cache_usage (id TEXT PRIMARY KEY,last_used REAL,hits INTEGER)")
            db.execute("INSERT OR IGNORE INTO cache_usage VALUES (?,?,1)", (cache_id,time.time()))
            order = {'fifo': 'cache.created DESC', 'lru': 'COALESCE(cache_usage.last_used,cache.created) DESC',
                     'lfu': 'COALESCE(cache_usage.hits,0) DESC,COALESCE(cache_usage.last_used,cache.created) DESC'}
            if settings['cache_strategy'] != 'ttl':
                db.execute("DELETE FROM cache WHERE id NOT IN (SELECT cache.id FROM cache LEFT JOIN cache_usage ON cache.id=cache_usage.id ORDER BY " + order.get(settings['cache_strategy'],order['lru']) + " LIMIT ?)", (settings['cache_capacity'],))
            db.execute("DELETE FROM cache WHERE created<?", (time.time()-settings['cache_ttl'],))
            db.execute("DELETE FROM cache_usage WHERE id NOT IN (SELECT id FROM cache)")
    except (OSError, sqlite3.Error):
        pass


def cache_stats() -> dict:
    from core.settings import get_settings
    settings = get_settings()
    with connect() as db:
        count = db.execute("SELECT count(*) FROM cache WHERE created>=?", (time.time() - settings['cache_ttl'],)).fetchone()[0]
    return {"entries": count, "threshold": float(os.getenv("CACHE_SIMILARITY_THRESHOLD", "0.92")), **settings}
