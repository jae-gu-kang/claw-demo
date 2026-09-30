"""M9 trim — 구속조건 트림(scipy SLSQP) + 수치섭동 선형화 (도메인 문서 §4).

구현됨: trim_level(수평정상비행) / trim_ground(지상 정지 평형) / trim(조건 분기) /
trim_batch(인접 시드·연속성 판정·트림 저장소 재사용·계산 실패 재시도) / solve_level·assemble_level(풀이·조립 분리) / linearize(수치섭동 중앙차분) / split_axes(종·횡축 분리).
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
from claw.trim.store import TrimRecord, TrimStore, TrimStoreScope
from claw.trim.trim import (
    DEFAULT_RETRY,
    RETRY_RESULTS,
    RetryPolicy,
    alpha_bound,
    assemble_level,
    interior_failure,
    physical_limits,
    retry_level,
    retry_result,
    retry_seeds,
    saturation_detail,
    solve_level,
    trim,
    trim_batch,
    trim_ground,
    trim_level,
)

__all__ = [
    "trim",
    "trim_level",
    "solve_level",
    "assemble_level",
    "TrimRecord",
    "TrimStore",
    "TrimStoreScope",
    "trim_ground",
    "trim_batch",
    "RetryPolicy",
    "DEFAULT_RETRY",
    "retry_level",
    "retry_seeds",
    "physical_limits",
    "alpha_bound",
    "interior_failure",
    "retry_result",
    "RETRY_RESULTS",
    "saturation_detail",
    "linearize",
    "split_axes",
    "U_NAMES",
    "LON_STATES",
    "LON_INPUTS",
    "LAT_STATES",
    "LAT_INPUTS",
]
