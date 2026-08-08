"""마진 맵 라우트 검증 — 02 §8 워크플로우 3단계 (트림점별 선형화 → 안정성·마진 맵).

케이스 격자 + 루프 스펙 → 배치 작업: 트림→선형화→모드 분류→PI 개루프 마진.
엔진 값 통과(고유치·감쇠비·마진)와 요청 검증(축 이름·중복 루프)을 핀한다.
"""


def _margin_map_request(machs=(0.5, 0.6, 0.7)):
    return {
        "cases": [{"mach": m, "alt": 1000.0, "fuel": 200.0} for m in machs],
        "loops": [
            {"name": "pitch_q", "axis": "lon", "x_out": "q", "u_in": "de",
             "kp": 0.5, "ki": 0.8},
        ],
        "fingerprint": "fp-mm",
    }


def test_margin_map_end_to_end(client, wait_job):
    r = client.post("/api/analysis/margin-map", json=_margin_map_request())
    assert r.status_code == 202
    j = wait_job(r.json()["id"])
    assert j["status"] == "done"
    assert j["done"] == j["total"] == 6  # 트림 패스 3 + 해석 패스 3

    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["kind"] == "margin_map"
    entries = body["cases"]
    assert len(entries) == 3
    for e in entries:
        assert e["trim"]["converged"] is True
        # 모드 분류 (엔진 classify 통과) — 단주기가 장주기보다 빠름
        sp = e["lon"]["classified"]["short_period"]
        ph = e["lon"]["classified"]["phugoid"]
        assert sp["wn"] > ph["wn"] > 0.0
        assert isinstance(sp["eig"], list) and len(sp["eig"]) == 2  # 복소 → [re, im]
        assert e["lat"]["classified"]["dutch_roll"]["wn"] > 0.5
        # 마진 (엔진 pi_loop+loop_margins 통과) — 데모 피치 루프 PM > 20°
        m = e["margins"]["pitch_q"]
        assert m["pm_deg"] > 20.0
    # 고유치 원자료도 포함 (고유치 맵 대시보드용)
    assert len(entries[0]["lon"]["modes"]) == 4
    assert len(entries[0]["lat"]["modes"]) == 4

    meta = client.get("/api/results").json()[0]
    assert meta["kind"] == "margin_map" and meta["fingerprint"] == "fp-mm"


def test_margin_map_infeasible_case_reported_not_fatal(client, wait_job):
    """트림 불가 케이스는 판정 플래그로 보고되고 해석은 건너뜀 — 작업은 완주."""
    req = {
        "cases": [
            {"mach": 0.6, "alt": 1000.0, "fuel": 200.0},
            {"name": "slow", "mach": 0.12, "alt": 100.0, "fuel": 400.0},  # 저속 저동압
        ],
        "loops": [],
    }
    j = wait_job(client.post("/api/analysis/margin-map", json=req).json()["id"])
    assert j["status"] == "done"
    body = client.get(f"/api/results/{j['result_id']}").json()
    ok, bad = body["cases"]
    assert ok["lon"] is not None
    tflags = bad["trim"]
    assert not (
        tflags["converged"]
        and tflags["flags"]["residual_ok"]
        and tflags["flags"]["alpha_margin_ok"]
    )
    assert bad["lon"] is None and bad["margins"] == {}  # 불가 케이스는 해석 생략


def test_vn_envelope_endpoint(client):
    """V-n 보호 경계 (01 §3.6) — 실속선·α 리미터 보호선, 구조 한계는 [TBD] null."""
    r = client.get("/api/analysis/vn-envelope", params={"alt": 1000.0, "fuel": 200.0})
    assert r.status_code == 200
    b = r.json()
    n = len(b["V"])
    assert n > 10 and len(b["n_stall"]) == len(b["n_prot"]) == len(b["mach"]) == n
    assert all(x < y for x, y in zip(b["n_stall"], b["n_stall"][1:]))  # 동압 V² 성장
    assert all(p < s for p, s in zip(b["n_prot"], b["n_stall"]))  # 보호선이 안쪽
    assert b["alpha_margin"] == 0.05  # α 리미터 [기본값]과 동일
    assert b["structural"] is None  # [TBD] — 서버가 값을 지어내지 않음
    # ISA 범위 밖 고도 → 엔진 ValueError → 422
    bad = client.get("/api/analysis/vn-envelope", params={"alt": 99999.0, "fuel": 200.0})
    assert bad.status_code == 422


def test_margin_map_loop_spec_validation_422(client):
    base = _margin_map_request()
    bad_x = dict(base, loops=[dict(base["loops"][0], x_out="psi")])  # 종축에 없는 상태
    assert client.post("/api/analysis/margin-map", json=bad_x).status_code == 422
    bad_u = dict(base, loops=[dict(base["loops"][0], u_in="da")])  # 종축에 없는 입력
    assert client.post("/api/analysis/margin-map", json=bad_u).status_code == 422
    dup = dict(base, loops=[base["loops"][0], base["loops"][0]])  # 이름 중복
    assert client.post("/api/analysis/margin-map", json=dup).status_code == 422
    bad_axis = dict(base, loops=[dict(base["loops"][0], axis="full")])
    assert client.post("/api/analysis/margin-map", json=bad_axis).status_code == 422
    # 무의미 루프 (제로 개루프) — 무의미 "inf" 마진 행 방지 (리뷰 Nit)
    zero_pi = dict(base, loops=[dict(base["loops"][0], kp=0.0, ki=0.0)])
    assert client.post("/api/analysis/margin-map", json=zero_pi).status_code == 422
    zero_sign = dict(base, loops=[dict(base["loops"][0], sign=0.0)])
    assert client.post("/api/analysis/margin-map", json=zero_sign).status_code == 422


def test_margin_map_cancel_preserves_trim_results(client, wait_job, monkeypatch):
    """취소 시 트림 완료분은 트림 전용 entry로 전량 보존 — 유실 금지 (리뷰 S1).

    트림 진행 콜백을 취소 대기 게이트로 감싸 결정론화 (트림 라우트 취소
    테스트와 동일 기법)."""
    import time as _time

    import claw_server.routes.analysis as analysis_route

    real_batch = analysis_route.trim_batch

    def gated_batch(ac, cases, fingerprint="", on_progress=None):
        deadline = _time.time() + 10.0

        def gated(done, total, tr):
            cancelled = on_progress(done, total, tr)
            while not cancelled and _time.time() < deadline:
                _time.sleep(0.005)
                cancelled = on_progress(done, total, tr)
            return cancelled

        return real_batch(ac, cases, fingerprint=fingerprint, on_progress=gated)

    monkeypatch.setattr(analysis_route, "trim_batch", gated_batch)
    cases = [{"mach": 0.5 + 0.05 * i, "alt": 1000.0, "fuel": 200.0} for i in range(4)]
    jid = client.post(
        "/api/analysis/margin-map", json={"cases": cases, "loops": []}
    ).json()["id"]
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    j = wait_job(jid)
    assert j["status"] == "cancelled"
    body = client.get(f"/api/results/{j['result_id']}").json()
    # 첫 케이스 트림 완료 후 취소 감지 — 해당 트림 결과가 해석 생략 entry로 보존
    assert len(body["cases"]) == 1
    entry = body["cases"][0]
    assert entry["trim"]["converged"] is True
    assert entry["lon"] is None and entry["margins"] == {}
