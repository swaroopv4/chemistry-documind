# Phase 2 extraction and adaptations

Source: [Build an Enterprise RAG System — Phase 2](https://www.youtube.com/watch?v=eYWQS3PHr-0). The 44:56 tutorial's auto-generated transcript and visible coding screens were reviewed. This is a reconstruction with the requested provider/file adaptations, not a byte-identical copy of an unpublished repository.

| Tutorial sequence | Result in this application |
|---|---|
| 0:17–1:50: phase2_async folder and architecture | phases/phase2_async package |
| 1:53–13:09: bound ingestion task, progress states and summary | tasks.py, task name documind.ingest, existing generic ingestion pipeline |
| 13:14–19:44: Celery app, Redis broker/backend, JSON configuration | worker.py, JSON serializers, STARTED tracking, one-hour results, prefetch 1 |
| 16:22–16:53: environment additions | REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND |
| 19:45–31:10: job submission and status dataclass | job_status.py, job IDs, queued/started/progress/success/failure states |
| 31:12–38:48: dependencies and pipeline entry points | Celery/Redis requirements, async_available, submit_ingest_job and get_ingest_status |
| 38:51–44:49: asynchronous upload, queue tab and demonstration | background upload toggle, Job queue, progress and results, preserved Q&A |

No additional API key is introduced. The video's OpenAI and Pinecone keys belong to Phase 1. This adaptation continues to use GROQ_API_KEY and PINECONE_API_KEY. A local Redis needs a connection URL, not an API key. A hosted Redis may require a username/password and TLS connection URL supplied by that provider.

## Corrections and requested adaptations

- All six existing file types use the same background task; Groq answers and Pinecone embeddings are retained.
- AsyncResult explicitly uses the configured Celery app. The task raises failures for Celery to serialize; arbitrary FAILURE dictionaries can break exception decoding.
- async_available performs bounded Redis pings instead of treating a configured URL as proof of a live server. It does not promise that a worker is running.
- Uploads are staged under .uploads with original filenames and relative keys shared by host/container workers. Streamlit does not delete a queued file. The worker cleans files after success or failure.
- A publication timeout may be ambiguous. The file is retained and the generated job ID is reported for lookup; it is not prematurely deleted.
- Source sections, citation locations and same-filename replacement behavior from the customization remain in use.
- The queue panel polls in a Streamlit fragment. Answers remain visible through reruns. Completed statuses are cached in the browser session.
- Docker Compose runs the app, worker and Redis on Linux containers on Windows. Native --pool=solo is documented only as a development option because Celery does not officially support Windows.

## Limits

This is a local single-user tutorial app. Keep one ingestion worker/concurrency=1 to avoid overlapping same-filename replacements. Results expire after one hour; unknown/expired IDs appear PENDING. A browser refresh can lose the session job list, but a saved job ID can be looked up while its result exists. Redis persistence and staging survive ordinary container restarts, but hard worker failures and ambiguous publications can leave staged files requiring manual review. This is not transactional or exactly-once ingestion. No automatic retries, cancellation, multi-user authorization or complete document catalog is claimed.

References: [Celery Redis settings](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html), [Celery platform support](https://docs.celeryq.dev/en/stable/getting-started/introduction.html), [Streamlit fragments](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment).
