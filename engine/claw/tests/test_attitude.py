import numpy as np
import pytest

from claw.common import attitude as att

# 브랜치·특이점 회피 케이스를 두루 포함한 오일러 세트 (φ, θ, ψ) [rad]
EULERS = [
    (0.0, 0.0, 0.0),
    (0.3, -0.5, 2.0),
    (-1.2, 0.7, -2.8),
    (3.0, 0.2, 0.1),
    (0.1, 1.45, 3.0),
    (-3.0, -1.4, -3.0),
    (0.0, 0.0, np.pi / 2),
]


def test_identity():
    assert np.allclose(att.euler_to_quat(0, 0, 0), [1, 0, 0, 0])
    assert np.allclose(att.quat_to_dcm([1, 0, 0, 0]), np.eye(3))


def test_yaw90_maps_north_to_body():
    # 기수 동쪽(ψ=90°)일 때 NED 북쪽 벡터는 동체 -y (좌현) 방향
    C = att.euler_to_dcm(0.0, 0.0, np.pi / 2)
    assert np.allclose(C @ [1.0, 0.0, 0.0], [0.0, -1.0, 0.0], atol=1e-12)


@pytest.mark.parametrize("e", EULERS)
def test_dcm_orthonormal(e):
    C = att.euler_to_dcm(*e)
    assert np.allclose(C @ C.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(C) == pytest.approx(1.0)


@pytest.mark.parametrize("e", EULERS)
def test_quat_dcm_consistency(e):
    # 쿼터니언 경로와 DCM 직접 계산이 일치해야 함
    assert np.allclose(att.quat_to_dcm(att.euler_to_quat(*e)), att.euler_to_dcm(*e), atol=1e-12)


@pytest.mark.parametrize("e", EULERS)
def test_euler_round_trip(e):
    phi, theta, psi = att.quat_to_euler(att.euler_to_quat(*e))
    assert att.wrap_pi(phi - e[0]) == pytest.approx(0.0, abs=1e-10)
    assert theta == pytest.approx(e[1], abs=1e-10)
    assert att.wrap_pi(psi - e[2]) == pytest.approx(0.0, abs=1e-10)


@pytest.mark.parametrize("e", EULERS)
def test_dcm_quat_round_trip(e):
    # Shepperd 4개 브랜치 커버 — 부호 이중성(±q)은 |내적|=1로 판정
    q = att.euler_to_quat(*e)
    q2 = att.dcm_to_quat(att.quat_to_dcm(q))
    assert abs(np.dot(q, q2)) == pytest.approx(1.0, abs=1e-10)


def test_quat_multiply_composition():
    # 합성 규칙: C(q1 ⊗ q2) = C(q2) @ C(q1)
    q1 = att.euler_to_quat(0.3, -0.5, 2.0)
    q2 = att.euler_to_quat(-1.2, 0.7, -2.8)
    left = att.quat_to_dcm(att.quat_multiply(q1, q2))
    right = att.quat_to_dcm(q2) @ att.quat_to_dcm(q1)
    assert np.allclose(left, right, atol=1e-12)


def test_quat_conjugate_inverse():
    q = att.euler_to_quat(0.4, 0.6, -1.0)
    qq = att.quat_multiply(q, att.quat_conjugate(q))
    assert np.allclose(qq, [1, 0, 0, 0], atol=1e-12)


def test_quat_derivative_pure_yaw_rate():
    # 요 각속도 r로 미소 시간 전파 → ψ ≈ r·dt
    r, dt = 0.5, 1e-4
    q = np.array([1.0, 0.0, 0.0, 0.0]) + att.quat_derivative([1, 0, 0, 0], [0, 0, r]) * dt
    _, _, psi = att.quat_to_euler(att.quat_normalize(q))
    assert psi == pytest.approx(r * dt, rel=1e-6)


def test_wrap_pi():
    assert att.wrap_pi(np.pi + 0.1) == pytest.approx(-np.pi + 0.1)
    assert att.wrap_pi(-np.pi) == pytest.approx(np.pi)  # 구간 (-π, π]
    assert att.wrap_pi(0.3) == pytest.approx(0.3)


def test_zero_quat_raises():
    with pytest.raises(ValueError):
        att.quat_normalize([0, 0, 0, 0])
