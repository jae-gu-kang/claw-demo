"""M16 design — 자동 설계 루프 (트림 격자 자동화 → 게인 자동 튜닝 → 스케줄 적합 → 마진 검증 → 이터레이션).

`pipeline/`(반자동 진단·스윕 보조)과 층이 다르다 — 여기는 산출물(트림 격자·게인
테이블·마진 판정)을 **생성**하는 설계 루프다. 단일 정본 상태는 "역할(role) 있는
운영점 집합"(points.PointSet)이며, 그 위에서 COARSE → REFINE → TUNE → FIT →
VERIFY → CLASSIFY 스테이지가 순환한다 (orchestrator).

역할 서열: validation < breakpoint < anchor. 승격은 단방향 래칫 — 같은 점이
아래로 내려가지 않아 이터레이션 종료가 보장된다 (points.PointSet.promote).
"""

from claw.design.classify import VERDICTS, classify_failures, classify_margin_deficit
from claw.design.criteria import MarginCriteria
from claw.design.linmodels import LinearModelSet, model_distance
from claw.design.points import (
    ROLE_ANCHOR,
    ROLE_BREAKPOINT,
    ROLE_VALIDATION,
    OperatingPoint,
    PointSet,
    case_name,
)
from claw.design.fit import (
    fit_gain_surface,
    fit_slot,
    fit_slots,
    resample_to_table,
    select_axes,
)
from claw.design.grid import coarse_grid
from claw.design.orchestrator import AutoDesignConfig, DesignSession
from claw.design.refine import refine_trim_points
from claw.design.tune import TuneTargets, tune_point, tune_points
from claw.design.schedmap import (
    midpoint_validation_points,
    scheduled_gains,
    scheduled_margin_map,
    scheduled_margin_point,
)

__all__ = [
    "ROLE_ANCHOR",
    "ROLE_BREAKPOINT",
    "ROLE_VALIDATION",
    "OperatingPoint",
    "PointSet",
    "case_name",
    "LinearModelSet",
    "model_distance",
    "MarginCriteria",
    "scheduled_gains",
    "scheduled_margin_point",
    "scheduled_margin_map",
    "midpoint_validation_points",
    "coarse_grid",
    "refine_trim_points",
    "TuneTargets",
    "tune_point",
    "tune_points",
    "fit_gain_surface",
    "fit_slot",
    "fit_slots",
    "select_axes",
    "resample_to_table",
    "VERDICTS",
    "classify_margin_deficit",
    "classify_failures",
    "AutoDesignConfig",
    "DesignSession",
]
