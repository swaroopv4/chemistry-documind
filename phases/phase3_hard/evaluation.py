from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics

from .guardrails import redact_pii
from .storage import connect, data_dir


@dataclass
class QueryMetrics:
    question: str
    answer: str
    retrieved_chunks: int
    retrieval_score: float | None
    faithfulness: float  # tutorial field; this is only a lexical grounding estimate
    latency_ms: float
    cache_hit: bool
    timestamp: float
    status: str = "answered"
    retrieval_mode: str = 'dense'
    keyword_chunks: int = 0


def log_query(metrics: QueryMetrics) -> None:
    payload = asdict(metrics)
    payload["question"] = redact_pii(payload["question"])[0]
    payload["answer"] = redact_pii(payload["answer"])[0]
    serialized = json.dumps(payload, ensure_ascii=False)
    with connect() as db:
        db.execute("INSERT INTO queries(payload) VALUES (?)", (serialized,))
        db.execute("DELETE FROM queries WHERE id NOT IN (SELECT id FROM queries ORDER BY id DESC LIMIT 10000)")
    # SQLite is authoritative for cross-process reads; JSONL is the tutorial's
    # inspectable log export. One append write per line, without provider keys.
    path = Path(os.getenv("EVAL_LOG_FILE", str(data_dir() / "logs" / "query_log.jsonl")))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (serialized + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def load_logs(n: int | None = None) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT payload FROM queries ORDER BY id DESC LIMIT ?", (n or 10000,)).fetchall()
    return [json.loads(row[0]) for row in reversed(rows)]


def score_faithfulness(answer: str, retrieved_chunks: list[dict]) -> float:
    """Cheap word overlap heuristic; NOT a factual faithfulness measurement."""
    words = lambda text: {w for w in re.findall(r"\b\w{4,}\b", text.casefold())}
    context = words(" ".join(s.get("text", "") for s in retrieved_chunks))
    # Ignore the citation-warning footer and the citation itself.
    answer = answer.split("⚠ Citation check:")[0]
    answer = re.sub(r"\(Source:.*?\)", "", answer, flags=re.I)
    sentences = [words(s) for s in re.split(r"[.!?]\s*", answer) if words(s)]
    if not context or not sentences:
        return 0.
    return round(sum(len(s & context) >= 2 for s in sentences) / len(sentences), 3)


def get_metrics_summary(n: int = 100) -> dict:
    rows = load_logs(n)
    answered = [r for r in rows if r.get("status", "answered") == "answered"]
    result = {"count": len(rows), "answered": len(answered), "blocked": sum(r.get("status") == "blocked" for r in rows)}
    for field in ("faithfulness", "retrieval_score", "latency_ms"):
        values = [r[field] for r in answered if r.get(field) is not None]
        result["avg_" + field] = statistics.mean(values) if values else 0.
    result['dense_scored_queries'] = sum(r.get('retrieval_score') is not None for r in answered)
    latency = sorted(r["latency_ms"] for r in answered)
    result["p95_latency_ms"] = latency[max(0, math.ceil(.95 * len(latency)) - 1)] if latency else 0.
    result["cache_hit_rate"] = sum(r["cache_hit"] for r in answered) / len(answered) if answered else 0.
    return result


@dataclass
class DriftAlert:
    metric: str
    baseline: float
    current: float
    drop_pct: float
    severity: str


def check_drift() -> list[DriftAlert]:
    window = max(2, int(os.getenv("BASELINE_WINDOW", "50")))
    threshold = float(os.getenv("DRIFT_THRESHOLD", "0.15"))
    rows = [r for r in load_logs() if r.get("status", "answered") == "answered" and not r["cache_hit"]]
    if len(rows) < window * 2:
        return []
    old, new = rows[-2*window:-window], rows[-window:]
    alerts = []
    for metric in ("faithfulness", "retrieval_score"):
        # Do not mix old dense-only windows with a new hybrid configuration, or
        # fabricate cosine scores for keyword-only answers.
        if len({r.get('retrieval_mode','dense') for r in old+new}) != 1:
            continue
        if any(r.get(metric) is None for r in old+new):
            continue
        baseline = statistics.mean(r[metric] for r in old)
        current = statistics.mean(r[metric] for r in new)
        drop = (baseline - current) / baseline if baseline > 0 else 0
        if drop > threshold:
            alerts.append(DriftAlert(metric, baseline, current, drop * 100,
                                     "critical" if drop > threshold * 2 else "warning"))
    return alerts
