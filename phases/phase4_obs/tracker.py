from __future__ import annotations

import logging
import tiktoken

from phases.phase3_hard.guardrails import redact_pii
from phases.phase4_obs import metrics_store as store

_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text):
    return len(_ENCODING.encode(text, disallowed_special=()))


def field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def response_usage(response):
    # Groq's final stream chunk can carry x_groq.usage instead of usage.
    return field(response, "usage") or field(field(response, "x_groq", {}), "usage")


def safe_track(function, **kwargs):
    if not store.enabled():
        return
    try:
        function(**kwargs)
    except Exception as error:
        # Never log provider error bodies, raw prompts or credentials.
        logging.getLogger(__name__).warning("Observability write failed (%s)", type(error).__name__)


def track_llm_call(messages, answer, model, latency_ms, cache_hit=False,
                   question="", usage=None, status="success", purpose="qa"):
    if cache_hit:
        inp = out = cached = 0
        source, cost = "answer_cache", 0.
    elif usage is not None and field(usage, "prompt_tokens") is not None and field(usage, "completion_tokens") is not None:
        inp, out = int(field(usage, "prompt_tokens")), int(field(usage, "completion_tokens"))
        cached = int(field(field(usage, "prompt_tokens_details", {}), "cached_tokens", 0) or 0)
        source = "provider"
        cost = store.estimate_cost(model, inp, out, cached)
    else:
        inp = sum(count_tokens(m.get("content", "")) for m in messages)
        out, cached = count_tokens(answer), 0
        source = "estimated"
        # An interrupted request may have billed unseen output tokens.
        cost = store.estimate_cost(model, inp, out) if status == "success" else None
    store.log_llm_call(model=model, input_tokens=inp, output_tokens=out,
                       cached_input_tokens=cached, cost_usd=cost, latency_ms=latency_ms,
                       cache_hit=int(cache_hit), question=redact_pii(question)[0][:200],
                       token_source=source, status=status, purpose=purpose)


def track_embedding(model, texts, usage, latency_ms, purpose, status="success"):
    tokens = field(usage, "total_tokens")
    source = "provider" if tokens is not None else "estimated"
    tokens = int(tokens) if tokens is not None else sum(count_tokens(t) for t in texts)
    store.log_embedding(model=model, purpose=purpose, total_tokens=tokens,
                        cost_usd=store.embedding_cost(tokens) if source == "provider" or status == "success" else None,
                        latency_ms=latency_ms, token_source=source, status=status)


def track_retrieval(sources, latency_ms, top_k, status="success"):
    from core.retrieval import dense_mean
    store.log_retrieval(top_k=top_k, chunk_count=len(sources),
                        avg_score=dense_mean(sources),
                        latency_ms=latency_ms,
                        doc_name=redact_pii(sources[0].get("doc_name", ""))[0][:200] if sources else "",
                        status=status)


def track_ingestion(doc_name, chunk_count, page_count, total_tokens, duration_ms, status="success"):
    # Source/chunk counts are local cl100k estimates. Embedding API cost is stored
    # per batch in embeddings, including batches before a later ingestion failure.
    store.log_ingestion(doc_name=redact_pii(doc_name)[0][:200], chunk_count=chunk_count,
                        page_count=page_count, total_tokens=total_tokens,
                        duration_ms=duration_ms, status=status)
