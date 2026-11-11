import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.models import User, UserPreference, Watchlist
from app.security import hash_password, login_failures, register_attempts

HDR = {"X-Requested-With": "InvestorIntelligence"}
PASSWORD = "correct horse battery"


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("II_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("II_FRONTEND_DIST", str(tmp_path / "no-frontend"))
    monkeypatch.setenv("II_SEC_USER_AGENT", "InvestorIntelligence tests test@example.invalid")
    monkeypatch.setenv("II_OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.setenv("II_SCHEDULER", "false")
    config.get_settings.cache_clear()
    db.reset_engine()
    db.init_db()
    login_failures.reset()
    register_attempts.reset()
    yield tmp_path
    db.reset_engine()
    config.get_settings.cache_clear()


def make_user(username: str, role: str = "member") -> int:
    s = db.session_factory()()
    u = User(username=username, display_name=username.title(), password_hash=hash_password(PASSWORD), role=role)
    s.add(u)
    s.flush()
    s.add(UserPreference(user_id=u.id))
    s.add(Watchlist(user_id=u.id, name="My watchlist"))
    s.commit()
    uid = u.id
    s.close()
    return uid


def login(client: TestClient, username: str):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD}, headers=HDR)
    assert r.status_code == 200, r.text
    return r


@pytest.fixture()
def client(app_env):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_client(app_env):
    from app.main import app

    make_user("admin", "admin")
    with TestClient(app) as c:
        login(c, "admin")
        yield c


SEC_SAMPLE = {
    # Shape of https://www.sec.gov/files/company_tickers_exchange.json — test fixture only.
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [789019, "MICROSOFT CORP", "MSFT", "Nasdaq"],
        [1018724, "AMAZON COM INC", "AMZN", "Nasdaq"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-A", "NYSE"],
        [999999, "", "BAD", "NYSE"],
    ],
}


@pytest.fixture()
def seeded(app_env):
    from app.services import sec

    s = db.session_factory()()
    sec.upsert_securities(s, sec.parse_payload(SEC_SAMPLE))
    s.commit()
    s.close()
