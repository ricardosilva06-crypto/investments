from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from app import db
from app.models import FxRate, Security
from app.services import screener, sec_client
from app.services import valuation as dcf

from .conftest import HDR, SEC_SAMPLE
from .fixtures import CIK, COMPANYFACTS, SUBMISSIONS


def frame(rows):
    return {"taxonomy": "us-gaap", "data": [{"accn": f"000-{i}", "cik": c, "entityName": n, "loc": "US-CA", "end": e, "val": v}
                                             for i, (c, n, e, v) in enumerate(rows)]}


FRAMES = {
    ("Revenues", "CY2024"): [(320193, "Apple Inc.", "2024-09-28", 391_035_000_000), (789019, "MICROSOFT CORP", "2024-06-30", 245_122_000_000)],
    ("Revenues", "CY2023"): [(320193, "Apple Inc.", "2023-09-30", 383_285_000_000), (789019, "MICROSOFT CORP", "2023-06-30", 211_915_000_000)],
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "CY2024"): [(1018724, "AMAZON COM INC", "2024-12-31", 637_959_000_000)],
    ("NetIncomeLoss", "CY2024"): [(320193, "Apple Inc.", "2024-09-28", 93_736_000_000), (789019, "MICROSOFT CORP", "2024-06-30", 88_136_000_000),
                                  (1018724, "AMAZON COM INC", "2024-12-31", 59_248_000_000)],
    ("StockholdersEquity", "CY2024Q4I"): [(320193, "Apple Inc.", "2024-09-28", 56_950_000_000), (789019, "MICROSOFT CORP", "2024-06-30", 268_477_000_000)],
}
# Note: synthetic test values shaped like SEC frames; used only to exercise the code.


@pytest.fixture()
def sec_frames(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        parts = req.url.path.split("/")
        if "frames" in parts:
            concept, period = parts[-3], parts[-1].removesuffix(".json")
            rows = FRAMES.get((concept, period))
            return httpx.Response(200, json=frame(rows)) if rows else httpx.Response(404)
        if "companyfacts" in req.url.path:
            return httpx.Response(200, json=COMPANYFACTS)
        if "submissions" in req.url.path:
            return httpx.Response(200, json=SUBMISSIONS)
        return httpx.Response(404)

    monkeypatch.setattr(sec_client, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(sec_client, "_MIN_INTERVAL", 0)
    return calls


def test_screener_sync_and_filters(admin_client, seeded, sec_frames):
    assert admin_client.get("/api/screener").json()["items"] == []
    r = admin_client.post("/api/admin/screener/sync", params={"year": 2024}, headers=HDR)
    assert r.status_code == 200, r.text
    assert len(sec_frames) == len(screener.plan(2024))  # one request per concept/period, no more
    d = admin_client.get("/api/screener", params={"sort": "revenue"}).json()
    assert d["year"] == 2024 and d["coverage"] == 3
    assert [i["ticker"] for i in d["items"]] == ["AMZN", "AAPL", "MSFT"]  # revenue concept fallback for AMZN
    aapl = next(i for i in d["items"] if i["ticker"] == "AAPL")
    assert Decimal(aapl["values"]["revenue_growth"]).quantize(Decimal("0.0001")) == Decimal("0.0202")
    assert Decimal(aapl["values"]["roe"]).quantize(Decimal("0.01")) == Decimal("1.65")
    assert aapl["values"]["pe"] is None  # no stored price -> no P/E
    f = admin_client.get("/api/screener", params={"min_revenue_growth": "0.1"}).json()
    assert [i["ticker"] for i in f["items"]] == ["MSFT"]  # AMZN has no prior year -> unknown never passes
    f2 = admin_client.get("/api/screener", params={"max_roe": "1", "sort": "net_margin", "order": "asc"}).json()
    assert [i["ticker"] for i in f2["items"]] == ["MSFT"]
    assert admin_client.get("/api/screener", params={"sort": "nope"}).status_code == 422


def test_dcf_math():
    i = dcf.DCFInputs(base_fcf=Decimal(100), growth_stage1=Decimal("0.10"), years_stage1=2, years_stage2=0,
                      terminal_growth=Decimal("0.02"), discount_rate=Decimal("0.10"), net_cash=Decimal(50), shares=Decimal(10))
    r = dcf.value(i)
    # FCF1=110, FCF2=121; PV = 100 + 100 ; TV = 121*1.02/0.08 = 1542.75 ; PV TV = 1542.75/1.21 = 1275
    assert r["pv_fcf"].quantize(Decimal("0.01")) == Decimal("200.00")
    assert r["pv_terminal"].quantize(Decimal("0.01")) == Decimal("1275.00")
    assert r["per_share"].quantize(Decimal("0.01")) == Decimal("152.50")
    with pytest.raises(dcf.DCFError):
        dcf.value(dcf.DCFInputs(**{**i.__dict__, "discount_rate": Decimal("0.02")}))
    s = dcf.sensitivity(i)
    assert s["per_share"][2][2].quantize(Decimal("0.01")) == Decimal("152.50")
    # fade: growth moves linearly from stage 1 to terminal
    rows = dcf.project(dcf.DCFInputs(**{**i.__dict__, "years_stage2": 3}))
    assert [r["growth"].quantize(Decimal("0.001")) for r in rows][2:] == [Decimal("0.080"), Decimal("0.060"), Decimal("0.040")]


@pytest.fixture()
def example(app_env, sec_frames):
    s = db.session_factory()()
    s.add(Security(ticker="EXMP", name="EXAMPLE CORP", cik=CIK, exchange="Nasdaq", source="test"))
    s.commit()
    s.close()


def test_dcf_inputs_endpoint_and_saving(admin_client, example):
    d = admin_client.get("/api/companies/EXMP/dcf-inputs").json()
    f = d["fields"]
    assert Decimal(f["base_fcf"]["value"]) == 200 and f["base_fcf"]["kind"] == "calculated"
    assert f["discount_rate"]["kind"] == "assumption" and f["terminal_growth"]["kind"] == "assumption"
    assert f["shares"]["kind"] == "missing" and f["shares"]["value"] is None  # never invented
    assert Decimal(f["net_cash"]["value"]) == 0 and "not reported" in f["net_cash"]["source"]
    assert d["price"] is None
    body = {"base_fcf": "200", "growth_stage1": "0.05", "years_stage1": 5, "years_stage2": 5, "terminal_growth": "0.025",
            "discount_rate": "0.09", "net_cash": "0", "shares": "100"}
    r = admin_client.post("/api/valuation/dcf", json=body, headers=HDR).json()
    assert Decimal(r["result"]["per_share"]) > 0 and len(r["sensitivity"]["per_share"]) == 5
    assert Decimal(r["result"]["terminal_share"]) > Decimal("0.5")
    bad = admin_client.post("/api/valuation/dcf", json={**body, "discount_rate": "0.02"}, headers=HDR)
    assert bad.status_code == 422
    sv = admin_client.post("/api/valuations", json={"ticker": "EXMP", "name": "Base case", "inputs": body}, headers=HDR)
    assert sv.status_code == 201
    lst = admin_client.get("/api/valuations", params={"ticker": "EXMP"}).json()
    assert lst[0]["name"] == "Base case" and lst[0]["inputs"]["shares"] == "100.000000"


def test_compare(admin_client, example):
    s = db.session_factory()()
    s.add(Security(ticker="EXM2", name="EXAMPLE TWO", cik=CIK, exchange="NYSE", source="test"))
    s.commit()
    s.close()
    assert admin_client.get("/api/compare", params={"tickers": "EXMP"}).status_code == 422
    d = admin_client.get("/api/compare", params={"tickers": "EXMP,EXM2"}).json()
    assert [c["ticker"] for c in d["companies"]] == ["EXMP", "EXM2"]
    c = d["companies"][0]
    assert Decimal(c["fields"]["revenue"]["value"]) == 1200 and c["fields"]["fcf"]["derived"]
    assert [h["end"] for h in c["history"]] == ["2022-12-31", "2023-12-31", "2024-12-31"]
    assert c["pe"] is None


def test_portfolio_analytics_and_dividends(admin_client, seeded):
    csv = "Date,Close\n" + "\n".join(f"{(date(2024, 1, 1) + timedelta(days=i)).isoformat()},{100 + i}" for i in range(0, 30))
    admin_client.post("/api/admin/prices/AAPL/import", json={"csv": csv, "source": "test", "currency": "USD"}, headers=HDR)
    p = admin_client.post("/api/portfolios", json={"name": "P"}, headers=HDR).json()
    tx = f"/api/portfolios/{p['id']}/transactions"
    admin_client.post(tx, json={"symbol": "AAPL", "currency": "USD", "kind": "buy", "trade_date": "2024-01-05", "quantity": "10", "price": "100"}, headers=HDR)
    admin_client.post(tx, json={"symbol": "ASML.AS", "currency": "EUR", "kind": "buy", "trade_date": "2024-01-05", "quantity": "1", "price": "600"}, headers=HDR)
    today = date.today()
    admin_client.post(tx, json={"symbol": "AAPL", "currency": "USD", "kind": "dividend", "trade_date": (today - timedelta(days=30)).isoformat(), "price": "2.5", "fees": "0.5"}, headers=HDR)
    admin_client.post(tx, json={"symbol": "AAPL", "currency": "USD", "kind": "dividend", "trade_date": "2020-03-01", "price": "1"}, headers=HDR)
    a = admin_client.get(f"/api/portfolios/{p['id']}/analytics").json()
    items = {i["symbol"]: i for i in a["allocation"]["items"]}
    assert items["AAPL"]["basis"] == "market" and Decimal(items["AAPL"]["value"]) == Decimal("1290.00")  # 10 x last close 129
    assert items["ASML.AS"]["basis"] == "cost"
    hist = a["history"]["USD"]
    assert hist[0]["date"] == "2024-01-05" and Decimal(hist[0]["value"]) == Decimal("1040.00")
    assert "EUR" not in a["history"]  # no EUR prices -> no invented history
    dv = a["dividends"]
    assert Decimal(dv["ttm_by_currency"]["USD"]) == Decimal("2.0")
    aapl = next(s for s in dv["by_symbol"] if s["symbol"] == "AAPL")
    assert Decimal(aapl["total"]) == Decimal("3.0") and Decimal(aapl["yield_on_cost"]) == Decimal("0.002")
    assert [y["year"] for y in dv["by_year"]["USD"]] == [2020, today.year if (today - timedelta(days=30)).year == today.year else today.year - 1]
    # Base-currency conversion needs ECB rates; missing -> explicit error, not a guess.
    b = admin_client.get(f"/api/portfolios/{p['id']}/analytics", params={"base": "EUR"}).json()
    assert "No ECB rate" in b["allocation"]["base"]["error"]
    s = db.session_factory()()
    s.add(FxRate(currency="USD", day=date(2024, 12, 31), value=Decimal("1.25")))
    s.commit()
    s.close()
    b = admin_client.get(f"/api/portfolios/{p['id']}/analytics", params={"base": "EUR"}).json()["allocation"]["base"]
    assert Decimal(b["total"]) == Decimal("1632") and b["rate_date"] == "2024-12-31" and b["includes_cost_basis"] is True


def test_transaction_csv_import(admin_client):
    p = admin_client.post("/api/portfolios", json={"name": "Imp"}, headers=HDR).json()
    url = f"/api/portfolios/{p['id']}/import"
    good = "Date;Symbol;Type;Quantity;Price;Fees;Currency\n2024-01-02;ASML.AS;Buy;2;600,50;1,5;EUR\n2024-03-01;ASML.AS;Div;0;3,20;0;EUR\n"
    r = admin_client.post(url, json={"csv": good}, headers=HDR)
    assert r.status_code == 200 and r.json()["imported"] == 2
    d = admin_client.get(f"/api/portfolios/{p['id']}").json()
    assert Decimal(d["open_positions"][0]["cost_basis"]) == Decimal("1202.5")
    bad = "Date,Symbol,Type,Quantity,Price\n2024-01-02,AAA,buy,1,10\n2024-01-03,AAA,sell,5,10\n"
    r = admin_client.post(url, json={"csv": bad}, headers=HDR)
    assert r.status_code == 422 and "Nothing imported" in r.json()["detail"]
    amb = "Date,Symbol,Type,Quantity,Price\n2024-01-02,AAA,buy,1,\"1,234\"\n"
    r = admin_client.post(url, json={"csv": amb}, headers=HDR)
    assert r.status_code == 422 and "ambiguous" in r.json()["detail"]
    assert len(admin_client.get(f"/api/portfolios/{p['id']}").json()["transactions"]) == 2  # all-or-nothing


def test_valuations_private(admin_client, example):
    from fastapi.testclient import TestClient

    from app.main import app

    from .conftest import login, make_user

    body = {"base_fcf": "200", "growth_stage1": "0.05", "years_stage1": 5, "years_stage2": 5, "terminal_growth": "0.025",
            "discount_rate": "0.09", "net_cash": "0", "shares": "100"}
    vid = admin_client.post("/api/valuations", json={"ticker": "EXMP", "inputs": body}, headers=HDR).json()["id"]
    make_user("mallory")
    with TestClient(app) as m:
        login(m, "mallory")
        assert m.get("/api/valuations").json() == []
        assert m.delete(f"/api/valuations/{vid}", headers=HDR).status_code == 404
