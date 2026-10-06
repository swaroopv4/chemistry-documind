"""Student view contains private session chat and reviewed source labels."""
import streamlit as st
from core.student import query_student
from core import conversation, feedback
from ui import design


def render_chat(principal):
    design.apply_theme()
    design.brand()
    design.hero('student')
    if principal.local_preview:
        st.info("Local admin preview of the student interface. Public access requires verified UCI sign-in.")
    current_scope = conversation.scope()
    identity = (principal.audit_id,current_scope)
    if st.session_state.get('_chat_scope')!=identity:
        st.session_state['chat_messages'],st.session_state['chat_memory'] = [],None
        st.session_state['_chat_scope'] = identity
    actions,account = st.columns([3,1])
    if actions.button("New conversation"):
        st.session_state["chat_messages"] = []
        st.session_state["chat_memory"] = None
        st.rerun()
    if not principal.local_preview and account.button("Sign out", key="chat_logout"):
        st.logout()
    if not st.session_state["chat_messages"]:
        design.welcome()
    for message in st.session_state["chat_messages"]:
        with st.chat_message(message["role"],avatar=":material/person:" if message['role']=='user' else ":material/science:"):
            if message['role']=='user':
                st.text(message['content'])
            else:
                st.text(message["content"])
            if message.get("sources"):
                with st.expander("Sources"):
                    for source in message["sources"]:
                        st.write(f"{source['doc_name']} · {source.get('locator','source')}")
                if any(source.get('ocr') for source in message['sources']):
                    st.caption('This answer uses scanned text. Verify chemical symbols and numbers against the original source.')
            if message.get('feedback_id'):
                render_feedback(message['feedback_id'],principal)
    question = st.chat_input("Ask a chemistry question", max_chars=4000)
    if question:
        from phases.phase3_hard.guardrails import redact_pii
        safe_question = redact_pii(question)[0]
        st.session_state["chat_messages"].append({"role": "user", "content": safe_question})
        with st.chat_message("user",avatar=":material/person:"):
            st.text(safe_question)
        with st.chat_message("assistant",avatar=":material/science:"):
            result = None
            try:
                with st.spinner("Checking the question and searching the chemistry documents…"):
                    effective = conversation.expand(question,st.session_state.get('chat_memory'),principal)
                    result = query_student(effective, principal)
                    remembered = conversation.remember(effective,result,principal)
                    if remembered:
                        st.session_state['chat_memory'] = remembered
                answer, sources = result.answer, result.sources
            except ValueError as error:
                answer, sources = str(error), []
            except Exception:
                answer, sources = "The question service is temporarily unavailable. Please try again shortly.", []
            st.text(answer)
            if sources:
                with st.expander("Sources"):
                    for source in sources:
                        st.write(f"{source['doc_name']} · {source.get('locator','source')}")
                if any(source.get('ocr') for source in sources):
                    st.caption('This answer uses scanned text. Verify chemical symbols and numbers against the original source.')
            if result and result.feedback_id:
                render_feedback(result.feedback_id,principal)
        if conversation.scope()!=current_scope:
            st.session_state['chat_messages'],st.session_state['chat_memory'] = [],None
            st.rerun()
        # UI history exposes selected safe fields only; no internal IDs/filenames.
        safe_sources = [{key: source.get(key, "") for key in ("doc_name", "locator", "ocr")} for source in sources]
        st.session_state["chat_messages"].append({"role": "assistant", "content": answer, "sources": safe_sources,"feedback_id":result.feedback_id if result else ""})
        st.session_state["chat_messages"] = st.session_state["chat_messages"][-100:]
    st.caption("Short follow-up context stays in this signed-in session and expires automatically. New conversation clears it. Personal-document content is unavailable.")


def render_feedback(identity,principal):
    st.markdown('**Was this answer useful?**')
    labels = {'helpful':'Helpful','incorrect':'Incorrect','missing_information':'Incomplete'}
    with st.form('feedback_'+identity):
        vote = st.radio('Your feedback',list(labels),format_func=labels.get,
                        horizontal=True,index=None)
        note = st.text_input('Optional comment (avoid personal information)',max_chars=500)
        if st.form_submit_button('Send feedback'):
            if vote is None:
                st.warning('Choose Helpful, Incorrect or Incomplete before sending.')
            else:
                try:
                    feedback.submit(principal,identity,vote,note)
                    st.session_state['feedback_sent_'+identity] = labels[vote]
                except (ValueError,PermissionError) as error:
                    st.error(str(error))
                except Exception:
                    st.error('Feedback is temporarily unavailable.')
    if st.session_state.get('feedback_sent_'+identity):
        st.success(f"Feedback saved: {st.session_state['feedback_sent_'+identity]}. Your administrator can review it.")
