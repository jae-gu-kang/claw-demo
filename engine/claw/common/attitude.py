"""자세 표현 (conventions.md §2).

쿼터니언 scalar-first (w, x, y, z), Hamilton 규약. q_nb = NED→동체 회전.
C_bn(q_nb) @ v_n = v_b. 오일러각 3-2-1 (ψ→θ→φ). 내부 상태 정본은 쿼터니언.

합성 규칙: C_bn(q1 ⊗ q2) = C_bn(q2) @ C_bn(q1).
3-2-1 오일러의 쿼터니언은 q_nb = q_ψ ⊗ q_θ ⊗ q_φ.
"""

import numpy as np

QUAT_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0])


def wrap_pi(a):
    """각도를 (-π, π]로 래핑."""
    return -((-np.asarray(a) + np.pi) % (2.0 * np.pi) - np.pi)


def quat_normalize(q):
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    if n == 0.0:
        raise ValueError("영 쿼터니언은 정규화 불가")
    return q / n


def quat_conjugate(q):
    q = np.asarray(q, dtype=float)
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_multiply(q1, q2):
    """Hamilton 곱 q1 ⊗ q2."""
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ]
    )


def quat_to_dcm(q):
    """q_nb → C_bn (v_b = C_bn @ v_n)."""
    w, x, y, z = quat_normalize(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
            [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
            [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def dcm_to_quat(C):
    """C_bn → q_nb. Shepperd 방법 — 4개 후보 중 최대 성분 기준 (수치 안정)."""
    C = np.asarray(C, dtype=float)
    tr = C[0, 0] + C[1, 1] + C[2, 2]
    cand = np.array(
        [1.0 + tr, 1.0 + 2.0 * C[0, 0] - tr, 1.0 + 2.0 * C[1, 1] - tr, 1.0 + 2.0 * C[2, 2] - tr]
    )
    i = int(np.argmax(cand))
    s = np.sqrt(max(cand[i], 0.0))
    if i == 0:
        w = 0.5 * s
        f = 0.25 / w
        q = [w, f * (C[1, 2] - C[2, 1]), f * (C[2, 0] - C[0, 2]), f * (C[0, 1] - C[1, 0])]
    elif i == 1:
        x = 0.5 * s
        f = 0.25 / x
        q = [f * (C[1, 2] - C[2, 1]), x, f * (C[1, 0] + C[0, 1]), f * (C[2, 0] + C[0, 2])]
    elif i == 2:
        y = 0.5 * s
        f = 0.25 / y
        q = [f * (C[2, 0] - C[0, 2]), f * (C[1, 0] + C[0, 1]), y, f * (C[2, 1] + C[1, 2])]
    else:
        z = 0.5 * s
        f = 0.25 / z
        q = [f * (C[0, 1] - C[1, 0]), f * (C[2, 0] + C[0, 2]), f * (C[2, 1] + C[1, 2]), z]
    return quat_normalize(q)


def euler_to_quat(phi, theta, psi):
    """3-2-1 오일러 (φ 롤, θ 피치, ψ 요) → q_nb."""
    cphi, sphi = np.cos(phi / 2), np.sin(phi / 2)
    cth, sth = np.cos(theta / 2), np.sin(theta / 2)
    cpsi, spsi = np.cos(psi / 2), np.sin(psi / 2)
    return np.array(
        [
            cphi * cth * cpsi + sphi * sth * spsi,
            sphi * cth * cpsi - cphi * sth * spsi,
            cphi * sth * cpsi + sphi * cth * spsi,
            cphi * cth * spsi - sphi * sth * cpsi,
        ]
    )


def quat_to_euler(q):
    """q_nb → (φ, θ, ψ). θ = ±π/2 특이점 부근에서 φ·ψ는 불정."""
    w, x, y, z = quat_normalize(q)
    phi = np.arctan2(2 * (y * z + w * x), 1 - 2 * (x * x + y * y))
    theta = np.arcsin(np.clip(2 * (w * y - x * z), -1.0, 1.0))
    psi = np.arctan2(2 * (x * y + w * z), 1 - 2 * (y * y + z * z))
    return phi, theta, psi


def euler_to_dcm(phi, theta, psi):
    """3-2-1 오일러 → C_bn."""
    cphi, sphi = np.cos(phi), np.sin(phi)
    cth, sth = np.cos(theta), np.sin(theta)
    cpsi, spsi = np.cos(psi), np.sin(psi)
    return np.array(
        [
            [cth * cpsi, cth * spsi, -sth],
            [sphi * sth * cpsi - cphi * spsi, sphi * sth * spsi + cphi * cpsi, sphi * cth],
            [cphi * sth * cpsi + sphi * spsi, cphi * sth * spsi - sphi * cpsi, cphi * cth],
        ]
    )


def dcm_to_euler(C):
    """C_bn → (φ, θ, ψ)."""
    C = np.asarray(C, dtype=float)
    phi = np.arctan2(C[1, 2], C[2, 2])
    theta = -np.arcsin(np.clip(C[0, 2], -1.0, 1.0))
    psi = np.arctan2(C[0, 1], C[0, 0])
    return phi, theta, psi


def quat_derivative(q_nb, omega_b):
    """자세 운동학: q̇_nb = ½ q_nb ⊗ (0, ω_b). ω_b는 동체축 각속도 [rad/s]."""
    ow = np.asarray(omega_b, dtype=float)
    return 0.5 * quat_multiply(q_nb, np.array([0.0, ow[0], ow[1], ow[2]]))
