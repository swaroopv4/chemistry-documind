"""Opt-in accounting smoke test: tiny public fixture, no index reads or writes."""
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if "--live" not in sys.argv:
        print("Skipped. Pass --live to call Groq and Pinecone with a small public fixture.")
        return
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    from core.generation import generate_answer
    from core.embeddings import embed_query
    from phases.phase4_obs.metrics_store import get_summary, get_recent_calls, get_recent_operations
    with tempfile.TemporaryDirectory() as folder:
        os.environ["DOCUMIND_DATA_DIR"] = folder
        os.environ["DOCUMIND_DB"] = str(Path(folder)/"metrics.db")
        os.environ["OBSERVABILITY_ENABLED"] = "true"
        sources = [{"doc_name": "public-fixture", "locator": "page 1", "text": "Water has chemical formula H2O."}]
        assert len(embed_query("What is the formula of water?")) == 1024
        assert generate_answer("What is the formula of water?", sources, stream=False)
        assert "".join(generate_answer("What is the formula of water?", sources, stream=True))
        summary = get_summary()
        assert summary["llm_calls"] == 2 and summary["embedding_calls"] == 1
        assert all(row["token_source"] == "provider" and row["total_tokens"] > 0 for row in get_recent_calls())
        assert get_recent_operations()["embeddings"][0]["token_source"] == "provider"
        assert summary["unpriced_events"] == 0
        print(f"PASS: live streaming and non-streaming usage; {summary['llm_tokens']} Groq tokens, "
              f"{summary['embedding_tokens']} Pinecone tokens; estimated cost ${summary['cost_usd']:.6f}.")


if __name__ == "__main__":
    main()
