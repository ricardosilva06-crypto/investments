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
