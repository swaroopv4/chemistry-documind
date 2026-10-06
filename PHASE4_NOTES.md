# Part 4 reconstruction and Groq adaptation

Reviewed [Production Grade AI Monitoring — Phase 4](https://www.youtube.com/watch?v=MZNJggB8-gY), Techknowledgehub, 51:07. The transcript and visible coding frames were used to reconstruct its pipeline. This is a working adaptation of the tutorial; it is not claimed to be a byte-for-byte copy of unpublished source. The folder visible in the video is `phases/phase4_obs`, preserved here.

## Video sequence

| Time | Tutorial step | Implemented location |
|---|---|---|
| 0:00–3:36 | Metrics store, database path, token prices, SQLite helper | phases/phase4_obs/metrics_store.py |
| 5:46–7:33 | LLM calls, retrievals and ingestion schema | metrics_store.py |
| 7:33–12:51 | Cost calculation and event logging | metrics_store.py |
| 12:51–19:54 | Rolling summary, daily cost/calls, latency, recent calls | metrics_store.py |
| 19:54–29:10 | Token counting and safe tracking helpers | phases/phase4_obs/tracker.py |
| 29:10–40:37 | Hook ingestion, cache, retrieval and both generation modes | core/pipeline.py, core/generation.py, core/embeddings.py |
| 40:37–44:47 | Dashboard window, refresh, cost/query/latency charts | ui/app.py |
| 44:47–51:07 | Demo and recent-call total_tokens correction | Dashboard and validation checks |

## API keys

No new key is needed. The adapted application still uses only GROQ_API_KEY and PINECONE_API_KEY. SQLite is built into Python; the dashboard uses existing Streamlit/Pandas dependencies. The tutorial's OpenAI prices/client are replaced with Groq pricing and Groq's compatible endpoint. Its OpenAI embedding estimate is replaced with separately recorded Pinecone inference batches. Credentials and user telemetry are excluded from the ZIP.

## Accounting corrections

Generation is tracked at the actual SDK boundary, before guardrails modify the displayed answer. Non-streaming response usage and the final streamed usage chunk are read, including Groq's `x_groq.usage` extension. Hidden reasoning completion tokens are included when reported. If usage is missing, the complete system/context/question prompt and raw visible answer are counted with cl100k_base and labeled estimated. Interrupted/failed requests without provider usage have unknown cost rather than a false zero. SDK retry charges that are not exposed by the response cannot be reconstructed.

Semantic answer-cache hits record zero Groq tokens/cost and bypass retrieval/generation. Their Pinecone query embedding is still recorded. This is distinct from Groq's provider prompt cache: reported cached input tokens receive the documented 50% input discount. Cache hit rate uses recorded Groq request/cache events, excluding blocked inputs and no-evidence responses. A blocked input makes no model/embedding call.

Embedding calls are logged per batch using Pinecone's reported `usage.total_tokens`, with a labeled fallback when absent. Purposes distinguish ingestion, query and RAGAS evaluation embeddings. Ingestion's local chunk token count is not used to bill embeddings, and its totals are not added a second time to costs. Paid batches remain recorded if a later batch or vector upsert fails. Ingestion counts distinguish successful documents from failed attempts. Retrieval latency covers vector search only; the Phase 3 Ask/Eval latency still covers the complete query.

All summaries, charts and recent tables use the same rolling UTC cutoff. Unknown model rates remain NULL and trigger a warning; known cost totals sum priced events only. The recent-call total_tokens alias is present from the outset. The shared SQLite database uses WAL, a bounded lock timeout, transactions, timestamp indexes and close/rollback handling. Monitoring failures log only the exception type and leave answers/ingestion usable; the Dashboard shows storage failures. No raw prompts, contexts, answers or provider error bodies are saved in this database. Question snippets and filenames receive the existing PII/credential redaction. Those heuristics are not a complete privacy guarantee. The original Phase 3 query logging remains separate.

## Default rates and scope

Verified October 5, 2026. Standard on-demand USD per million tokens:

| Provider/model | Input | Output |
|---|---:|---:|
| Groq openai/gpt-oss-20b | 0.075 | 0.30 |
| Groq openai/gpt-oss-120b | 0.15 | 0.60 |
| Pinecone llama-text-embed-v2 | 0.16 | — |

Sources: [Groq model rates](https://console.groq.com/docs/models), [Groq prompt-cache discount and usage](https://console.groq.com/docs/prompt-caching), [Pinecone model inference rate](https://www.pinecone.io/learn/nvidia-for-pinecone-inference/), [Pinecone plans and included usage](https://www.pinecone.io/pricing/).

Override rates in .env with GROQ_PRICES_JSON (model to input/output rate pair) and PINECONE_EMBEDDING_USD_PER_MILLION. The rates apply when each event is recorded; changing configuration does not rewrite historical estimates. The default dashboard covers Groq document-answer requests, including fresh evaluation answers, and Pinecone embedding requests. RAGAS judge calls use their separate LangChain client and are explicitly excluded. Vector storage/read/write charges, subscription/plan minimums, free-tier allowances, credits and taxes are also excluded. This dashboard is not an invoice or a complete account-spend report.

## Persistence and limits

By default metrics live in data/documind.db, shared by the app and worker through Compose's data mount. DOCUMIND_DB can override the path; configure both processes identically. OBSERVABILITY_ENABLED defaults to true and can disable new tracking. Existing history remains viewable when disabled. Events start after the upgrade; old Part 1–3 tokens/costs cannot be recovered. SQLite history grows until manually archived; this local app has no retention scheduler, authentication, access roles, tracing backend or account reconciliation. Existing Groq/Pinecone configuration and all six accepted upload formats remain supported.

Tests: tests/phase4_validation.py checks actual SDK-shaped usage, streamed usage-only chunks, interrupted streams, caching/embedding accounting, failed ingestion costs, UTC windows, unknown pricing, disabled/unavailable monitoring, concurrent writes and empty/populated dashboards. tests/phase4_service_check.py --live makes tiny public-fixture inference calls without index reads/writes and verifies real provider token accounting. The Redis integration also asserts successful/failed worker ingestion appears in shared Phase 4 storage.
