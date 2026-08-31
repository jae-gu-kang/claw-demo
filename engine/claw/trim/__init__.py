"""M9 trim — 구속조건 트림(scipy SLSQP) + 수치섭동 선형화 (도메인 문서 §4).

구현됨: trim_level(수평정상비행) / trim_ground(지상 정지 평형) / trim(조건 분기) /
trim_batch(인접 시드·연속성 판정) / linearize(수치섭동 중앙차분) / split_axes(종·횡축 분리).
후속: 정상선회·상승 트림 [확정 추후].
"""

from claw.trim.linearize import (
    LAT_INPUTS,
    LAT_STATES,
    LON_INPUTS,
    LON_STATES,
    U_NAMES,
    linearize,
    split_axes,
)
from claw.trim.trim import saturation_detail, trim, trim_batch, trim_ground, trim_level

__all__ = [
    "trim",
    "trim_level",
    "trim_ground",
    "trim_batch",
    "saturation_detail",
    "linearize",
    "split_axes",
    "U_NAMES",
    "LON_STATES",
    "LON_INPUTS",
    "LAT_STATES",
    "LAT_INPUTS",
]
