"""M4 env 검증 — WGS-84 중력·곡률반경·지오퍼텐셜 변환 (Phase 1 백로그 소진)."""

import math

import pytest

from claw.env import (
    G0,
    geometric_altitude,
    geopotential_altitude,
    gravity_wgs84,
    radius_meridian,
    radius_prime_vertical,
)
from claw.env import constants as c


# ---- Somigliana 중력 ----


def test_gravity_equator_pole_exact():
    """Somigliana 폐형식은 적도·극에서 WGS-84 정의 상수를 정확 재현해야 한다."""
    assert gravity_wgs84(0.0, 0.0) == pytest.approx(c.WGS84_GE, abs=1e-9)
    assert gravity_wgs84(math.pi / 2, 0.0) == pytest.approx(c.WGS84_GP, abs=1e-9)


def test_gravity_standard_latitude_matches_g0():
    # 위도 45.5425°는 정규중력이 표준중력상수 G0를 재현하는 기준위도
    assert gravity_wgs84(math.radians(45.5425), 0.0) == pytest.approx(G0, abs=1e-4)


def test_gravity_monotone_with_latitude():
    lats = [math.radians(d) for d in (0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0)]
    gs = [gravity_wgs84(lat) for lat in lats]
    assert all(gs[i] < gs[i + 1] for i in range(len(gs) - 1))  # 적도→극 단조 증가


def test_gravity_free_air_altitude_correction():
    lat = math.radians(37.5)
    g0 = gravity_wgs84(lat, 0.0)
    g10k = gravity_wgs84(lat, 10000.0)
    assert g10k < g0
    # 자유대기 감률 ≈ 3.086e-6 m/s² per m (10 km에서 ~0.031 m/s²)
    assert (g0 - g10k) == pytest.approx(0.0309, abs=0.002)


# ---- 곡률반경 ----


def test_radius_prime_vertical_at_equator_is_semimajor():
    assert radius_prime_vertical(0.0) == pytest.approx(c.WGS84_A, rel=1e-12)


def test_radius_meridian_at_equator_reference():
    # M(0) = a(1-e²) — 참조값 약 6,335,439 m
    assert radius_meridian(0.0) == pytest.approx(c.WGS84_A * (1.0 - c.WGS84_E2), rel=1e-12)
    assert radius_meridian(0.0) == pytest.approx(6335439.0, abs=1.0)


def test_radii_converge_at_pole():
    lat = math.pi / 2
    assert radius_meridian(lat) == pytest.approx(radius_prime_vertical(lat), rel=1e-9)
    assert radius_prime_vertical(lat) == pytest.approx(6399593.6, abs=1.0)  # a/√(1-e²)


def test_meridian_below_prime_vertical_at_midlatitude():
    lat = math.radians(45.0)
    assert radius_meridian(lat) < radius_prime_vertical(lat)


# ---- 지오퍼텐셜 변환 ----


def test_geopotential_below_geometric():
    assert geopotential_altitude(20000.0) == pytest.approx(19937.3, abs=0.5)  # US Std Atm 참조
    assert geopotential_altitude(0.0) == 0.0


def test_geopotential_round_trip():
    for h in (0.0, 1000.0, 11000.0, 20000.0):
        assert geometric_altitude(geopotential_altitude(h)) == pytest.approx(h, abs=1e-9)
