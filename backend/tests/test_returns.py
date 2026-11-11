"""Time-weighted and money-weighted returns, checked against hand calculations."""

from datetime import date
from decimal import Decimal

from app.services import portfolio_analytics as pa

from .conftest import HDR


def q(v, places="0.0001"):
    return Decimal(str(v)).quantize(Decimal(places))


def setup(admin_client, closes: dict[str, float], symbol="AAPL"):
    csv = "Date,Close\n" + "\n".join(f"{d},{c}" for d, c in closes.items())
    r = admin_client.post(f"/api/admin/prices/{symbol}/import", json={"csv": csv, "source": "test", "currency": "USD"}, headers=HDR)
    assert r.status_code == 200, r.text
    p = admin_client.post("/api/portfolios", json={"name": "R"}, headers=HDR).json()
    return p["id"]


def tx(admin_client, pid, **kw):
    body = {"symbol": "AAPL", "currency": "USD", "quantity": "0", "fees": "0", **kw}
    r = admin_client.post(f"/api/portfolios/{pid}/transactions", json=body, headers=HDR)
    assert r.status_code == 201, r.text


def rets(admin_client, pid):
    return admin_client.get(f"/api/portfolios/{pid}/analytics").json()["returns"]["USD"]


def test_twr_ignores_deposit_timing(admin_client, seeded):
    # Price +10% per day. Buying more on day 2 must not change the TWR: it equals the price return (21%).
    pid = setup(admin_client, {"2024-01-02": 100, "2024-01-03": 110, "2024-01-04": 121})
    tx(admin_client, pid, kind="buy", trade_date="2024-01-02", quantity="10", price="100")
    tx(admin_client, pid, kind="buy", trade_date="2024-01-03", quantity="10", price="110")
    r = rets(admin_client, pid)
    assert q(r["twr_total"]) == Decimal("0.2100")
    assert [q(p["twr"]) for p in r["series"]] == [Decimal("0"), Decimal("0.1000"), Decimal("0.2100")]
    assert r["twr_annualised"] is None  # less than a year: not annualised
    assert r["gaps"] == 0


def test_twr_fees_dividends_and_full_exit(admin_client, seeded):
    pid = setup(admin_client, {"2024-01-02": 100, "2024-01-03": 100, "2024-01-04": 100, "2024-01-05": 100})
    tx(admin_client, pid, kind="buy", trade_date="2024-01-02", quantity="10", price="100", fees="10")  # day 1: 1000/1010 − 1
    tx(admin_client, pid, kind="dividend", trade_date="2024-01-03", price="20")  # day 2: (1000 + 20)/1000 − 1 = 2%
    tx(admin_client, pid, kind="sell", trade_date="2024-01-04", quantity="10", price="100", fees="5")  # day 3: (0 + 995)/1000 − 1
    r = rets(admin_client, pid)
    expected = (Decimal(1000) / Decimal(1010)) * Decimal("1.02") * Decimal("0.995") - 1
    assert q(r["twr_total"], "0.000001") == q(expected, "0.000001")
    assert r["series"][-1]["date"] == "2024-01-04"  # the exit day is valued at 0 and ends the exposure


def test_twr_skips_gaps_without_inventing_values(admin_client, seeded):
    # MSFT has no close between 01-02 and 01-20, so 01-12 (10 days stale) cannot be valued and is skipped.
    csv = "Date,Close\n2024-01-02,100\n2024-01-20,110\n"
    admin_client.post("/api/admin/prices/MSFT/import", json={"csv": csv, "source": "test", "currency": "USD"}, headers=HDR)
    pid = setup(admin_client, {"2024-01-02": 50, "2024-01-12": 60, "2024-01-20": 55})
    tx(admin_client, pid, kind="buy", trade_date="2024-01-02", quantity="10", price="50")
    tx(admin_client, pid, kind="buy", trade_date="2024-01-02", symbol="MSFT", quantity="5", price="100")
    r = rets(admin_client, pid)
    assert r["gaps"] == 1
    assert [p["date"] for p in r["series"]] == ["2024-01-02", "2024-01-20"]
    assert q(r["twr_total"]) == Decimal("0.1000")  # 1000 -> 1100, chained straight across the gap


def test_xirr_and_annualised_periods():
    flows = [(date(2023, 1, 1), Decimal(-1000)), (date(2024, 1, 1), Decimal(1100))]
    assert q(pa.xirr(flows)) == Decimal("0.1000")
    assert pa.xirr([(date(2023, 1, 1), Decimal(-1000))]) is None  # no positive flow -> undefined
    pts = [{"date": date(2023, 12, 29), "twr": Decimal("0.10")}, {"date": date(2024, 6, 30), "twr": Decimal("0.21")}]
    assert q(pa._period(pts, date(2024, 1, 1))) == Decimal("0.1000")  # (1.21 / 1.10) − 1
    assert pa._period(pts, date(2023, 1, 1)) is None  # history does not reach back that far


def test_money_weighted_differs_from_time_weighted(admin_client, seeded):
    # A big deposit right before a fall: TWR reflects the investment, XIRR reflects the investor's timing.
    closes = {"2023-01-02": 100, "2023-07-03": 150, "2024-01-02": 120}
    pid = setup(admin_client, closes)
    tx(admin_client, pid, kind="buy", trade_date="2023-01-02", quantity="1", price="100")
    tx(admin_client, pid, kind="buy", trade_date="2023-07-03", quantity="10", price="150")
    r = rets(admin_client, pid)
    assert q(r["twr_total"]) == Decimal("0.2000")  # 100 -> 150 -> 120
    assert Decimal(r["mwr_annualised"]) < 0  # most money went in at 150 and is now worth 120
    assert r["twr_annualised"] is not None and r["days"] == 365
