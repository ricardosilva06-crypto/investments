"""AI analyst: local models (Ollama), private documents, grounded chat."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, session_factory, utcnow
from ..deps import get_current_user
from ..models import AISettings, ChatMessage, Conversation, Document, Note, Security, User
from ..schemas import ORM
from ..services import analyst, llm
from ..services import documents as docsvc

router = APIRouter(prefix="/api", tags=["ai"])

# Protect the host machine: at most 2 generations at once (local inference is heavy).
_generation_slots = threading.BoundedSemaphore(2)


def _ai_settings(db: Session, user: User) -> AISettings:
    s = db.get(AISettings, user.id)
    if s is None:
        s = AISettings(user_id=user.id)
        db.add(s)
        db.commit()
    return s


# ------------------------------------------------------------------ status & settings
class ModelOut(BaseModel):
    name: str
    size_bytes: int | None
    family: str
    parameter_size: str
    quantization: str
    embedding: bool


class AIStatusOut(BaseModel):
    available: bool
    message: str
    url: str
    models: list[ModelOut]
    chat_model: str | None
    embed_model: str | None
    chosen_chat_model: str
    chosen_embed_model: str
    temperature: Decimal
    num_ctx: int
    tasks: dict[str, str]


@router.get("/ai/status", response_model=AIStatusOut)
def ai_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    st = _ai_settings(db, user)
    cfg = get_settings()
    base = dict(
        url=cfg.ollama_url,
        chosen_chat_model=st.chat_model,
        chosen_embed_model=st.embed_model,
        temperature=st.temperature,
        num_ctx=cfg.ollama_num_ctx,
        tasks={k: v["label"] for k, v in analyst.TASKS.items()},
    )
    try:
        chat, embed, models = llm.resolve_models(st.chat_model, st.embed_model)
    except llm.LLMUnavailable as exc:
        return AIStatusOut(available=False, message=str(exc), models=[], chat_model=None, embed_model=None, **base)
    msg = "" if chat else "Ollama is running but no chat model is installed. Run e.g.: ollama pull llama3.1:8b"
    return AIStatusOut(available=bool(chat), message=msg, models=[ModelOut(**m.__dict__) for m in models],
                       chat_model=chat, embed_model=embed, **base)


class AISettingsIn(BaseModel):
    chat_model: str = Field("", max_length=128)
    embed_model: str = Field("", max_length=128)
    temperature: Decimal = Field(Decimal("0.2"), ge=0, le=1)


@router.put("/ai/settings", response_model=AIStatusOut)
def put_ai_settings(data: AISettingsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    st = _ai_settings(db, user)
    st.chat_model, st.embed_model, st.temperature = data.chat_model.strip(), data.embed_model.strip(), data.temperature
    db.commit()
    return ai_status(db, user)


# ------------------------------------------------------------------ documents
class DocumentOut(ORM):
    id: int
    title: str
    filename: str
    size_bytes: int
    pages: int
    chars: int
    ocr_pages: int = 0
    ocr_language: str = ""
    status: str
    message: str
    embed_model: str
    created_at: datetime
    ticker: str | None = None


def _doc_out(d: Document) -> DocumentOut:
    out = DocumentOut.model_validate(d)
    out.ticker = d.security.ticker if d.security else None
    return out


def owned_doc(db: Session, user: User, doc_id: int) -> Document:
    d = db.scalar(select(Document).where(Document.id == doc_id, Document.user_id == user.id))
    if d is None:
        raise HTTPException(404, "Document not found")
    return d


def _embed_model_for(db: Session, user: User) -> str | None:
    try:
        _, embed, _ = llm.resolve_models(_ai_settings(db, user).chat_model, _ai_settings(db, user).embed_model)
        return embed
    except llm.LLMUnavailable:
        return None


@router.get("/documents/ocr-status")
def ocr_status(_: User = Depends(get_current_user)):
    from ..services import ocr

    st = ocr.status()
    return {"available": st.available, "reason": st.reason, "languages": st.languages, "default": st.default_language,
            "max_pages": get_settings().ocr_max_pages}


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [_doc_out(d) for d in db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc()))]


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form("", max_length=255),
    ticker: str = Form("", max_length=20),
    ocr_language: str = Form("", max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    sec_id = None
    if ticker.strip():
        sec = db.scalar(select(Security).where(Security.ticker == ticker.strip().upper()))
        if sec is None:
            raise HTTPException(404, "Unknown ticker")
        sec_id = sec.id
    try:
        doc = docsvc.store_upload(db, user.id, file.filename or "document.pdf", data, title.strip(), sec_id,
                                  ocr_language=ocr_language.strip() or None)
    except docsvc.DocumentError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    todo = getattr(doc, "_ocr_pages_todo", [])
    if todo:
        background.add_task(docsvc.ocr_document, doc.id, todo, _embed_model_for(db, user))
    else:
        background.add_task(docsvc.index_document, doc.id, _embed_model_for(db, user))
    db.refresh(doc)
    return _doc_out(doc)


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _doc_out(owned_doc(db, user, doc_id))


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = owned_doc(db, user, doc_id)
    path = docsvc.file_path(d)
    if not path.exists():
        raise HTTPException(404, "File missing on server")
    return FileResponse(path, media_type="application/pdf", filename=d.filename, content_disposition_type="inline")


@router.post("/documents/{doc_id}/reindex", response_model=DocumentOut)
def reindex_document(doc_id: int, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = owned_doc(db, user, doc_id)
    background.add_task(docsvc.index_document, d.id, _embed_model_for(db, user))
    return _doc_out(d)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docsvc.delete_document(db, owned_doc(db, user, doc_id))


# ------------------------------------------------------------------ conversations
class MessageOut(ORM):
    id: int
    role: str
    content: str
    task: str
    tickers: list[str]
    document_ids: list[int]
    model: str
    sources: list[dict]
    verification: dict
    status: str
    created_at: datetime


def _msg_out(m: ChatMessage) -> MessageOut:
    return MessageOut(
        id=m.id, role=m.role, content=m.content, task=m.task,
        tickers=[t for t in m.tickers.split(",") if t],
        document_ids=[int(x) for x in m.document_ids.split(",") if x],
        model=m.model, sources=json.loads(m.sources or "[]"), verification=json.loads(m.verification or "{}"),
        status=m.status, created_at=m.created_at,
    )


class ConversationOut(ORM):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


def owned_conv(db: Session, user: User, cid: int) -> Conversation:
    c = db.scalar(select(Conversation).where(Conversation.id == cid, Conversation.user_id == user.id))
    if c is None:
        raise HTTPException(404, "Conversation not found")
    return c


@router.get("/ai/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()).limit(100)).all()


@router.get("/ai/conversations/{cid}", response_model=ConversationDetail)
def get_conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = owned_conv(db, user, cid)
    return ConversationDetail(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at,
                              messages=[_msg_out(m) for m in c.messages])


@router.delete("/ai/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(owned_conv(db, user, cid))
    db.commit()


class SaveNoteIn(BaseModel):
    title: str = Field("", max_length=160)


@router.post("/ai/messages/{mid}/save-note", status_code=201)
def save_as_note(mid: int, data: SaveNoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.scalar(
        select(ChatMessage).join(Conversation).where(ChatMessage.id == mid, Conversation.user_id == user.id, ChatMessage.role == "assistant")
    )
    if m is None:
        raise HTTPException(404, "Message not found")
    tickers = [t for t in m.tickers.split(",") if t]
    sec = db.scalar(select(Security).where(Security.ticker == tickers[0])) if tickers else None
    sources = json.loads(m.sources or "[]")
    ver = json.loads(m.verification or "{}")
    footer = [
        "",
        "---",
        f"_AI-generated by local model {m.model} on {m.created_at:%Y-%m-%d}. Verify before relying on it. Not investment advice._",
    ]
    if ver.get("unmatched_verified"):
        footer.append(f"_Numbers not found in sources: {', '.join(ver['unmatched_verified'])}_")
    if sources:
        footer.append("")
        footer.append("Sources:")
        footer += [f"- [{s['id']}] {s['label']}" for s in sources]
    label = analyst.TASKS.get(m.task, {}).get("label", "AI analysis")
    title = data.title.strip() or f"{', '.join(tickers) + ' · ' if tickers else ''}{label}"
    note = Note(user_id=user.id, security_id=sec.id if sec else None, title=title[:160], body=m.content + "\n".join(footer))
    db.add(note)
    db.commit()
    return {"note_id": note.id}


# ------------------------------------------------------------------ chat (SSE)
class ChatIn(BaseModel):
    conversation_id: int | None = None
    message: str = Field("", max_length=4000)
    task: str = Field("ask", max_length=32)
    tickers: list[str] = Field(default_factory=list, max_length=3)
    document_ids: list[int] = Field(default_factory=list, max_length=10)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/ai/chat")
def chat(data: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if data.task not in analyst.TASKS:
        raise HTTPException(422, "Unknown task")
    if not data.message.strip() and data.task == "ask":
        raise HTTPException(422, "Type a question or choose a task")
    st = _ai_settings(db, user)
    try:
        chat_model, embed_model, _ = llm.resolve_models(st.chat_model, st.embed_model)
    except llm.LLMUnavailable as exc:
        raise HTTPException(503, str(exc))
    if not chat_model:
        raise HTTPException(503, "No chat model installed in Ollama. Run e.g.: ollama pull llama3.1:8b")

    conv = owned_conv(db, user, data.conversation_id) if data.conversation_id else None
    tickers = [t.strip().upper() for t in data.tickers if t.strip()]
    doc_ids = list(dict.fromkeys(data.document_ids))
    # Follow-up questions inherit the companies/documents of the previous turn.
    if conv and not tickers and not doc_ids:
        last = next((m for m in reversed(conv.messages) if m.role == "user"), None)
        if last:
            tickers = [t for t in last.tickers.split(",") if t]
            doc_ids = [int(x) for x in last.document_ids.split(",") if x]
    secs = []
    for t in tickers:
        s = db.scalar(select(Security).where(Security.ticker == t))
        if s is None:
            raise HTTPException(404, f"Unknown ticker {t}")
        secs.append(s)
    docs = [owned_doc(db, user, i) for i in doc_ids]
    needs = analyst.TASKS[data.task]["needs"]
    if "ticker" in needs and not secs:
        raise HTTPException(422, "Choose a company for this task")
    if "two_tickers" in needs and len(secs) < 2:
        raise HTTPException(422, "Choose at least two companies to compare")
    if "document" in needs and not docs:
        raise HTTPException(422, "Choose a document for this task")

    if not _generation_slots.acquire(blocking=False):
        raise HTTPException(429, "The local AI is busy with other requests. Try again in a moment.")

    try:
        if conv is None:
            label = analyst.TASKS[data.task]["label"]
            title = (data.message.strip()[:80] or f"{label}{' · ' + ', '.join(tickers) if tickers else ''}")
            conv = Conversation(user_id=user.id, title=title)
            db.add(conv)
            db.flush()
        history = []
        for m in conv.messages[-6:]:
            history.append({"role": m.role, "content": m.content[:3000]})
        user_msg = ChatMessage(conversation_id=conv.id, role="user", content=data.message.strip() or analyst.TASKS[data.task]["label"],
                               task=data.task, tickers=",".join(tickers), document_ids=",".join(map(str, doc_ids)))
        db.add(user_msg)
        conv.updated_at = utcnow()
        db.commit()
        ctx = analyst.build_context(db, user, data.task, secs, docs, data.message, embed_model)
        budget = max(4000, int(get_settings().ollama_num_ctx * 3.2) - 6000)  # ~4 chars/token, leave room for the answer
        ctx_text = ctx.text(budget)
        messages = analyst.build_messages(data.task, data.message, tickers, ctx_text, history)
        conv_id, temperature = conv.id, float(st.temperature)
        sources = [s.as_dict() for s in ctx.sources]
        values, warnings = ctx.values, ctx.warnings
    except Exception:
        _generation_slots.release()
        raise

    def stream():
        parts: list[str] = []
        status = "ok"
        try:
            yield _sse("meta", {"conversation_id": conv_id, "model": chat_model, "sources": sources, "warnings": warnings})
            for piece in llm.get_provider().chat_stream(chat_model, messages, temperature=temperature,
                                                          num_ctx=get_settings().ollama_num_ctx):
                parts.append(piece)
                yield _sse("token", {"t": piece})
        except llm.LLMUnavailable as exc:
            status = "error" if not parts else "partial"
            yield _sse("error", {"message": str(exc)})
        finally:
            _generation_slots.release()
            content = "".join(parts).strip()
            verification = analyst.verify_numbers(content, values) if content else {}
            sdb = session_factory()()
            try:
                m = ChatMessage(conversation_id=conv_id, role="assistant", content=content or "(no answer)", task=data.task,
                                tickers=",".join(tickers), document_ids=",".join(map(str, doc_ids)), model=chat_model,
                                sources=json.dumps(sources), verification=json.dumps(verification), status=status)
                sdb.add(m)
                c = sdb.get(Conversation, conv_id)
                if c:
                    c.updated_at = utcnow()
                sdb.commit()
                mid = m.id
            finally:
                sdb.close()
        yield _sse("done", {"message_id": mid, "verification": verification, "status": status})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
