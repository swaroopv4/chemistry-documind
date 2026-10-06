from __future__ import annotations

from dataclasses import asdict

from phases.phase2_async.worker import celery_app
from phases.phase2_async.uploads import resolve_upload, cleanup_upload


@celery_app.task(bind=True, name='documind.ingest')
def ingest_task(self, upload_key: str, chunk_size: int = 400, chunk_overlap: int = 50) -> dict:
    from core.pipeline import ingest_document

    # Resolve before entering cleanup: an invalid key must never delete any file.
    path = resolve_upload(upload_key)

    def progress(step: str, pct: float):
        self.update_state(state='PROGRESS', meta={'step': step, 'pct': round(pct, 2)})

    try:
        result = ingest_document(path, chunk_size, chunk_overlap, progress,job_id=self.request.id)
        if result.status not in {'success','duplicate'}:
            # Celery encodes the raised exception in its normal FAILURE format.
            # Writing arbitrary FAILURE metadata breaks backend exception decoding.
            raise ValueError(result.error)
        return asdict(result)
    finally:
        cleanup_upload(upload_key)
