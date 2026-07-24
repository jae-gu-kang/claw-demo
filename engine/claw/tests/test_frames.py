import numpy as np
import pytest

from claw.common import frames
from claw.common.attitude import euler_to_quat


def test_wind_angles_alpha():
    V, alpha, beta = frames.wind_angles([50.0, 0.0, 5.0])
    assert V == pytest.approx(np.hypot(50.0, 5.0))
    assert alpha == pytest.approx(np.arctan2(5.0, 50.0))
    assert beta == pytest.approx(0.0)


def test_wind_angles_beta():
    V, alpha, beta = frames.wind_angles([50.0, 5.0, 0.0])
    assert alpha == pytest.approx(0.0)
    assert beta == pytest.approx(np.arcsin(5.0 / V))


def test_wind_angles_zero_speed():
    assert frames.wind_angles([0.0, 0.0, 0.0]) == (0.0, 0.0, 0.0)


def test_ned_body_round_trip():
    q = euler_to_quat(0.3, -0.5, 2.0)
    v_n = np.array([10.0, -3.0, 1.5])
    assert np.allclose(frames.body_to_ned(q, frames.ned_to_body(q, v_n)), v_n, atol=1e-12)


def test_yaw90_velocity():
    # 기수 동쪽, 전방 10 m/s → NED 속도는 동쪽 10 m/s
    q = euler_to_quat(0.0, 0.0, np.pi / 2)
    assert np.allclose(frames.body_to_ned(q, [10.0, 0.0, 0.0]), [0.0, 10.0, 0.0], atol=1e-12)
