# Verification

## Hybrid retrieval upgrade

Verified October 5, 2026: **86/86 checks passed on Windows Python 3.12 and in the final Linux Docker image**. The 19 hybrid checks exercise actual SQLite FTS5 BM25 ranking, chemical formula case/superscripts, CAS identifiers, independent keyword-only recall, safe FTS query encoding, rank fusion/deduplication, document filtering before ranking, malicious dense matches, fresh remote validation of deleted/changed/renamed vectors, keyword failure fallback, keyword-only pipeline evidence and missing cosine telemetry, atomic replacement/deletion, PII redaction, partial remote ingestion failure, failed/over-limit backfill, concurrent replacement/deletion preservation, current Pinecone ListResponse/ListItem compatibility, cache scopes, student policy changes during generation and admin UI startup without provider calls. Earlier boundary tests explicitly retain semantic-only compatibility; hybrid student behavior is covered separately.

Actual isolated Redis/Celery integration passed in Linux, additionally asserting that a successful queued CIF job writes searchable chunks to the shared BM25 database and that private filters exclude them. No provider/index requests were made by this integration test.

Live migration read **89 existing vectors from one document** and populated the keyword index without re-embedding or modifying Pinecone. The first attempt revealed the installed SDK's ListItem ID representation; it retained the previous keyword corpus, and both migration and document discovery were corrected and tested for legacy/current representations. Publication settings were preserved; unreviewed existing documents remain private. A live retrieval-only check using the fixed chemistry term `chemistry` returned five keyword-only chunks after semantic candidates were not admitted, demonstrating independent keyword recall and remote ID/text validation. It made a small query-embedding request; no Groq answer was generated. This is functional validation, not a representative answer-quality or latency benchmark.

The separate loopback development preview showed the hybrid mode, 89 indexed chunks and the rebuild control. Evidence: `hybrid-index-preview.png`. Browser inspection of the existing localhost:8501 tab remains unavailable under the browser tool's URL policy; service health is checked separately. Docker became unavailable during final verification, was restarted using its installed CLI, and all 86 Linux checks were collected again before the update. Existing volumes/data were retained. The prior campus source archive is kept as `documind-campus-before-hybrid.zip`; the original Downloads backup remains untouched.

## Campus admin and student upgrade

Verified October 5, 2026: **67/67 offline checks passed on Windows Python 3.12 and in the Linux campus Docker image**. The 18 additional campus checks cover verified UCI claims and the explicit admin allowlist, default-closed access, student-only UI, admin permission checks, private/unknown document exclusion, Pinecone filtering and post-filtering, publication changes during generation, safe source labels, audience-separated cache scopes, exact repeats bypassing classifier/embedding/generation, privacy and safety failures, redaction before indexing, batch limits/partial submission, configurable cache policies and generated OAuth configuration. Existing Parts 1–4 tests run alongside these checks.

Actual isolated Redis tests passed on Windows and in Linux: FIFO/LRU/LFU retention and atomic capacity, expiry-only mode, TTL, corpus revision, cache disabling/clearing and per-user rate limiting. Redis/Celery integration passed in the final Linux image with staged-file/progress/success/failure/cleanup and shared Phase 4 accounting checks; provider/vector calls were mocked. Disposable test Redis services were used separately from the real ingestion broker.

Small live Groq fixtures passed the student input classifier for chemistry, unrelated sports, personal-data requests and prompt injection; the output gate accepted a water-formula answer and rejected a personal name/address fixture. Test telemetry was isolated and no Pinecone vectors were read or written. These fixtures do not prove universal jailbreak resistance, comprehensive PII detection or research-answer quality.

Local app and worker were updated to `documind-campus:latest` after confirming no active/reserved jobs and an empty named ingestion queue. Existing broker volume, uploads and data were retained. Streamlit health returns `ok`, both Redis services return `PONG`, and one worker answers `inspect ping`. Both local and cloud Compose configurations validate; cloud configuration was checked using placeholder example credentials. The cloud stack has **not** been deployed, ARM execution has not been tested, and real Google/UCI login still requires client credentials and a provider sign-in test.

The separate localhost:8503 development preview was visually checked for student chat, batch uploads/private-document controls, cache retention settings and admin logs/Redis monitoring. Screenshots are retained in local evidence as `campus-student-preview.png`, `campus-documents-preview.png` and `campus-redis-preview.png`. This is a local admin preview; actual student authorization is additionally exercised by Streamlit tests. Browser access to the existing localhost:8501 tab remains unavailable under the browser tool's URL policy; its running container was verified through service health instead.

The original working Part 4 distributable was copied to Downloads before editing and its SHA-256 checksum compared with the source archive. The campus distributable is built from an explicit source/documentation allowlist and excludes credentials, uploads, vector data and generated OAuth secrets.

## Earlier tutorial phases

Verified October 5, 2026. Parts 1–2 were tested with Python 3.14; Parts 3–4 use a separate Python 3.12 environment with RAGAS 0.4.2.

**49/49 offline checks passed on Windows Python 3.12 and in the Part 4 Linux image**, covering the existing parsing/queue behavior plus Parts 3–4. After the final database-path and currency-label adjustments, all 10 Part 4 checks passed again on both platforms. Coverage includes:
- Real PDF page text and blank-file rejection.
- Token windows, overlap validation and source metadata.
- Generated PPTX text, tables and speaker notes.
- Generated DOCX paragraphs, table order and headers.
- Multiple MOL2 molecules, coordinate/charge validation, counts and bond references.
- CIF quoted/multiline strings, uncertainty notation, missing values, loops, save frames and multiple blocks.
- Chemistry chunking that preserves complete rows and repeats identifying context.
- Legacy PPT edit history: latest text wins; deleted and obsolete slide text are excluded.
- Pinecone passage versus query embedding parameters, 96-text batches, response validation.
- Pinecone upsert batches, namespace isolation, retrieval/deletion filters and index compatibility.
- Pipeline progress, failures, streamed/non-streamed answers and citation prompts.
- Streamlit startup with missing credentials and disabled upload/ask actions.
- Streamlit startup with configured keys makes no provider requests.
- Celery JSON configuration, one-hour result lifetime and prefetch setting.
- Managed upload staging, path containment, worker cleanup and publication ambiguity.
- Correct app binding and queued/started/progress/success/failure/revoked state mapping.
- Queue UI displays success/error summaries and preserves previous answers.
- Input guardrails block before provider calls; monitoring redacts personal information.
- Chemical rows/coordinates survive PII checks; output redaction handles values spanning streamed tokens.
- Cache hits retain sources and bypass retrieval/generation; document filter, top-k and model changes alter scope.
- Numeric/negated/chemical questions are not conflated by the tested cache constraints.
- Document removal and partial upsert failure invalidate old answers; generation failure cannot cache a partial answer.
- No-evidence retrieval avoids generation; lexical scores, P95 latency and baseline/drift calculations are checked.
- RAGAS JSON schemas are validated before API calls; evaluation answer generation bypasses cache.
- RAGAS receives validated sample/reference fields and fresh metrics; failed cells remain missing in JSON/CSV.
- CSV filenames are contained and text is escaped against formula execution.
- Streamlit displays blocked answers and partial RAGAS reports, retaining reports through refresh.
- Groq provider-reported prompt/completion/reasoning usage, final streamed x_groq usage-only chunks, and the provider prompt-cache discount.
- Semantic answer-cache events record zero Groq tokens/cost while retaining query embedding costs.
- Failed/interrupted generation has unknown cost if provider usage is unavailable; partial answers are not cached.
- Failed ingestion retains already incurred embedding costs and does not inflate successful document counts.
- Consistent rolling UTC cutoffs, daily costs/tokens, latency excluding answer-cache hits, and the recent total_tokens alias.
- Unknown models, configurable rates and estimated token-count labels are checked.
- Disabled/unavailable monitoring does not break answers; concurrent app/worker-style writes share SQLite.
- Empty and populated Dashboard states display correctly, including unknown-cost warnings.

**Actual Redis/Celery integration passed** against an isolated Redis 8 container: a submitted file remains staged before worker startup; the backend reports PROGRESS at 40%; CIF ingestion returns SUCCESS and removes the upload; malformed MOL2 returns a normally decoded FAILURE and is also cleaned. Embedding and vector calls are mocked in this integration check, so it does not consume API credits or write a Pinecone index. The test is tests/redis_integration.py and uses an isolated queue on localhost:6381.

Docker Compose configuration is validated without emitting credentials. The Linux application image is built from the pinned dependencies and excludes .env and staged uploads.
The same Redis/Celery integration also passed inside that Linux image. The image's Streamlit UI was opened on localhost and verified to show the six upload formats, background toggle, Job queue, automatic updates and job-ID lookup. Temporary test containers were stopped after verification.

For Part 3, the Redis/Celery integration passed again with isolated query/cache storage. The updated Streamlit interface was visually checked in the local Python 3.12 preview: all five tabs, six upload formats, the truthful insufficient-drift-baseline message, JSON template download and 5 MB evaluation upload limit. A snapshot export error in Docker was resolved by rebuilding a single shared image for app and worker. Final Compose services are running on localhost:8501; Redis ping succeeds and Celery inspect ping returns one worker. The direct browser binding to the existing 8501 tab was blocked by the browser tool's URL policy, so no successful browser opening of that final container endpoint is claimed. Service health and the identical image's 39 checks were verified separately.

For Part 4, the actual Redis/Celery integration passed in Linux against a disposable Redis on localhost:6381, additionally asserting that one successful CIF ingestion and one failed MOL2 ingestion appear in Phase 4 SQLite metrics. No model/vector calls were made in that test. The test container was removed afterward. The real application queue was confirmed empty before updating the app and worker to documind-phase4:latest; its Redis volume and shared uploads/data were retained. Final Streamlit health returns ok, one worker answers Celery inspect ping, and Redis returns PONG.

The separate localhost:8503 development preview was visually verified: six tabs, the six upload extensions, Phase 4 sidebar, 7-day default window, all eight metric cards, cost coverage labels and the truthful empty-history state. The screenshot is retained in local evidence as part4-dashboard-preview.png. This does not claim a browser verification of the existing localhost:8501 tab. New monitoring starts after the upgrade; old Part 1–3 usage is not fabricated.

Legacy PPT extraction was also run on the actual binary [Apache POI basic_test_ppt_file.ppt fixture](https://github.com/apache/poi/blob/trunk/test-data/slideshow/basic_test_ppt_file.ppt): both slides and their expected text were recovered. The external fixture is kept in local evidence and excluded from the application ZIP.

**Live provider checks passed** with the locally configured credentials:
- Pinecone passage embedding, 1024 dimensions.
- Pinecone query embedding, 1024 dimensions.
- Groq streamed answer using openai/gpt-oss-20b.
- One-row RAGAS evaluation using Groq openai/gpt-oss-20b and Pinecone embeddings: faithfulness 1.0, answer relevancy 1.0, context precision approximately 1.0 and context recall 1.0; detailed CSV created. This deliberately simple water-formula fixture verifies provider/metric integration, not quality on the user's documents. No OpenAI API key was used and no Pinecone index was read or written.
- Part 4 real accounting smoke test: one Pinecone query embedding plus streaming and non-streaming Groq answers. All three events used provider-reported tokens, with 688 Groq tokens and 10 embedding tokens in this run; known estimated cost was USD 0.000083. Test telemetry was isolated in a temporary database. No index reads or writes occurred. Counts/cost vary between runs; this is not a charge or account-spend statement.

Pinecone's model metadata confirms llama-text-embed-v2 defaults to 1024 dimensions, supports 2048 input tokens and at most 96 texts per embedding request. These live checks made small inference requests; they did not create an index, upsert documents or delete data. Index persistence is covered by mocked SDK-boundary checks, not a live end-to-end database test.

Exact Python 3.12 dependency versions are in requirements-tested.txt, and pip check passes. Public cl100k_base and o200k_base vocabularies are cached for local testing and baked into Docker. Source files compile and ZIP integrity/secret exclusion are checked during packaging.

Limits: no OCR or embedded chart/object extraction; legacy PPT notes are omitted. Chemical files are searched as structured text, not analyzed with a chemistry engine. Regex guardrails, citation-format checks and lexical monitoring cannot prove factual correctness. Semantic cache matches can be imperfect and outside index edits need manual cache clearing. RAGAS judge results are model/reference-dependent. See PHASE3_NOTES.md for the reconstruction's omissions, corrections and runtime choice.

Phase 4 costs explicitly exclude RAGAS judge requests and provider account/database charges. Unknown events are flagged and fallback tokens are labeled estimated. SQLite telemetry can be missing when storage fails, grows until manually archived, and cannot reconstruct unreported retry or interrupted-call charges. See PHASE4_NOTES.md for the covered operations, default rate sources and settings.
