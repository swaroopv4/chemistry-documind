"""Independent dense + BM25 candidates, merged with reciprocal rank fusion."""
import logging
import os
import sqlite3

from core import keyword_index
from core.vector_store import query_index, get_index, NAMESPACE

VERSION = 'hybrid-bm25-rrf-v1'


def mode():
    value = os.getenv('RETRIEVAL_MODE','hybrid').lower()
    if value not in {'hybrid','dense'}:
        raise ValueError('RETRIEVAL_MODE must be hybrid or dense')
    return value


def _identity(source):
    return source.get('id') or f"{source.get('doc_name','')}_{source.get('chunk_index',0)}"


def fuse(dense, lexical, top_k):
    merged = {}
    for branch, rows in (('dense',dense),('keyword',lexical)):
        seen = set()
        for rank, source in enumerate(rows,1):
            identity = _identity(source)
            if identity in seen:
                continue
            seen.add(identity)
            if identity not in merged:
                merged[identity] = {**source,'hybrid_score':0.,'retrieval_method':branch}
            entry = merged[identity]
            entry['hybrid_score'] += 1./(60+rank)
            if branch == 'dense':
                entry['dense_score'] = source['score']
            else:
                entry.update({key:source[key] for key in ('bm25_score','lexical_coverage')})
                if 'dense_score' in entry:
                    entry['retrieval_method'] = 'both'
    return sorted(merged.values(),key=lambda source:(-source['hybrid_score'],_identity(source)))[:top_k]


def verified_keyword_candidates(candidates, question, filter_doc=None, allowed_docs=None):
    if not candidates:
        return []
    # Validate against the remote source of truth: deleted or externally replaced
    # vectors must not be resurrected by a stale local keyword index.
    response = get_index().fetch(ids=[source['id'] for source in candidates],namespace=NAMESPACE)
    result = []
    for candidate in candidates:
        vector = response.vectors.get(candidate['id'])
        if vector is None:
            continue
        metadata = keyword_index.safe_metadata(vector.metadata or {})
        if metadata['doc_name'] != candidate['doc_name']:
            continue
        if filter_doc and metadata['doc_name'] != filter_doc:
            continue
        if allowed_docs is not None and metadata['doc_name'] not in allowed_docs:
            continue
        if keyword_index.text_digest(metadata['text']) != candidate['_keyword_digest']:
            continue
        result.append({**metadata,**{key:candidate[key] for key in ('id','score','bm25_score','lexical_coverage')}})
    return result


def retrieve(question, embedding, top_k=5, filter_doc=None, allowed_docs=None, dense_search=None):
    if allowed_docs == []:
        return []
    candidate_limit = min(100,max(20,top_k*4))
    kwargs = {'top_k':candidate_limit,'filter_doc':filter_doc}
    if allowed_docs is not None:
        kwargs['allowed_docs'] = allowed_docs
    dense = (dense_search or query_index)(embedding,**kwargs)
    # Apply access rules independently of SDK compliance and before rank fusion.
    dense = [source for source in dense if (not filter_doc or source.get('doc_name') == filter_doc)
             and (allowed_docs is None or source.get('doc_name') in allowed_docs)]
    minimum = float(os.getenv('MIN_RETRIEVAL_SCORE','0.25'))
    dense = [source for source in dense if source.get('score',0.) >= minimum]
    try:
        lexical = keyword_index.search(question,candidate_limit,filter_doc,allowed_docs)
        lexical = verified_keyword_candidates(lexical,question,filter_doc,allowed_docs)
    except Exception as error:
        logging.getLogger(__name__).warning('Keyword branch unavailable (%s); using dense retrieval',type(error).__name__)
        lexical = []
    return fuse(dense,lexical,top_k)


def dense_mean(sources):
    scores = [source.get('dense_score',source.get('score',0.)) for source in sources
              if source.get('retrieval_method') != 'keyword']
    return sum(scores)/len(scores) if scores else None
