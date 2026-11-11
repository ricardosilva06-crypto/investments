"""Private investment notes and theses."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import get_current_user
from ..models import Note, Security, User
from ..schemas import ORM, SecurityOut

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteOut(ORM):
    id: int
    title: str
    body: str
    created_at: datetime
    updated_at: datetime
    security: SecurityOut | None


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field("", max_length=50_000)
    ticker: str | None = Field(None, max_length=20)


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


@router.get("", response_model=list[NoteOut])
def list_notes(
    ticker: str | None = Query(None, max_length=20),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Note).where(Note.user_id == user.id)
    if ticker:
        stmt = stmt.join(Security).where(Security.ticker == ticker.upper())
    return db.scalars(stmt.order_by(Note.updated_at.desc())).all()


@router.get("/{note_id}", response_model=NoteOut)
def get_note(note_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return owned_note(db, user, note_id)


@router.post("", response_model=NoteOut, status_code=201)
def create_note(data: NoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note = Note(user_id=user.id, title=data.title.strip(), body=data.body, security_id=resolve_security(db, data.ticker))
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.put("/{note_id}", response_model=NoteOut)
def update_note(note_id: int, data: NoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note = owned_note(db, user, note_id)
    note.title, note.body = data.title.strip(), data.body
    note.security_id = resolve_security(db, data.ticker)
    note.updated_at = utcnow()
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(owned_note(db, user, note_id))
    db.commit()
