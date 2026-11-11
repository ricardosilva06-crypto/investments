from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import HDR, SEC_SAMPLE, login, make_user


def test_sec_parse_skips_incomplete_rows():
    from app.services.sec import parse_payload

    rows = parse_payload(SEC_SAMPLE)
    assert {r["ticker"] for r in rows} == {"AAPL", "MSFT", "AMZN", "BRK-B", "BRK-A"}


def test_sec_sync_with_mock_transport(admin_client, app_env):
    from app import db
    from app.services import sec

    seen = {}

    def handler(request: httpx.Request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json=SEC_SAMPLE)

    s = db.session_factory()()
    row = sec.sync_securities(s, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert row.status == "ok" and row.record_count == 5
    assert "@" in seen["ua"]
    # Second sync inside the minimum interval is refused (fair use of SEC).
    with pytest.raises(sec.SyncError):
        sec.sync_securities(s, client=httpx.Client(transport=httpx.MockTransport(handler)))
    # Delisted tickers are flagged, not deleted.
    smaller = {"fields": SEC_SAMPLE["fields"], "data": SEC_SAMPLE["data"][:2]}
    sec.sync_securities(s, force=True, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=smaller))))
    s.close()
    r = admin_client.get("/api/securities", params={"q": "amazon"}).json()
    assert r["items"] == []


def test_sec_error_recorded(admin_client):
    from app import db
    from app.services import sec

    s = db.session_factory()()
    with pytest.raises(sec.SyncError):
        sec.sync_securities(s, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
    s.close()
    src = admin_client.get("/api/system/status").json()["data_sources"][0]
    assert src["status"] == "error" and "403" in src["message"]


def test_search_ranking(admin_client, seeded):
    hits = admin_client.get("/api/search", params={"q": "ms"}).json()
    assert hits[0]["title"] == "MSFT"
    page = admin_client.get("/api/securities", params={"exchange": "NYSE"}).json()
    assert page["total"] == 2
    ex = admin_client.get("/api/securities/exchanges").json()
    assert ex[0] == {"exchange": "Nasdaq", "count": 3}
    detail = admin_client.get("/api/securities/aapl").json()
    assert detail["security"]["cik"] == 320193 and "0000320193" in detail["edgar_url"]
    # LIKE wildcards are escaped.
    assert admin_client.get("/api/securities", params={"q": "%"}).json()["total"] == 0


def test_watchlist_isolation(admin_client, seeded, app_env):
    from app.main import app

    wl = admin_client.get("/api/watchlists").json()[0]
    r = admin_client.post(f"/api/watchlists/{wl['id']}/items", json={"ticker": "aapl"}, headers=HDR)
    assert r.status_code == 201
    assert admin_client.post(f"/api/watchlists/{wl['id']}/items", json={"ticker": "AAPL"}, headers=HDR).status_code == 409
    assert admin_client.post(f"/api/watchlists/{wl['id']}/items", json={"ticker": "ZZZZ"}, headers=HDR).status_code == 404

    make_user("mallory")
    with TestClient(app) as m:
        login(m, "mallory")
        mine = m.get("/api/watchlists").json()
        assert len(mine) == 1 and mine[0]["items"] == []
        assert m.delete(f"/api/watchlists/{wl['id']}", headers=HDR).status_code == 404
        assert m.post(f"/api/watchlists/{wl['id']}/items", json={"ticker": "MSFT"}, headers=HDR).status_code == 404
        assert all(h["type"] == "security" for h in m.get("/api/search", params={"q": "my"}).json() if h["type"] != "watchlist")


def test_notes_isolation(admin_client, seeded, app_env):
    from app.main import app

    n = admin_client.post("/api/notes", json={"title": "AAPL thesis", "body": "secret", "ticker": "AAPL"}, headers=HDR).json()
    assert n["security"]["ticker"] == "AAPL"
    make_user("mallory")
    with TestClient(app) as m:
        login(m, "mallory")
        assert m.get(f"/api/notes/{n['id']}").status_code == 404
        assert m.get("/api/notes").json() == []
        assert not [h for h in m.get("/api/search", params={"q": "thesis"}).json() if h["type"] == "note"]
    assert [h for h in admin_client.get("/api/search", params={"q": "thesis"}).json() if h["type"] == "note"]


def test_portfolio_ledger(admin_client, seeded):
    p = admin_client.post("/api/portfolios", json={"name": "Main"}, headers=HDR).json()
    url = f"/api/portfolios/{p['id']}/transactions"
    base = {"symbol": "AAPL", "currency": "USD"}
    assert admin_client.post(url, json={**base, "kind": "buy", "trade_date": "2024-01-02", "quantity": "10", "price": "100", "fees": "1"}, headers=HDR).status_code == 201
    assert admin_client.post(url, json={**base, "kind": "buy", "trade_date": "2024-02-02", "quantity": "10", "price": "120", "fees": "1"}, headers=HDR).status_code == 201
    assert admin_client.post(url, json={**base, "kind": "sell", "trade_date": "2024-03-01", "quantity": "5", "price": "130", "fees": "1"}, headers=HDR).status_code == 201
    assert admin_client.post(url, json={**base, "kind": "dividend", "trade_date": "2024-03-15", "price": "3.75"}, headers=HDR).status_code == 201
    # Overselling is rejected.
    r = admin_client.post(url, json={**base, "kind": "sell", "trade_date": "2024-03-20", "quantity": "100", "price": "1"}, headers=HDR)
    assert r.status_code == 422
    # A non-SEC symbol (e.g. Euronext) is allowed.
    assert admin_client.post(url, json={"symbol": "ASML.AS", "currency": "EUR", "kind": "buy", "trade_date": "2024-01-05", "quantity": "1", "price": "600"}, headers=HDR).status_code == 201

    d = admin_client.get(f"/api/portfolios/{p['id']}").json()
    aapl = next(x for x in d["open_positions"] if x["symbol"] == "AAPL")
    # cost 2202 for 20 sh -> avg 110.1 ; sell 5 removes 550.5 ; proceeds 650-1 => realized 98.5
    assert Decimal(aapl["quantity"]) == 15
    assert Decimal(aapl["cost_basis"]) == Decimal("1651.5")
    assert Decimal(aapl["realized_pl"]) == Decimal("98.5")
    assert Decimal(aapl["dividends"]) == Decimal("3.75")
    assert aapl["security_name"] == "Apple Inc."
    assert {t["currency"] for t in d["totals_by_currency"]} == {"EUR", "USD"}
    assert "Phase 2" in d["market_value_note"]

    # Deleting one buy keeps the sell valid; deleting both would not -> refused.
    buys = [t for t in d["transactions"] if t["kind"] == "buy" and t["symbol"] == "AAPL"]
    assert admin_client.delete(f"{url}/{buys[0]['id']}", headers=HDR).status_code == 204
    assert admin_client.delete(f"{url}/{buys[1]['id']}", headers=HDR).status_code == 422


def test_future_trade_rejected(admin_client):
    p = admin_client.post("/api/portfolios", json={"name": "X"}, headers=HDR).json()
    r = admin_client.post(f"/api/portfolios/{p['id']}/transactions", json={"symbol": "X", "currency": "EUR", "kind": "buy", "trade_date": "2999-01-01", "quantity": "1", "price": "1"}, headers=HDR)
    assert r.status_code == 422


def test_dashboard_status_and_export(admin_client, seeded):
    d = admin_client.get("/api/dashboard").json()
    assert d["securities_available"] == 5 and d["watchlist_count"] == 1
    st = admin_client.get("/api/system/status").json()
    assert st["ai"]["available"] is False and "not reachable" in st["ai"]["message"]
    exp = admin_client.get("/api/me/export")
    assert exp.status_code == 200 and exp.json()["user"]["username"] == "admin"
    assert "password" not in exp.text


def test_preferences(admin_client):
    r = admin_client.put("/api/preferences", json={"theme": "light", "base_currency": "EUR", "compact_numbers": False}, headers=HDR)
    assert r.status_code == 200 and r.json()["theme"] == "light"
    bad = admin_client.put("/api/preferences", json={"theme": "pink", "base_currency": "EUR", "compact_numbers": False}, headers=HDR)
    assert bad.status_code == 422


def test_backup(admin_client):
    r = admin_client.post("/api/admin/backups", headers=HDR)
    assert r.status_code == 201
    name = r.json()["name"]
    dl = admin_client.get(f"/api/admin/backups/{name}")
    assert dl.status_code == 200 and dl.content[:15] == b"SQLite format 3"
    assert admin_client.get("/api/admin/backups/..%2Finvestor.db").status_code == 404


def test_unknown_api_route_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["detail"] == "Not found"
