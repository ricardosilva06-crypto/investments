from fastapi.testclient import TestClient

from .conftest import HDR, PASSWORD, login, make_user


def test_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/watchlists").status_code == 401


def test_login_logout(client):
    make_user("alice")
    login(client, "alice")
    assert client.get("/api/auth/me").json()["username"] == "alice"
    assert client.post("/api/auth/logout", headers=HDR).status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_session_cookie_is_httponly(client):
    make_user("alice")
    r = login(client, "alice")
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_wrong_password_and_rate_limit(client):
    make_user("alice")
    for _ in range(10):
        r = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password"}, headers=HDR)
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}, headers=HDR)
    assert r.status_code == 429


def test_csrf_header_required(client):
    make_user("alice")
    r = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 403


def test_invite_flow(admin_client, app_env):
    from app.main import app

    r = admin_client.post("/api/admin/invites", json={"label": "Bob"}, headers=HDR)
    assert r.status_code == 201
    code = r.json()["code"]
    assert "code" not in admin_client.get("/api/admin/invites").json()[0]

    with TestClient(app) as anon:
        bad = anon.post(
            "/api/auth/register",
            json={"invite_code": "AAAA-BBBB-CCCC-DDDD", "username": "bob", "display_name": "Bob", "password": PASSWORD},
            headers=HDR,
        )
        assert bad.status_code == 400
        ok = anon.post(
            "/api/auth/register",
            json={"invite_code": code.lower().replace("-", ""), "username": "Bob", "display_name": "Bob", "password": PASSWORD},
            headers=HDR,
        )
        assert ok.status_code == 201, ok.text
        assert ok.json()["username"] == "bob" and ok.json()["role"] == "member"
        assert anon.get("/api/auth/me").status_code == 200
        # Members cannot reach admin endpoints.
        assert anon.get("/api/admin/users").status_code == 403

    with TestClient(app) as anon2:
        reuse = anon2.post(
            "/api/auth/register",
            json={"invite_code": code, "username": "carol", "display_name": "Carol", "password": PASSWORD},
            headers=HDR,
        )
        assert reuse.status_code == 400

    notes = admin_client.get("/api/notifications").json()
    assert notes and notes[0]["kind"] == "invite_used"


def test_short_password_rejected(admin_client, app_env):
    code = admin_client.post("/api/admin/invites", json={}, headers=HDR).json()["code"]
    from app.main import app

    with TestClient(app) as anon:
        r = anon.post(
            "/api/auth/register",
            json={"invite_code": code, "username": "dave", "display_name": "Dave", "password": "short"},
            headers=HDR,
        )
        assert r.status_code == 422


def test_password_change_revokes_other_sessions(client, app_env):
    from app.main import app

    make_user("alice")
    login(client, "alice")
    with TestClient(app) as other:
        login(other, "alice")
        r = client.post(
            "/api/auth/password", json={"current_password": PASSWORD, "new_password": "another long password"}, headers=HDR
        )
        assert r.status_code == 204
        assert other.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200


def test_deactivated_user_signed_out(admin_client, app_env):
    from app.main import app

    uid = make_user("eve")
    with TestClient(app) as eve:
        login(eve, "eve")
        assert admin_client.patch(f"/api/admin/users/{uid}", json={"is_active": False}, headers=HDR).status_code == 200
        assert eve.get("/api/auth/me").status_code == 401
