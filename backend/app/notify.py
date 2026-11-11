from sqlalchemy.orm import Session

from .models import Notification


def notify(db: Session, user_id: int, kind: str, title: str, body: str = "", link: str = "", push: bool = False) -> None:
    """Record an in-app notification (caller commits). Optionally also send a Web Push."""
    db.add(Notification(user_id=user_id, kind=kind, title=title, body=body, link=link))
    if push:
        from .services import push as pushsvc

        pushsvc.send_in_background(user_id, title, body, link or "/")
