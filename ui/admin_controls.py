import json
import os
import streamlit as st
from core import audit, catalog, redis_cache
from core.access import require_admin
from core.settings import get_settings, save_settings


def batch_upload(principal, chunk_size, overlap, missing):
    require_admin(principal)
    st.markdown('**Ingest multiple documents**')
    files = st.file_uploader('Select documents for a batch', type=['pdf','ppt','pptx','docx','mol2','cif'],
                            accept_multiple_files=True, max_upload_size=20, key='batch_upload')
    st.caption('Up to 50 files / 250 MB total. Each file gets its own background job. New and replaced documents stay private until you review and publish them below.')
    personal = st.checkbox('This batch contains personal details', value=True, key='batch_personal')
    if st.button('Ingest selected documents', disabled=bool(missing) or not files):
        from core.batch import submit_batch
        try:
            if len(files)>50 or sum(file.size for file in files)>250*1024*1024:
                raise ValueError('Select at most 50 files with at most 250 MB combined size.')
            with st.spinner('Submitting document jobs…'):
                results = submit_batch([(file.name,file.getvalue()) for file in files], principal, chunk_size, overlap, personal)
            st.session_state['batch_results'] = results
            for result in results:
                if result['job_id']:
                    st.session_state['jobs'][result['job_id']] = {'filename': result['filename'], 'status': None}
        except ValueError as error:
            st.error(str(error))
        except Exception:
            st.error('Batch submission is unavailable. Check the services and try again.')
    if st.session_state.get('batch_results'):
        st.dataframe(st.session_state['batch_results'], width='stretch', hide_index=True)
        st.caption('Follow submitted jobs in Job queue. Review each successful document before publishing it to students.')


def document_policies(principal, missing):
    require_admin(principal)
    from core import keyword_index
    from core.retrieval import mode
    st.markdown('**Hybrid retrieval**')
    status = keyword_index.status()
    st.caption(f"Mode: {mode()} · Keyword index: {status['chunks']:,} chunks across {status['documents']:,} documents.")
    st.caption('Semantic Pinecone matches and independent BM25 keyword matches are merged. New uploads update both indexes automatically. Rebuild here for existing vectors or changes made outside this app; it reads existing text without re-embedding or changing Pinecone.')
    if st.button('Rebuild keyword index from existing vectors', disabled=bool(missing)):
        try:
            with st.spinner('Reading stored chunks and rebuilding the keyword index…'):
                rebuilt = keyword_index.rebuild_from_pinecone(principal)
            st.success(f"Keyword index ready: {rebuilt['chunks']:,} chunks / {rebuilt['documents']:,} documents. Student access policies were preserved.")
            st.rerun()
        except ValueError as error:
            st.error(str(error))
        except Exception:
            st.error('Keyword rebuild could not finish. Check the index status and Pinecone before retrying.')
    st.markdown('**Student access and personal information**')
    st.caption('Private documents are excluded from student retrieval and cached answers. Unreviewed existing vectors start private. Basic redaction and student safety checks are always enforced, including on published documents.')
    if st.button('Discover existing vector documents', disabled=bool(missing)):
        from core.vector_store import scan_document_names
        try:
            with st.spinner('Scanning vector IDs and document metadata…'):
                names, scanned, truncated = scan_document_names()
                catalog.sync_names(names)
            st.success(f'Discovered {len(names)} documents from {scanned:,} vectors. No document was automatically published.')
            if truncated:
                st.warning('The scan reached the 10,000-vector limit. The catalog is incomplete; undiscovered documents remain unavailable to students.')
        except Exception:
            st.error('Document discovery failed. Check Pinecone and retry.')
    for document in catalog.list_documents():
        name = document['name']
        with st.expander(f"{name} · {document['visibility']} · {document['chunks']} recorded chunks"):
            private = st.checkbox('Contains personal details / keep private from students',
                                  value=document['visibility'] != 'published', key='privacy_'+name)
            label = st.text_input('Student source label (avoid personal names)', value=document['label'], key='label_'+name)
            reviewed = st.checkbox('I reviewed this document and source label for personal information', value=False, key='review_'+name)
            ocr_reviewed = True
            if document.get('ocr_pages',0):
                st.warning(f"{document['ocr_pages']} pages used OCR. Check chemical formulas, units and values against the scan.")
                ocr_reviewed = st.checkbox('I checked OCR chemistry text against the original scan',key='ocr_review_'+name)
            if st.button('Save student access', key='save_policy_'+name, disabled=not private and (not reviewed or not ocr_reviewed)):
                try:
                    catalog.set_policy(name, 'private' if private else 'published', label, principal)
                    st.success('Saved. Cached answers were invalidated.')
                    st.rerun()
                except Exception:
                    st.error('The document policy could not be saved. Retry before allowing student access.')
            if st.button('Inspect stored chunks', key='inspect_'+name, disabled=bool(missing)):
                from core.vector_store import document_chunks
                try:
                    st.session_state['chunks_'+name] = document_chunks(name)
                except Exception:
                    st.error('Chunk inspection failed.')
            if 'chunks_'+name in st.session_state:
                st.caption('Sample of up to 20 stored chunks; common personal identifiers are redacted. Review the original document for unlabeled personal data before publishing.')
                for chunk in st.session_state['chunks_'+name]:
                    st.write(f"Chunk {chunk['chunk']} · {chunk['locator']}")
                    st.text(chunk['text'])
    from core import versions
    with st.expander('Document version history'):
        history = versions.history(principal)
        st.dataframe(history,hide_index=True,width='stretch')
        st.caption('Identical bytes and parsing settings skip embedding. Changed files get a new version. Previous versions remain stored and private until reviewed.')
        pending = [row['name'] for row in history if row['state'] in {'queued','processing','uncertain'}]
        if pending:
            selected = st.selectbox('Pending version to reconcile',pending)
            if st.button('Resolve confirmed failed job'):
                try:
                    versions.reconcile_failure(selected,principal)
                    st.success('Confirmed failure recorded. This file can be retried.')
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
                except Exception:
                    st.error('Job status is unavailable; the reservation was preserved.')


def logs_and_redis(principal):
    require_admin(principal)
    st.markdown('**Answer caching**')
    settings = get_settings()
    names = {'lru':'Recently used (LRU)', 'fifo':'Last questions added (FIFO)',
             'lfu':'Frequently asked (LFU)', 'ttl':'All answers within expiry', 'disabled':'Disabled'}
    with st.form('cache_settings'):
        strategy = st.selectbox('Retention strategy', list(names), index=list(names).index(settings['cache_strategy']), format_func=names.get)
        capacities = [50,100,250,500,1000]
        if settings['cache_capacity'] not in capacities:
            capacities.append(settings['cache_capacity'])
            capacities.sort()
        capacity = st.selectbox('Maximum cached questions', capacities, index=capacities.index(settings['cache_capacity']))
        ttl = st.number_input('Expiry (seconds)', min_value=60,max_value=604800,value=settings['cache_ttl'],step=60)
        semantic = st.checkbox('Enable semantic matching for student questions', value=settings['student_semantic_cache'])
        top_k = st.slider('Student retrieval chunks',1,15,settings['student_top_k'])
        st.caption('LRU with 100 answers is the default. LFU suits stable FAQs. FIFO keeps the latest new questions. All-with-expiry ignores the count limit but still has expiry and a 128 MB Redis memory ceiling. Exact repeats skip embedding and model calls. Semantic matching can confuse similar chemical questions; it is off for students by default.')
        if st.form_submit_button('Apply cache settings'):
            try:
                save_settings({**settings,'cache_strategy':strategy,'cache_capacity':capacity,'cache_ttl':int(ttl),
                               'student_semantic_cache':semantic,'student_top_k':top_k}, principal)
                st.success('Settings saved for all app/worker processes; old answer caches were invalidated.')
                st.rerun()
            except Exception:
                st.error('Settings could not be saved.')
    if st.button('Clear Redis and semantic answer caches'):
        from phases.phase3_hard.cache import clear_cache
        clear_cache()
        redis_cache.clear_answers()
        audit.record(principal,'answer_cache_cleared')
        st.success('Answer caches cleared. The ingestion broker and queue were not cleared.')
    st.markdown('**Redis service health**')
    from ui.readiness_controls import provider_settings
    provider_settings(principal)
    if st.button('Check Redis and worker health'):
        result = {}
        try:
            result['answer_cache'] = redis_cache.status()
        except Exception:
            result['answer_cache'] = {'connected':False}
        try:
            import redis
            from phases.phase2_async.worker import celery_app, BROKER, QUEUE
            with redis.Redis.from_url(BROKER, socket_connect_timeout=1,socket_timeout=1) as connection:
                result['ingestion_broker'] = {'connected':connection.ping(),'pending_jobs':connection.llen(QUEUE)}
            result['responsive_workers'] = len(celery_app.control.inspect(timeout=2).ping() or {})
        except Exception:
            result['ingestion_broker'] = {'connected':False}
        st.session_state['redis_health'] = result
    if 'redis_health' in st.session_state:
        st.json(st.session_state['redis_health'])
    audit_history(principal)
    from core import feedback
    st.markdown('**Student answer feedback**')
    responses = feedback.recent(principal)
    if responses:
        st.dataframe(responses,hide_index=True,width='stretch')
        st.download_button('Download feedback',json.dumps(responses,indent=2),'feedback.json','application/json')
    else:
        st.caption('No feedback yet. Students can report helpful, incorrect or incomplete answers directly in chat.')


def _move_audit_page(delta):
    st.session_state['audit_page'] = max(0,st.session_state.get('audit_page',0)+delta)


def audit_history(principal):
    require_admin(principal)
    st.markdown('**Admin and access events**')
    if st.button('Refresh logs'):
        st.session_state.pop('audit_anchor',None)
        st.session_state['audit_page'] = 0
    view = audit.page(principal,st.session_state.get('audit_page',0),
                      through_id=st.session_state.get('audit_anchor'))
    st.session_state['audit_anchor'] = view['through_id']
    st.session_state['audit_page'] = view['number']
    records = view['records']
    if records:
        import pandas as pd
        frame = pd.DataFrame(records)
        frame['time_utc'] = pd.to_datetime(frame.pop('ts'),unit='s',utc=True)
        st.dataframe(frame.drop(columns=['id']),width='stretch',hide_index=True)
        start = view['number']*100+1
        st.caption(f"Showing logs {start:,}–{start+len(records)-1:,} of {view['total']:,} · Page {view['number']+1} of {view['pages']} · Newest first")
        previous,next_page = st.columns(2)
        previous.button('Previous (newer)',disabled=view['number']==0,
                        on_click=_move_audit_page,args=(-1,))
        next_page.button('Next (older)',disabled=view['number']+1>=view['pages'],
                         on_click=_move_audit_page,args=(1,))
        count = st.number_input('Number of audit logs to download',min_value=1,
                                max_value=audit.MAX_ENTRIES,value=200,step=1)
        exported = audit.recent(principal,count)
        st.caption(f'Download includes the latest {len(exported):,} available entries, regardless of the page shown. Up to 20,000 entries are retained; use Refresh logs to load new activity.')
        st.download_button('Download audit logs (JSON)',json.dumps(exported,indent=2),
                           'audit_logs.json','application/json')
    else:
        st.info('No access/admin events recorded yet.')
    st.caption('Actors use pseudonymous identifiers. Query outcomes remain in Eval & metrics; model/embedding/retrieval events are in Dashboard. Logs are visible only to administrators.')
