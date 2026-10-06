from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from phases.phase3_hard.storage import data_dir

# Standard on-demand rates per million tokens, verified 2026-10-05.
# Unknown models stay unpriced until explicitly configured.
PRICES = {"openai/gpt-oss-20b": (0.075, 0.30),
          "openai/gpt-oss-120b": (0.15, 0.60)}


def enabled() -> bool:
    return os.getenv("OBSERVABILITY_ENABLED", "true").lower() in {"true", "1", "yes"}


@contextmanager
def _db():
    configured_path = os.getenv("DOCUMIND_DB")
    path = Path(configured_path) if configured_path else data_dir() / "documind.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, model TEXT,
                input_tokens INTEGER, output_tokens INTEGER, cached_input_tokens INTEGER,
                cost_usd REAL, latency_ms REAL, cache_hit INTEGER, question TEXT,
                token_source TEXT, status TEXT, purpose TEXT DEFAULT 'qa');
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, model TEXT, purpose TEXT,
                total_tokens INTEGER, cost_usd REAL, latency_ms REAL,
                token_source TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS retrievals (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, top_k INTEGER,
                chunk_count INTEGER, avg_score REAL, latency_ms REAL,
                doc_name TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS ingestions (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, doc_name TEXT,
                chunk_count INTEGER, page_count INTEGER, total_tokens INTEGER,
                duration_ms REAL, status TEXT);
            CREATE INDEX IF NOT EXISTS llm_ts ON llm_calls(ts);
            CREATE INDEX IF NOT EXISTS embedding_ts ON embeddings(ts);
            CREATE INDEX IF NOT EXISTS retrieval_ts ON retrievals(ts);
            CREATE INDEX IF NOT EXISTS ingestion_ts ON ingestions(ts);
        """)
        if 'purpose' not in {row[1] for row in db.execute('PRAGMA table_info(llm_calls)')}:
            try:
                db.execute("ALTER TABLE llm_calls ADD COLUMN purpose TEXT DEFAULT 'qa'")
            except sqlite3.OperationalError:
                if 'purpose' not in {row[1] for row in db.execute('PRAGMA table_info(llm_calls)')}:
                    raise
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with _db():
        pass


def _rate(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Token prices must be finite and nonnegative")
    return value


def estimate_cost(model, inp, out, cached_input_tokens=0):
    if inp is None or out is None:
        return None
    prices = dict(PRICES)
    try:
        prices.update(json.loads(os.getenv("GROQ_PRICES_JSON", "{}")))
        if model not in prices:
            return None
        input_rate, output_rate = map(_rate, prices[model])
    except (ValueError, TypeError, AttributeError):
        return None
    # Groq's provider prompt cache discounts input tokens by 50%.
    # This is independent of DocuMind's semantic answer cache.
    cached = min(max(cached_input_tokens, 0), inp)
    return ((inp - cached * .5) * input_rate + out * output_rate) / 1_000_000


def embedding_cost(tokens):
    if tokens is None:
        return None
    try:
        return tokens * _rate(os.getenv("PINECONE_EMBEDDING_USD_PER_MILLION", ".16")) / 1_000_000
    except (ValueError, TypeError):
        return None


def _insert(table, values):
    values = {"ts": time.time(), **values}
    with _db() as db:
        db.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
                   tuple(values.values()))


def log_llm_call(**values):
    _insert("llm_calls", values)


def log_embedding(**values):
    _insert("embeddings", values)


def log_retrieval(**values):
    _insert("retrievals", values)


def log_ingestion(**values):
    _insert("ingestions", values)


def _cutoff(days):
    if not isinstance(days, int) or not 1 <= days <= 365:
        raise ValueError("Days must be an integer between 1 and 365")
    return time.time() - days * 86400


def get_summary(days=7):
    cutoff = _cutoff(days)
    with _db() as db:
        llm = dict(db.execute("""SELECT COUNT(*) AS answer_events,
            COALESCE(SUM(cache_hit=0),0) AS llm_calls,
            COALESCE(SUM(cache_hit),0) AS cache_hits,
            COALESCE(SUM(input_tokens+output_tokens),0) AS llm_tokens,
            COALESCE(SUM(cost_usd),0) AS llm_cost_usd,
            COALESCE(AVG(CASE WHEN cache_hit=0 THEN latency_ms END),0) AS avg_latency_ms,
            COALESCE(SUM(cost_usd IS NULL),0) AS unpriced_llm,
            COALESCE(SUM(token_source='estimated'),0) AS estimated_llm,
            COALESCE(SUM(status!='success'),0) AS failed_llm
            FROM llm_calls WHERE ts>=?""", (cutoff,)).fetchone())
        embed = dict(db.execute("""SELECT COUNT(*) AS embedding_calls,
            COALESCE(SUM(total_tokens),0) AS embedding_tokens,
            COALESCE(SUM(cost_usd),0) AS embedding_cost_usd,
            COALESCE(SUM(cost_usd IS NULL),0) AS unpriced_embeddings,
            COALESCE(SUM(token_source='estimated'),0) AS estimated_embeddings
            FROM embeddings WHERE ts>=?""", (cutoff,)).fetchone())
        ops = dict(db.execute("""SELECT COUNT(*) AS ingestions,
            COALESCE(SUM(status='success'),0) AS documents_ingested,
            COALESCE(AVG(duration_ms),0) AS avg_ingestion_ms
            FROM ingestions WHERE ts>=?""", (cutoff,)).fetchone())
        retrieval = dict(db.execute("""SELECT COUNT(*) AS retrievals,
            COALESCE(AVG(latency_ms),0) AS avg_retrieval_ms
            FROM retrievals WHERE ts>=?""", (cutoff,)).fetchone())
    result = {**llm, **embed, **ops, **retrieval}
    result["cost_usd"] = result["llm_cost_usd"] + result["embedding_cost_usd"]
    result["cache_hit_rate"] = result["cache_hits"] / result["answer_events"] if result["answer_events"] else 0.
    result["unpriced_events"] = result["unpriced_llm"] + result["unpriced_embeddings"]
    return result


def get_daily_cost(days=7):
    with _db() as db:
        return [dict(row) for row in db.execute("""SELECT
            strftime('%Y-%m-%d', ts, 'unixepoch') AS day,
            COALESCE(SUM(cost_usd),0) AS known_cost_usd,
            SUM(cost_usd IS NULL) AS unpriced_events,
            SUM(model_call) AS llm_calls, SUM(cache_hit) AS cache_hits,
            SUM(embedding_call) AS embedding_calls,
            SUM(tokens) AS total_tokens FROM (
                SELECT ts,cost_usd,cache_hit=0 AS model_call,cache_hit,0 AS embedding_call,
                    COALESCE(input_tokens,0)+COALESCE(output_tokens,0) AS tokens FROM llm_calls
                UNION ALL SELECT ts,cost_usd,0,0,1,COALESCE(total_tokens,0) FROM embeddings
            ) WHERE ts>=? GROUP BY day ORDER BY day""", (_cutoff(days),))]


def get_latency_series(days=7):
    with _db() as db:
        return [dict(row) for row in db.execute("""SELECT
            strftime('%Y-%m-%d',ts,'unixepoch') AS day, AVG(latency_ms) AS avg_latency_ms
            FROM llm_calls WHERE ts>=? AND cache_hit=0 GROUP BY day ORDER BY day""", (_cutoff(days),))]


# Spelling shown in the tutorial's UI.
get_daily_costs = get_daily_cost


def get_recent_calls(limit=20, days=7):
    return _recent("llm_calls", limit, days, ", input_tokens+output_tokens AS total_tokens")


def _recent(table, limit=20, days=7, extra=""):
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000")
    with _db() as db:
        return [dict(row) for row in db.execute(
            f"SELECT *{extra} FROM {table} WHERE ts>=? ORDER BY ts DESC,id DESC LIMIT ?",
            (_cutoff(days), limit))]


def get_recent_operations(days=7):
    return {table: _recent(table, days=days) for table in ("embeddings", "retrievals", "ingestions")}
