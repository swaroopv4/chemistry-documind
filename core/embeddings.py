from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from pinecone import Pinecone,RetryConfig
from phases.phase4_obs import tracker

if TYPE_CHECKING:
    from core.ingestion import Chunk

EMBEDDING_MODEL = "llama-text-embed-v2"
EMBEDDING_DIM = 1024
BATCH_SIZE = 96


def get_client() -> Pinecone:
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        raise EnvironmentError("PINECONE_API_KEY not found")
    from core.settings import get_settings
    return Pinecone(api_key=api_key,timeout=get_settings()['provider_timeout'],retry_config=RetryConfig(max_retries=0))


def embed_texts(texts: list[str], client: Pinecone | None = None,
                input_type: str = "passage", purpose: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    if client is None:
        client = get_client()
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        started, usage, status = time.perf_counter(), None, "error"
        from core.provider_limits import embedding_budget
        try:
            with embedding_budget(sum(tracker.count_tokens(text) for text in batch)) as lease:
                response = client.inference.embed(
                    model=EMBEDDING_MODEL, inputs=batch,
                    parameters={"input_type": input_type, "dimension": EMBEDDING_DIM,
                                "truncate": "NONE"},
                )
                measured = tracker.field(tracker.field(response,'usage'),'total_tokens')
                if isinstance(measured,int):
                    lease.usage = measured
            usage = tracker.field(response, "usage")
            batch_embeddings = [list(item.values) for item in response]
            if len(batch_embeddings) != len(batch) or any(
                len(vector) != EMBEDDING_DIM for vector in batch_embeddings
            ):
                raise ValueError("Pinecone returned incomplete or incompatible embeddings")
            status = "success"
        finally:
            tracker.safe_track(tracker.track_embedding, model=EMBEDDING_MODEL,
                texts=batch, usage=usage, latency_ms=(time.perf_counter()-started)*1000,
                purpose=purpose or ("query" if input_type == "query" else "ingestion"), status=status)
        all_embeddings.extend(batch_embeddings)
    return all_embeddings


def embed_chunks(chunks: list[Chunk], client: Pinecone | None = None) -> list[list[float]]:
    texts = [c.text for c in chunks]
    return embed_texts(texts, client)


def embed_query(query: str, client: Pinecone | None = None) -> list[float]:
    return embed_texts([query], client, input_type="query")[0]
