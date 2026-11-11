"""Per-user portfolios and transaction ledger."""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Portfolio, Security, Transaction, User
from ..schemas import ORM
from ..services.portfolio import LedgerError, build_ledger
from ..services import portfolio_analytics as pa
from ..services.prices import latest_quotes

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


class PortfolioIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class TransactionIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    kind: str
    trade_date: date
    quantity: Decimal = Decimal(0)
    price: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    currency: str = Field(min_length=3, max_length=3)
    note: str = Field("", max_length=2000)

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        v = v.strip().upper()
        if not all(c.isalnum() or c in ".-:" for c in v):
            raise ValueError("Symbol may contain letters, digits, '.', '-' or ':'")
        return v

    @field_validator("currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code")
        return v

    @field_validator("quantity", "price", "fees")
    @classmethod
    def _non_negative(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v < 0:
            raise ValueError("Must be a non-negative number")
        return v

    @model_validator(mode="after")
    def _check(self):
        if self.kind not in ("buy", "sell", "dividend"):
            raise ValueError("kind must be buy, sell or dividend")
        if self.kind in ("buy", "sell") and self.quantity <= 0:
            raise ValueError("Quantity must be greater than zero")
        if self.kind == "dividend" and self.price <= 0:
            raise ValueError("Dividend amount must be greater than zero")
        if self.trade_date > date.today():
            raise ValueError("Trade date cannot be in the future")
        return self


class TransactionOut(ORM):
    id: int
    symbol: str
    kind: str
    trade_date: date
    quantity: Decimal
    price: Decimal
    fees: Decimal
    currency: str
    note: str
    security_id: int | None
    created_at: datetime


class PositionOut(BaseModel):
    symbol: str
    currency: str
    quantity: Decimal
    average_cost: Decimal | None
    cost_basis: Decimal
    realized_pl: Decimal
    dividends: Decimal
    fees: Decimal
    transactions: int
    first_trade: str | None
    security_ticker: str | None
    security_name: str | None
    # Valuation at the latest stored end-of-day close (only when the price currency matches).
    last_close: Decimal | None = None
    last_close_date: date | None = None
    price_source: str | None = None
    market_value: Decimal | None = None
    unrealized_pl: Decimal | None = None
    valuation_note: str | None = None


class CurrencyTotal(BaseModel):
    currency: str
    cost_basis: Decimal
    realized_pl: Decimal
    dividends: Decimal
    market_value: Decimal | None = None  # only when every open position in this currency has a price
    unrealized_pl: Decimal | None = None
    priced_positions: int = 0
    open_positions: int = 0
    oldest_price_date: date | None = None


class PortfolioOut(ORM):
    id: int
    name: str
    created_at: datetime


class PortfolioDetail(BaseModel):
    portfolio: PortfolioOut
    open_positions: list[PositionOut]
    closed_positions: list[PositionOut]
    totals_by_currency: list[CurrencyTotal]
    transactions: list[TransactionOut]
    market_value_note: str


def owned_portfolio(db: Session, user: User, portfolio_id: int) -> Portfolio:
    p = db.scalar(select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user.id))
    if p is None:
        raise HTTPException(404, "Portfolio not found")
    return p


def detail(db: Session, p: Portfolio) -> PortfolioDetail:
    txs = list(p.transactions)
    ledger = build_ledger(txs)
    sec_ids = {pos.security_id for pos in ledger.positions.values() if pos.security_id}
    secs = {s.id: s for s in db.scalars(select(Security).where(Security.id.in_(sec_ids)))} if sec_ids else {}
    quotes = latest_quotes(db, sorted({pos.symbol for pos in ledger.positions.values() if pos.quantity > 0}))
    open_, closed = [], []
    totals: dict[str, CurrencyTotal] = {}
    for pos in sorted(ledger.positions.values(), key=lambda x: x.symbol):
        sec = secs.get(pos.security_id) if pos.security_id else None
        out = PositionOut(
            symbol=pos.symbol,
            currency=pos.currency,
            quantity=pos.quantity,
            average_cost=pos.average_cost,
            cost_basis=pos.cost_basis,
            realized_pl=pos.realized_pl,
            dividends=pos.dividends,
            fees=pos.fees,
            transactions=pos.transactions,
            first_trade=pos.first_trade,
            security_ticker=sec.ticker if sec else None,
            security_name=sec.name if sec else None,
        )
        t = totals.setdefault(pos.currency, CurrencyTotal(currency=pos.currency, cost_basis=0, realized_pl=0, dividends=0, market_value=0, unrealized_pl=0))
        if pos.quantity > 0:
            t.open_positions += 1
            q = quotes.get(pos.symbol)
            if q is None:
                out.valuation_note = "No stored price"
            elif q["currency"] != pos.currency:
                out.valuation_note = f"Price is in {q['currency']}, position in {pos.currency}; not converted"
            else:
                out.last_close, out.last_close_date, out.price_source = q["close"], q["date"], q["source"]
                out.market_value = (pos.quantity * q["close"]).quantize(Decimal("0.01"))
                out.unrealized_pl = out.market_value - pos.cost_basis
                t.priced_positions += 1
                t.market_value += out.market_value
                t.unrealized_pl += out.unrealized_pl
                if t.oldest_price_date is None or q["date"] < t.oldest_price_date:
                    t.oldest_price_date = q["date"]
        (open_ if pos.quantity > 0 else closed).append(out)
        t.cost_basis += pos.cost_basis
        t.realized_pl += pos.realized_pl
        t.dividends += pos.dividends
    for t in totals.values():
        if t.priced_positions < t.open_positions or t.open_positions == 0:
            t.market_value = t.unrealized_pl = None
    return PortfolioDetail(
        portfolio=p,
        open_positions=open_,
        closed_positions=closed,
        totals_by_currency=sorted(totals.values(), key=lambda t: t.currency),
        transactions=sorted(txs, key=lambda t: (t.trade_date, t.id), reverse=True),
        market_value_note=(
            "Market value uses the latest stored end-of-day close (date shown), not live prices. "
            "Totals are shown only when every open position in that currency has a price; no FX conversion."
        ),
    )


@router.get("", response_model=list[PortfolioOut])
def list_portfolios(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Portfolio).where(Portfolio.user_id == user.id).order_by(Portfolio.created_at)).all()


@router.post("", response_model=PortfolioOut, status_code=201)
def create_portfolio(data: PortfolioIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = Portfolio(user_id=user.id, name=data.name.strip())
    db.add(p)
    db.commit()
    return p


@router.get("/{portfolio_id}", response_model=PortfolioDetail)
def get_portfolio(portfolio_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return detail(db, owned_portfolio(db, user, portfolio_id))


@router.patch("/{portfolio_id}", response_model=PortfolioOut)
def rename_portfolio(
    portfolio_id: int, data: PortfolioIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    p = owned_portfolio(db, user, portfolio_id)
    p.name = data.name.strip()
    db.commit()
    return p


@router.delete("/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(owned_portfolio(db, user, portfolio_id))
    db.commit()


@router.post("/{portfolio_id}/transactions", response_model=TransactionOut, status_code=201)
def add_transaction(
    portfolio_id: int, data: TransactionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    p = owned_portfolio(db, user, portfolio_id)
    sec = db.scalar(select(Security).where(Security.ticker == data.symbol))
    tx = Transaction(portfolio_id=p.id, security_id=sec.id if sec else None, **data.model_dump())
    db.add(tx)
    db.flush()
    db.refresh(p)
    try:
        build_ledger(list(p.transactions))
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    db.commit()
    return tx


@router.delete("/{portfolio_id}/transactions/{tx_id}", status_code=204)
def delete_transaction(
    portfolio_id: int, tx_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    p = owned_portfolio(db, user, portfolio_id)
    tx = db.scalar(select(Transaction).where(Transaction.id == tx_id, Transaction.portfolio_id == p.id))
    if tx is None:
        raise HTTPException(404, "Transaction not found")
    db.delete(tx)
    db.flush()
    db.refresh(p)
    try:
        build_ledger(list(p.transactions))
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(422, f"Cannot delete: {exc}")
    db.commit()


@router.get("/{portfolio_id}/analytics")
def analytics(
    portfolio_id: int,
    base: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = owned_portfolio(db, user, portfolio_id)
    txs = list(p.transactions)
    if base is not None and (len(base) != 3 or not base.isalpha()):
        raise HTTPException(422, "base must be a 3-letter currency code")
    try:
        alloc = pa.allocation(db, txs, base.upper() if base else None)
    except LedgerError as exc:
        raise HTTPException(422, str(exc))

    def fmt(o):
        if isinstance(o, Decimal):
            return format(o, "f")
        if isinstance(o, dict):
            return {str(k): fmt(v) for k, v in o.items()}
        if isinstance(o, list):
            return [fmt(x) for x in o]
        if isinstance(o, date):
            return o.isoformat()
        return o

    return fmt({
        "allocation": alloc,
        "history": pa.value_history(db, txs),
        "returns": pa.returns(db, txs),
        "returns_note": (
            "Time-weighted return (TWR) measures how the investments performed, removing the effect of when you "
            "added or withdrew money; it is linked daily from stored end-of-day closes, with trades valued at their "
            "transaction prices and dividends counted as income. Money-weighted return (XIRR) is your own annualised "
            "return including the timing of your deposits. Per currency, no FX conversion. Days without a complete "
            "valuation are skipped, not estimated."
        ),
        "dividends": pa.dividends(txs),
        "history_note": "Daily value from stored end-of-day closes. Days where any held symbol lacks a close within 7 days are left empty.",
    })


class ImportIn(BaseModel):
    csv: str = Field(min_length=10, max_length=2_000_000)
    default_currency: str = Field("EUR", min_length=3, max_length=3)


IMPORT_ALIASES = {
    "trade_date": ("date", "trade date", "trade_date", "data", "datum"),
    "symbol": ("symbol", "ticker", "isin/ticker", "instrument"),
    "kind": ("type", "kind", "action", "side", "transaction"),
    "quantity": ("quantity", "qty", "shares", "units"),
    "price": ("price", "price per share", "amount", "unit price"),
    "fees": ("fees", "fee", "commission", "costs", "tax"),
    "currency": ("currency", "ccy"),
    "note": ("note", "notes", "comment", "description"),
}
KIND_ALIASES = {"buy": "buy", "b": "buy", "purchase": "buy", "sell": "sell", "s": "sell", "sale": "sell",
                "dividend": "dividend", "div": "dividend", "dividends": "dividend"}


def _num(raw: str) -> str:
    """Accept 1234.5, 1,234.5, 1234,5 and 1.234,5; reject ambiguous 1,234 / 1.234 style values."""
    v = raw.replace(" ", "").replace("\u00a0", "")
    if not v:
        return "0"
    if "," in v and "." in v:
        return v.replace(",", "") if v.rfind(".") > v.rfind(",") else v.replace(".", "").replace(",", ".")
    if "," in v:
        head, _, tail = v.rpartition(",")
        if len(tail) == 3 and head.lstrip("-").isdigit() and v.count(",") == 1:
            raise ValueError(f"ambiguous number '{raw}' (thousands or decimal separator?)")
        return v.replace(",", ".") if v.count(",") == 1 else v.replace(",", "")
    return v


@router.post("/{portfolio_id}/import")
def import_transactions(portfolio_id: int, data: ImportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """All-or-nothing import of a transactions CSV (header row required)."""
    import csv
    import io

    from pydantic import ValidationError

    p = owned_portfolio(db, user, portfolio_id)
    try:
        dialect = csv.Sniffer().sniff(data.csv[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(data.csv), dialect)
    header = [h.strip().lower().lstrip("\ufeff") for h in next(reader, [])]
    cols = {k: next((i for i, h in enumerate(header) if h in aliases), None) for k, aliases in IMPORT_ALIASES.items()}
    if any(cols[k] is None for k in ("trade_date", "symbol", "kind", "price")):
        raise HTTPException(422, "CSV header needs at least: date, symbol, type, price (and quantity for buys/sells).")
    parsed, errors = [], []
    for n, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue

        def col(k, default=""):
            i = cols[k]
            return row[i].strip() if i is not None and i < len(row) else default

        kind = KIND_ALIASES.get(col("kind").lower())
        if kind is None:
            errors.append(f"line {n}: unknown type '{col('kind')}'")
            continue
        try:
            q_, pr_, fe_ = _num(col("quantity")), _num(col("price")), _num(col("fees"))
        except ValueError as exc:
            errors.append(f"line {n}: {exc}")
            continue
        try:
            tx = TransactionIn(symbol=col("symbol"), kind=kind, trade_date=col("trade_date")[:10], quantity=q_, price=pr_, fees=fe_,
                               currency=col("currency") or data.default_currency, note=col("note")[:2000])
        except ValidationError as exc:
            errors.append(f"line {n}: {exc.errors()[0]['msg'].replace('Value error, ', '')}")
            continue
        parsed.append(tx)
        if len(errors) > 20:
            break
    if errors:
        raise HTTPException(422, "Nothing imported. " + "; ".join(errors[:10]))
    if not parsed:
        raise HTTPException(422, "No transactions found in the file.")
    if len(parsed) > 5000:
        raise HTTPException(422, "Too many rows (max 5000 per import).")
    secs = {s.ticker: s.id for s in db.scalars(select(Security).where(Security.ticker.in_({t.symbol for t in parsed})))}
    for t in parsed:
        db.add(Transaction(portfolio_id=p.id, security_id=secs.get(t.symbol), **t.model_dump()))
    db.flush()
    db.refresh(p)
    try:
        build_ledger(list(p.transactions))
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(422, f"Nothing imported: {exc}")
    db.commit()
    return {"imported": len(parsed)}
