"""Generate the local cookie secret without displaying any credentials."""
from pathlib import Path
import secrets
from dotenv import dotenv_values,set_key

if __name__=='__main__':
    path = Path(__file__).resolve().parents[1]/'.env'
    if not path.is_file():
        raise SystemExit('Create the private .env from .env.example first.')
    values = dotenv_values(path)
    if not values.get('OIDC_COOKIE_SECRET'):
        set_key(path,'OIDC_COOKIE_SECRET',secrets.token_urlsafe(48))
    if not values.get('ADMIN_EMAILS'):
        set_key(path,'ADMIN_EMAILS','admin@uci.edu')
    print('Local cookie/admin settings prepared; no secrets printed. Add Google OAuth client ID/secret privately, then restart.')
