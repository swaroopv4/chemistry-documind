"""Reference retrieval benchmark with isolated SQLite and optional real embeddings."""
import json
import math
from pathlib import Path
import sqlite3
import time
from core import keyword_index,retrieval


def run(compare=False,fixture=None,top_k=5):
    dataset = json.loads(Path(fixture or Path(__file__).resolve().parents[1]/'benchmarks/chemistry.json').read_text(encoding='utf-8'))
    cases = dataset['cases']
    if not 1<=len(cases)<=100 or not 1<=top_k<=20:
        raise ValueError('Benchmark supports 1–100 cases and top-k 1–20')
    dense_vectors = query_vectors = None
    if compare:
        from core.embeddings import embed_texts
        dense_vectors = embed_texts([case['passage'] for case in cases],purpose='benchmark_passages')
        query_vectors = embed_texts([case['question'] for case in cases],input_type='query',purpose='benchmark_queries')
    results = {'bm25':[]}
    if compare:
        results.update(dense=[],hybrid=[])
    with sqlite3.connect(':memory:') as db:
        db.row_factory = sqlite3.Row
        keyword_index._schema(db)
        for case in cases:
            keyword_index._insert(db,case['id'],{'doc_name':case['expected_document'],'text':case['passage'],'locator':'passage 1'})
        for number,case in enumerate(cases):
            started = time.perf_counter()
            lexical = keyword_index.search(case['question'],max(20,top_k*4),connection=db)
            branches = {'bm25':lexical[:top_k]}
            if compare:
                query = query_vectors[number]
                def cosine(vector):
                    denominator = math.sqrt(sum(v*v for v in query)*sum(v*v for v in vector))
                    return sum(a*b for a,b in zip(query,vector))/denominator if denominator else 0.
                dense = [{'id':row['id'],'doc_name':row['expected_document'],'text':row['passage'],'score':cosine(vector)}
                         for row,vector in zip(cases,dense_vectors)]
                dense.sort(key=lambda row:(-row['score'],row['id']))
                dense = [row for row in dense[:max(20,top_k*4)] if row['score']>=.25]
                branches.update(dense=dense[:top_k],hybrid=retrieval.fuse(dense,lexical,top_k))
            latency = (time.perf_counter()-started)*1000
            for name,rows in branches.items():
                rank = next((i for i,row in enumerate(rows,1) if row['doc_name']==case['expected_document']),None)
                results[name].append({'id':case['id'],'rank':rank,'retrieval_ms':round(latency,3)})
    return {'description':dataset['description'],'cases_count':len(cases),'top_k':top_k,
        'embedding_calls':compare,'latency_note':'Ranking only; embedding/network time excluded. Compare measures shared ranking work.',
        'metrics':{name:{'recall_at_k':sum(row['rank'] is not None for row in rows)/len(rows),
                         'mrr':sum(1/row['rank'] if row['rank'] else 0 for row in rows)/len(rows)} for name,rows in results.items()},
        'cases':results}
