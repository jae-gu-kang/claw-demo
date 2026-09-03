"""좌표 변환·바람각 (conventions.md §1·§4). WGS-84 측지 변환은 env 모듈(M4) 소관."""

import numpy as np

from claw.common.attitude import quat_to_dcm


def ned_to_body(q_nb, v_n):
    return quat_to_dcm(q_nb) @ np.asarray(v_n, dtype=float)


def body_to_ned(q_nb, v_b):
    return quat_to_dcm(q_nb).T @ np.asarray(v_b, dtype=float)


# 바람각이 정의되는 최소 공기속도 [m/s] [기본값] — **정지 판정이지 물리 문턱이 아니다.**
#
# α·β는 상대풍의 방향이라 상대풍이 없으면 정의되지 않는다. 종전 가드는 `V == 0.0`
# 부동소수 정확 비교였는데, 적분기가 남기는 잔차 때문에 **실제로는 한 번도 발동하지
# 않았다**: 착륙 후 선 기체를 재면 V ≈ 3e-15 m/s이고 u의 부호가 매 스텝 뒤집힌다.
# 그러면 α = atan2(±1e-15, ∓1e-18) = ±π/2~±π가 나오고, 그 값이 공력 DB 유효범위
# (α −0.2~0.45)를 벗어나 **선 채로 실속 플래그가 선다**. 실측: 정지 후 9,028 표본 중
# 95.3%가 |α| > 0.45.
#
# 0.1 m/s인 근거 셋. ① **공력이 없다**: 동압이 q̄S = 0.5·1.225·0.1²·3.0 ≈ 0.018 N이라
# 이 기체 중량 11.8 kN의 백만분의 일이다. ② **잡음대에서 충분히 멀다**: 문턱 없이
# α가 DB 범위를 벗어나는 표본의 최대 속도가 0.00144 m/s이므로 필요 최소 문턱의
# **69배**다. (0.01로도 플래그는 사라지지만 여유가 6.9배뿐이라, 시나리오가 조금만
# 달라져도 다시 샌다 — 그 값은 "테스트가 통과하는 최소치"였다.) ③ **실제로 움직이는
# 구간에 안 닿는다**: 시뮬 자신의 정지 판정이 speed_le 0.5이고 착륙 활주 구간의 최저
# 속도가 0.463 m/s다. 문턱은 그 21%이고 비행 속도대(≥76.5 m/s)와는 세 자릿수 떨어져 있다.
#
# V 자체는 그대로 낸다 — 정의되지 않는 것은 **각도**이지 속도가 아니다. (V가 정확히
# 0이면 종전과 똑같이 (0, 0, 0)이 나온다.)
#
# **닫는 범위를 정확히 말해 둔다: 참값 경로만이다.** 같은 함수를 fcl/airdata.py가
# 항법 추정 속도(NavOutput.vel_n)에도 부르는데, 거기에는 백색잡음이 실려 있고
# σ가 0.3~0.45 m/s(nav/error_model.py)라 **이 문턱의 서너 배**다. 그래서 정지 상태의
# α 리미터·β는 이 수정 뒤에도 잡음이 만든 큰 각을 본다. 그쪽을 닫으려면 속도 문턱이
# 아니라 항법 쪽 처리(접지 게이팅 등)가 필요하고, 그건 별개 사안 [TBD]이다.
V_ANGLE_MIN = 0.1


def wind_angles(vel_air_b):
    """공기속도 동체 성분 (u, v, w) → (V, α, β). α = atan2(w, u), β = asin(v/V).

    V < V_ANGLE_MIN이면 상대풍이 없다고 보고 α = β = 0 (위 주석 참조).
    """
    u, v, w = np.asarray(vel_air_b, dtype=float)
    V = float(np.sqrt(u * u + v * v + w * w))
    if V < V_ANGLE_MIN:
        return V, 0.0, 0.0
    alpha = float(np.arctan2(w, u))
    beta = float(np.arcsin(np.clip(v / V, -1.0, 1.0)))
    return V, alpha, beta
