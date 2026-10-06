"""Verify file parsing, Groq and Pinecone boundaries without network calls."""
from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from core import ingestion, embeddings, vector_store, generation, pipeline


def make_pdf(path, texts):
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref}),
        })
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 40 740 Td ({text}) Tj ET'.encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


class ReconstructionChecks(unittest.TestCase):
    def setUp(self):
        local_auth = patch.dict(os.environ, {'DOCUMIND_LOCAL_ADMIN':'true', 'DEPLOYMENT_ENV':'local', 'OIDC_CLIENT_ID':'', 'OIDC_CLIENT_SECRET':''})
        local_auth.start()
        self.addCleanup(local_auth.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = patch.dict(os.environ, {"DOCUMIND_DATA_DIR": folder.name, "RETRIEVAL_MODE":"dense"})
        settings.start()
        self.addCleanup(settings.stop)

    def test_pdf_extracts_all_pages_and_rejects_blank_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sample.pdf'
            make_pdf(path, ['First page text', 'Second page text'])
            self.assertEqual(ingestion.extract_text_from_pdf(path),
                             [(1, 'First page text'), (2, 'Second page text')])
            chunks = ingestion.ingest_pdf(path, 4, 1)
            self.assertEqual(chunks[0].doc_name, 'sample')
            self.assertTrue(all(c.token_count <= 4 for c in chunks))
            make_pdf(path, [''])
            with self.assertRaisesRegex(ValueError, 'No text found|needs OCR'):
                ingestion.ingest_pdf(path)

    def test_token_windows_keep_overlap_and_starting_page(self):
        pages = [(1, 'alpha beta gamma delta'), (2, 'epsilon zeta eta theta')]
        tokens = [ingestion._ENCODER.encode(t) for _, t in pages]
        flat = tokens[0] + tokens[1]
        mapping = [1] * len(tokens[0]) + [2] * len(tokens[1])
        chunks = ingestion.chunk_pages(pages, 'guide', 4, 1)
        self.assertEqual(len(chunks), len(range(0, len(flat), 3)))
        for i, start in enumerate(range(0, len(flat), 3)):
            self.assertEqual(chunks[i].text, ingestion._ENCODER.decode(flat[start:start + 4]))
            self.assertEqual(chunks[i].page_num, mapping[start])
            self.assertEqual(chunks[i].chunk_index, i)
        self.assertEqual(ingestion._clean_text(' inter-\n national\x00 text  '), 'international text')
        with self.assertRaises(ValueError):
            ingestion.chunk_pages(pages, 'guide', 100, 100)

    def test_embedding_batches_and_response_order(self):
        client = MagicMock()
        def create(**kwargs):
            return [NS(values=[float(t)] * 1024) for t in kwargs['inputs']]
        client.inference.embed.side_effect = create
        result = embeddings.embed_texts([str(i) for i in range(101)], client)
        self.assertEqual(result, [[float(i)] * 1024 for i in range(101)])
        self.assertEqual([len(c.kwargs['inputs']) for c in client.inference.embed.call_args_list], [96, 5])
        self.assertEqual(client.inference.embed.call_args.kwargs['parameters']['input_type'], 'passage')
        self.assertEqual(embeddings.embed_query('42', client), [42.0] * 1024)
        self.assertEqual(client.inference.embed.call_args.kwargs['parameters']['input_type'], 'query')
        client.inference.embed.side_effect = lambda **kwargs: [NS(values=[1.0])]
        with self.assertRaises(ValueError):
            embeddings.embed_texts(['text'], client)

    def test_vector_batches_filtering_deletion_and_stats(self):
        index = MagicMock()
        chunks = [ingestion.Chunk('text', 'guide', 1, i, 1) for i in range(101)]
        index.query.return_value = NS(matches=[NS(
            id='guide_0', score=.987654,
            metadata=chunks[0].to_pinecone_metadata(),
        )])
        index.describe_index_stats.return_value = NS(total_vector_count=105, dimension=1024,
            namespaces={vector_store.NAMESPACE: {'vector_count': 101}})
        with patch.object(vector_store, 'get_index', return_value=index):
            self.assertEqual(vector_store.upsert_chunks(chunks, [[.1] * 1024] * 101), 101)
            self.assertEqual([len(c.kwargs['vectors']) for c in index.upsert.call_args_list], [100, 1])
            self.assertEqual(index.delete.call_args.kwargs['filter'], {'$and': [
                {'doc_name': {'$eq': 'guide'}}, {'chunk_index': {'$gte': 101}},
            ]})
            index.delete.reset_mock()
            sources = vector_store.query_index([.1], filter_doc='guide')
            self.assertEqual(index.query.call_args.kwargs['filter'], {'doc_name': {'$eq': 'guide'}})
            self.assertEqual(sources[0]['score'], .9877)
            vector_store.delete_document('guide')
            index.delete.assert_called_once_with(filter={'doc_name': {'$eq': 'guide'}}, namespace=vector_store.NAMESPACE)
            self.assertEqual(vector_store.get_index_stats()['total_vectors'], 101)
        with self.assertRaises(ValueError):
            vector_store.upsert_chunks(chunks, [])

    def test_index_creation_and_document_listing(self):
        pc = MagicMock()
        pc.list_indexes.return_value = []
        pc.describe_index.return_value = NS(dimension=1024, metric='cosine')
        with patch.dict(os.environ, {'PINECONE_API_KEY': 'test-only'}), \
             patch.object(vector_store, 'Pinecone', return_value=pc):
            self.assertIs(vector_store.get_index(), pc.Index.return_value)
            self.assertEqual(pc.create_index.call_args.kwargs['dimension'], 1024)
            pc.describe_index.return_value.dimension = 1536
            with self.assertRaisesRegex(ValueError, '1024 dimensions'):
                vector_store.get_index()
        index = MagicMock()
        index.query.return_value = NS(matches=[NS(metadata={'doc_name': x}) for x in ['b', 'a', 'a', '']])
        self.assertEqual(vector_store.list_indexed_documents(index), ['a', 'b'])

    def test_pipeline_ingestion_flow_and_error_result(self):
        chunks = [ingestion.Chunk('text', 'guide.pdf', 1, 0, 4)]
        steps = []
        with patch.object(pipeline, 'ingest_file', return_value=chunks), \
             patch.object(pipeline, 'embed_chunks', return_value=[[.1]]) as embed, \
             patch.object(pipeline, 'upsert_chunks') as upsert:
            result = pipeline.ingest_document('guide.pdf', progress_callback=lambda s, p: steps.append((s, p)))
            embed.assert_called_once_with(chunks)
            upsert.assert_called_once_with(chunks, [[.1]])
        self.assertEqual((result.status, result.chunk_count, result.page_count, result.total_tokens),
                         ('success', 1, 1, 4))
        self.assertEqual([p for _, p in steps], [.1, .4, .7, 1.0])
        with patch.object(pipeline, 'ingest_file', side_effect=ValueError('bad PDF')):
            self.assertEqual(pipeline.ingest_document('guide.pdf').error, 'bad PDF')

    def test_query_returns_both_stream_and_result_modes(self):
        sources = [{'text': 'evidence', 'doc_name': 'guide', 'page_num': 2}]
        with patch.dict(os.environ, {'GUARDRAILS_ENABLED': 'false', 'CACHE_ENABLED': 'false'}), \
             patch.object(pipeline, 'embed_query', return_value=[.1]), \
             patch.object(pipeline, 'query_index', return_value=sources) as retrieve, \
             patch.object(pipeline, 'generate_answer', side_effect=lambda q, s, stream: iter(['answer']) if stream else 'answer'):
            gen, found = pipeline.query_document(' question ', filter_doc='guide')
            self.assertEqual(''.join(gen), 'answer')
            self.assertEqual(found, sources)
            retrieve.assert_called_with([.1], top_k=5, filter_doc='guide')
            result = pipeline.query_document('question', stream=False)
            self.assertEqual((result.answer, result.query, result.top_k), ('answer', 'question', 5))
        with self.assertRaises(ValueError):
            pipeline.query_document('   ')

    def test_generation_prompt_stream_and_empty_retrieval(self):
        sources = [{'doc_name': 'guide', 'page_num': 2, 'text': 'Evidence'}]
        client = MagicMock()
        client.chat.completions.create.return_value = NS(choices=[NS(message=NS(content='Answer'))])
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test-only'}), \
             patch.object(generation, 'OpenAI', return_value=client) as constructor:
            self.assertEqual(generation.generate_answer('Question', sources, stream=False), 'Answer')
            messages = client.chat.completions.create.call_args.kwargs['messages']
            self.assertEqual([m['role'] for m in messages], ['system', 'user'])
            self.assertIn('page 2', messages[1]['content'])
            self.assertEqual(constructor.call_args.kwargs['base_url'],'https://api.groq.com/openai/v1')
            self.assertEqual(constructor.call_args.kwargs['max_retries'],0)
            self.assertEqual(client.chat.completions.create.call_args.kwargs['max_completion_tokens'],2048)
            self.assertEqual(client.chat.completions.create.call_args.kwargs['model'], 'openai/gpt-oss-20b')
            client.chat.completions.create.reset_mock()
            self.assertEqual(''.join(generation.generate_answer('Question', [])),
                             'I could not find relevant passages.')
            client.chat.completions.create.assert_not_called()
            stream = MagicMock()
            stream.__enter__.return_value = iter([NS(choices=[NS(delta=NS(content=x))]) for x in ['Hello', None, ' world']])
            client.chat.completions.create.return_value = stream
            self.assertEqual(''.join(generation.generate_answer('Question', sources)), 'Hello world')

    def test_streamlit_starts_without_credentials(self):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ, {'GROQ_API_KEY': '', 'PINECONE_API_KEY': ''}):
            app = AppTest.from_file(str(ROOT / 'ui' / 'app.py')).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([s.value for s in app.sidebar.slider], [400, 50, 5])
        self.assertEqual([t.label for t in app.tabs], ['Ask', 'Job queue', 'Eval & metrics', 'RAGAS evaluation', 'Dashboard', 'Documents', 'Logs & Redis', 'Readiness'])
        self.assertIn('Missing:', app.warning[0].value)

    def test_streamlit_with_credentials_does_not_call_providers_on_startup(self):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test-only', 'PINECONE_API_KEY': 'test-only'}), \
             patch.object(vector_store, 'get_index') as connect, \
             patch.object(embeddings, 'get_client') as embed_connect:
            app = AppTest.from_file(str(ROOT / 'ui' / 'app.py')).run(timeout=20)
            connect.assert_not_called()
            embed_connect.assert_not_called()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.warning), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
