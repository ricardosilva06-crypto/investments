import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.models import Security
from app.services import analyst, esef

from .conftest import HDR, login, make_user
from .esef_fixtures import IXBRL, LEI, package, xbrl_json_2024


def upload(client, data: bytes, name="report.zip"):
    return client.post("/api/admin/esef/upload", files={"file": (name, data, "application/zip")}, headers=HDR)


def rows(d):
    return {r["key"]: r["values"] for r in d["rows"]}


def test_lei_check_digits():
    assert esef.valid_lei(LEI)
    assert not esef.valid_lei(LEI[:-1] + ("0" if LEI[-1] != "0" else "1"))
    assert not esef.valid_lei("not-a-lei")


def test_parse_inline_xbrl():
    r = esef.parse_ixbrl([IXBRL])
    assert r.lei == LEI and r.entity_name == "Example Europa SE" and r.period_end.isoformat() == "2023-12-31"
    facts = {(f["taxonomy"], f["concept"], f["end"].isoformat()): f for f in r.facts}
    rev = facts[("ifrs-full", "Revenue", "2023-12-31")]
    assert rev["value"] == Decimal("1234500000") and rev["unit"] == "EUR"  # nested span + comma decimal + scale 6
    assert facts[("ifrs-full", "ProfitLossAttributableToOwnersOfParent", "2022-12-31")]["value"] == Decimal("-20000000")  # sign="-"
    assert facts[("ifrs-full", "CostOfSales", "2023-12-31")]["value"] == Decimal("734500000")  # brackets are presentation only
    assert facts[("ifrs-full", "DilutedEarningsLossPerShare", "2023-12-31")]["unit"] == "EUR/shares"
    assert facts[("ifrs-full", "DividendsPaidClassifiedAsFinancingActivities", "2023-12-31")]["value"] == 0
    assert ("exe", "AdjustedEbitda", "2023-12-31") in facts  # extension kept, just not mapped to a standard line
    assert r.skipped_dimensional == 1  # segment revenue
    assert sum(1 for f in r.facts if f["concept"] == "Revenue" and f["end"].isoformat() == "2023-12-31") == 1  # deduplicated


def test_xbrl_json_period_semantics():
    r = esef.parse_xbrl_json(xbrl_json_2024())
    assert r.lei == LEI and r.period_end.isoformat() == "2024-12-31"  # exclusive end 2025-01-01 -> 2024-12-31
    inst = next(f for f in r.facts if f["concept"] == "Assets")
    assert inst["start"] is None and inst["end"].isoformat() == "2024-12-31"
    assert r.skipped_dimensional == 1 and r.entity_name == "Example Europa SE"


def test_upload_link_and_company_pages(admin_client, seeded):
    r = upload(admin_client, package())
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["created"] is True and d["skipped_dimensional"] == 1 and d["linked_ticker"] is None
    assert upload(admin_client, package()).json()["created"] is False  # idempotent
    bad = admin_client.post("/api/admin/esef/link", json={"lei": LEI, "ticker": "AAPL"}, headers=HDR)
    assert bad.status_code == 422 and "SEC-registered" in bad.json()["detail"]
    ok = admin_client.post("/api/admin/esef/link", json={"lei": LEI, "ticker": "exeu.pa", "exchange": "Euronext Paris"}, headers=HDR)
    assert ok.status_code == 200 and ok.json()["ticker"] == "EXEU.PA" and ok.json()["name"] == "Example Europa SE"
    # Search, company page, statements
    assert any(h["title"] == "EXEU.PA" for h in admin_client.get("/api/search", params={"q": "europa"}).json())
    c = admin_client.get("/api/companies/EXEU.PA").json()
    assert c["has_financials"] and c["currency"] == "EUR" and c["esef"]["lei"] == LEI and c["esef"]["reports"] == 1
    inc = admin_client.get("/api/companies/EXEU.PA/financials", params={"statement": "income"}).json()
    assert [p["end"] for p in inc["periods"]] == ["2023-12-31", "2022-12-31"]
    rv = rows(inc)
    assert Decimal(rv["revenue"][0]["value"]) == Decimal("1234500000") and rv["revenue"][0]["concept"] == "ifrs-full:Revenue"
    assert Decimal(rv["net_income"][1]["value"]) == Decimal("-20000000")
    assert Decimal(rv["eps_diluted"][0]["value"]) == Decimal("1.25")
    assert rv["revenue"][0]["form"].startswith("ESEF annual report FY 2023-12-31")
    assert "ESEF" in inc["source"]["name"]
    q = admin_client.get("/api/companies/EXEU.PA/financials", params={"statement": "income", "period": "quarterly"}).json()
    assert q["periods"] == []  # ESEF reports are annual: no quarters invented
    m = rows(admin_client.get("/api/companies/EXEU.PA/financials", params={"statement": "metrics"}).json())
    assert Decimal(m["fcf"][0]["value"]) == Decimal("220000000")
    assert Decimal(m["gross_margin"][0]["value"]).quantize(Decimal("0.0001")) == Decimal("0.4050")
    f = admin_client.get("/api/companies/EXEU.PA/filings").json()
    assert f[0]["form"] == "ESEF" and f[0]["report_date"] == "2023-12-31"
    # DCF pre-fill uses the ESEF cash flows
    dcf = admin_client.get("/api/companies/EXEU.PA/dcf-inputs").json()
    assert Decimal(dcf["fields"]["base_fcf"]["value"]) == Decimal("220000000") and "ESEF" in dcf["fields"]["base_fcf"]["source"]
    assert dcf["currency"] == "EUR"


def test_fxo_fetch_adds_years_and_restatements(admin_client, monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if req.url.path == "/api/filings":
            assert req.url.params["filter[entity.identifier]"] == LEI
            return httpx.Response(200, json={"data": [{"type": "filing", "id": "9", "attributes": {
                "period_end": "2024-12-31", "json_url": f"/{LEI}/2024-12-31/ESEF/XX/0/report.json",
                "viewer_url": f"/{LEI}/2024-12-31/ESEF/XX/0/viewer.html"}}]})
        if req.url.path.endswith("report.json"):
            return httpx.Response(200, json=xbrl_json_2024())
        return httpx.Response(404)

    monkeypatch.setattr(esef, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    upload(admin_client, package())
    admin_client.post("/api/admin/esef/link", json={"lei": LEI, "ticker": "EXEU.PA"}, headers=HDR)
    r = admin_client.post("/api/admin/esef/fetch", json={"lei": LEI}, headers=HDR)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1 and r.json()["reports"][0]["viewer_url"].startswith("https://filings.xbrl.org/")
    inc = admin_client.get("/api/companies/EXEU.PA/financials", params={"statement": "income"}).json()
    assert [p["end"] for p in inc["periods"]] == ["2024-12-31", "2023-12-31", "2022-12-31"]
    rev = rows(inc)["revenue"]
    assert Decimal(rev[1]["value"]) == Decimal("1240000000")  # restated in the later report wins
    assert rev[0]["url"].endswith("viewer.html")
    # An LEI with wrong check digits is refused before any request is made.
    n = len(calls)
    assert admin_client.post("/api/admin/esef/fetch", json={"lei": "5299000EXAMPLE00EU00"}, headers=HDR).status_code == 422
    assert len(calls) == n


def test_rejections_and_permissions(admin_client, app_env):
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><p>&b;</p></html>'
    r = upload(admin_client, bomb, "x.xhtml")
    assert r.status_code == 422
    assert upload(admin_client, b"%PDF-1.4 not esef", "x.pdf").status_code == 422
    no_tags = package(b'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>inlineXBRL but no facts</body></html>')
    assert upload(admin_client, no_tags).status_code == 422
    assert admin_client.post("/api/admin/esef/link", json={"lei": LEI, "ticker": "X"}, headers=HDR).status_code == 404
    from app.main import app

    make_user("bob")
    with TestClient(app) as b:
        login(b, "bob")
        assert upload(b, package()).status_code == 403
        assert b.get("/api/esef/companies").status_code == 200


def test_ai_context_uses_esef(admin_client, seeded):
    upload(admin_client, package())
    admin_client.post("/api/admin/esef/link", json={"lei": LEI, "ticker": "EXEU.PA"}, headers=HDR)
    s = db.session_factory()()
    from app.models import User

    sec = s.query(Security).filter_by(ticker="EXEU.PA").one()
    user = s.query(User).first()
    ctx = analyst.build_context(s, user, "company_analysis", [sec], [], "", None)
    text = ctx.text(100_000)
    assert "ESEF annual reports (IFRS)" in text and f"LEI {LEI}" in text and "1,234.5" in text
    s.close()
