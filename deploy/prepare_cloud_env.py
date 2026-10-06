"""Create a private cloud configuration from local keys; never prints secrets."""
from pathlib import Path
import json
import secrets
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]


def main():
    destination=ROOT/'.env.cloud'
    if destination.exists():
        raise SystemExit('Existing .env.cloud was preserved. Edit it directly.')
    original=dotenv_values(ROOT/'.env')
    defaults=dotenv_values(ROOT/'.env.cloud.example')
    allowed=('GROQ_API_KEY','PINECONE_API_KEY','GROQ_MODEL','PINECONE_INDEX_NAME',
             'PINECONE_CLOUD','PINECONE_REGION','ADMIN_EMAILS','OIDC_PROVIDER','OIDC_TENANT_ID','OIDC_CLIENT_ID','OIDC_CLIENT_SECRET')
    for key in allowed:
        if original.get(key):defaults[key]=original[key]
    if original.get('ADMIN_EMAILS'):
        defaults['TLS_EMAIL']=original['ADMIN_EMAILS'].split(',')[0].strip()
    for key in ('OIDC_COOKIE_SECRET','BROKER_REDIS_PASSWORD','CACHE_REDIS_PASSWORD'):
        defaults[key]=secrets.token_urlsafe(48)
    destination.write_text('\n'.join(f'{key}={json.dumps(value or "")}' for key,value in defaults.items())+'\n',encoding='utf-8')
    destination.chmod(0o600)
    print('Created ignored .env.cloud with fresh internal secrets. Set the hostname, TLS email and real OAuth credentials before deployment. No secrets were printed.')


if __name__=='__main__':main()
