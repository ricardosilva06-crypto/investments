from decimal import Decimal

import httpx
import pytest

from app import db
from app.models import Security
from app.services import ecb, prices, sec_client

from .conftest import HDR, login, make_user
from .fixtures import CIK, COMPANYFACTS, ECB_CSV, SUBMISSIONS, TIINGO


@pytest.fixture()
def sec_mock(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        assert "@" in request.headers["user-agent"]
        if "companyfacts" in request.url.path:
            return httpx.Response(200, json=COMPANYFACTS)
        if "submissions" in request.url.path:
            return httpx.Response(200, json=SUBMISSIONS)
        return httpx.Response(404)

    monkeypatch.setattr(sec_client, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(sec_client, "_MIN_INTERVAL", 0)
    return calls


@pytest.fixture()
def example(app_env):
    s = db.session_factory()()
    s.add(Security(ticker="EXMP", name="EXAMPLE CORP", cik=CIK, exchange="Nasdaq", source="test"))
    s.commit()
    s.close()


def rows(data):
    return {r["key"]: r["values"] for r in data["rows"]}


def test_company_profile_and_cache(admin_client, example, sec_mock):
    r = admin_client.get("/api/companies/exmp")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["profile"]["sic_description"] == "Services-Prepackaged Software"
    assert d["profile"]["business_address"].startswith("1 Example Way")
    assert d["has_financials"] and d["currency"] == "USD"
    assert {f["status"] for f in d["freshness"]} == {"ok"}
    assert len(sec_mock) == 2
    admin_client.get("/api/companies/EXMP")
    assert len(sec_mock) == 2  # served from the local database, no new SEC requests
    figs = {k["key"]: k for k in d["key_figures"]}
    assert Decimal(figs["revenue"]["value"]) == 1200 and figs["revenue"]["form"] == "10-K"
    assert figs["fcf"]["derived"] and Decimal(figs["fcf"]["value"]) == 200
    assert d["quote"] is None  # no prices stored, none invented


def test_annual_income_restatement_and_fallback(admin_client, example, sec_mock):
    admin_client.get("/api/companies/EXMP")
    d = admin_client.get("/api/companies/EXMP/financials", params={"statement": "income"}).json()
    assert [p["end"] for p in d["periods"]] == ["2024-12-31", "2023-12-31", "2022-12-31"]
    rev = rows(d)["revenue"]
    assert [Decimal(c["value"]) for c in rev] == [1200, 1010, 900]
    assert rev[1]["filed"] == "2025-02-15"  # restated value from the later filing
    assert rev[2]["concept"] == "us-gaap:SalesRevenueNet"  # concept fallback
    assert rev[0]["url"].endswith("/1234567/000123456725000010/")
    assert not any(c["derived"] for c in rev)
    assert "cost_of_revenue" not in rows(d)  # never reported -> not shown, not invented


def test_quarterly_derivation(admin_client, example, sec_mock):
    admin_client.get("/api/companies/EXMP")
    inc = admin_client.get("/api/companies/EXMP/financials", params={"statement": "income", "period": "quarterly"}).json()
    assert [p["label"].split(" ")[0] for p in inc["periods"]] == ["Q4", "Q3", "Q2", "Q1"]
    rev = rows(inc)["revenue"]
    assert [Decimal(c["value"]) for c in rev] == [340, 310, 300, 250]
    assert rev[0]["derived"] and "12-month" in rev[0]["formula"]
    assert not rev[1]["derived"]
    eps = rows(inc)["eps_diluted"]
    assert eps[0] is None and Decimal(eps[3]["value"]) == Decimal("0.25")  # EPS is never derived by subtraction
    cf = admin_client.get("/api/companies/EXMP/financials", params={"statement": "cashflow", "period": "quarterly"}).json()
    cfo = rows(cf)["cfo"]
    assert [Decimal(c["value"]) for c in cfo] == [80, 70, 60, 50]
    assert [c["derived"] for c in cfo] == [True, True, True, False]


def test_balance_and_metrics(admin_client, example, sec_mock):
    admin_client.get("/api/companies/EXMP")
    bal = rows(admin_client.get("/api/companies/EXMP/financials", params={"statement": "balance"}).json())
    assert Decimal(bal["total_assets"][0]["value"]) == 5000 and Decimal(bal["total_assets"][1]["value"]) == 4500
    m = rows(admin_client.get("/api/companies/EXMP/financials", params={"statement": "metrics"}).json())
    assert Decimal(m["revenue_growth"][0]["value"]) == Decimal("0.188119")
    assert Decimal(m["net_margin"][0]["value"]) == Decimal("0.1")
    assert Decimal(m["roe"][0]["value"]) == Decimal("0.06")
    assert Decimal(m["current_ratio"][0]["value"]) == Decimal("1.5")
    assert all(c is None or c["derived"] for c in m["net_margin"])


def test_filings(admin_client, example, sec_mock):
    admin_client.get("/api/companies/EXMP")
    f = admin_client.get("/api/companies/EXMP/filings").json()
    assert [x["form"] for x in f] == ["10-K", "10-Q"]  # Form 4 filtered from key forms
    assert f[0]["url"] == "https://www.sec.gov/Archives/edgar/data/1234567/000123456725000010/exmp-20241231.htm"
    assert len(admin_client.get("/api/companies/EXMP/filings", params={"forms": "all"}).json()) == 3


def test_sec_error_is_reported_not_hidden(admin_client, example, monkeypatch):
    monkeypatch.setattr(sec_client, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    monkeypatch.setattr(sec_client, "_MIN_INTERVAL", 0)
    d = admin_client.get("/api/companies/EXMP").json()
    assert "503" in d["errors"]["sec_companyfacts"]
    assert d["has_financials"] is False and d["key_figures"] == []


def test_csv_import_and_quotes(admin_client, example, seeded):
    csv_text = "Date;Open;High;Low;Close;Volume\n2024-12-30;10;11;9,5;10,50;1000\n2024-12-31;10.5;12;10;11.55;1200\n"
    r = admin_client.post("/api/admin/prices/AAPL/import", json={"csv": csv_text, "source": "My broker", "currency": "USD"}, headers=HDR)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2
    p = admin_client.get("/api/prices/AAPL").json()
    assert p["last_date"] == "2024-12-31" and p["sources"] == ["CSV import: My broker"]
    assert p["provider_configured"] is False and "not real-time" in p["note"]
    wl = admin_client.get("/api/watchlists").json()[0]
    admin_client.post(f"/api/watchlists/{wl['id']}/items", json={"ticker": "AAPL"}, headers=HDR)
    q = admin_client.get("/api/watchlists").json()[0]["items"][0]["quote"]
    assert Decimal(q["close"]) == Decimal("11.55") and q["date"] == "2024-12-31"
    assert Decimal(q["change_pct"]) == Decimal("0.1")
    bad = admin_client.post("/api/admin/prices/AAPL/import", json={"csv": "foo,bar\n1,2\n", "source": "x1", "currency": "USD"}, headers=HDR)
    assert bad.status_code == 422


def test_csv_import_admin_only(admin_client, app_env):
    from fastapi.testclient import TestClient

    from app.main import app

    make_user("bob")
    with TestClient(app) as c:
        login(c, "bob")
        r = c.post("/api/admin/prices/AAPL/import", json={"csv": "Date,Close\n2024-01-02,1\n", "source": "x1", "currency": "USD"}, headers=HDR)
        assert r.status_code == 403


def test_portfolio_valuation_uses_stored_close(admin_client, seeded):
    admin_client.post("/api/admin/prices/AAPL/import", json={"csv": "Date,Close\n2024-12-31,200\n", "source": "test", "currency": "USD"}, headers=HDR)
    p = admin_client.post("/api/portfolios", json={"name": "P"}, headers=HDR).json()
    url = f"/api/portfolios/{p['id']}/transactions"
    admin_client.post(url, json={"symbol": "AAPL", "currency": "USD", "kind": "buy", "trade_date": "2024-01-02", "quantity": "10", "price": "150"}, headers=HDR)
    admin_client.post(url, json={"symbol": "MSFT", "currency": "EUR", "kind": "buy", "trade_date": "2024-01-02", "quantity": "1", "price": "300"}, headers=HDR)
    d = admin_client.get(f"/api/portfolios/{p['id']}").json()
    pos = {x["symbol"]: x for x in d["open_positions"]}
    assert Decimal(pos["AAPL"]["market_value"]) == 2000 and Decimal(pos["AAPL"]["unrealized_pl"]) == 500
    assert pos["AAPL"]["last_close_date"] == "2024-12-31"
    assert pos["MSFT"]["market_value"] is None
    usd = next(t for t in d["totals_by_currency"] if t["currency"] == "USD")
    eur = next(t for t in d["totals_by_currency"] if t["currency"] == "EUR")
    assert Decimal(usd["market_value"]) == 2000
    assert eur["market_value"] is None  # incomplete pricing -> no total rather than a misleading one


def test_tiingo_provider_and_budget(admin_client, monkeypatch, app_env):
    from app import config

    monkeypatch.setenv("II_TIINGO_API_KEY", "dummy-key")
    monkeypatch.setenv("II_TIINGO_MAX_PER_HOUR", "1")
    config.get_settings.cache_clear()
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["authorization"] == "Token dummy-key"
        return httpx.Response(200, json=TIINGO)

    monkeypatch.setattr(prices, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    p = admin_client.get("/api/prices/brk.b").json()
    assert seen[0].url.path == "/tiingo/daily/brk-b/prices"
    assert p["last_date"] == "2024-12-31" and p["sources"] == ["Tiingo (end of day)"]
    admin_client.get("/api/prices/BRK.B")
    assert len(seen) == 1  # cached for 12 hours
    p2 = admin_client.get("/api/prices/MSFT").json()
    assert "budget" in p2["error"] and p2["bars"] == []  # hourly budget of 1 respected
    assert len(seen) == 1


def test_ecb_fx(admin_client, monkeypatch):
    monkeypatch.setattr(ecb, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=ECB_CSV))))
    d = admin_client.get("/api/fx").json()
    rates = {r["currency"]: r for r in d["rates"]}
    assert rates["USD"]["value"] == "1.0389" and rates["USD"]["date"] == "2024-12-31"
    assert Decimal(rates["USD"]["change_pct"]) < 0
    assert "JPY" not in rates  # empty observation skipped, not filled
    assert d["status"] == "ok"
    h = admin_client.get("/api/fx/usd").json()
    assert len(h["points"]) == 2
