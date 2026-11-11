"""Position accounting from user-entered transactions (average-cost method).

Only the user's own transactions are used. No market prices are involved, so
no market value or unrealised P/L is computed here; that requires a price
source (Phase 2) and will always carry the price's timestamp.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from ..models import Transaction

ZERO = Decimal(0)


class LedgerError(ValueError):
    pass


@dataclass
class Position:
    symbol: str
    currency: str
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO  # includes buy fees
    realized_pl: Decimal = ZERO  # net of sell fees
    dividends: Decimal = ZERO
    fees: Decimal = ZERO
    first_trade: str | None = None
    transactions: int = 0
    security_id: int | None = None

    @property
    def average_cost(self) -> Decimal | None:
        return (self.cost_basis / self.quantity) if self.quantity > 0 else None


@dataclass
class Ledger:
    positions: dict[tuple[str, str], Position] = field(default_factory=dict)


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0000000001")).normalize()


def build_ledger(transactions: list[Transaction]) -> Ledger:
    ledger = Ledger()
    ordered = sorted(transactions, key=lambda t: (t.trade_date, t.id or 0))
    for t in ordered:
        key = (t.symbol.upper(), t.currency.upper())
        pos = ledger.positions.setdefault(key, Position(symbol=key[0], currency=key[1]))
        pos.transactions += 1
        pos.security_id = pos.security_id or t.security_id
        pos.first_trade = pos.first_trade or t.trade_date.isoformat()
        pos.fees += t.fees
        if t.kind == "buy":
            pos.quantity += t.quantity
            pos.cost_basis += t.quantity * t.price + t.fees
        elif t.kind == "sell":
            if t.quantity > pos.quantity:
                raise LedgerError(
                    f"Sell of {t.quantity} {t.symbol} on {t.trade_date} exceeds the {pos.quantity} held at that date"
                )
            avg = pos.cost_basis / pos.quantity
            removed_cost = avg * t.quantity
            pos.realized_pl += t.quantity * t.price - t.fees - removed_cost
            pos.quantity -= t.quantity
            pos.cost_basis -= removed_cost
            if pos.quantity == 0:
                pos.cost_basis = ZERO
        elif t.kind == "dividend":
            # For dividends ``price`` holds the total cash amount received.
            pos.dividends += t.price - t.fees
        else:  # pragma: no cover - validated at input
            raise LedgerError(f"Unknown transaction kind {t.kind}")
    for pos in ledger.positions.values():
        pos.cost_basis, pos.realized_pl, pos.dividends = _q(pos.cost_basis), _q(pos.realized_pl), _q(pos.dividends)
    return ledger
