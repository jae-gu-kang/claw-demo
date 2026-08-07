"""M7 SCAS 검증 — 축 해석해(PI 수열·워시아웃 감쇠), 선형모델 폐루프 성능, NavOutput 소비.

폐루프 게인은 설계점 M0.6 h1000 fuel200의 선형모델(트림→선형화, Phase 3 산출물)로
연속 고유치 스캔 + 이산 100 Hz 응답 확인을 거쳐 선정한 데모 기체 설계값.
게인 부호는 설계값이 보유 — 코드는 공력 부호를 가정하지 않음 (conventions.md).
"""

import math

import numpy as np
import pytest

from claw.common.attitude import euler_to_quat
from claw.common.contracts import NavOutput, TrimCase
from claw.fcl import Scas, ScasAxis, airdata_from_nav
from claw.plant import make_demo_aircraft, rk4_step
from claw.trim import linearize, split_axes, trim_level

DT = 0.01  # 제어주기 100 Hz [확정 시작값]

# 데모 기체 SCAS 설계값 (설계점 M0.6 h1000 fuel200)
PITCH = dict(kp=-2.0, ki=-0.5, k_rate=0.4, out_lo=-0.35, out_hi=0.35)
ROLL = dict(kp=1.0, ki=0.1, k_rate=-0.2, out_lo=-0.35, out_hi=0.35)
YAW = dict(kp=0.5, ki=0.0, k_rate=0.8, washout_tau=2.0, out_lo=-0.35, out_hi=0.35)


@pytest.fixture(scope="module")
def design_point():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    lon, lat = split_axes(linearize(ac, tr))
    return tr, lon, lat


# ---------- 축 단위 해석해 ----------


def test_axis_pi_sequence_analytic():
    """상수 오차 e에서 y_k = kp·e + ki·e·k·dt — PID forward Euler 정확 수열."""
    ax = ScasAxis(kp=2.0, ki=1.0).init(DT)
    e = 0.1
    for k in range(50):
        y = ax.step(e, 0.0)
        assert y == pytest.approx(2.0 * e + 1.0 * e * k * DT, rel=1e-12)


def test_axis_washout_rate_decays():
    """상수 각속도 입력 → 워시아웃 기여 y_k = r·p^k (ZOH-정확), 지속 선회 미대항."""
    ax = ScasAxis(k_rate=1.0, washout_tau=1.0).init(DT)
    p = math.exp(-DT / 1.0)
    r = 0.2
    for k in range(200):
        assert ax.step(0.0, r) == pytest.approx(r * p**k, rel=1e-9)


def test_axis_output_clamp_and_validation():
    ax = ScasAxis(kp=1.0, out_lo=-0.1, out_hi=0.1).init(DT)
    assert ax.step(5.0, 0.0) == 0.1
    assert ax.step(-5.0, 0.0) == -0.1
    with pytest.raises(ValueError):
        ScasAxis(out_lo=1.0, out_hi=-1.0)


def test_axis_gain_override_schedule():
    """스텝 인자 게인 덮어쓰기 — M7 게인 스케줄 주입 경로."""
    ax = ScasAxis(kp=1.0, ki=0.0, k_rate=0.0).init(DT)
    assert ax.step(0.1, 0.3) == pytest.approx(0.1)
    assert ax.step(0.1, 0.3, kp=2.0, k_rate=0.5) == pytest.approx(0.2 + 0.15)


def test_axis_reset_warm_start_bumpless():
    """reset(state)=적분기 웜스타트 — 범프리스 전환 계약."""
    ax = ScasAxis(kp=1.0, ki=1.0).init(DT)
    ax.reset(state=0.05)
    assert ax.step(0.0, 0.0) == pytest.approx(0.05)


# ---------- 선형모델 폐루프 (설계점, 이산 100 Hz) ----------


def test_pitch_closed_loop_tracks_theta_cmd(design_point):
    """θ 스텝 0.05 rad: 오버슈트<10%, 10 s 오차<2 mrad, 40 s 오차<1 mrad."""
    _, lon, _ = design_point
    ax = ScasAxis(**PITCH).init(DT)
    cmd, x, hist = 0.05, np.zeros(4), []
    for _ in range(int(40.0 / DT)):
        de = ax.step(cmd - x[3], x[2])
        x = rk4_step(lambda s: lon.A @ s + lon.B @ np.array([de, 0.0]), x, DT)
        hist.append(x[3])
    th = np.array(hist)
    assert (th.max() - cmd) / cmd < 0.10
    assert abs(th[int(10.0 / DT) - 1] - cmd) < 2e-3
    assert abs(th[-1] - cmd) < 1e-3


def test_roll_closed_loop_with_yaw_damper(design_point):
    """φ 스텝 0.3 rad (요 댐퍼 동시 작동): 오버슈트<8%, 5 s 오차<10 mrad, |β|<0.02."""
    tr, _, lat = design_point
    V0 = float(np.linalg.norm(tr.state.vel_b))
    roll = ScasAxis(**ROLL).init(DT)
    yaw = ScasAxis(**YAW).init(DT)
    cmd, x = 0.3, np.zeros(4)
    phis, betas = [], []
    for _ in range(int(20.0 / DT)):
        v, p, r, phi = x
        da = roll.step(cmd - phi, p)
        dr = yaw.step(-(v / V0), r)
        u = lat.B @ np.array([da, dr])
        x = rk4_step(lambda s: lat.A @ s + u, x, DT)
        phis.append(x[3])
        betas.append(x[0] / V0)
    phis = np.array(phis)
    assert (phis.max() - cmd) / cmd < 0.08
    assert abs(phis[int(5.0 / DT) - 1] - cmd) < 1e-2
    assert abs(phis[-1] - cmd) < 5e-3
    assert np.max(np.abs(betas)) < 0.02


def test_yaw_damper_dutch_roll_suppression(design_point):
    """v 초기교란 자유응답: 워시아웃 요 댐퍼가 ∫β²dt를 1/3 미만으로 감쇠 (개루프 ζ≈0.05)."""
    tr, _, lat = design_point
    V0 = float(np.linalg.norm(tr.state.vel_b))

    def beta_energy(with_damper):
        yaw = ScasAxis(**YAW).init(DT) if with_damper else None
        x = np.zeros(4)
        x[0] = 5.0
        acc = 0.0
        for _ in range(int(15.0 / DT)):
            dr = yaw.step(-(x[0] / V0), x[2]) if yaw else 0.0
            u = lat.B @ np.array([0.0, dr])
            x = rk4_step(lambda s: lat.A @ s + u, x, DT)
            acc += (x[0] / V0) ** 2 * DT
        return acc, abs(x[0])

    e_off, _ = beta_energy(False)
    e_on, v_end = beta_energy(True)
    assert e_on / e_off < 0.35
    assert v_end < 0.5  # 감쇠 후 잔여 사이드슬립 미미


# ---------- 3축 조립 (NavOutput 소비) ----------


def _nav(phi=0.0, theta=0.0, psi=0.0, vel_b=(200.0, 0.0, 0.0), omega=(0.0, 0.0, 0.0)):
    q = euler_to_quat(phi, theta, psi)
    from claw.common.frames import body_to_ned

    return NavOutput(q_nb=q, vel_n=body_to_ned(q, np.array(vel_b)), omega_b=np.array(omega))


def make_scas():
    return Scas(ScasAxis(**PITCH), ScasAxis(**ROLL), ScasAxis(**YAW)).init(DT)


def test_scas_assembly_signs_demo_profile():
    """데모 기체 부호: 기수올림 명령→de<0(TE up), 우롤 명령→da>0, β>0→dr<0."""
    scas = make_scas()
    de, da, dr = scas.step(0.05, 0.3, _nav())
    assert de < 0 and da > 0 and dr == 0.0
    scas.reset()
    de, da, dr = scas.step(0.0, 0.0, _nav(vel_b=(200.0, 5.0, 0.0)))
    assert dr < 0
    assert de == pytest.approx(0.0, abs=1e-12) and da == pytest.approx(0.0, abs=1e-12)


def test_scas_uses_nav_attitude_and_rates():
    """자세·각속도 피드백 반영: 명령=자세이면 P항 0, 레이트만 남음."""
    scas = make_scas()
    de, da, _ = scas.step(0.1, 0.2, _nav(phi=0.2, theta=0.1, omega=(0.05, 0.03, 0.0)))
    assert de == pytest.approx(PITCH["k_rate"] * 0.03)  # kq·q만
    assert da == pytest.approx(ROLL["k_rate"] * 0.05)  # kpp·p만


def test_scas_gain_override_dict():
    scas = make_scas()
    base = scas.step(0.05, 0.0, _nav())[0]
    scas.reset()
    doubled = scas.step(0.05, 0.0, _nav(), gains={"pitch": {"kp": -4.0}})[0]
    assert doubled == pytest.approx(2.0 * base)


def test_airdata_from_nav_roundtrip():
    """NavOutput → (V, α, β): 동체속도 재구성 일치 (바람 0 가정)."""
    nav = _nav(phi=0.1, theta=0.06, psi=1.0, vel_b=(200.0, 4.0, 12.0))
    V, alpha, beta = airdata_from_nav(nav)
    assert V == pytest.approx(math.sqrt(200.0**2 + 4.0**2 + 12.0**2), rel=1e-12)
    assert alpha == pytest.approx(math.atan2(12.0, 200.0), rel=1e-12)
    assert beta == pytest.approx(math.asin(4.0 / V), rel=1e-12)
