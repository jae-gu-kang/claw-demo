"""M5 eom 물리검증 (Phase 2 완료 기준, 구현 문서 §7 층2) —
자유낙하 해석해, 에너지·각운동량 보존, 토크-프리 회전, RK4 수렴 차수.
"""

import numpy as np
import pytest

from claw.common.attitude import euler_to_quat
from claw.common.constants import G0
from claw.common.frames import body_to_ned
from claw.plant import OMEGA, POS, QUAT, VEL, RigidBody, gravity_body, pack, unpack

NO_FM = lambda x: (np.zeros(3), np.zeros(3))  # noqa: E731 — 힘·모멘트 없음


def test_pack_unpack_roundtrip():
    pos = np.array([1.0, 2.0, 3.0])
    vel = np.array([4.0, 5.0, 6.0])
    q = euler_to_quat(0.1, 0.2, 0.3)
    om = np.array([0.7, 0.8, 0.9])
    p, v, qq, o = unpack(pack(pos, vel, q, om))
    assert np.allclose(p, pos) and np.allclose(v, vel)
    assert np.allclose(qq, q) and np.allclose(o, om)


def test_free_fall_analytic():
    """수평자세 정지 상태에서 중력만: w = g·t, z = g·t²/2 (RK4는 다항식 해에 정확)."""
    rb = RigidBody(mass=100.0, inertia=np.diag([10.0, 20.0, 30.0]))
    x = pack(np.zeros(3), np.zeros(3), euler_to_quat(0.0, 0.0, 0.0), np.zeros(3))
    fm = lambda xx: (gravity_body(xx[QUAT], rb.m), np.zeros(3))  # noqa: E731
    dt, T = 0.01, 1.0
    for _ in range(round(T / dt)):
        x = rb.step(x, fm, dt)
    assert x[VEL][2] == pytest.approx(G0 * T, abs=1e-9)
    assert x[POS][2] == pytest.approx(0.5 * G0 * T**2, abs=1e-9)
    assert x[VEL][0] == pytest.approx(0.0, abs=1e-12)


def test_projectile_energy_conservation():
    """중력만 작용하는 포물체: E = ½m|v|² + m·g·h (h = -z_n) 보존."""
    rb = RigidBody(mass=250.0, inertia=np.diag([50.0, 80.0, 120.0]))
    q0 = euler_to_quat(0.3, 0.2, 0.1)
    x = pack(np.zeros(3), np.array([60.0, 5.0, -10.0]), q0, np.zeros(3))
    fm = lambda xx: (gravity_body(xx[QUAT], rb.m), np.zeros(3))  # noqa: E731

    def energy(xx):
        v = np.linalg.norm(xx[VEL])
        return 0.5 * rb.m * v * v + rb.m * G0 * (-xx[POS][2])

    e0 = energy(x)
    for _ in range(500):  # 5초, dt=0.01
        x = rb.step(x, fm, 0.01)
    assert energy(x) == pytest.approx(e0, rel=1e-10)


def test_torque_free_spherical_omega_constant():
    """구형 관성(J=kI): ω×Jω = 0 → ω 정확히 일정, 쿼터니언 노름 1 유지."""
    rb = RigidBody(mass=10.0, inertia=np.diag([5.0, 5.0, 5.0]))
    om0 = np.array([0.3, -0.2, 0.5])
    x = pack(np.zeros(3), np.zeros(3), euler_to_quat(0.0, 0.0, 0.0), om0)
    for _ in range(1000):
        x = rb.step(x, NO_FM, 0.005)
    assert np.allclose(x[OMEGA], om0, atol=1e-13)
    assert np.linalg.norm(x[QUAT]) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize(
    "inertia",
    [
        np.diag([4.0, 6.0, 9.0]),
        np.array([[4.0, 0.0, -0.8], [0.0, 6.0, 0.0], [-0.8, 0.0, 9.0]]),  # I_xz 결합 (델타윙)
    ],
    ids=["diagonal", "with_Ixz"],
)
def test_torque_free_conservation(inertia):
    """비대칭 토크-프리 텀블링: NED 각운동량 L_n = C_nb·(Jω)와 회전 KE 보존."""
    rb = RigidBody(mass=10.0, inertia=inertia)
    x = pack(np.zeros(3), np.zeros(3), euler_to_quat(0.1, -0.2, 0.3), np.array([0.5, 0.4, 0.3]))

    def L_n(xx):
        return body_to_ned(xx[QUAT], rb.J @ xx[OMEGA])

    def ke(xx):
        return 0.5 * xx[OMEGA] @ rb.J @ xx[OMEGA]

    L0, k0 = L_n(x), ke(x)
    for _ in range(5000):  # 5초, dt=1e-3
        x = rb.step(x, NO_FM, 1e-3)
    assert np.linalg.norm(L_n(x) - L0) / np.linalg.norm(L0) < 1e-7
    assert ke(x) == pytest.approx(k0, rel=1e-7)


def test_rk4_convergence_order():
    """스텝 반분 시 오차 ~1/16 (4차) — 비대칭 텀블링 기준 (구현 문서 §7 층2)."""
    rb = RigidBody(mass=10.0, inertia=np.diag([4.0, 6.0, 9.0]))
    x0 = pack(np.zeros(3), np.zeros(3), euler_to_quat(0.0, 0.0, 0.0), np.array([0.7, 0.5, 0.3]))

    def run(dt):
        x = x0.copy()
        for _ in range(round(1.0 / dt)):
            x = rb.step(x, NO_FM, dt)
        return x[OMEGA]

    ref = run(1.0 / 6400.0)
    e1 = np.linalg.norm(run(1.0 / 100.0) - ref)
    e2 = np.linalg.norm(run(1.0 / 200.0) - ref)
    assert 10.0 < e1 / e2 < 24.0  # 이론값 16


def test_rigid_body_validation():
    with pytest.raises(ValueError):
        RigidBody(mass=0.0, inertia=np.eye(3))
    with pytest.raises(ValueError):
        RigidBody(mass=1.0, inertia=np.array([[1.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]))
