"""M7 조립 검증 — 게인 스케줄(클립·필터·불연속), α 리미터, 믹서, FCL 최상위.

α 리미터 폐루프 수치는 스크래치 확인 결과 고정: M0.3 h500 급피치업에서
리미터 미장착 α_max>0.34(실속 경계 초과), 장착 시 α_max≤0.31 (α_max=0.30).
"""

import math

import numpy as np
import pytest

from claw.common.attitude import euler_to_dcm, euler_to_quat
from claw.common.contracts import GuidanceCommand, NavOutput, TrimCase
from claw.fcl import (
    AlphaLimiter,
    Autopilot,
    FlightControlLaw,
    GainSchedule,
    Mixer,
    Scas,
    ScasAxis,
    make_demo_fcl,
    max_adjacent_jump,
)
from claw.fcl.demo import DEMO_PITCH, DEMO_ROLL, DEMO_YAW
from claw.plant import (
    XE_H,
    XE_THETA,
    XE_U,
    XE_W,
    make_demo_aircraft,
    make_demo_stall_table,
    rk4_step,
)
from claw.tables import Table
from claw.trim import trim_level

DT = 0.01


def _nav(vel_b=(200.0, 0.0, 0.0), h=1000.0, phi=0.0, theta=0.0, psi=0.0,
         omega=(0.0, 0.0, 0.0), fuel=200.0):
    q = euler_to_quat(phi, theta, psi)
    return NavOutput(pos_n=np.array([0.0, 0.0, -h]),
                     vel_n=euler_to_dcm(phi, theta, psi).T @ np.asarray(vel_b, dtype=float),
                     q_nb=q, omega_b=np.asarray(omega, dtype=float), fuel=fuel)


# ---------- 게인 스케줄 ----------


def test_schedule_lookup_nested_and_clip():
    """점 네임스페이스 → 중첩 dict, 외삽 금지(경계값 고정) [기본값 01 §3.4]."""
    tab = Table({"mach": (0.4, 0.8)}, (-3.0, -1.5), extrapolate="clip")
    gs = GainSchedule({"pitch.kp": tab}, filter_tau=0.0).init(DT)
    assert gs.step(0.6, 0.0, 0.0) == {"pitch": {"kp": pytest.approx(-2.25)}}
    assert gs.step(1.2, 0.0, 0.0)["pitch"]["kp"] == pytest.approx(-1.5)
    assert gs.step(0.1, 0.0, 0.0)["pitch"]["kp"] == pytest.approx(-3.0)


def test_schedule_variable_filtering_prevents_chatter():
    """스케줄 변수 1차 필터 [기본값]: 첫 스텝은 시드(무과도), 점프는 서서히 반영."""
    tab = Table({"mach": (0.4, 0.8)}, (-3.0, -1.5), extrapolate="clip")
    gs = GainSchedule({"pitch.kp": tab}, filter_tau=1.0).init(DT)
    assert gs.step(0.4, 0.0, 0.0)["pitch"]["kp"] == pytest.approx(-3.0)  # 시드
    p = math.exp(-DT / 1.0)
    mach_f = 0.4 + (1.0 - p) * 0.4  # 0.8 점프의 1스텝 필터값
    expected = -3.0 + (mach_f - 0.4) / 0.4 * 1.5
    assert gs.step(0.8, 0.0, 0.0)["pitch"]["kp"] == pytest.approx(expected, rel=1e-9)


def test_schedule_validation():
    bad_axis = Table({"speed": (0.0, 1.0)}, (1.0, 2.0))
    with pytest.raises(ValueError):
        GainSchedule({"pitch.kp": bad_axis})
    ok = Table({"mach": (0.0, 1.0)}, (1.0, 2.0))
    with pytest.raises(ValueError):
        GainSchedule({"no_dot_name": ok})


def test_max_adjacent_jump_detects_discontinuity():
    """게인 테이블 불연속 검출 (01 §3.4 스케줄 검증 요구)."""
    tab = Table({"mach": (0.2, 0.4, 0.6, 0.8)}, (0.0, 0.1, 5.0, 5.1))
    assert max_adjacent_jump(tab) == {"mach": pytest.approx(4.9)}
    tab2 = Table({"mach": (0.2, 0.4), "alt": (0.0, 1000.0)}, [[1.0, 1.2], [1.1, 9.0]])
    jumps = max_adjacent_jump(tab2)
    assert jumps["mach"] == pytest.approx(7.8)  # 1.2→9.0 (alt=1000 열)
    assert jumps["alt"] == pytest.approx(7.9)  # 1.1→9.0 (mach=0.4 행)


# ---------- α 리미터 ----------


def test_schedule_group_typo_rejected_at_assembly():
    """그룹 이름 오타는 분배 필터에서 조용히 버려짐 — 조립 시 시끄럽게 거부 (리뷰 Must fix)."""
    tab = Table({"mach": (0.4, 0.8)}, (-3.0, -1.5), extrapolate="clip")
    sched = GainSchedule({"ptich.kp": tab})  # 오타
    with pytest.raises(ValueError):
        FlightControlLaw(
            Scas(ScasAxis(), ScasAxis(), ScasAxis()), Autopilot(), Mixer(), schedule=sched
        )


def test_alpha_limiter_rejects_multiaxis_and_error_policy():
    """다축 실속 테이블·error 외삽 정책은 조용한 오조회/비행 중 예외 — 생성 시 거부 (리뷰 Must fix)."""
    two_d = Table({"mach": (0.2, 0.8), "alt": (0.0, 5000.0)},
                  [[0.35, 0.35], [0.30, 0.30]], extrapolate="clip")
    with pytest.raises(ValueError):
        AlphaLimiter(two_d)
    err_tab = Table({"mach": (0.2, 0.8)}, (0.35, 0.30), extrapolate="error")
    with pytest.raises(ValueError):
        AlphaLimiter(err_tab)


def test_alpha_limiter_caps_pitch_command():
    lim = AlphaLimiter(make_demo_stall_table(), margin=0.05)
    assert lim.alpha_max(0.3) == pytest.approx(0.30)  # 데모 α_stall(0.3)=0.35 − 0.05
    alpha = math.atan2(25.0, 100.0)
    nav = _nav(vel_b=(100.0, 0.0, 25.0), theta=0.25)
    cap = 0.25 + (0.30 - alpha)
    th_c, active, margin = lim.step(0.6, nav, mach=0.3)
    assert active and th_c == pytest.approx(cap, rel=1e-9)
    assert margin == pytest.approx(0.30 - alpha, rel=1e-9)
    th_c2, active2, _ = lim.step(cap - 0.01, nav, mach=0.3)
    assert not active2 and th_c2 == pytest.approx(cap - 0.01)


# ---------- 믹서 ----------


def test_mixer_reconstruction_identity():
    """좌=de+da, 우=de−da → 평균=de, (좌−우)/2=da (계약 순서 [내좌,외좌,내우,외우])."""
    sc = Mixer().init(DT).step(de=0.1, da=0.03, dr=-0.05, thr=0.4)
    assert np.allclose(sc.elevon, (0.13, 0.13, 0.07, 0.07))
    assert np.mean(sc.elevon) == pytest.approx(0.1)
    assert (sc.elevon[0] - sc.elevon[2]) / 2.0 == pytest.approx(0.03)
    assert sc.rudder == pytest.approx(-0.05)
    assert np.allclose(sc.throttle, (0.4, 0.4))


def test_mixer_differential_thrust_compensation():
    """차동추력 보상 (01 §3.2): 클램프된 실 러더 기준 분배 — 러더가 내지 못하는
    명령에 추력이 반응하지 않음 (리뷰 반영)."""
    mx = Mixer(k_diff_thr=0.1).init(DT)
    sc = mx.step(0.0, 0.0, 0.2, 0.5)
    assert sc.throttle[0] == pytest.approx(0.48) and sc.throttle[1] == pytest.approx(0.52)
    sc2 = mx.step(0.0, 0.0, 5.0, 0.9)  # dr 클램프 0.35 → d=0.035
    assert sc2.rudder == pytest.approx(0.35)
    assert sc2.throttle[0] == pytest.approx(0.865)
    assert sc2.throttle[1] == pytest.approx(0.935)


def test_mixer_per_surface_saturation():
    sc = Mixer().init(DT).step(de=0.3, da=0.2, dr=0.5, thr=0.5)
    assert np.allclose(sc.elevon, (0.35, 0.35, 0.1, 0.1))  # 좌측만 포화
    assert sc.rudder == pytest.approx(0.35)


# ---------- FCL 최상위 조립 ----------


@pytest.fixture(scope="module")
def trim_design():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    return ac, tr


def _nav_from_trim(tr):
    q = tr.state.q_nb
    return NavOutput(pos_n=np.array([0.0, 0.0, -1000.0]),
                     vel_n=np.asarray(tr.state.vel_n(), dtype=float),
                     q_nb=q.copy(), omega_b=np.zeros(3), fuel=200.0, valid=True)


def test_fcl_trim_equilibrium_end_to_end(trim_design):
    """트림 웜스타트 + 트림 항법 + 전 축 off → 출력 = 트림 타면·스로틀 (평형 유지)."""
    _, tr = trim_design
    de0, thr0 = float(tr.control.elevon[0]), float(tr.control.throttle[0])
    th0 = tr.state.euler()[1]
    fcl = make_demo_fcl().init(DT)
    fcl.reset(state={"theta": th0, "throttle": thr0, "de": de0})
    for _ in range(20):
        sc = fcl.step(GuidanceCommand(), _nav_from_trim(tr))
        assert np.allclose(sc.elevon, de0, atol=1e-9)
        assert sc.rudder == pytest.approx(0.0, abs=1e-9)
        assert np.allclose(sc.throttle, thr0, atol=1e-9)


def test_fcl_invalid_nav_holds_last_command(trim_design):
    _, tr = trim_design
    de0, thr0 = float(tr.control.elevon[0]), float(tr.control.throttle[0])
    fcl = make_demo_fcl().init(DT)
    fcl.reset(state={"theta": tr.state.euler()[1], "throttle": thr0, "de": de0})
    # 첫 유효 이전 invalid → 웜스타트 홀드 명령
    sc = fcl.step(GuidanceCommand(), NavOutput(valid=False))
    assert np.allclose(sc.elevon, de0) and np.allclose(sc.throttle, thr0)
    # 유효 스텝 후 invalid → 마지막 유효 명령 유지
    good = fcl.step(GuidanceCommand(alt=1200.0, alt_on=True), _nav_from_trim(tr))
    held = fcl.step(GuidanceCommand(alt=1200.0, alt_on=True), NavOutput(valid=False))
    assert np.allclose(held.elevon, good.elevon) and np.allclose(held.throttle, good.throttle)


def test_fcl_schedule_scales_gain_off_design(trim_design):
    """M0.4에서 동압 스케줄 f=(0.6/0.4)²=2.25 — P항 응답이 정확히 2.25배."""
    _, tr = trim_design
    from claw.env import isa_atmosphere

    V04 = 0.4 * isa_atmosphere(1000.0).a
    nav = _nav(vel_b=(V04, 0.0, 0.0), h=1000.0)
    cmd = GuidanceCommand()
    e = 0.01  # θ 오차 (웜스타트 θ에 오프셋)

    def first_de(with_schedule):
        fcl = make_demo_fcl(with_schedule=with_schedule).init(DT)
        fcl.reset(state={"theta": e, "throttle": 0.3, "de": 0.0})
        return float(fcl.step(cmd, nav).elevon[0])

    assert first_de(True) == pytest.approx(2.25 * first_de(False), rel=1e-6)


def test_fcl_alpha_limiter_prevents_stall_closed_loop():
    """M0.3 급피치업 (θ_cmd≈0.45): 리미터 없으면 α>0.34(경계 초과),
    있으면 α≤0.31 (α_max=0.30) — 리미터가 실제 하중을 지는지 검증."""
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("slow", mach=0.3, alt=500.0, fuel=300.0))
    assert tr.converged
    th0 = tr.state.euler()[1]

    def alpha_max_closed_loop(with_limiter):
        scas = Scas(ScasAxis(**DEMO_PITCH), ScasAxis(**DEMO_ROLL), ScasAxis(**DEMO_YAW))
        ap = Autopilot(theta_hi=0.45, tau_alt=0.0, kp_alt=0.01, ki_alt=0.0005, k_hdot=-0.01)
        lim = AlphaLimiter(make_demo_stall_table(), margin=0.05) if with_limiter else None
        fcl = FlightControlLaw(scas, ap, Mixer(), alpha_limiter=lim).init(DT)
        fcl.reset(state={"theta": th0, "throttle": float(tr.control.throttle[0]),
                         "de": float(tr.control.elevon[0])})
        cmd = GuidanceCommand(alt=1300.0, alt_on=True)
        xe = np.zeros(12)
        xe[XE_U], xe[XE_W] = tr.state.vel_b[0], tr.state.vel_b[2]
        xe[XE_THETA], xe[XE_H] = th0, 500.0
        amax = 0.0
        engaged = False
        for k in range(int(15.0 / DT)):
            phi, th, psi = xe[6], xe[7], xe[8]
            nav = NavOutput(pos_n=np.array([0.0, 0.0, -xe[XE_H]]),
                            vel_n=euler_to_dcm(phi, th, psi).T @ xe[:3],
                            q_nb=euler_to_quat(phi, th, psi), omega_b=xe[3:6].copy(),
                            fuel=300.0)
            sc = fcl.step(cmd, nav)
            engaged = engaged or fcl.limiter_active
            ctrl = {"de": float(np.mean(sc.elevon)),
                    "da": float((sc.elevon[0] - sc.elevon[2]) / 2.0),
                    "dr": sc.rudder, "throttle": tuple(sc.throttle)}
            xe = rk4_step(lambda s: ac.deriv_euler(s, ctrl, 300.0), xe, DT)
            amax = max(amax, float(np.arctan2(xe[XE_W], xe[XE_U])))
        return amax, engaged

    a_off, _ = alpha_max_closed_loop(False)
    a_on, engaged = alpha_max_closed_loop(True)
    assert a_off > 0.34  # 리미터 없으면 실속 경계(0.35) 급접근
    assert a_on <= 0.31 and engaged  # α_max=0.30 + 소량 오버슈트 허용


def test_make_demo_fcl_gain_tables_injection():
    """게인 테이블 주입 (M13 게인 편집 경로) — 동일 테이블 주입 = 기본 조립과 동일."""
    from claw.fcl.demo import make_demo_gain_tables

    fcl_default = make_demo_fcl().init(0.01)
    fcl_injected = make_demo_fcl(gain_tables=make_demo_gain_tables()).init(0.01)
    g1 = fcl_default.schedule.step(0.3, 1000.0, 200.0)
    g2 = fcl_injected.schedule.step(0.3, 1000.0, 200.0)
    assert g1 == g2
    # 편집된 테이블이 실제 반영되는지 — 피치 kp 2배 테이블 → 스케줄 값 2배
    doubled = dict(make_demo_gain_tables())
    t = doubled["pitch.kp"]
    doubled["pitch.kp"] = Table(
        {"mach": t.axes[0]}, t.data * 2.0, name="pitch.kp", extrapolate="clip"
    )
    fcl2 = make_demo_fcl(gain_tables=doubled).init(0.01)
    g3 = fcl2.schedule.step(0.3, 1000.0, 200.0)
    assert g3["pitch"]["kp"] == pytest.approx(2.0 * g2["pitch"]["kp"])
    # 미정의 그룹 이름은 FCL 조립 검증이 거부
    bad = {"pitchX.kp": Table({"mach": (0.2, 0.8)}, (1.0, 1.0), extrapolate="clip")}
    with pytest.raises(ValueError):
        make_demo_fcl(gain_tables=bad)
    # 미정의 게인 "키"도 조립 시 거부 — 실행 시점 TypeError 지연 금지 (리뷰 M1)
    bad_key = {"pitch.kpX": Table({"mach": (0.2, 0.8)}, (1.0, 1.0), extrapolate="clip")}
    with pytest.raises(ValueError):
        make_demo_fcl(gain_tables=bad_key)
    # 생성자 파라미터지만 스텝 덮어쓰기 불가 키 (washout_tau)도 거부
    bad_tau = {"yaw.washout_tau": Table({"mach": (0.2, 0.8)}, (2.0, 2.0), extrapolate="clip")}
    with pytest.raises(ValueError):
        make_demo_fcl(gain_tables=bad_tau)
    # 스케줄 비활성 조립에 테이블 주입은 구성 오류
    with pytest.raises(ValueError):
        make_demo_fcl(with_schedule=False, gain_tables=make_demo_gain_tables())
