import streamlit as st
from core.settings import get_settings,save_settings
from core.access import require_admin


def provider_settings(principal):
    require_admin(principal)
    from core import provider_limits
    st.markdown('**Shared AI limits and parsing**')
    st.caption('Limits cover answers, safety checks, evaluations and embedding jobs across app/worker processes. Set them below your provider account allowance. They do not change provider billing settings.')
    st.dataframe(provider_limits.status(),hide_index=True,width='stretch')
    settings = get_settings()
    fields = [
        ('groq_requests_minute','Groq requests / minute',1,1000),
        ('groq_requests_day','Groq requests / rolling 24 hours',1,100000),
        ('groq_tokens_minute','Groq tokens / minute',1024,1000000),
        ('groq_tokens_day','Groq tokens / rolling 24 hours',2048,10000000),
        ('embedding_tokens_day','Pinecone embedding tokens / rolling 24 hours',1000,10000000),
        ('provider_concurrency','Concurrent AI requests',1,8),
        ('provider_timeout','Provider timeout (seconds)',10,120),
        ('answer_tokens','Maximum answer tokens',512,4096),
        ('context_tokens','Maximum evidence tokens',800,6000),
        ('conversation_ttl','Follow-up memory expiry (seconds)',60,3600),
        ('ocr_max_pages','Maximum OCR pages per PDF',1,50)]
    with st.expander('Change shared limits, follow-up memory and OCR'):
        with st.form('provider_settings'):
            values = dict(settings)
            for key,label,minimum,maximum in fields:
                values[key] = int(st.number_input(label,min_value=minimum,max_value=maximum,value=settings[key]))
            values['ocr_enabled'] = st.checkbox('Use local OCR for scanned PDF pages',value=settings['ocr_enabled'])
            if st.form_submit_button('Apply shared limits'):
                try:
                    save_settings(values,principal)
                    st.success('Shared settings saved.')
                    st.rerun()
                except Exception:
                    st.error('Settings could not be saved.')
