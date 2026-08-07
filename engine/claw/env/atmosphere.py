"""ISA 표준대기 (도메인 문서 01§2.5) — 대류권 + 등온 성층권 1층의 2층 모델.

입력 고도는 **지오퍼텐셜 고도** [m] (ISA 정의 그대로). 6DOF 플랜트가 주는
기하고도와의 변환(h_gp = r0·h / (r0 + h), r0 = 6,356,766 m)은 plant 착수 시
earth 모듈에 추가한다.

유효범위는 비행영역(씨스키밍 0 ft MSL ~ 순항)을 여유 있게 덮는
-5,000 ~ 20,000 m. 범위 밖은 조용한 외삽 대신 ValueError를 낸다
(엔벨로프 감시 원칙, 구현 문서 §6.1).
"""

import math
from dataclasses import dataclass

from claw.common.constants import G0
from claw.env import constants as c


@dataclass(frozen=True)
class AtmState:
    T: float  # 온도 [K]
    P: float  # 압력 [Pa]
    rho: float  # 밀도 [kg/m3]
    a: float  # 음속 [m/s]


# 대류권계면(11,000 m)의 온도·압력 — 성층권 층의 경계값으로 모듈 로드 시 1회 계산
_T11 = c.ISA_T0 + c.ISA_LAPSE_RATE * c.ISA_TROPOPAUSE_ALT
_P11 = c.ISA_P0 * (_T11 / c.ISA_T0) ** (-G0 / (c.ISA_LAPSE_RATE * c.ISA_R_AIR))


def isa_atmosphere(h_m: float) -> AtmState:
    """지오퍼텐셜 고도 h_m [m]에서의 ISA 표준대기 상태량 (T, P, rho, a)."""
    if not (c.ISA_MIN_ALT <= h_m <= c.ISA_STRATO1_TOP_ALT):
        raise ValueError(
            f"고도 범위 초과: {h_m} m (허용 {c.ISA_MIN_ALT}~{c.ISA_STRATO1_TOP_ALT} m)"
        )

    if h_m <= c.ISA_TROPOPAUSE_ALT:
        T = c.ISA_T0 + c.ISA_LAPSE_RATE * h_m
        P = c.ISA_P0 * (T / c.ISA_T0) ** (-G0 / (c.ISA_LAPSE_RATE * c.ISA_R_AIR))
    else:
        T = _T11
        P = _P11 * math.exp(-G0 * (h_m - c.ISA_TROPOPAUSE_ALT) / (c.ISA_R_AIR * T))

    rho = P / (c.ISA_R_AIR * T)
    a = math.sqrt(c.ISA_GAMMA_AIR * c.ISA_R_AIR * T)
    return AtmState(T=T, P=P, rho=rho, a=a)
