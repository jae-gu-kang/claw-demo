"""M4 env 검증 — ISA 표준대기표 대조 (Phase 1 완료 기준, 모듈 문서 §6).

압력 참조값은 ICAO Doc 7488 / ISO 2533의 **지오퍼텐셜 고도** 행에서 전사.
"""

import math

import pytest

from claw.common.constants import G0
from claw.env import AtmState, isa_atmosphere
from claw.env import constants as c


def test_sea_level():
    atm = isa_atmosphere(0.0)
    assert isinstance(atm, AtmState)
    assert atm.T == pytest.approx(c.ISA_T0, abs=1e-12)
    assert atm.P == pytest.approx(c.ISA_P0, abs=1e-9)
    assert atm.rho == pytest.approx(c.ISA_RHO0, rel=1e-5)
    assert atm.a == pytest.approx(340.294, rel=1e-5)


@pytest.mark.parametrize(
    "h, T_ref, P_ref",
    [
        (1000.0, 281.65, 89874.6),
        (5000.0, 255.65, 54019.9),
        (11000.0, 216.65, 22632.1),
        (15000.0, 216.65, 12044.6),
        (20000.0, 216.65, 5474.9),
    ],
)
def test_standard_table(h, T_ref, P_ref):
    atm = isa_atmosphere(h)
    assert atm.T == pytest.approx(T_ref, abs=1e-9)
    assert atm.P == pytest.approx(P_ref, rel=5e-4)
    assert atm.rho == pytest.approx(atm.P / (c.ISA_R_AIR * atm.T), rel=1e-12)


def test_tropopause_continuity():
    below = isa_atmosphere(c.ISA_TROPOPAUSE_ALT)
    above = isa_atmosphere(c.ISA_TROPOPAUSE_ALT + 1e-6)
    assert above.T == pytest.approx(below.T, rel=1e-9)
    assert above.P == pytest.approx(below.P, rel=1e-9)


@pytest.mark.parametrize("h", [500.0, 3000.0, 8000.0, 13000.0, 18000.0])
def test_hydrostatic_consistency(h):
    """정수역학 dP/dh = -rho*g0 — 지오퍼텐셜 고도 기반 모델의 해석적 성질."""
    delta = 0.5
    dp_dh = (isa_atmosphere(h + delta).P - isa_atmosphere(h - delta).P) / (2 * delta)
    assert dp_dh == pytest.approx(-isa_atmosphere(h).rho * G0, rel=1e-5)


def test_below_sea_level():
    atm = isa_atmosphere(-1000.0)
    assert atm.T == pytest.approx(288.15 + 6.5, abs=1e-9)
    assert atm.P > c.ISA_P0
    assert atm.rho > c.ISA_RHO0


def test_range_bounds():
    isa_atmosphere(c.ISA_MIN_ALT)  # 경계값은 유효
    isa_atmosphere(c.ISA_STRATO1_TOP_ALT)
    with pytest.raises(ValueError):
        isa_atmosphere(c.ISA_MIN_ALT - 0.1)
    with pytest.raises(ValueError):
        isa_atmosphere(c.ISA_STRATO1_TOP_ALT + 0.1)


def test_speed_of_sound_relation():
    atm = isa_atmosphere(7000.0)
    assert atm.a == pytest.approx(
        math.sqrt(c.ISA_GAMMA_AIR * c.ISA_R_AIR * atm.T), rel=1e-12
    )
