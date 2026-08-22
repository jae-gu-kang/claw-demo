"""M7 오토파일럿 검증 — 명령필터 해석해, 축별 방향·유지 거동, 비선형 폐루프 캡처 성능.

폐루프 게인(블록 기본값)은 비선형 데모 플랜트+SCAS 폐루프 스캔으로 선정한 설계값:
고도 +100 m 오버슈트 8.3%·V 강하 0.62 m/s, 속도 +10 m/s 오버슈트 3.7%,
헤딩 0.5 rad 오버슈트 없음·고도 강하 1.1 m (선회 피치 FF 0.05 적용 시).
"""

import math

import numpy as np
import pytest

from claw.common.attitude import euler_to_dcm, euler_to_quat, wrap_pi
from claw.common.contracts import GuidanceCommand, NavOutput, TrimCase
from claw.fcl import Autopilot, CommandFilter, Scas, ScasAxis
from claw.plant import XE_H, XE_PSI, XE_THETA, XE_U, XE_W, make_demo_aircraft, rk4_step
from claw.trim import trim_level

DT = 0.01
PITCH = dict(kp=-2.0, ki=-0.5, k_rate=0.4, out_lo=-0.35, out_hi=0.35)
ROLL = dict(kp=1.0, ki=0.1, k_rate=-0.2, out_lo=-0.35, out_hi=0.35)
YAW = dict(kp=0.5, ki=0.0, k_rate=0.8, washout_tau=2.0, out_lo=-0.35, out_hi=0.35)


@pytest.fixture(scope="module")
def design_point():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    return ac, tr


# ---------- 명령필터 (01 §3.2 [기본값]) ----------


def test_command_filter_seed_and_exact_sequence():
    """첫 스텝은 현재 측정에서 시드(캡처 거동), 이후 x_k = cmd − (cmd−seed)·p^k 정확."""
    f = CommandFilter(tau=2.0).init(DT)
    p = math.exp(-DT / 2.0)
    cmd, seed = 110.0, 100.0
    for k in range(1, 300):
        x = f.step(cmd, seed)
        assert x == pytest.approx(cmd - (cmd - seed) * p**k, rel=1e-12)


def test_command_filter_angle_wraps_shortest_path():
    """±π 경계를 넘는 헤딩 명령 — 최단 경로로 수렴, 출력은 항상 [−π, π]."""
    f = CommandFilter(tau=0.5, angle=True).init(DT)
    cmd, seed = 3.0, -3.0  # 최단 경로는 −방향 0.283 rad (π 경계 통과)
    xs = [f.step(cmd, seed) for _ in range(2000)]
    assert all(-math.pi <= x <= math.pi for x in xs)
    assert wrap_pi(xs[-1] - cmd) == pytest.approx(0.0, abs=1e-6)
    # 반대 방향(6.0 rad 돌아가기)이 아니라 0.283 rad 이동이었는지 — 초반 이동 방향 확인
    assert wrap_pi(xs[0] - seed) < 0.0


def test_command_filter_off_tracks_measurement():
    """비활성 축 추적: reset_to로 현재 측정에 재시드 → 활성화 시 현재값부터 램프."""
    f = CommandFilter(tau=2.0).init(DT)
    f.step(100.0, 90.0)
    f.reset_to(55.0)
    assert f.step(60.0, 0.0) == pytest.approx(55.0 + (1.0 - math.exp(-DT / 2.0)) * 5.0)


def test_command_filter_tau_zero_passthrough():
    """tau=0 = 필터 통과 (즉시 명령) — 문서화된 분기 핀."""
    f = CommandFilter(tau=0.0).init(DT)
    assert f.step(123.0, 0.0) == 123.0
    assert f.step(-7.0, 0.0) == -7.0


def test_phi_max_guard_quarter_pi():
    """phi_max ≥ π/2는 선회 FF 부호 반전 — 생성자 가드 (리뷰 반영)."""
    with pytest.raises(ValueError):
        Autopilot(phi_max=1.6)


# ---------- 축별 방향·유지 거동 (단위) ----------


def _nav(vel_b=(200.0, 0.0, 0.0), h=1000.0, phi=0.0, theta=0.0, psi=0.0, omega=(0, 0, 0)):
    q = euler_to_quat(phi, theta, psi)
    vel_n = euler_to_dcm(phi, theta, psi).T @ np.asarray(vel_b, dtype=float)
    return NavOutput(pos_n=np.array([0.0, 0.0, -h]), vel_n=vel_n, q_nb=q,
                     omega_b=np.asarray(omega, dtype=float))


def make_ap(**over):
    ap = Autopilot(**over).init(DT)
    ap.reset(state={"throttle": 0.2, "theta": 0.04})
    return ap


def test_axes_off_hold_warm_start():
    """전 축 비활성 → 트림 웜스타트 값 유지 (θ=적분기, φ=0, thr=적분기)."""
    ap = make_ap()
    cmd = GuidanceCommand()  # 전 축 off
    for _ in range(50):
        th_c, phi_c, thr = ap.step(cmd, _nav())
        assert th_c == pytest.approx(0.04) and phi_c == 0.0 and thr == pytest.approx(0.2)


def test_speed_loop_direction():
    ap = make_ap()
    cmd = GuidanceCommand(speed=210.0, speed_on=True)
    _, _, thr = ap.step(cmd, _nav())
    assert thr > 0.2  # 저속 → 증추력
    ap = make_ap()
    cmd = GuidanceCommand(speed=190.0, speed_on=True)
    _, _, thr = ap.step(cmd, _nav())
    assert thr < 0.2


def test_alt_loop_direction_and_theta_limit():
    ap = make_ap()
    th_c, _, _ = ap.step(GuidanceCommand(alt=1100.0, alt_on=True), _nav())
    assert th_c > 0.04  # 저고도 → 기수올림
    ap = make_ap(tau_alt=1e-9)  # 필터 즉시 통과로 큰 오차 노출
    th_c, _, _ = ap.step(GuidanceCommand(alt=9000.0, alt_on=True), _nav())
    assert th_c == pytest.approx(ap.theta_hi)


def test_heading_shortest_path_and_bank_limit():
    """ψ=+3.0에서 −3.0 명령 — 오차 wrap +0.283 → 우선회(φ>0), |φ|≤φ_max."""
    ap = make_ap(tau_hdg=1e-9)
    _, phi_c, _ = ap.step(GuidanceCommand(heading=-3.0, heading_on=True), _nav(psi=3.0))
    assert 0.0 < phi_c <= ap.phi_max
    ap = make_ap(tau_hdg=1e-9)
    _, phi_c, _ = ap.step(GuidanceCommand(heading=math.pi, heading_on=True), _nav(psi=0.0))
    assert phi_c == pytest.approx(ap.phi_max)  # 대오차 → 뱅크 한계 클립


def test_turn_pitch_feedforward():
    """선회 중 피치 FF: φ_cmd≠0이면 θ_cmd 상승 (델타윙 고도손실 보상, 01 §3.3.1)."""
    ap0 = make_ap()
    th_level, _, _ = ap0.step(GuidanceCommand(alt=1000.0, alt_on=True), _nav())
    ap1 = make_ap(tau_hdg=1e-9)
    th_turn, phi_c, _ = ap1.step(
        GuidanceCommand(alt=1000.0, alt_on=True, heading=1.0, heading_on=True), _nav()
    )
    assert phi_c != 0.0
    assert th_turn - th_level == pytest.approx(
        ap1.k_pitch_turn * (1.0 / math.cos(phi_c) - 1.0), rel=1e-9
    )


def test_alt_reengage_bumpless_after_drift():
    """관여→해제→고도 드리프트→재관여: 필터 재시드로 첫 스텝이 홀드값 근방 (슬램 없음)."""
    ap = make_ap()
    on = GuidanceCommand(alt=1000.0, alt_on=True)
    off = GuidanceCommand()
    ap.step(on, _nav(h=1000.0))
    for _ in range(10):
        ap.step(off, _nav(h=900.0))  # 해제 중 100 m 드리프트 — 필터가 측정 추적
    th_c, _, _ = ap.step(on, _nav(h=900.0))
    # 재시드 없으면 100 m 오차 슬램(θ→상한). 재시드 시 (1−p)·100 m 오차만 반영
    assert abs(th_c - 0.04) < 2e-3


def test_heading_reengage_no_integrator_kick():
    """ki_hdg≠0 포화 선회 후 해제→정침 재관여 — 적분기 잔존 뱅크 킥 없음 (리뷰 Must fix)."""
    ap = make_ap(ki_hdg=0.5, tau_hdg=1e-9)
    on = GuidanceCommand(heading=0.5, heading_on=True)
    for _ in range(200):
        ap.step(on, _nav(psi=0.0))  # 대오차 지속 → 적분기 와인드업
    for _ in range(5):
        ap.step(GuidanceCommand(), _nav(psi=0.5))  # 해제
    _, phi_c, _ = ap.step(GuidanceCommand(heading=0.5, heading_on=True), _nav(psi=0.5))
    assert abs(phi_c) < 1e-6  # 오차 0 재관여 → 뱅크 명령 0


# ---------- 비선형 폐루프 캡처 (AP 기본 게인 = 설계값) ----------


def _closed_loop(ac, tr, cmd: GuidanceCommand, t_end=60.0):
    th0 = tr.state.euler()[1]
    ap = Autopilot().init(DT)
    ap.reset(state={"throttle": float(tr.control.throttle[0]), "theta": th0})
    scas = Scas(ScasAxis(**PITCH), ScasAxis(**ROLL), ScasAxis(**YAW)).init(DT)
    # 웜스타트는 조립(Scas)에 넣는다 — 축 인스턴스는 파라미터 보유자이고 상태는
    # 조립의 러너 한 곳에만 있다 (거기 넣지 않으면 조용히 무시되는 대신 터진다)
    scas.reset(states={"pitch": float(tr.control.elevon[0])})
    xe = np.zeros(12)
    xe[XE_U], xe[XE_W] = tr.state.vel_b[0], tr.state.vel_b[2]
    xe[XE_THETA], xe[XE_H] = th0, 1000.0
    log = {"h": [], "V": [], "psi": []}
    for k in range(int(t_end / DT)):
        phi, th, psi = xe[6], xe[7], xe[8]
        q = euler_to_quat(phi, th, psi)
        nav = NavOutput(t=k * DT, pos_n=np.array([xe[9], xe[10], -xe[XE_H]]),
                        vel_n=euler_to_dcm(phi, th, psi).T @ xe[:3],
                        q_nb=q, omega_b=xe[3:6].copy(), t_meas=k * DT)
        th_c, phi_c, thr = ap.step(cmd, nav)
        de, da, dr = scas.step(th_c, phi_c, nav)
        ctrl = {"de": de, "da": da, "dr": dr, "throttle": (thr, thr)}
        xe = rk4_step(lambda s: ac.deriv_euler(s, ctrl, 200.0), xe, DT)
        log["h"].append(xe[XE_H])
        log["V"].append(float(np.linalg.norm(xe[:3])))
        log["psi"].append(xe[XE_PSI])
    return {k: np.array(v) for k, v in log.items()}


def test_alt_capture_nonlinear(design_point):
    ac, tr = design_point
    V0 = float(np.linalg.norm(tr.state.vel_b))
    cmd = GuidanceCommand(speed=V0, alt=1100.0, heading=0.0,
                          speed_on=True, alt_on=True, heading_on=True)
    log = _closed_loop(ac, tr, cmd)
    assert (np.max(log["h"]) - 1100.0) / 100.0 < 0.12  # 오버슈트 <12% (설계 8.3%)
    assert abs(log["h"][-1] - 1100.0) < 1.0
    assert V0 - np.min(log["V"]) < 2.0  # 상승 중 속도 강하 억제


def test_speed_step_nonlinear(design_point):
    ac, tr = design_point
    V0 = float(np.linalg.norm(tr.state.vel_b))
    cmd = GuidanceCommand(speed=V0 + 10.0, alt=1000.0, heading=0.0,
                          speed_on=True, alt_on=True, heading_on=True)
    log = _closed_loop(ac, tr, cmd)
    assert (np.max(log["V"]) - (V0 + 10.0)) / 10.0 < 0.08  # 오버슈트 <8% (설계 3.7%)
    assert abs(log["V"][-1] - (V0 + 10.0)) < 0.2
    assert np.max(np.abs(log["h"] - 1000.0)) < 3.0  # 고도 결합 억제


def test_heading_capture_nonlinear(design_point):
    ac, tr = design_point
    V0 = float(np.linalg.norm(tr.state.vel_b))
    cmd = GuidanceCommand(speed=V0, alt=1000.0, heading=0.5,
                          speed_on=True, alt_on=True, heading_on=True)
    log = _closed_loop(ac, tr, cmd)
    assert np.max(log["psi"]) < 0.5 * 1.02  # 오버슈트 사실상 없음 (설계 −0.02%)
    assert abs(wrap_pi(log["psi"][-1] - 0.5)) < 0.01
    assert 1000.0 - np.min(log["h"]) < 3.0  # 선회 고도손실 FF 보상 (설계 1.1 m)


def test_phi_max_guard_matches_paramdef_hi():
    """생성자 가드 == ParamDef hi(1.5) — 스키마가 노출하는 범위와 실제 수용 범위
    일치 (리뷰: 1.5 < phi_max < π/2 구간이 조용히 통과하던 불일치 봉쇄)."""
    Autopilot(phi_max=1.5)  # 경계 수용
    with pytest.raises(ValueError):
        Autopilot(phi_max=1.55)  # ParamDef hi 초과 (기존 가드 π/2보다는 작음)
    with pytest.raises(ValueError):
        Autopilot(phi_max=-0.1)
