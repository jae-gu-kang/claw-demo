import math

import pytest

from claw.common import units


def test_deg_rad():
    assert units.deg2rad(180.0) == pytest.approx(math.pi)
    assert units.rad2deg(math.pi / 2) == pytest.approx(90.0)
    assert units.rad2deg(units.deg2rad(37.5)) == pytest.approx(37.5)


def test_length():
    assert units.ft2m(1.0) == pytest.approx(0.3048)
    assert units.m2ft(units.ft2m(12345.0)) == pytest.approx(12345.0)
    assert units.NM2M == pytest.approx(1852.0)


def test_speed():
    assert units.kt2mps(1.0) == pytest.approx(0.5144444444, rel=1e-9)
    assert units.mps2kt(units.kt2mps(250.0)) == pytest.approx(250.0)


def test_mass():
    assert units.lb2kg(1.0) == pytest.approx(0.45359237)
    assert units.kg2lb(units.lb2kg(77.7)) == pytest.approx(77.7)


def test_hz2dt():
    assert units.hz2dt(100.0) == pytest.approx(0.01)
    assert units.hz2dt(50.0) == pytest.approx(0.02)
    with pytest.raises(ValueError):
        units.hz2dt(0.0)
