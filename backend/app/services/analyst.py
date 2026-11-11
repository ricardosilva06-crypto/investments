"""Grounded prompting for the local AI analyst.

The model never gets to "remember" financial figures: every figure it may use is
placed in a numbered SOURCES block built from this application's database
(SEC XBRL facts, stored prices, the user's own portfolio and notes) and from
passages retrieved from the user's PDFs. Answers must separate verified data,
calculations, assumptions and opinion, and cite sources. Afterwards every number
in the answer is checked against the source values (``verify_numbers``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import CompanyProfile, Document, FinancialFact, Note, Portfolio, PriceBar, Security, User
from . import documents as docsvc
from . import fundamentals, prices
from .portfolio import LedgerError, build_ledger

TASKS: dict[str, dict] = {
    "ask": {"label": "Ask", "needs": []},
    "company_analysis": {"label": "Company analysis", "needs": ["ticker"]},
    "bull_bear": {"label": "Bull & bear case", "needs": ["ticker"]},
    "earnings": {"label": "Earnings analysis", "needs": ["ticker"]},
    "financials": {"label": "Financial statement analysis", "needs": ["ticker"]},
    "valuation": {"label": "Valuation explained", "needs": ["ticker"]},
    "compare": {"label": "Compare companies", "needs": ["two_tickers"]},
    "portfolio": {"label": "Portfolio analysis", "needs": []},
    "document": {"label": "Document analysis", "needs": ["document"]},
    "thesis": {"label": "Investment thesis", "needs": ["ticker"]},
}

TASK_INSTRUCTIONS = {
    "ask": "Answer the user's question.",
    "company_analysis": (
        "Write a concise research report on {tickers}: business overview (only from the sources), revenue and profit "
        "trend, margins, cash generation, balance-sheet strength, key risks, and what to watch next."
    ),
    "bull_bear": (
        "Write a balanced bull case and bear case for {tickers}. Under Opinion use two sub-headings '### Bull case' "
        "and '### Bear case', 3–5 points each, each point tied to cited data where possible. End with what evidence "
        "would decide between them."
    ),
    "earnings": (
        "Analyse the most recent reported periods for {tickers}: quarter-over-quarter and year-over-year changes in "
        "revenue, operating income, net income, EPS and operating cash flow. Point out derived (calculated) quarters."
    ),
    "financials": (
        "Analyse the financial statements of {tickers}: income statement quality, balance-sheet structure (liquidity, "
        "leverage), cash-flow conversion (operating cash flow vs net income, free cash flow), and capital returns."
    ),
    "valuation": (
        "Explain how {tickers} could be valued: which multiples are computable from the sources (e.g. P/E from the "
        "stored close and diluted EPS), what they mean, and what a discounted-cash-flow approach would require. "
        "Never invent a price, share count or market capitalisation. If they are missing say so. Any target value must "
        "be presented under Assumptions/Opinion with explicit inputs."
    ),
    "compare": (
        "Compare {tickers} side by side on growth, margins, cash flow, balance sheet and, if available, valuation "
        "multiples. Use a Markdown table under Verified data for the reported figures."
    ),
    "portfolio": (
        "Review the user's portfolio: concentration by position and currency, cost basis vs stored market value where "
        "available, realised results and dividends, and questions the user should ask themselves. No FX conversion."
    ),
    "document": "Summarise and analyse the provided document passages: key figures, guidance, risks and changes.",
    "thesis": (
        "Draft an investment thesis for {tickers}: thesis statement, key drivers, valuation considerations, risks, "
        "catalysts, and what would make the thesis wrong."
    ),
}

SYSTEM_PROMPT = """You are a careful equity research assistant running locally for a private investor.

RULES — follow strictly:
1. Use ONLY the numbered SOURCES provided in the user's message for any financial figure, date, price or fact about a company. Cite them inline like [F1], [P1], [D2], [C1], [N1].
2. Never invent or recall from memory figures that are not in the SOURCES. If something needed is missing, write "not in the provided data".
3. Prices are end-of-day closes with the date given. Never call them real-time.
4. Values marked "calculated" were computed by the application; say so when you use them.
5. Structure every answer with exactly these Markdown headings, in this order:
## Verified data
(only facts taken directly from the sources, each with a citation)
## Calculations
(any arithmetic you perform: show the formula and the cited inputs; write "None" if none)
## Assumptions
(anything assumed, e.g. growth rates or discount rates, labelled as assumptions; write "None" if none)
## Opinion
(your interpretation and judgement, clearly opinion; not investment advice)
6. Be concise. Use bullet points. Write amounts with their currency and unit (e.g. USD 391.0 billion).
7. User notes [N#] are the user's own opinions, not verified data."""


# ------------------------------------------------------------------ data structures
@dataclass
class Source:
    id: str
    kind: str  # company | financials | price | calc | document | note | portfolio
    label: str
    url: str | None = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "url": self.url, "detail": self.detail}


@dataclass
class Context:
    blocks: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    values: list[Decimal] = field(default_factory=list)  # raw numbers available to the model
    counters: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def next_id(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}{self.counters[prefix]}"

    def text(self, budget_chars: int) -> str:
        out, used = [], 0
        for b in self.blocks:
            if used + len(b) > budget_chars:
                self.warnings.append("Some sources were left out to fit the model's context window.")
                break
            out.append(b)
            used += len(b)
        return "\n\n".join(out) if out else "(no sources available)"


def _fmt(v: Decimal | None, kind: str) -> str:
    if v is None:
        return "n/a"
    if kind == "money":
        return f"{v / Decimal(1_000_000):,.1f}"
    if kind == "percent":
        return f"{v * 100:.1f}%"
    if kind == "ratio":
        return f"{v:.2f}x"
    if kind == "shares":
        return f"{v / Decimal(1_000_000):,.1f}m"
    return f"{v:,.2f}"


# ------------------------------------------------------------------ context builders
def _statement_block(ctx: Context, sec: Security, facts, statement: str, period: str, n: int) -> None:
    data = (
        fundamentals.build_metrics(facts, period)
        if statement == "metrics"
        else fundamentals.build_statement(facts, statement, period, limit=n)
    )
    periods = data["periods"][:n]
    if not periods or not data["rows"]:
        return
    sid = ctx.next_id("C" if statement == "metrics" else "F")
    names = {"income": "Income statement", "balance": "Balance sheet", "cashflow": "Cash flow", "metrics": "Ratios (calculated by the app)"}
    head = " | ".join(p["label"] for p in periods)
    lines = [
        f"[{sid}] {sec.ticker} {names[statement]}, {period}. Source: {'ESEF annual reports (IFRS)' if sec.lei and not sec.cik else 'SEC EDGAR XBRL filings'}. "
        f"Money in {data['currency']} millions; per-share in {data['currency']}." + (" All values calculated." if statement == "metrics" else ""),
        f"Line | {head}",
    ]
    for r in data["rows"]:
        cells = []
        for c in r["values"][:n]:
            if c is None:
                cells.append("n/a")
                continue
            v = Decimal(c["value"])
            ctx.values.append(v)
            mark = " (calculated)" if c["derived"] and statement != "metrics" else ""
            cells.append(_fmt(v, r["kind"]) + mark)
        lines.append(f"{r['label']} | " + " | ".join(cells))
    ctx.blocks.append("\n".join(lines))
    ctx.sources.append(
        Source(sid, "calc" if statement == "metrics" else "financials", f"{sec.ticker} · {names[statement]} ({period})",
               url=f"/company?t={sec.ticker}")
    )


def add_company(ctx: Context, db: Session, sec: Security, task: str) -> None:
    prof = db.get(CompanyProfile, sec.cik) if sec.cik else None
    sid = ctx.next_id("S")
    ident = f"SEC CIK {sec.cik}" if sec.cik else (f"LEI {sec.lei} (EU issuer, ESEF reports)" if sec.lei else "no SEC CIK")
    desc = [f"[{sid}] Company: {sec.name} — ticker {sec.ticker}, exchange {sec.exchange or 'n/a'}, {ident}."]
    if prof:
        desc.append(
            f"Industry (SIC): {prof.sic_description or 'n/a'}. Fiscal year end (MMDD): {prof.fiscal_year_end or 'n/a'}. "
            f"Incorporated: {prof.state_of_incorporation or 'n/a'}. Filer category: {prof.category or 'n/a'}."
        )
    ctx.blocks.append(" ".join(desc))
    ctx.sources.append(Source(sid, "company", f"{sec.ticker} · SEC company profile", url=f"/company?t={sec.ticker}"))

    facts = fundamentals.facts_for_security(db, sec)
    if not facts:
        ctx.blocks.append(f"(No SEC or ESEF financial data stored for {sec.ticker}. Do not state its financial figures.)")
        ctx.warnings.append(f"No financial statements stored for {sec.ticker}. Open its company page first to download them.")
    else:
        n_years = 3 if task == "compare" else 4
        for st in ("income", "cashflow", "balance", "metrics"):
            _statement_block(ctx, sec, facts, st, "annual", n_years)
        if task in ("earnings", "company_analysis", "thesis"):
            _statement_block(ctx, sec, facts, "income", "quarterly", 5)
            _statement_block(ctx, sec, facts, "cashflow", "quarterly", 5)

    # Prices and simple valuation multiples (computed here, labelled as calculated).
    q = prices.latest_quotes(db, [sec.ticker]).get(sec.ticker)
    if not q:
        ctx.blocks.append(f"(No stored price for {sec.ticker}. Do not state a share price, market capitalisation or price multiple.)")
        return
    pid = ctx.next_id("P")
    last = q["date"]
    year = db.execute(
        select(func.min(PriceBar.close), func.max(PriceBar.close)).where(
            PriceBar.ticker == sec.ticker, PriceBar.day >= last - timedelta(days=365)
        )
    ).one()
    lo, hi = (Decimal(year[0]), Decimal(year[1])) if year[0] is not None else (None, None)
    ctx.values += [q["close"]] + ([lo, hi] if lo is not None else [])
    ctx.blocks.append(
        f"[{pid}] {sec.ticker} end-of-day close {q['close']} {q['currency']} on {last.isoformat()} (source: {q['source']}; not real-time)."
        + (f" 52-week closing range in stored data: {lo}–{hi} {q['currency']}." if lo is not None else "")
    )
    ctx.sources.append(Source(pid, "price", f"{sec.ticker} close {last.isoformat()} ({q['source']})", url=f"/company?t={sec.ticker}"))
    if facts:
        inc = fundamentals.build_statement(facts, "income", "annual", limit=1)
        bal = fundamentals.build_statement(facts, "balance", "annual", limit=1)
        eps = next((r["values"][0] for r in inc["rows"] if r["key"] == "eps_diluted"), None)
        shares = next((r["values"][0] for r in bal["rows"] if r["key"] == "shares_outstanding"), None)
        calc = []
        if eps and inc["currency"] == q["currency"] and Decimal(eps["value"]) > 0:
            pe = q["close"] / Decimal(eps["value"])
            ctx.values.append(pe)
            calc.append(f"P/E = close {q['close']} / latest fiscal-year diluted EPS {eps['value']} = {pe:.1f}")
        if shares and inc["currency"] == q["currency"]:
            mcap = q["close"] * Decimal(shares["value"])
            ctx.values.append(mcap)
            calc.append(
                f"Approx. market capitalisation = close × shares outstanding reported at fiscal year end ({_fmt(Decimal(shares['value']), 'shares')}) "
                f"= {_fmt(mcap, 'money')} {q['currency']} millions (share count may be outdated)"
            )
        if calc:
            cid = ctx.next_id("C")
            ctx.blocks.append(f"[{cid}] {sec.ticker} valuation inputs calculated by the app: " + "; ".join(calc) + ".")
            ctx.sources.append(Source(cid, "calc", f"{sec.ticker} · multiples calculated from stored close and SEC data"))


def add_notes(ctx: Context, db: Session, user: User, sec: Security) -> None:
    for n in db.scalars(
        select(Note).where(Note.user_id == user.id, Note.security_id == sec.id).order_by(Note.updated_at.desc()).limit(2)
    ):
        nid = ctx.next_id("N")
        ctx.blocks.append(f"[{nid}] User's own note “{n.title}” (opinion, not verified):\n{n.body[:1500]}")
        ctx.sources.append(Source(nid, "note", f"Your note: {n.title}", url=f"/notes?id={n.id}"))


def add_portfolio(ctx: Context, db: Session, user: User) -> None:
    pfs = db.scalars(select(Portfolio).where(Portfolio.user_id == user.id).options(selectinload(Portfolio.transactions))).all()
    if not pfs:
        ctx.blocks.append("(The user has no portfolio recorded.)")
        return
    for p in pfs:
        try:
            ledger = build_ledger(list(p.transactions))
        except LedgerError as exc:
            ctx.warnings.append(f"Portfolio {p.name}: {exc}")
            continue
        open_pos = [x for x in ledger.positions.values() if x.quantity > 0]
        quotes = prices.latest_quotes(db, [x.symbol for x in open_pos])
        pid = ctx.next_id("H")
        lines = [f"[{pid}] Portfolio “{p.name}” (from the user's own transactions; average-cost method; no FX conversion)."]
        lines.append("Symbol | Currency | Quantity | Cost basis | Last close (date) | Market value | Realised P/L | Dividends")
        for x in sorted(open_pos, key=lambda x: x.cost_basis, reverse=True):
            q = quotes.get(x.symbol)
            mv = (x.quantity * q["close"]) if q and q["currency"] == x.currency else None
            ctx.values += [x.quantity, x.cost_basis, x.realized_pl, x.dividends] + ([q["close"], mv] if mv is not None else [])
            lines.append(
                f"{x.symbol} | {x.currency} | {x.quantity} | {x.cost_basis:.2f} | "
                + (f"{q['close']} ({q['date'].isoformat()})" if q else "n/a")
                + f" | {f'{mv:.2f}' if mv is not None else 'n/a'} | {x.realized_pl:.2f} | {x.dividends:.2f}"
            )
        closed = [x for x in ledger.positions.values() if x.quantity == 0]
        if closed:
            lines.append("Closed positions: " + ", ".join(f"{x.symbol} realised {x.realized_pl:.2f} {x.currency}" for x in closed))
            ctx.values += [x.realized_pl for x in closed]
        ctx.blocks.append("\n".join(lines))
        ctx.sources.append(Source(pid, "portfolio", f"Your portfolio: {p.name}", url=f"/portfolio?id={p.id}"))


def add_documents(ctx: Context, db: Session, docs: list[Document], query: str, embed_model: str | None, k: int) -> None:
    for hit in docsvc.search(db, docs, query, k=k, embed_model=embed_model):
        did = ctx.next_id("D")
        ocr_note = " (text recognised by OCR from a scanned page: numbers may contain recognition errors; say so when you use them)" if hit.ocr else ""
        ctx.blocks.append(f"[{did}] Document “{hit.title}”, page {hit.page}{ocr_note}:\n{hit.text}")
        ctx.sources.append(Source(did, "document", f"{hit.title} · p. {hit.page}{' (OCR)' if hit.ocr else ''}", url=f"/api/documents/{hit.document_id}/file#page={hit.page}",
                                  detail=hit.text[:300]))
        ctx.values += _numbers_in_text(hit.text)


def build_context(db: Session, user: User, task: str, securities: list[Security], docs: list[Document], question: str,
                  embed_model: str | None) -> Context:
    ctx = Context()
    for sec in securities[:3]:
        add_company(ctx, db, sec, task)
        add_notes(ctx, db, user, sec)
    if task == "portfolio":
        add_portfolio(ctx, db, user)
    if docs:
        add_documents(ctx, db, docs, question or " ".join(s.name for s in securities), embed_model, k=10 if task == "document" else 6)
    return ctx


def build_messages(task: str, question: str, tickers: list[str], ctx_text: str, history: list[dict]) -> list[dict]:
    instruction = TASK_INSTRUCTIONS.get(task, TASK_INSTRUCTIONS["ask"]).format(tickers=", ".join(tickers) or "the company")
    user_msg = f"SOURCES:\n{ctx_text}\n\nTASK: {instruction}"
    if question.strip():
        user_msg += f"\n\nUSER QUESTION: {question.strip()}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": user_msg}]


# ------------------------------------------------------------------ verification
NUM_RE = re.compile(
    r"(?<![\w\[])(?P<sign>[-−])?(?P<cur>[$€£¥])?\s?(?P<num>\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<suf>%|x\b|×|trillion\b|tn\b|billion\b|bn\b|b\b|million\b|mn\b|m\b|thousand\b|k\b)?",
    re.IGNORECASE,
)
SCALE = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6,
         "thousand": 1e3, "k": 1e3}


def _numbers_in_text(t: str) -> list[Decimal]:
    out = []
    for m in NUM_RE.finditer(t):
        try:
            out.append(Decimal(m.group("num").replace(",", "").replace(" ", "").replace(" ", "")))
        except InvalidOperation:
            pass
    return out


def _sections(answer: str) -> list[tuple[str, str]]:
    parts, current, buf = [], "Other", []
    for line in answer.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)", line)
        if m and m.group(1).strip().lower().startswith(("verified", "calculation", "assumption", "opinion")):
            parts.append((current, "\n".join(buf)))
            current, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    parts.append((current, "\n".join(buf)))
    return [(h, b) for h, b in parts if b.strip()]


def _matches(value: float, decimals: int, known: list[float], allow_scaled: bool) -> bool:
    tol_abs = 0.5 * 10 ** (-decimals)
    for k in known:
        cands = [k]
        if allow_scaled:
            cands += [k / 1e3, k / 1e6, k / 1e9, k / 1e12]
        for c in cands:
            if abs(abs(value) - abs(c)) <= max(tol_abs * 1.0001, abs(c) * 0.002):
                return True
    return False


def verify_numbers(answer: str, values: list[Decimal]) -> dict:
    """Check every number in the answer against the numbers present in the sources.

    Years, citation markers and small counts are ignored. Numbers under
    Calculations/Assumptions/Opinion may legitimately be new (results of arithmetic or
    assumptions); unmatched numbers under "Verified data" are flagged as warnings.
    """
    known = [float(v) for v in values]
    known_pct = [float(v) * 100 for v in values]
    checked, unmatched_verified, unmatched_other = 0, [], []
    for heading, body in _sections(answer):
        body = re.sub(r"\[[A-Z]\d+\]", " ", body)  # citations
        in_verified = heading.lower().startswith("verified")
        for m in NUM_RE.finditer(body):
            raw, suf = m.group("num"), (m.group("suf") or "").lower()
            try:
                num = float(raw.replace(",", "").replace(" ", "").replace(" ", ""))
            except ValueError:
                continue
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            if not suf and not m.group("cur") and decimals == 0 and (1900 <= num <= 2100 or num < 10):
                continue  # years and small counts
            checked += 1
            if suf == "%":
                ok = _matches(num, decimals, known_pct, False) or _matches(num / 100, decimals + 2, known, False)
            elif suf in ("x", "×"):
                ok = _matches(num, decimals, known, False)
            elif suf in SCALE:
                ok = _matches(num * SCALE[suf], decimals, [k for k in known], False) or _matches(num, decimals, known, True)
                if not ok:
                    ok = any(abs(num * SCALE[suf] - k) <= SCALE[suf] * 0.5 * 10 ** (-decimals) + abs(k) * 0.002 for k in known)
            else:
                ok = _matches(num, decimals, known, True)
            if not ok:
                token = m.group(0).strip()
                (unmatched_verified if in_verified else unmatched_other).append(token)
    sections_found = [h for h, _ in _sections(answer)]
    return {
        "checked": checked,
        "unmatched_verified": sorted(set(unmatched_verified))[:30],
        "unmatched_other": sorted(set(unmatched_other))[:30],
        "has_structure": all(
            any(s.lower().startswith(p) for s in sections_found) for p in ("verified", "calculation", "assumption", "opinion")
        ),
    }
