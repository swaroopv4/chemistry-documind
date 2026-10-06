"""Exercise real Redis Lua scripts in an isolated test database, no provider calls."""
from pathlib import Path
import os
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core import redis_cache, access


def main():
    url=os.getenv('DOCUMIND_TEST_CACHE_REDIS_URL','redis://127.0.0.1:6382/0')
    with patch.dict(os.environ,{'ANSWER_CACHE_REDIS_URL':url,'REDIS_URL':url}), \
         patch.object(redis_cache,'PREFIX','documind-test:'+uuid.uuid4().hex+':'):
        settings={'cache_strategy':'lru','cache_capacity':2,'cache_ttl':60}
        sources=[{'doc_name':'Guide','text':'H2O','locator':'page 1'}]
        def store(question):
            redis_cache.put_answer(question,'scope','Answer '+question,sources,settings)
        def hit(question):
            return redis_cache.get_answer(question,'scope',settings)
        for mode in ('lru','lfu','fifo'):
            settings['cache_strategy']=mode
            redis_cache.clear_answers()
            store('A');store('B')
            assert hit('A') and hit('A')
            store('C')
            if mode=='fifo':
                assert hit('A') is None and hit('B') and hit('C')
            else:
                assert hit('B') is None and hit('A') and hit('C')
            assert redis_cache.status()['active_answers']==2
            print('PASS:',mode,'retention and atomic capacity enforcement')
        redis_cache.clear_answers()
        settings['cache_strategy']='ttl'
        for question in ('A','B','C'):store(question)
        assert all(hit(question) for question in ('A','B','C'))
        print('PASS: all-with-expiry ignores capacity and preserves TTL')
        with redis_cache.client() as connection:
            key=redis_cache._key('A','scope')
            assert 0<connection.ttl(key)<=60
            connection.expire(key,0)
        assert hit('A') is None
        assert redis_cache.get_answer('B','different-scope',settings) is None
        settings['cache_strategy']='disabled'
        assert hit('B') is None
        principal=access.Principal('isolated-test:'+uuid.uuid4().hex,'student','test@uci.edu')
        with patch.dict(os.environ,{'USER_RATE_LIMIT_PER_MINUTE':'2'}):
            redis_cache.check_rate_limit(principal);redis_cache.check_rate_limit(principal)
            try:
                redis_cache.check_rate_limit(principal)
                raise AssertionError('Rate limit did not block')
            except ValueError as error:
                assert 'wait a minute' in str(error)
        redis_cache.clear_answers()
        print('PASS: TTL, corpus scope, disable, clear, and per-user rate limit')


if __name__=='__main__':main()
