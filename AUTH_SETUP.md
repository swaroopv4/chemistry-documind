# Verified UCI sign-in

Google OIDC is the default. This uses Google's identity service; the app does not create a password database. Knowing or typing an @uci.edu email address cannot grant access. The app checks Streamlit-validated identity claims: Google's issuer, verified email, managed-domain `hd=uci.edu`, exact @uci.edu suffix, subject and token expiry. The `hd` request hint only improves the login screen; the server checks the returned claim independently. Ordinary/unverified Google accounts, similar-looking domains and expired sessions are rejected.

Each deployment needs its own Google OAuth web client and private credentials. Validate real administrator/student logins and rejection of non-UCI accounts; local previews are not evidence of real provider authentication.

Set `ADMIN_EMAILS` to the exact approved UCI administrator address(es), comma separated. Configure the exact administrator addresses privately for your deployment. Every other accepted UCI account receives the student chat view. Administrative permissions are evaluated on every rerun and are not controlled by a URL, browser setting or user-supplied role. Account changes clear session history. Streamlit handles OAuth state/nonce and token/cookie validation. Identity/access tokens are not exposed to the frontend.

## Google setup

Follow the official [Streamlit Google sign-in guide](https://docs.streamlit.io/develop/tutorials/authentication/google) and [Google OIDC documentation](https://developers.google.com/identity/openid-connect/openid-connect). OAuth login does not require a paid compute deployment or a new AI API key. You may need UCI approval if its Workspace policy blocks external applications.

1. In a Google Cloud project you control, configure Google Auth Platform branding/audience. Use only `openid`, `email`, and `profile` scopes. Google's [publishing-state guide](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview) documents an exception to the Testing allowlist for these basic identity scopes; the app itself still rejects non-UCI accounts. Use the appropriate production audience and complete required branding verification before a campus launch. UCI Workspace administrators can block external apps regardless of their publishing state. A personal project cannot designate itself as a UCI internal organization app.
2. Create an OAuth client of type **Web application**. Add `http://localhost:8501` as a local origin and `http://localhost:8501/oauth2callback` as its authorized redirect URI. Add the actual HTTPS cloud origin/callback before deploying.
3. Put the client ID and secret in the application's ignored `.env`; do not paste them into source, screenshots or chat. Set `OIDC_PROVIDER=google`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_COOKIE_SECRET` (at least 32 random characters), `OIDC_REDIRECT_URI`, and `ADMIN_EMAILS`. Generate a random cookie secret privately.
4. Restart the app through `python ui/launch.py` or Docker Compose. The launcher generates the ignored `.streamlit/secrets.toml` before Streamlit starts. It preserves manually maintained secrets files rather than overwriting them. Even if local Compose's preview flag is present, configured OIDC credentials disable the local bypass.
5. Verify that the approved admin account sees Admin/Student chat workspaces; another verified UCI account sees only chat; a non-UCI account is refused. This real-provider login test is still required once credentials are supplied. The offline tests validate claims/roles and UI gating but cannot sign in to Google on your behalf.

Streamlit identity cookies can otherwise persist for 30 days. This app additionally checks the original ID token expiry on every rerun; an expired session must sign out and authenticate again. [Streamlit authentication behavior](https://docs.streamlit.io/develop/concepts/connections/authentication).

## Local preview and deployment

The local Compose stack is bound to 127.0.0.1 and explicitly enables `DOCUMIND_LOCAL_ADMIN=true` while OAuth is absent, preserving the owner's existing local admin workflow. **Student chat** in that local admin workspace is a preview, not proof of verified sign-in. Never expose that local stack publicly. The cloud stack sets the bypass to false, and the production launcher rejects both a bypass and missing OAuth credentials. Public production sign-in requires HTTPS.

An optional Microsoft single-tenant path is included: set OIDC_PROVIDER=microsoft and the actual UCI OIDC_TENANT_ID, register a web client in that tenant, and set the same client/cookie/callback variables. The app requires the expected issuer/tenant, subject/object ID, exact UCI UPN and rejects tokens marked as guests. It does not use `/common` or arbitrary tenants. UCI administrator consent may be required. Google is the configured default and the recommended path for this project.

No app can promise universal jailbreak immunity or perfect automatic PII detection. Verified identity, role separation, private-document exclusion, input classification, identifier redaction, output privacy validation, bounded requests and safe caches provide layered controls. Only publish reviewed/anonymized chemistry documents. Private mixed-content files should be anonymized into a separate reviewed copy before publication.
