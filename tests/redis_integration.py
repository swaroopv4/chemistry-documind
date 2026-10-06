"""Real Redis/Celery test; model and vector services are mocked.

Requires a disposable Redis at 127.0.0.1:6381. No flush, index writes or paid API calls.
"""
from pathlib import Path
import os
import sys
import tempfile
import threading
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
test_url = os.getenv('DOCUMIND_TEST_REDIS_URL', 'redis://127.0.0.1:6381/0')
os.environ['REDIS_URL'] = test_url
os.environ['CELERY_BROKER_URL'] = test_url
os.environ['CELERY_RESULT_BACKEND'] = test_url.rsplit('/', 1)[0] + '/1'
os.environ['CELERY_QUEUE'] = 'documind-check-' + uuid.uuid4().hex
os.environ['GROQ_API_KEY'] = 'test-only'
os.environ['PINECONE_API_KEY'] = 'test-only'

from celery.contrib.testing.worker import start_worker
from phases.phase2_async.worker import celery_app
from phases.phase2_async.job_status import submit_uploaded_job, get_job_status, check_connection
from core import pipeline


def main():
    if not check_connection():
        raise RuntimeError('Start the disposable Redis test container on port 6381 first')
    entered, release = threading.Event(), threading.Event()
    captured = []

    def embed(chunks):
        captured.extend(chunks)
        entered.set()
        if not release.wait(15):
            raise RuntimeError('Integration test timed out waiting for progress observation')
        return [[0.1] * 1024 for _ in chunks]

    with tempfile.TemporaryDirectory() as directory, \
         patch.dict(os.environ, {'DOCUMIND_UPLOAD_DIR': directory,
                                'DOCUMIND_DATA_DIR': str(Path(directory) / 'data'),
                                'CACHE_INVALIDATION_DELAY_SECONDS': '0'}), \
         patch.object(pipeline, 'embed_chunks', side_effect=embed) as embed_mock, \
         patch.object(pipeline, 'upsert_chunks', return_value=1) as upsert_mock:
        job_id = submit_uploaded_job('crystal.cif', b'data_water\n_chemical_formula_sum "H2 O"\n_cell_length_a 9.1\n')
        assert get_job_status(job_id).state == 'PENDING'
        assert list(Path(directory).rglob('crystal.cif'))
        print('PASS: job queued immediately; staged file survives before worker startup')
        with start_worker(celery_app, pool='solo', concurrency=1,
                          perform_ping_check=False, loglevel='CRITICAL'):
            try:
                assert entered.wait(15)
                progress = get_job_status(job_id)
                assert progress.state == 'PROGRESS' and progress.pct == 0.4
                print('PASS: actual Redis backend reports embedding progress at 40%')
            finally:
                release.set()
            result = celery_app.AsyncResult(job_id).get(timeout=20)
            status = get_job_status(job_id)
            assert status.state == 'SUCCESS' and result['doc_name'] == 'crystal.cif'
            assert captured and captured[0].metadata['file_type'] == 'cif'
            assert not list(Path(directory).rglob('crystal.cif'))
            print('PASS: worker extracts CIF, returns SUCCESS and cleans staged upload')

            bad_id = submit_uploaded_job('invalid.mol2', b'not a molecule')
            celery_app.AsyncResult(bad_id).get(timeout=20, propagate=False)
            failed = get_job_status(bad_id)
            assert failed.state == 'FAILURE' and 'MOL2' in failed.error
            assert not list(Path(directory).rglob('invalid.mol2'))
            print('PASS: actual failure metadata decodes and failed upload is cleaned')
            assert embed_mock.call_count == 1 and upsert_mock.call_count == 1
            from phases.phase4_obs.metrics_store import get_summary
            monitored = get_summary()
            assert monitored['documents_ingested'] == 1 and monitored['ingestions'] == 2
            print('PASS: worker records successful and failed ingestion in shared Phase 4 SQLite storage')
            from core.keyword_index import status as keyword_status, search as keyword_search
            assert keyword_status()['documents'] == 1
            assert keyword_search('water')[0]['doc_name'] == 'crystal.cif'
            assert not keyword_search('water',allowed_docs=[])
            print('PASS: queued ingestion populates the shared BM25 index; private filters remain enforced')
        celery_app.AsyncResult(job_id).forget()
        celery_app.AsyncResult(bad_id).forget()
    print('Redis/Celery integration passed; no model or Pinecone requests were made')


if __name__ == '__main__':
    main()
