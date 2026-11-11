"""Remote MCP endpoint (Streamable HTTP transport, JSON responses, stateless).

Claude's hosted apps (web, desktop, iPhone/Android) call this endpoint from Anthropic's
servers with an OAuth bearer token issued by ``routers/oauth.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from ..db import session_factory
from ..services import mcp_tools, oauth

router = APIRouter(include_in_schema=False)

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SERVER_INFO = {"name": "investor-intelligence", "title": "Investor Intelligence", "version": "0.6.0"}
ALLOWED_ORIGINS = {"https://claude.ai", "https://claude.com"}


def _unauthorized(invalid: bool) -> JSONResponse:
    params = f'resource_metadata="{oauth.resource_metadata_url()}", scope="{oauth.SCOPE}"'
    if invalid:
        params = 'error="invalid_token", ' + params
    return JSONResponse({"error": "invalid_token" if invalid else "unauthorized"}, status_code=401,
                        headers={"WWW-Authenticate": f"Bearer {params}", "Cache-Control": "no-store"})


def _err(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _ok(id_: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _handle(msg: Any, user_id: int) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _err(None, -32600, "Invalid Request")
    method, id_ = msg.get("method"), msg.get("id")
    if method is None:
        return None  # a response from the client; nothing to do
    if "id" not in msg:
        return None  # notification (e.g. notifications/initialized)
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return _err(id_, -32602, "Invalid params")

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _ok(id_, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": SERVER_INFO, "instructions": mcp_tools.SERVER_INSTRUCTIONS})
    if method == "ping":
        return _ok(id_, {})
    if method == "tools/list":
        return _ok(id_, {"tools": [t.schema() for t in mcp_tools.tools()]})
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            return _err(id_, -32602, "Missing tool name")
        db = session_factory()()
        try:
            from ..models import User

            user = db.get(User, user_id)
            if user is None or not user.is_active:
                return _err(id_, -32001, "Account disabled")
            try:
                text, is_error = mcp_tools.call(db, user, name, params.get("arguments") or {})
            except KeyError:
                return _err(id_, -32602, f"Unknown tool: {name}")
            except Exception as exc:  # never leak a stack trace to the client
                db.rollback()
                text, is_error = f"Internal error while running {name}: {type(exc).__name__}", True
        finally:
            db.close()
        return _ok(id_, {"content": [{"type": "text", "text": text}], "isError": is_error})
    if method in ("resources/list", "resources/templates/list", "prompts/list"):
        key = {"resources/list": "resources", "resources/templates/list": "resourceTemplates", "prompts/list": "prompts"}[method]
        return _ok(id_, {key: []})
    return _err(id_, -32601, f"Method not found: {method}")


def _authenticate(token: str) -> int | None:
    db = session_factory()()
    try:
        found = oauth.authenticate(db, token)
        return found[0].id if found else None
    finally:
        db.close()


@router.post("/mcp")
async def mcp_post(request: Request):
    if not oauth.enabled():
        return JSONResponse({"error": "Connector is not configured"}, status_code=404)
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in ALLOWED_ORIGINS | {oauth.base_url()}:
        return JSONResponse({"error": "Origin not allowed"}, status_code=403)
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    user_id = await run_in_threadpool(_authenticate, token) if token else None
    if user_id is None:
        return _unauthorized(invalid=bool(token))
    version = request.headers.get("mcp-protocol-version")
    if version and version not in SUPPORTED_VERSIONS:
        return JSONResponse(_err(None, -32600, f"Unsupported MCP-Protocol-Version: {version}"), status_code=400)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_err(None, -32700, "Parse error"), status_code=400)

    if isinstance(body, list):
        if not body:
            return JSONResponse(_err(None, -32600, "Invalid Request"), status_code=400)
        replies = [r for r in [await run_in_threadpool(_handle, m, user_id) for m in body] if r is not None]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await run_in_threadpool(_handle, body, user_id)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@router.get("/mcp")
@router.delete("/mcp")
def mcp_other():
    # No server-initiated stream and no sessions: this server is stateless.
    return Response(status_code=405, headers={"Allow": "POST"})
