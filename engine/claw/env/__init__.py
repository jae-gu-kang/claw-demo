"""M4 env — ISA 대기, 중력, WGS-84 지구모델, 바람/난류(확장) (도메인 문서 §2.5).

구현됨: ISA 표준대기 2층 모델(atmosphere), WGS-84 Somigliana 중력+고도보정(gravity),
곡률반경·지오퍼텐셜↔기하고도 변환(earth), 표준중력 G0 재수출.
후속 증분: 바람/Dryden 난류(확장 항목).
"""

from claw.common.constants import G0
from claw.env.atmosphere import AtmState, isa_atmosphere
from claw.env.earth import (
    geometric_altitude,
    geopotential_altitude,
    radius_meridian,
    radius_prime_vertical,
)
from claw.env.gravity import gravity_wgs84

__all__ = [
    "G0",
    "AtmState",
    "isa_atmosphere",
    "gravity_wgs84",
    "radius_meridian",
    "radius_prime_vertical",
    "geopotential_altitude",
    "geometric_altitude",
]
