"""Optional Web Push notifications (open standard, no paid service).

VAPID keys are generated locally on first use and stored in the data directory.
Payloads are end-to-end encrypted by the protocol; the browser vendor's push
service (Google, Apple, Mozilla) only relays an encrypted blob. Requires HTTPS
and, on iPhone, the app installed to the home screen (iOS 16.4+).
"""

from __future__ import annotations

import base64
import json
import logging
import threading

from sqlalchemy import select

from ..config import get_settings
from ..db import session_factory
from ..models import PushSubscription

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _key_path():
    return get_settings().data_dir / "vapid_private.pem"


def _vapid():
    from py_vapid import Vapid01

    path = _key_path()
    with _lock:
        if not path.exists():
            v = Vapid01()
            v.generate_keys()
            path.parent.mkdir(parents=True, exist_ok=True)
            v.save_key(str(path))
            path.chmod(0o600)
        return Vapid01.from_file(str(path))


def public_key() -> str:
    from cryptography.hazmat.primitives import serialization

    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def send(user_id: int, title: str, body: str, url: str = "/") -> int:
    """Send to all of a user's devices. Expired subscriptions are removed. Returns deliveries."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # optional dependency
        return 0
    db = session_factory()()
    sent = 0
    try:
        subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)).all()
        if not subs:
            return 0
        key = str(_key_path())
        _vapid()  # ensure key exists
        payload = json.dumps({"title": title[:120], "body": body[:300], "url": url if url.startswith("/") else "/"})
        for s in subs:
            try:
                webpush(
                    subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                    data=payload,
                    vapid_private_key=key,
                    vapid_claims={"sub": get_settings().vapid_contact},
                    ttl=24 * 3600,
                    timeout=10,
                )
                sent += 1
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):
                    db.delete(s)
                log.warning("web push failed (%s)", status)
            except Exception:  # network errors etc. never break the caller
                log.warning("web push failed", exc_info=True)
        db.commit()
    finally:
        db.close()
    return sent


def send_in_background(user_id: int, title: str, body: str, url: str = "/") -> None:
    threading.Thread(target=send, args=(user_id, title, body, url), daemon=True).start()
