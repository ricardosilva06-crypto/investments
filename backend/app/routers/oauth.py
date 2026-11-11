"""OAuth endpoints and discovery metadata for the Claude connector (public connector app only)."""

from __future__ import annotations

import html
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import RateLimiter, hash_password, login_failures, needs_rehash, verify_password
from ..services import oauth

router = APIRouter(include_in_schema=False)

# Registration is unauthenticated by design (DCR); keep it bounded.
register_limiter = RateLimiter(max_events=30, window_seconds=60 * 60)

AUTH_PARAMS = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state",
               "scope", "resource")
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _disabled() -> JSONResponse:
    return JSONResponse({"error": "temporarily_unavailable", "error_description": "Connector is not configured"},
                        status_code=404)


def _ip(request: Request) -> str:
    # Behind Tailscale Funnel the peer is the local proxy; the last X-Forwarded-For hop is the one it added.
    fwd = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    return fwd or (request.client.host if request.client else "unknown")


# ------------------------------------------------------------------ discovery
@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource():
    if not oauth.enabled():
        return _disabled()
    return JSONResponse(oauth.protected_resource_metadata())


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/mcp")
@router.get("/.well-known/openid-configuration")
def authorization_server():
    if not oauth.enabled():
        return _disabled()
    return JSONResponse(oauth.authorization_server_metadata())


# ------------------------------------------------------------------ registration
@router.post("/oauth/register")
async def register(request: Request, db: Session = Depends(get_db)):
    if not oauth.enabled():
        return _disabled()
    ip = _ip(request)
    if register_limiter.is_limited(ip):
        return JSONResponse({"error": "invalid_client_metadata", "error_description": "Too many registrations"},
                            status_code=429)
    register_limiter.hit(ip)
    try:
        data = await request.json()
    except ValueError:
        data = None
    try:
        return JSONResponse(oauth.register_client(db, data), status_code=201, headers=NO_STORE)
    except oauth.OAuthError as exc:
        return JSONResponse(exc.body(), status_code=exc.status, headers=NO_STORE)


# ------------------------------------------------------------------ authorization (sign-in + consent page)
PAGE_CSS = """
:root{color-scheme:dark light;--bg:#0b0d12;--card:#151922;--fg:#e8ebf2;--muted:#9aa3b5;--line:#2a3140;--accent:#3987e5;--err:#e5484d}
@media (prefers-color-scheme: light){:root{--bg:#f5f6f8;--card:#fff;--fg:#14171f;--muted:#5b6474;--line:#dde1e8;--accent:#2a78d6}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 -apple-system,system-ui,sans-serif;
padding:max(24px,env(safe-area-inset-top)) 16px 24px;display:flex;justify-content:center}
main{width:100%;max-width:420px}h1{font-size:20px;margin:8px 0 4px}p{margin:8px 0;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-top:16px}
ul{margin:8px 0 0;padding-left:20px;color:var(--fg)}li{margin:4px 0}
label{display:block;font-size:14px;color:var(--muted);margin:14px 0 6px}
input{width:100%;font-size:16px;padding:12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--fg)}
.row{display:flex;flex-direction:row-reverse;gap:12px;margin-top:20px}button{flex:1;font-size:16px;font-weight:600;padding:12px;border-radius:10px;border:1px solid var(--line);
background:transparent;color:var(--fg)}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.err{color:var(--err);margin-top:12px}.host{font-weight:600;color:var(--fg)}small{color:var(--muted)}
"""


def _page(body: str, status: int = 200) -> HTMLResponse:
    doc = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        "<meta name=referrer content=no-referrer><title>Connect Claude · Investor Intelligence</title>"
        f"<style>{PAGE_CSS}</style></head><body><main>{body}</main></body></html>"
    )
    return HTMLResponse(doc, status_code=status, headers={
        **NO_STORE, "X-Frame-Options": "DENY", "Content-Security-Policy":
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    })


def _error_page(message: str) -> HTMLResponse:
    return _page(f"<h1>Can't connect</h1><div class=card><p>{html.escape(message)}</p></div>", status=400)


def _redirect(uri: str, **params) -> RedirectResponse:
    params = {k: v for k, v in params.items() if v}
    params["iss"] = oauth.base_url()
    sep = "&" if "?" in uri else "?"
    return RedirectResponse(uri + sep + urlencode(params), status_code=302, headers=NO_STORE)


def _consent(client_name: str, redirect_uri: str, params: dict, error: str = "", username: str = "") -> HTMLResponse:
    hidden = "".join(
        f"<input type=hidden name='{k}' value='{html.escape(params.get(k) or '', quote=True)}'>" for k in AUTH_PARAMS
    )
    from ..config import get_settings

    write = get_settings().connector_write_tools
    err = f"<p class=err role=alert>{html.escape(error)}</p>" if error else ""
    body = f"""
<h1>Connect to Investor Intelligence</h1>
<p><span class=host>{html.escape(client_name)}</span> wants to use your account. After you allow it, you'll go back to
<span class=host>{html.escape(oauth.redirect_host(redirect_uri))}</span>.</p>
<div class=card>
<p>It will be able to:</p>
<ul><li>Read your portfolios, watchlists, notes and alerts</li>
<li>Search and read the PDFs you uploaded</li>
<li>Read company data, financials, prices and news stored in the app</li>
{'<li>Save new notes</li>' if write else ''}</ul>
<p><small>Data it reads is sent to Anthropic to answer your questions in Claude. You can revoke access at any time in
Settings → Claude connector.</small></p>
<form method=post action='/oauth/authorize' autocomplete=on>{hidden}
<label for=u>Username</label><input id=u name=username autocomplete=username autocapitalize=none required value='{html.escape(username, quote=True)}'>
<label for=p>Password</label><input id=p name=password type=password autocomplete=current-password required>
{err}
<div class=row><button class=primary type=submit name=decision value=allow>Allow</button>
<button type=submit name=decision value=deny formnovalidate>Deny</button></div>
</form></div>"""
    return _page(body, status=400 if error else 200)


@router.get("/oauth/authorize")
def authorize_page(request: Request, db: Session = Depends(get_db)):
    if not oauth.enabled():
        return _error_page("The Claude connector is not configured on this server.")
    params = {k: request.query_params.get(k) for k in AUTH_PARAMS}
    try:
        client, redirect_uri = oauth.validate_authorize(db, params)
    except oauth.OAuthError as exc:
        return _error_page(exc.description)
    params["redirect_uri"] = redirect_uri
    err = oauth.redirect_errors(params)
    if err:
        return _redirect(redirect_uri, error=err.error, error_description=err.description, state=params.get("state"))
    return _consent(client.client_name, redirect_uri, params)


@router.post("/oauth/authorize")
async def authorize_submit(request: Request, db: Session = Depends(get_db)):
    if not oauth.enabled():
        return _error_page("The Claude connector is not configured on this server.")
    form = await request.form()
    params = {k: (str(form.get(k)) if form.get(k) is not None else None) for k in AUTH_PARAMS}
    try:
        client, redirect_uri = oauth.validate_authorize(db, params)
    except oauth.OAuthError as exc:
        return _error_page(exc.description)
    params["redirect_uri"] = redirect_uri
    state = params.get("state")
    err = oauth.redirect_errors(params)
    if err:
        return _redirect(redirect_uri, error=err.error, error_description=err.description, state=state)
    if form.get("decision") != "allow":
        return _redirect(redirect_uri, error="access_denied", error_description="The user denied access", state=state)

    username = str(form.get("username") or "").strip().lower()[:40]
    password = str(form.get("password") or "")[:256]
    ip = _ip(request)
    if login_failures.is_limited(f"ip:{ip}") or login_failures.is_limited(f"user:{username}"):
        return _consent(client.client_name, redirect_uri, params, "Too many failed attempts. Try again in 15 minutes.", username)
    user = db.scalar(select(User).where(User.username == username))
    if not verify_password(user.password_hash if user else None, password) or user is None or not user.is_active:
        login_failures.hit(f"ip:{ip}")
        login_failures.hit(f"user:{username}")
        return _consent(client.client_name, redirect_uri, params, "Invalid username or password.", username)
    login_failures.reset(f"user:{username}")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
    code = oauth.create_code(db, client, user, redirect_uri, params)
    return _redirect(redirect_uri, code=code, state=state)


# ------------------------------------------------------------------ token
@router.post("/oauth/token")
async def token(request: Request, db: Session = Depends(get_db)):
    if not oauth.enabled():
        return _disabled()
    try:
        form = {k: str(v) for k, v in (await request.form()).items()}
    except Exception:  # malformed body
        form = {}
    grant_type = form.get("grant_type")
    try:
        if grant_type == "authorization_code":
            body = oauth.exchange_code(db, form)
        elif grant_type == "refresh_token":
            body = oauth.refresh(db, form)
        else:
            raise oauth.OAuthError("unsupported_grant_type", "Use authorization_code or refresh_token")
    except oauth.OAuthError as exc:
        return JSONResponse(exc.body(), status_code=exc.status, headers=NO_STORE)
    return JSONResponse(body, headers=NO_STORE)

