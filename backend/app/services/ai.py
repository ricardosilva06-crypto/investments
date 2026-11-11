"""Local AI availability check (Ollama). Phase 3 builds the analyst on top.

Nothing here contacts a paid provider. If Ollama is not running, the rest of
the application keeps working and the UI explains how to enable it.
"""

import httpx

from ..config import get_settings


def ollama_status(timeout: float = 1.5) -> dict:
    url = get_settings().ollama_url.rstrip("/")
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=timeout)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        return {"available": True, "url": url, "models": models, "message": ""}
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "available": False,
            "url": url,
            "models": [],
            "message": f"Ollama is not reachable at {url} ({exc.__class__.__name__}).",
        }
