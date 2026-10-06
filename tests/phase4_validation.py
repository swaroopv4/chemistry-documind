"""Phase 4 accounting and UI checks. Providers and storage are isolated."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import embeddings, generation, ingestion, pipeline
from phases.phase4_obs import metrics_store as store, tracker

SOURCES = [{"doc_name": "guide.pdf", "locator": "page 1", "score": .8,
            "text": "Water has chemical formula H2O."}]
ANSWER = "Water has chemical formula H2O. (Source: guide.pdf, page 1)"
USAGE = NS(prompt_tokens=1000, completion_tokens=200,
           prompt_tokens_details=NS(cached_tokens=400))


class Phase4Checks(unittest.TestCase):
    def setUp(self):
        local_auth = patch.dict(os.environ, {'DOCUMIND_LOCAL_ADMIN':'true', 'DEPLOYMENT_ENV':'local', 'OIDC_CLIENT_ID':'', 'OIDC_CLIENT_SECRET':''})
        local_auth.start()
        self.addCleanup(local_auth.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = patch.dict(os.environ, {
            "RETRIEVAL_MODE":"dense",
            "DOCUMIND_DATA_DIR": self.temp.name, "DOCUMIND_DB": str(Path(self.temp.name)/"documind.db"),
            "EVAL_LOG_FILE": str(Path(self.temp.name)/"queries.jsonl"),
            "OBSERVABILITY_ENABLED": "true", "GROQ_PRICES_JSON": "{}",
            "PINECONE_EMBEDDING_USD_PER_MILLION": ".16",
            "GUARDRAILS_ENABLED": "true", "CACHE_ENABLED": "true",
            "CACHE_INVALIDATION_DELAY_SECONDS": "0",
            "MIN_RETRIEVAL_SCORE": ".25", "GROQ_API_KEY": "test-only", "PINECONE_API_KEY": "test-only"})
        settings.start()
        self.addCleanup(settings.stop)

    def test_provider_usage_prices_reasoning_output_and_prompt_cache(self):
        client = MagicMock()
        client.chat.completions.create.return_value = NS(choices=[NS(message=NS(content=ANSWER))], usage=USAGE)
        with patch.object(generation, "OpenAI", return_value=client):
            self.assertEqual(generation.generate_answer("Contact x@example.com", SOURCES, stream=False), ANSWER)
        row = store.get_recent_calls()[0]
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["total_tokens"], row["token_source"]),
                         (1000, 200, 1200, "provider"))
        self.assertAlmostEqual(row["cost_usd"], .00012)
        self.assertNotIn("x@example.com", row["question"])
        self.assertEqual(row["cached_input_tokens"], 400)
        client.close.assert_called_once()

    def test_stream_final_x_groq_usage_without_choices(self):
        client, stream = MagicMock(), MagicMock()
        stream.__enter__.return_value = iter([
            NS(choices=[NS(delta=NS(content=ANSWER))], usage=None),
            NS(choices=[], usage=None, x_groq={"usage": {"prompt_tokens": 700, "completion_tokens": 150}})])
        client.chat.completions.create.return_value = stream
        with patch.object(generation, "OpenAI", return_value=client):
            self.assertEqual("".join(generation.generate_answer("Formula?", SOURCES)), ANSWER)
        row = store.get_recent_calls()[0]
        self.assertEqual((row["total_tokens"], row["token_source"], row["status"]), (850, "provider", "success"))
        self.assertEqual(client.chat.completions.create.call_args.kwargs["stream_options"], {"include_usage": True})
        self.assertEqual(store.get_summary()["llm_calls"], 1)

    def test_interrupted_stream_has_unknown_cost_and_does_not_cache(self):
        client, stream = MagicMock(), MagicMock()
        def broken():
            yield NS(choices=[NS(delta=NS(content="Partial answer"))], usage=None)
            raise RuntimeError("Stream interrupted")
        stream.__enter__.return_value = broken()
        client.chat.completions.create.return_value = stream
        with patch.object(generation, "OpenAI", return_value=client), \
             patch.object(pipeline, "embed_query", return_value=[1., 0.]), \
             patch.object(pipeline, "query_index", return_value=SOURCES):
            result, _ = pipeline.query_document("Formula?")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                "".join(result)
        row = store.get_recent_calls()[0]
        self.assertEqual(row["status"], "interrupted")
        self.assertIsNone(row["cost_usd"])
        self.assertEqual(store.get_summary()["unpriced_events"], 1)
        from phases.phase3_hard import cache
        self.assertIsNone(cache.cache_lookup([1., 0.], "Formula?", cache.current_scope(5, None)))

    def test_answer_cache_hit_skips_groq_and_retrieval_but_embeds_query(self):
        class EmbeddingResult(list):
            usage = {"total_tokens": 11}
        client, pc = MagicMock(), MagicMock()
        pc.inference.embed.return_value = EmbeddingResult([NS(values=[1., 0.]+[0.]*1022)])
        client.chat.completions.create.return_value = NS(choices=[NS(message=NS(content=ANSWER))], usage=USAGE)
        with patch.object(generation, "OpenAI", return_value=client), \
             patch.object(embeddings, "get_client", return_value=pc), \
             patch.object(pipeline, "query_index", return_value=SOURCES) as retrieve:
            first = pipeline.query_document("Formula?", stream=False)
            second = pipeline.query_document("Formula?", stream=False)
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        retrieve.assert_called_once()
        client.chat.completions.create.assert_called_once()
        summary = store.get_summary()
        self.assertEqual((summary["llm_calls"], summary["cache_hits"], summary["embedding_calls"], summary["retrievals"]), (1, 1, 2, 1))
        self.assertEqual(summary["cache_hit_rate"], .5)
        cached = next(row for row in store.get_recent_calls() if row["cache_hit"])
        self.assertEqual((cached["total_tokens"], cached["cost_usd"], cached["token_source"]), (0, 0., "answer_cache"))
        self.assertAlmostEqual(summary["cost_usd"], .00012+22*.16/1_000_000)

    def test_ingestion_failure_keeps_embedding_charge_and_no_success_count(self):
        class EmbeddingResult(list):
            usage = NS(total_tokens=55)
        pc = MagicMock()
        pc.inference.embed.return_value = EmbeddingResult([NS(values=[0.]*1024)])
        chunks = [ingestion.Chunk("water", "guide", 1, 0, 4)]
        with patch.object(pipeline, "ingest_file", return_value=chunks), \
             patch.object(embeddings, "get_client", return_value=pc), \
             patch.object(pipeline, "upsert_chunks", side_effect=RuntimeError("Upload failed")):
            result = pipeline.ingest_document("guide.pdf")
        self.assertEqual(result.status, "error")
        summary = store.get_summary()
        self.assertEqual((summary["ingestions"], summary["documents_ingested"], summary["embedding_tokens"]), (1, 0, 55))
        self.assertAlmostEqual(summary["cost_usd"], 55*.16/1_000_000)
        self.assertEqual(store.get_recent_operations()["ingestions"][0]["status"], "error")

    def test_rolling_window_daily_totals_and_recent_token_alias(self):
        now = 1_800_000_000.
        with patch.object(store.time, "time", return_value=now):
            tracker.track_llm_call([], "", "openai/gpt-oss-20b", 120, usage=USAGE)
            tracker.track_embedding("llama-text-embed-v2", ["text"], {"total_tokens": 100}, 10, "evaluation")
            tracker.track_llm_call([], "", "openai/gpt-oss-20b", 5, cache_hit=True)
            store.log_llm_call(ts=now-2*86400, model="old", input_tokens=1, output_tokens=1,
                               cached_input_tokens=0, cost_usd=999, latency_ms=99, cache_hit=0,
                               question="old", token_source="provider", status="success")
            summary, daily = store.get_summary(1), store.get_daily_costs(1)
            self.assertEqual((summary["llm_calls"], summary["cache_hits"], len(daily)), (1, 1, 1))
            self.assertAlmostEqual(daily[0]["known_cost_usd"], summary["cost_usd"])
            self.assertEqual(daily[0]["total_tokens"], 1300)
            self.assertEqual(store.get_latency_series(1)[0]["avg_latency_ms"], 120)
            self.assertEqual(len(store.get_recent_calls(days=1)), 2)
            self.assertEqual(store.get_summary(7)["llm_calls"], 2)
        with self.assertRaises(ValueError):
            store.get_summary(0)

    def test_unknown_model_and_missing_usage_are_labeled(self):
        tracker.track_llm_call([{"content": "full system and context prompt"}], "answer", "unknown", 1)
        row = store.get_recent_calls()[0]
        self.assertIsNone(row["cost_usd"])
        self.assertEqual(row["input_tokens"], tracker.count_tokens("full system and context prompt"))
        self.assertEqual(row["token_source"], "estimated")
        with patch.dict(os.environ, {"GROQ_PRICES_JSON": '{"unknown":[1,2]}'}):
            self.assertEqual(store.estimate_cost("unknown", 1000, 500), .002)
        with patch.dict(os.environ, {"PINECONE_EMBEDDING_USD_PER_MILLION": "nan"}):
            self.assertIsNone(store.embedding_cost(100))

    def test_monitoring_failure_and_disable_do_not_break_answer(self):
        client = MagicMock()
        client.chat.completions.create.return_value = NS(choices=[NS(message=NS(content=ANSWER))], usage=USAGE)
        with patch.object(generation, "OpenAI", return_value=client), \
             patch.object(store, "log_llm_call", side_effect=OSError("Database unavailable")), \
             self.assertLogs("phases.phase4_obs.tracker", level="WARNING") as logged:
            self.assertEqual(generation.generate_answer("Formula?", SOURCES, stream=False), ANSWER)
        self.assertIn("OSError", logged.output[0])
        with patch.dict(os.environ, {"OBSERVABILITY_ENABLED": "false"}), patch.object(store, "log_llm_call") as write:
            tracker.safe_track(tracker.track_llm_call, messages=[], answer="", model="unknown", latency_ms=0)
            write.assert_not_called()

    def test_concurrent_app_and_worker_writes_share_database(self):
        store.init_db()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(tracker.track_embedding, "llama-text-embed-v2", ["water"],
                                   {"total_tokens": 5}, 1, "ingestion") for _ in range(16)]
            for future in futures:
                future.result()
        self.assertEqual(store.get_summary()["embedding_tokens"], 80)

    def test_dashboard_empty_and_unknown_cost(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT/"ui"/"app.py")).run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Dashboard", [tab.label for tab in app.tabs])
        self.assertTrue(any("No monitoring events" in message.value for message in app.info))
        tracker.track_llm_call([], "text", "unknown", 10)
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("unknown cost" in message.value for message in app.warning))
        self.assertEqual(next(metric.value for metric in app.metric if metric.label == "Groq requests"), "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
