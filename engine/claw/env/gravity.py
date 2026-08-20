"""중력 모델 — WGS-84 Somigliana 정규중력 + 고도보정 (도메인 문서 01§2.5).

plant(M5)의 6DOF 중력항이 소비. 타원체면 정규중력은 Somigliana 폐형식(적도·극에서
WGS84_GE·WGS84_GP를 정확 재현), 고도보정은 자유대기 2차 근사
(Stevens & Lewis, Aircraft Control and Simulation 관례식).
"""

import math

from claw.env import constants as c


def gravity_wgs84(lat_rad: float, h_m: float = 0.0) -> float:
    """측지위도 lat_rad [rad]·타원체고도 h_m [m]에서의 중력가속도 크기 [m/s2]."""
    sin2 = math.sin(lat_rad) ** 2
    cos2 = math.cos(lat_rad) ** 2
    g_phi = (c.WGS84_A * c.WGS84_GE * cos2 + c.WGS84_B * c.WGS84_GP * sin2) / math.sqrt(
        c.WGS84_A**2 * cos2 + c.WGS84_B**2 * sin2
    )

    h_a = h_m / c.WGS84_A
    correction = (
        1.0
        - 2.0 * (1.0 + c.WGS84_F + c.WGS84_M - 2.0 * c.WGS84_F * sin2) * h_a
        + 3.0 * h_a**2
    )
    return g_phi * correction
