"""Claude connector: OAuth (DCR + PKCE + refresh rotation) and the MCP endpoint."""

import base64
import hashlib
import json
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import config, db
from sqlalchemy import select

from app.models import Document, OAuthGrant, User
from app.services import documents

from .conftest import HDR, PASSWORD, login, make_user
from .test_phase2 import example, sec_mock  # noqa: F401  (fixtures)

BASE = "https://mac.example.ts.net:8443"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 20 + "erifier-0123456789-abcdefghijklmnop"


def challenge(v: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture()
def env(app_env, monkeypatch):
    monkeypatch.setenv("II_CONNECTOR_PUBLIC_URL", BASE + "/")
    config.get_settings.cache_clear()
    from app.connector import app as public
    from app.main import app as main

    make_user("alice")
    make_user("bob")
    with TestClient(public, base_url=BASE) as pub, TestClient(main) as web:
        yield pub, web


def register(pub) -> str:
    r = pub.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [CALLBACK],
                                          "token_endpoint_auth_method": "none"})
    assert r.status_code == 201, r.text
    assert r.json()["token_endpoint_auth_method"] == "none"
    return r.json()["client_id"]


def auth_params(client_id: str, **extra) -> dict:
    p = {"response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK, "state": "st-123",
         "code_challenge": challenge(VERIFIER), "code_challenge_method": "S256", "scope": "investor",
         "resource": BASE + "/mcp"}
    p.update(extra)
    return p


def authorize(pub, client_id: str, username: str = "alice", password: str = PASSWORD, decision: str = "allow"):
    return pub.post("/oauth/authorize", data={**auth_params(client_id), "username": username, "password": password,
                                              "decision": decision}, follow_redirects=False)


def connect(pub, username: str = "alice") -> dict:
    cid = register(pub)
    r = authorize(pub, cid, username)
    assert r.status_code == 302, r.text
    q = parse_qs(urlsplit(r.headers["location"]).query)
    r = pub.post("/oauth/token", data={"grant_type": "authorization_code", "code": q["code"][0], "client_id": cid,
                                       "redirect_uri": CALLBACK, "code_verifier": VERIFIER, "resource": BASE + "/mcp"})
    assert r.status_code == 200, r.text
    return {"client_id": cid, **r.json()}


def rpc(pub, token: str, method: str, params: dict | None = None, id_: int = 1):
    r = pub.post("/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
                 headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    return r.json()


def call(pub, token: str, name: str, args: dict | None = None):
    res = rpc(pub, token, "tools/call", {"name": name, "arguments": args or {}})["result"]
    text = res["content"][0]["text"]
    return (text if res["isError"] else json.loads(text)), res["isError"]


def test_discovery_and_401(env):
    pub, _ = env
    prm = pub.get("/.well-known/oauth-protected-resource/mcp").json()
    assert prm["resource"] == BASE + "/mcp" and prm["authorization_servers"] == [BASE]
    asm = pub.get("/.well-known/oauth-authorization-server").json()
    assert asm["issuer"] == BASE and asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["registration_endpoint"] == BASE + "/oauth/register"
    assert "none" in asm["token_endpoint_auth_methods_supported"]
    r = pub.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 401
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"' in r.headers["www-authenticate"]
    r = pub.post("/mcp", json={}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]
    # The public app serves nothing else of the application.
    assert pub.get("/api/portfolios").status_code == 404
    assert pub.get("/").status_code == 404


def test_disabled_without_public_url(app_env):
    from app.connector import app as public

    with TestClient(public) as pub:
        assert pub.get("/.well-known/oauth-authorization-server").status_code == 404
        assert pub.post("/mcp", json={}).status_code == 404


def test_registration_rejects_foreign_redirects(env):
    pub, _ = env
    r = pub.post("/oauth/register", json={"redirect_uris": ["https://evil.example/cb"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"
    assert pub.post("/oauth/register", json={"redirect_uris": []}).status_code == 400


def test_authorize_page_and_errors(env):
    pub, _ = env
    cid = register(pub)
    r = pub.get("/oauth/authorize", params=auth_params(cid))
    assert r.status_code == 200 and "Connect to Investor Intelligence" in r.text and "claude.ai" in r.text
    assert r.headers["x-frame-options"] == "DENY"
    # Unknown client / unregistered redirect: shown to the user, never redirected.
    assert pub.get("/oauth/authorize", params=auth_params("ii-unknown"), follow_redirects=False).status_code == 400
    r = pub.get("/oauth/authorize", params=auth_params(cid, redirect_uri="https://evil.example/cb"), follow_redirects=False)
    assert r.status_code == 400
    # Missing PKCE: reported back through the redirect.
    r = pub.get("/oauth/authorize", params=auth_params(cid, code_challenge_method="plain"), follow_redirects=False)
    assert r.status_code == 302 and "error=invalid_request" in r.headers["location"] and "state=st-123" in r.headers["location"]
    # Wrong password keeps the user on the page; deny redirects with access_denied.
    r = authorize(pub, cid, password="wrong password!")
    assert r.status_code == 400 and "Invalid username or password" in r.text
    r = authorize(pub, cid, decision="deny")
    assert r.status_code == 302 and "error=access_denied" in r.headers["location"]


def test_token_exchange_pkce_replay_and_refresh(env):
    pub, _ = env
    cid = register(pub)
    loc = authorize(pub, cid).headers["location"]
    assert loc.startswith(CALLBACK + "?")
    q = parse_qs(urlsplit(loc).query)
    assert q["state"] == ["st-123"] and q["iss"] == [BASE]
    form = {"grant_type": "authorization_code", "code": q["code"][0], "client_id": cid, "redirect_uri": CALLBACK}
    bad = pub.post("/oauth/token", data={**form, "code_verifier": "x" * 43})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    ok = pub.post("/oauth/token", data={**form, "code_verifier": VERIFIER})
    assert ok.status_code == 200, ok.text
    tok = ok.json()
    assert tok["token_type"] == "Bearer" and tok["refresh_token"] and ok.headers["cache-control"] == "no-store"
    # Replaying the code fails and revokes the grant it produced.
    again = pub.post("/oauth/token", data={**form, "code_verifier": VERIFIER})
    assert again.json()["error"] == "invalid_grant"
    assert pub.post("/mcp", json={}, headers={"Authorization": f"Bearer {tok['access_token']}"}).status_code == 401

    t = connect(pub)
    r = pub.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": t["client_id"]})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != t["refresh_token"]
    # Rotation: the old refresh and access tokens are no longer valid.
    r = pub.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": t["client_id"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert rpc(pub, new["access_token"], "ping") == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert pub.post("/mcp", json={}, headers={"Authorization": f"Bearer {t['access_token']}"}).status_code == 401
    assert pub.post("/oauth/token", data={"grant_type": "password"}).json()["error"] == "unsupported_grant_type"


def test_mcp_protocol(env):
    pub, _ = env
    token = connect(pub)["access_token"]
    init = rpc(pub, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "claude-ai", "version": "1"}})["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    assert "end-of-day" in init["instructions"]
    r = pub.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                 headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 202
    tools = {t["name"]: t for t in rpc(pub, token, "tools/list")["result"]["tools"]}
    assert {"search_documents", "get_portfolios", "get_financials", "save_note"} <= set(tools)
    assert tools["get_portfolios"]["annotations"]["readOnlyHint"] is True
    assert tools["save_note"]["annotations"]["readOnlyHint"] is False
    assert rpc(pub, token, "nope/method")["error"]["code"] == -32601
    assert rpc(pub, token, "tools/call", {"name": "nope"})["error"]["code"] == -32602
    assert pub.get("/mcp", headers={"Authorization": f"Bearer {token}"}).status_code == 405
    r = pub.post("/mcp", json={}, headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_tools_use_only_the_users_data(env):
    pub, web = env
    login(web, "alice")
    assert web.post("/api/notes", json={"title": "Thesis", "body": "Moat is distribution."}, headers=HDR).status_code == 201
    pid = web.post("/api/portfolios", json={"name": "Core"}, headers=HDR).json()["id"]
    r = web.post(f"/api/portfolios/{pid}/transactions", headers=HDR, json={
        "symbol": "EXM", "kind": "buy", "trade_date": "2025-01-02", "quantity": "10", "price": "12.5", "fees": "1",
        "currency": "EUR"})
    assert r.status_code == 201, r.text

    s = db.session_factory()()
    alice_id = s.scalar(select(User.id).where(User.username == "alice"))
    doc = Document(user_id=alice_id, title="Annual report 2024", filename="ar.pdf", stored_name="x.pdf", size_bytes=1,
                   sha256="0" * 64, pages=3, chars=100, status="keyword_only")
    s.add(doc)
    s.flush()
    documents.ensure_fts(s)
    documents._add_chunks(s, doc.id, [(1, "Chairman letter. Revenue grew strongly.")], 0, False)
    documents._add_chunks(s, doc.id, [(2, "Dividend policy: payout of 40 percent.")], 1, True)
    s.commit()
    doc_id = doc.id
    s.close()

    alice = connect(pub, "alice")["access_token"]
    bob = connect(pub, "bob")["access_token"]

    notes, err = call(pub, alice, "get_notes")
    assert not err and [n["title"] for n in notes["notes"]] == ["Thesis"]
    notes, _ = call(pub, bob, "get_notes")
    assert notes["notes"] == []

    res, err = call(pub, alice, "search_documents", {"query": "dividend payout"})
    assert not err and res["results"][0]["page"] == 2 and res["results"][0]["ocr"] is True
    res, _ = call(pub, bob, "search_documents", {"query": "dividend payout"})
    assert res["results"] == []
    text, err = call(pub, bob, "read_document", {"document_id": doc_id})
    assert err and "not found" in text.lower()
    res, err = call(pub, alice, "read_document", {"document_id": doc_id, "start_page": 1, "end_page": 2})
    assert not err and [p["page"] for p in res["passages"]] == [1, 2]

    ports, err = call(pub, alice, "get_portfolios")
    pos = ports["portfolios"][0]["open_positions"][0]
    assert not err and pos["symbol"] == "EXM" and pos["quantity"] == "10" and ports["portfolios"][0]["transaction_count"] == 1
    assert call(pub, bob, "get_portfolios")[0]["portfolios"] == []
    text, err = call(pub, bob, "get_portfolio_performance", {"portfolio_id": pid})
    assert err and "not found" in text.lower()

    saved, err = call(pub, alice, "save_note", {"title": "From Claude", "body": "Summary"})
    assert not err and saved["saved"]
    titles = [n["title"] for n in web.get("/api/notes").json()]
    assert "From Claude" in titles

    text, err = call(pub, alice, "get_notes", {"include_shared": "yes"})
    assert err and "true or false" in text


def test_account_lists_and_revokes_connections(env):
    pub, web = env
    t = connect(pub, "alice")
    login(web, "alice")
    st = web.get("/api/account/connector").json()
    assert st["enabled"] and st["mcp_url"] == BASE + "/mcp" and len(st["connections"]) == 1
    gid = st["connections"][0]["id"]
    assert web.delete(f"/api/account/connector/{gid}", headers=HDR).status_code == 204
    assert pub.post("/mcp", json={}, headers={"Authorization": f"Bearer {t['access_token']}"}).status_code == 401
    r = pub.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    assert r.json()["error"] == "invalid_grant"
    assert web.get("/api/account/connector").json()["connections"] == []
    s = db.session_factory()()
    assert s.query(OAuthGrant).count() == 1
    s.close()


def test_company_tools(env, example, sec_mock):
    from datetime import date as d

    from app.services import prices

    pub, _ = env
    s = db.session_factory()()
    prices.upsert_bars(s, "EXMP", [{"day": d(2024, 12, 30), "close": Decimal("10.50")},
                                   {"day": d(2024, 12, 31), "close": Decimal("11.55")}], "CSV import: test", "USD")
    s.commit()
    s.close()
    token = connect(pub)["access_token"]

    found, err = call(pub, token, "search_securities", {"query": "example"})
    assert not err and found["results"][0]["ticker"] == "EXMP"
    comp, err = call(pub, token, "get_company", {"ticker": "exmp"})
    assert not err and comp["currency"] == "USD" and comp["quote"]["close"] == "11.55"
    fin, err = call(pub, token, "get_financials", {"ticker": "EXMP", "statement": "income"})
    assert not err and fin["currency"] == "USD"
    rev = next(r for r in fin["rows"] if r["label"].lower().startswith("revenue"))
    assert Decimal(rev["values"][0]) == 1200
    assert fin["latest_period_sources"][0]["form"] == "10-K"
    px, err = call(pub, token, "get_price_history", {"ticker": "EXMP", "range": "max"})
    assert not err and px["summary"]["last"] == {"date": "2024-12-31", "close": "11.55"}
    assert px["summary"]["change_pct"] == "10.00" and "not real-time" in px["note"]
    text, err = call(pub, token, "get_financials", {"ticker": "EXMP", "statement": "bogus"})
    assert err and "must be one of" in text
    text, err = call(pub, token, "get_company", {"ticker": "NOPE"})
    assert err
    text, err = call(pub, token, "compare_companies", {"tickers": ["EXMP"]})
    assert err and "2 to 5" in text
