"""Private PDF documents: local text extraction, chunking and retrieval (RAG).

* Text extraction: PyMuPDF, entirely local. Scanned PDFs without a text layer
  are rejected with a clear message (no OCR service is used).
* Retrieval: SQLite FTS5 keyword search (BM25) always; plus semantic search with
  local Ollama embeddings when an embedding model is installed. Results are
  merged with reciprocal-rank fusion.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_factory
from ..models import Document, DocumentChunk
from . import llm

CHUNK_CHARS = 1400
CHUNK_OVERLAP = 200
EMBED_BATCH = 16


class DocumentError(ValueError):
    pass


# ------------------------------------------------------------------ fts
def ensure_fts(db: Session) -> None:
    db.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(body, tokenize='porter unicode61')"))


# ------------------------------------------------------------------ extract
def extract_pages(data: bytes, max_pages: int) -> list[str]:
    import pymupdf  # AGPL-3.0; imported lazily so the rest of the app never depends on it

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # pymupdf raises various types
        raise DocumentError("This file could not be opened as a PDF.") from exc
    try:
        if doc.needs_pass:
            raise DocumentError("Password-protected PDFs are not supported.")
        if doc.page_count > max_pages:
            raise DocumentError(f"PDF has {doc.page_count} pages; the limit is {max_pages}.")
        return [page.get_text("text") or "" for page in doc]
    finally:
        doc.close()


def _clean(t: str) -> str:
    t = t.replace("­", "")  # soft hyphen
    t = re.sub(r"-\n(?=[a-z])", "", t)  # de-hyphenate line breaks
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def chunk_pages(pages: list[str]) -> list[tuple[int, str]]:
    """Split page texts into overlapping chunks; each chunk keeps its starting page (1-based)."""
    chunks: list[tuple[int, str]] = []
    for pno, raw in enumerate(pages, start=1):
        t = _clean(raw)
        if not t:
            continue
        start = 0
        while start < len(t):
            end = min(len(t), start + CHUNK_CHARS)
            if end < len(t):
                cut = max(t.rfind("\n", start + CHUNK_CHARS // 2, end), t.rfind(". ", start + CHUNK_CHARS // 2, end))
                if cut > start:
                    end = cut + 1
            piece = t[start:end].strip()
            if len(piece) > 40:
                chunks.append((pno, piece))
            if end >= len(t):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _add_chunks(db: Session, doc_id: int, chunks: list[tuple[int, str]], start_seq: int, ocr: bool) -> int:
    ensure_fts(db)
    for seq, (page, body) in enumerate(chunks, start=start_seq):
        ch = DocumentChunk(document_id=doc_id, seq=seq, page=page, text=body, ocr=ocr)
        db.add(ch)
        db.flush()
        db.execute(text("INSERT INTO chunk_fts(rowid, body) VALUES (:id, :b)"), {"id": ch.id, "b": body})
    return start_seq + len(chunks)


def store_upload(db: Session, user_id: int, filename: str, data: bytes, title: str, security_id: int | None,
                 ocr_language: str | None = None) -> Document:
    """Store a PDF and index its text layer. Scanned pages are queued for OCR (see ``ocr_document``)."""
    from . import ocr

    s = get_settings()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise DocumentError(f"File is larger than {s.max_upload_mb} MB.")
    if not data.startswith(b"%PDF"):
        raise DocumentError("Only PDF files are supported.")
    pages = extract_pages(data, s.max_pdf_pages)
    scanned = ocr.pages_needing_ocr(data)
    # Text-layer pages are indexed now; scanned pages only through OCR.
    text_pages = [("" if i in set(scanned) else t) for i, t in enumerate(pages)]
    chunks = chunk_pages(text_pages)
    total_chars = sum(len(c) for _, c in chunks)
    st = ocr.status()
    if scanned and not st.available:
        if total_chars < 200:
            raise DocumentError(
                "No extractable text found: this looks like a scanned PDF. OCR is not available on the server "
                f"({st.reason}) Install the free Tesseract OCR engine to read scanned PDFs (see README)."
            )
        scanned = []  # index the text pages only; the document message explains what was skipped
    if scanned and len(scanned) > s.ocr_max_pages:
        raise DocumentError(f"{len(scanned)} scanned pages exceed the OCR limit of {s.ocr_max_pages} pages (II_OCR_MAX_PAGES).")
    lang = ""
    if scanned:
        try:
            lang = ocr.normalise_languages(ocr_language)
        except ValueError as exc:
            raise DocumentError(str(exc)) from exc
    if not scanned and total_chars < 200:
        raise DocumentError("No extractable text found in this PDF (no text layer and no scanned images).")
    folder = s.documents_dir / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.pdf"
    (folder / stored).write_bytes(data)
    doc = Document(
        user_id=user_id,
        security_id=security_id,
        title=title or Path(filename).stem[:255],
        filename=Path(filename).name[:255] or "document.pdf",
        stored_name=stored,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        pages=len(pages),
        chars=total_chars,
        status="ocr" if scanned else "extracted",
        message=f"Waiting to read {len(scanned)} scanned page(s) with OCR…" if scanned else "",
        ocr_language=lang,
    )
    if not scanned and ocr.pages_needing_ocr(data) and not st.available:
        doc.message = "Some pages look scanned and were skipped: OCR is not installed on the server."
    db.add(doc)
    db.flush()
    _add_chunks(db, doc.id, chunks, 0, ocr=False)
    db.commit()
    doc._ocr_pages_todo = scanned  # transient: picked up by the caller's background task
    return doc


def ocr_document(document_id: int, pages: list[int], embed_model: str | None) -> None:
    """Background: OCR scanned pages, add their text to the index, then build embeddings."""
    from . import ocr

    db = session_factory()()
    try:
        doc = db.get(Document, document_id)
        if doc is None or not pages:
            return

        def progress(done: int, total: int) -> None:
            doc.message = f"Reading scanned pages with OCR: {done}/{total}"
            db.commit()

        try:
            texts = ocr.ocr_pages(file_path(doc), pages, doc.ocr_language or get_settings().ocr_languages, progress)
        except Exception as exc:  # Tesseract missing at runtime, damaged page, ...
            doc.status, doc.message = "error", f"OCR failed: {exc}"[:500]
            db.commit()
            return
        page_texts = [""] * doc.pages
        for i, t in texts.items():
            page_texts[i] = t
        chunks = chunk_pages(page_texts)
        next_seq = (db.scalar(select(func.max(DocumentChunk.seq)).where(DocumentChunk.document_id == doc.id)) or -1) + 1
        _add_chunks(db, doc.id, chunks, next_seq, ocr=True)
        doc.ocr_pages = sum(1 for t in texts.values() if t.strip())
        doc.chars += sum(len(c) for _, c in chunks)
        if doc.chars < 200:
            doc.status, doc.message = "error", "OCR found no readable text. Check the scan quality or the OCR language."
            db.commit()
            return
        doc.status, doc.message = "extracted", ""
        db.commit()
    finally:
        db.close()
    index_document(document_id, embed_model)


def file_path(doc: Document) -> Path:
    return get_settings().documents_dir / str(doc.user_id) / doc.stored_name


def delete_document(db: Session, doc: Document) -> None:
    ensure_fts(db)
    ids = list(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == doc.id)))
    for i in range(0, len(ids), 500):
        part = ids[i : i + 500]
        db.execute(text(f"DELETE FROM chunk_fts WHERE rowid IN ({','.join(str(int(x)) for x in part)})"))
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    path = file_path(doc)
    db.delete(doc)
    db.commit()
    path.unlink(missing_ok=True)


# ------------------------------------------------------------------ embeddings
def _normalise(vecs: list[list[float]]) -> np.ndarray:
    arr = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return arr / norms


def index_document(document_id: int, embed_model: str | None) -> None:
    """Compute embeddings in the background. Without a model the document stays keyword-searchable."""
    db = session_factory()()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        if not embed_model:
            doc.status = "keyword_only"
            doc.message = "No embedding model installed; using keyword search. Install one with: ollama pull nomic-embed-text"
            db.commit()
            return
        doc.status, doc.message = "indexing", ""
        db.commit()
        chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.seq)))
        provider = llm.get_provider()
        try:
            for i in range(0, len(chunks), EMBED_BATCH):
                batch = chunks[i : i + EMBED_BATCH]
                vecs = _normalise(provider.embed(embed_model, [c.text for c in batch]))
                for c, v in zip(batch, vecs):
                    c.embedding = v.tobytes()
                db.commit()
        except llm.LLMUnavailable as exc:
            db.rollback()
            doc = db.get(Document, document_id)
            doc.status, doc.message = "keyword_only", f"Semantic index not built: {exc}"
            db.commit()
            return
        doc.status, doc.embed_model, doc.message = "ready", embed_model, ""
        db.commit()
    finally:
        db.close()


# ------------------------------------------------------------------ search
@dataclass
class Hit:
    chunk_id: int
    document_id: int
    title: str
    page: int
    text: str
    score: float
    ocr: bool = False


def _fts_query(q: str) -> str:
    terms = [t for t in re.findall(r"[A-Za-z0-9]{2,}", q.lower()) if t not in STOPWORDS][:24]
    return " OR ".join(f'"{t}"' for t in terms)


STOPWORDS = set(
    "the a an and or of to in on for with by is are was were be been this that these those what which who how why "
    "when where does do did it its as at from about into than then there their they them can could should would "
    "will shall may might me my our your you we i".split()
)


def search(db: Session, docs: list[Document], query: str, k: int = 8, embed_model: str | None = None) -> list[Hit]:
    if not docs:
        return []
    ensure_fts(db)
    ids = [d.id for d in docs]
    titles = {d.id: d.title for d in docs}
    ranked: dict[int, float] = {}
    rows: dict[int, DocumentChunk] = {}

    fq = _fts_query(query)
    if fq:
        id_list = ",".join(str(int(i)) for i in ids)
        res = db.execute(
            text(
                "SELECT c.id FROM chunk_fts f JOIN document_chunks c ON c.id = f.rowid "
                f"WHERE chunk_fts MATCH :q AND c.document_id IN ({id_list}) ORDER BY bm25(chunk_fts) LIMIT 40"
            ),
            {"q": fq},
        ).all()
        for rank, (cid,) in enumerate(res):
            ranked[cid] = ranked.get(cid, 0) + 1 / (60 + rank)

    sem_docs = [d for d in docs if d.status == "ready" and d.embed_model and d.embed_model == embed_model]
    if sem_docs and embed_model:
        try:
            qv = _normalise(llm.get_provider().embed(embed_model, [query]))[0]
            chunks = list(
                db.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id.in_([d.id for d in sem_docs]), DocumentChunk.embedding.is_not(None)
                    )
                )
            )
            if chunks:
                mat = np.frombuffer(b"".join(c.embedding for c in chunks), dtype=np.float32).reshape(len(chunks), -1)
                if mat.shape[1] == qv.shape[0]:
                    sims = mat @ qv
                    order = np.argsort(-sims)[:40]
                    for rank, idx in enumerate(order):
                        c = chunks[int(idx)]
                        rows[c.id] = c
                        ranked[c.id] = ranked.get(c.id, 0) + 1 / (60 + rank)
        except llm.LLMUnavailable:
            pass  # keyword results still apply

    if not ranked:
        # No keyword or vector match: fall back to the start of each document (summary-type questions).
        first = db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id.in_(ids), DocumentChunk.seq < 3).order_by(DocumentChunk.seq)
        ).all()
        return [Hit(c.id, c.document_id, titles[c.document_id], c.page, c.text, 0.0, c.ocr) for c in first][:k]

    top = sorted(ranked.items(), key=lambda kv: kv[1], reverse=True)[:k]
    missing = [cid for cid, _ in top if cid not in rows]
    if missing:
        for c in db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(missing))):
            rows[c.id] = c
    return [Hit(cid, rows[cid].document_id, titles[rows[cid].document_id], rows[cid].page, rows[cid].text, score, rows[cid].ocr)
            for cid, score in top]
