"""Shared HTTP access to SEC EDGAR, honouring the SEC fair-access policy.

* Every request carries the configured User-Agent (name + contact e-mail).
* Requests are spaced so this process never exceeds ~5 requests/second
  (the SEC limit is 10/s per user, we stay well below it).
"""

import threading
import time

import httpx

from ..config import get_settings


class SecError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


_MIN_INTERVAL = 0.2  # seconds between requests -> max 5 req/s
_lock = threading.Lock()
_last_request = 0.0

# Tests replace this with a factory returning an httpx.Client(transport=MockTransport(...)).
client_factory = lambda: httpx.Client(timeout=30, follow_redirects=True)  # noqa: E731


def user_agent() -> str:
    ua = get_settings().sec_user_agent
    if "@" not in ua:
        raise SecError(
            "Set II_SEC_USER_AGENT to a name and contact e-mail (required by the SEC fair-access policy)."
        )
    return ua


def get_json(url: str) -> dict:
    global _last_request
    ua = user_agent()
    with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    try:
        with client_factory() as client:
            resp = client.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    except httpx.HTTPError as exc:
        raise SecError(f"Network error contacting SEC: {exc.__class__.__name__}") from exc
    if resp.status_code == 404:
        raise SecError("SEC has no data for this company at this endpoint.", 404)
    if resp.status_code == 403:
        raise SecError("SEC refused the request (403). Check II_SEC_USER_AGENT.", 403)
    if resp.status_code == 429:
        raise SecError("SEC rate limit reached (429). Try again later.", 429)
    if resp.status_code != 200:
        raise SecError(f"SEC returned HTTP {resp.status_code}", resp.status_code)
    try:
        return resp.json()
    except ValueError as exc:
        raise SecError("SEC response was not valid JSON") from exc
