"""앱 팩토리 검증 — 헬스체크, 결과 저장 루트 생성."""

from fastapi.testclient import TestClient

from claw_server import create_app


def test_create_app_and_health(tmp_path):
    app = create_app(data_dir=tmp_path / "store")
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["jobs"] == 0
    assert (tmp_path / "store").is_dir()  # 저장 루트 생성 확인
