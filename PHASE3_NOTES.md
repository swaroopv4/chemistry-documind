# Phase 3 extraction and adaptations

Source: [Enterprise RAG System — Phase 3](https://www.youtube.com/watch?v=CaZQ3uq5SXE). The 1:24:28 video's full auto-generated transcript and coding screens were reviewed. This extends the existing reconstruction; it is not a byte-identical copy of an unpublished repository. The actual spoken sequence differs from the description's chapter timings.

| Video sequence | Implementation |
|---|---|
| 0:00–23:06: query logging, lexical score, summaries and drift | phases/phase3_hard/evaluation.py |
| 23:11–41:19: RAGAS metrics, reference dataset, report export | phases/phase3_hard/ragas_eval.py |
| 41:24–55:02: input patterns, PII, citation check | phases/phase3_hard/guardrails.py |
| 55:03–1:14:58: guardrail/cache/logging integration | core/pipeline.py; QueryResult cache and latency fields |
| 1:15:02–1:19:45: package, UI changes and fixes | phases/phase3_hard package; two evaluation tabs |
| 1:20:00–1:24:28: off-topic/cache demo and JSON benchmark | cache feedback, monitoring, JSON upload and downloadable CSV |

The tutorial imports a semantic cache but does not show its implementation. cache.py and storage.py complete that missing piece using local SQLite, shared between Docker app and worker. Cache entries retain the original sources, expire after one hour, and are scoped to document filter, top-k, provider credentials, index/namespace, model, prompt, guardrail settings and corpus revision. Document writes/removals suppress cache during mutation, invalidate before and after even a partial write failure, and allow a 30-second consistency window. Outside edits to Pinecone cannot automatically invalidate local cache: clear it after changes made outside this app.

The tutorial's 0.92 semantic threshold is retained. Numbers and negation must match for reuse. For MOL2/CIF contexts, the normalized question must match exactly; chemical identifiers or site names can otherwise produce misleadingly similar embeddings. A semantic match is not proof that two questions have identical meaning. The Ask panel shows the matched cached question and source locations.

## Keys

The video's evaluator uses its existing OpenAI key with gpt-4o-mini and text-embedding-3-small. This customized app explicitly uses **GROQ_API_KEY** for answers and the RAGAS judge, and **PINECONE_API_KEY** for retrieval and relevance embeddings. No new key is required. There is no OpenAI endpoint fallback, and no RAGAS cloud account or LangSmith key is needed for the local report workflow. Redis connection settings remain from Phase 2.

RAGAS evaluation makes additional inference calls. RAGAS_GROQ_MODEL defaults to openai/gpt-oss-20b. Despite that model's name, requests go to Groq. Judge scores depend on that model and are not directly interchangeable with the video's OpenAI-based numbers.

## Corrections and limits

- The video labels a word-overlap heuristic "faithfulness". The compatible log field is retained, but UI calls it **lexical grounding**. RAGAS faithfulness is a separate judge-based metric. Neither certifies scientific correctness.
- Guardrails use recognizable instruction-override patterns, conservative PII redaction and a soft citation-format warning. They do not detect every injection or every type of personal information. Chemical coordinates and uncertainty notation are preserved. Labelled phone numbers, email, PAN, Luhn-valid card numbers and recognizable provider keys are redacted from guarded questions/context/answers and monitoring text.
- Query-time redaction does not anonymize uploads: extracted document text is sent to Pinecone for embedding/storage during ingestion. Source document names are retained for citations.
- Obvious off-topic requests are blocked before provider calls. Retrieval below MIN_RETRIEVAL_SCORE (default 0.25) returns a no-evidence message without calling Groq. Similarity thresholds are workload-dependent heuristics; legitimate questions may need a lower setting. They do not establish that an answer is supported.
- With guardrails enabled, the full streamed answer is buffered, redacted and citation-checked **before** display. This avoids emitting PII that spans token boundaries, but delays the first text. Turning guardrails off restores token streaming.
- Completed answers alone enter the cache and success log. Generation failures cannot populate partial answers. Cached responses are checked again; sources and cache metadata are retained in both query modes.
- RAGAS dataset validation remains enabled. The tutorial's global dtype-validation bypass is omitted. Evaluation uses SingleTurnSample/EvaluationDataset with question, answer, contexts and reference mapped explicitly. Each run gets fresh metrics and a separate evaluator thread with event-loop patching disabled.
- Failed RAGAS cells remain missing rather than becoming zero or producing a false success message. UI marks partial reports and averages only successful cells. CSV and JSON report filenames are unique and user-supplied names are sanitized.
- Drift needs two windows of fresh answered queries (default 100 total), then compares lexical grounding and retrieval similarity. Cache hits, blocked inputs and no-evidence refusals are excluded. Query mix, model changes and document changes can affect these trends; absence of alerts does not prove no degradation.
- Cache/monitoring/report storage stays in the application's ignored data directory, shared with the worker. SQLite caps query rows at 10,000 and cache rows at 500. The inspectable JSONL log is append-only; manage retention locally. These files contain question/answer text and are excluded from ZIP and Docker build context.
- Python **3.12** is used for Part 3 and Docker. The prior Python 3.14 environment encountered RAGAS/dependency incompatibilities. A separate .venv-phase3 keeps the compatible runtime isolated from the original chemistry application.

## Test set

Upload a JSON list like:

```json
[
  {
    "question": "What value of cell length a is reported?",
    "ground_truth": "Enter the verified value and units from your own document."
  }
]
```

Replace the example with independently verified answers from the documents already ingested. The app generates fresh answers with cache bypassed, then scores faithfulness, answer relevancy, context precision and context recall. A saved dataset may supply nonempty answer and contexts (a list of strings) for every row. Mixed schemas are rejected. Limit: 50 rows and a 5 MB upload. Start with a few short rows. Download the detailed CSV from the RAGAS tab; missing metrics are blank. CSV text is escaped to prevent formula execution in spreadsheet viewers.

References: [RAGAS evaluation API](https://docs.ragas.io/en/v0.4.2/references/evaluate/), [evaluator customization](https://docs.ragas.io/en/v0.3.2/extra/components/choose_evaluator_llm/).
