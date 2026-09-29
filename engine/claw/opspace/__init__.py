"""공통 운용공간 (05 §11) — 요구 운용영역 → 기본 모델 격자 → 조건 상태.

탭이 격자를 따로 소유하지 않고 여기서 점 집합을 받는다(05 §11.12 「정의는 한 곳」). 이 패키지는 **점을 어디에
둘지와 각 점이 어떤 상태인지**만 정한다 — 트림 풀기는 claw.trim, 성능 판정은 기준(04)이 한다.

- region: 요구 운용영역(기본 범위 + 경계표)과 모델 유효영역 — 둘은 별개 객체다 (05 §11.2)
- states: 조건 상태 8가지와 미수렴 트림의 귀속 (05 §11.3)
- basegrid: 기본 모델 격자 — 공통 마하 좌표 + 행 끝점 (05 §11.11)
"""

from claw.opspace.basegrid import base_grid
from claw.opspace.region import ModelRange, Region, model_range_of, region_of
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
    trim_state,
)

__all__ = [
    "CALC_FAILED", "COMPUTABLE", "CONSTRAINT_HIT", "INFEASIBLE", "MODEL_GAP", "NOT_RUN", "OUT_OF_REGION",
    "STATE_LABEL", "STATE_ORDER", "UNDEFINED",
    "ModelRange", "Region", "base_grid", "model_range_of", "pre_state", "region_of", "trim_state",
]
