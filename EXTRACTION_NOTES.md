# Evidence, corrections, and reconstruction limits

## Current customization

The running application now includes Phase 2 Celery/Redis background jobs, Groq answers, Pinecone hosted embeddings and PDF/PPT/PPTX/DOCX/MOL2/CIF ingestion as requested. The notes below describe the original Phase 1 extraction, including its former OpenAI/PDF choices and original verification status. See PHASE2_NOTES.md, README.md, PIPELINE.md and VALIDATION.md for current behavior and results.

The original video is [1UIFg23U8xg](https://www.youtube.com/watch?v=1UIFg23U8xg).
Timestamp links below use the actual coding sequence. The suggested chapters in
the description have different timings and do not reliably locate these sections.

## Evidence map

| File / block | Coding interval | Useful inspected frames |
|---|---|---|
| Folder structure and requirements | [00:12–02:36](https://www.youtube.com/watch?v=1UIFg23U8xg&t=12s) | 00:50 |
| Environment variables | [02:40–04:23](https://www.youtube.com/watch?v=1UIFg23U8xg&t=160s) | Transcript; defaults also visible in vector_store.py |
| ingestion.py | [04:28–20:32](https://www.youtube.com/watch?v=1UIFg23U8xg&t=268s) | 13:10, 13:50, 15:32, 16:55, 20:30, 20:40 |
| embeddings.py | [20:34–34:17](https://www.youtube.com/watch?v=1UIFg23U8xg&t=1234s) | 30:55, 33:55, 34:10; imports visible again at 1:16:40 |
| vector_store.py | [34:21–52:00](https://www.youtube.com/watch?v=1UIFg23U8xg&t=2061s) | 38:10, 42:15, 44:10, 46:50, 51:58 |
| generation.py | [52:04–1:03:04](https://www.youtube.com/watch?v=1UIFg23U8xg&t=3124s) | 53:40, 57:25, 1:00:30, 1:02:05, 1:03:00 |
| pipeline.py | [1:03:10–1:15:44](https://www.youtube.com/watch?v=1UIFg23U8xg&t=3790s) | 1:08:00, 1:10:00, 1:13:00, 1:14:10, 1:15:00 |
| core/__init__.py | [1:15:53–1:16:13](https://www.youtube.com/watch?v=1UIFg23U8xg&t=4553s) | Transcript confirms package marker; explanatory docstring reconstructed |
| ui/app.py | [1:17:50–1:19:18](https://www.youtube.com/watch?v=1UIFg23U8xg&t=4670s) | 1:18:00, 1:18:40, 1:19:05, 1:19:20 |
| pypdf omission discovered | [1:20:01–1:20:31](https://www.youtube.com/watch?v=1UIFg23U8xg&t=4801s) | Transcript |

Selected source frames are stored in the enclosing `evidence/frames` directory,
named by elapsed seconds. The runnable ZIP contains the source project and notes,
not the full video or third-party package directories.

## Corrections to visible errors

These are deliberate differences from the displayed code, not claims that the
author's final repository contains them.

| Module | On-screen issue | Reconstruction |
|---|---|---|
| ingestion | `Pdfreader`, `readers.page` | `PdfReader`, `reader.pages` |
| ingestion | `return pages` appears indented inside the page loop | Return after the loop so all pages are extracted |
| ingestion | `feild(default_factory=dict)` | `field(default_factory=dict)` |
| embeddings | type-only import `core.ingestion.py` | `core.ingestion` |
| embeddings | batch slices `text` while parameter is `texts` | Slice `texts` |
| embeddings | `embed_texts[texts, client]` | Function call `embed_texts(texts, client)` |
| embeddings | malformed query client annotation/call while typing | `client: OpenAI | None = None`; `embed_texts([query], client)[0]` |
| vector store | `list["chunk"]` | `list[Chunk]` |
| vector store | `index = get_index()` on the same line as function signature, followed by a multiline body | Normal multiline function body |
| vector store | delete filter uses `"doc.name"` and literal `"doc_name"` | Metadata field `"doc_name"` and argument value `doc_name` |
| vector store | stats assigns `index = get_index` | Call `get_index()` |
| generation | return occurs before closing the append call while typing | Close append; return after the loop |
| generation | defines `_empty` but calls `empty()` | Call `_empty()` |
| generation | user message labeled `system` | Label it `user` |
| pipeline | imports `cors.generation` | `core.generation` |
| pipeline | class `QueryResults`, later constructs `QueryResult`; `top_k = int` | Consistent `QueryResult`; annotated `top_k: int` |
| pipeline/UI | handwritten `ingestion_document`, UI imports `ingest_document` | `ingest_document` plus compatibility alias `ingestion_document` |
| pipeline/UI | handwritten callbacks pass only step text, pasted UI expects `(step, pct)` | Supply progress values 0.1, 0.4, 0.7, 1.0; values after 0.1 are reconstructed |

Ordinary typing mistakes that the author fixes before proceeding are normalized;
whitespace, wrapping, and comments are not exact replicas. Core algorithms,
metadata fields, batch sizes, model choices, prompt text, and UI layout were
recovered from frames. The requirements use `>=`, not exact version pins.

## Added safeguards / supporting files

- Validate `0 <= chunk_overlap < chunk_size`; the original sliders allow invalid
  combinations that otherwise make the chunking loop fail to advance.
- Validate equal counts of chunks and embeddings before upserting.
- Explicitly load this project's own `.env`, avoiding accidental parent-file lookup.
- Clean the temporary upload in a `finally` block.
- Give collapsed upload/question controls non-empty accessibility labels.
- Skip database access when credentials are missing during initial UI startup.
- Convert a null non-streaming completion to an empty string.
- Add `.env.example`, `.gitignore`, documentation, offline tests, and tested version
  pins. These files/support details are authored for this reconstruction.

## Unavailable or intentionally unreconstructed portions

- No GitHub repository contents were obtained; there is no byte-level comparison.
- The Phase 2 async folder appears in the later screen recording, but its internals
  are not explained or fully shown in this Phase 1 video. Only the original empty
  `phases/` placeholder is included.
- The sample PDF used in the demonstration is unavailable.
- Credentials are blank placeholders. No key shown in the video is copied or used.
- Live API requests have not been performed; index readiness, account permissions,
  quotas, model availability, and live answer quality remain unverified.
- Pinecone's document list is the video's zero-vector sampling approach, not a
  complete catalog. New index readiness waiting and full document listing would
  be changes beyond the visible algorithm.
