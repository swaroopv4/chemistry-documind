import json
import streamlit as st
from core.access import require_admin


def render(principal):
    require_admin(principal)
    st.subheader('Before public deployment')
    st.caption('Local preview does not count as a verified sign-in test.')
    from core.readiness import checks
    st.dataframe(checks(principal),hide_index=True,width='stretch')
    st.info('Google OAuth client ID, client secret and a cookie secret are needed for UCI sign-in. Follow AUTH_SETUP.md. Replace the Groq and Pinecone keys shared in chat through their provider consoles, update the private .env, and restart. This page cannot verify key rotation.')
    st.subheader('Encrypted state backup')
    st.caption('Includes policies, settings, keyword index, versions, feedback, budgets and local metrics/logs. Remote Pinecone vectors, Redis queues, original uploads and credentials are excluded. Finish pending jobs first.')
    if st.button('Prepare encrypted backup'):
        from core import backups
        try:
            with st.spinner('Taking consistent database snapshots…'):
                st.session_state['_prepared_backup'] = backups.export(principal)
        except Exception as error:
            st.error(str(error))
    if st.session_state.get('_prepared_backup'):
        payload,manifest = st.session_state['_prepared_backup']
        st.download_button('Download encrypted backup',payload,'documind-state.fernet','application/octet-stream')
        st.json(manifest)
    st.caption('The separate decryption key is BACKUP_ENCRYPTION_KEY or data/.backup-key on the server. Save it securely separately from the archive. Restore using deploy/backup.py into a new directory; existing live data is preserved.')
    st.subheader('Chemistry retrieval benchmark')
    st.caption('32 original reference cases cover formulas, units, identifiers and chemistry concepts. The offline check uses BM25 without API calls. It is a fixture test, not a score for your uploaded corpus. Optional dense/hybrid comparison uses your Pinecone embedding quota without writing vectors or calling Groq.')
    if st.button('Run offline chemistry benchmark'):
        from core.benchmark import run
        with st.spinner('Checking reference-case retrieval…'):
            st.session_state['_benchmark'] = run()
    if '_benchmark' in st.session_state:
        report = st.session_state['_benchmark']
        st.json({k:v for k,v in report.items() if k!='cases'})
        st.download_button('Download benchmark report',json.dumps(report,indent=2),'chemistry_benchmark.json','application/json')
