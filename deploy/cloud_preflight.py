"""Validate production settings without printing secret values or making API calls."""
import argparse
import ipaddress
from pathlib import Path
import re
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values


def placeholder(value):
    return not isinstance(value,str) or not value.strip() or value.lower().startswith(('your_','replace_with_'))


def validate(values):
    errors = []
    required = ['APP_DOMAIN','TLS_EMAIL','GROQ_API_KEY','PINECONE_API_KEY','ADMIN_EMAILS',
                'OIDC_CLIENT_ID','OIDC_CLIENT_SECRET','OIDC_COOKIE_SECRET',
                'BROKER_REDIS_PASSWORD','CACHE_REDIS_PASSWORD']
    for key in required:
        if placeholder(values.get(key)):
            errors.append(key+' needs a real value')
    domain = values.get('APP_DOMAIN','')
    if isinstance(domain,str):
        try:
            ipaddress.ip_address(domain)
            errors.append('APP_DOMAIN needs a DNS hostname for HTTPS and sign-in')
        except ValueError:
            if (len(domain)>253 or '.' not in domain or domain.endswith(('.example','.invalid','.localhost'))
                    or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',part) for part in domain.split('.'))):
                errors.append('APP_DOMAIN must be a valid public DNS hostname')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values.get('TLS_EMAIL') or ''):
        errors.append('TLS_EMAIL needs a valid certificate contact email')
    admins = [email.strip().lower() for email in (values.get('ADMIN_EMAILS') or '').split(',')]
    if not admins or any(not re.fullmatch(r'[^\s@]+@uci\.edu',email) for email in admins):
        errors.append('ADMIN_EMAILS must list exact UCI addresses')
    provider = values.get('OIDC_PROVIDER','google')
    if provider=='google':
        if not (values.get('OIDC_CLIENT_ID') or '').endswith('.apps.googleusercontent.com'):
            errors.append('OIDC_CLIENT_ID needs a Google web OAuth client ID')
    elif provider=='microsoft':
        for key in ('OIDC_TENANT_ID','OIDC_CLIENT_ID'):
            try:
                uuid.UUID(values.get(key) or '')
            except ValueError:
                errors.append(key+' needs the registered UCI tenant/client UUID')
    else:
        errors.append('OIDC_PROVIDER must be google or microsoft')
    cookie = values.get('OIDC_COOKIE_SECRET') or ''
    if len(cookie)<32:
        errors.append('OIDC_COOKIE_SECRET must have at least 32 random characters')
    for key in ('BROKER_REDIS_PASSWORD','CACHE_REDIS_PASSWORD'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,}',values.get(key) or ''):
            errors.append(key+' needs at least 32 URL-safe random characters')
    if values.get('BROKER_REDIS_PASSWORD')==values.get('CACHE_REDIS_PASSWORD'):
        errors.append('Broker and answer-cache passwords must differ')
    if (values.get('DOCUMIND_LOCAL_ADMIN') or '').lower() in {'true','1','yes'}:
        errors.append('Local admin preview must be disabled in cloud deployment')
    return list(dict.fromkeys(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',default=str(Path(__file__).resolve().parents[1]/'.env.cloud'))
    args = parser.parse_args()
    path = Path(args.env_file)
    if not path.is_file():
        raise SystemExit('Private cloud configuration is missing. Prepare .env.cloud first.')
    errors = validate(dotenv_values(path,interpolate=False))
    if errors:
        print('Cloud setup incomplete (no secret values shown):')
        for error in errors:
            print('- '+error)
        raise SystemExit(1)
    print('Production settings passed local validation. Real OAuth/key validity and Azure spending-limit checks remain separate.')


if __name__=='__main__': main()
