from __future__ import annotations

import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')

REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
BROKER = os.getenv('CELERY_BROKER_URL') or REDIS_URL
BACKEND = os.getenv('CELERY_RESULT_BACKEND') or REDIS_URL
QUEUE = os.getenv('CELERY_QUEUE', 'documind-ingestion')

celery_app = Celery(
    'documind', broker=BROKER, backend=BACKEND,
    include=['phases.phase2_async.tasks'],
)
celery_app.conf.update(
    task_serializer='json', result_serializer='json', accept_content=['json'],
    task_track_started=True, result_expires=3600, worker_prefetch_multiplier=1,
    task_default_queue=QUEUE, broker_connection_retry_on_startup=True,
    broker_connection_timeout=2, broker_transport_options={'socket_timeout': 2, 'socket_connect_timeout': 2},
    redis_socket_connect_timeout=2, redis_socket_timeout=2,
    result_backend_transport_options={'retry_policy': {'timeout': 2}},
    task_publish_retry=False,
)
