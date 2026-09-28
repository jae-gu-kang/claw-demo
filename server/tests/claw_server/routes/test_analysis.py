"""마진 맵 라우트 검증 — 02 §8 워크플로우 5단계 (트림점별 선형화 → 안정성·마진 맵).

케이스 격자 + 루프 스펙 → 배치 작업: 트림→선형화→모드 분류→PI 개루프 마진.
엔진 값 통과(고유치·감쇠비·마진)와 요청 검증(축 이름·중복 루프)을 핀한다.
"""

import pytest


# 프로펠러 전환으로 수평비행 상단이 1000 m·연료 200 kg에서 M0.595까지 내려왔다
# (plant/prop.py). M0.58은 **해면·연료 400 kg** 값이라 다른 줄이다.
# 이 파일의 기준 수치는 test_envelope_scan_round_trip의 "1000 m는 M0.22~0.595"이고,
# 그 0.595는 실측(경계 ~0.5995)을 house 관례대로 **안쪽으로 반올림**한 값이다
# (test_trim.py SEA_LEVEL_BAND와 같은 방식) — 경계 자체가 아니다
def _margin_map_request(machs=(0.35, 0.4, 0.45)):
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
        # 비행성 수준 판정 (엔진 fq 통과) — 분류된 모드마다 level이 있고 나선은
        # 안정(stable) 또는 배가 시간(t2_s) 중 하나를 말한다
        assert set(e["lon"]["fq"]) == {"short_period", "phugoid"}
        assert set(e["lat"]["fq"]) == {"dutch_roll", "roll", "spiral"}
        for judged in (*e["lon"]["fq"].values(), *e["lat"]["fq"].values()):
            assert judged["level"] in (1, 2, 3, None)
        spiral = e["lat"]["fq"]["spiral"]
        assert spiral["stable"] is (spiral["t2_s"] is None)
        # 마진 (엔진 pi_loop+loop_margins 통과) — 데모 피치 루프 PM > 20°
        m = e["margins"]["pitch_q"]
        assert m["pm_deg"] > 20.0
    # 고유치 원자료도 포함 (고유치 맵 대시보드용)
    assert len(entries[0]["lon"]["modes"]) == 4
    assert len(entries[0]["lat"]["modes"]) == 4
    # 판정선 동봉 — 화면 범례의 정본 (재기술 금지). 지문은 계보 키
    fq = body["fq_criteria"]
    assert fq["spiral_t2_l1"] == 20.0 and len(fq["fingerprint"]) == 16

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
    # 하한 0 — demo 계수 함수가 마하를 쓰지 않아 하한이 데이터의 성질이 아니었고,
    # 0.1(해면 34 m/s)이면 발사·착륙 미끄럼 구간 전체가 "DB 범위 밖"으로 찍혔다
    assert aero["db"]["mach"] == [0.0, 0.9]

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


def test_design_envelope_takes_q_max_and_operating_altitudes_from_the_document(client):
    """질의가 비면 기체 문서의 q_max·운용 고도 — 문서에 실기체 값이 있는데 폼이 비었다고 경계를 빼면 그 기체의
    엔벨로프가 아니다. 출처는 bounds_source로 칸마다, 문서 값을 하나라도 쓴 응답에만 싣는다(예제 골든 보존)."""
    from claw.profile import load_example

    d = load_example()
    d.update(id="ops-delta", name="운용 한계 기체", is_example=False, variants=[])
    d["structural"]["q_max"] = 20000.0
    d["operating"].update(alt_min=500.0, alt_max=6000.0)
    assert client.post("/api/profiles", json={"document": d}).status_code == 201
    base = {"fuel": 200.0, "profile_id": "ops-delta"}

    b = client.get("/api/analysis/design-envelope", params=base).json()
    assert (b["bounds"]["q_max"], b["bounds"]["alt_min"], b["bounds"]["alt_max"]) == (20000.0, 500.0, 6000.0)
    assert b["bounds"]["alt_max_is_display_default"] is False
    assert b["bounds"]["qbar_mach"] is not None and "qbar" in b["region"]["hi_source"]
    assert b["bounds_source"] == {"q_max": "profile", "alt_min": "profile", "alt_max": "profile"}
    assert b["limits_source"] == "profile"  # 구조 한계 출처(±n·M_NO·M_D)는 종전 필드 그대로
    # 질의가 이긴다 — 칸마다
    q = client.get("/api/analysis/design-envelope", params={**base, "q_max": 15000.0, "alt_max": 4000.0}).json()
    assert (q["bounds"]["q_max"], q["bounds"]["alt_min"], q["bounds"]["alt_max"]) == (15000.0, 500.0, 4000.0)
    assert q["bounds_source"] == {"q_max": "query", "alt_min": "profile", "alt_max": "query"}
    # 전부 질의가 주면 문서 값을 쓰지 않은 응답 — 종전 모양(키 없음)
    allq = client.get("/api/analysis/design-envelope",
                      params={**base, "q_max": 15000.0, "alt_min": 0.0, "alt_max": 4000.0}).json()
    assert "bounds_source" not in allq
    # 섞여서 서열이 어긋나면 사용자가 넣지 않은 문서 값을 사유에 밝힌다
    bad = client.get("/api/analysis/design-envelope", params={**base, "alt_min": 7000.0})
    assert bad.status_code == 422 and "기체 문서 값" in bad.json()["detail"] and "alt_max=6000" in bad.json()["detail"]
    # 문서 값이 전부 null인 예제는 종전 응답 그대로(서버 골든 design_envelope가 바이트로 지킨다)
    assert "bounds_source" not in client.get("/api/analysis/design-envelope", params={"fuel": 200.0}).json()


def test_design_envelope_maneuver_and_iso_params(client):
    """n_z·등고선 파라미터 — 미지정이면 엔진이 정하고, 지정하면 그대로 전달."""
    base = client.get("/api/analysis/design-envelope", params={"fuel": 200.0}).json()
    assert base["maneuver"] is None  # 미지정 = 기동 엔벨로프 자체가 없다
    assert [c["q"] for c in base["iso"]["qbar"]] == [5000.0, 10000.0, 20000.0, 40000.0]
    assert base["bounds"]["tropopause_alt"] == 11000.0  # 웹이 11000을 재기술하지 않도록
    # 상단 대기속도 보조축 기준 — 웹이 ISA 음속을 재기술하지 않도록 모서리 값이 온다
    assert base["bounds"]["speed_of_sound"]["alt_min_used"] == pytest.approx(340.294, abs=1e-3)
    assert base["bounds"]["speed_of_sound"]["alt_max_used"] == pytest.approx(295.070, abs=1e-3)

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
    # 앞 둘은 엔벨로프 **안**(1000 m·200 kg는 M0.21~0.595), 뒤 둘은 밖이어야 이 테스트가
    # 성립한다. 밖을 **두 사유로** 넣는 것이 요점이다 — 귀속이 실제로 갈리는지 본다.
    cases = [
        {"mach": 0.4, "alt": 1000.0, "fuel": 200.0},
        {"mach": 0.45, "alt": 1000.0, "fuel": 200.0},
        # 미수렴 + α 여유. v1.07부터 α 판정이 실속 표 기준(α < α_stall(M) − 0.035)이라 M0.16 아래에서는 판정
        # 한계가 탐색 상한 0.35 위로 올라가 해가 상한에 붙어도 α 여유는 통과한다(저속 가림) — 종전 M0.12는 사유가
        # 미수렴 하나로 줄었다. M0.20은 한계 0.340이라 상한 0.35에 붙은 해가 α 여유에서도 걸린다
        {"name": "slow", "mach": 0.2, "alt": 100.0, "fuel": 400.0},
        # M0.60은 thr 0.950438 — 문턱 0.95에서 **0.04%** 떨어진 칼날 위다. 기본값이나
        # ISA 보간이 조금만 움직여도 사유가 뒤집히고, 그때 실패는 "엔벨로프가 움직였다"로
        # 읽힌다. M0.605(thr 0.968)는 포화 문턱 0.596과 미수렴 0.615에서 거의 등거리다.
        {"name": "fast", "mach": 0.605, "alt": 1000.0, "fuel": 200.0},  # 수렴하지만 스로틀 포화
    ]
    r = client.post("/api/analysis/design-envelope-scan",
                    json={"cases": cases, "fingerprint": "fp-env"})
    assert r.status_code == 202
    j = wait_job(r.json()["id"])
    assert j["status"] == "done"
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["kind"] == "envelope_scan" and body["n_requested"] == 4
    entries = body["cases"]
    assert len(entries) == 4
    ok0, ok1, slow, fast = entries
    for e in (ok0, ok1):
        assert e["verdict"]["ok"] is True and e["verdict"]["reasons"] == []
    assert slow["trim"]["case"]["name"] == "slow"
    assert slow["verdict"]["ok"] is False
    assert slow["verdict"]["reasons"] == ["not_converged", "alpha_margin"]
    # 수렴 여부로 밖을 판정하면 이 케이스가 통과해 버린다 — 프로펠러 상단은 **수렴하는데
    # 포화하는** 자리라 사유가 갈려야 한다 (engine design/points.py envelope_verdict)
    assert fast["trim"]["case"]["name"] == "fast"
    assert fast["trim"]["converged"] is True, "상단 밖은 미수렴이 아니라 포화다"
    assert fast["verdict"]["ok"] is False
    assert fast["verdict"]["reasons"] == ["saturated_throttle_high"]
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
    # M0.6은 h1000·f200에서 스로틀 95.04%로 엔벨로프 밖이다(수렴은 한다).
    # test_margin_map_cancel_preserves_trim_results가 같은 이유로 격자를 옮겼으므로
    # 여기도 안쪽 점으로 둔다 — 지금은 통과하지만 엔벨로프가 더 조여지면 마진
    # 회귀처럼 보이는 실패가 난다
    base = _margin_map_request(machs=(0.5,))
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


# 마진맵 쪽과 같은 이유로 안쪽 점이다 — M0.6 h1000 f200은 스로틀 95.04%로 엔벨로프
# 밖이고, Bode는 수렴만 요구해 통과하지만 엔벨로프가 더 조여지면 실패가 난다
_BODE_CASE = {"name": "", "mach": 0.5, "alt": 1000.0, "fuel": 200.0}
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
    # 해면 상단이 M0.60(연료 200 kg)까지 내려와 종전 격자(0.65·0.75·0.85)는 전부
    # 엔벨로프 밖이다 — 수렴한 칸이 없으면 이 테스트가 볼 것이 없다 (plant/prop.py)
    cases = [{"name": "", "mach": m, "alt": 0.0, "fuel": 200.0} for m in (0.35, 0.45, 0.55)]
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


# ── 법칙 게인 루프 (gain_source "profile") — 칸마다 그 칸에서 기체가 실제로 나는 게인 ─────────────
# 요청 게인 루프는 루프마다 kp 하나라 스케줄 게인을 한 마하에서 읽어 전 칸에 쓰면 그 마하 열 밖은 근사였다
# (쇼케이스 기체 격자 20칸 중 4칸만 정확 — 판정까지 뒤집힌다). 법칙 게인 루프는 서버가 조립 법칙에서 칸마다 읽는다
_RATE_LOOPS = (("pitch_q", "lon", "q", "de", "pitch"), ("roll_p", "lat", "p", "da", "roll"),
               ("yaw_r", "lat", "r", "dr", "yaw"))


def _law_loop(name, axis, x_out, u_in, _group=None):
    return {"name": name, "axis": axis, "x_out": x_out, "u_in": u_in, "sign": -1.0, "gain_source": "profile"}


def _run_map(client, wait_job, body):
    r = client.post("/api/analysis/margin-map", json=body)
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"])
    assert j["status"] == "done", j
    return client.get(f"/api/results/{j['result_id']}").json()


def _law_of(client, pid, variant=None):
    """저장소의 그 기체 문서 → 조립 법칙 — 2단 개루프(openloop)와 같은 조립 경로(make_law)."""
    from claw.pipeline.influence import Shape, make_law
    from claw.profile import build_profile

    doc = client.get(f"/api/profiles/{pid}").json()["document"]
    built = build_profile(doc, variant)
    return built, make_law(Shape(profile=built))


def test_margin_map_law_gains_are_each_cells_own_openloop_gain(client, wait_job):
    """쇼케이스 기체 격자에서 칸마다 게인이 openloop.effective_gain(그 칸)과 비트 같고, 마진은 그 게인을 요청
    kp로 적은 같은 격자 맵의 그 칸과 비트 같다 — 서버가 스케줄 산식을 따로 적지 않고 법칙을 칸에서 읽는다는 증명.
    한 kp 근사였다면 마하마다 다른 게인이 한 값으로 뭉친다."""
    from claw.pipeline.openloop import effective_gain
    from claw.profile import SHOWCASE_ID
    from claw.common.contracts import TrimCase

    assert client.post("/api/profiles/_showcase/install").status_code == 200
    built, law = _law_of(client, SHOWCASE_ID)
    g = built.doc["mission_template"]["trim_grid"]
    step = g["mach"]["step"]
    n = round((g["mach"]["to"] - g["mach"]["from"]) / step)
    machs = [g["mach"]["from"], g["mach"]["from"] + step * (n // 2), g["mach"]["to"]]  # 템플릿 격자 양끝·가운데
    cases = [{"name": f"c{i}", "mach": m, "alt": g["alt"][0], "fuel": g["fuel"][0]} for i, m in enumerate(machs)]
    prof = {"id": SHOWCASE_ID}
    body = _run_map(client, wait_job, {"profile": prof, "cases": cases,
                                       "loops": [_law_loop(*lp) for lp in _RATE_LOOPS]})

    # echo — 법칙 게인 루프는 kp·ki 없이 gain_source만(그대로 보드선도 요청에 되실린다), 출처는 결과와 함께
    assert body["loops"] == [_law_loop(*lp) for lp in _RATE_LOOPS]
    tables = law.schedule.tables
    assert body["profile_gains"] == {
        "basis": "confirmed" if built.doc["law"]["gain_tables"] is not None else "rule",
        "loops": {name: {"kp": {"slot": f"{grp}.k_rate", "scheduled": f"{grp}.k_rate" in tables}}
                  for name, *_, grp in _RATE_LOOPS},
    }
    entries = body["cases"]
    assert all(e["trim"]["converged"] for e in entries)  # 픽스처 전제 — 템플릿 격자 안쪽
    for e in entries:
        c = e["trim"]["case"]
        case = TrimCase(c["name"], mach=c["mach"], alt=c["alt"], fuel=c["fuel"])
        for name, *_, grp in _RATE_LOOPS:
            assert e["gains"][name] == {"kp": effective_gain(law, grp, "k_rate", case), "ki": 0.0}, (c, name)
    # 격자 안에서 게인이 실제로 달라진다 — 같다면 이 테스트는 한 kp 근사와 구분하지 못한다
    assert len({e["gains"]["pitch_q"]["kp"] for e in entries}) == len(entries)

    # 마진 — 그 칸의 게인을 요청 kp로 적은 같은 격자(같은 순서 = 같은 웜스타트 트림) 맵의 그 칸과 비트 같다. 같은 축의
    # 나머지 루프를 닫고 끊으므로(broken_loop) 세 루프를 함께 — 닫아 둔 루프도 그 칸의 게인이어야 같은 수다
    for e in entries:
        ref = _run_map(client, wait_job, {"profile": prof, "cases": cases, "loops": [
            {"name": name, "axis": axis, "x_out": x_out, "u_in": u_in, "kp": e["gains"][name]["kp"], "ki": 0.0,
             "sign": -1.0} for name, axis, x_out, u_in, _grp in _RATE_LOOPS]})
        twin = next(r for r in ref["cases"] if r["trim"]["case"]["name"] == e["trim"]["case"]["name"])
        for name, *_ in _RATE_LOOPS:
            assert e["margins"][name] == twin["margins"][name], (name, e["trim"]["case"]["name"])
        assert "gains" not in twin and "profile_gains" not in ref  # 요청 게인 맵은 종전 모양

    # 보드선도 — 결과의 루프 echo를 그대로 되실어도 같은 칸 게인으로 같은 곡선(칸과 곡선이 같은 게인)
    e = entries[-1]
    t = e["trim"]
    b = client.post("/api/analysis/bode", json={
        "profile": prof, "case": t["case"], "loop": body["loops"][0],
        "z0": [t["euler"][1], t["control"]["elevon"][0], t["control"]["throttle"][0]]})
    assert b.status_code == 200, b.text
    bj = b.json()
    assert bj["gains"] == e["gains"]["pitch_q"] and bj["loop"] == body["loops"][0]
    assert bj["profile_gains"]["loops"] == {"pitch_q": body["profile_gains"]["loops"]["pitch_q"]}
    for k in ("pm_deg", "wcp"):
        assert bj["margins"][k] == pytest.approx(e["margins"]["pitch_q"][k], rel=1e-6, abs=1e-9), k


def test_margin_map_law_gains_mix_with_request_gains_and_name_the_constant_slots(client, wait_job):
    """예제 기체(규칙 스케줄 — 피치 k_rate는 스케줄, 요 k_rate는 설계 상수): 스케줄 자리는 칸마다 다르고 상수
    자리는 전 칸 같으며, 출처가 그 구분을 말한다. 손으로 적은 루프는 같은 요청 안에서 요청 kp 그대로다."""
    from claw.profile import EXAMPLE_ID

    _built, law = _law_of(client, EXAMPLE_ID)
    tables = law.schedule.tables
    assert "pitch.k_rate" in tables and "yaw.k_rate" not in tables  # 픽스처 전제
    hand = {"name": "roll_hand", "axis": "lat", "x_out": "p", "u_in": "da", "kp": -0.4, "ki": 0.0, "sign": -1.0}
    body = _run_map(client, wait_job, {**_margin_map_request(), "loops": [
        _law_loop(*_RATE_LOOPS[0]), _law_loop(*_RATE_LOOPS[2]), hand]})
    assert body["profile_gains"] == {"basis": "rule", "loops": {
        "pitch_q": {"kp": {"slot": "pitch.k_rate", "scheduled": True}},
        "yaw_r": {"kp": {"slot": "yaw.k_rate", "scheduled": False}}}}
    assert body["loops"][2] == hand  # 요청 게인 루프 echo는 종전 모양(gain_source 키 없음)
    entries = body["cases"]
    assert len({e["gains"]["pitch_q"]["kp"] for e in entries}) > 1
    assert {e["gains"]["yaw_r"]["kp"] for e in entries} == {float(law.scas.cfg["yaw"]["k_rate"])}
    assert all(set(e["gains"]) == {"pitch_q", "yaw_r"} for e in entries)  # 손으로 적은 루프는 칸 게인 기록이 없다
    assert all(set(e["margins"]) == {"pitch_q", "yaw_r", "roll_hand"} for e in entries)


def test_margin_map_law_gain_loops_are_validated(client):
    base = _margin_map_request()
    law_loop = _law_loop(*_RATE_LOOPS[0])
    # 게인을 두 곳에서 받지 않는다 — 어느 쪽으로 쟀는지 결과에서 흐려진다
    for extra in ({"kp": 0.5}, {"ki": 0.1}, {"kp": None}):
        r = client.post("/api/analysis/margin-map", json={**base, "loops": [{**law_loop, **extra}]})
        assert r.status_code == 422, extra
    # 법칙 자리 선언(GROUP_LOOPS)이 없는 루프는 법칙 게인을 읽을 자리가 없다
    undeclared = {**law_loop, "name": "sideslip", "axis": "lat", "x_out": "v", "u_in": "dr"}
    r = client.post("/api/analysis/margin-map", json={**base, "loops": [undeclared]})
    assert r.status_code == 422 and "GROUP_LOOPS" in r.text
    assert client.post("/api/analysis/margin-map",
                       json={**base, "loops": [{**law_loop, "sign": 0.0}]}).status_code == 422
    # 요청 게인 루프는 여전히 kp가 필수다
    no_kp = {k: v for k, v in base["loops"][0].items() if k != "kp"}
    r = client.post("/api/analysis/margin-map", json={**base, "loops": [no_kp]})
    assert r.status_code == 422 and "kp 필요" in r.text
    assert client.post("/api/analysis/bode", json={"case": _BODE_CASE, "loop": {**law_loop, "kp": 0.5}}).status_code == 422


def test_margin_map_law_gains_refuse_a_law_that_does_not_assemble(client):
    """확정 게인 표가 낡은 문서는 조립이 거부한다(시뮬·코드 422) — 법칙 게인 루프도 같은 422다. 기체가 날 게인이
    없는데 다른 표(규칙 스케줄)로 재서 그 기체의 마진인 척하지 않는다. 요청 게인 루프는 조립과 무관하게 선다."""
    from claw.profile import SHOWCASE_ID

    assert client.post("/api/profiles/_showcase/install").status_code == 200
    doc = client.get(f"/api/profiles/{SHOWCASE_ID}").json()["document"]
    if doc["law"]["gain_tables"] is None:
        pytest.skip("쇼케이스 문서에 확정 게인 표가 없다 — 낡음 경로를 만들 수 없다")
    doc.update(id="stale-tables", name="낡은 확정 표", variants=[])
    doc["law"]["design"]["autopilot"]["tau_alt"] *= 1.5  # 설계값 변경 → 표의 기준 지문과 어긋남(플랜트는 그대로)
    assert client.post("/api/profiles", json={"document": doc}).status_code == 201
    m = doc["mission_template"]["trim_grid"]["mach"]["from"]
    req = {"profile": {"id": "stale-tables"}, "cases": [{"mach": m, "alt": 200.0, "fuel": 10.0}],
           "loops": [_law_loop(*_RATE_LOOPS[0])]}
    r = client.post("/api/analysis/margin-map", json=req)
    assert r.status_code == 422 and r.json()["detail"]["path"] == "/law/gain_tables"
    b = client.post("/api/analysis/bode", json={**req, "case": req["cases"][0], "loop": req["loops"][0]})
    assert b.status_code == 422 and b.json()["detail"]["path"] == "/law/gain_tables"
    hand = {"name": "pitch_q", "axis": "lon", "x_out": "q", "u_in": "de", "kp": 0.3, "sign": -1.0}
    assert client.post("/api/analysis/margin-map", json={**req, "loops": [hand]}).status_code == 202


def test_margin_map_law_gain_zero_everywhere_is_a_meaningless_loop(client):
    """법칙 게인이 격자 전 칸에서 0인 루프는 요청 kp=ki=0 루프와 같은 422 — 재면 무의미한 inf 마진이 칠해진다."""
    from claw.profile import load_example

    d = load_example()
    d.update(id="no-yaw-damper", name="요 댐퍼 없음", is_example=False, variants=[])
    d["law"]["design"]["scas"]["yaw"]["k_rate"] = 0.0  # 예제는 요 k_rate를 스케줄하지 않는다 — 전 칸 설계 상수 0
    assert client.post("/api/profiles", json={"document": d}).status_code == 201
    req = {**_margin_map_request(), "profile": {"id": "no-yaw-damper"}, "loops": [_law_loop(*_RATE_LOOPS[2])]}
    r = client.post("/api/analysis/margin-map", json=req)
    assert r.status_code == 422 and "yaw_r" in r.json()["detail"] and "0" in r.json()["detail"]
    b = client.post("/api/analysis/bode", json={"profile": {"id": "no-yaw-damper"}, "case": _BODE_CASE,
                                               "loop": _law_loop(*_RATE_LOOPS[2])})
    assert b.status_code == 422 and "0" in b.json()["detail"]


def test_margin_map_law_gain_zero_in_some_cells_leaves_those_cells_blank_with_a_reason(client, wait_job):
    """법칙 게인이 **일부 칸에서만** 0이면 그 칸만 마진 없이 사유(note) — 0 게인으로 재면 무의미한 inf 마진이 초록으로
    칠해진다. 확정 표 값만 고친 문서는 표의 기준 지문(표 절 밖)이 그대로라 낡지 않는다."""
    from claw.profile import SHOWCASE_ID

    assert client.post("/api/profiles/_showcase/install").status_code == 200
    doc = client.get(f"/api/profiles/{SHOWCASE_ID}").json()["document"]
    if doc["law"]["gain_tables"] is None or "yaw.k_rate" not in doc["law"]["gain_tables"]["tables"]:
        pytest.skip("쇼케이스 문서에 요 k_rate 확정 표가 없다")
    t = doc["law"]["gain_tables"]["tables"]["yaw.k_rate"]
    lo, hi = doc["mission_template"]["trim_grid"]["mach"]["from"], doc["mission_template"]["trim_grid"]["mach"]["to"]
    cut = max(m for m in t["axes"]["mach"] if m < hi)  # hi 아래 마지막 격자점까지 0 — lo 칸은 0, hi 칸은 0이 아님
    assert cut > lo
    t["data"] = [0.0 if m <= cut else v for m, v in zip(t["axes"]["mach"], t["data"])]
    doc.update(id="yaw-gap", name="요 댐퍼 저속 공백", variants=[])
    assert client.post("/api/profiles", json={"document": doc}).status_code == 201
    cases = [{"name": "lo", "mach": lo, "alt": 200.0, "fuel": 10.0}, {"name": "hi", "mach": hi, "alt": 200.0, "fuel": 10.0}]
    body = _run_map(client, wait_job, {"profile": {"id": "yaw-gap"}, "cases": cases,
                                       "loops": [_law_loop(*_RATE_LOOPS[0]), _law_loop(*_RATE_LOOPS[2])]})
    e_lo, e_hi = body["cases"]
    assert e_lo["gains"]["yaw_r"] == {"kp": 0.0, "ki": 0.0} and e_hi["gains"]["yaw_r"]["kp"] > 0.0
    assert set(e_lo["margins"]) == {"pitch_q"} and "yaw_r" in e_lo["note"]  # 그 칸의 그 루프만 비고 사유가 붙는다
    assert set(e_hi["margins"]) == {"pitch_q", "yaw_r"} and e_hi["note"] is None
    b = client.post("/api/analysis/bode", json={"profile": {"id": "yaw-gap"}, "case": e_lo["trim"]["case"],
                                               "loop": body["loops"][1]})
    assert b.status_code == 422 and "0" in b.json()["detail"]


# ── 끊는 자리 — 같은 축의 나머지 루프를 닫고 끊는다 (엔진 broken_loop, AS94900 · e2e D2) ──────────────────

_ROLL_HAND = {"name": "roll_p", "axis": "lat", "x_out": "p", "u_in": "da", "kp": -0.3, "ki": 0.0, "sign": -1.0}
_YAW_HAND = {"name": "yaw_r", "axis": "lat", "x_out": "r", "u_in": "dr", "kp": 0.9, "ki": 0.0, "sign": -1.0}
_ACT = {"actuator": {"wn": 30.0, "zeta": 0.7}, "delay_s": 0.035}


def _cells(body, name):
    return {e["trim"]["case"]["name"]: e["margins"][name] for e in body["cases"] if name in e["margins"]}


def test_margin_map_closes_the_other_loops_of_the_same_axis(client, wait_job):
    """roll_p·yaw_r(같은 횡축)는 서로를 닫고 끊는다 — 칸의 마진이 엔진 broken_loop(나머지 닫힘)의 nyquist_margins와
    같고 closed_with가 닫아 둔 루프를 말한다. 다른 축 루프(pitch_q)는 닫지 않는다 — 종전 값·종전 키 그대로.
    close_others를 끄면 루프마다 그 루프 하나만 있는 축(종전 방식)이라 한 루프짜리 요청과 같은 수다."""
    from claw.analysis import broken_loop, nyquist_margins
    from claw.profile import load_example, build_profile
    from claw.trim import linearize, split_axes, trim_batch
    from claw.common.contracts import TrimCase
    from claw_server.serialize import to_jsonable

    req = {**_margin_map_request(), **_ACT, "loops": [_PITCH_LOOP, _ROLL_HAND, _YAW_HAND]}
    body = _run_map(client, wait_job, req)
    for e in body["cases"]:
        assert e["margins"]["roll_p"]["closed_with"] == ["yaw_r"]
        assert e["margins"]["yaw_r"]["closed_with"] == ["roll_p"]
        assert "closed_with" not in e["margins"]["pitch_rate"]
    # 엔진 대조 — 같은 웜스타트 순서로 트림해 같은 선형화점에서
    ac = build_profile(load_example(), None).aircraft()
    cases = [TrimCase(name=e["trim"]["case"]["name"], mach=e["trim"]["case"]["mach"],
                      alt=e["trim"]["case"]["alt"], fuel=e["trim"]["case"]["fuel"]) for e in body["cases"]]
    trs = trim_batch(ac, cases, fingerprint="fp-mm")
    ad = {"actuator_wn": 30.0, "actuator_zeta": 0.7, "delay_s": 0.035, "pade_order": 2}
    yaw = {k: _YAW_HAND[k] for k in ("x_out", "u_in", "kp", "ki", "sign")}
    for tr, e in zip(trs, body["cases"]):
        _lon, lat = split_axes(linearize(ac, tr))
        want = nyquist_margins(broken_loop(lat, "p", "da", -0.3, others=[yaw], **ad))
        got = {k: v for k, v in e["margins"]["roll_p"].items() if k != "closed_with"}
        assert got == to_jsonable(want), tr.case.name

    # 끄면 종전 — 한 루프짜리 요청과 같은 칸
    off = _run_map(client, wait_job, {**req, "close_others": False})
    alone = _run_map(client, wait_job, {**req, "loops": [_ROLL_HAND]})
    assert _cells(off, "roll_p") == _cells(alone, "roll_p")
    assert _cells(off, "roll_p") != _cells(body, "roll_p")  # 닫는 것이 실제로 수를 바꾼다(아니면 이 테스트가 무의미)
    assert _cells(off, "pitch_rate") == _cells(body, "pitch_rate")  # 다른 축은 무관


def test_margin_map_does_not_close_an_alternative_loop_on_the_same_slot(client, wait_job):
    """같은 자리(p←δa)의 kp만 다른 사본은 한 루프의 대안이다 — 서로 닫지 않는다(한 센서·한 타면에 되먹임 둘이 아니다)."""
    alt = {**_ROLL_HAND, "name": "roll_p_alt", "kp": -0.2}
    body = _run_map(client, wait_job, {**_margin_map_request(), **_ACT, "loops": [_ROLL_HAND, alt]})
    alone = _run_map(client, wait_job, {**_margin_map_request(), **_ACT, "loops": [_ROLL_HAND]})
    assert _cells(body, "roll_p") == _cells(alone, "roll_p")
    assert all("closed_with" not in m for m in _cells(body, "roll_p_alt").values())


def test_bode_closes_the_same_others_as_the_cell(client, wait_job):
    """칸의 closed_with 루프를 결과 echo에서 그대로 others로 실으면 보드선도가 그 칸과 같은 조립·같은 마진이다.
    다른 축 루프를 others로 실으면 422 — 닫을 수 없는 루프를 조용히 버리지 않는다."""
    req = {**_margin_map_request(), **_ACT, "loops": [_ROLL_HAND, _YAW_HAND]}
    body = _run_map(client, wait_job, req)
    e = body["cases"][1]
    t = e["trim"]
    z0 = [t["euler"][1], t["control"]["elevon"][0], t["control"]["throttle"][0]]
    loops = {lp["name"]: lp for lp in body["loops"]}
    b = client.post("/api/analysis/bode", json={
        "case": t["case"], "loop": loops["roll_p"], "others": [loops["yaw_r"]], **_ACT, "z0": z0})
    assert b.status_code == 200, b.text
    got, want = b.json()["margins"], e["margins"]["roll_p"]
    assert got["closed_with"] == ["yaw_r"]
    for k in ("pm_deg", "wcp", "gm_db", "wcg"):
        assert got[k] == pytest.approx(want[k], rel=1e-6, abs=1e-9), k
    # others 없이 — 종전 단독 조립(칸과 다르다)
    solo = client.post("/api/analysis/bode", json={
        "case": t["case"], "loop": loops["roll_p"], **_ACT, "z0": z0}).json()["margins"]
    assert "closed_with" not in solo and solo["pm_deg"] != pytest.approx(want["pm_deg"], rel=1e-6)
    bad = client.post("/api/analysis/bode", json={
        "case": t["case"], "loop": loops["roll_p"], "others": [_PITCH_LOOP], **_ACT, "z0": z0})
    assert bad.status_code == 422 and "같은 축" in bad.text
    dup = client.post("/api/analysis/bode", json={
        "case": t["case"], "loop": loops["roll_p"], "others": [loops["roll_p"]], **_ACT, "z0": z0})
    assert dup.status_code == 422 and "중복" in dup.text
