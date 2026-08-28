"""접근 보호 검증 — 옵트인 Basic Auth: http 401/허용, 헬스체크 면제, WS 거절."""

import base64

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from claw_server import create_app


def _basic(password, user="x"):
    tok = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return {"authorization": f"Basic {tok}"}


@pytest.fixture()
def guarded(tmp_path):
    app = create_app(data_dir=tmp_path / "store", access_password="pw")
    with TestClient(app) as c:
        yield c


def test_http_requires_password(guarded):
    for path in ("/", "/api/jobs"):  # 정적 웹·API 둘 다 보호
        r = guarded.get(path)
        assert r.status_code == 401
        assert r.headers["www-authenticate"].startswith("Basic")
    assert guarded.get("/", headers=_basic("pw")).status_code == 200
    # 아이디는 무엇이든 통과, 비밀번호만 비교
    assert guarded.get("/api/jobs", headers=_basic("pw", user="아무개")).status_code == 200
    assert guarded.get("/api/jobs", headers=_basic("wrong")).status_code == 401
    # 깨진 자격(비 base64)은 500이 아니라 401
    assert guarded.get("/api/jobs", headers={"authorization": "Basic %%%"}).status_code == 401


def test_health_exempt(guarded):
    """배포 플랫폼 헬스체크는 자격 없이 온다 — /api/health만 면제."""
    assert guarded.get("/api/health").status_code == 200


def test_ws_requires_password(guarded):
    """웹소켓도 보호 — BaseHTTPMiddleware였다면 무방비로 통과했을 경로."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with guarded.websocket_connect("/api/ws/jobs/nope"):
            pass
    assert exc.value.code == 1008  # policy violation — 거절 사유까지 고정
    # 자격이 실리면 기존 동작 그대로 (routes/test_jobs.py의 미존재 작업 에러)
    with guarded.websocket_connect("/api/ws/jobs/nope", headers=_basic("pw")) as ws:
        assert "error" in ws.receive_json()


def test_empty_password_means_open(tmp_path):
    """비밀번호 미설정(빈 값) = 현행 무인증 그대로 (회귀 방어)."""
    app = create_app(data_dir=tmp_path / "store", access_password="")
    with TestClient(app) as c:
        assert c.get("/api/jobs").status_code == 200
        assert c.get("/").status_code == 200
