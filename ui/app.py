import sys
import os
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import streamlit as st
from core.pipeline import (
    ingest_document, submit_uploaded_document, get_ingest_status,
    query_document, async_available, remove_document,
)
from phases.phase3_hard import cache, evaluation, guardrails
from phases.phase4_obs import metrics_store
from core.access import require_identity
from core import catalog, audit

st.set_page_config(page_title="DocuMind · Chemistry", page_icon="⚗️", layout="wide")
from ui import design
design.apply_theme()

principal = require_identity()
if principal.role == 'student':
    from ui.chat import render_chat
    render_chat(principal)
    st.stop()
with st.sidebar:
    design.brand()
    if principal.local_preview:
        st.caption('Local admin session · public access requires UCI sign-in')
    else:
        st.caption('UCI administrator')
        if st.button('Sign out', key='admin_logout'):
            st.logout()
    workspace = st.radio('Workspace', ['Admin','Student chat'], horizontal=True)
if workspace == 'Student chat':
    from ui.chat import render_chat
    render_chat(principal)
    st.stop()

missing = [k for k in ["GROQ_API_KEY", "PINECONE_API_KEY"] if not os.getenv(k)]
if missing:
    st.warning(f"Missing: {', '.join(missing)} — add to .env and restart.")

if "jobs" not in st.session_state:
    st.session_state["jobs"] = {}

with st.sidebar:
    st.markdown('<div class="dm-section-label">Processing &amp; retrieval</div>',unsafe_allow_html=True)
    background = st.toggle("Process uploads in background", value=True)
    chunk_size = st.slider("Chunk size (tokens)", 100, 800, 400, 50)
    chunk_overlap = st.slider("Chunk overlap (tokens)", 0, 150, 50, 10)
    top_k = st.slider("Top-k chunks", 1, 15, 5, 1)
    st.caption(f"Safety checks {'on' if guardrails.enabled() else 'off'} · Answer cache {'on' if cache.enabled() else 'off'}")
    from core.retrieval import mode as retrieval_mode
    st.caption('Hybrid retrieval · semantic + BM25 keywords' if retrieval_mode() == 'hybrid' else 'Semantic retrieval only')
    if guardrails.enabled():
        st.caption("Answers are checked before display; this adds a wait before the first text.")
    if st.button("Check queue connection"):
        if async_available():
            st.success("Redis is connected. Start the worker to process queued jobs.")
        else:
            st.warning("Redis is unavailable. Start the services using the README instructions.")

design.hero('admin')
tab_ask, tab_jobs, tab_eval, tab_ragas, tab_dash, tab_docs, tab_logs, tab_ready = st.tabs(["Ask", "Job queue", "Eval & metrics", "RAGAS evaluation", "Dashboard", "Documents", "Logs & Redis", "Readiness"])

with tab_ask:
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Upload**")
        uploaded = st.file_uploader("Upload document", type=["pdf", "ppt", "pptx", "docx", "mol2", "cif"], max_upload_size=20)
        st.caption("Text, slides, Word tables and chemical records. Scanned PDFs use local OCR in Docker.")
        st.caption('New and replaced files stay private until reviewed and published in Documents.')
        if uploaded and st.button('Preview parsed chunks', key='preview_upload'):
            from core.ingestion import ingest_file
            try:
                with tempfile.TemporaryDirectory() as folder:
                    preview_path = Path(folder)/Path(uploaded.name.replace('\\','/')).name
                    preview_path.write_bytes(uploaded.getvalue())
                    preview_chunks = ingest_file(preview_path, chunk_size, chunk_overlap)
                st.caption(f'{len(preview_chunks)} chunks; preview shows the first 10. No embeddings or index writes are made.')
                for chunk in preview_chunks[:10]:
                    with st.expander(f"Chunk {chunk.chunk_index} · {chunk.metadata.get('locator','source')} · {chunk.token_count} tokens"):
                        st.text(guardrails.redact_pii(chunk.text)[0])
            except Exception:
                st.error('Parsing preview failed. Check the file format and chunk settings.')
        if uploaded and st.button("Ingest document", width="stretch", disabled=bool(missing)):
            filename = Path(uploaded.name.replace("\\", "/")).name
            try:
                if background:
                    job_id = submit_uploaded_document(filename, uploaded.getvalue(), chunk_size, chunk_overlap,principal=principal)
                    st.session_state["jobs"][job_id] = {"filename": filename, "status": None}
                    st.success(f"Job submitted for {filename}")
                    st.code(job_id, language=None)
                    st.caption("Track progress in Job queue. You can keep asking questions.")
                else:
                    with tempfile.TemporaryDirectory() as folder:
                        path = Path(folder) / filename
                        path.write_bytes(uploaded.getvalue())
                        pb, cap = st.progress(0), st.empty()
                        result = ingest_document(path, chunk_size, chunk_overlap,
                            lambda step, pct: (pb.progress(pct), cap.caption(step)),principal=principal)
                        if result.status == "error":
                            st.error(result.error)
                        else:
                            st.success(f"Ingested: {result.doc_name}")
                            st.caption(f"{result.chunk_count} chunks · {result.page_count} source units · {result.total_tokens:,} tokens")
                            st.session_state.pop("documents", None)
            except Exception as error:
                st.error(str(error))

    with right:
        st.markdown("**Question**")
        question = st.text_area("Question",
            placeholder="What cell parameters or molecule details are reported?",
            height=110, label_visibility="collapsed")
        col1, col2 = st.columns([4, 1])
        show_chunks = col2.toggle("Sources", value=True)
        ask = col1.button("Ask", width="stretch", disabled=bool(missing))
        answered = False
        if ask:
            if not question.strip():
                st.warning("Enter a question.")
            else:
                try:
                    gen, sources = query_document(question=question, top_k=top_k, stream=True)
                    st.markdown("**Answer**")
                    answer = st.write_stream(gen)
                    st.session_state["last_answer"] = answer
                    st.session_state["last_sources"] = sources
                    st.session_state["last_result"] = gen.result
                    answered = True
                except Exception as error:
                    st.error(str(error))
        if "last_answer" in st.session_state:
            if not answered:
                st.markdown("**Answer**")
                st.markdown(st.session_state["last_answer"])
            sources = st.session_state.get("last_sources", [])
            result = st.session_state.get("last_result")
            if result:
                st.caption(f"{'Cache hit' if result.cache_hit else 'Fresh query'} · {result.latency_ms:,.0f} ms · {result.status.replace('_', ' ')}")
                if result.cache_hit:
                    st.caption(f"Cached question: {result.cached_question} · similarity {result.cache_similarity:.3f}")
            if show_chunks and sources:
                st.divider()
                st.caption(f"SOURCES — {len(sources)} chunks")
                for i, chunk in enumerate(sources, 1):
                    if 'hybrid_score' in chunk:
                        cosine = f"{chunk['dense_score']:.3f}" if 'dense_score' in chunk else 'not ranked in dense candidates'
                        st.markdown(f"**{i}** · {chunk['doc_name']} · {chunk['locator']} · {chunk['retrieval_method']}")
                        st.caption(f"RRF rank score {chunk['hybrid_score']:.5f} · dense cosine {cosine}")
                        if 'bm25_score' in chunk:
                            st.caption(f"BM25 {chunk['bm25_score']:.5g} · keyword coverage {chunk['lexical_coverage']:.0%}")
                    else:
                        st.markdown(f"**{i}** · {chunk['doc_name']} · {chunk['locator']} · similarity {chunk['score']:.3f}")
                    st.write(chunk["text"][:350] + ("..." if len(chunk["text"]) > 350 else ""))
            elif not sources and (result is None or result.status == "answered"):
                st.caption("No chunks found — ingest a document first.")

with tab_jobs:
    st.markdown("**Job queue**")
    auto_refresh = st.toggle("Update progress automatically", value=True)
    with st.container(key="job_lookup_controls"):
        st.markdown('<style>.st-key-job_lookup_controls [data-testid="InputInstructions"] {display: none;}</style>', unsafe_allow_html=True)
        with st.form("job_lookup_form", enter_to_submit=False, border=False):
            job_lookup = st.text_input("Look up a job ID", placeholder="Paste a previously submitted job ID")
            st.caption("Paste the Job ID, then click Track job.")
            track_job = st.form_submit_button("Track job")
        if track_job:
            if not job_lookup.strip():
                st.warning("Enter a Job ID, then click Track job.")
            else:
                try:
                    status = get_ingest_status(job_lookup.strip())
                    st.session_state["jobs"][status.job_id] = {"filename": "Tracked document", "status": status}
                    st.success("Job added to the tracking list below.")
                except Exception as error:
                    st.error(str(error))

    terminal = {"SUCCESS", "FAILURE", "REVOKED"}
    active = any(job["status"] is None or job["status"].state not in terminal
                 for job in st.session_state["jobs"].values())

    @st.fragment(run_every="2s" if auto_refresh and active else None)
    def render_jobs():
        st.button("Refresh jobs")
        jobs = st.session_state["jobs"]
        if not jobs:
            st.info("No jobs yet. Upload a document to start background processing.")
            return
        for job_id, job in list(jobs.items()):
            status = job["status"]
            previous_state = status.state if status else None
            try:
                if status is None or status.state not in terminal:
                    status = get_ingest_status(job_id)
                    job["status"] = status
                st.markdown(f"**{job['filename']} · {status.state}**")
                st.caption(f"Job ID: {job_id}")
                st.progress(status.pct, text=status.step)
                if status.state == "SUCCESS":
                    result = status.result or {}
                    st.success(f"{result.get('doc_name', job['filename'])}: "
                               f"{result.get('chunk_count', 0)} chunks · "
                               f"{result.get('page_count', 0)} source units · "
                               f"{result.get('total_tokens', 0):,} tokens")
                    if previous_state != "SUCCESS":
                        st.session_state.pop("documents", None)
                elif status.state == "FAILURE":
                    st.error(status.error)
                elif status.state == "PENDING":
                    st.caption("If this stays queued, check that the Celery worker is running. Unknown or expired IDs also show PENDING.")
                if status.state in terminal and st.button("Dismiss", key=f"dismiss_{job_id}"):
                    del jobs[job_id]
                    st.rerun()
            except Exception:
                st.warning("Unable to read job status. Check the Redis connection and refresh.")
        if active and jobs and all(job["status"] and job["status"].state in terminal for job in jobs.values()):
            st.rerun()  # stop the timer; cached answer and form values survive

    render_jobs()

with tab_eval:
    st.markdown("**Query monitoring**")
    st.button("Refresh metrics")
    st.caption("Recent 100 queries. Word overlap is a lexical grounding estimate, not RAGAS faithfulness or a guarantee of correctness.")
    try:
        summary = evaluation.get_metrics_summary()
        cols = st.columns(4)
        cols[0].metric("Queries / blocked", f"{summary['count']} / {summary['blocked']}")
        cols[1].metric("Lexical grounding", f"{summary['avg_faithfulness']:.3f}")
        cols[2].metric("Retrieval similarity", f"{summary['avg_retrieval_score']:.3f}" if summary['dense_scored_queries'] else '—')
        st.caption('Retrieval similarity averages dense cosine scores only. Keyword-only answers have no cosine score. Hybrid rank scores are not confidence probabilities.')
        cols[3].metric("Cache hit rate", f"{summary['cache_hit_rate']:.0%}")
        st.caption(f"Answered queries: {summary['answered']} · Average latency {summary['avg_latency_ms']:,.0f} ms · P95 {summary['p95_latency_ms']:,.0f} ms")
        info = cache.cache_stats()
        st.caption(f"Cache entries: {info['entries']} · Similarity threshold {info['threshold']:.2f}")
        if st.button("Clear answer cache"):
            cache.clear_cache()
            st.rerun()
        window = max(2, int(os.getenv('BASELINE_WINDOW', '50')))
        fresh_count = sum(r.get('status', 'answered') == 'answered' and not r['cache_hit'] for r in evaluation.load_logs())
        alerts = evaluation.check_drift()
        if fresh_count < window * 2:
            st.info(f"Drift baseline needs {window * 2} fresh answered queries; currently {fresh_count}.")
        elif alerts:
            for alert in alerts:
                label = 'lexical grounding' if alert.metric == 'faithfulness' else 'retrieval similarity'
                st.warning(f"{alert.severity.title()}: {label} dropped {alert.drop_pct:.1f}% ({alert.baseline:.3f} → {alert.current:.3f}).")
        else:
            st.success("No monitored score drop detected between the two recent windows.")
        st.caption("Drift compares recent query windows. A different mix of questions or documents can change these scores.")
        recent = evaluation.load_logs(20)
        if recent:
            st.dataframe([{k: r.get(k) for k in ('question', 'status', 'retrieval_mode', 'keyword_chunks', 'retrieved_chunks', 'retrieval_score', 'latency_ms', 'cache_hit')} for r in reversed(recent)], width="stretch")
    except Exception:
        st.warning("Monitoring storage is unavailable. Check the data directory permissions.")

with tab_ragas:
    st.markdown("**Evaluate against reference answers**")
    st.caption("Upload JSON with question and ground_truth for each row. The app retrieves fresh answers with cache bypassed. Optionally supply answer and contexts for every row to evaluate a saved dataset.")
    st.caption("Uses Groq for the judge and Pinecone for relevance embeddings. Evaluation makes additional API calls and can take several minutes. Judge scores depend on the selected model.")
    example = [{"question": "What cell length a is reported in the CIF?", "ground_truth": "Replace this with the verified value and units from your own CIF."}]
    st.download_button("Download test-set template", json.dumps(example, indent=2), "test_set.json", "application/json")
    test_upload = st.file_uploader("Evaluation test set", type=["json"], key="test_set", max_upload_size=5)
    rows = None
    if test_upload:
        try:
            from phases.phase3_hard.ragas_eval import validate_test_set
            if test_upload.size > 5 * 1024 * 1024:
                raise ValueError("Test set must be smaller than 5 MB.")
            rows = validate_test_set(json.loads(test_upload.getvalue().decode("utf-8-sig")))
            st.caption(f"{len(rows)} validated rows")
            st.dataframe([{"question": r['question'], "ground_truth": r['ground_truth']} for r in rows], width="stretch")
        except Exception as error:
            st.error(str(error))
    if st.button("Run RAGAS evaluation", disabled=bool(missing) or rows is None):
        try:
            from phases.phase3_hard.ragas_eval import build_test_set_from_pipeline, run_ragas_eval
            with st.spinner("Retrieving fresh answers and scoring with RAGAS…"):
                if "answer" not in rows[0]:
                    progress = st.progress(0, text="Building evaluation answers")
                    rows = build_test_set_from_pipeline(rows, top_k=top_k, progress_callback=progress.progress)
                    progress.empty()
                st.session_state['ragas_result'] = run_ragas_eval(rows)
        except Exception as error:
            st.error(guardrails.redact_pii(str(error))[0])
    if 'ragas_result' in st.session_state:
        report = st.session_state['ragas_result']
        names = [('faithfulness', 'Faithfulness'), ('answer_relevancy', 'Answer relevancy'), ('context_precision', 'Context precision'), ('context_recall', 'Context recall')]
        for column, (key, label) in zip(st.columns(4), names):
            column.metric(label, f"{report[key]:.3f}" if report[key] is not None else "Unavailable")
        st.caption(f"{report['count']} rows · Judge: {report['evaluator_model']}")
        if report['failed_cells']:
            st.warning(f"Partial evaluation: {report['failed_cells']} metric cells failed. Averages exclude failed cells; CSV leaves them blank.")
        else:
            st.success("All evaluation metrics completed.")
        st.dataframe(report['scores'], width="stretch")
        try:
            st.download_button("Download detailed CSV", Path(report['csv_path']).read_bytes(), Path(report['csv_path']).name, "text/csv")
        except OSError:
            st.warning("The saved report is unavailable on this app instance.")

with tab_dash:
    st.markdown("**Cost · latency · usage**")
    st.caption("Groq Q&A and student safety-check requests, plus Pinecone query, ingestion and evaluation embeddings. "
               "RAGAS judge calls, Pinecone database/storage charges, plan minimums, credits and taxes are excluded.")
    days = st.selectbox("Dashboard window", [1, 7, 14, 30], index=1,
                        format_func=lambda value: f"Last {value} days", key="dashboard_days")
    st.button("Refresh dashboard")
    if not metrics_store.enabled():
        st.info("New monitoring is disabled. Previously recorded metrics remain available.")
    try:
        import pandas as pd
        summary = metrics_store.get_summary(days)
        daily = metrics_store.get_daily_cost(days)
        latency = metrics_store.get_latency_series(days)
        recent = metrics_store.get_recent_calls(days=days)
        operations = metrics_store.get_recent_operations(days)
        cols = st.columns(4)
        cols[0].metric("Groq requests", f"{summary['llm_calls']:,}")
        cols[1].metric("Groq tokens", f"{summary['llm_tokens']:,}")
        cols[2].metric("Known estimated cost (USD)", f"${summary['cost_usd']:.6f}")
        cols[3].metric("Average Groq latency", f"{summary['avg_latency_ms']:,.0f} ms")
        cols = st.columns(4)
        cols[0].metric("Answer cache hits", f"{summary['cache_hits']:,}")
        cols[1].metric("Answer cache hit rate", f"{summary['cache_hit_rate']:.1%}")
        cols[2].metric("Embedding tokens", f"{summary['embedding_tokens']:,}")
        cols[3].metric("Documents ingested", f"{summary['documents_ingested']:,}")
        st.caption(f"Groq: USD {summary['llm_cost_usd']:.6f} · Embeddings: USD {summary['embedding_cost_usd']:.6f} · "
                   f"Retrieval: {summary['avg_retrieval_ms']:,.0f} ms average over {summary['retrievals']:,} searches. "
                   "All times are UTC. Prices were verified on 2026-10-05 and can be overridden in .env.")
        st.caption("Costs are token-rate estimates, not an invoice. Provider token counts include reasoning tokens when reported. "
                   "Fallback cl100k token counts are labeled estimated. An answer cache hit has zero Groq cost; its query embedding is still tracked. "
                   "Cache hit rate covers recorded Groq request and answer-cache events; blocked inputs and no-evidence responses are excluded.")
        if summary['unpriced_events']:
            st.warning(f"{summary['unpriced_events']} events have unknown cost. The displayed cost includes only priced events.")
        if summary['estimated_llm'] or summary['estimated_embeddings']:
            st.caption(f"Estimated token counts: {summary['estimated_llm']} Groq events and {summary['estimated_embeddings']} embedding events.")
        if daily:
            frame = pd.DataFrame(daily).set_index("day")
            left, right = st.columns(2)
            with left:
                st.caption("KNOWN ESTIMATED COST PER DAY (USD)")
                st.bar_chart(frame[["known_cost_usd"]], height=200)
            with right:
                st.caption("GROQ REQUESTS AND CACHE HITS PER DAY")
                st.bar_chart(frame[["llm_calls", "cache_hits"]], height=200)
        else:
            st.info("No monitoring events in this window. Ask a document question or ingest a document to start recording.")
        if latency:
            st.caption("AVERAGE GROQ LATENCY PER DAY (MS)")
            st.line_chart(pd.DataFrame(latency).set_index("day"), height=180)
        if recent:
            st.markdown("**Recent Groq requests and answer cache hits**")
            frame = pd.DataFrame(recent)
            frame["time_utc"] = pd.to_datetime(frame.pop("ts"), unit="s", utc=True)
            st.dataframe(frame.drop(columns=["id"]), width="stretch", hide_index=True)
        for name, rows in operations.items():
            if rows:
                with st.expander(f"Recent {name}"):
                    frame = pd.DataFrame(rows)
                    frame["time_utc"] = pd.to_datetime(frame.pop("ts"), unit="s", utc=True)
                    st.dataframe(frame.drop(columns=["id"]), width="stretch", hide_index=True)
        st.caption("Ingestion total_tokens counts chunk content, including overlap, using cl100k estimates. "
                   "Embedding batch costs are counted once in the cost total, even if a later upload step fails.")
    except Exception as error:
        st.warning(f"Monitoring storage is unavailable ({type(error).__name__}). Document features remain available.")

with tab_docs:
    from ui.admin_controls import batch_upload, document_policies
    batch_upload(principal,chunk_size,chunk_overlap,missing)
    st.divider()
    document_policies(principal,missing)
    st.divider()
    st.markdown("**Indexed documents**")
    refresh = st.button("Refresh", disabled=bool(missing))
    if not missing and (refresh or "documents" in st.session_state):
        try:
            from core.vector_store import list_indexed_documents, get_index_stats
            if refresh:
                st.session_state["stats"] = get_index_stats()
                st.session_state["documents"] = list_indexed_documents()
                catalog.sync_names(st.session_state['documents'])
            stats = st.session_state["stats"]
            st.caption(f"{stats['total_vectors']:,} vectors · {stats['dimension']} dims · cosine")
            st.caption("Document names are sampled from up to 100 matching vectors.")
            for doc in st.session_state["documents"]:
                c1, c2 = st.columns([6, 1])
                c1.markdown(f"`{doc}`")
                if c2.button("Remove", key=f"d_{doc}"):
                    policy = next(row for row in catalog.list_documents() if row['name']==doc)
                    catalog.set_policy(doc,'private',policy['label'],principal)
                    remove_document(doc)
                    catalog.remove_policy(doc,principal)
                    audit.record(principal,'document_removed',{'document':doc})
                    del st.session_state["documents"]
                    st.rerun()
        except Exception as error:
            st.error(str(error))
    elif not missing:
        st.caption("Click Refresh to load indexed documents.")

with tab_logs:
    from ui.admin_controls import logs_and_redis
    logs_and_redis(principal)

with tab_ready:
    from ui.readiness import render
    render(principal)
