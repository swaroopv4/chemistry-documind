"""Offline checks for Celery configuration, managed uploads and UI job states."""
from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import pipeline
from phases.phase2_async import uploads, job_status, tasks, worker


class AsyncChecks(unittest.TestCase):
    def setUp(self):
        local_auth = patch.dict(os.environ, {'DOCUMIND_LOCAL_ADMIN':'true', 'DEPLOYMENT_ENV':'local', 'OIDC_CLIENT_ID':'', 'OIDC_CLIENT_SECRET':''})
        local_auth.start()
        self.addCleanup(local_auth.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'DOCUMIND_UPLOAD_DIR': self.temp.name,
                                          'DOCUMIND_DATA_DIR': str(Path(self.temp.name) / 'data')})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_worker_config_uses_json_started_tracking_and_queue(self):
        conf = worker.celery_app.conf
        self.assertEqual(conf.task_serializer, 'json')
        self.assertEqual(conf.accept_content, ['json'])
        self.assertTrue(conf.task_track_started)
        self.assertEqual(conf.result_expires, 3600)
        self.assertEqual(conf.worker_prefetch_multiplier, 1)
        self.assertEqual(conf.task_default_queue, 'documind-ingestion')

    def test_upload_staging_preserves_name_and_prevents_path_escape(self):
        key = uploads.stage_upload('../../slides.PPTX', b'content')
        self.assertEqual(uploads.resolve_upload(key).name, 'slides.PPTX')
        self.assertEqual(uploads.resolve_upload(key).read_bytes(), b'content')
        for invalid in ['../secret.env', '/etc/passwd', 'not-a-uuid/file.pdf',
                        '0' * 32 + '/../outside.pdf']:
            with self.assertRaises(ValueError):
                uploads.resolve_upload(invalid)
        uploads.cleanup_upload(key)
        self.assertFalse(uploads.resolve_upload(key).exists())
        for name, content in [('bad.exe', b'data'), ('empty.pdf', b'')]:
            with self.assertRaises(ValueError):
                uploads.stage_upload(name, content)

    def test_submit_returns_id_and_worker_receives_shared_relative_key(self):
        with patch.object(job_status, 'check_connection', return_value=True), \
             patch.object(tasks.ingest_task, 'apply_async') as publish:
            job_id = job_status.submit_uploaded_job('sample.cif', b'data_sample\n_tag 1', 400, 50)
        uuid.UUID(job_id)
        kwargs = publish.call_args.kwargs
        self.assertEqual(kwargs['task_id'], job_id)
        self.assertEqual(kwargs['args'][1:], [400, 50])
        self.assertFalse(Path(kwargs['args'][0]).is_absolute())
        self.assertTrue(uploads.resolve_upload(kwargs['args'][0]).exists())

    def test_unavailable_redis_does_not_stage_file(self):
        with patch.object(job_status, 'check_connection', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Redis is unavailable'):
                job_status.submit_uploaded_job('sample.pdf', b'content')
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_publish_uncertainty_retains_file_and_reports_job_id(self):
        with patch.object(job_status, 'check_connection', return_value=True), \
             patch.object(tasks.ingest_task, 'apply_async', side_effect=OSError('disconnected')):
            with self.assertRaisesRegex(RuntimeError, 'Check Job ID'):
                job_status.submit_uploaded_job('sample.pdf', b'content')
        self.assertEqual(len(list(Path(self.temp.name).rglob('sample.pdf'))), 1)

    def test_worker_progress_result_and_cleanup(self):
        key = uploads.stage_upload('sample.cif', b'data_sample\n_tag 1')
        def ingest(path, size, overlap, progress, job_id=None):
            self.assertEqual(path.name, 'sample.cif')
            self.assertTrue(path.exists())
            progress('Generating embeddings', 0.4)
            return pipeline.IngestResult('sample.cif', 2, 1, 20)
        with patch.object(pipeline, 'ingest_document', side_effect=ingest), \
             patch.object(tasks.ingest_task, 'update_state') as update:
            result = tasks.ingest_task.run(key)
        self.assertEqual(result['status'], 'success')
        update.assert_called_once_with(state='PROGRESS', meta={'step': 'Generating embeddings', 'pct': 0.4})
        self.assertFalse(uploads.resolve_upload(key).exists())

    def test_worker_errors_raise_for_celery_and_cleanup(self):
        key = uploads.stage_upload('invalid.mol2', b'invalid')
        result = pipeline.IngestResult('invalid.mol2', 0, 0, 0, 'error', 'Invalid MOL2')
        with patch.object(pipeline, 'ingest_document', return_value=result), \
             patch.object(tasks.ingest_task, 'update_state') as update:
            with self.assertRaisesRegex(ValueError, 'Invalid MOL2'):
                tasks.ingest_task.run(key)
        update.assert_not_called()  # no malformed manual FAILURE payload
        self.assertFalse(uploads.resolve_upload(key).exists())

    def test_job_status_states_are_bound_to_configured_app(self):
        job_id = str(uuid.uuid4())
        cases = [
            ('PENDING', None, None, 'Queued or no result yet', 0.0),
            ('STARTED', None, None, 'Worker started', 0.0),
            ('PROGRESS', {'step': 'Embedding', 'pct': 0.4}, None, 'Embedding', 0.4),
            ('SUCCESS', None, {'chunk_count': 2}, 'Done', 1.0),
            ('FAILURE', None, ValueError('bad data'), 'Error', 0.0),
            ('REVOKED', None, None, 'Cancelled', 0.0),
        ]
        for state, info, result, step, pct in cases:
            with self.subTest(state=state), patch.object(job_status, 'AsyncResult',
                return_value=NS(state=state, info=info, result=result)) as async_result:
                status = job_status.get_job_status(job_id)
                self.assertEqual((status.state, status.step, status.pct), (state, step, pct))
                async_result.assert_called_once_with(job_id, app=worker.celery_app)
                if state == 'FAILURE':
                    self.assertEqual(status.error, 'bad data')
        with self.assertRaises(ValueError):
            job_status.get_job_status('invalid-id')

    def test_ui_displays_completed_and_failed_jobs_without_losing_answer(self):
        from streamlit.testing.v1 import AppTest
        good, bad = str(uuid.uuid4()), str(uuid.uuid4())
        status = {
            good: job_status.JobStatus(good, 'SUCCESS', 'Done', 1.0,
                                      {'doc_name': 'report.docx', 'chunk_count': 2, 'page_count': 1, 'total_tokens': 40}),
            bad: job_status.JobStatus(bad, 'FAILURE', 'Error', error='Invalid MOL2'),
        }
        with patch.dict(os.environ, {'GROQ_API_KEY': '', 'PINECONE_API_KEY': ''}), \
             patch.object(pipeline, 'get_ingest_status', side_effect=lambda key: status[key]):
            app = AppTest.from_file(str(ROOT / 'ui' / 'app.py'))
            app.session_state['jobs'] = {key: {'filename': 'upload', 'status': None} for key in status}
            app.session_state['last_answer'] = 'Stored answer'
            app.session_state['last_sources'] = []
            app.run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('2 chunks' in message.value for message in app.success))
        self.assertTrue(any('Invalid MOL2' in message.value for message in app.error))
        self.assertTrue(any('Stored answer' in message.value for message in app.markdown))

    def test_job_lookup_submits_the_entered_id_with_one_button_click(self):
        from streamlit.testing.v1 import AppTest
        job_id = str(uuid.uuid4())
        status = job_status.JobStatus(job_id,'SUCCESS','Done',1.0,
            {'doc_name':'report.docx','chunk_count':2,'page_count':1,'total_tokens':40})
        with patch.dict(os.environ,{'GROQ_API_KEY':'','PINECONE_API_KEY':''}), \
             patch.object(pipeline,'get_ingest_status',return_value=status) as lookup:
            app = AppTest.from_file(str(ROOT/'ui/app.py')).run(timeout=20)
            track = next(button for button in app.button if button.label=='Track job')
            track.click().run(timeout=20)
            lookup.assert_not_called()
            self.assertTrue(any('Enter a Job ID' in item.value for item in app.warning))
            field = next(field for field in app.text_input if field.label=='Look up a job ID')
            # No intermediate field .run() or Enter/apply step.
            field.set_value('  '+job_id+'  ')
            next(button for button in app.button if button.label=='Track job').click().run(timeout=20)
            self.assertEqual(len(app.exception),0)
            lookup.assert_called_once_with(job_id)
            self.assertIn(job_id,app.session_state['jobs'])
            self.assertTrue(any('Job added to the tracking list' in item.value for item in app.success))
            self.assertTrue(any('2 chunks' in item.value for item in app.success))


if __name__ == '__main__':
    unittest.main(verbosity=2)
