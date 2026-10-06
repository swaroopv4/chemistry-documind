# Module and call sequence — customized application

## Hybrid retrieval (default)

```text
new chunks → redaction → Pinecone dense upsert → atomic SQLite BM25 replacement
existing vectors → admin rebuild → paginated ID/fetch scan → atomic BM25 backfill
question → embedding → optional audience-scoped answer cache
  core/retrieval.py: retrieve
    vector_store.query_index → filtered dense candidates
    keyword_index.search → independently filtered BM25 candidates
    Pinecone fetch → reject stale/deleted/renamed keyword candidates
    reciprocal rank fusion → deduplicate → final top-k
  student source/policy checks → evidence prompt → Groq → output/privacy checks
  safe answer cache and query/retrieval telemetry
```

See HYBRID_NOTES.md for candidate bounds, case-preserving chemistry tokens and separate score interpretation. `RETRIEVAL_MODE=dense` retains the tutorial's semantic-only retrieval branch described later in this file.

## Verified role and student question path

```text
ui/launch.py → server OIDC configuration → Streamlit login/cookie validation
core/access.py → expected issuer, managed UCI domain, verified email, token expiry
  explicit ADMIN_EMAILS → admin workspace
  other accepted UCI accounts → ui/chat.py (questions and safe citations only)
student question → identity + per-user rate limit + input checks
  shared settings/corpus/audience scope → exact Redis hit → policy recheck → answer
  miss → Groq structured chemistry/privacy/injection classification
  catalog.published → independently filtered Pinecone dense + SQLite BM25 candidates
  keyword candidates → fresh Pinecone ID/document/text verification
  reciprocal rank fusion → deduplicate → top-k → sanitize/recheck sources
  redacted context + generic source labels → chemistry researcher prompt → Groq
  buffered answer → redaction/citations → Groq output privacy check
  final document-policy recheck → scope-safe Redis/optional semantic cache → chat
  audit events and provider usage → admin-only logs/Dashboard
```

Private/unreviewed documents never enter student retrieval. Source chunks and original filenames are not rendered in chat. Admin batch uploads stage each file privately, enqueue independent jobs, then require review/publication in Documents. Admin logging/cache/Redis health controls are in ui/admin_controls.py. See CAMPUS_NOTES.md for the bounded cache strategies and AUTH_SETUP.md for real sign-in setup.

## Phase 2 background path (default)

```text
ui/app.py → submit_uploaded_document(filename, bytes, chunk parameters)
  phases/phase2_async/job_status.py: submit_uploaded_job
    check broker/backend Redis connection
    uploads.py: stage .uploads/<uuid>/<original_filename>
    tasks.ingest_task.apply_async(relative upload key, task_id=<job ID>)
    return job ID immediately
  Redis message → worker.py configured Celery app → tasks.py: ingest_task
    resolve the shared relative upload key
    run ingest_document below; callback updates PROGRESS in Redis
    return summary dict → Celery SUCCESS, or raise → Celery FAILURE
    finally clean the managed upload
  Job queue fragment → get_ingest_status → get_job_status
    AsyncResult(job_id, app=celery_app)
    queued/started/progress/success/failure → UI status and counts
```

submit_ingest_job(path) is the video-compatible pipeline entry point for a file already on disk. The direct ingestion path below remains available through the background toggle.

## Ingestion

```text
ui/app.py: upload → temporary directory / original filename
  core/pipeline.py: ingest_document(path, chunk_size, overlap, callback)
    1. core/ingestion.py: ingest_file
       core/formats.py: extract_sections dispatches by extension
         PDF: pypdf page text
         PPTX: python-pptx slides / tables / grouped shapes / notes
         DOCX: python-docx paragraphs / tables / headers / footers
         PPT: core/legacy_ppt.py OLE current edit → persist directory
              → live document → ordered slides → UTF-16 / byte text atoms
         MOL2: core/chemical_formats.py molecule headers / atom-bond validation
         CIF: core/chemical_formats.py gemmi blocks / pairs / loops / frames
       chunk_sections → Chunk(text, doc_name, source number, index, tokens,
                               metadata={locator, file_type})
       ordinary text: section-local overlapping token windows
       chemistry: whole records with identifying prefix; no row overlap
    2. core/embeddings.py: embed_chunks → embed_texts(input_type="passage")
       Pinecone.inference.embed(model="llama-text-embed-v2")
       dimension=1024, truncate=NONE; batches of 96
       verify response count and dimensions
    3. core/vector_store.py: upsert_chunks
       cache.corpus_update suppresses/invalidate cache around writes
       get_index → create documind-groq if absent; validate 1024 / cosine
       id = "{original_filename}_{chunk_index}"
       metadata includes text, filename, locator, file type, embedding model
       batches of 100 → upsert(namespace="llama-text-embed-v2-1024")
       delete stale trailing chunks for successfully replaced filenames
    4. Return IngestResult → UI counts and status
       page_count is retained as a compatibility field for source unit count
       phase4_obs.tracker: ingestion duration / success or error / source counts
       each actual embedding batch: usage.total_tokens → estimated cost → SQLite
```

## Questions

```text
ui/app.py: Ask → query_document(question, top_k=5, stream=True)
  core/pipeline.py:
    1. Strip question; reject empty input; check top_k
       phase3_hard.guardrails.check_input: injection/off-topic block and redaction
    2. embed_query → Pinecone.inference.embed(input_type="query")
    3. phase3_hard.cache: lookup by embedding + scoped corpus/model/filter
       cache hit retains answer and original sources; skip retrieval/generation
       Phase 4: cache event has zero Groq tokens/cost; query embedding still counted
       otherwise query_index → index.query in the embedding namespace
       Phase 4: search duration / returned chunk count / average score / first document
       optional document filename filter
       sources include locator and file_type
    4. Minimum retrieval evidence check; redact context text
       generate_answer → context + evidence-only system prompt
       OpenAI SDK(base_url="https://api.groq.com/openai/v1", GROQ_API_KEY)
       model=GROQ_MODEL (default openai/gpt-oss-20b), temperature=0.1
       guarded stream: collect → redact/check citations → st.write_stream
       guardrails disabled: streamed deltas → st.write_stream
       claim citations use actual source locations
       Phase 4: capture raw provider usage at generation boundary (stream and non-stream)
       prompt/completion/cached-input tokens + model latency + estimated cost
    5. Complete answers → scoped semantic cache → QueryMetrics
       SQLite + inspectable JSONL → dashboard and two-window drift checks
       stream=False → QueryResult(answer, sources, query, top_k,
                                  cache_hit, latency_ms, status, cache metadata)
       stream=True → (AnswerStream with .result metadata, sources)
```

## Management

Documents Refresh → describe_index_stats for namespace → sampled document query.
Remove → cache.corpus_update → metadata-filtered delete in the same namespace. Cache stays suppressed for a 30-second consistency window. Opening the UI performs no API calls.

## RAGAS evaluation

```text
JSON upload → validate 1–50 question/ground_truth rows before API calls
  optional saved answer/contexts for every row
  otherwise query_document(stream=False, use_cache=False) → fresh answer/context
  SingleTurnSample(user_input, response, retrieved_contexts, reference)
    → EvaluationDataset (validation remains enabled)
  Groq ChatOpenAI-compatible client → LangchainLLMWrapper
  Pinecone symmetric query embeddings → LangchainEmbeddingsWrapper
  fresh Faithfulness / ResponseRelevancy / ContextPrecision / ContextRecall
    → RAGAS evaluate in clean thread, max_workers=1, no event-loop patching
  detailed CSV + summary JSON under data/reports
  UI averages available cells; visibly marks failures and missing values
```

Phase 1 used PDF, OpenAI text-embedding-3-small / 1536 and gpt-4o-mini. Those provider choices were replaced as requested. Phase 2 adds the queue around the existing generic ingestion path, so all supported file formats benefit from background processing.

## Phase 4 operations dashboard

```text
core/generation.py → tracker.track_llm_call → metrics_store.log_llm_call
core/embeddings.py → tracker.track_embedding → metrics_store.log_embedding
core/pipeline.py → cache/retrieval/ingestion tracking hooks
  safe_track catches monitoring write failures without breaking the pipeline
  SQLite data/documind.db shared by app and worker (separate from Phase 3 state)
ui/app.py: Dashboard → rolling 1/7/14/30-day queries
  get_summary → requests / tokens / known estimated cost / cache rate / ingestion
  get_daily_costs → cost and request/cache-hit charts, UTC
  get_latency_series → daily mean Groq request latency, excludes answer-cache hits
  get_recent_calls → input/output/total tokens, token source, cost, status
  get_recent_operations → embeddings / retrievals / ingestions
```

Provider usage is preferred. Fallback token counts are labeled estimates; unknown costs are flagged. Only priced Groq Q&A and Pinecone embedding events contribute to known cost; ingestion totals do not duplicate embedding costs. RAGAS judge calls and provider account/database charges are excluded. See PHASE4_NOTES.md for pricing and limits.
