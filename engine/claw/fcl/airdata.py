"""NavOutput → 동체 속도·바람각 추정 — 법칙 측 공용 유틸.

법칙(M7·M8)은 plant 참값을 보지 않고 NavOutput만 소비한다 (03 §4 핵심 계약).
α·β·V도 항법 출력(관성속도+자세)에서 추정하며, 바람 0 가정에서 공기속도와
일치한다 (바람/난류는 확장 항목, 01 §2.5 — 도입 시 이 추정의 오차가 곧
법칙이 감내해야 할 실환경 불확실성이 된다).
"""

from claw.common.frames import ned_to_body, wind_angles


def vel_b_from_nav(nav):
    """항법 관성속도(NED)를 항법 자세로 동체축 투영."""
    return ned_to_body(nav.q_nb, nav.vel_n)


def airdata_from_nav(nav):
    """NavOutput → (V, α, β). α = atan2(w,u), β = asin(v/V) (conventions.md §4)."""
    return wind_angles(vel_b_from_nav(nav))
