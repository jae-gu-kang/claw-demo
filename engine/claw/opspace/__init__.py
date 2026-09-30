"""공통 운용공간 (05 §11) — 요구 운용영역 → 기본 모델 격자 → 조건 상태.

탭이 격자를 따로 소유하지 않고 여기서 점 집합을 받는다(05 §11.12 「정의는 한 곳」). 이 패키지는 **점을 어디에
둘지와 각 점이 어떤 상태인지**만 정한다 — 트림 풀기는 claw.trim, 성능 판정은 기준(04)이 한다.

- region: 요구 운용영역(기본 범위 + 경계표)과 모델 유효영역 — 둘은 별개 객체다 (05 §11.2)
- states: 조건 상태 8가지, 미수렴 트림의 귀속과 그 근거, 상태와 따로 가는 여유 판정 (05 §11.3)
- basegrid: 기본 모델 격자 — 공통 마하 좌표 + 행 끝점 (05 §11.11)
- verdict: 조건 판정 — 트림·모델·제한·여유 항목과 자동 설계 채택(트림 탭과 자동 설계가 같이 쓴다)
"""

from claw.opspace.basegrid import base_grid
from claw.opspace.region import (
    ModelRange,
    Region,
    grid_diff,
    model_range_of,
    region_echo,
    region_from_section,
    region_key,
    region_of,
    region_outline,
)
from claw.opspace.states import (
    CALC_FAILED,
    COMPUTABLE,
    CONSTRAINT_HIT,
    INFEASIBLE,
    MODEL_GAP,
    NOT_RUN,
    OUT_OF_REGION,
    STATE_LABEL,
    STATE_ORDER,
    UNDEFINED,
    pre_state,
    trim_assessment,
    trim_state,
)
from claw.opspace.verdict import PRE_TRIM_CATEGORY, VerdictContext, condition_verdict, margin_of, pre_trim_verdict

__all__ = [
    "CALC_FAILED", "COMPUTABLE", "CONSTRAINT_HIT", "INFEASIBLE", "MODEL_GAP", "NOT_RUN", "OUT_OF_REGION",
    "STATE_LABEL", "STATE_ORDER", "UNDEFINED",
    "ModelRange", "Region", "base_grid", "grid_diff", "model_range_of", "pre_state", "region_echo",
    "region_from_section", "region_key", "region_of", "region_outline", "trim_assessment", "trim_state",
    "PRE_TRIM_CATEGORY", "VerdictContext", "condition_verdict", "margin_of", "pre_trim_verdict",
]
