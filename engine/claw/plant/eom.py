"""6DOF 강체 운동방정식 + RK4 고정스텝 적분 (03 M5.eom, 구현 문서 §6).

상태 벡터 x (13,): [pos_n(3), vel_b(3), q_nb(4), omega_b(3)] — conventions.md 규약
(NED, 동체 FRD, 쿼터니언 scalar-first Hamilton).

    ṗ_n = C_nb·v_b
    v̇_b = F_b/m − ω×v_b
    q̇   = ½ q ⊗ (0, ω)
    ω̇   = J⁻¹(M_b − ω×Jω)

힘·모멘트는 콜백 fm(x) -> (F_b, M_b)로 주입 — 중력 포함 여부는 조립자(플랜트)가
결정한다 (gravity_body 헬퍼 제공). 적분 스텝마다 쿼터니언을 재정규화한다.
연료 소모에 따른 질량·관성 변화는 준정적(quasi-static)으로 취급 — 조립자가
스텝 사이에 m·J를 갱신한다 (구현 문서 §5.5).
"""

import numpy as np

from claw.common.attitude import quat_derivative, quat_normalize
from claw.common.constants import G0
from claw.common.frames import body_to_ned, ned_to_body

POS = slice(0, 3)
VEL = slice(3, 6)
QUAT = slice(6, 10)
OMEGA = slice(10, 13)

N_STATES = 13


def pack(pos_n, vel_b, q_nb, omega_b):
    """상태 성분 → 상태 벡터 (13,)."""
    return np.concatenate(
        [
            np.asarray(pos_n, dtype=float),
            np.asarray(vel_b, dtype=float),
            np.asarray(q_nb, dtype=float),
            np.asarray(omega_b, dtype=float),
        ]
    )


def unpack(x):
    """상태 벡터 → (pos_n, vel_b, q_nb, omega_b) 뷰."""
    return x[POS], x[VEL], x[QUAT], x[OMEGA]


def gravity_body(q_nb, mass, g=G0):
    """중력을 동체축 힘으로: C_bn·[0, 0, m·g] (NED z 하방 +)."""
    return ned_to_body(q_nb, np.array([0.0, 0.0, mass * g]))


def rk4_step(f, x, dt):
    """고전 RK4 한 스텝 — f(x) -> ẋ. 고정스텝 (구현 문서 §6 [기본값])."""
    k1 = f(x)
    k2 = f(x + 0.5 * dt * k1)
    k3 = f(x + 0.5 * dt * k2)
    k4 = f(x + dt * k3)
    return x + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


class RigidBody:
    """질량·관성 고정(준정적) 강체. m·J는 속성으로 갱신 가능 (연료 소모 반영)."""

    def __init__(self, mass, inertia):
        J = np.asarray(inertia, dtype=float)
        if mass <= 0:
            raise ValueError(f"질량은 양수여야 함: {mass}")
        if J.shape != (3, 3) or not np.allclose(J, J.T):
            raise ValueError("관성행렬은 3x3 대칭이어야 함")
        if np.any(np.diag(J) <= 0):
            raise ValueError("관성 주대각 성분은 양수여야 함")
        self.m = float(mass)
        self.J = J
        self.J_inv = np.linalg.inv(J)

    def deriv(self, x, force_b, moment_b):
        """상태미분 ẋ — force_b/moment_b는 동체축 총 외력·외모멘트 (중력 포함은 호출자 몫)."""
        v_b, q, w = x[VEL], x[QUAT], x[OMEGA]
        xdot = np.empty(N_STATES)
        xdot[POS] = body_to_ned(q, v_b)
        xdot[VEL] = np.asarray(force_b, dtype=float) / self.m - np.cross(w, v_b)
        xdot[QUAT] = quat_derivative(q, w)
        xdot[OMEGA] = self.J_inv @ (np.asarray(moment_b, dtype=float) - np.cross(w, self.J @ w))
        return xdot

    def step(self, x, fm, dt):
        """RK4 한 스텝 — fm(x) -> (F_b, M_b) 상태 의존 힘·모멘트를 부단계마다 재평가."""

        def f(xx):
            force_b, moment_b = fm(xx)
            return self.deriv(xx, force_b, moment_b)

        xn = rk4_step(f, x, dt)
        xn[QUAT] = quat_normalize(xn[QUAT])
        return xn
