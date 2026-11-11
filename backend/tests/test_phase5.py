import io
import zipfile
from datetime import date, datetime, timedelta, UTC

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.models import Filing, Notification, Security
from app.services import news, scheduler, sec_client

from .conftest import HDR, login, make_user
from .fixtures import CIK, COMPANYFACTS, SUBMISSIONS

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Example IR</title>
<item><title>Example Corp reports Q3 results</title><link>https://ir.example.com/q3</link><guid>q3</guid>
<pubDate>Tue, 04 Nov 2025 12:00:00 GMT</pubDate><description>&lt;p&gt;Revenue rose.&lt;/p&gt;</description></item>
<item><title>Bad link</title><link>javascript:alert(1)</link><guid>x</guid></item>
</channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title><entry><id>tag:1</id><title>Atom entry</title>
<link rel="alternate" href="https://a.example/1"/><updated>2025-11-05T10:00:00Z</updated><summary>S</summary></entry></feed>"""


@pytest.fixture()
def feeds(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        if req.url.host == "ir.example.com":
            return httpx.Response(200, content=RSS, headers={"ETag": '"v1"'})
        if req.url.host == "atom.example.com":
            return httpx.Response(200, content=ATOM)
        return httpx.Response(200, content=b"<html>not a feed</html>")

    monkeypatch.setattr(news, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return calls


@pytest.fixture()
def example(app_env, monkeypatch):
    s = db.session_factory()()
    s.add(Security(ticker="EXMP", name="EXAMPLE CORP", cik=CIK, exchange="Nasdaq", source="test"))
    s.commit()
    s.close()
    monkeypatch.setattr(sec_client, "_MIN_INTERVAL", 0)
    monkeypatch.setattr(sec_client, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=COMPANYFACTS if "companyfacts" in r.url.path else SUBMISSIONS))))


def test_feeds_and_news(admin_client, feeds, example):
    r = admin_client.post("/api/admin/feeds", json={"url": "https://ir.example.com/rss", "title": "Example IR", "ticker": "EXMP"}, headers=HDR)
    assert r.status_code == 201, r.text
    bad = admin_client.post("/api/admin/feeds", json={"url": "https://nofeed.example.com/"}, headers=HDR)
    assert bad.status_code == 422 and "Could not read" in bad.json()["detail"]
    assert admin_client.post("/api/admin/feeds", json={"url": "file:///etc/passwd"}, headers=HDR).status_code == 422
    admin_client.post("/api/admin/feeds", json={"url": "https://atom.example.com/feed"}, headers=HDR)
    allnews = admin_client.get("/api/news").json()["items"]
    titles = [i["title"] for i in allnews]
    assert "Example Corp reports Q3 results" in titles and "Atom entry" in titles
    assert all(i["link"].startswith("https://") or i["link"] == "" for i in allnews)  # javascript: links dropped
    q3 = next(i for i in allnews if i["title"].startswith("Example"))
    assert q3["summary"] == "Revenue rose." and q3["ticker"] == "EXMP"
    # Conditional request: second fetch sends ETag and gets 304, no duplicates.
    admin_client.post("/api/admin/feeds/refresh", headers=HDR)
    assert any(c.headers.get("if-none-match") == '"v1"' for c in feeds)
    assert len(admin_client.get("/api/news").json()["items"]) == 3
    # "mine" = feeds and SEC filings for companies the user watches/holds.
    assert admin_client.get("/api/news", params={"scope": "mine"}).json()["items"] == []
    wl = admin_client.get("/api/watchlists").json()[0]
    admin_client.post(f"/api/watchlists/{wl['id']}/items", json={"ticker": "EXMP"}, headers=HDR)
    admin_client.get("/api/companies/EXMP")  # stores filings
    mine = admin_client.get("/api/news", params={"scope": "mine"}).json()["items"]
    assert {i["type"] for i in mine} == {"news", "filing"}
    assert any(i["title"].startswith("EXMP filed 10-K") for i in mine)


def test_feed_parser_safety():
    with pytest.raises(news.FeedError):
        news.parse(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><rss><channel><title>&a;</title></channel></rss>')
    with pytest.raises(news.FeedError):
        news.parse(b"<html/>")


def test_price_alerts(admin_client, seeded):
    a = admin_client.post("/api/alerts", json={"ticker": "AAPL", "kind": "price_above", "threshold": "150"}, headers=HDR)
    assert a.status_code == 201
    m = admin_client.post("/api/alerts", json={"ticker": "AAPL", "kind": "daily_move", "threshold": "0.05", "repeat": True}, headers=HDR).json()
    assert admin_client.post("/api/alerts", json={"ticker": "AAPL", "kind": "price_below"}, headers=HDR).status_code == 422
    assert admin_client.post("/api/alerts", json={"ticker": "AAPL", "kind": "daily_move", "threshold": "5"}, headers=HDR).status_code == 422
    admin_client.post("/api/admin/prices/AAPL/import", json={"csv": "Date,Close\n2024-12-30,140\n2024-12-31,149\n", "source": "test", "currency": "USD"}, headers=HDR)
    notes = admin_client.get("/api/notifications").json()
    assert [n["title"] for n in notes if n["kind"] == "alert"] == ["AAPL moved +6.43%"]  # 149 < 150, no price alert yet
    admin_client.post("/api/admin/prices/AAPL/import", json={"csv": "Date,Close\n2025-01-02,151\n", "source": "test", "currency": "USD"}, headers=HDR)
    titles = [n["title"] for n in admin_client.get("/api/notifications").json() if n["kind"] == "alert"]
    assert "AAPL closed at 151 USD" in titles
    alerts = {x["id"]: x for x in admin_client.get("/api/alerts").json()}
    assert alerts[a.json()["id"]]["active"] is False  # one-shot
    assert alerts[m["id"]]["active"] is True  # repeating
    # Re-evaluating the same close does not fire again.
    admin_client.post("/api/admin/prices/AAPL/import", json={"csv": "Date,Close\n2025-01-02,151\n", "source": "test", "currency": "USD"}, headers=HDR)
    assert len([n for n in admin_client.get("/api/notifications").json() if n["kind"] == "alert"]) == 2


def test_filing_alert_only_new_filings(admin_client, example):
    admin_client.get("/api/companies/EXMP")  # existing filings stored
    r = admin_client.post("/api/alerts", json={"ticker": "EXMP", "kind": "filing", "forms": "8-K,10-Q"}, headers=HDR)
    assert r.status_code == 201
    assert not [n for n in admin_client.get("/api/notifications").json() if n["kind"] == "alert"]
    s = db.session_factory()()
    s.add(Filing(cik=CIK, accession="0001234567-25-000099", form="8-K", filing_date=date.today(), primary_document="x.htm"))
    s.add(Filing(cik=CIK, accession="0001234567-25-000098", form="4", filing_date=date.today(), primary_document="y.xml"))
    s.commit()
    s.close()
    from app.services import alerts

    s = db.session_factory()()
    assert alerts.evaluate(s) == 1
    s.close()
    n = [x for x in admin_client.get("/api/notifications").json() if x["kind"] == "alert"]
    assert n[0]["title"] == "EXMP: new 8-K filing"


def test_alerts_are_private(admin_client, seeded, app_env):
    aid = admin_client.post("/api/alerts", json={"ticker": "AAPL", "kind": "price_above", "threshold": "1000"}, headers=HDR).json()["id"]
    from app.main import app

    make_user("mallory")
    with TestClient(app) as m:
        login(m, "mallory")
        assert m.get("/api/alerts").json() == []
        assert m.delete(f"/api/alerts/{aid}", headers=HDR).status_code == 404


def test_shared_research(admin_client, seeded, app_env):
    from app.main import app

    private = admin_client.post("/api/notes", json={"title": "Private", "body": "mine"}, headers=HDR).json()
    shared = admin_client.post("/api/notes", json={"title": "AAPL thesis", "body": "shared body", "ticker": "AAPL", "is_shared": True}, headers=HDR).json()
    assert shared["is_shared"] is True
    make_user("bob")
    with TestClient(app) as b:
        login(b, "bob")
        lst = b.get("/api/notes", params={"scope": "shared"}).json()
        assert [n["title"] for n in lst] == ["AAPL thesis"] and lst[0]["author"] == "Admin" and lst[0]["is_mine"] is False
        assert b.get(f"/api/notes/{shared['id']}").status_code == 200
        assert b.get(f"/api/notes/{private['id']}").status_code == 404
        assert b.put(f"/api/notes/{shared['id']}", json={"title": "hacked", "body": ""}, headers=HDR).status_code == 404
        assert b.delete(f"/api/notes/{shared['id']}", headers=HDR).status_code == 404
        assert b.get("/api/notes").json() == []
    # Unsharing hides it again; updates without is_shared keep the current setting.
    admin_client.put(f"/api/notes/{shared['id']}", json={"title": "AAPL thesis v2", "body": "x", "ticker": "AAPL"}, headers=HDR)
    assert admin_client.get(f"/api/notes/{shared['id']}").json()["is_shared"] is True
    admin_client.put(f"/api/notes/{shared['id']}", json={"title": "AAPL thesis v2", "body": "x", "is_shared": False}, headers=HDR)
    with TestClient(app) as b:
        login(b, "bob")
        assert b.get("/api/notes", params={"scope": "shared"}).json() == []


def test_backup_includes_documents(admin_client, app_env):
    from app.config import get_settings

    d = get_settings().documents_dir / "1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "abc.pdf").write_bytes(b"%PDF-1.4 test")
    r = admin_client.post("/api/admin/jobs/backup/run", headers=HDR).json()
    assert r["status"] == "ok"
    name = admin_client.get("/api/admin/backups").json()[0]["name"]
    z = zipfile.ZipFile(io.BytesIO(admin_client.get(f"/api/admin/backups/{name}").content))
    assert "documents/1/abc.pdf" in z.namelist() and "investor.db" in z.namelist()
    jobs = admin_client.get("/api/admin/jobs").json()
    assert jobs["runs"][0]["job"] == "backup" and jobs["runs"][0]["status"] == "ok"


def test_scheduler_due_logic():
    now = datetime(2026, 1, 10, 23, 30, tzinfo=UTC)
    due = scheduler.due_jobs(now, {})
    assert set(due) == {"feeds", "fx", "daily_refresh", "backup"}
    last = {"feeds": now - timedelta(minutes=10), "fx": now - timedelta(hours=1),
            "daily_refresh": now.replace(hour=22, minute=1), "backup": now.replace(hour=3, minute=5)}
    assert scheduler.due_jobs(now, last) == []
    early = now.replace(hour=2)
    assert "backup" not in scheduler.due_jobs(early, {"backup": early - timedelta(hours=23), "feeds": early, "fx": early, "daily_refresh": early})


def test_daily_refresh_job(admin_client, example):
    wl = admin_client.get("/api/watchlists").json()[0]
    admin_client.post(f"/api/watchlists/{wl['id']}/items", json={"ticker": "EXMP"}, headers=HDR)
    r = admin_client.post("/api/admin/jobs/daily_refresh/run", headers=HDR).json()
    assert r["status"] == "ok" and "1 companies checked" in r["message"]


def test_security_check_and_push_key(admin_client, app_env):
    sc = admin_client.get("/api/admin/security").json()
    keys = {c["key"]: c["ok"] for c in sc["checks"]}
    assert keys["https"] is False and keys["api_docs"] is True
    assert admin_client.get("/api/docs").status_code == 404  # docs disabled by default
    k = admin_client.get("/api/push/public-key").json()["key"]
    assert len(k) > 80  # base64url uncompressed P-256 point
    assert admin_client.get("/api/push/public-key").json()["key"] == k  # key persisted
    bad = admin_client.post("/api/push/subscriptions", json={"endpoint": "http://evil", "keys": {}}, headers=HDR)
    assert bad.status_code == 422
    ok = admin_client.post("/api/push/subscriptions", json={"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "x", "auth": "y"}}, headers=HDR)
    assert ok.status_code == 201 and admin_client.get("/api/push/status").json()["devices"] == 1


def test_migration_adds_missing_column(app_env):
    from sqlalchemy import text

    eng = db.get_engine()
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE legacy_probe (id INTEGER)")
    db.ADDED_COLUMNS.append(("legacy_probe", "extra", "TEXT"))
    try:
        db.init_db()
        with eng.begin() as c:
            cols = [r[1] for r in c.execute(text("PRAGMA table_info(legacy_probe)"))]
        assert "extra" in cols
        db.init_db()  # idempotent
    finally:
        db.ADDED_COLUMNS.pop()


_ = Notification
