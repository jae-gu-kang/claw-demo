"""트림 배치 라우트 검증 — 제출→진행률→결과 저장·조회 end-to-end, 취소, 422.

02 §8 워크플로우 2단계(케이스 매트릭스 → 배치 트림 → 결과표)의 서버 계층.
판정 플래그·연속성·지문은 엔진 trim_batch 산출을 그대로 노출해야 한다.
"""


def test_trim_batch_end_to_end(client, wait_job):
    # 프로펠러 추력 모델로 수평비행 상단이 1000 m에서 M0.58까지 내려왔다 —
    # 종전 격자(0.5·0.6·0.7)의 위 둘은 이제 수렴하지 않는다 (plant/prop.py)
    cases = [{"mach": m, "alt": 1000.0, "fuel": 200.0} for m in (0.40, 0.45, 0.50)]
    r = client.post(
        "/api/trim/batch", json={"cases": cases, "fingerprint": "fp-web"}
    )
    assert r.status_code == 202
    submitted = r.json()
    assert submitted["kind"] == "trim_batch"

    j = wait_job(submitted["id"])
    assert j["status"] == "done"
    assert j["progress"] == 1.0 and j["done"] == 3 and j["total"] == 3
    assert j["result_id"] == j["id"]
    assert j["error"] is None

    body = client.get(f"/api/results/{j['result_id']}").json()
    results = body["results"]
    assert len(results) == 3
    assert all(res["converged"] for res in results)
    assert results[0]["case"]["name"] == "M0.40_h1000_f200"  # 이름 자동 생성
    assert results[0]["flags"]["continuity_ok"] is None  # 첫 케이스 미판정
    assert results[1]["flags"]["continuity_ok"] is True  # 인접 시드 연속성 (엔진 판정)
    assert all(res["params_fingerprint"] == "fp-web" for res in results)
    # 물리 경향 보존 확인 (엔진 값 통과 — 마하 증가 → 트림 α=θ 감소)
    thetas = [res["euler"][1] for res in results]
    assert thetas[0] > thetas[1] > thetas[2]

    lst = client.get("/api/results").json()
    assert [m["id"] for m in lst] == [j["result_id"]]
    assert lst[0]["kind"] == "trim_batch" and lst[0]["n"] == 3
    assert lst[0]["fingerprint"] == "fp-web"

    jobs = client.get("/api/jobs").json()
    assert [jb["id"] for jb in jobs] == [j["id"]]


def test_trim_batch_cancel_partial(client, wait_job, monkeypatch):
    """취소 → 부분 결과 저장. 데모 트림이 케이스당 ~1 ms라 실배치는 취소 도착 전
    완주하는 레이스가 있음 — 진행 콜백을 취소 신호 대기 게이트로 감싸 결정론화."""
    import time as _time

    import claw_server.routes.trim as trim_route

    real_batch = trim_route.trim_batch

    def gated_batch(ac, cases, fingerprint="", on_progress=None):
        deadline = _time.time() + 10.0

        def gated_progress(done, total, tr):
            cancelled = on_progress(done, total, tr)
            while not cancelled and _time.time() < deadline:
                _time.sleep(0.005)
                cancelled = on_progress(done, total, tr)
            return cancelled

        return real_batch(ac, cases, fingerprint=fingerprint, on_progress=gated_progress)

    monkeypatch.setattr(trim_route, "trim_batch", gated_batch)

    cases = [{"mach": 0.5 + 0.05 * i, "alt": 1000.0, "fuel": 200.0} for i in range(5)]
    jid = client.post("/api/trim/batch", json={"cases": cases}).json()["id"]
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    j = wait_job(jid)
    assert j["status"] == "cancelled"
    # 협조적 취소 — 첫 케이스 완료 후 취소 감지, 부분 결과가 저장됨
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert len(body["results"]) == 1


def test_trim_batch_validation_422(client):
    assert client.post("/api/trim/batch", json={"cases": []}).status_code == 422
    bad = {"cases": [{"mach": -0.5, "alt": 0.0, "fuel": 0.0}]}
    assert client.post("/api/trim/batch", json=bad).status_code == 422
    unknown_ac = {"aircraft": "f16", "cases": [{"mach": 0.5, "alt": 0.0, "fuel": 0.0}]}
    assert client.post("/api/trim/batch", json=unknown_ac).status_code == 422


def test_trim_batch_nonfinite_rejected_422(client):
    """JSON Infinity/NaN 리터럴은 제출 시점 422 — 202 수락 후 저장 시점 배치
    전멸(allow_nan=False ValueError → job error)을 막는 경계 검증 (리뷰 M1).

    파이썬 json.loads는 비표준 Infinity/NaN 리터럴을 허용하므로 raw body로 전송
    (httpx의 json=은 자체적으로 거부해 실제 위협 경로를 재현하지 못함)."""
    for body in (
        '{"cases": [{"mach": Infinity, "alt": 1000.0, "fuel": 200.0}]}',
        '{"cases": [{"mach": 0.6, "alt": NaN, "fuel": 200.0}]}',
        '{"cases": [{"mach": 0.6, "alt": 1000.0, "fuel": Infinity}]}',
    ):
        r = client.post(
            "/api/trim/batch",
            content=body,
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422, body


def test_trim_batch_location_header(client):
    r = client.post(
        "/api/trim/batch",
        json={"cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]},
    )
    assert r.headers["location"] == f"/api/jobs/{r.json()['id']}"
