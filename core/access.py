"""Authorization uses verified Streamlit OIDC claims, never an email textbox."""
from dataclasses import dataclass
import hashlib
import os
import time
import uuid


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    email: str = ""
    local_preview: bool = False

    @property
    def audit_id(self):
        return hashlib.sha256(self.subject.encode()).hexdigest()[:16]


def oidc_configured():
    return all(os.getenv(key) for key in ("OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_COOKIE_SECRET"))


def authorize_claims(claims, logged_in=True, now=None):
    """Only call with claims from st.user, whose token/cookie Streamlit validates."""
    if not logged_in or not claims.get("sub"):
        raise PermissionError("Sign in with your UCI account.")
    now = time.time() if now is None else now
    expiry = claims.get("exp")
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or expiry <= now:
        raise PermissionError("Your sign-in has expired. Sign out and sign in again.")
    provider = os.getenv("OIDC_PROVIDER", "google")
    if provider == "google":
        if claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}:
            raise PermissionError("Unsupported identity issuer.")
        if claims.get("email_verified") is not True or claims.get("hd") != "uci.edu":
            raise PermissionError("Use your managed UCI Google account with a verified @uci.edu email.")
        email = claims.get("email", "")
    elif provider == "microsoft":
        tenant = os.getenv("OIDC_TENANT_ID", "")
        try:
            uuid.UUID(tenant)
        except ValueError:
            raise PermissionError("The UCI Microsoft tenant has not been configured.") from None
        if claims.get("tid") != tenant or claims.get("iss") != f"https://login.microsoftonline.com/{tenant}/v2.0":
            raise PermissionError("Use the configured UCI Microsoft tenant.")
        if not claims.get("oid") or claims.get("acct") == 1:
            raise PermissionError("Guest accounts are not permitted.")
        email = claims.get("preferred_username", "")
    else:
        raise PermissionError("Unsupported sign-in provider.")
    email = email.strip().lower() if isinstance(email, str) else ""
    if email.count("@") != 1 or email.split("@")[1] != "uci.edu" or not email.split("@")[0]:
        raise PermissionError("Only @uci.edu accounts can use this application.")
    admins = {address.strip().lower() for address in os.getenv("ADMIN_EMAILS", "").split(",") if address.strip()}
    return Principal(f"{provider}:{claims['sub']}", "admin" if email in admins else "student", email)


def require_identity():
    import streamlit as st
    # Explicit local-only development mode. Production launcher refuses it.
    local = os.getenv("DOCUMIND_LOCAL_ADMIN", "false").lower() == "true"
    if local and os.getenv("DEPLOYMENT_ENV", "local") != "production" and not oidc_configured():
        principal = Principal("local-admin-preview", "admin", local_preview=True)
    else:
        if not oidc_configured():
            st.title("Chemistry research assistant")
            st.info("Verified UCI sign-in is not configured yet. Access is closed until the administrator completes identity setup.")
            st.stop()
        if not st.user.is_logged_in:
            from ui import design
            label = "Google" if os.getenv("OIDC_PROVIDER", "google") == "google" else "Microsoft"
            if design.login(label):
                st.login()
            st.stop()
        try:
            principal = authorize_claims(dict(st.user), st.user.is_logged_in)
        except PermissionError as error:
            claims = dict(st.user)
            if (claims.get('iss') in {'https://accounts.google.com','accounts.google.com'}
                    and claims.get('email_verified') is True and claims.get('sub')
                    and isinstance(claims.get('exp'),(int,float)) and claims['exp']>time.time()
                    and (claims.get('hd')!='uci.edu' or not str(claims.get('email','')).lower().endswith('@uci.edu'))):
                from core.audit import record
                try:
                    record(Principal('google:'+claims['sub'],'denied'),'outside_uci_rejected')
                except Exception:
                    pass
            st.error(str(error))
            if st.button("Sign out"):
                st.logout()
            st.stop()
    previous = st.session_state.get("_identity")
    identity = principal.subject+':'+principal.role
    if previous is not None and previous != identity:
        st.session_state.clear()
    if previous != identity:
        from core.audit import record
        try:
            record(principal,'session_started',{'role':principal.role,'local_preview':principal.local_preview})
        except Exception:
            pass
    st.session_state["_identity"] = identity
    return principal


def require_admin(principal):
    if not isinstance(principal, Principal) or principal.role != "admin":
        raise PermissionError("Administrator access is required.")
