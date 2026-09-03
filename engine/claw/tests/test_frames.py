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


def test_wind_angles_are_zero_when_effectively_at_rest():
    """정지 기체의 α·β는 0이다 — 상대풍이 없으면 각도가 정의되지 않는다.

    회귀 근거: 종전 가드는 `V == 0.0` 부동소수 정확 비교라 **한 번도 발동하지 않았다**.
    착륙 후 선 기체를 재면 적분 잔차로 V ≈ 3e-15 m/s이고 u의 부호가 매 스텝 뒤집혀
    α = atan2(±1e-15, ∓1e-18) = ±π/2~±π가 나왔다. 그 값이 공력 DB 유효범위를 벗어나
    **선 채로 실속 플래그가 서고**, 착륙 시나리오 22,000 표본 중 8,608회가 그랬다.
    """
    # 실측에서 실제로 나온 형태 — u가 미세하게 음수, w는 그보다 작다
    V, alpha, beta = frames.wind_angles([-1e-18, 0.0, 3e-15])
    assert alpha == 0.0 and beta == 0.0, "정지 잔차에서 각도를 지어내면 안 된다"
    # abs=0.0이 필수다 — approx의 기본 절대허용오차가 1e-12라 abs를 안 끄면 V=0.0도
    # 통과해서, "각도만 0으로 하고 V는 그대로 낸다"는 이 함수의 계약을 못 잡는다 (리뷰)
    assert V > 0.0, "정의되지 않는 것은 각도이지 속도가 아니다 — V를 0으로 뭉개면 안 된다"
    assert V == pytest.approx(3e-15, rel=1e-6, abs=0.0)  # u 항이 1e-7 상대로 섞인다

    # 문턱 자체를 양쪽에서 못박는다 — 값을 바꾸면 여기가 운다
    below = 0.999 * frames.V_ANGLE_MIN
    above = 1.001 * frames.V_ANGLE_MIN
    assert frames.wind_angles([below / np.sqrt(2), 0.0, below / np.sqrt(2)])[1] == 0.0
    assert frames.wind_angles([above / np.sqrt(2), 0.0, above / np.sqrt(2)])[1] != 0.0

    # 문턱 위는 정상 계산 — 실제로 움직이는 구간에 손대지 않는다
    V2, alpha2, _ = frames.wind_angles([10.0 * frames.V_ANGLE_MIN, 0.0, 10.0 * frames.V_ANGLE_MIN])
    assert alpha2 == pytest.approx(np.pi / 4)
    assert V2 == pytest.approx(np.sqrt(2.0) * 10.0 * frames.V_ANGLE_MIN)
    # 핀하고 싶은 명제는 "비행 속도대에서 멀다"이지 "문턱이 작다"가 아니다 — 후자로
    # 적으면 문턱을 **올리는** 방향의 변경을 테스트가 막는다 (리뷰). 착륙 활주 구간의
    # 최저 속도가 0.463 m/s이므로 그 절반 아래면 실제로 움직이는 구간에 안 닿는다
    assert frames.V_ANGLE_MIN < 0.463 / 2
