"""Local OCR for scanned PDF pages (Tesseract, open source, Apache-2.0).

Tesseract runs on the server through PyMuPDF; nothing leaves the machine and no
paid service is involved. It is optional: when Tesseract is not installed,
scanned PDFs are refused with instructions instead of being guessed at.

Install (free):
  Debian/Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-por   (add tesseract-ocr-<lang> per language)
  macOS:         brew install tesseract tesseract-lang
  Windows:       the UB Mannheim installer (github.com/UB-Mannheim/tesseract/wiki)
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings

# A page with less than this much text but at least one image is treated as scanned.
MIN_TEXT_CHARS = 40


@dataclass
class OcrStatus:
    available: bool
    reason: str
    tessdata: str | None
    languages: list[str]
    default_language: str


def _tessdata() -> str | None:
    env = os.environ.get("TESSDATA_PREFIX")
    if env and Path(env).is_dir():
        return env
    try:
        import pymupdf

        found = pymupdf.get_tessdata()
        return str(found) if found else None
    except Exception:  # PyMuPDF raises if it cannot locate Tesseract
        return None


def status() -> OcrStatus:
    s = get_settings()
    default = s.ocr_languages
    if s.ocr == "off":
        return OcrStatus(False, "OCR is turned off (II_OCR=off).", None, [], default)
    td = _tessdata()
    if not td or not shutil.which("tesseract") and not Path(td).is_dir():
        return OcrStatus(False, "Tesseract is not installed on the server.", None, [], default)
    langs = sorted(p.stem for p in Path(td).glob("*.traineddata") if p.stem not in ("osd", "equ"))
    if not langs:
        return OcrStatus(False, f"No Tesseract language data found in {td}.", td, [], default)
    return OcrStatus(True, "", td, langs, default)


def normalise_languages(requested: str | None) -> str:
    """Validate a 'eng+por' style string against the installed language packs."""
    st = status()
    want = (requested or st.default_language or "eng").strip()
    parts = [p for p in want.replace(",", "+").split("+") if p]
    missing = [p for p in parts if p not in st.languages]
    if missing:
        raise ValueError(f"OCR language(s) not installed: {', '.join(missing)}. Installed: {', '.join(st.languages) or 'none'}.")
    return "+".join(parts)


def pages_needing_ocr(data: bytes) -> list[int]:
    """0-based page numbers that have (almost) no text layer but contain an image."""
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        out = []
        for i in range(doc.page_count):
            page = doc[i]
            if len((page.get_text("text") or "").strip()) < MIN_TEXT_CHARS and page.get_images(full=False):
                out.append(i)
        return out
    finally:
        doc.close()


def ocr_pages(path: Path, pages: list[int], language: str, progress=None) -> dict[int, str]:
    """OCR the given pages. Returns {page_index: text}. ``progress(done, total)`` is called after each page."""
    import pymupdf

    st = status()
    if not st.available:
        raise RuntimeError(st.reason)
    dpi = get_settings().ocr_dpi
    doc = pymupdf.open(path)
    out: dict[int, str] = {}
    try:
        for n, i in enumerate(pages, start=1):
            page = doc[i]  # keep a reference: the OCR text page refers back to it
            tp = page.get_textpage_ocr(language=language, dpi=dpi, full=True, tessdata=st.tessdata)
            out[i] = page.get_text("text", textpage=tp) or ""
            if progress:
                progress(n, len(pages))
    finally:
        doc.close()
    return out
