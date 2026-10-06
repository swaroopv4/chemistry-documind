from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pinecone import Pinecone, ServerlessSpec
from core.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL

if TYPE_CHECKING:
    from core.ingestion import Chunk

INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "documind-groq")
NAMESPACE = "llama-text-embed-v2-1024"
CLOUD = os.getenv("PINECONE_CLOUD", "aws")
REGION = os.getenv("PINECONE_REGION", "us-east-1")
DIMENSION = EMBEDDING_DIM
METRIC = "cosine"
UPSERT_BATCH = 100


def get_index():
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        raise EnvironmentError("Pinecone api_key not set")
    from core.settings import get_settings
    pc = Pinecone(api_key=api_key,timeout=get_settings()['provider_timeout'])
    existing = [idx.name for idx in pc.list_indexes()]
    if INDEX_NAME not in existing:
        pc.create_index(
            name=INDEX_NAME,
            dimension=DIMENSION,
            metric=METRIC,
            spec=ServerlessSpec(cloud=CLOUD, region=REGION),
            timeout=60,
        )
    description = pc.describe_index(INDEX_NAME)
    if description.dimension != DIMENSION or description.metric != METRIC:
        raise ValueError(
            f"Index {INDEX_NAME!r} must use {DIMENSION} dimensions and {METRIC}. "
            "Set PINECONE_INDEX_NAME to a new name and re-ingest your files."
        )
    return pc.Index(INDEX_NAME)


def upsert_chunks(chunks: list[Chunk], embeddings: list[list[float]]) -> int:
    # Added validation so a partial embedding response cannot silently drop chunks.
    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk must have one embedding")
    if any(len(vector) != DIMENSION for vector in embeddings):
        raise ValueError(f"Embeddings must have {DIMENSION} dimensions")
    index = get_index()
    vectors = []
    for chunk, embedding in zip(chunks, embeddings):
        vec_id = f"{chunk.doc_name}_{chunk.chunk_index}"
        vectors.append({
            "id": vec_id,
            "values": embedding,
            "metadata": {**chunk.to_pinecone_metadata(), "embedding_model": EMBEDDING_MODEL},
        })
    for i in range(0, len(vectors), UPSERT_BATCH):
        batch = vectors[i:i + UPSERT_BATCH]
        index.upsert(vectors=batch, namespace=NAMESPACE)
    # Same filename means replacement. Clear trailing chunks left by a previous
    # longer upload only after all new batches have been written successfully.
    for doc_name in {chunk.doc_name for chunk in chunks}:
        next_index = max(chunk.chunk_index for chunk in chunks if chunk.doc_name == doc_name) + 1
        index.delete(filter={"$and": [
            {"doc_name": {"$eq": doc_name}}, {"chunk_index": {"$gte": next_index}},
        ]}, namespace=NAMESPACE)
    return len(vectors)


def query_index(
    query_embeddings: list[float],
    top_k: int = 5,
    filter_doc: str | None = None,
    allowed_docs: list[str] | None = None,
) -> list[dict]:
    if allowed_docs is not None and not allowed_docs:
        return []
    index = get_index()
    query_kwargs = {
        "vector": query_embeddings,
        "top_k": top_k,
        "include_metadata": True,
        "namespace": NAMESPACE,
    }
    if filter_doc:
        query_kwargs["filter"] = {"doc_name": {"$eq": filter_doc}}
    if allowed_docs is not None:
        permitted = {"doc_name": {"$in": allowed_docs}}
        query_kwargs['filter'] = {"$and": [query_kwargs['filter'], permitted]} if filter_doc else permitted
    response = index.query(**query_kwargs)
    results = []
    for match in response.matches:
        results.append({
            "id": match.id,
            "score": round(match.score, 4),
            "text": match.metadata.get("text", ""),
            "doc_name": match.metadata.get("doc_name", ""),
            "page_num": match.metadata.get("page_num", 0),
            "chunk_index": match.metadata.get("chunk_index", 0),
            "locator": match.metadata.get("locator", f"page {match.metadata.get('page_num', 0)}"),
            "file_type": match.metadata.get("file_type", "pdf"),
            **({'ocr':True,'ocr_confidence':match.metadata.get('ocr_confidence',0.)} if match.metadata.get('ocr') else {}),
        })
    return results


def delete_document(doc_name: str) -> None:
    index = get_index()
    index.delete(filter={"doc_name": {"$eq": doc_name}}, namespace=NAMESPACE)


def get_index_stats() -> dict:
    index = get_index()
    stats = index.describe_index_stats()
    return {
        "total_vectors": stats.namespaces.get(NAMESPACE, {}).get("vector_count", 0),
        "dimension": stats.dimension,
        "index_name": INDEX_NAME,
    }


def list_indexed_documents(index=None) -> list[str]:
    """Video's approximate listing method; samples at most 100 vector matches."""
    if index is None:
        index = get_index()
    zero_vec = [0.0] * DIMENSION
    response = index.query(vector=zero_vec, top_k=100, include_metadata=True, namespace=NAMESPACE)
    docs = list({m.metadata.get("doc_name", "") for m in response.matches if m.metadata})
    return sorted(d for d in docs if d)


def scan_document_names(max_vectors=10000):
    """Bounded paginated ID scan of this app's namespace; no raw text in catalog."""
    index, names, scanned, truncated = get_index(), set(), 0, False
    for batch in index.list(namespace=NAMESPACE):
        batch = vector_ids(batch)
        if scanned + len(batch) > max_vectors:
            truncated = True
            break
        response = index.fetch(ids=batch, namespace=NAMESPACE)
        for vector in response.vectors.values():
            name = vector.metadata.get('doc_name', '')
            if name:
                names.add(name)
        scanned += len(batch)
    return sorted(names), scanned, truncated


def vector_ids(batch):
    """SDK versions yield either strings or ListItem records with an id field."""
    result = []
    for item in getattr(batch,'vectors',batch):
        value = item if isinstance(item,str) else item.get('id') if isinstance(item,dict) else getattr(item,'id',None)
        if not isinstance(value,str) or not value:
            raise ValueError('Pinecone returned an invalid vector ID')
        result.append(value)
    return result


def document_chunks(doc_name, limit=20):
    from phases.phase3_hard.guardrails import redact_pii
    response = get_index().query(vector=[0.0]*DIMENSION, top_k=min(max(limit,1),100),
        include_metadata=True, namespace=NAMESPACE, filter={'doc_name': {'$eq': doc_name}})
    return sorted([{'chunk': match.metadata.get('chunk_index',0),
                    'locator': redact_pii(match.metadata.get('locator','source'))[0],
                    'text': redact_pii(match.metadata.get('text',''))[0]}
                   for match in response.matches], key=lambda item:item['chunk'])
