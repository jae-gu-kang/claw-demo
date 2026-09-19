"""세션 인증 라우트 검증 — 로그인·가입·me·logout, /api만 게이트, WS 쿠키, 모드 선택.

미들웨어(SessionAuthProtect)와 라우트가 한 몸으로 도는 통합 케이스 —
Basic Auth 쪽은 tests/claw_server/test_auth.py가 그대로 지킨다.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from claw_server import create_app, sessions


@pytest.fixture()
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "store",
                     admin_password="root-pw", session_secret="test-secret")
    with TestClient(app) as c:
        yield c


def _login(client, username, password):
    return client.post("/api/auth/login",
                       json={"username": username, "password": password})


def test_me_reports_mode_without_auth(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"mode": "session", "user": None}


def test_me_malformed_cookie_is_401_not_500(client):
    """조작된 쿠키에 /api/auth/me가 500이면 부팅 게이트가 통째로 못 뜬다 — 위조로
    처리해 200(user:null)이어야 한다. 서명 자리 비ASCII는 latin-1 쿠키 헤더로 실제
    도달하며 hmac.compare_digest가 TypeError를 던지던 경로다(sessions.verify)."""
    # bytes로 보낸다 — httpx는 str 헤더를 ascii로 재인코딩해 막지만, 실서버는 쿠키
    # 헤더를 latin-1 바이트로 받는다(0xe9='é'가 서명 자리에 온 상황을 그대로 재현)
    r = client.get("/api/auth/me",
                   headers={"cookie": b"claw_session=dGVzdA.caf\xe9"})
    assert r.status_code == 200
    assert r.json() == {"mode": "session", "user": None}
    # 남의 malformed 쿠키가 섞여도 유효한 세션은 살아남는다(엄격 파서 SimpleCookie 회귀)
    token = _login(client, "admin", "root-pw").cookies[sessions.COOKIE]
    r = client.get("/api/auth/me",
                   headers={"cookie": f"broken; claw_session={token}"})
    assert r.json()["user"]["username"] == "admin"


def test_api_gated_static_open(client):
    r = client.get("/api/jobs")
    assert r.status_code == 401
    assert "www-authenticate" not in r.headers  # Basic 팝업이 로그인 화면을 가리면 안 된다
    assert client.get("/").status_code == 200  # 정적 껍데기는 개방 — 로그인 화면 재료
    assert client.get("/api/health").status_code == 200  # 배포 헬스체크 면제


def test_admin_seed_login_logout_flow(client):
    r = _login(client, "admin", "root-pw")
    assert r.status_code == 200
    assert r.json() == {"username": "admin", "role": "admin"}
    assert sessions.COOKIE in r.cookies
    assert client.get("/api/jobs").status_code == 200  # 쿠키로 게이트 통과
    me = client.get("/api/auth/me").json()
    assert me["user"]["username"] == "admin"
    assert "pw_hash" not in me["user"]  # 해시 유출 금지
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/jobs").status_code == 401


def test_login_wrong_password(client):
    assert _login(client, "admin", "wrong").status_code == 401
    assert _login(client, "ghost", "pw").status_code == 401


def test_login_nonexistent_runs_verify(client, monkeypatch):
    """없는 아이디에도 verify_password(scrypt)를 한 번 돌려 응답 시간을 맞춘다 —
    안 돌리면 record is None이 즉시 401을 반환해 아이디 존재 여부가 타이밍으로 샌다."""
    from claw_server.routes import auth as auth_routes
    calls = []
    monkeypatch.setattr(auth_routes, "verify_password",
                        lambda pw, h: (calls.append(h), False)[1])
    assert _login(client, "ghost-user", "pw").status_code == 401
    assert calls == [auth_routes._DUMMY_HASH]  # 더미 해시로 실제로 돌았다


def test_signup_pending_then_approved(client):
    r = client.post("/api/auth/signup", json={"username": "kim", "password": "pw1234"})
    assert r.status_code == 201
    # 승인 전 로그인 — 비번이 맞아야 pending을 말한다 (틀리면 401: 계정 존재 탐침 방지)
    r = _login(client, "kim", "pw1234")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "pending"
    assert _login(client, "kim", "wrong").status_code == 401
    # 중복 가입
    assert client.post("/api/auth/signup",
                       json={"username": "kim", "password": "xxxx"}).status_code == 409
    # 승인 후 로그인 (관리자 API 경유는 test_admin.py — 여기선 저장소 직접)
    client.app.state.users.update("kim", status="active")
    assert _login(client, "kim", "pw1234").status_code == 200
    assert client.get("/api/auth/me").json()["user"]["role"] == "user"


def test_rejected_cookie_stops_working(client):
    """이미 발급된 쿠키도 거절 즉시 무효 — role·status는 쿠키가 아니라 저장소가 정본."""
    client.post("/api/auth/signup", json={"username": "kim", "password": "pw1234"})
    client.app.state.users.update("kim", status="active")
    _login(client, "kim", "pw1234")
    assert client.get("/api/jobs").status_code == 200
    client.app.state.users.update("kim", status="rejected")
    assert client.get("/api/jobs").status_code == 401


def test_signup_rejects_bad_input(client):
    assert client.post("/api/auth/signup",
                       json={"username": "한글만", "password": "pw1234"}).status_code == 422
    assert client.post("/api/auth/signup",
                       json={"username": "kim", "password": ""}).status_code == 422


def test_ws_requires_cookie(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws/jobs/nope"):
            pass
    assert exc.value.code == 1008
    token = _login(client, "admin", "root-pw").cookies[sessions.COOKIE]
    headers = {"cookie": f"{sessions.COOKIE}={token}"}
    with client.websocket_connect("/api/ws/jobs/nope", headers=headers) as ws:
        assert "error" in ws.receive_json()  # 인증 통과 → 기존 미존재 작업 에러


def test_mode_selection(tmp_path):
    """admin_password가 있으면 세션이 이기고, 없으면 기존 Basic, 둘 다 없으면 개방."""
    both = create_app(data_dir=tmp_path / "a",
                      admin_password="s", access_password="b", session_secret="x")
    with TestClient(both) as c:
        r = c.get("/api/jobs")
        assert r.status_code == 401 and "www-authenticate" not in r.headers
        assert c.get("/api/auth/me").json()["mode"] == "session"
    basic = create_app(data_dir=tmp_path / "b", admin_password="", access_password="b")
    with TestClient(basic) as c:
        r = c.get("/api/jobs")
        assert r.status_code == 401 and "www-authenticate" in r.headers
        assert c.get("/api/auth/me", auth=("x", "b")).json()["mode"] == "basic"
    open_ = create_app(data_dir=tmp_path / "c", admin_password="", access_password="")
    with TestClient(open_) as c:
        assert c.get("/api/jobs").status_code == 200
        assert c.get("/api/auth/me").json() == {"mode": "open", "user": None}
        # 세션 모드가 아니면 로그인·가입은 기능 자체가 없다 (형식은 유효한 입력으로)
        assert c.post("/api/auth/login",
                      json={"username": "a", "password": "bbbb"}).status_code == 404
        assert c.post("/api/auth/signup",
                      json={"username": "a", "password": "bbbb"}).status_code == 404
