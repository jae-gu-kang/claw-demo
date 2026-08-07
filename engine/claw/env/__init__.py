"""M4 env — ISA 대기, 중력, WGS-84 지구모델, 바람/난류(확장) (도메인 문서 §2.5).

구현됨: ISA 표준대기 2층 모델(atmosphere), 표준중력 G0 재수출.
후속 증분: WGS-84 지구모델·Somigliana 중력(plant 착수 시), 바람/Dryden(확장 항목).
"""

from claw.common.constants import G0
from claw.env.atmosphere import AtmState, isa_atmosphere

__all__ = ["G0", "AtmState", "isa_atmosphere"]
