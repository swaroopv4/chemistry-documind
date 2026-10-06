from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid

from celery.result import AsyncResult
import redis

from phases.phase2_async.worker import celery_app, BROKER, BACKEND
from phases.phase2_async.uploads import stage_upload


class JobSubmissionError(RuntimeError):
    def __init__(self, job_id):
        self.job_id = job_id
        super().__init__(f'Could not confirm job submission. Check Job ID {job_id} before retrying. The staged file was retained.')


@dataclass
class JobStatus:
    job_id: str
    state: str
    step: str = ''
    pct: float = 0.0
    result: dict | None = None
    error: str = ''


def check_connection() -> bool:
    """Bounded Redis ping for broker and result backend; does not promise a worker is up."""
    try:
        for url in set([BROKER, BACKEND]):
            if not url.startswith(('redis://', 'rediss://')):
                return False
            with redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1) as client:
                client.ping()
        return True
    except (redis.RedisError, ValueError):
        return False


def submit_uploaded_job(filename: str, content: bytes,
                        chunk_size: int = 400, chunk_overlap: int = 50,job_id=None) -> str:
    if not 0 <= chunk_overlap < chunk_size <= 800:
        raise ValueError('Require 0 <= overlap < chunk size <= 800')
    if not check_connection():
        raise RuntimeError('Redis is unavailable. Start Redis and the Celery worker, then retry.')
    from phases.phase2_async.tasks import ingest_task

    key = stage_upload(filename, content)
    job_id = job_id or str(uuid.uuid4())
    uuid.UUID(job_id)
    try:
        ingest_task.apply_async(args=[key, chunk_size, chunk_overlap], task_id=job_id, retry=False)
    except Exception:
        # Publishing may be ambiguous if the server accepted the message before
        # disconnecting. Keep the file so an accepted task can still run.
        raise JobSubmissionError(job_id) from None
    return job_id


def submit_ingest_job(path: str, chunk_size: int = 400, chunk_overlap: int = 50) -> str:
    path = Path(path)
    return submit_uploaded_job(path.name, path.read_bytes(), chunk_size, chunk_overlap)


def get_job_status(job_id: str) -> JobStatus:
    try:
        uuid.UUID(job_id)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Enter a valid job ID') from None
    result = AsyncResult(job_id, app=celery_app)
    state = result.state
    if state in ('PROGRESS', 'RETRY'):
        meta = result.info if isinstance(result.info, dict) else {}
        return JobStatus(job_id, state, meta.get('step', 'Retrying' if state == 'RETRY' else 'Processing'),
                         max(0.0, min(1.0, float(meta.get('pct', 0.0)))))
    if state == 'SUCCESS':
        return JobStatus(job_id, state, 'Done', 1.0, result.result)
    if state == 'FAILURE':
        return JobStatus(job_id, state, 'Error', error=str(result.result))
    if state == 'REVOKED':
        return JobStatus(job_id, state, 'Cancelled')
    return JobStatus(job_id, state, 'Worker started' if state == 'STARTED' else 'Queued or no result yet')
