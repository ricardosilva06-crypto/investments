"""OCR of scanned PDFs with the real Tesseract engine (skipped where it is not installed)."""

import shutil

import pymupdf
import pytest

from app import db
from app.models import Document, DocumentChunk
from app.services import ocr

from .conftest import HDR

needs_tesseract = pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")


def scanned_page(doc: pymupdf.Document, text: str) -> None:
    """Add a page that only contains a picture of `text` (like a scanner would produce)."""
    src = pymupdf.open()
    p = src.new_page()
    p.insert_textbox(pymupdf.Rect(50, 50, 550, 700), text, fontsize=14)
    pix = p.get_pixmap(dpi=200)
    page = doc.new_page(width=p.rect.width, height=p.rect.height)
    page.insert_image(page.rect, pixmap=pix)


def text_page(doc: pymupdf.Document, text: str) -> None:
    p = doc.new_page()
    p.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)


SCAN_TEXT = ("Annual report 2024\nRevenue grew to EUR 1,234.5 million.\nNet profit was 150 million.\n"
             "The board proposes a dividend of 0.85 per share.\n" * 3)


@needs_tesseract
def test_ocr_status_lists_installed_languages():
    st = ocr.status()
    assert st.available and "eng" in st.languages
    assert ocr.normalise_languages("eng") == "eng"
    with pytest.raises(ValueError):
        ocr.normalise_languages("xxx")


@needs_tesseract
def test_scanned_pdf_is_ocrd_and_searchable(admin_client):
    d = pymupdf.open()
    scanned_page(d, SCAN_TEXT)
    pdf = d.tobytes()
    assert ocr.pages_needing_ocr(pdf) == [0]
    st = admin_client.get("/api/documents/ocr-status").json()
    assert st["available"] and "eng" in st["languages"]
    r = admin_client.post("/api/documents", files={"file": ("scan.pdf", pdf, "application/pdf")}, data={"ocr_language": "eng"}, headers=HDR)
    assert r.status_code == 201, r.text
    doc = admin_client.get(f"/api/documents/{r.json()['id']}").json()  # background OCR ran after the response
    assert doc["ocr_pages"] == 1 and doc["ocr_language"] == "eng"
    assert doc["status"] == "keyword_only"  # no embedding model in tests -> keyword search
    s = db.session_factory()()
    chunks = s.query(DocumentChunk).filter_by(document_id=doc["id"]).all()
    assert chunks and all(c.ocr for c in chunks)
    joined = " ".join(c.text for c in chunks)
    assert "1,234.5" in joined and "dividend" in joined
    from app.services import documents as docsvc

    hits = docsvc.search(s, [s.get(Document, doc["id"])], "dividend per share", k=2)
    assert hits and hits[0].ocr is True and hits[0].page == 1
    s.close()


@needs_tesseract
def test_mixed_pdf_only_ocrs_scanned_pages(admin_client):
    d = pymupdf.open()
    text_page(d, "Management report. Our strategy focuses on recurring revenue. " * 20)
    scanned_page(d, SCAN_TEXT)
    pdf = d.tobytes()
    assert ocr.pages_needing_ocr(pdf) == [1]
    r = admin_client.post("/api/documents", files={"file": ("mixed.pdf", pdf, "application/pdf")}, headers=HDR)
    doc = admin_client.get(f"/api/documents/{r.json()['id']}").json()
    assert doc["ocr_pages"] == 1 and doc["pages"] == 2
    s = db.session_factory()()
    chunks = s.query(DocumentChunk).filter_by(document_id=doc["id"]).order_by(DocumentChunk.seq).all()
    assert {c.page for c in chunks if not c.ocr} == {1} and {c.page for c in chunks if c.ocr} == {2}
    s.close()


def test_scanned_pdf_refused_with_instructions_when_ocr_off(admin_client, monkeypatch):
    from app import config

    monkeypatch.setenv("II_OCR", "off")
    config.get_settings.cache_clear()
    d = pymupdf.open()
    scanned_page(d, SCAN_TEXT)
    r = admin_client.post("/api/documents", files={"file": ("scan.pdf", d.tobytes(), "application/pdf")}, headers=HDR)
    assert r.status_code == 422
    assert "scanned PDF" in r.json()["detail"] and "Tesseract" in r.json()["detail"]
    assert admin_client.get("/api/documents/ocr-status").json()["available"] is False


@needs_tesseract
def test_unknown_ocr_language_is_rejected(admin_client):
    d = pymupdf.open()
    scanned_page(d, SCAN_TEXT)
    r = admin_client.post("/api/documents", files={"file": ("scan.pdf", d.tobytes(), "application/pdf")}, data={"ocr_language": "klingon"}, headers=HDR)
    assert r.status_code == 422 and "not installed" in r.json()["detail"]


@needs_tesseract
def test_ai_source_is_labelled_ocr(admin_client):
    from app.models import User
    from app.services import analyst

    d = pymupdf.open()
    scanned_page(d, SCAN_TEXT)
    r = admin_client.post("/api/documents", files={"file": ("scan.pdf", d.tobytes(), "application/pdf")}, headers=HDR)
    s = db.session_factory()()
    doc = s.get(Document, r.json()["id"])
    ctx = analyst.build_context(s, s.query(User).first(), "document", [], [doc], "dividend", None)
    assert any(src.label.endswith("(OCR)") for src in ctx.sources)
    assert "recognised by OCR" in ctx.text(50_000)
    s.close()
