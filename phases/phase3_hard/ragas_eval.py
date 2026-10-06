from __future__ import annotations

import asyncio
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import uuid

from .guardrails import check_input, enabled, redact_pii
from .storage import data_dir

METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def validate_test_set(rows: list, complete: bool = False) -> list[dict]:
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError("Test set must be a JSON list with 1–50 rows.")
    output = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Row {i} must be an object.")
        item = {}
        for field in ("question", "ground_truth"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 20000:
                raise ValueError(f"Row {i}: {field} must be a nonempty string under 20,000 characters.")
            item[field] = redact_pii(value.strip())[0]
        if enabled():
            item["question"] = check_input(item["question"])
        if complete or "answer" in row or "contexts" in row:
            if not isinstance(row.get("answer"), str) or not row["answer"].strip():
                raise ValueError(f"Row {i}: answer must be a nonempty string.")
            contexts = row.get("contexts")
            if not isinstance(contexts, list) or not contexts or any(not isinstance(c, str) or not c.strip() for c in contexts):
                raise ValueError(f"Row {i}: contexts must be a nonempty list of strings.")
            if len(contexts) > 30 or sum(len(c) for c in contexts) + len(row["answer"]) > 100000:
                raise ValueError(f"Row {i} is too large for evaluation.")
            item["answer"] = redact_pii(row["answer"])[0]
            item["contexts"] = [redact_pii(c)[0] for c in contexts]
        output.append(item)
    if any("answer" in row for row in output) and not all("answer" in row for row in output):
        raise ValueError("Provide answer/contexts for every row, or omit them for every row.")
    return output


def load_test_set_from_json(path: str | Path) -> list[dict]:
    return validate_test_set(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def build_test_set_from_pipeline(pairs: list[dict], top_k: int = 5,
                                 filter_doc: str | None = None, progress_callback=None) -> list[dict]:
    from core.pipeline import query_document
    pairs = validate_test_set(pairs)
    output = []
    for i, pair in enumerate(pairs):
        result = query_document(pair["question"], top_k=top_k, stream=False,
                                filter_doc=filter_doc, use_cache=False)
        if result.status != "answered" or not result.sources:
            raise ValueError(f"Row {i + 1}: no usable answer/context. Ingest the matching document and check the question.")
        output.append({**pair, "answer": result.answer,
                       "contexts": [source["text"] for source in result.sources]})
        if progress_callback:
            progress_callback((i + 1) / len(pairs))
    return output


def _make_evaluator():
    from langchain_openai import ChatOpenAI
    from langchain_core.embeddings import Embeddings
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from core.embeddings import embed_texts

    if not os.getenv("GROQ_API_KEY") or not os.getenv("PINECONE_API_KEY"):
        raise EnvironmentError("RAGAS needs GROQ_API_KEY and PINECONE_API_KEY.")

    class PineconeEvaluationEmbeddings(Embeddings):
        # Answer relevancy compares generated questions with the input question;
        # use symmetric query embeddings for both sides of that comparison.
        def embed_documents(self, texts):
            return embed_texts(texts, input_type="query", purpose="evaluation")

        def embed_query(self, text):
            return self.embed_documents([text])[0]

        async def aembed_documents(self, texts):
            return await asyncio.to_thread(self.embed_documents, texts)

        async def aembed_query(self, text):
            return (await self.aembed_documents([text]))[0]

    from core import provider_limits
    from core.settings import get_settings
    llm = ChatOpenAI(model=os.getenv("RAGAS_GROQ_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")),
                     api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1",
                     temperature=0, max_tokens=get_settings()['answer_tokens'], timeout=get_settings()['provider_timeout'], max_retries=0,
                     http_client=provider_limits.http_client(),http_async_client=provider_limits.async_http_client())
    return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(PineconeEvaluationEmbeddings())


def run_ragas_eval(test_set: list[dict], report_name: str | None = None) -> dict:
    """Evaluate locally with explicit providers; never fall back to OpenAI."""
    rows = validate_test_set(test_set, complete=True)
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import Faithfulness, ResponseRelevancy, LLMContextPrecisionWithReference, LLMContextRecall
    from ragas.run_config import RunConfig

    dataset = EvaluationDataset(samples=[SingleTurnSample(
        user_input=row["question"], response=row["answer"], retrieved_contexts=row["contexts"],
        reference=row["ground_truth"]) for row in rows])
    llm, embeddings = _make_evaluator()
    metrics = [Faithfulness(), ResponseRelevancy(strictness=1),
               LLMContextPrecisionWithReference(name="context_precision"), LLMContextRecall()]
    # Run in a clean thread: RAGAS creates its own event loop without patching
    # Streamlit's loop or disabling dataset dtype validation.
    def run():
        return evaluate(dataset, metrics=metrics, llm=llm, embeddings=embeddings,
                               run_config=RunConfig(timeout=120, max_retries=1, max_workers=1),
                               raise_exceptions=False, show_progress=False, allow_nest_asyncio=False)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(run).result()
    scores = []
    for score in result.scores:
        scores.append({key: float(score[key]) if key in score and math.isfinite(float(score[key])) else None
                       for key in METRICS})
    if len(scores) != len(rows):
        raise RuntimeError("Evaluator returned an incomplete result set.")
    report_dir = Path(os.getenv("RAGAS_REPORT_DIR", str(data_dir() / "reports")))
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", report_name or "ragas")[:60] or "ragas"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = report_dir / f"{stem}_{stamp}_{uuid.uuid4().hex[:8]}.csv"
    fields = ["question", "ground_truth", "answer", "contexts", *METRICS]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row, score in zip(rows, scores):
            values = {**row, "contexts": json.dumps(row["contexts"], ensure_ascii=False), **score}
            # Prevent uploaded text being treated as formulas when CSV is opened.
            values = {k: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for k, v in values.items()}
            writer.writerow(values)
    summary = {key: statistics.mean(s[key] for s in scores if s[key] is not None)
               if any(s[key] is not None for s in scores) else None for key in METRICS}
    summary.update(count=len(rows), failed_cells=sum(s[k] is None for s in scores for k in METRICS),
                   csv_path=str(path), scores=scores,
                   evaluator_model=os.getenv("RAGAS_GROQ_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")))
    summary_path = path.with_suffix(".json")
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    return summary
