"""Administrator functions: invites, members, data sync, backups."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import require_admin
from ..models import AuthSession, Invite, User
from ..notify import notify
from ..schemas import ORM, UserOut
from ..security import new_invite_code, sha256
from ..services import backup, sec

router = APIRouter(prefix="/api/admin", tags=["admin"])


class InviteIn(BaseModel):
    label: str = Field("", max_length=80)
    role: str = Field("member", pattern="^(member|admin)$")
    expires_in_days: int = Field(7, ge=1, le=30)


class InviteOut(ORM):
    id: int
    code_hint: str
    label: str
    role: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    revoked: bool


class InviteCreated(InviteOut):
    code: str  # shown exactly once


@router.get("/invites", response_model=list[InviteOut])
def list_invites(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(Invite).order_by(Invite.created_at.desc())).all()


@router.post("/invites", response_model=InviteCreated, status_code=201)
def create_invite(data: InviteIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    code = new_invite_code()
    inv = Invite(
        code_hash=sha256(code),
        code_hint=code[:4],
        label=data.label.strip(),
        role=data.role,
        created_by_id=admin.id,
        expires_at=utcnow() + timedelta(days=data.expires_in_days),
    )
    db.add(inv)
    db.commit()
    return InviteCreated(**InviteOut.model_validate(inv).model_dump(), code=code)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    inv = db.get(Invite, invite_id)
    if inv is None:
        raise HTTPException(404, "Invite not found")
    inv.revoked = True
    db.commit()


class MemberOut(UserOut):
    is_active: bool


@router.get("/users", response_model=list[MemberOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(User).order_by(User.created_at)).all()


class UserActiveIn(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}", response_model=MemberOut)
def set_user_active(
    user_id: int, data: UserActiveIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(400, "You cannot deactivate your own account")
    u.is_active = data.is_active
    if not data.is_active:
        db.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
    db.commit()
    return u


@router.post("/sync/sec")
def sync_sec(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        row = sec.sync_securities(db)
    except sec.SyncError as exc:
        raise HTTPException(400, str(exc))
    notify(db, admin.id, "sync", "SEC company list updated", f"{row.record_count:,} securities loaded from SEC EDGAR.", "/markets")
    db.commit()
    return {"record_count": row.record_count, "last_success_at": row.last_success_at}


class BackupOut(BaseModel):
    name: str
    size_bytes: int
    created_at: datetime


@router.get("/backups", response_model=list[BackupOut])
def list_backups(_: User = Depends(require_admin)):
    from datetime import UTC

    return [
        BackupOut(name=p.name, size_bytes=p.stat().st_size, created_at=datetime.fromtimestamp(p.stat().st_mtime, UTC))
        for p in backup.list_backups()
    ]


@router.post("/backups", response_model=BackupOut, status_code=201)
def make_backup(_: User = Depends(require_admin)):
    from datetime import UTC

    p = backup.create_backup()
    return BackupOut(name=p.name, size_bytes=p.stat().st_size, created_at=datetime.fromtimestamp(p.stat().st_mtime, UTC))


@router.get("/backups/{name}")
def download_backup(name: str, _: User = Depends(require_admin)):
    match = next((p for p in backup.list_backups() if p.name == name), None)
    if match is None:
        raise HTTPException(404, "Backup not found")
    media = "application/zip" if match.suffix == ".zip" else "application/vnd.sqlite3"
    return FileResponse(match, media_type=media, filename=match.name)
