"""Short session-only follow-up context; no extra model or shared user memory."""
import re
import time
from core.settings import get_settings
from phases.phase3_hard import cache,guardrails

FOLLOW_UP = re.compile(r'(?i)\b(?:its|it|that compound|that molecule|those compounds|them|their)\b|^(?:and\b|what about\b|how about\b)')

def scope():
    return cache.current_scope(get_settings()['student_top_k'],None,audience='student')

def expand(question,memory,principal):
    question = guardrails.check_input(question)
    current = scope()
    if not memory or not current or memory.get('scope')!=current or memory.get('owner')!=principal.audit_id or memory.get('expires',0)<time.time():
        return question
    if not FOLLOW_UP.search(question):
        return question
    prior = memory.get('topic','')[:800]
    expanded = f'Previous chemistry question: {prior}\nCurrent chemistry question: {question}'
    return guardrails.check_input(expanded) if len(expanded)<=get_settings()['max_question_chars'] else question

def remember(question,result,principal):
    if result.status!='answered' or not result.sources:
        return None
    current = scope()
    if not current:
        return None
    return {'owner':principal.audit_id,'scope':current,'expires':time.time()+get_settings()['conversation_ttl'],
            'topic':guardrails.redact_pii(question)[0][:800]}
