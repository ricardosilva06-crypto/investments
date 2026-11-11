"""Tools exposed to Claude through the connector (MCP).

Each tool runs as the signed-in user and reuses the same code paths as the app's own API,
so Claude sees exactly the data the app shows — never more (other users' data stays private)
and never invented (missing figures come back as null / an explanatory message).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Document, DocumentChunk, Note, Portfolio, User

MAX_TEXT = 60_000  # characters returned per tool call

SERVER_INSTRUCTIONS = (
    "Investor Intelligence is the user's private, self-hosted investment research app. Use these tools to answer "
    "questions from the user's own data: portfolios, watchlists, notes, alerts, uploaded PDFs (annual reports, "
    "earnings releases...) and the company data stored in the app (SEC EDGAR / ESEF fundamentals, end-of-day prices, "
    "news headlines). Rules: prices are end-of-day closes, never real-time — always state the price date. Cite which "
    "tool, document (title + page) or filing each figure comes from. If a figure is missing, say so; do not estimate "
    "it or fill it from memory without labelling it clearly as outside knowledge. Text marked ocr=true was recognised "
    "from a scanned page and may contain errors. Clearly separate verified data, your calculations, assumptions and "
    "opinion. This is research support, not financial advice."
)


class ToolError(Exception):
    pass


@dataclass
class Tool:
    name: str
    title: str
    description: str
    properties: dict
    handler: Callable[[Session, User, dict], Any]
    required: list[str] = field(default_factory=list)
    read_only: bool = True

    def schema(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": {"type": "object", "properties": self.properties, "required": self.required,
                            "additionalProperties": False},
            "annotations": {"title": self.title, "readOnlyHint": self.read_only, "destructiveHint": False,
                            "idempotentHint": self.read_only, "openWorldHint": False},
        }


# ------------------------------------------------------------------ argument helpers
def _str(args: dict, name: str, *, required: bool = False, max_len: int = 200, default: str | None = None) -> str | None:
    v = args.get(name, default)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ToolError(f"'{name}' is required")
        return default
    if not isinstance(v, str):
        raise ToolError(f"'{name}' must be a string")
    v = v.strip()
    if len(v) > max_len:
        raise ToolError(f"'{name}' is too long (max {max_len} characters)")
    return v


def _int(args: dict, name: str, default: int | None, lo: int, hi: int) -> int | None:
    v = args.get(name, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
        raise ToolError(f"'{name}' must be an integer")
    return max(lo, min(hi, int(v)))


def _enum(args: dict, name: str, choices: tuple[str, ...], default: str) -> str:
    v = args.get(name) or default
    if v not in choices:
        raise ToolError(f"'{name}' must be one of: {', '.join(choices)}")
    return v


def _bool(args: dict, name: str, default: bool) -> bool:
    v = args.get(name, default)
    if not isinstance(v, bool):
        raise ToolError(f"'{name}' must be true or false")
    return v


def plain(o: Any) -> Any:
    """JSON-friendly copy that keeps decimals exact (as strings)."""
    if isinstance(o, BaseModel):
        return plain(o.model_dump())
    if isinstance(o, Decimal):
        return format(o, "f")
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, dict):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [plain(x) for x in o]
    return o


TICKER = {"type": "string", "description": "Ticker symbol as used in the app, e.g. AAPL or BRK-B", "maxLength": 20}


# ------------------------------------------------------------------ documents
def list_documents(db: Session, user: User, args: dict):
    docs = db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())).all()
    return {
        "documents": [
            {"id": d.id, "title": d.title, "filename": d.filename, "pages": d.pages, "ocr_pages": d.ocr_pages,
             "status": d.status, "ticker": d.security.ticker if d.security else None, "uploaded_at": d.created_at}
            for d in docs
        ],
        "note": "Use search_documents to find passages, read_document to read pages.",
    }


def _owned_docs(db: Session, user: User, ids: list | None) -> list[Document]:
    stmt = select(Document).where(Document.user_id == user.id, Document.status.not_in(("error",)))
    if ids:
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids) or len(ids) > 50:
            raise ToolError("'document_ids' must be a list of up to 50 integers")
        stmt = stmt.where(Document.id.in_(ids))
    return list(db.scalars(stmt))


def search_documents(db: Session, user: User, args: dict):
    from ..routers.ai import _embed_model_for
    from . import documents as docsvc

    query = _str(args, "query", required=True, max_len=500)
    k = _int(args, "limit", 8, 1, 20)
    docs = _owned_docs(db, user, args.get("document_ids"))
    if not docs:
        return {"results": [], "note": "No uploaded documents match. The user can upload PDFs in the app (Documents)."}
    hits = docsvc.search(db, docs, query, k=k, embed_model=_embed_model_for(db, user))
    return {
        "results": [{"document_id": h.document_id, "document": h.title, "page": h.page, "ocr": h.ocr, "text": h.text}
                    for h in hits],
        "note": "Passages ranked by keyword (and semantic, when local embeddings exist) relevance. Cite document + page.",
    }


def read_document(db: Session, user: User, args: dict):
    doc_id = _int(args, "document_id", None, 1, 2**31)
    if doc_id is None:
        raise ToolError("'document_id' is required")
    doc = db.scalar(select(Document).where(Document.id == doc_id, Document.user_id == user.id))
    if doc is None:
        raise ToolError("Document not found")
    start = _int(args, "start_page", 1, 1, max(doc.pages, 1))
    end = _int(args, "end_page", start + 4, start, max(doc.pages, 1))
    end = min(end, start + 9)
    chunks = db.scalars(select(DocumentChunk).where(
        DocumentChunk.document_id == doc.id, DocumentChunk.page >= start, DocumentChunk.page <= end,
    ).order_by(DocumentChunk.seq)).all()
    return {
        "document_id": doc.id, "title": doc.title, "total_pages": doc.pages, "start_page": start, "end_page": end,
        "passages": [{"page": c.page, "ocr": c.ocr, "text": c.text} for c in chunks],
        "note": ("Consecutive passages may overlap slightly. At most 10 pages per call."
                 + ("" if chunks else " No text was extracted for these pages.")),
    }


# ------------------------------------------------------------------ portfolio & lists
def get_portfolios(db: Session, user: User, args: dict):
    from ..routers import portfolios as pr

    pid = _int(args, "portfolio_id", None, 1, 2**31)
    include_tx = _bool(args, "include_transactions", False)
    stmt = select(Portfolio).where(Portfolio.user_id == user.id).order_by(Portfolio.created_at)
    if pid:
        stmt = stmt.where(Portfolio.id == pid)
    ports = db.scalars(stmt).all()
    if pid and not ports:
        raise ToolError("Portfolio not found")
    out = []
    for p in ports:
        d = plain(pr.detail(db, p))
        txs = d.pop("transactions")
        d["transaction_count"] = len(txs)
        if include_tx:
            d["transactions"] = txs[:300]
        out.append(d)
    return {"portfolios": out}


def get_portfolio_performance(db: Session, user: User, args: dict):
    from ..routers import portfolios as pr

    pid = _int(args, "portfolio_id", None, 1, 2**31)
    if pid is None:
        raise ToolError("'portfolio_id' is required (see get_portfolios)")
    base = _str(args, "base_currency", max_len=3)
    data = pr.analytics(pid, base.upper() if base else None, db, user)
    if not _bool(args, "include_daily_history", False):
        hist = data.pop("history", {})
        data["history_summary"] = {
            ccy: {"points": len(pts), "first": pts[0] if pts else None, "last": pts[-1] if pts else None}
            for ccy, pts in hist.items()
        }
    return data


def get_watchlists(db: Session, user: User, args: dict):
    from ..routers import watchlists as wr

    return {"watchlists": plain(wr.list_watchlists(db, user)),
            "note": "Quotes are the latest stored end-of-day closes (see their date), not live prices."}


def get_notes(db: Session, user: User, args: dict):
    from ..routers import notes as nr

    ticker = _str(args, "ticker", max_len=20)
    q = (_str(args, "query", max_len=200) or "").lower()
    include_shared = _bool(args, "include_shared", True)
    notes = list(nr.list_notes(ticker, "mine", db, user))
    if include_shared:
        notes += list(nr.list_notes(ticker, "shared", db, user))
    if q:
        notes = [n for n in notes if q in n.title.lower() or q in n.body.lower()]
    out = []
    for n in notes[:50]:
        d = plain(n)
        d["ticker"] = (d.pop("security") or {}).get("ticker")
        if len(d["body"]) > 6000:
            d["body"] = d["body"][:6000] + " …[truncated]"
        out.append(d)
    return {"notes": out, "total": len(notes)}


def save_note(db: Session, user: User, args: dict):
    from ..routers import notes as nr

    title = _str(args, "title", required=True, max_len=160)
    body = args.get("body") or ""
    if not isinstance(body, str) or len(body) > 50_000:
        raise ToolError("'body' must be text up to 50,000 characters")
    ticker = _str(args, "ticker", max_len=20)
    note = nr.create_note(nr.NoteIn(title=title, body=body, ticker=ticker, is_shared=False), db, user)
    return {"saved": True, "note_id": note.id, "title": note.title,
            "note": "Saved as a private note in the app (Notes). The user can edit or share it there."}


def get_alerts(db: Session, user: User, args: dict):
    from ..routers import engage

    return {"alerts": [plain(engage.AlertOut.model_validate(a)) for a in engage.list_alerts(db, user)]}


def get_news(db: Session, user: User, args: dict):
    from ..routers import engage

    scope = _enum(args, "scope", ("mine", "all"), "mine")
    limit = _int(args, "limit", 30, 1, 100)
    return engage.get_news(scope, None, limit, db, user)


# ------------------------------------------------------------------ companies & markets
def search_securities(db: Session, user: User, args: dict):
    from ..routers.securities import search_securities as search

    q = _str(args, "query", required=True, max_len=80)
    rows = search(db, q, limit=_int(args, "limit", 10, 1, 25))
    return {"results": [{"ticker": s.ticker, "name": s.name, "exchange": s.exchange, "has_sec_data": bool(s.cik),
                         "has_esef_data": bool(s.lei)} for s in rows]}


def get_company(db: Session, user: User, args: dict):
    from ..routers import companies

    ticker = _str(args, "ticker", required=True, max_len=20)
    return plain(companies.company(ticker, db, user))


def get_financials(db: Session, user: User, args: dict):
    from ..routers import companies

    ticker = _str(args, "ticker", required=True, max_len=20)
    statement = _enum(args, "statement", ("income", "balance", "cashflow", "metrics"), "income")
    period = _enum(args, "period", ("annual", "quarterly"), "annual")
    data = companies.financials(ticker, statement, period, db, user)
    rows, formulas = [], {}
    for r in data["rows"]:
        rows.append({"label": r["label"], "kind": r["kind"], "values": [c["value"] if c else None for c in r["values"]]})
        f = next((c.get("formula") for c in r["values"] if c and c.get("formula")), None)
        if f:
            formulas[r["label"]] = f
    latest = []
    for r in data["rows"]:
        c = r["values"][0] if r["values"] else None
        if c and c.get("form"):
            latest.append({"label": r["label"], "form": c.get("form"), "filed": c.get("filed"), "url": c.get("url")})
    return {
        "ticker": ticker.upper(), "statement": statement, "period": period, "currency": data.get("currency"),
        "periods": [p["label"] + f" (ends {p['end']})" for p in data["periods"]],
        "rows": rows,
        "derived_formulas": formulas,
        "latest_period_sources": latest[:40],
        "source": data.get("source"),
        "note": ("Values as reported (money in units of the currency, not thousands). null = not reported. "
                 "Percent/ratio metrics are fractions (0.25 = 25%)."),
    }


def get_price_history(db: Session, user: User, args: dict):
    from ..routers import companies

    ticker = _str(args, "ticker", required=True, max_len=20)
    rng = _enum(args, "range", ("1m", "3m", "6m", "1y", "5y", "max"), "1y")
    p = companies.get_prices(ticker, rng, db, user)
    bars = p.bars
    if not bars:
        return {"ticker": p.ticker, "bars": [], "error": p.error,
                "note": "No stored prices for this ticker. " + p.note}
    step = "daily"
    sampled = bars
    if rng == "5y":
        step, sampled = "weekly (last close of each ISO week)", _last_per(bars, lambda d: d.isocalendar()[:2])
    elif rng == "max":
        step, sampled = "monthly (last close of each month)", _last_per(bars, lambda d: (d.year, d.month))
    closes = [b.close for b in bars]
    first, last = bars[0], bars[-1]
    return {
        "ticker": p.ticker, "currency": p.currency, "sources": p.sources, "range": rng,
        "summary": {
            "first": {"date": first.date, "close": first.close}, "last": {"date": last.date, "close": last.close},
            "change_pct": format(((last.close / first.close) - 1) * 100, ".2f") if first.close else None,
            "high_close": max(closes), "low_close": min(closes), "trading_days": len(bars),
        },
        "series_interval": step,
        "series": [[b.date.isoformat(), format(b.close, "f")] for b in sampled],
        "error": p.error, "note": p.note,
    }


def _last_per(bars, key):
    seen = {}
    for b in bars:
        seen[key(b.date)] = b
    return sorted(seen.values(), key=lambda b: b.date)


def compare_companies(db: Session, user: User, args: dict):
    from ..routers import research

    tickers = args.get("tickers")
    if not isinstance(tickers, list) or not 2 <= len(tickers) <= 5 or not all(isinstance(t, str) for t in tickers):
        raise ToolError("'tickers' must be a list of 2 to 5 ticker strings")
    return plain(research.compare(",".join(t.strip().upper() for t in tickers), db, user))


def get_valuations(db: Session, user: User, args: dict):
    from ..routers import research

    ticker = _str(args, "ticker", max_len=20)
    out = {"saved_valuations": plain(research.list_valuations(ticker.upper() if ticker else None, db, user))}
    if ticker and _bool(args, "include_dcf_inputs", False):
        out["dcf_inputs"] = plain(research.dcf_inputs(ticker, db, user))
    return out


# ------------------------------------------------------------------ registry
def tools() -> list[Tool]:
    t = [
        Tool("list_documents", "List uploaded documents",
             "List the PDFs the user uploaded to the app (annual reports, presentations, broker research...), with id, "
             "title, pages and linked ticker.", {}, list_documents),
        Tool("search_documents", "Search uploaded documents",
             "Search the text of the user's uploaded PDFs and return the most relevant passages with document title and "
             "page. Use for any question about the contents of their files.",
             {"query": {"type": "string", "description": "What to look for (keywords or a question)", "maxLength": 500},
              "document_ids": {"type": "array", "items": {"type": "integer"}, "description": "Optional: limit to these documents"},
              "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8}},
             search_documents, required=["query"]),
        Tool("read_document", "Read document pages",
             "Read the extracted text of up to 10 consecutive pages of one uploaded PDF.",
             {"document_id": {"type": "integer"}, "start_page": {"type": "integer", "minimum": 1, "default": 1},
              "end_page": {"type": "integer", "minimum": 1}},
             read_document, required=["document_id"]),
        Tool("get_portfolios", "Get portfolios and holdings",
             "The user's portfolios: open and closed positions (quantity, average cost, cost basis, realised P/L, "
             "dividends, latest stored close and market value) and totals per currency.",
             {"portfolio_id": {"type": "integer", "description": "Optional: one portfolio"},
              "include_transactions": {"type": "boolean", "default": False}},
             get_portfolios),
        Tool("get_portfolio_performance", "Get portfolio performance",
             "Allocation, time-weighted return (TWR), money-weighted return (XIRR) and dividend income for one portfolio.",
             {"portfolio_id": {"type": "integer"},
              "base_currency": {"type": "string", "description": "Optional 3-letter code to convert allocation (ECB rates)", "maxLength": 3},
              "include_daily_history": {"type": "boolean", "default": False}},
             get_portfolio_performance, required=["portfolio_id"]),
        Tool("get_watchlists", "Get watchlists", "The user's watchlists with their notes and latest stored close per ticker.",
             {}, get_watchlists),
        Tool("get_notes", "Get research notes",
             "The user's research notes (and notes other members shared), optionally filtered by ticker or text.",
             {"ticker": TICKER, "query": {"type": "string", "maxLength": 200},
              "include_shared": {"type": "boolean", "default": True}},
             get_notes),
        Tool("get_alerts", "Get alerts", "The user's price and filing alerts and when they last triggered.", {}, get_alerts),
        Tool("get_news", "Get news and filings",
             "Recent headlines from the app's RSS feeds and, for scope=mine, recent SEC filings of companies the user "
             "follows (watchlists and portfolios).",
             {"scope": {"type": "string", "enum": ["mine", "all"], "default": "mine"},
              "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}},
             get_news),
        Tool("search_securities", "Find a company or ticker",
             "Find listed securities by ticker or company name.",
             {"query": {"type": "string", "maxLength": 80}, "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10}},
             search_securities, required=["query"]),
        Tool("get_company", "Get company overview",
             "Company profile, latest stored end-of-day quote, key figures from the latest annual report and data freshness.",
             {"ticker": TICKER}, get_company, required=["ticker"]),
        Tool("get_financials", "Get financial statements",
             "Reported income statement, balance sheet, cash flow or derived metrics (margins, ROE, payout...) from SEC "
             "XBRL or ESEF filings, annual (up to 10 years) or quarterly.",
             {"ticker": TICKER,
              "statement": {"type": "string", "enum": ["income", "balance", "cashflow", "metrics"], "default": "income"},
              "period": {"type": "string", "enum": ["annual", "quarterly"], "default": "annual"}},
             get_financials, required=["ticker"]),
        Tool("get_price_history", "Get price history",
             "End-of-day closing prices stored in the app (not real-time) with a summary of the change over the range.",
             {"ticker": TICKER, "range": {"type": "string", "enum": ["1m", "3m", "6m", "1y", "5y", "max"], "default": "1y"}},
             get_price_history, required=["ticker"]),
        Tool("compare_companies", "Compare companies", "Side-by-side key figures and metrics for 2–5 companies.",
             {"tickers": {"type": "array", "items": {"type": "string", "maxLength": 20}, "minItems": 2, "maxItems": 5}},
             compare_companies, required=["tickers"]),
        Tool("get_valuations", "Get saved valuations",
             "DCF valuations the user saved in the app, optionally with the DCF inputs the app derives from filings.",
             {"ticker": TICKER, "include_dcf_inputs": {"type": "boolean", "default": False}},
             get_valuations),
    ]
    if get_settings().connector_write_tools:
        t.append(Tool("save_note", "Save a note",
                      "Save a new private research note in the app (e.g. a summary of this analysis). Only when the user asks.",
                      {"title": {"type": "string", "maxLength": 160}, "body": {"type": "string", "maxLength": 50000},
                       "ticker": TICKER},
                      save_note, required=["title"], read_only=False))
    return t


def call(db: Session, user: User, name: str, args: dict) -> tuple[str, bool]:
    """Run a tool. Returns (text, is_error)."""
    tool = next((t for t in tools() if t.name == name), None)
    if tool is None:
        raise KeyError(name)
    if not isinstance(args, dict):
        return "Arguments must be an object", True
    try:
        result = tool.handler(db, user, args)
    except ToolError as exc:
        return str(exc), True
    except HTTPException as exc:
        db.rollback()
        return str(exc.detail), True
    text = json.dumps(plain(result), ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n…[output truncated; narrow the request, e.g. fewer pages or a shorter range]"
    return text, False
