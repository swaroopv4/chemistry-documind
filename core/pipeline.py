from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import os
import sqlite3
import time

from core.ingestion import ingest_file, count_tokens
from core.embeddings import embed_chunks, embed_query
from core.vector_store import upsert_chunks, query_index, delete_document, get_index_stats
from core.generation import generate_answer
from phases.phase3_hard import cache, guardrails, evaluation
from phases.phase4_obs import tracker


@dataclass
class IngestResult:
    doc_name: str
    chunk_count: int
    page_count: int
    total_tokens: int
    status: str = "success"
    error: str = ""
    version: int = 0


@dataclass
class QueryResult:
    answer: str
    sources: list[dict]
    query: str
    top_k: int
    cache_hit: bool = False
    latency_ms: float = 0.
    cache_similarity: float | None = None
    cached_question: str = ""
    status: str = "answered"
    feedback_id: str = ''


class AnswerStream:
    """Preserve the original (iterator, sources) API with completion metadata."""
    def __init__(self, iterator, result):
        self.iterator, self.result = iter(iterator), result

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)


def ingest_document(
    pdf_path: str | Path,
    chunk_size: int = 400,
    chunk_overlap: int = 50,
    progress_callback=None,
    job_id=None,
    principal=None,
) -> IngestResult:
    pdf_path = Path(pdf_path)
    started = time.perf_counter()
    claimed = False
    try:
        from core import versions
        planned = versions.prepare_path(pdf_path,chunk_size,chunk_overlap,job_id)
        with versions.document_lock(planned['name']):
            claimed = True
            versions.set_state(planned['name'],'processing')
            if planned.get('family'):
                from core.access import Principal
                versions.stage_private(planned,principal or Principal('trusted-ingestion','admin',local_preview=True))
            if progress_callback:
                progress_callback('Extracting and chunking',.1)
            chunks = ingest_file(pdf_path,chunk_size,chunk_overlap)
            for chunk in chunks:
                chunk.doc_name = planned['name']
                redacted = guardrails.redact_pii(chunk.text)[0]
                if redacted!=chunk.text:
                    chunk.text,chunk.token_count = redacted,count_tokens(redacted)
            if progress_callback:
                progress_callback('Generating embeddings',.4)
            embeddings = embed_chunks(chunks)
            if progress_callback:
                progress_callback('Uploading to the vector store',.7)
            with cache.corpus_update():
                from core import keyword_index
                keyword_index.remove_document(planned['name'])
                upsert_chunks(chunks, embeddings)
                keyword_index.replace_document(planned['name'], chunks)
            versions.set_state(planned['name'],'success')
        if progress_callback:
            progress_callback("Done", 1.0)
        pages = sorted(set(c.page_num for c in chunks))
        from core.catalog import record_ingestion
        record_ingestion(planned['name'], len(chunks),len({c.page_num for c in chunks if c.metadata.get('ocr')}))
        result = IngestResult(
            doc_name=planned['name'],version=planned['version'],
            chunk_count=len(chunks),
            page_count=len(pages),
            total_tokens=sum(c.token_count for c in chunks),
        )
    except Exception as e:
        if claimed:
            versions.set_state(planned['name'],'failed')
        result = IngestResult(
            doc_name=pdf_path.name, chunk_count=0, page_count=0,
            total_tokens=0, status="error", error=str(e),
        )
        if isinstance(e,versions.ExistingUpload):
            from core.catalog import list_documents
            stored = next((row for row in list_documents() if row['name']==e.document),{})
            result = IngestResult(e.document,stored.get('chunks',0),0,0,status='duplicate',error=str(e))
    tracker.safe_track(tracker.track_ingestion, doc_name=result.doc_name,
        chunk_count=result.chunk_count, page_count=result.page_count,
        total_tokens=result.total_tokens, duration_ms=(time.perf_counter()-started)*1000,
        status=result.status)
    return result


# The handwritten portion spells this ingestion_document; the pasted UI uses ingest_document.
ingestion_document = ingest_document


def query_document(
    question: str,
    top_k: int = 5,
    stream: bool = True,
    filter_doc: str | None = None,
    use_cache: bool = True,
    audience: str = "admin",
    answer_validator=None,
):
    started = time.perf_counter()
    question = question.strip()
    if audience not in {"admin", "student"}:
        raise ValueError("Unknown audience")
    use_guardrails = audience == "student" or guardrails.enabled()
    if not question:
        raise ValueError("Question cannot be empty.")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    def finish(result):
        result.latency_ms = round((time.perf_counter() - started) * 1000, 2)
        try:
            from core.retrieval import dense_mean, mode
            evaluation.log_query(evaluation.QueryMetrics(
                result.query, result.answer, len(result.sources),
                dense_mean(result.sources),
                evaluation.score_faithfulness(result.answer, result.sources),
                result.latency_ms, result.cache_hit, time.time(), result.status, mode(),
                sum(s.get('retrieval_method') in {'keyword','both'} for s in result.sources)))
        except (OSError, sqlite3.Error):
            logging.getLogger(__name__).warning("Query monitoring storage is unavailable")
        return result

    def respond(result):
        finish(result)
        return (AnswerStream(iter([result.answer]), result), result.sources) if stream else result

    if use_guardrails:
        try:
            question = guardrails.check_input(question)
        except guardrails.GuardrailError as error:
            return respond(QueryResult(f"Blocked: {error.reason}", [], guardrails.redact_pii(question)[0], top_k, status="blocked"))
    if audience == 'student':
        from core import catalog
        from core.settings import get_settings
        allowed_docs = list(catalog.published())
        if not allowed_docs:
            return respond(QueryResult("The administrator has not published any reviewed chemistry documents yet.", [], question, top_k, status='no_evidence'))
    q_embedding = embed_query(question)
    scope = cache.current_scope(top_k, filter_doc, audience) if use_cache else None
    semantic_enabled = audience != 'student' or get_settings()['student_semantic_cache']
    hit = cache.cache_lookup(q_embedding, question, scope) if semantic_enabled else None
    if hit and audience == 'student' and not catalog.sources_allowed(hit.sources):
        hit = None
    if hit:
        answer = guardrails.check_output(hit.answer, hit.sources) if use_guardrails else hit.answer
        from core.generation import LLM_MODEL
        tracker.safe_track(tracker.track_llm_call, messages=[], answer=answer, model=LLM_MODEL,
            latency_ms=(time.perf_counter()-started)*1000, cache_hit=True, question=question)
        return respond(QueryResult(answer, hit.sources, question, top_k,
                                   cache_hit=True, cache_similarity=hit.similarity, cached_question=hit.question))
    retrieval_started, sources, retrieval_status = time.perf_counter(), [], "error"
    try:
        from core import retrieval
        if retrieval.mode() == 'hybrid':
            sources = retrieval.retrieve(question, q_embedding, top_k, filter_doc,
                allowed_docs if audience == 'student' else None, dense_search=query_index)
            if audience == 'student':
                sources = catalog.student_sources(sources)
        elif audience == 'student':
            sources = query_index(q_embedding, top_k=top_k, filter_doc=filter_doc, allowed_docs=allowed_docs)
            sources = catalog.student_sources(sources)
        else:
            sources = query_index(q_embedding, top_k=top_k, filter_doc=filter_doc)
        retrieval_status = "success"
    finally:
        tracker.safe_track(tracker.track_retrieval, sources=sources, top_k=top_k,
            latency_ms=(time.perf_counter()-retrieval_started)*1000, status=retrieval_status)
    if use_guardrails:
        minimum = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.25"))
        if not sources or not any(s.get('score',0.) >= minimum or s.get('lexical_coverage',0.) >= .5 for s in sources):
            return respond(QueryResult("I couldn't find relevant evidence in the uploaded documents. Try a more specific document question.", [], question, top_k, status="no_evidence"))
        sources = [{**s, "text": guardrails.redact_pii(s.get("text", ""))[0]} for s in sources]

    from core.generation import bounded_sources
    sources = bounded_sources(sources)
    result = QueryResult("", sources, question, top_k)
    def complete(answer):
        try:
            if audience == 'student' and not catalog.sources_allowed(sources):
                raise guardrails.GuardrailError("A source is no longer available for student access. Please ask again.", 'access_changed')
            result.answer = guardrails.check_output(answer, sources) if use_guardrails else answer
            if answer_validator:
                result.answer = answer_validator(result.answer, sources)
            if audience == 'student' and not catalog.sources_allowed(sources):
                raise guardrails.GuardrailError("A source is no longer available for student access. Please ask again.", 'access_changed')
        except guardrails.GuardrailError as error:
            result.answer, result.sources, result.status = error.reason, [], error.code
            finish(result)
            return result.answer
        except Exception:
            if audience != 'student':
                raise
            result.answer, result.sources, result.status = "The answer safety check is temporarily unavailable. Please try again shortly.", [], 'guard_unavailable'
            finish(result)
            return result.answer
        cache.cache_store(q_embedding, question, result.answer, sources, scope, top_k, filter_doc, audience)
        finish(result)
        return result.answer

    if stream:
        def checked_stream():
            raw = generate_answer(question, sources, stream=True)
            if use_guardrails:
                # Validate/redact before display, even when a PII value spans tokens.
                answer = complete("".join(raw))
                yield answer
            else:
                parts = []
                for token in raw:
                    parts.append(token)
                    yield token
                complete("".join(parts))
        return AnswerStream(checked_stream(), result), sources
    answer = generate_answer(question, sources, stream=False)
    complete(answer)
    return result


def remove_document(doc_name: str) -> None:
    from core import versions
    with versions.document_lock(doc_name),cache.corpus_update():
        from core import keyword_index
        keyword_index.remove_document(doc_name)
        delete_document(doc_name)
        versions.set_state(doc_name,'deleted')


def index_stats() -> dict:
    return get_index_stats()


def phase3_available() -> bool:
    return True


def phase4_available() -> bool:
    return True


def async_available() -> bool:
    try:
        from phases.phase2_async.job_status import check_connection
        return check_connection()
    except ImportError:
        return False


def submit_ingest(path: str | Path, chunk_size: int = 400, chunk_overlap: int = 50) -> str:
    from phases.phase2_async.job_status import submit_ingest_job
    return submit_ingest_job(str(path), chunk_size, chunk_overlap)


# Name used by the pasted Phase 2 UI in the tutorial.
submit_ingest_job = submit_ingest


def submit_uploaded_document(filename: str, content: bytes,
                             chunk_size: int = 400, chunk_overlap: int = 50,principal=None) -> str:
    from phases.phase2_async.job_status import submit_uploaded_job,JobSubmissionError
    from core import versions
    from core.access import Principal
    if principal is not None:
        from core.access import require_admin
        require_admin(principal)
    planned = versions.plan(filename,content,chunk_size,chunk_overlap)
    try:
        versions.stage_private(planned,principal or Principal('trusted-ingestion','admin',local_preview=True))
        return submit_uploaded_job(planned['name'],content,chunk_size,chunk_overlap,job_id=planned['job_id'])
    except JobSubmissionError:
        versions.set_state(planned['name'],'uncertain')
        raise
    except Exception:
        versions.set_state(planned['name'],'failed')
        raise


def get_ingest_status(job_id: str):
    from phases.phase2_async.job_status import get_job_status
    return get_job_status(job_id)
