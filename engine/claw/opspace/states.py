"""조건 상태 (05 §11.3) — 조건마다 정확히 하나, 위에서부터 판정한다.

앞의 셋(요구영역 밖 · 요구 미정의 · 모델 부족)은 트림 **전에** 정해지고 그 점은 트림을 돌리지 않는다(`pre_state`).
나머지는 트림 해로 정한다(`trim_state`). 현행 `envelope_ok`(design/points.py)는 계산 실패와 물리적 불가를 한
`False`로 내는데, 여기서는 갈라 낸다 — 계산 실패는 다시 풀 대상이고 물리적 불가는 그 조건의 답이다.
"""

from __future__ import annotations

import math

OUT_OF_REGION = "out_of_region"  # 요구영역 밖 — 판정 대상 아님
UNDEFINED = "undefined"  # 요구 미정의 — 경계표가 덮지 않음
MODEL_GAP = "model_gap"  # 모델 부족 — 요구 안인데 모델 유효영역 밖
CALC_FAILED = "calc_failed"  # 계산 실패 — 어떤 한계에도 붙지 않은 미수렴 (재시도 대상)
CONSTRAINT_HIT = "constraint_hit"  # 제약 도달·미수렴 — 탐색 제약에 붙음, 물리적 불가의 별도 근거 없음
INFEASIBLE = "infeasible"  # 물리적 불가 — 별도 근거가 있는 불가 (사유 전량)
COMPUTABLE = "computable"  # 계산 가능 — 성능 판정 대상
NOT_RUN = "not_run"  # 미계산

STATE_ORDER = (OUT_OF_REGION, UNDEFINED, MODEL_GAP, CALC_FAILED, CONSTRAINT_HIT, INFEASIBLE, COMPUTABLE, NOT_RUN)
STATE_LABEL = {
    OUT_OF_REGION: "요구영역 밖", UNDEFINED: "요구 미정의", MODEL_GAP: "모델 부족", CALC_FAILED: "계산 실패",
    CONSTRAINT_HIT: "제약 도달·미수렴", INFEASIBLE: "물리적 불가", COMPUTABLE: "계산 가능", NOT_RUN: "미계산",
}

_EPS = 1e-9


def pre_state(region, model, mach: float, alt: float, fuel: float) -> str:
    """트림 전 상태 — 요구영역 밖 · 요구 미정의 · 모델 부족, 아니면 미계산(트림 대상)."""
    rs = region.classify(mach, alt, fuel)
    if rs is not None:
        return rs
    if not model.covers(mach, fuel):
        return MODEL_GAP
    return NOT_RUN


def trim_state(tr, built, model, *, vs_cache: dict | None = None) -> tuple:
    """수평비행 트림 해 → (상태, 사유 목록). 사유는 해당되는 것 전부다.

    미수렴의 귀속은 **한계의 종류**로 가른다 (05 §11.3 [기본값]):
    - 조종량(δe·스로틀)의 한계는 작동기·추진의 물리 한계다 — 거기 붙어 잔차가 남으면 물리적 불가.
    - 받음각 탐색 상한은 실속 받음각·모델 유효 상한과 다른 값이라, 붙었다는 것만으로 날 수 없다고 못 한다.
      실속표로 잰 1g 실속 속도 V_S보다 느리다는 별도 근거(또는 1g 도달 불가)가 있을 때만 물리적 불가이고,
      아니면 제약 도달·미수렴이다. 하한에 붙은 미수렴은 양력이 남는 쪽이라 실속 논리를 쓰지 않는다.
    - 어느 한계에도 붙지 않은 미수렴은 계산 실패다.
    수렴했어도 포화·α 여유 미달이면 물리적 불가다(envelope_ok와 같은 판정).
    """
    from claw.trim import saturation_detail

    tb = built.trim_bounds
    sat = [ch for ch, on in saturation_detail(tr, tb["de"]).items() if on]
    if not tr.converged:
        if sat:
            return INFEASIBLE, [*sat, "not_converged"]
        alpha = math.atan2(float(tr.state.vel_b[2]), float(tr.state.vel_b[0]))
        a_lo, a_hi = tb["alpha"]
        if alpha <= a_lo + 1e-6:
            return CONSTRAINT_HIT, ["alpha_search_lower", "not_converged"]
        if alpha >= a_hi - 1e-6:
            return _alpha_upper(tr.case, built, model, {} if vs_cache is None else vs_cache)
        return CALC_FAILED, ["not_converged"]
    why = sat + ([] if tr.flags.get("alpha_margin_ok") else ["alpha_margin"])
    if why:
        return INFEASIBLE, why
    return COMPUTABLE, []


def _alpha_upper(case, built, model, cache: dict) -> tuple:
    from claw.analysis.envelope import stall_mach_lo

    base = ["alpha_search_bound", "not_converged"]
    stall = built.stall_table()
    mach_hi = float(model.mach[1]) if model.mach is not None else float(stall.axes[0][-1])
    # V_S를 잴 근거가 없는 자리 — 스캔 상한이 실속표 축 시작보다 낮거나, 조건이 스캔 상한 위(모델 밖에서 손으로 더한
    # 케이스)면 스캔이 그 마하를 보지 않는다. 판단을 짓지 않고 근거 없음으로 둔다(1g 도달 불가로 둔갑하지 않게)
    if mach_hi <= float(stall.axes[0][0]) or case.mach > mach_hi + _EPS:
        return CONSTRAINT_HIT, [*base, "stall_basis_missing"]
    key = (float(case.alt), float(case.fuel), mach_hi)  # mach_hi가 결과를 바꾸므로 키에 든다
    if key not in cache:
        try:
            cache[key] = stall_mach_lo(built.aircraft(), stall, case.alt, case.fuel, mach_hi=mach_hi, mach_margin=1.0)
        except (ValueError, ArithmeticError):
            # 실속 경계 계산이 수치적으로 실패 — 트림 해는 이미 있다. 배치 전체를 잃지 않고 판단 미완료로 남긴다
            cache[key] = (None, "error")
    vs, src = cache[key]
    if src == "error":
        return CONSTRAINT_HIT, [*base, "stall_basis_error"]
    if src == "n_reach":
        return INFEASIBLE, [*base, "1g_unreachable"]
    if src == "stall":  # V_S 확정 — 실속표 축 밖(더 느린 쪽)이라도 V_S보다 느리면 불가다
        if case.mach < vs - _EPS:
            return INFEASIBLE, [*base, "below_V_S"]
        return CONSTRAINT_HIT, [*base, "above_V_S"]
    # "db": V_S가 실속표 축 아래라는 것만 안다 — 축 안의 마하는 V_S보다 빠르고, 축 밖은 근거가 없다
    if case.mach < float(stall.axes[0][0]) - _EPS:
        return CONSTRAINT_HIT, [*base, "stall_basis_missing"]
    return CONSTRAINT_HIT, [*base, "above_V_S"]
