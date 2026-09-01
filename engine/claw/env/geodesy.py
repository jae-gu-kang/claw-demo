"""국지 접평면 측지 변환 — NED(원점 기준 m) ↔ 측지좌표(위경도) (01 §2.5, 규약 §1).

`common/frames.py`가 "WGS-84 측지 변환은 env 모듈(M4) 소관"이라고 지정한 그 자리다.
구현식은 `earth.py` 모듈 독스트링이 이미 예고한 두 줄이며, 그 곡률반경 함수를 그대로 쓴다:

    lat = lat0 + n / (M(lat0) + h_ref)
    lon = lon0 + e / ((N(lat0) + h_ref)·cos(lat0))

**수직축은 변환하지 않는다.** 이 리포의 NED D축은 곧 MSL 고도의 부호 반전이라
(h = −pos_n[2], `sim/simulator.py`·`plant/aircraft.py`) 원점과 해면 사이에 오프셋이 없다.
h_ref는 **곡률반경을 평가할 기준 고도일 뿐**이지 수직 원점이 아니다 — 호출자가 활주로
표고 같은 대표값을 준다.

**동역학은 이 모듈을 쓰지 않는다.** 시뮬은 종전대로 평면지구 NED이고, 여기 있는 것은
"그 평면이 지구 어디에 놓였는가"를 적는 등록(registration) 변환이다 — 지형 자산 정합,
배경지도 타일 조회, 좌표 표시가 소비자다.

## 1차 접평면 근사의 오차

곡률반경을 원점에서 한 번만 평가한다(선형화). M(φ)의 위도 변화율은 φ=34.6°에서
약 6.0e4 m/rad이므로, 원점에서 20 km 떨어진 지점(Δφ ≈ 3.1e-3 rad)에서 M이 2.9e-5만큼
상대적으로 달라지고 누적 위치오차는 **약 0.3 m**다. 수치표고모델 5 m 격자의 1/16이므로
반복 ECEF 변환은 이 용도에 과잉이다.

**이 수치가 곧 재검토 조건이다** — 관심구역을 100 km 급으로 넓히면 오차가 제곱으로 커지니
(20 km에서 0.3 m → 100 km에서 약 8 m) 그때는 엄밀 변환으로 올려야 한다.
"""

import math

from claw.env.earth import radius_meridian, radius_prime_vertical

# 원점 위도 한계 — 이보다 극에 가까우면 cos(lat0)가 0에 수렴해 동서 스케일이 발산한다.
# 조용히 거대한 경도를 내놓는 대신 거부한다 (엔벨로프 감시 원칙, 02 §6.1).
_LAT0_MAX_RAD = math.radians(89.0)


def local_scales(lat0_rad: float, h_ref: float = 0.0) -> tuple[float, float]:
    """원점에서의 국지 스케일 (북 [m/rad], 동 [m/rad]).

    북 = M(φ0) + h_ref, 동 = (N(φ0) + h_ref)·cos(φ0).
    둘의 비가 곧 위도에 따른 동서 압축이다 — φ=34.6°에서 동/북 ≈ 0.8269.
    (cos φ = 0.8231과 미세하게 다르다: M(φ) ≠ N(φ)이기 때문이다.)
    """
    if not math.isfinite(lat0_rad):
        raise ValueError(f"원점 위도는 유한값이어야 함: {lat0_rad}")
    if abs(lat0_rad) > _LAT0_MAX_RAD:
        raise ValueError(
            f"원점 위도 |{math.degrees(lat0_rad):.4f}°| > 89° — 국지 접평면 근사가 성립하지 않음"
        )
    if not math.isfinite(h_ref):
        raise ValueError(f"기준 고도는 유한값이어야 함: {h_ref}")
    m_north = radius_meridian(lat0_rad) + h_ref
    m_east = (radius_prime_vertical(lat0_rad) + h_ref) * math.cos(lat0_rad)
    return m_north, m_east


def ned_to_geodetic(
    n: float, e: float, lat0_rad: float, lon0_rad: float, h_ref: float = 0.0
) -> tuple[float, float]:
    """NED 수평 (n, e) [m] → (위도, 경도) [rad]. 수직은 변환하지 않는다 (모듈 독스트링)."""
    m_north, m_east = local_scales(lat0_rad, h_ref)
    return lat0_rad + n / m_north, lon0_rad + e / m_east


def geodetic_to_ned(
    lat_rad: float, lon_rad: float, lat0_rad: float, lon0_rad: float, h_ref: float = 0.0
) -> tuple[float, float]:
    """(위도, 경도) [rad] → NED 수평 (n, e) [m]. `ned_to_geodetic`의 정확한 역함수."""
    m_north, m_east = local_scales(lat0_rad, h_ref)
    return (lat_rad - lat0_rad) * m_north, (lon_rad - lon0_rad) * m_east
