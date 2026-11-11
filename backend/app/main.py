"""INVESTOR INTELLIGENCE API + static PWA host.

Run locally:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .config import get_settings
from .db import init_db
from .routers import account, admin, ai, auth, companies, research, notes, portfolios, securities, watchlists

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "InvestorIntelligence"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Investor Intelligence", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # CSRF defence: state-changing API calls must carry a custom header. Browsers
    # cannot add custom headers to cross-site requests without a CORS preflight,
    # and this server never grants CORS. Combined with SameSite=Lax cookies.
    if request.url.path.startswith("/api/") and request.method in UNSAFE_METHODS:
        if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


for r in (auth, securities, companies, research, watchlists, notes, portfolios, account, admin, ai):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_not_found(path: str):
    return JSONResponse({"detail": "Not found"}, status_code=404)


# ------------------------------------------------------------- static frontend
def _resolve_static(dist: Path, path: str) -> Path | None:
    clean = path.strip("/")
    candidates = [dist / clean] if clean else []
    candidates += [dist / f"{clean}.html", dist / clean / "index.html"] if clean else [dist / "index.html"]
    root = dist.resolve()
    for c in candidates:
        try:
            resolved = c.resolve()
        except OSError:
            continue
        if resolved.is_file() and resolved.is_relative_to(root):
            return resolved
    return None


@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def frontend(path: str):
    dist = get_settings().frontend_dist
    if not dist.exists():
        return JSONResponse(
            {"detail": "Frontend not built. Run `npm run build` in frontend/, or use `npm run dev` on port 3000."},
            status_code=404,
        )
    target = _resolve_static(dist, path)
    if target is None:
        not_found = dist / "404.html"
        return FileResponse(not_found, status_code=404) if not_found.exists() else Response(status_code=404)
    headers = {}
    if target.name in ("sw.js", "manifest.webmanifest") or target.suffix == ".html":
        headers["Cache-Control"] = "no-cache"
    elif "/_next/static/" in target.as_posix():
        headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return FileResponse(target, headers=headers)
