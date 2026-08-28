"""M13 서버 테스트 공통 픽스처 — 임시 저장 루트의 앱 + 작업 폴링 헬퍼."""

import time

import pytest
from fastapi.testclient import TestClient

from claw_server import create_app

TERMINAL = ("done", "error", "cancelled")


@pytest.fixture(autouse=True)
def _no_deploy_env(monkeypatch):
    """개발자 셸의 배포용 환경변수 오염 차단 — 테스트는 명시 주입만 쓴다."""
    for var in ("CLAW_ACCESS_PASSWORD", "CLAW_RESULT_LIMIT",
                "CLAW_WEB_DIR", "CLAW_SERVER_DATA"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "store")
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def wait_job(client):
    """작업 종단 상태 폴링 — 시간 초과 시 실패 (배치 작업은 실 스레드로 돈다)."""

    def _wait(job_id, timeout=60.0):
        deadline = time.time() + timeout
        j = None
        while time.time() < deadline:
            r = client.get(f"/api/jobs/{job_id}")
            assert r.status_code == 200
            j = r.json()
            if j["status"] in TERMINAL:
                return j
            time.sleep(0.02)
        raise AssertionError(f"작업 시간 초과: {j}")

    return _wait
