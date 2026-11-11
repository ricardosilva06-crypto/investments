"""Minimal OAuth 2.1 authorization server for the Claude connector.

Implements what Claude's remote-MCP client needs and nothing more:
- Dynamic Client Registration (RFC 7591), public clients only (no client secrets);
- authorization code grant with mandatory PKCE S256;
- refresh tokens, rotated on every use;
- redirect URIs restricted to an allow-list (Claude's hosted callback by default).

Users sign in with their normal app username and password. All tokens are random
and stored only as SHA-256 hashes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import OAuthClient, OAuthCode, OAuthGrant, User
from ..security import new_token, sha256

SCOPE = "investor"
CODE_TTL = timedelta(minutes=5)
MAX_CLIENTS = 200
_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9\-_]{43,128}$")


class OAuthError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400):
        super().__init__(description or error)
        self.error = error
        self.description = description
        self.status = status

    def body(self) -> dict:
        out = {"error": self.error}
        if self.description:
            out["error_description"] = self.description
        return out


# ------------------------------------------------------------------ configuration
def base_url() -> str:
    return get_settings().connector_public_url.strip().rstrip("/")


def enabled() -> bool:
    u = base_url()
    return u.startswith("https://") or u.startswith("http://localhost") or u.startswith("http://127.0.0.1")


def mcp_url() -> str:
    return base_url() + "/mcp"


def resource_metadata_url() -> str:
    return base_url() + "/.well-known/oauth-protected-resource/mcp"


def allowed_redirects() -> set[str]:
    return {u.strip() for u in get_settings().connector_redirect_uris.split(",") if u.strip()}


def _same_resource(value: str) -> bool:
    v = value.strip().rstrip("/")
    return v in (mcp_url(), base_url())


def protected_resource_metadata() -> dict:
    return {
        "resource": mcp_url(),
        "authorization_servers": [base_url()],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Investor Intelligence",
    }


def authorization_server_metadata() -> dict:
    b = base_url()
    return {
        "issuer": b,
        "authorization_endpoint": f"{b}/oauth/authorize",
        "token_endpoint": f"{b}/oauth/token",
        "registration_endpoint": f"{b}/oauth/register",
        "scopes_supported": [SCOPE],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
    }


# ------------------------------------------------------------------ clients (DCR)
def _prune_clients(db: Session) -> None:
    """Drop registrations older than a day that never received a grant."""
    cutoff = utcnow() - timedelta(days=1)
    granted = select(OAuthGrant.client_id)
    db.execute(delete(OAuthClient).where(OAuthClient.created_at < cutoff, OAuthClient.client_id.not_in(granted)))
    db.execute(delete(OAuthCode).where(OAuthCode.expires_at < utcnow()))


def register_client(db: Session, data: dict) -> dict:
    if not isinstance(data, dict):
        raise OAuthError("invalid_client_metadata", "Body must be a JSON object")
    uris = data.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris) or len(uris) > 5:
        raise OAuthError("invalid_redirect_uri", "redirect_uris must be a non-empty list")
    allowed = allowed_redirects()
    bad = [u for u in uris if u not in allowed]
    if bad:
        raise OAuthError("invalid_redirect_uri", "Only the Claude app callback URLs are accepted by this server")
    grants = data.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grants, list) or "authorization_code" not in grants:
        raise OAuthError("invalid_client_metadata", "grant_types must include authorization_code")
    _prune_clients(db)
    if len(db.scalars(select(OAuthClient.id)).all()) >= MAX_CLIENTS:
        raise OAuthError("invalid_client_metadata", "Too many registered clients; try again tomorrow", status=429)
    name = str(data.get("client_name") or "Claude")[:200]
    c = OAuthClient(client_id="ii-" + secrets.token_urlsafe(24), client_name=name, redirect_uris=json.dumps(uris))
    db.add(c)
    db.commit()
    return {
        "client_id": c.client_id,
        "client_id_issued_at": int(c.created_at.timestamp()),
        "client_name": name,
        "redirect_uris": uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    }


def get_client(db: Session, client_id: str | None) -> OAuthClient | None:
    if not client_id or len(client_id) > 64:
        return None
    return db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))


def client_redirects(c: OAuthClient) -> list[str]:
    try:
        return [u for u in json.loads(c.redirect_uris) if isinstance(u, str)]
    except ValueError:
        return []


# ------------------------------------------------------------------ authorization request
def validate_authorize(db: Session, params: dict) -> tuple[OAuthClient, str]:
    """Checks that must pass before we may redirect back to the client. Raises OAuthError
    with status 400 when the error must be shown to the user instead of redirected."""
    client = get_client(db, params.get("client_id"))
    if client is None:
        raise OAuthError("invalid_client", "Unknown client. Remove the connector in Claude and add it again.")
    redirect_uri = params.get("redirect_uri") or ""
    redirects = client_redirects(client)
    if not redirect_uri and len(redirects) == 1:
        redirect_uri = redirects[0]
    if redirect_uri not in redirects or redirect_uri not in allowed_redirects():
        raise OAuthError("invalid_request", "The redirect URI is not registered for this client.")
    return client, redirect_uri


def redirect_errors(params: dict) -> OAuthError | None:
    """Errors that are reported back to the client through the redirect."""
    if params.get("response_type") != "code":
        return OAuthError("unsupported_response_type", "Only response_type=code is supported")
    if params.get("code_challenge_method") != "S256" or not _CHALLENGE_RE.match(params.get("code_challenge") or ""):
        return OAuthError("invalid_request", "PKCE with code_challenge_method=S256 is required")
    resource = params.get("resource")
    if resource and not _same_resource(resource):
        return OAuthError("invalid_target", "Unknown resource")
    scopes = set((params.get("scope") or SCOPE).split())
    if not scopes <= {SCOPE, "offline_access"}:
        return OAuthError("invalid_scope", f"Supported scope: {SCOPE}")
    return None


def create_code(db: Session, client: OAuthClient, user: User, redirect_uri: str, params: dict) -> str:
    code = new_token()
    db.add(OAuthCode(
        code_hash=sha256(code), client_id=client.client_id, user_id=user.id, redirect_uri=redirect_uri,
        code_challenge=params["code_challenge"], scope=SCOPE, resource=(params.get("resource") or "")[:500],
        expires_at=utcnow() + CODE_TTL,
    ))
    db.commit()
    return code


def redirect_host(uri: str) -> str:
    return urlsplit(uri).hostname or uri


# ------------------------------------------------------------------ tokens
def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _issue(grant: OAuthGrant) -> dict:
    cfg = get_settings()
    access, refresh = new_token(), new_token()
    now = utcnow()
    grant.access_hash, grant.refresh_hash = sha256(access), sha256(refresh)
    grant.access_expires_at = now + timedelta(minutes=cfg.connector_access_minutes)
    grant.refresh_expires_at = now + timedelta(days=cfg.connector_refresh_days)
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": cfg.connector_access_minutes * 60,
        "refresh_token": refresh,
        "scope": grant.scope,
    }


def exchange_code(db: Session, form: dict) -> dict:
    code = form.get("code") or ""
    row = db.scalar(select(OAuthCode).where(OAuthCode.code_hash == sha256(code))) if code else None
    if row is None or row.used or row.expires_at <= utcnow():
        if row is not None and row.used:
            # A replayed code: revoke whatever it produced, as OAuth 2.1 recommends.
            for g in db.scalars(select(OAuthGrant).where(OAuthGrant.client_id == row.client_id, OAuthGrant.user_id == row.user_id)):
                g.revoked = True
            db.commit()
        raise OAuthError("invalid_grant", "Authorization code is invalid or expired")
    if form.get("client_id") != row.client_id:
        raise OAuthError("invalid_grant", "Code was issued to another client")
    if (form.get("redirect_uri") or row.redirect_uri) != row.redirect_uri:
        raise OAuthError("invalid_grant", "redirect_uri does not match")
    verifier = form.get("code_verifier") or ""
    if not _VERIFIER_RE.match(verifier) or not secrets.compare_digest(_s256(verifier), row.code_challenge):
        raise OAuthError("invalid_grant", "PKCE verification failed")
    if form.get("resource") and not _same_resource(form["resource"]):
        raise OAuthError("invalid_target", "Unknown resource")
    row.used = True
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        db.commit()
        raise OAuthError("invalid_grant", "Account is disabled")
    client = get_client(db, row.client_id)
    grant = OAuthGrant(user_id=user.id, client_id=row.client_id, client_name=client.client_name if client else "Claude",
                       scope=row.scope, access_hash="", access_expires_at=utcnow(), refresh_hash="",
                       refresh_expires_at=utcnow())
    tokens = _issue(grant)
    db.add(grant)
    db.commit()
    return tokens


def refresh(db: Session, form: dict) -> dict:
    token = form.get("refresh_token") or ""
    grant = db.scalar(select(OAuthGrant).where(OAuthGrant.refresh_hash == sha256(token))) if token else None
    if grant is None or grant.revoked or grant.refresh_expires_at <= utcnow():
        raise OAuthError("invalid_grant", "Refresh token is invalid, expired or revoked")
    if form.get("client_id") and form["client_id"] != grant.client_id:
        raise OAuthError("invalid_grant", "Refresh token was issued to another client")
    if form.get("resource") and not _same_resource(form["resource"]):
        raise OAuthError("invalid_target", "Unknown resource")
    user = db.get(User, grant.user_id)
    if user is None or not user.is_active:
        raise OAuthError("invalid_grant", "Account is disabled")
    tokens = _issue(grant)
    db.commit()
    return tokens


def authenticate(db: Session, token: str) -> tuple[User, OAuthGrant] | None:
    if not token:
        return None
    grant = db.scalar(select(OAuthGrant).where(OAuthGrant.access_hash == sha256(token)))
    now = utcnow()
    if grant is None or grant.revoked or grant.access_expires_at <= now:
        return None
    user = db.get(User, grant.user_id)
    if user is None or not user.is_active:
        return None
    if grant.last_used_at is None or now - grant.last_used_at > timedelta(minutes=5):
        grant.last_used_at = now
        db.commit()
    return user, grant


def active_grants(db: Session, user_id: int) -> list[OAuthGrant]:
    return list(db.scalars(
        select(OAuthGrant).where(OAuthGrant.user_id == user_id, OAuthGrant.revoked.is_(False),
                                 OAuthGrant.refresh_expires_at > utcnow()).order_by(OAuthGrant.created_at.desc())
    ))
