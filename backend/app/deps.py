"""FastAPI dependencies: database session and authenticated user."""

from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db, utcnow
from .models import AuthSession, User
from .security import sha256

SESSION_COOKIE = "ii_session"


def get_current_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256(token)))
    now = utcnow()
    if session is None or session.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    if not session.user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    # Avoid a write on every request: refresh last_seen at most every 5 minutes.
    if now - session.last_seen_at > timedelta(minutes=5):
        session.last_seen_at = now
        db.commit()
    return session


def get_current_user(session: AuthSession = Depends(get_current_session)) -> User:
    return session.user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator only")
    return user
