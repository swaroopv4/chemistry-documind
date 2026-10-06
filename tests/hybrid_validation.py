"""Real BM25 storage/ranking, fusion, privacy, mutation and backfill checks."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core import keyword_index as keyword, retrieval, pipeline, catalog, redis_cache, vector_store
from core.access import Principal
from core.ingestion import Chunk
from phases.phase3_hard import cache, evaluation

ADMIN = Principal('admin','admin')
USER = Principal('student','student')


def chunk(name, text, number=0):
    return Chunk(text,name,1,number,20)


def source(name, text, score=.8, number=0):
    return {'id':f'{name}_{number}','doc_name':name,'text':text,'score':score,
            'page_num':1,'chunk_index':number,'locator':'page 1','file_type':'pdf'}


class HybridChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ,{'DOCUMIND_DATA_DIR':self.temp.name,
            'DOCUMIND_DB':str(Path(self.temp.name)/'metrics.sqlite3'),
            'EVAL_LOG_FILE':str(Path(self.temp.name)/'queries.jsonl'),
            'RETRIEVAL_MODE':'hybrid','GUARDRAILS_ENABLED':'true','CACHE_ENABLED':'true',
            'CACHE_INVALIDATION_DELAY_SECONDS':'0','MIN_RETRIEVAL_SCORE':'.25',
            'GROQ_API_KEY':'test-only','PINECONE_API_KEY':'test-only'})
        env.start()
        self.addCleanup(env.stop)
        clear = patch.object(redis_cache,'clear_answers')
        clear.start()
        self.addCleanup(clear.stop)

    def remote(self, sources):
        index = MagicMock()
        index.fetch.return_value = NS(vectors={row['id']:NS(metadata=row) for row in sources})
        return index

    def test_real_bm25_finds_formula_case_and_superscript_without_conflating_cobalt(self):
        keyword.replace_document('CO.pdf',[chunk('CO.pdf','CO is carbon monoxide.')])
        keyword.replace_document('Co.pdf',[chunk('Co.pdf','Co is cobalt.')])
        keyword.replace_document('water.pdf',[chunk('water.pdf','H₂O is water.')])
        self.assertEqual([s['doc_name'] for s in keyword.search('CO')],['CO.pdf'])
        self.assertEqual([s['doc_name'] for s in keyword.search('Co')],['Co.pdf'])
        self.assertEqual([s['doc_name'] for s in keyword.search('H2O')],['water.pdf'])

    def test_real_bm25_ranks_term_frequency_and_preserves_cas_identifiers(self):
        keyword.replace_document('rare.pdf',[chunk('rare.pdf','acetone acetone acetone 67-64-1')])
        keyword.replace_document('other.pdf',[chunk('other.pdf','acetone '+'unrelated '*30)])
        self.assertEqual(keyword.search('acetone')[0]['doc_name'],'rare.pdf')
        self.assertEqual([s['doc_name'] for s in keyword.search('67-64-1')],['rare.pdf'])
        self.assertGreater(keyword.search('acetone')[0]['bm25_score'],0)

    def test_query_syntax_is_data_and_stopwords_cannot_produce_evidence(self):
        keyword.replace_document('guide.pdf',[chunk('guide.pdf','acetone extraction')])
        self.assertEqual(keyword.search('what is the'),[])
        self.assertEqual(keyword.search('" OR * ; DROP TABLE keyword_chunks; --'),[])
        self.assertEqual(keyword.status()['chunks'],1)

    def test_document_filters_apply_to_keyword_search_before_ranking(self):
        keyword.replace_document('private.pdf',[chunk('private.pdf','acetone '*100)])
        keyword.replace_document('public.pdf',[chunk('public.pdf','acetone extraction')])
        self.assertEqual([s['doc_name'] for s in keyword.search('acetone',allowed_docs=['public.pdf'])],['public.pdf'])
        self.assertEqual(keyword.search('acetone',filter_doc='private.pdf',allowed_docs=['public.pdf']),[])
        self.assertEqual(keyword.search('acetone',allowed_docs=[]),[])

    def test_rrf_rewards_both_branches_and_deduplicates_ids(self):
        common = source('common.pdf','acetone')
        dense = [source('dense.pdf','solvent'),common]
        lexical = [{**common,'bm25_score':2.,'lexical_coverage':1.},
                   {**source('keyword.pdf','acetone',0.),'bm25_score':1.,'lexical_coverage':1.}]
        fused = retrieval.fuse(dense,lexical,3)
        self.assertEqual(fused[0]['id'],common['id'])
        self.assertEqual(fused[0]['retrieval_method'],'both')
        self.assertAlmostEqual(fused[0]['hybrid_score'],1/62+1/61)
        self.assertEqual(len({s['id'] for s in fused}),3)
        self.assertEqual(len(retrieval.fuse([common,common],[],3)),1)

    def test_hybrid_returns_independent_keyword_hit_absent_from_dense_candidates(self):
        exact = source('exact.pdf','The CAS identifier is 67-64-1.',0.)
        keyword.replace_document('exact.pdf',[chunk('exact.pdf',exact['text'])])
        with patch.object(retrieval,'get_index',return_value=self.remote([exact])):
            result = retrieval.retrieve('67-64-1',[1.],top_k=2,dense_search=lambda *args,**kwargs:[source('meaning.pdf','Related solvent properties')])
        self.assertEqual({s['doc_name'] for s in result},{'meaning.pdf','exact.pdf'})
        self.assertEqual(next(s for s in result if s['doc_name']=='exact.pdf')['retrieval_method'],'keyword')

    def test_hybrid_postfilters_malicious_dense_matches_and_keeps_private_keywords_out(self):
        public = source('public.pdf','acetone extraction')
        private = source('private.pdf','acetone secret')
        keyword.replace_document('public.pdf',[chunk('public.pdf',public['text'])])
        keyword.replace_document('private.pdf',[chunk('private.pdf',private['text'])])
        dense = MagicMock(return_value=[private,public])
        with patch.object(retrieval,'get_index',return_value=self.remote([private,public])):
            result = retrieval.retrieve('acetone',[1.],allowed_docs=['public.pdf'],dense_search=dense)
        self.assertEqual([s['doc_name'] for s in result],['public.pdf'])
        self.assertEqual(dense.call_args.kwargs['allowed_docs'],['public.pdf'])
        dense.reset_mock()
        self.assertEqual(retrieval.retrieve('acetone',[1.],allowed_docs=[],dense_search=dense),[])
        dense.assert_not_called()

    def test_remote_deleted_changed_and_renamed_vectors_are_not_resurrected(self):
        keyword.replace_document('guide.pdf',[chunk('guide.pdf','acetone extraction')])
        candidates = keyword.search('acetone')
        for remote in [[],[source('guide.pdf','Replacement benzene text')],
                       [{**source('private.pdf','acetone extraction'),'id':'guide.pdf_0'}]]:
            with self.subTest(remote=remote),patch.object(retrieval,'get_index',return_value=self.remote(remote)):
                self.assertEqual(retrieval.verified_keyword_candidates(candidates,'acetone'),[])

    def test_keyword_failure_falls_back_to_dense_and_retains_original_cosine(self):
        with patch.object(keyword,'search',side_effect=sqlite3.OperationalError('unavailable')):
            result = retrieval.retrieve('acetone',[1.],dense_search=lambda *args,**kwargs:[source('guide.pdf','solvent',.82)])
        self.assertEqual(result[0]['dense_score'],.82)
        self.assertEqual(result[0]['retrieval_method'],'dense')
        self.assertEqual(retrieval.dense_mean(result),.82)

    def test_pipeline_accepts_relevant_keyword_evidence_below_dense_threshold_and_records_truthfully(self):
        text = 'The chemical formula is XeF6.'
        raw = source('guide.pdf',text,0.)
        keyword.replace_document('guide.pdf',[chunk('guide.pdf',text)])
        catalog.set_policy('guide.pdf','published','Shared chemistry',ADMIN)
        with patch.object(pipeline,'embed_query',return_value=[1.]),patch.object(pipeline,'query_index',return_value=[]), \
             patch.object(retrieval,'get_index',return_value=self.remote([raw])), \
             patch.object(pipeline,'generate_answer',return_value='The formula is XeF6. (Source: Shared chemistry, page 1)'):
            result = pipeline.query_document('XeF6',stream=False,audience='student',use_cache=False,answer_validator=lambda answer,sources:answer)
        self.assertEqual(result.status,'answered')
        self.assertEqual(result.sources[0]['doc_name'],'Shared chemistry')
        self.assertEqual(result.sources[0]['retrieval_method'],'keyword')
        log = evaluation.load_logs()[-1]
        self.assertIsNone(log['retrieval_score'])
        self.assertEqual(log['retrieval_mode'],'hybrid')
        self.assertEqual(log['keyword_chunks'],1)
        self.assertEqual(evaluation.check_drift(),[])

    def test_replacement_and_deletion_leave_no_old_or_trailing_keyword_chunks(self):
        keyword.replace_document('guide.pdf',[chunk('guide.pdf','acetone',0),chunk('guide.pdf','benzene',1)])
        keyword.replace_document('guide.pdf',[chunk('guide.pdf','ethanol')])
        self.assertEqual(keyword.search('benzene'),[])
        self.assertEqual(keyword.status()['chunks'],1)
        with patch.object(pipeline,'delete_document'):
            pipeline.remove_document('guide.pdf')
        self.assertEqual(keyword.status()['chunks'],0)

    def test_ingestion_redacts_keywords_and_partial_remote_failure_removes_old_text(self):
        keyword.replace_document('guide.pdf',[chunk('guide.pdf','obsolete solvent')])
        chunks = [chunk('guide.pdf','acetone. Author: Jane Doe\nEmail x@example.com')]
        with patch.object(pipeline,'ingest_file',return_value=chunks),patch.object(pipeline,'embed_chunks',return_value=[[0.]*1024]), \
             patch.object(pipeline,'upsert_chunks'):
            self.assertEqual(pipeline.ingest_document('guide.pdf').status,'success')
        self.assertNotIn('x@example.com',str(keyword.search('acetone')))
        self.assertNotIn('Jane Doe',str(keyword.search('acetone')))
        with patch.object(pipeline,'ingest_file',return_value=chunks),patch.object(pipeline,'embed_chunks',return_value=[[0.]*1024]), \
             patch.object(pipeline,'upsert_chunks',side_effect=RuntimeError('partial write')):
            self.assertEqual(pipeline.ingest_document('guide.pdf').status,'error')
        self.assertEqual(keyword.status()['chunks'],0)

    def test_backfill_is_atomic_discovers_private_documents_and_invalidates_cache(self):
        keyword.replace_document('old.pdf',[chunk('old.pdf','obsolete')])
        row = source('existing.pdf','acetone synthesis')
        index = self.remote([row])
        index.list.return_value = [[NS(id=row['id'])]]
        before = cache.current_scope(5,None)
        result = keyword.rebuild_from_pinecone(ADMIN,index)
        self.assertEqual(result['chunks'],1)
        self.assertEqual(keyword.search('obsolete'),[])
        self.assertEqual(keyword.search('acetone')[0]['doc_name'],'existing.pdf')
        self.assertEqual(catalog.published(),{})
        self.assertEqual(catalog.list_documents()[0]['chunks'],1)
        self.assertNotEqual(before,cache.current_scope(5,None))
        with self.assertRaises(PermissionError):
            keyword.rebuild_from_pinecone(USER,index)

    def test_pinecone_listing_accepts_current_sdk_items_and_legacy_strings(self):
        self.assertEqual(vector_store.vector_ids(['a',NS(id='b'),{'id':'c'}]),['a','b','c'])
        self.assertEqual(vector_store.vector_ids(NS(vectors=[NS(id='a')])),['a'])
        with self.assertRaises(ValueError):
            vector_store.vector_ids([NS(id=5)])
        row = source('guide.pdf','acetone')
        index = self.remote([row])
        index.list.return_value = [[NS(id=row['id'])]]
        with patch.object(vector_store,'get_index',return_value=index):
            names, count, truncated = vector_store.scan_document_names()
        self.assertEqual((names,count,truncated),(['guide.pdf'],1,False))
        index.fetch.assert_called_once_with(ids=[row['id']],namespace=vector_store.NAMESPACE)

    def test_failed_or_overlimit_backfill_retains_previous_complete_index(self):
        keyword.replace_document('old.pdf',[chunk('old.pdf','acetone')])
        index = MagicMock()
        index.list.return_value = [['id-1','id-2']]
        with self.assertRaises(ValueError):
            keyword.rebuild_from_pinecone(ADMIN,index,max_vectors=1)
        self.assertEqual(keyword.search('acetone')[0]['doc_name'],'old.pdf')
        index = MagicMock()
        index.list.return_value = [['id-1']]
        index.fetch.side_effect = RuntimeError('network')
        with self.assertRaises(RuntimeError):
            keyword.rebuild_from_pinecone(ADMIN,index)
        self.assertEqual(keyword.status()['chunks'],1)

    def test_backfill_preserves_concurrent_replacement_and_deletion(self):
        keyword.replace_document('replace.pdf',[chunk('replace.pdf','old acetone')])
        keyword.replace_document('delete.pdf',[chunk('delete.pdf','old benzene')])
        rows = [source('replace.pdf','old acetone'),source('delete.pdf','old benzene')]
        index = self.remote(rows)
        def listing(**kwargs):
            keyword.replace_document('replace.pdf',[chunk('replace.pdf','new ethanol')])
            keyword.remove_document('delete.pdf')
            yield [row['id'] for row in rows]
        index.list.side_effect = listing
        keyword.rebuild_from_pinecone(ADMIN,index)
        self.assertEqual(keyword.search('acetone'),[])
        self.assertEqual(keyword.search('benzene'),[])
        self.assertEqual(keyword.search('ethanol')[0]['doc_name'],'replace.pdf')

    def test_retrieval_mode_changes_both_cache_scopes_and_invalid_mode_is_rejected(self):
        hybrid = cache.current_scope(5,None)
        with patch.dict(os.environ,{'RETRIEVAL_MODE':'dense'}):
            self.assertNotEqual(hybrid,cache.current_scope(5,None))
        with patch.dict(os.environ,{'RETRIEVAL_MODE':'unknown'}),self.assertRaises(ValueError):
            retrieval.mode()

    def test_hybrid_policy_change_during_generation_blocks_keyword_answer(self):
        raw = source('guide.pdf','XeF6 is xenon hexafluoride.',0.)
        keyword.replace_document('guide.pdf',[chunk('guide.pdf',raw['text'])])
        catalog.set_policy('guide.pdf','published','Chemistry',ADMIN)
        def generate(*args,**kwargs):
            catalog.set_policy('guide.pdf','private','Chemistry',ADMIN)
            return 'XeF6 is xenon hexafluoride. (Source: Chemistry, page 1)'
        with patch.object(pipeline,'embed_query',return_value=[1.]),patch.object(pipeline,'query_index',return_value=[]), \
             patch.object(retrieval,'get_index',return_value=self.remote([raw])),patch.object(pipeline,'generate_answer',side_effect=generate):
            result = pipeline.query_document('XeF6',stream=False,audience='student')
        self.assertEqual(result.status,'access_changed')
        self.assertEqual(result.sources,[])
        self.assertEqual(cache.cache_stats()['entries'],0)

    def test_hybrid_admin_ui_starts_without_provider_requests_and_shows_rebuild(self):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ,{'DOCUMIND_LOCAL_ADMIN':'true','DEPLOYMENT_ENV':'local','OIDC_CLIENT_ID':'','OIDC_CLIENT_SECRET':''}), \
             patch.object(pipeline,'query_index') as query,patch.object(retrieval,'get_index') as index:
            app = AppTest.from_file(str(ROOT/'ui/app.py')).run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any('Hybrid retrieval' in item.value for item in app.caption))
        self.assertTrue(any(item.label=='Rebuild keyword index from existing vectors' for item in app.button))
        query.assert_not_called()
        index.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
