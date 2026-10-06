"""Redis exact-answer cache uses a dedicated Redis, separate from the broker."""
import hashlib
import json
import logging
import os
import time
import unicodedata
import redis

PREFIX = "documind:answers:"


def client():
    return redis.Redis.from_url(os.getenv("ANSWER_CACHE_REDIS_URL", "redis://127.0.0.1:6380/0"),
        decode_responses=True, socket_connect_timeout=.5, socket_timeout=.5)


def _key(question, scope):
    # Preserve case: CO and Co are different chemistry questions.
    normalized = " ".join(unicodedata.normalize("NFC", question).split())
    return PREFIX + hashlib.sha256((scope + "\n" + normalized).encode()).hexdigest()


def _keys():
    return [PREFIX+suffix for suffix in ("fifo", "lru", "lfu", "expiry", "clock", "hits", "misses")]


LOOKUP = """
local payload=redis.call('GET',KEYS[1])
if not payload then redis.call('INCR',KEYS[8]); return nil end
local tick=redis.call('INCR',KEYS[6])
redis.call('ZADD',KEYS[3],tick,KEYS[1])
redis.call('ZINCRBY',KEYS[4],1,KEYS[1])
redis.call('INCR',KEYS[7])
return payload
"""

STORE = """
local tick=redis.call('INCR',KEYS[6])
local isnew=redis.call('EXISTS',KEYS[1])==0
redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[2])
if isnew then redis.call('ZADD',KEYS[2],tick,KEYS[1]); redis.call('ZADD',KEYS[4],1,KEYS[1]) end
redis.call('ZADD',KEYS[3],tick,KEYS[1])
redis.call('ZADD',KEYS[5],ARGV[3]+ARGV[2],KEYS[1])
local expired=redis.call('ZRANGEBYSCORE',KEYS[5],'-inf',ARGV[3])
for _,key in ipairs(expired) do
 redis.call('DEL',key)
 for i=2,5 do redis.call('ZREM',KEYS[i],key) end
end
if ARGV[4]~='ttl' then
 local index=KEYS[3]
 if ARGV[4]=='fifo' then index=KEYS[2] elseif ARGV[4]=='lfu' then index=KEYS[4] end
 local excess=redis.call('ZCARD',index)-tonumber(ARGV[5])
 if excess>0 then
  local victims=redis.call('ZRANGE',index,0,excess-1)
  for _,key in ipairs(victims) do
   redis.call('DEL',key)
   for i=2,5 do redis.call('ZREM',KEYS[i],key) end
  end
 end
end
for i=2,5 do redis.call('EXPIRE',KEYS[i],tonumber(ARGV[2])+60) end
return 1
"""


def get_answer(question, scope, settings):
    if not scope or settings["cache_strategy"] == "disabled":
        return None
    try:
        with client() as connection:
            payload = connection.eval(LOOKUP, 8, _key(question, scope), *_keys())
        if payload:
            value = json.loads(payload)
            if isinstance(value.get("answer"), str) and isinstance(value.get("sources"), list):
                return value
    except (redis.RedisError, ValueError, TypeError):
        logging.getLogger(__name__).warning("Answer Redis unavailable; using normal retrieval")
    return None


def put_answer(question, scope, answer, sources, settings):
    if not scope or not sources or settings["cache_strategy"] == "disabled":
        return
    try:
        payload = json.dumps({"answer": answer, "sources": sources, "question": question})
        with client() as connection:
            connection.eval(STORE, 8, _key(question, scope), *_keys(), payload,
                            settings["cache_ttl"], time.time(), settings["cache_strategy"], settings["cache_capacity"])
    except (redis.RedisError, ValueError, TypeError):
        logging.getLogger(__name__).warning("Answer Redis unavailable; response was not cached")


def clear_answers():
    try:
        with client() as connection:
            for key in connection.scan_iter(match=PREFIX+"*", count=100):
                connection.delete(key)
    except redis.RedisError:
        pass  # Corpus revision in scoped keys prevents stale cache reuse.


def status():
    with client() as connection:
        connection.ping()
        memory, server, stats = connection.info("memory"), connection.info("server"), connection.info("stats")
        return {"connected": True, "active_answers": connection.zcount(PREFIX+"expiry", time.time(), "+inf"),
                "application_hits": int(connection.get(PREFIX+"hits") or 0),
                "application_misses": int(connection.get(PREFIX+"misses") or 0),
                "used_memory": memory["used_memory_human"], "maxmemory": memory["maxmemory_human"],
                "memory_policy": memory["maxmemory_policy"], "evicted_keys": stats["evicted_keys"],
                "uptime_seconds": server["uptime_in_seconds"]}


def check_rate_limit(principal):
    """No-eviction broker Redis holds expiring counters, not answer-cache Redis."""
    limit = int(os.getenv("USER_RATE_LIMIT_PER_MINUTE", "20"))
    bucket = int(time.time() // 60)
    key = f"documind:rate:{principal.audit_id}:{bucket}"
    connection = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        socket_connect_timeout=1, socket_timeout=1)
    try:
        count = connection.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],120) end; return n", 1, key)
        if count > limit:
            raise ValueError("Too many questions. Please wait a minute and try again.")
    except redis.RedisError:
        raise ValueError("The question service is temporarily unavailable. Please try again shortly.") from None
    finally:
        connection.close()
