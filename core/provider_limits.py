"""Atomic app-wide provider budgets. No raw prompts, credentials or new service."""
from contextlib import contextmanager
import json
import math
import sqlite3
import time
import uuid
import httpx
from core.settings import get_settings
from phases.phase3_hard.storage import connect


class CapacityError(ValueError):
    def __init__(self, seconds=60):
        self.retry_after = max(1,math.ceil(seconds))
        super().__init__(f'The shared question service is busy. Please try again in {self.retry_after} seconds.')


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS provider_calls (id TEXT PRIMARY KEY, provider TEXT NOT NULL, started REAL NOT NULL, tokens INTEGER NOT NULL, active INTEGER NOT NULL, expires REAL NOT NULL, token_source TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS provider_window ON provider_calls(provider,started)')
    db.execute('CREATE TABLE IF NOT EXISTS provider_cooldowns (provider TEXT PRIMARY KEY, until REAL NOT NULL)')


class Lease:
    def __init__(self, identity):
        self.identity, self.usage = identity, None

    def finish(self):
        with connect() as db:
            _schema(db)
            if self.usage is None:
                db.execute('UPDATE provider_calls SET active=0 WHERE id=?',(self.identity,))
            else:
                db.execute("UPDATE provider_calls SET active=0,tokens=?,token_source='provider' WHERE id=?",(max(0,int(self.usage)),self.identity))


def reserve(provider, tokens):
    settings, now, identity = get_settings(),time.time(),uuid.uuid4().hex
    if tokens < 0:
        raise ValueError('Invalid provider reservation')
    try:
        with connect() as db:
            _schema(db)
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM provider_calls WHERE started<? AND expires<?',(now-86400,now))
            row = db.execute('SELECT until FROM provider_cooldowns WHERE provider=?',(provider,)).fetchone()
            if row and row[0]>now:
                raise CapacityError(row[0]-now)
            active = db.execute('SELECT count(*) FROM provider_calls WHERE active=1 AND expires>?',(now,)).fetchone()[0]
            if active>=settings['provider_concurrency']:
                raise CapacityError(5)
            day = db.execute('SELECT count(*),coalesce(sum(tokens),0) FROM provider_calls WHERE provider=? AND started>?',(provider,now-86400)).fetchone()
            if provider=='groq':
                minute = db.execute('SELECT count(*),coalesce(sum(tokens),0) FROM provider_calls WHERE provider=? AND started>?',(provider,now-60)).fetchone()
                if minute[0]>=settings['groq_requests_minute'] or minute[1]+tokens>settings['groq_tokens_minute']:
                    raise CapacityError(60)
                if day[0]>=settings['groq_requests_day'] or day[1]+tokens>settings['groq_tokens_day']:
                    raise CapacityError(3600)
            elif provider=='pinecone_embedding' and day[1]+tokens>settings['embedding_tokens_day']:
                raise CapacityError(3600)
            db.execute("INSERT INTO provider_calls VALUES (?,?,?,?,1,?,'reserved')",(identity,provider,now,int(tokens),now+settings['provider_timeout']+30))
        return Lease(identity)
    except sqlite3.Error:
        raise CapacityError(30) from None


@contextmanager
def embedding_budget(tokens):
    lease = reserve('pinecone_embedding',tokens)
    try:
        yield lease
    finally:
        lease.finish()


def cooldown(provider, seconds):
    with connect() as db:
        _schema(db)
        db.execute('INSERT INTO provider_cooldowns VALUES (?,?) ON CONFLICT(provider) DO UPDATE SET until=max(until,excluded.until)',(provider,time.time()+max(1,min(3600,seconds))))


def status():
    now = time.time()
    with connect() as db:
        _schema(db)
        return [dict(row) for row in db.execute('SELECT provider,count(*) AS calls_24h,sum(tokens) AS tokens_24h,sum(CASE WHEN active=1 AND expires>? THEN 1 ELSE 0 END) AS active FROM provider_calls WHERE started>? GROUP BY provider',(now,now-86400))]


def friendly_error(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error,CapacityError):
            return str(error)
        if getattr(error,'status_code',None)==429:
            return 'The AI provider is temporarily rate limited. Please wait a minute and try again.'
        error = getattr(error,'__cause__',None)
    return None


def _request_lease(request):
    if not request.url.path.endswith('/chat/completions'):
        return None,False
    from phases.phase4_obs.tracker import count_tokens
    payload = json.loads(request.content)
    budget = 64+sum(8+count_tokens(str(message.get('content',''))) for message in payload.get('messages',[]))
    if payload.get('response_format'):
        budget += count_tokens(json.dumps(payload['response_format']))
    budget += int(payload.get('max_completion_tokens',payload.get('max_tokens',get_settings()['answer_tokens'])))
    return reserve('groq',budget),bool(payload.get('stream'))


class UsageReader:
    def __init__(self, lease, streamed):
        self.lease,self.streamed,self.buffer = lease,streamed,b''

    def feed(self,data):
        if not self.lease:
            return
        self.buffer += data
        if self.streamed:
            lines = self.buffer.split(b'\n')
            self.buffer = lines.pop()[-65536:]
            for line in lines:
                if line.startswith(b'data: '):
                    self._usage(line[6:])
        elif len(self.buffer)>8*1024*1024:
            self.buffer = b''  # Retain the conservative reservation for oversized data.

    def _usage(self,data):
        try:
            value = json.loads(data)
            usage = value.get('usage') or value.get('x_groq',{}).get('usage')
            if usage and isinstance(usage.get('total_tokens'),int):
                self.lease.usage = usage['total_tokens']
        except (ValueError,TypeError,AttributeError):
            pass

    def finish(self):
        if self.lease:
            self._usage(self.buffer)
            self.lease.finish()
            self.lease = None


class BudgetStream(httpx.SyncByteStream):
    def __init__(self,stream,reader):
        self.stream,self.reader = stream,reader
    def __iter__(self):
        try:
            for data in self.stream:
                self.reader.feed(data)
                yield data
        finally:
            self.close()
    def close(self):
        try:
            self.stream.close()
        finally:
            self.reader.finish()


def _rate_response(response):
    if response.status_code==429:
        try:
            seconds = float(response.headers.get('retry-after','60'))
        except ValueError:
            seconds = 60
        cooldown('groq',seconds)


class BudgetTransport(httpx.BaseTransport):
    def __init__(self,inner=None):
        self.inner = inner or httpx.HTTPTransport(retries=0)
    def handle_request(self,request):
        lease,streamed = _request_lease(request)
        try:
            response = self.inner.handle_request(request)
            _rate_response(response)
            reader = UsageReader(lease,streamed)
            if response.is_stream_consumed:
                reader.feed(response.content)
                reader.finish()
            else:
                response.stream = BudgetStream(response.stream,reader)
            return response
        except Exception:
            if lease:
                lease.finish()
            raise
    def close(self):
        self.inner.close()


class AsyncBudgetStream(httpx.AsyncByteStream):
    def __init__(self,stream,reader):
        self.stream,self.reader = stream,reader
    async def __aiter__(self):
        try:
            async for data in self.stream:
                self.reader.feed(data)
                yield data
        finally:
            await self.aclose()
    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            self.reader.finish()


class AsyncBudgetTransport(httpx.AsyncBaseTransport):
    def __init__(self,inner=None):
        self.inner = inner or httpx.AsyncHTTPTransport(retries=0)
    async def handle_async_request(self,request):
        import asyncio
        lease,streamed = await asyncio.to_thread(_request_lease,request)
        try:
            response = await self.inner.handle_async_request(request)
            _rate_response(response)
            reader = UsageReader(lease,streamed)
            if response.is_stream_consumed:
                reader.feed(response.content)
                reader.finish()
            else:
                response.stream = AsyncBudgetStream(response.stream,reader)
            return response
        except Exception:
            if lease:
                lease.finish()
            raise
    async def aclose(self):
        await self.inner.aclose()


def http_client():
    return httpx.Client(transport=BudgetTransport(),timeout=get_settings()['provider_timeout'])


def async_http_client():
    return httpx.AsyncClient(transport=AsyncBudgetTransport(),timeout=get_settings()['provider_timeout'])
