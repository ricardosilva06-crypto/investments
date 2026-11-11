"""Public Claude connector: MCP endpoint + OAuth only.

Runs as a separate process so it can be exposed to the internet (Anthropic's servers must
reach it) while the full app stays private on your tailnet:

    uvicorn app.connector:app --host 127.0.0.1 --port 8001
    tailscale funnel --bg --https=8443 http://127.0.0.1:8001

Nothing else of the app (UI, /api) is served here.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .db import init_db
from .routers import mcp, oauth as oauth_router
from .services import oauth


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Investor Intelligence connector", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(oauth_router.router)
app.include_router(mcp.router)


@app.get("/health")
def health():
    return {"status": "ok", "configured": oauth.enabled()}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"], include_in_schema=False)
def not_found(path: str):
    return JSONResponse({"detail": "Not found"}, status_code=404)
