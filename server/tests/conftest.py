"""M13 서버 테스트 공통 픽스처 — 임시 저장 루트의 앱 + 작업 폴링 헬퍼."""

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claw.profile.document import EXAMPLE_OVERRIDE_ENV
from claw_server import create_app

# 서버 테스트·골든도 구 합성 기체(1200 kg 회귀 픽스처) 기준이다 — 엔진 conftest와 같은 문서(02 §5.6.1)
LEGACY_EXAMPLE = Path(__file__).resolve().parents[2] / "engine" / "claw" / "tests" / "fixtures" / "delta_legacy.json"
os.environ[EXAMPLE_OVERRIDE_ENV] = str(LEGACY_EXAMPLE)

TERMINAL = ("done", "error", "cancelled")


@pytest.fixture(autouse=True)
def _no_deploy_env(monkeypatch):
    """개발자 셸의 배포용 환경변수 오염 차단 — 테스트는 명시 주입만 쓴다."""
    for var in ("CLAW_ACCESS_PASSWORD", "CLAW_RESULT_LIMIT",
                "CLAW_WEB_DIR", "CLAW_SERVER_DATA", "CLAW_PROFILE_DATA", "CLAW_PROFILE_VOLATILE",
                # 배포 형상 변수 — 로컬에서 재현하느라 켜 뒀을 수 있다
                "CLAW_GIT_COMMIT", "RENDER_GIT_COMMIT",
                # LLM 백엔드 — 셸의 진짜 키·사내 URL로 테스트가 바깥에 나가면
                # 안 되고, "미설정" degrade 테스트가 셸 환경에 뒤집혀도 안 된다
                "CLAW_ANTHROPIC_API_KEY", "CLAW_ANTHROPIC_MODEL",
                "CLAW_LLM_BASE_URL", "CLAW_LLM_MODEL", "CLAW_LLM_API_KEY"):
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


@pytest.fixture()
def unseeded_doc():
    """게인이 빈 기체 문서 공장 — 새 기체의 첫 상태(초기 게인 빠른 탐색 전). 「미설계」의 정의가 여기
    한 벌이다(v1.28~29에서 다섯 테스트 파일에 복제됐던 헬퍼). keep_design=True면 설계는 남기고
    스케줄만 비운다(카탈로그의 /law/schedule 경로 시험)."""
    from claw.profile import load_example

    def make(pid, *, keep_design=False):
        d = load_example()
        d.update(id=pid, name="게인 없는 기체", is_example=False, variants=[])
        if not keep_design:
            d["law"]["design"] = None
            d["law"]["alloc"] = None
        d["law"]["schedule"] = None
        return d

    return make
