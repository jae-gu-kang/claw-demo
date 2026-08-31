"""마진 맵 라우트 검증 — 02 §8 워크플로우 3단계 (트림점별 선형화 → 안정성·마진 맵).

케이스 격자 + 루프 스펙 → 배치 작업: 트림→선형화→모드 분류→PI 개루프 마진.
엔진 값 통과(고유치·감쇠비·마진)와 요청 검증(축 이름·중복 루프)을 핀한다.
"""

import pytest


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
    """V-n 선도 (01 §3.6) — 실속·보호 곡선 + 구조 한계선(프로파일 자리표시) +
    특성 속도. 한계값 출처는 데모 자리표시임을 응답이 자기서술."""
    r = client.get("/api/analysis/vn-envelope", params={"alt": 1000.0, "fuel": 200.0})
    assert r.status_code == 200
    b = r.json()
    n = len(b["V"])
    assert n > 10 and len(b["n_stall"]) == len(b["n_prot"]) == len(b["mach"]) == n
    assert all(x < y for x, y in zip(b["n_stall"], b["n_stall"][1:]))  # 동압 V² 성장
    assert all(p < s for p, s in zip(b["n_prot"], b["n_stall"]))  # 보호선이 안쪽
    assert b["alpha_margin"] == 0.05  # α 리미터 [기본값]과 동일
    lim = b["limits"]
    assert lim["n_ultimate_pos"] == lim["n_limit_pos"] * lim["safety_factor"]
    assert 0.0 < lim["v_no"] < lim["v_d"]
    sp = b["speeds"]
    assert 0.0 < sp["v_s"] < sp["v_a"] < lim["v_d"]  # V_S < V_A < V_D
    assert b["limits_source"] == "demo-placeholder"  # 실기체 값 아님 자기서술
    # 음의 실속 자리표시 — 전부 음수, ratio echo (웹 명기 표시 근거)
    assert len(b["n_stall_neg"]) == n
    assert all(v < 0.0 for v in b["n_stall_neg"])
    assert b["neg_alpha_ratio"] == 0.6
    # 포물선 뿌리 — 격자 시작이 저마하(첫 n_stall ≈ 0 부근)
    assert b["n_stall"][0] < 0.05
    # 비기본 ratio가 엔진까지 전달되는 배선 고정 — 기본값 echo만으론 라우트의
    # neg_alpha_ratio= 전달 누락 회귀를 못 잡음 (리뷰 Should fix)
    r2 = client.get("/api/analysis/vn-envelope",
                    params={"alt": 1000.0, "fuel": 200.0, "neg_alpha_ratio": 0.4})
    b2 = r2.json()
    assert b2["neg_alpha_ratio"] == 0.4
    assert b2["n_stall_neg"][20] == pytest.approx(-0.4 * b2["n_stall"][20], rel=1e-9)
    # ISA 범위 밖 고도 → 엔진 ValueError → 422
    bad = client.get("/api/analysis/vn-envelope", params={"alt": 99999.0, "fuel": 200.0})
    assert bad.status_code == 422
    # ratio 범위 위반 → 422 (경계 검증)
    bad2 = client.get("/api/analysis/vn-envelope",
                      params={"alt": 1000.0, "fuel": 200.0, "neg_alpha_ratio": 0.0})
    assert bad2.status_code == 422


def test_vn_envelope_limit_overrides(client):
    """필요값 입력(01 §2.6) — 구조 한계 오버라이드가 엔진까지 전달되고 출처가
    echo된다. 부호·서열 위반은 엔진 검증 → 422."""
    r = client.get("/api/analysis/vn-envelope",
                   params={"alt": 1000.0, "fuel": 200.0, "mach_no": 0.6, "n_limit_pos": 4.0})
    assert r.status_code == 200
    b = r.json()
    assert b["limits"]["mach_no"] == 0.6 and b["limits"]["n_limit_pos"] == 4.0
    assert b["limits"]["n_ultimate_pos"] == pytest.approx(4.0 * 1.5)  # 나머지는 데모가 채움
    assert b["limits_source"] == "user-input"
    assert sorted(b["limits_overridden"]) == ["mach_no", "n_limit_pos"]
    # V_NO도 오버라이드 반영 (mach_no × a) — 단순 echo가 아니라 계산 경유
    assert b["limits"]["v_no"] == pytest.approx(b["limits"]["v_d"] * 0.6 / 0.9, rel=1e-9)
    bad = client.get("/api/analysis/vn-envelope",
                     params={"alt": 1000.0, "fuel": 200.0, "n_limit_neg": 1.0})
    assert bad.status_code == 422  # 음수여야 함 — 엔진 _check_limits


def test_design_envelope_endpoint(client):
    """설계 엔벨로프 M-h 합성 + 공력 선도 (01 §2.6) — 형태·귀속·null 정책."""
    r = client.get("/api/analysis/design-envelope", params={"fuel": 200.0})
    assert r.status_code == 200
    b = r.json()
    reg = b["region"]
    n = len(reg["alt"])
    assert n > 10
    for key in ("mach_lo", "mach_hi", "lo_source", "hi_source", "empty"):
        assert len(reg[key]) == n
    # q̄·운용 고도 미지정 — 경계 없음 (없는 데이터를 만들지 않는다)
    assert b["bounds"]["qbar_mach"] is None and b["bounds"]["q_max"] is None
    assert b["bounds"]["alt_min"] is None and b["bounds"]["alt_max"] is None
    assert b["bounds"]["alt_max_is_display_default"] is True
    assert b["limits_source"] == "demo-placeholder" and b["limits_overridden"] == []
    # 스케줄 격자 좌표 존재 (coarse 격자 정본 — trimmable 미판정 좌표)
    assert len(b["schedule_grid"]["points"]) > 0
    # 공력 선도 블록 — 보호선 = 실속 − α마진 [기본값 0.05], 트림 α 범위 주입 echo
    aero = b["aero"]
    assert aero["alpha_prot"][0] == pytest.approx(aero["alpha_stall"][0] - 0.05, rel=1e-9)
    assert aero["trim_alpha_bounds"] == [-0.10, 0.35]
    assert aero["db"]["mach"] == [0.1, 0.9]

    # q̄ 한계 지정 — 저고도에서 qbar가 상한 승자
    r2 = client.get("/api/analysis/design-envelope", params={"fuel": 200.0, "q_max": 20000.0})
    b2 = r2.json()
    assert b2["bounds"]["qbar_mach"] is not None
    assert b2["region"]["hi_source"][0] == "qbar"
    # 구조 오버라이드 공유 계약 (vn-envelope와 동일)
    r3 = client.get("/api/analysis/design-envelope", params={"fuel": 200.0, "mach_no": 0.6})
    assert r3.json()["bounds"]["mach_no"] == 0.6
    assert r3.json()["limits_source"] == "user-input"
    # ISA 밖·서열 위반 → 엔진 ValueError → 422
    assert client.get("/api/analysis/design-envelope",
                      params={"fuel": 200.0, "alt_max": 99999.0}).status_code == 422
    assert client.get("/api/analysis/design-envelope",
                      params={"fuel": 200.0, "alt_min": 5000.0, "alt_max": 1000.0}).status_code == 422
    # 비유한 연료 → 422 — fuel_max로 조용히 잘린 정상 차트 + 거짓 echo 방지 (서버 유한성 경계)
    assert client.get("/api/analysis/design-envelope",
                      params={"fuel": "inf"}).status_code == 422
    assert client.get("/api/analysis/vn-envelope",
                      params={"alt": 1000.0, "fuel": "inf"}).status_code == 422


def test_design_envelope_maneuver_and_iso_params(client):
    """n_z·등고선 파라미터 — 미지정이면 엔진이 정하고, 지정하면 그대로 전달."""
    base = client.get("/api/analysis/design-envelope", params={"fuel": 200.0}).json()
    assert base["maneuver"] is None  # 미지정 = 기동 엔벨로프 자체가 없다
    assert [c["q"] for c in base["iso"]["qbar"]] == [5000.0, 10000.0, 20000.0, 40000.0]
    assert base["bounds"]["tropopause_alt"] == 11000.0  # 웹이 11000을 재기술하지 않도록

    man = client.get("/api/analysis/design-envelope",
                     params={"fuel": 200.0, "nz": 3.0}).json()
    assert man["maneuver"]["nz"] == 3.0 and man["maneuver"]["nz_over_limit"] is False
    mreg, reg = man["maneuver"]["region"], man["region"]
    assert all(a > b for a, b in zip(mreg["mach_lo"], reg["mach_lo"]))  # 안쪽
    assert sum(mreg["empty"]) > 0 and "n_reach" in mreg["lo_source"]
    # 구조 제한하중 초과는 422가 아니라 echo — 한계 밖을 보는 것도 정당한 탐색
    over = client.get("/api/analysis/design-envelope", params={"fuel": 200.0, "nz": 9.0})
    assert over.status_code == 200 and over.json()["maneuver"]["nz_over_limit"] is True

    iso = client.get("/api/analysis/design-envelope",
                     params={"fuel": 200.0, "iso_qbar": "1000, 2000", "iso_tas": "120"}).json()
    assert [c["q"] for c in iso["iso"]["qbar"]] == [1000.0, 2000.0]
    assert [c["v"] for c in iso["iso"]["tas"]] == [120.0]
    # 비수치·비유한·비양수 목록과 비양수 n_z → 422
    for params in ({"iso_qbar": "1000, 어"}, {"iso_tas": "inf"}, {"nz": 0.0}, {"nz": -1.0},
                   {"iso_tas": "0"}, {"iso_tas": "-100"}, {"iso_qbar": "0"}):
        assert client.get("/api/analysis/design-envelope",
                          params={"fuel": 200.0, **params}).status_code == 422


def test_iso_value_count_is_bounded(client):
    """등고선 개수 상한 — MAX_SCAN_CASES와 같은 이유(단일 워커 점유 차단).

    값 하나가 표시 41행마다 대기 계산을 돌리고 응답에 41개 수를 더한다. 상한이
    없으면 15 KB 쿼리 하나가 2.4 MB 응답이 되며, 공격이 아니라 CSV 한 열을
    붙여넣는 실수로 닿는다.
    """
    from claw_server.routes.analysis import MAX_ISO_VALUES

    ok = ",".join(str(1000 + i) for i in range(MAX_ISO_VALUES))
    r = client.get("/api/analysis/design-envelope", params={"fuel": 200.0, "iso_qbar": ok})
    assert r.status_code == 200 and len(r.json()["iso"]["qbar"]) == MAX_ISO_VALUES
    too_many = ",".join(str(1000 + i) for i in range(MAX_ISO_VALUES + 1))
    over = client.get("/api/analysis/design-envelope",
                      params={"fuel": 200.0, "iso_qbar": too_many})
    assert over.status_code == 422 and "상한" in over.json()["detail"]
    # 같은 상한이 등속선에도 걸린다 (두 파라미터가 같은 계약)
    assert client.get("/api/analysis/design-envelope",
                      params={"fuel": 200.0, "iso_tas": too_many}).status_code == 422


def test_envelope_scan_round_trip(client, wait_job):
    """제어 가능 영역 스캔 (01 §2.6) — 트림 잡 + envelope_ok 정본 판정·사유 귀속."""
    cases = [
        {"mach": 0.6, "alt": 1000.0, "fuel": 200.0},
        {"mach": 0.7, "alt": 1000.0, "fuel": 200.0},
        {"name": "slow", "mach": 0.12, "alt": 100.0, "fuel": 400.0},  # 저속 저동압 — 비성립
    ]
    r = client.post("/api/analysis/design-envelope-scan",
                    json={"cases": cases, "fingerprint": "fp-env"})
    assert r.status_code == 202
    j = wait_job(r.json()["id"])
    assert j["status"] == "done"
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["kind"] == "envelope_scan" and body["n_requested"] == 3
    entries = body["cases"]
    assert len(entries) == 3
    ok0, ok1, bad = entries
    assert ok0["verdict"]["ok"] is True and ok0["verdict"]["reasons"] == []
    assert bad["trim"]["case"]["name"] == "slow"
    assert bad["verdict"]["ok"] is False and len(bad["verdict"]["reasons"]) > 0
    # 스로틀 소요가 페이로드에 있음 — 추진 선도(스로틀 히트맵)의 데이터 근거
    assert 0.0 <= ok0["trim"]["control"]["throttle"][0] <= 1.0
    meta = client.get("/api/results").json()[0]
    assert meta["kind"] == "envelope_scan" and meta["fingerprint"] == "fp-env"


def test_envelope_scan_cases_cap_422(client):
    """201케이스 → 422 — 오타 격자의 단일 워커 점유 차단 (영향성 MAX_CASES 원칙)."""
    cases = [{"mach": 0.3 + 0.001 * i, "alt": 1000.0, "fuel": 200.0} for i in range(201)]
    assert client.post("/api/analysis/design-envelope-scan",
                       json={"cases": cases}).status_code == 422


def test_envelope_scan_cancel_preserves_partial(client, wait_job, monkeypatch):
    """취소 시 완료 트림·판정 보존 — 마진 맵과 같은 협조적 취소 계약."""
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
    jid = client.post("/api/analysis/design-envelope-scan", json={"cases": cases}).json()["id"]
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    j = wait_job(jid)
    assert j["status"] == "cancelled"
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert len(body["cases"]) == 1  # 첫 케이스 완료 후 취소 감지 — 판정 포함 보존
    assert body["cases"][0]["verdict"]["ok"] is True


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


def test_margin_map_actuator_and_delay_included_reduce_margins(client, wait_job):
    """actuator·delay_s 지정 시 엔진 pi_loop로 전달되어 마진이 낮아짐 (01 §4.2
    [기본값] — 제외 마진은 낙관적). 결과에 적용값이 echo되어 열람 시 재확인 가능."""
    base = _margin_map_request(machs=(0.6,))
    j0 = wait_job(client.post("/api/analysis/margin-map", json=base).json()["id"])
    base_pm = client.get(f"/api/results/{j0['result_id']}").json()["cases"][0]["margins"]["pitch_q"]["pm_deg"]

    req = dict(base, actuator={"wn": 30.0, "zeta": 0.7}, delay_s=0.035, pade_order=2)
    j1 = wait_job(client.post("/api/analysis/margin-map", json=req).json()["id"])
    body = client.get(f"/api/results/{j1['result_id']}").json()
    assert body["actuator"] == {"wn": 30.0, "zeta": 0.7}
    assert body["delay_s"] == 0.035 and body["pade_order"] == 2
    with_both_pm = body["cases"][0]["margins"]["pitch_q"]["pm_deg"]
    assert with_both_pm < base_pm  # 실측: 91.0° → -76.3° (M0.6 kp=0.5·ki=0.8, 엔진 테스트와 동일 기체)


def test_margin_map_default_actuator_delay_absent_matches_prior_behavior(client, wait_job):
    """actuator·delay_s 미지정 — 결과에 actuator=null·delay_s=0.0 echo, 마진은
    플랜트 단독 (하위호환 — 기존 계약 불변)."""
    j = wait_job(client.post("/api/analysis/margin-map", json=_margin_map_request()).json()["id"])
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["actuator"] is None
    assert body["delay_s"] == 0.0 and body["pade_order"] == 2


def test_margin_map_actuator_delay_validation_422(client):
    base = _margin_map_request()
    for bad in (
        dict(base, actuator={"wn": 0.0, "zeta": 0.7}),   # wn 비양수
        dict(base, actuator={"wn": 30.0, "zeta": -0.1}),  # zeta 비양수
        dict(base, delay_s=-0.01),                        # 음수 지연
        dict(base, pade_order=0),                         # 1 미만 차수
    ):
        assert client.post("/api/analysis/margin-map", json=bad).status_code == 422, bad


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


_BODE_CASE = {"name": "", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}
_YAW_LOOP = {"name": "yaw_rate", "axis": "lat", "x_out": "r", "u_in": "dr",
             "kp": 0.8, "ki": 0.0, "sign": -1.0}
_PITCH_LOOP = {"name": "pitch_rate", "axis": "lon", "x_out": "q", "u_in": "de",
               "kp": 0.5, "ki": 0.0, "sign": -1.0}


def test_bode_opens_every_converged_cell_and_agrees_with_it(client, wait_job):
    """수렴한 칸은 **전부** 열리고 마진이 칸과 일치한다 — 격자 여러 칸으로 본다.

    마진 맵은 `trim_batch`가 직전 수렴해로 웜스타트한다(웹이 serpentine 순서를 쓰는
    이유). 드릴다운이 냉간으로 다시 풀면 다른 선형화점에 앉아, 색칠된 칸이 **여기서만
    미수렴**이 나 422가 되기도 한다 — 실측으로 M0.85가 그랬다. 그래서 호출자가 칸의
    트림 해를 z0로 넘긴다. 한 칸짜리 격자로는 z_prev가 None이라 두 경로가 똑같이
    냉간 트림을 해서 이 결함이 안 보인다 — 격자를 여럿으로 두는 것이 이 테스트의 요점.
    """
    act = {"wn": 30.0, "zeta": 0.7}
    cases = [{"name": "", "mach": m, "alt": 0.0, "fuel": 200.0} for m in (0.65, 0.75, 0.85)]
    mm = client.post("/api/analysis/margin-map", json={
        "cases": cases, "loops": [_PITCH_LOOP], "actuator": act, "delay_s": 0.035})
    assert mm.status_code == 202
    job = wait_job(mm.json()["id"])
    entries = client.get(f"/api/results/{job['result_id']}").json()["cases"]
    assert sum(e["trim"]["converged"] for e in entries) >= 3  # 픽스처 전제

    for e in entries:
        t = e["trim"]
        z0 = [t["euler"][1], t["control"]["elevon"][0], t["control"]["throttle"][0]]
        b = client.post("/api/analysis/bode", json={
            "case": t["case"], "loop": _PITCH_LOOP, "actuator": act,
            "delay_s": 0.035, "z0": z0})
        assert b.status_code == 200, f"{t['case']['name']}: {b.json()}"
        got, want = b.json()["margins"], e["margins"]["pitch_rate"]
        # 같은 선형화점이므로 일치한다. 재풀이라 비트일치는 보장하지 않는다 —
        # 보장한다고 적으면 지키지 못할 약속이 된다
        for k in ("pm_deg", "wcp"):
            assert got[k] == pytest.approx(want[k], rel=1e-6, abs=1e-9), (k, t["case"]["name"])
    # z0 없이 부르면 냉간 트림이라 열리지 않을 수 있다 — 사유에 그 수단을 적어 준다
    cold = client.post("/api/analysis/bode", json={
        "case": entries[-1]["trim"]["case"], "loop": _PITCH_LOOP,
        "actuator": act, "delay_s": 0.035})
    if cold.status_code == 422:
        assert "z0" in cold.json()["detail"]


def test_bode_overlays_the_law_rate_filter_where_the_law_has_one(client):
    """법칙에 필터가 있는 자리는 두 곡선, 없는 자리는 사유 문장.

    마진 맵은 요축 워시아웃을 정적 게인으로 본다(01 §4.2 [한계]). 보드선도는 그
    한계를 없애는 대신 두 조립을 겹쳐 **차이의 크기를 보여준다** — 조용히 한 곡선만
    그리면 "이 자리엔 필터가 없다"와 "대응을 못 찾았다"가 구분되지 않는다.
    """
    body = {"case": _BODE_CASE, "loop": _YAW_LOOP}
    b = client.post("/api/analysis/bode", json=body).json()
    f = b["filtered"]
    assert f is not None and b["filtered_note"] is None
    assert f["filter"] == {"kind": "washout", "tau": 2.0}  # fcl.demo 정본
    assert f["margins"] != b["margins"]  # 필터가 실제로 마진을 움직인다
    assert f["w"] == b["w"]  # 같은 축이라야 겹쳐 비교가 성립
    # 필터 없는 자리는 거부가 아니라 사유
    p = client.post("/api/analysis/bode",
                    json={"case": _BODE_CASE, "loop": _PITCH_LOOP}).json()
    assert p["filtered"] is None and "선언이 없습니다" in p["filtered_note"]
    # 선언은 **그룹이 아니라 루프 자리**에 달려 있다 — 같은 yaw 그룹이라도 선언이
    # 없는 자리는 필터를 받으면 안 된다 (그룹만 키로 쓰면 자세 루프가 레이트
    # 워시아웃을 얻는 날이 온다). 요축 자세 자리는 GROUP_LOOPS에 선언이 없다
    yaw_att = {"name": "yaw_att", "axis": "lat", "x_out": "phi", "u_in": "dr",
               "kp": 0.4, "ki": 0.0, "sign": -1.0}
    ya = client.post("/api/analysis/bode",
                     json={"case": _BODE_CASE, "loop": yaw_att}).json()
    assert ya["filtered"] is None
    # GROUP_LOOPS에 선언이 없는 자리(v←dr — 사이드슬립 루프는 선언 안 됨)는
    # "필터가 없다"가 아니라 "대응을 못 찾았다"여야 한다 — 두 경우는 다른 사실이다
    undeclared = {"name": "sideslip", "axis": "lat", "x_out": "v", "u_in": "dr",
                  "kp": 0.3, "ki": 0.0, "sign": -1.0}
    a = client.post("/api/analysis/bode",
                    json={"case": _BODE_CASE, "loop": undeclared}).json()
    assert a["filtered"] is None
    assert "대응하는 법칙 자리" in a["filtered_note"]
    assert a["filtered_note"] != p["filtered_note"]


def test_bode_and_margin_map_agree_on_what_is_computable(client):
    """마진 맵이 받는 pade_order는 보드선도도 받는다 — 상한이 갈리면 모순이 난다.

    한쪽에만 상한을 두면 **마진 맵이 칠한 칸을 드릴다운이 거절**한다(z0 씨앗이
    없애려던 바로 그 모순이 다른 문으로 되돌아온다). 실제 실패 조건은 차수 하나가
    아니라 delay_s×pade_order 조합이라 상수 상한으로는 표현되지 않는다.
    """
    case = dict(_BODE_CASE)
    for order in (2, 20, 21):
        mm = client.post("/api/analysis/margin-map", json={
            "cases": [case], "loops": [_PITCH_LOOP], "delay_s": 0.035, "pade_order": order})
        bd = client.post("/api/analysis/bode", json={
            "case": case, "loop": _PITCH_LOOP, "delay_s": 0.035, "pade_order": order})
        assert mm.status_code == 202 and bd.status_code == 200, (order, bd.status_code)
    # 계수가 넘치는 조합은 사유가 파라미터를 지목한다 — 날것의 numpy 문장만 내보내면
    # 사용자가 자기 입력 형식이 틀렸다고 읽는다
    over = client.post("/api/analysis/bode", json={
        "case": case, "loop": _PITCH_LOOP, "delay_s": 0.035, "pade_order": 60})
    assert over.status_code == 422
    assert "pade_order" in over.json()["detail"] and "delay_s" in over.json()["detail"]
    # 더 높은 차수는 control 내부에서 0으로 나눈다 — ZeroDivisionError는 ValueError가
    # 아니라서 잡지 않으면 사유도 없는 500으로 샌다 (공개 동기 엔드포인트)
    for order in (95, 200):
        r = client.post("/api/analysis/bode", json={
            "case": case, "loop": _PITCH_LOOP, "delay_s": 0.035, "pade_order": order})
        assert r.status_code == 422, (order, r.status_code)
        assert "pade_order" in r.json()["detail"]


def test_bode_refuses_what_it_cannot_linearize(client):
    """트림이 없으면 선형화점이 없다 — 빈 곡선을 그려 정상인 척하지 않는다."""
    bad = client.post("/api/analysis/bode", json={
        "case": {"name": "", "mach": 0.02, "alt": 18000.0, "fuel": 400.0},
        "loop": _PITCH_LOOP})
    assert bad.status_code == 422 and "트림 미수렴" in bad.json()["detail"]
    # 축에 없는 상태·입력은 엔진 축 이름 검증이 잡는다 (마진 맵과 같은 계약)
    assert client.post("/api/analysis/bode", json={
        "case": _BODE_CASE, "loop": {**_PITCH_LOOP, "x_out": "phi"}}).status_code == 422
    # n_points 상한 — 교차 탐색 격자 폭주 차단
    assert client.post("/api/analysis/bode", json={
        "case": _BODE_CASE, "loop": _PITCH_LOOP, "n_points": 99999}).status_code == 422
