"""Private investment notes and theses."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import get_current_user
from ..models import Note, Security, User
from sqlalchemy.orm import selectinload
from ..schemas import ORM, SecurityOut

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteOut(ORM):
    id: int
    title: str
    body: str
    created_at: datetime
    updated_at: datetime
    security: SecurityOut | None
    is_shared: bool = False
    is_mine: bool = True
    author: str | None = None


def _out(n: Note, user: User, authors: dict[int, str] | None = None) -> NoteOut:
    o = NoteOut.model_validate(n)
    o.is_mine = n.user_id == user.id
    o.author = None if o.is_mine else (authors or {}).get(n.user_id)
    return o


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field("", max_length=50_000)
    ticker: str | None = Field(None, max_length=20)
    is_shared: bool | None = None  # None = leave unchanged


def owned_note(db: Session, user: User, note_id: int) -> Note:
    note = db.scalar(select(Note).where(Note.id == note_id, Note.user_id == user.id))
    if note is None:
        raise HTTPException(404, "Note not found")
    return note


def resolve_security(db: Session, ticker: str | None) -> int | None:
    if not ticker:
        return None
    sec = db.scalar(select(Security).where(Security.ticker == ticker.strip().upper()))
    if sec is None:
        raise HTTPException(404, "Unknown ticker")
    return sec.id


def _authors(db: Session, ids: set[int]) -> dict[int, str]:
    return {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


@router.get("", response_model=list[NoteOut])
def list_notes(
    ticker: str | None = Query(None, max_length=20),
    scope: str = Query("mine", pattern="^(mine|shared)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """scope=mine: your notes. scope=shared: notes other members chose to share (read-only)."""
    if scope == "shared":
        stmt = select(Note).join(User, User.id == Note.user_id).where(
            Note.is_shared.is_(True), Note.user_id != user.id, User.is_active.is_(True)
        )
    else:
        stmt = select(Note).where(Note.user_id == user.id)
    if ticker:
        stmt = stmt.join(Security).where(Security.ticker == ticker.upper())
    notes = db.scalars(stmt.options(selectinload(Note.security)).order_by(Note.updated_at.desc())).all()
    authors = _authors(db, {n.user_id for n in notes if n.user_id != user.id})
    return [_out(n, user, authors) for n in notes]


@router.get("/{note_id}", response_model=NoteOut)
def get_note(note_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note = db.scalar(select(Note).where(Note.id == note_id, (Note.user_id == user.id) | (Note.is_shared.is_(True))))
    if note is None:
        raise HTTPException(404, "Note not found")
    return _out(note, user, _authors(db, {note.user_id}))


@router.post("", response_model=NoteOut, status_code=201)
def create_note(data: NoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note = Note(user_id=user.id, title=data.title.strip(), body=data.body, security_id=resolve_security(db, data.ticker),
                is_shared=bool(data.is_shared))
    db.add(note)
    db.commit()
    db.refresh(note)
    return _out(note, user)


@router.put("/{note_id}", response_model=NoteOut)
def update_note(note_id: int, data: NoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note = owned_note(db, user, note_id)
    note.title, note.body = data.title.strip(), data.body
    note.security_id = resolve_security(db, data.ticker)
    if data.is_shared is not None:
        note.is_shared = data.is_shared
    note.updated_at = utcnow()
    db.commit()
    db.refresh(note)
    return _out(note, user)


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(owned_note(db, user, note_id))
    db.commit()
