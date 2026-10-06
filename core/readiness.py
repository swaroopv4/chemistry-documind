"""Inspectable setup checks; no credentials are returned or rotated."""
import json
import os
from core.access import require_admin,oidc_configured
from core import audit,catalog,keyword_index,ocr


def checks(principal):
    require_admin(principal)
    events = audit.recent(principal,1000)
    roles = {json.loads(row['details']).get('role') for row in events if row['event']=='session_started'
             and not json.loads(row['details']).get('local_preview')}
    return [
        {'check':'Groq key configured','ready':bool(os.getenv('GROQ_API_KEY'))},
        {'check':'Pinecone key configured','ready':bool(os.getenv('PINECONE_API_KEY'))},
        {'check':'Verified UCI sign-in configured','ready':oidc_configured()},
        {'check':'Admin account allowlist configured','ready':bool(os.getenv('ADMIN_EMAILS'))},
        {'check':'Real admin sign-in observed','ready':'admin' in roles},
        {'check':'Real student sign-in observed','ready':'student' in roles},
        {'check':'Outside-UCI sign-in rejected in live test','ready':any(row['event']=='outside_uci_rejected' for row in events)},
        {'check':'Local PDF OCR tools available','ready':ocr.available()},
        {'check':'Keyword index populated','ready':keyword_index.status()['chunks']>0},
        {'check':'Reviewed chemistry documents published','ready':bool(catalog.published())}]
