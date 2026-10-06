# Campus readiness and operations

The local Docker application now includes shared AI budgets, strict source-citation checks, a chemistry retrieval benchmark, upload deduplication and versions, encrypted state backups, student feedback, short session memory and local scanned-PDF OCR. No additional AI service or API key was introduced.

## Account setup that remains

A new deployment requires its own Google OAuth client ID and client secret. Follow AUTH_SETUP.md and add them directly to the private `.env`; never send them in chat. `python deploy/prepare_local_auth.py` generates a missing local cookie secret without printing it. Restart the app afterward. Configure the exact administrator account through `ADMIN_EMAILS`; other verified managed `@uci.edu` accounts receive the student role.

Test a real administrator login, a real student login, logout, and rejection of an outside-UCI account. Readiness records verified sessions separately from local preview. Unit tests verify claim/domain/role boundaries but cannot substitute for real OAuth testing. Production refuses local-preview authentication and missing credentials.

Keep provider credentials private, rotate any exposed credentials through their provider consoles and update the ignored configuration. AI keys do not provide identity verification. There is no promise that prompts alone prevent every jailbreak: document isolation, reviewed publication, input/output checks and cache invalidation provide independent boundaries.

## Admin controls

- **Readiness:** shared limits for Groq request/token windows, embedding daily tokens, concurrency, timeouts, answer/context tokens, memory expiry and OCR pages; provider usage; student feedback exports.
- **Documents:** duplicate uploads are identified by bytes plus parser settings; changed uploads receive new filenames such as `guide__v2.pdf`. Previous versions are retained privately. Only successful versions can be published. Pending/uncertain jobs can be reconciled only when Redis confirms FAILURE or REVOKED; PENDING is not treated as failure.
- **Readiness:** configuration/live-login checks, encrypted backup download and an offline 32-case chemistry benchmark.

Default shared caps are 18 Groq requests/minute, 500/rolling day, 7,000 tokens/minute, 150,000/rolling day, 200,000 embedding tokens/day and two concurrent provider requests. Safety checks and RAGAS consume the same allowance as answers. Provider errors retain conservative reserved usage; known usage replaces reservations. Quota checks fail closed if storage is unavailable. These application caps do not change your provider plan or guarantee free billing. Reduce them for your actual account allowance.

Answer evidence uses complete passages within the context limit, with exact document/locator citation membership and a citation in every answer paragraph. Unknown or absent citations block the answer. Citation membership does not prove that a scientific claim follows from a passage; review evidence and run evaluations.

Student feedback belongs to a server-issued response and its signed-in owner. Admins can review helpful/incorrect/missing-information votes and optional comments. Response records expire after 90 days and are capped at 10,000. Notes and stored answers receive common-identifier redaction. Session memory contains the prior safe question for follow-ups, expires after ten minutes by default, and changes scope whenever source access, settings, credentials or corpus revisions change. It is not shared across users.

## Chemistry benchmark

`benchmarks/chemistry.json` contains 32 original educational question/passage/reference cases, including explicitly fictional experimental measurements. It is reference-fixture ground truth, not validation of uploaded private documents.

```sh
python deploy/benchmark.py --output data/reports/chemistry-offline.json
python deploy/benchmark.py --compare --output data/reports/chemistry-comparison.json
```

The first command runs BM25 without remote calls. The second explicitly uses two small Pinecone embedding batches, ranks vectors locally, and compares dense, BM25 and the same reciprocal-rank fusion used by the app. It does not write vectors or call Groq. Adapt cases to reviewed real document evidence before drawing conclusions about campus answer quality.

The current fixture comparison achieved recall@5 and MRR of 1.0 for all three methods. The examples are simple: this result does not demonstrate that hybrid is universally better. Reported latency covers ranking work and excludes embedding/network latency. Evaluation reports should be regenerated after corpus or retrieval changes.

## OCR

Docker installs Poppler and Tesseract; no OCR key or cloud service is needed. Only PDF pages without extractable text use OCR. Default limit: 20 scanned pages per file, with 30-second subprocess timeouts and bounded output. PPT/DOCX image OCR is not included.

OCR can misread chemical symbols, subscripts and numbers even at high word confidence. The test scan produced `H20` for `H2O`; extracted text is preserved without guessing a correction. OCR chunks carry confidence/provenance, model context and student sources flag scan uncertainty, and the admin publication screen requires checking the scan. Always inspect original chemical records before publication. Standalone Windows needs the two binaries installed; the provided Docker image contains them.

## Backup and recovery

```sh
python deploy/backup.py export data/backups/state.fernet
python deploy/backup.py verify data/backups/state.fernet
python deploy/backup.py restore data/backups/state.fernet --destination data/restored-state
```

Use a new archive filename and a new restore directory. Snapshots use SQLite's online backup and authenticated encryption, then validate manifest checksums, filenames and database integrity. Active/pending ingestion prevents backup. Files under data include policies, settings, keyword index, version metadata, feedback, budgets, SQLite metrics and local reports/logs. An external custom metrics path is rejected rather than silently omitted.

The encryption key is `BACKUP_ENCRYPTION_KEY` or `data/.backup-key`; save it separately and securely. The archive excludes that key, API/OAuth secrets, original uploads, remote Pinecone vectors and Redis queues. It is a state backup, not a full remote-vector backup. Preserve the persistent Redis volume/AOF and your Pinecone project separately.

Restoration never overwrites live data. Stop app/worker processes, verify the restored policies, copy the separate key securely or configure it, and point DOCUMIND_DATA_DIR to the restored directory. Clear answer caches and rebuild the keyword index from current Pinecone vectors before reopening student access. Do not remove the existing data until recovery is verified.

Always verify a backup by restoring to a new directory before relying on recovery. Private backups and restored state are excluded from source.

## Validation

108 regression checks run on Windows (one real-OCR check skipped when binaries are absent) and Linux Docker (all checks). Coverage includes concurrent budgets, sync/async usage and throttling, citation rejection, duplicate embedding prevention, publication/job races, feedback ownership, memory isolation, encrypted restoration/path checks, real OCR and both UI roles. The separate actual Redis/Celery test checks queue progress, success/failure cleanup and keyword indexing without model/vector API calls.

Public deployment and real OAuth login remain pending account setup. The local application is not exposed publicly.
