"""Shared, validated runtime settings. Stored on the app/worker data volume."""
import json
import os
from phases.phase3_hard.storage import connect

DEFAULTS = {"cache_strategy": "lru", "cache_capacity": 100,
            "cache_ttl": 3600, "student_semantic_cache": False,
            "student_top_k": 5, "max_question_chars": 4000,
            "groq_requests_minute": 18, "groq_requests_day": 500,
            "groq_tokens_minute": 7000, "groq_tokens_day": 150000,
            "provider_concurrency": 2, "provider_timeout": 45, "answer_tokens": 2048,
            "context_tokens": 2500, "embedding_tokens_day": 200000,
            "ocr_enabled": True, "ocr_max_pages": 20, "conversation_ttl": 600}


def get_settings():
    values = {**DEFAULTS, "cache_ttl": int(os.getenv("CACHE_TTL_SECONDS", "3600"))}
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS app_settings (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        row = db.execute("SELECT payload FROM app_settings WHERE id=1").fetchone()
    if row:
        values.update(json.loads(row[0]))
    return validate(values)


def validate(values):
    if set(values) != set(DEFAULTS):
        raise ValueError("Unrecognized settings")
    if values["cache_strategy"] not in {"lru", "lfu", "fifo", "ttl", "disabled"}:
        raise ValueError("Unknown cache strategy")
    for key, low, high in (("cache_capacity", 1, 10000), ("cache_ttl", 60, 604800),
                           ("student_top_k", 1, 15), ("max_question_chars", 100, 8000)):
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"Invalid {key}")
    if not isinstance(values["student_semantic_cache"], bool):
        raise ValueError("Invalid semantic-cache setting")
    if not isinstance(values['ocr_enabled'],bool):
        raise ValueError('Invalid OCR setting')
    for key,low,high in (('groq_requests_minute',1,1000),('groq_requests_day',1,100000),
                        ('groq_tokens_minute',1024,1000000),('groq_tokens_day',2048,10000000),
                        ('provider_concurrency',1,8),('provider_timeout',10,120),
                        ('answer_tokens',512,4096),('context_tokens',800,6000),
                        ('embedding_tokens_day',1000,10000000),('ocr_max_pages',1,50),('conversation_ttl',60,3600)):
        if isinstance(values[key],bool) or not isinstance(values[key],int) or not low<=values[key]<=high:
            raise ValueError(f'Invalid {key}')
    return values


def save_settings(values, principal):
    from core.access import require_admin
    from core.audit import record
    require_admin(principal)
    validate(values)
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS app_settings (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO app_settings VALUES (1,?)", (json.dumps(values),))
    from phases.phase3_hard.cache import clear_cache
    clear_cache()
    from core.redis_cache import clear_answers
    clear_answers()
    record(principal, "settings_changed", values)
