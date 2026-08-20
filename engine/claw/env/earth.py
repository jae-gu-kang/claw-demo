"""WGS-84 지구모델 — 곡률반경, 지오퍼텐셜↔기하고도 변환 (도메인 문서 01§2.5).

곡률반경은 plant(M5) 위치 운동방정식의 위도/경도 변화율 스케일 인자:
lat_dot = v_N / (M + h), lon_dot = v_E / ((N + h)·cos(lat)).
지오퍼텐셜 변환은 6DOF 기하고도를 ISA 대기 입력(지오퍼텐셜)으로 잇는 다리
(atmosphere 모듈 규약 참조).
"""

import math

from claw.env import constants as c


def radius_prime_vertical(lat_rad: float) -> float:
    """묘유선 곡률반경 N(φ) [m] — 경도(동/서) 방향 스케일. 적도에서 WGS84_A와 일치."""
    sin2 = math.sin(lat_rad) ** 2
    return c.WGS84_A / math.sqrt(1.0 - c.WGS84_E2 * sin2)


def radius_meridian(lat_rad: float) -> float:
    """자오선 곡률반경 M(φ) [m] — 위도(남/북) 방향 스케일. 극에서 N(φ)와 일치."""
    sin2 = math.sin(lat_rad) ** 2
    return c.WGS84_A * (1.0 - c.WGS84_E2) / (1.0 - c.WGS84_E2 * sin2) ** 1.5


def geopotential_altitude(h_geometric_m: float) -> float:
    """기하고도 → 지오퍼텐셜 고도 [m]: h_gp = r0·h / (r0 + h)."""
    return c.EARTH_R0 * h_geometric_m / (c.EARTH_R0 + h_geometric_m)


def geometric_altitude(h_geopotential_m: float) -> float:
    """지오퍼텐셜 고도 → 기하고도 [m] (역변환): h = r0·h_gp / (r0 − h_gp)."""
    return c.EARTH_R0 * h_geopotential_m / (c.EARTH_R0 - h_geopotential_m)
