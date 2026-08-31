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
        # 정적 파일은 항상 재검증(no-cache) — 헤더 부재 시 브라우저 휴리스틱 캐시가
        # 일반 새로고침에서 구버전 ES 모듈을 재사용 ("수정했는데 안 바뀜" 함정).
        # ETag 재검증이라 미변경 파일은 304로 비용 없음. index.html 포함 전 응답.
        for resp in (r, js):
            assert resp.headers["cache-control"] == "no-cache"
        # 조건부 요청은 304로 응답 (재검증 경로가 실제로 동작하는지)
        etag = js.headers["etag"]
        assert client.get("/js/main.js", headers={"if-none-match": etag}).status_code == 304


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
        # 이 테스트가 보는 것은 **ctx 수치 타입 보존**이고 mach는 그 매개일 뿐이다.
        # 키가 gt에서 ge로 옮긴 것은 이륙·착륙 도입 때문이다 — 지상 평형은 mach=0을
        # 요구하므로 필드 제약을 ge로 풀고 조건별 하한은 검증기가 본다(TrimCaseIn).
        # mach=-1.0이 거부되는 것 자체는 그대로다.
        assert err["ctx"]["ge"] == 0.0  # 숫자 유지
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
