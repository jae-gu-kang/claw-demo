"""앱 팩토리 검증 — 헬스체크, 결과 저장 루트 생성, 정적 웹 서빙 (M14 진입점)."""

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


def test_static_web_served(tmp_path):
    """모노레포 web/ 정적 서빙 — no-build ESM 진입점 (서버 1대 = 배포 전체)."""
    app = create_app(data_dir=tmp_path / "store")
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        js = client.get("/js/main.js")
        assert js.status_code == 200
        assert client.get("/api/health").status_code == 200  # API 라우트 우선 유지


def test_validation_422_ctx_types_preserved(tmp_path):
    """422 소독 핸들러 — ctx 수치 타입 보존(문자열화 금지), 예외 객체만 str화,
    url 제거 (리뷰 Nit)."""
    app = create_app(data_dir=tmp_path / "store")
    with TestClient(app) as client:
        r = client.post(
            "/api/trim/batch",
            json={"cases": [{"mach": -1.0, "alt": 0.0, "fuel": 0.0}]},
        )
        assert r.status_code == 422
        err = r.json()["detail"][0]
        assert err["ctx"]["gt"] == 0.0  # 숫자 유지
        assert "url" not in err
        # malformed JSON — ctx의 예외 객체는 문자열로
        r2 = client.post(
            "/api/trim/batch", content="{bad", headers={"content-type": "application/json"}
        )
        assert r2.status_code == 422
        e2 = r2.json()["detail"][0]
        if "ctx" in e2:
            assert all(isinstance(v, (str, int, float, bool, type(None)))
                       for v in e2["ctx"].values())


def test_missing_web_dir_keeps_api(tmp_path):
    """web 디렉터리가 없어도 API 서버는 정상 (엔진 우선 원칙 — UI는 별도 층)."""
    app = create_app(data_dir=tmp_path / "store", web_dir=tmp_path / "no-web")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 404
