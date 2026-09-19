"""관리자 라우트 검증 — 권한, 회원 CRUD·승인, 마지막 관리자 보호, 접속 현황, 데이터 정리."""

import pytest
from fastapi.testclient import TestClient

from claw_server import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "store",
                     admin_password="root-pw", session_secret="test-secret")
    with TestClient(app) as c:
        yield c


def _login(client, username, password):
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


def test_requires_admin(client, tmp_path):
    assert client.get("/api/admin/users").status_code == 401  # 미인증
    client.post("/api/auth/signup", json={"username": "kim", "password": "pw1234"})
    client.app.state.users.update("kim", status="active")
    _login(client, "kim", "pw1234")
    assert client.get("/api/admin/users").status_code == 403  # 일반 계정
    # 세션 모드가 아니면 관리자 API도 없다
    open_app = create_app(data_dir=tmp_path / "open", admin_password="")
    with TestClient(open_app) as c:
        assert c.get("/api/admin/users").status_code == 403


def test_member_management_flow(client):
    client.post("/api/auth/signup", json={"username": "kim", "password": "pw1234"})
    _login(client, "admin", "root-pw")
    users = client.get("/api/admin/users").json()
    kim = next(u for u in users if u["username"] == "kim")
    assert kim["status"] == "pending" and "pw_hash" not in kim
    # 승인 → 로그인 가능
    r = client.patch("/api/admin/users/kim", json={"status": "active"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    # 관리자 지정·비번 재설정
    assert client.patch("/api/admin/users/kim",
                        json={"role": "admin"}).json()["role"] == "admin"
    assert client.patch("/api/admin/users/kim",
                        json={"password": "new-pw"}).status_code == 200
    # 관리자 직접 생성 = 즉시 active
    r = client.post("/api/admin/users",
                    json={"username": "lee", "password": "pw1234"})
    assert r.status_code == 201 and r.json()["status"] == "active"
    # 삭제
    assert client.delete("/api/admin/users/lee").status_code == 200
    assert client.delete("/api/admin/users/lee").status_code == 404
    assert client.patch("/api/admin/users/ghost",
                        json={"status": "active"}).status_code == 404
    assert client.patch("/api/admin/users/kim",
                        json={"status": "이상함"}).status_code == 422
    # 관리자 직접 생성도 아이디 문자 규칙 위반은 500이 아니라 422 — Pydantic은 길이만 본다
    for bad in ("김철수", "a b"):
        assert client.post("/api/admin/users",
                           json={"username": bad, "password": "pw1234"}).status_code == 422
    # 재설정된 비번으로 kim 로그인
    _login(client, "kim", "new-pw")


def test_last_admin_and_self_protected(client):
    _login(client, "admin", "root-pw")
    # 유일한 active 관리자는 강등·거절 불가
    assert client.patch("/api/admin/users/admin",
                        json={"role": "user"}).status_code == 409
    assert client.patch("/api/admin/users/admin",
                        json={"status": "rejected"}).status_code == 409
    # 자기 자신 삭제 불가 (다른 관리자가 있어도)
    r = client.post("/api/admin/users",
                    json={"username": "boss2", "password": "pw1234", "role": "admin"})
    assert r.status_code == 201
    assert client.delete("/api/admin/users/admin").status_code == 409


def test_sessions_overview(client):
    client.post("/api/auth/signup", json={"username": "kim", "password": "pw1234"})
    client.app.state.users.update("kim", status="active")
    _login(client, "kim", "pw1234")
    _login(client, "admin", "root-pw")  # TestClient 쿠키 하나라 마지막 로그인이 admin
    r = client.get("/api/admin/sessions")
    assert r.status_code == 200
    body = r.json()
    online = {s["username"] for s in body["online"]}
    assert "admin" in online  # 이 요청 자신이 최근 요청
    kim = next(u for u in body["users"] if u["username"] == "kim")
    assert kim["last_login"] is not None  # 로그인 시각 기록


def test_data_overview_and_prune(client):
    store = client.app.state.store
    for i in range(3):
        store.save(f"r{i}", {"x": i}, meta={"created": float(i)})
    _login(client, "admin", "root-pw")
    r = client.get("/api/admin/data")
    assert r.status_code == 200
    assert r.json()["results"] == 3 and r.json()["bytes"] > 0
    r = client.post("/api/admin/data/prune", json={"keep": 1})
    assert r.status_code == 200 and r.json()["removed"] == 2
    assert [m["id"] for m in store.list()] == ["r2"]  # 최신만 남는다
    assert client.post("/api/admin/data/prune",
                       json={"keep": -1}).status_code == 422
