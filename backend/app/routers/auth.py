"""Local, invite-only authentication with server-side sessions."""

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import SESSION_COOKIE, get_current_session, get_current_user
from ..models import AuthSession, Invite, User, UserPreference, Watchlist
from ..notify import notify
from ..schemas import UserOut
from ..security import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    login_failures,
    needs_rehash,
    new_token,
    normalise_invite_code,
    register_attempts,
    sha256,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,40}$")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(value) > 256:
        raise ValueError("Password is too long")
    return value


class LoginIn(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=256)


class RegisterIn(BaseModel):
    invite_code: str = Field(max_length=40)
    username: str
    display_name: str = Field(min_length=1, max_length=80)
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("Username: 3–40 characters, letters, digits, '.', '_' or '-'")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _validate_password(v)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _validate_password(v)


class SessionOut(BaseModel):
    id: int
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    current: bool


def start_session(db: Session, response: Response, user: User, request: Request) -> None:
    settings = get_settings()
    token = new_token()
    now = utcnow()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=sha256(token),
            user_agent=(request.headers.get("user-agent") or "")[:255],
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=settings.session_days),
        )
    )
    # Housekeeping: drop this user's expired sessions.
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at <= now))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=UserOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    username = data.username.strip().lower()
    if login_failures.is_limited(f"ip:{ip}") or login_failures.is_limited(f"user:{username}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(User.username == username))
    ok = verify_password(user.password_hash if user else None, data.password)
    if not ok or user is None or not user.is_active:
        login_failures.hit(f"ip:{ip}")
        login_failures.hit(f"user:{username}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    login_failures.reset(f"user:{username}")
    start_session(db, response, user, request)
    return user


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if register_attempts.is_limited(f"ip:{ip}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again later.")
    register_attempts.hit(f"ip:{ip}")

    code_hash = sha256(normalise_invite_code(data.invite_code))
    invite = db.scalar(select(Invite).where(Invite.code_hash == code_hash))
    now = utcnow()
    if invite is None or invite.revoked or invite.used_at is not None or invite.expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invite code is invalid, used or expired")
    if db.scalar(select(func.count()).where(User.username == data.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken")

    user = User(
        username=data.username,
        display_name=data.display_name.strip(),
        password_hash=hash_password(data.password),
        role=invite.role,
        invited_by_id=invite.created_by_id,
    )
    db.add(user)
    db.flush()
    invite.used_by_id = user.id
    invite.used_at = now
    db.add(UserPreference(user_id=user.id))
    db.add(Watchlist(user_id=user.id, name="My watchlist"))
    if invite.created_by_id:
        notify(
            db,
            invite.created_by_id,
            "invite_used",
            f"{user.display_name} joined",
            f"Invite {invite.label or invite.code_hint + '…'} was used by @{user.username}.",
            "/admin",
        )
    db.commit()
    start_session(db, response, user, request)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response, session: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.id == session.id))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password", status_code=204)
def change_password(
    data: PasswordChangeIn,
    session: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user = session.user
    if not verify_password(user.password_hash, data.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    # Sign out every other device.
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.id != session.id))
    db.commit()


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(session: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == session.user_id, AuthSession.expires_at > utcnow())
        .order_by(AuthSession.last_seen_at.desc())
    ).all()
    return [
        SessionOut(
            id=s.id,
            user_agent=s.user_agent,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            current=s.id == session.id,
        )
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: int, session: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)):
    result = db.execute(
        delete(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == session.user_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    db.commit()
