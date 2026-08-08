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
