"""M10 analysis 검증 — 감쇠비 해석해, 모드 자동 분류, 교과서 전달함수 마진, 마진 맵."""

import control
import numpy as np
import pytest

from claw.analysis import classify_lat, classify_lon, damp, loop_margins, make_siso, margin_map
from claw.common.contracts import TrimCase
from claw.plant import make_demo_aircraft, make_demo_stall_table
from claw.trim import linearize, split_axes, trim_batch


@pytest.fixture(scope="module")
def lon_lat():
    ac = make_demo_aircraft()
    cases = [TrimCase(f"m{m:.1f}", mach=m, alt=1000.0, fuel=200.0) for m in (0.5, 0.6, 0.7)]
    trs = trim_batch(ac, cases)
    models = [split_axes(linearize(ac, tr)) for tr in trs]
    return models  # [(lon, lat), ...]


def test_damp_analytic():
    """A=[[0,1],[-4,-2]] → λ=-1±j√3, wn=2, ζ=0.5 정확."""
    modes = damp(np.array([[0.0, 1.0], [-4.0, -2.0]]))
    assert len(modes) == 2
    for m in modes:
        assert m["wn"] == pytest.approx(2.0, rel=1e-12)
        assert m["zeta"] == pytest.approx(0.5, rel=1e-12)


def test_classify_lon(lon_lat):
    lon, _ = lon_lat[1]  # M0.6
    c = classify_lon(lon)
    sp, ph = c["short_period"], c["phugoid"]
    assert sp["wn"] > ph["wn"]  # 단주기가 장주기보다 빠름
    assert sp["zeta"] > 0 and ph["zeta"] > 0  # 데모 기체는 둘 다 안정
    assert 1.0 < sp["wn"] < 30.0  # 물리 상식 범위


def test_classify_lat(lon_lat):
    _, lat = lon_lat[1]
    c = classify_lat(lat)
    assert c["dutch_roll"]["wn"] > 0.5  # 복소쌍
    assert c["roll"]["eig"].imag == 0 and c["roll"]["eig"].real < 0  # 빠른 실근
    assert abs(c["roll"]["eig"].real) > abs(c["spiral"]["eig"].real)  # 롤 >> 나선


def test_loop_margins_textbook():
    """L = 1/(s(s+1)): PM = 51.83° @ 0.786 rad/s, GM = ∞."""
    s = control.tf("s")
    m = loop_margins(1.0 / (s * (s + 1.0)))
    assert m["pm_deg"] == pytest.approx(51.827, abs=0.01)
    assert m["wcp"] == pytest.approx(0.7862, abs=0.001)
    assert np.isinf(m["gm_db"])


def test_margin_map_over_cases(lon_lat):
    """트림 케이스별 피치레이트 PI 개루프 마진 — 마진 맵의 최소 형태 (01 §4.2 [확정])."""
    s = control.tf("s")
    pi = 0.5 + 0.8 / s
    loops = {}
    for lon, _ in lon_lat:
        g_q = make_siso(lon, x_out="q", u_in="de")  # δe → q
        loops[lon.case.name] = -pi * g_q  # 데모 부호: δe + → 기수 하방 (Cmde<0) → 루프 부호 반전
    mm = margin_map(loops)
    assert set(mm) == {"m0.5", "m0.6", "m0.7"}
    for name, m in mm.items():
        assert m["pm_deg"] > 20.0, f"{name}: PM {m['pm_deg']}"
        assert np.isfinite(m["wcp"])


def test_pi_loop_matches_manual_composition(lon_lat):
    """pi_loop 헬퍼 == 수동 조립(−PI·G) — M13 마진 맵 API가 쓰는 공식 경로."""
    from claw.analysis import pi_loop

    lon, _ = lon_lat[1]
    s = control.tf("s")
    manual = loop_margins(-(0.5 + 0.8 / s) * make_siso(lon, x_out="q", u_in="de"))
    helper = loop_margins(pi_loop(lon, x_out="q", u_in="de", kp=0.5, ki=0.8))
    assert helper["pm_deg"] == pytest.approx(manual["pm_deg"], rel=1e-9)
    assert helper["wcp"] == pytest.approx(manual["wcp"], rel=1e-9)
    # P 단독(ki=0)·부호 지정 경로
    p_only = pi_loop(lon, x_out="q", u_in="de", kp=0.5, ki=0.0, sign=-1.0)
    assert np.isfinite(loop_margins(p_only)["pm_deg"])


def test_pi_loop_actuator_cascade_matches_manual(lon_lat):
    """actuator_wn/zeta 지정 시 = 수동으로 2차계 wn²/(s²+2ζωn s+wn²)를 곱한 것과 동일
    (01 §4.2 [기본값] — 작동기 동특성 포함 마진)."""
    from claw.analysis import pi_loop

    lon, _ = lon_lat[1]  # M0.6
    s = control.tf("s")
    wn, zeta = 30.0, 0.7
    act = wn**2 / (s**2 + 2 * zeta * wn * s + wn**2)
    manual = loop_margins(-(0.5 + 0.8 / s) * act * make_siso(lon, x_out="q", u_in="de"))
    helper = loop_margins(pi_loop(
        lon, x_out="q", u_in="de", kp=0.5, ki=0.8, actuator_wn=wn, actuator_zeta=zeta))
    assert helper["pm_deg"] == pytest.approx(manual["pm_deg"], rel=1e-9)
    assert helper["wcp"] == pytest.approx(manual["wcp"], rel=1e-9)


def test_pi_loop_actuator_requires_both_params(lon_lat):
    """wn·zeta는 함께 지정 — 한쪽만 주면 조용히 무시하지 않고 즉시 거부."""
    from claw.analysis import pi_loop

    lon, _ = lon_lat[1]
    with pytest.raises(ValueError, match="actuator_wn.*actuator_zeta"):
        pi_loop(lon, x_out="q", u_in="de", kp=0.5, actuator_wn=30.0)
    with pytest.raises(ValueError, match="actuator_wn.*actuator_zeta"):
        pi_loop(lon, x_out="q", u_in="de", kp=0.5, actuator_zeta=0.7)


def test_pi_loop_delay_cascade_matches_manual_pade(lon_lat):
    """delay_s 지정 시 = 수동 control.pade(delay_s, pade_order) 캐스케이드와 동일
    (01 §4.2 [TBD]→해소 — Padé 차수 [기본값] 2)."""
    from claw.analysis import pi_loop

    lon, _ = lon_lat[1]
    s = control.tf("s")
    num, den = control.pade(0.035, 2)
    delay_tf = control.tf(num, den)
    manual = loop_margins(-(0.5 + 0.8 / s) * delay_tf * make_siso(lon, x_out="q", u_in="de"))
    helper = loop_margins(pi_loop(
        lon, x_out="q", u_in="de", kp=0.5, ki=0.8, delay_s=0.035))
    assert helper["pm_deg"] == pytest.approx(manual["pm_deg"], rel=1e-9)
    assert helper["wcp"] == pytest.approx(manual["wcp"], rel=1e-9)
    # 차수를 바꾸면 다른(더 부정확한) 근사 — 기본 2차와 달라야 함 (인자가 실제로 쓰임)
    order1 = loop_margins(pi_loop(
        lon, x_out="q", u_in="de", kp=0.5, ki=0.8, delay_s=0.035, pade_order=1))
    assert order1["pm_deg"] != pytest.approx(helper["pm_deg"], rel=1e-6)


def test_pi_loop_delay_zero_is_noop(lon_lat):
    """delay_s=0.0(기본) — 캐스케이드 없음, 기존 호출과 완전히 동일 (하위호환)."""
    from claw.analysis import pi_loop

    lon, _ = lon_lat[1]
    base = loop_margins(pi_loop(lon, x_out="q", u_in="de", kp=0.5, ki=0.8))
    explicit = loop_margins(pi_loop(lon, x_out="q", u_in="de", kp=0.5, ki=0.8, delay_s=0.0))
    for k in base:  # nan != nan이라 dict == 대신 항목별 비교 (wcg가 nan일 수 있음)
        assert explicit[k] == base[k] or (np.isnan(explicit[k]) and np.isnan(base[k])), k


def test_pi_loop_invalid_delay_or_pade_order(lon_lat):
    from claw.analysis import pi_loop

    lon, _ = lon_lat[1]
    with pytest.raises(ValueError, match="delay_s"):
        pi_loop(lon, x_out="q", u_in="de", kp=0.5, delay_s=-0.01)
    with pytest.raises(ValueError, match="pade_order"):
        pi_loop(lon, x_out="q", u_in="de", kp=0.5, delay_s=0.03, pade_order=0)


def test_pi_loop_actuator_and_delay_reduce_margins(lon_lat):
    """작동기·지연 포함 마진 ≤ 미포함 마진 — 01 §4.2 '제외 마진은 낙관적' 회귀 고정.

    실측(피치 M0.6 kp=0.5·ki=0.8): 기준 PM 91.0° → 작동기 포함 PM −8.4°(불안정
    전환! 크로스오버 52 rad/s가 작동기 대역폭 30 rad/s를 넘어섬) → 지연 포함
    −12.9° → 둘 다 포함 −76.3°(각각보다 더 나쁨, 위상지연 누적)."""
    from claw.analysis import pi_loop

    lon, lat = lon_lat[1]
    wn, zeta, delay_s = 30.0, 0.7, 0.035
    cases = [
        (lon, "q", "de", 0.5, 0.8),
        (lat, "p", "da", -0.2, 0.0),
        (lat, "r", "dr", 0.8, 0.0),
    ]
    for model, x_out, u_in, kp, ki in cases:
        base = loop_margins(pi_loop(model, x_out=x_out, u_in=u_in, kp=kp, ki=ki))
        with_act = loop_margins(pi_loop(
            model, x_out=x_out, u_in=u_in, kp=kp, ki=ki, actuator_wn=wn, actuator_zeta=zeta))
        with_delay = loop_margins(pi_loop(
            model, x_out=x_out, u_in=u_in, kp=kp, ki=ki, delay_s=delay_s))
        with_both = loop_margins(pi_loop(
            model, x_out=x_out, u_in=u_in, kp=kp, ki=ki,
            actuator_wn=wn, actuator_zeta=zeta, delay_s=delay_s))
        assert with_act["pm_deg"] < base["pm_deg"], f"{x_out}: 작동기 포함이 PM 개선"
        assert with_delay["pm_deg"] < base["pm_deg"], f"{x_out}: 지연 포함이 PM 개선"
        assert with_both["pm_deg"] < with_act["pm_deg"], f"{x_out}: 병용이 작동기 단독보다 양호"
        assert with_both["pm_deg"] < with_delay["pm_deg"], f"{x_out}: 병용이 지연 단독보다 양호"


def test_vn_stall_boundary_analytic():
    """V-n 실속 경계 해석 대조 — 데모 CL(α, δe=0)=3.5α → n = q̄·S·CL/W 정확."""
    from claw.analysis import vn_stall_boundary
    from claw.common.constants import G0
    from claw.env import isa_atmosphere

    ac = make_demo_aircraft()
    st = make_demo_stall_table()
    machs = (0.3, 0.5, 0.7)
    vn = vn_stall_boundary(ac, st, alt=1000.0, fuel=200.0, machs=machs)
    atm = isa_atmosphere(1000.0)
    m = ac.fuel_mass.at(200.0)[0]
    for M, V, n in zip(vn["mach"], vn["V"], vn["n"]):
        a_s = float(st.interp(mach=M))
        n_expect = 0.5 * atm.rho * V**2 * 3.0 * (3.5 * a_s) / (m * G0)  # S=3.0
        assert n == pytest.approx(n_expect, rel=1e-9)
    assert vn["n"][0] < vn["n"][1] < vn["n"][2]  # 동압 V² 성장
    # α 리미터 보호 마진 적용 → 경계 하향 (보호선이 실속선 안쪽)
    vp = vn_stall_boundary(ac, st, 1000.0, 200.0, machs, alpha_margin=0.05)
    assert all(p < s for s, p in zip(vn["n"], vp["n"]))


def test_vn_envelope_full_diagram_data():
    """V-n 선도 일습 — 구조 한계선·특성 속도(V_S·V_A) 정합 (01 §3.6 [기본값])."""
    from claw.analysis import vn_envelope
    from claw.plant import make_demo_structural_limits

    ac = make_demo_aircraft()
    st = make_demo_stall_table()
    lim = make_demo_structural_limits()
    env = vn_envelope(ac, st, lim, alt=1000.0, fuel=200.0, alpha_margin=0.05)
    V = np.array(env["V"])
    n = np.array(env["n_stall"])
    # 특성 속도: V_S에서 n_stall≈1, V_A에서 n_stall≈제한하중 (곡선 보간 역산)
    assert env["speeds"]["v_s"] is not None and env["speeds"]["v_a"] is not None
    assert np.interp(env["speeds"]["v_s"], V, n) == pytest.approx(1.0, rel=1e-6)
    assert np.interp(env["speeds"]["v_a"], V, n) == pytest.approx(
        lim["n_limit_pos"], rel=1e-6)
    assert env["speeds"]["v_s"] < env["speeds"]["v_a"]  # 실속속도 < 기동속도
    # 구조 한계: 극한 = 제한 × 안전계수, V_NO < V_D
    L = env["limits"]
    assert L["n_ultimate_pos"] == pytest.approx(6.0 * 1.5)
    assert L["n_ultimate_neg"] == pytest.approx(-3.0 * 1.5)
    assert 0.0 < L["v_no"] < L["v_d"]
    # 보호 곡선은 실속 곡선 안쪽
    assert all(p < s for p, s in zip(env["n_prot"], env["n_stall"]))
    # 마하 격자는 저속(포물선 뿌리)부터 — 첫 점 n_stall ≈ 0 부근
    assert env["mach"][0] == pytest.approx(0.02)
    assert 0.0 < n[0] < 0.05
    # V_S·V_A는 뿌리 확장과 무관 (곡선 자체가 동일 물리)
    assert env["speeds"]["v_s"] == pytest.approx(66.9, rel=0.01)


def test_vn_envelope_negative_stall_placeholder():
    """음의 실속 자리표시 (01 §3.6 [기본값]) — 데이터 부재 대역: −ratio×α_stall.

    데모 CL(α)=3.5α 선형이라 n_neg = −ratio × n_stall 정확 성립 — 해석 대조.
    ratio는 출력에 echo (자리표시 출처 명기, 웹 표기 근거).
    """
    from claw.analysis import vn_envelope
    from claw.plant import make_demo_structural_limits

    ac = make_demo_aircraft()
    st = make_demo_stall_table()
    lim = make_demo_structural_limits()
    env = vn_envelope(ac, st, lim, alt=1000.0, fuel=200.0, alpha_margin=0.05)
    assert env["neg_alpha_ratio"] == pytest.approx(0.6)
    assert len(env["n_stall_neg"]) == len(env["n_stall"])
    for s, ng in zip(env["n_stall"], env["n_stall_neg"]):
        assert ng == pytest.approx(-0.6 * s, rel=1e-9)  # CL 선형 → 정확 비례
        assert ng < 0.0
    # ratio 조정 반영
    env2 = vn_envelope(ac, st, lim, alt=1000.0, fuel=200.0, neg_alpha_ratio=0.4)
    assert env2["n_stall_neg"][10] == pytest.approx(-0.4 * env2["n_stall"][10], rel=1e-9)


def test_vn_envelope_rejects_invalid_limits():
    """구조 한계 오버라이드(01 §2.6)가 열리며 부호·서열 위반은 계산 전에 차단."""
    from claw.analysis import vn_envelope
    from claw.plant import make_demo_structural_limits

    ac = make_demo_aircraft()
    st = make_demo_stall_table()
    for bad in (
        {"n_limit_pos": 0.0},
        {"n_limit_neg": 1.0},
        {"safety_factor": 0.9},
        {"mach_no": 0.95},  # > mach_d 0.9 — 서열 위반
        {"mach_no": 0.0},
    ):
        lim = dict(make_demo_structural_limits(), **bad)
        with pytest.raises(ValueError):
            vn_envelope(ac, st, lim, alt=1000.0, fuel=200.0)


def test_mach_qbar_limit_analytic():
    """동압 한계 마하 해석 대조 — ½ρ(M_q̄·a)² = q_max 정확, ρ 감소로 고도 단조 증가."""
    from claw.analysis import mach_qbar_limit
    from claw.env import isa_atmosphere

    for alt in (0.0, 3000.0, 8000.0):
        m = mach_qbar_limit(alt, 30000.0)
        atm = isa_atmosphere(alt)
        assert 0.5 * atm.rho * (m * atm.a) ** 2 == pytest.approx(30000.0, rel=1e-12)
    assert (mach_qbar_limit(0.0, 30000.0)
            < mach_qbar_limit(5000.0, 30000.0)
            < mach_qbar_limit(11000.0, 30000.0))
    with pytest.raises(ValueError):
        mach_qbar_limit(1000.0, 0.0)


def test_stall_mach_lo_rederivation_and_sources():
    """실속 mach 하한 — 독립 np.interp 재유도 + 중량 상승 + DB 폴백 귀속.

    구 design.grid._mach_lo의 정본 이동(01 §2.6) — coarse 격자와 설계 엔벨로프가
    같은 수를 봐야 하므로 여기서 수식 자체를 핀한다.
    """
    from claw.analysis import stall_mach_lo, vn_stall_boundary
    from claw.env import isa_atmosphere

    ac = make_demo_aircraft()
    st = make_demo_stall_table()
    lo, src = stall_mach_lo(ac, st, 1000.0, 200.0, mach_hi=0.75, db_mach_lo=0.1)
    assert src == "stall"
    # 독립 재유도 — 같은 스캔 격자에서 V_S 역보간 × 1.1
    machs = np.linspace(0.1, 0.75, 41)
    bnd = vn_stall_boundary(ac, st, 1000.0, 200.0, machs)
    v_s = float(np.interp(1.0, np.asarray(bnd["n"]), np.asarray(bnd["V"])))
    atm = isa_atmosphere(1000.0)
    assert lo == pytest.approx((v_s / atm.a) * 1.1, rel=1e-12)
    # 무거울수록·높을수록 실속 하한 상승
    lo_heavy, _ = stall_mach_lo(ac, st, 1000.0, 400.0, mach_hi=0.75, db_mach_lo=0.1)
    lo_high, _ = stall_mach_lo(ac, st, 5000.0, 200.0, mach_hi=0.75, db_mach_lo=0.1)
    assert lo_heavy > lo and lo_high > lo
    # DB 하한이 실속 하한보다 높으면 실효 하한 = DB — 귀속 "db"
    lo_db, src_db = stall_mach_lo(ac, st, 0.0, 100.0, mach_hi=0.75, db_mach_lo=0.5)
    assert src_db == "db" and lo_db == pytest.approx(0.5)


def test_design_envelope_composition_and_attribution():
    """M-h 합성 (01 §2.6) — 행별 min/max 승자 귀속과 q̄ 경계의 고도 교대."""
    from claw.analysis import design_envelope, mach_qbar_limit
    from claw.design.grid import coarse_grid
    from claw.plant import make_demo_db_ranges, make_demo_structural_limits

    ac = make_demo_aircraft()
    st = make_demo_stall_table()
    lim = make_demo_structural_limits()
    db = make_demo_db_ranges()

    env = design_envelope(ac, st, lim, db, fuel=200.0, q_max=20000.0)
    b = env["bounds"]
    assert b["mach_no"] == 0.75 and b["db_mach"] == [0.1, 0.9]
    assert b["alt_max_used"] == 12000.0 and b["alt_max_is_display_default"] is True
    assert b["alt_min"] is None and b["alt_max"] is None
    r = env["region"]
    n = len(r["alt"])
    assert n == 41
    for key in ("mach_lo", "mach_hi", "lo_source", "hi_source", "empty"):
        assert len(r[key]) == n
    assert set(r["lo_source"]) <= {"stall", "db"}
    assert set(r["hi_source"]) <= {"mach_no", "db", "stall_table", "qbar"}
    # q̄=20 kPa: 저고도는 M_q̄(0)≈0.53 < M_NO 0.75 → qbar 승자, 고고도는 ρ 감소로 역전
    assert r["hi_source"][0] == "qbar"
    assert r["mach_hi"][0] == pytest.approx(mach_qbar_limit(r["alt"][0], 20000.0), rel=1e-12)
    assert r["hi_source"][-1] == "mach_no" and r["mach_hi"][-1] == 0.75
    assert b["qbar_mach"] is not None and len(b["qbar_mach"]) == n

    # q_max 미지정 — 경계 자체가 없다 (null echo, 합성 제외)
    env0 = design_envelope(ac, st, lim, db, fuel=200.0)
    assert env0["bounds"]["qbar_mach"] is None and env0["bounds"]["q_max"] is None
    assert set(env0["region"]["hi_source"]) == {"mach_no"}

    # 스케줄 격자 좌표 = coarse 격자 좌표 (row_machs 단일 정본 — 리팩토링 등가)
    grid = coarse_grid(ac, st, lim, db, fuels=(200.0,))
    coarse_coords = {(p.case.mach, p.case.alt) for p in grid["points"]}
    sched_coords = {(p["mach"], p["alt"]) for p in env0["schedule_grid"]["points"]}
    assert sched_coords == coarse_coords

    # 운용 고도 상하한이 표본 범위·격자 필터에 반영
    env2 = design_envelope(ac, st, lim, db, fuel=200.0, alt_min=500.0, alt_max=4000.0)
    assert env2["bounds"]["alt_max_is_display_default"] is False
    assert env2["region"]["alt"][0] == 500.0 and env2["region"]["alt"][-1] == 4000.0
    assert env2["schedule_grid"]["alts"] == [1000.0, 3000.0]  # 기본 (0,1k,3k,5k) ∩ [500,4000]


def test_design_envelope_validation_errors():
    from claw.analysis import design_envelope
    from claw.plant import make_demo_db_ranges, make_demo_structural_limits

    ac = make_demo_aircraft()
    st = make_demo_stall_table()
    lim = make_demo_structural_limits()
    db = make_demo_db_ranges()
    with pytest.raises(ValueError):  # ISA 범위 밖
        design_envelope(ac, st, lim, db, fuel=200.0, alt_max=99999.0)
    with pytest.raises(ValueError):  # 하한 ≥ 상한
        design_envelope(ac, st, lim, db, fuel=200.0, alt_min=5000.0, alt_max=1000.0)
    with pytest.raises(ValueError):  # 실속 여유 < 1
        design_envelope(ac, st, lim, db, fuel=200.0, mach_margin=0.9)
    with pytest.raises(ValueError):  # 동압 한계 비양수
        design_envelope(ac, st, lim, db, fuel=200.0, q_max=-1.0)


def test_aero_envelope_boundaries():
    """공력 선도 데이터 (01 §2.6) — 실속·보호선 관계와 echo 일습."""
    from claw.analysis import aero_envelope
    from claw.plant import make_demo_db_ranges

    st = make_demo_stall_table()
    db = make_demo_db_ranges()
    env = aero_envelope(st, db, alpha_margin=0.05, trim_alpha_bounds=(-0.10, 0.35))
    assert env["mach"][0] == 0.1 and env["mach"][-1] == 0.9
    for m, a_s, a_p in zip(env["mach"], env["alpha_stall"], env["alpha_prot"]):
        assert a_s == pytest.approx(float(st.interp(mach=m)), rel=1e-12)
        assert a_p == pytest.approx(a_s - 0.05, rel=1e-12)  # 보호선 = 실속 − 마진
    assert env["db"] == {"alpha": [-0.2, 0.45], "mach": [0.1, 0.9]}
    assert env["trim_alpha_bounds"] == [-0.10, 0.35]
    assert env["alpha_margin"] == 0.05
    # 미주입 시 null — 없는 데이터를 만들어내지 않는다
    assert aero_envelope(st, db)["trim_alpha_bounds"] is None
    with pytest.raises(ValueError):
        aero_envelope(st, db, alpha_margin=-0.01)


def test_filter_tf_analytic():
    """레이트 경로 필터의 연속시간 등가 — 해석 대조 (01 §2.6·§4.2).

    블록은 이산(1차 ZOH-정확, 노치 RBJ)이지만 pi_loop는 작동기·Padé도 연속으로
    모델하므로 같은 자를 쓴다. 여기서 고정하는 것은 그 연속 표현이 각 필터의
    정의(워시아웃=고역통과, 저역통과 코너 −3 dB, 노치 f0 차단)와 맞는가다.
    """
    import control

    from claw.analysis.margins import filter_tf

    wo = filter_tf({"kind": "washout", "tau": 2.0})
    assert abs(control.evalfr(wo, 1e-6j)) < 1e-5  # DC 차단
    assert abs(control.evalfr(wo, 1e6j)) == pytest.approx(1.0, abs=1e-9)  # HF 통과
    # 코너 1/τ에서 −3 dB
    assert 20 * np.log10(abs(control.evalfr(wo, 0.5j))) == pytest.approx(-3.0103, abs=1e-3)

    lp = filter_tf({"kind": "lowpass", "fc": 15.0})
    assert abs(control.evalfr(lp, 1e-6j)) == pytest.approx(1.0, abs=1e-9)  # DC 통과
    w_c = 2 * np.pi * 15.0
    assert 20 * np.log10(abs(control.evalfr(lp, 1j * w_c))) == pytest.approx(-3.0103, abs=1e-3)

    nt = filter_tf({"kind": "notch", "f0": 4.4, "q": 2.0})
    assert abs(control.evalfr(nt, 1j * 2 * np.pi * 4.4)) < 1e-9  # f0 차단
    assert abs(control.evalfr(nt, 1e-6j)) == pytest.approx(1.0, abs=1e-9)
    assert abs(control.evalfr(nt, 1e6j)) == pytest.approx(1.0, abs=1e-9)

    # "필터 없음"의 두 표현
    assert filter_tf(None) is None and filter_tf({"kind": "none"}) is None
    for bad in ({"kind": "zzz"}, {"kind": "lowpass", "fc": 0.0},
                {"kind": "washout", "tau": -1.0}, {"kind": "notch", "f0": 4.4, "q": 0.0}):
        with pytest.raises(ValueError):
            filter_tf(bad)


def test_filter_vocabulary_and_tf_stay_in_sync():
    """어휘(blocks.RATE_FILTERS)와 마진 TF가 어긋나면 import 시점에 죽는다.

    단정문 자체는 모듈 로드 때 이미 돌았으므로(margins.py) 여기서는 그 단정이
    **존재하고 실제로 두 표를 비교한다**는 것을 고정한다 — codegen/ir_exec.py의
    `assert set(_OP_FN) == set(OPS)`와 같은 드리프트 가드다.
    """
    from claw.analysis.margins import _FILTER_TF
    from claw.blocks.filters import RATE_FILTERS

    assert set(_FILTER_TF) == set(RATE_FILTERS) - {"none"}
    assert "none" in RATE_FILTERS and RATE_FILTERS["none"] is None


def test_pi_loop_filter_is_opt_in(lon_lat):
    """rate_filter 미지정이면 기존 루프와 **완전히 동일** — 하위호환 핀.

    지정하면 캐스케이드가 하나 늘고(극·영점 수 증가) 응답이 필터배만큼 바뀐다.
    """
    import control

    from claw.analysis import pi_loop

    lon, _lat = lon_lat[1]
    kw = dict(x_out="q", u_in="de", kp=0.5, ki=0.8)
    base = pi_loop(lon, **kw)
    same = pi_loop(lon, **kw, rate_filter=None)
    assert control.evalfr(base, 2j) == control.evalfr(same, 2j)
    assert control.evalfr(base, 2j) == control.evalfr(pi_loop(lon, **kw,
                                                             rate_filter={"kind": "none"}), 2j)
    wo = pi_loop(lon, **kw, rate_filter={"kind": "washout", "tau": 2.0})
    # 필터배만큼 정확히 달라진다 — 곱해 넣는 것 이상을 하지 않는다
    at = 2j
    from claw.analysis.margins import filter_tf
    assert control.evalfr(wo, at) == pytest.approx(
        control.evalfr(base, at) * control.evalfr(filter_tf({"kind": "washout", "tau": 2.0}), at)
    )
