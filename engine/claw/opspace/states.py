"""조건 상태 (05 §11.3) — 조건마다 정확히 하나, 위에서부터 판정한다.

앞의 셋(요구영역 밖 · 요구 미정의 · 모델 부족)은 트림 **전에** 정해지고 그 점은 트림을 돌리지 않는다(`pre_state`).
나머지는 트림 해로 정한다(`trim_state`). 종전 `envelope_ok`는 계산 실패와 물리적 불가를 한 `False`로 냈는데, 여기서는
갈라 낸다 — 계산 실패는 다시 풀 대상이고 물리적 불가는 그 조건의 답이다. 자동 설계 채택도 이 상태를 쓴다(opspace/verdict.py).
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
    """수평비행 트림 해 → (상태, 사유 목록). `trim_assessment`의 상태·사유만 — 여유 판정·근거는 거기 있다."""
    a = trim_assessment(tr, built, model, cache=vs_cache)
    return a["state"], a["reasons"]


def trim_assessment(tr, built, model, *, cache: dict | None = None) -> dict:
    """수평비행 트림 해 → {"state", "reasons", "margin", "evidence"} (05 §11.3).

    **상태와 여유 판정은 따로다.** 상태는 그 조건에서 트림이 성립하는지, margin은 성립한 트림이 판정선(스로틀·
    엘레본 포화 SAT_FRAC, 트림 α 여유)을 넘는지다. 수렴한 해는 판정선을 넘어도 계산 가능이다 — 날 수 있는 평형이고
    선형화 자료로 남는다. 여유 미달은 margin이 말한다: {"status": "met"|"short"|"unevaluated", "reasons": [...]}.
    판정선을 바꾸면 트림을 다시 풀지 않고 margin만 다시 정하면 된다. 계산 가능은 합격이나 자동 설계 채택을 뜻하지
    않는다 — 채택은 조건 판정(opspace/verdict.py — 트림·모델·제한 항목)의 채택 정책이 정한다.

    미수렴의 귀속은 **한계의 종류와 별도 근거**로 가른다 (05 §11.3 [기본값]):
    - 조종량의 물리 한계(스로틀 0·1, 엘레본 끝)에 붙은 미수렴은 그것만으로 불가가 아니다 — 풀이기가 거기서 멈췄을
      뿐일 수 있다. 그 채널을 한계에 고정하고 나머지 평형을 모델 유효범위 안에서 다시 풀어(`_limit_evidence`), 찾은
      평형 해 **전부**에서 그 채널의 식이 허용치를 넘게 남을 때만 물리적 불가다(사유와 근거 수치를 싣는다). 평형을
      못 찾으면 제약 도달·미수렴(원인 미확인), 남지 않는 해가 있으면 트림이 있는데 못 푼 것이라 계산 실패다.
    - 받음각 탐색 상한은 실속 받음각·모델 유효 상한과 다른 값이라, 붙었다는 것만으로 날 수 없다고 못 한다.
      실속표로 잰 1g 실속 속도 V_S보다 느리다는 별도 근거(또는 1g 도달 불가)가 있을 때만 물리적 불가이고,
      아니면 제약 도달·미수렴이다. 하한에 붙은 미수렴은 양력이 남는 쪽이라 실속 논리를 쓰지 않는다.
    - 어느 한계에도 붙지 않은 미수렴은 계산 실패다.
    """
    cache = {} if cache is None else cache
    tb = built.trim_bounds
    unevaluated = {"status": "unevaluated", "reasons": []}
    if not tr.converged:
        limits = _at_physical_limits(tr, tb)
        if len(limits) == 1:
            state, reasons, evidence = _limit_evidence(tr, built, limits[0], cache)
            return {"state": state, "reasons": reasons, "margin": unevaluated, "evidence": evidence}
        if limits:  # 둘 이상이 한계 — 한 채널을 고정해 나머지를 푸는 근거가 서지 않는다
            return {"state": CONSTRAINT_HIT, "reasons": [*limits, "not_converged", "balance_not_found"],
                    "margin": unevaluated, "evidence": None}
        alpha = math.atan2(float(tr.state.vel_b[2]), float(tr.state.vel_b[0]))
        a_lo, a_hi = tb["alpha"]
        if alpha <= a_lo + 1e-6:
            state, reasons = CONSTRAINT_HIT, ["alpha_search_lower", "not_converged"]
        elif alpha >= a_hi - 1e-6:
            state, reasons = _alpha_upper(tr.case, built, model, cache)
        else:
            state, reasons = CALC_FAILED, ["not_converged"]
        return {"state": state, "reasons": reasons, "margin": unevaluated, "evidence": None}
    # 수렴한 해는 계산 가능이다 — 실속 경계·리미터·동압 같은 운용 제한 위반은 수치 평형의 존재와 따로 조건 판정
    # (opspace/verdict.py)의 제한 항목이 말한다. 여유 판정은 자동 설계와 같은 한 규칙(margin_of)이다
    from claw.opspace.verdict import margin_of

    return {"state": COMPUTABLE, "reasons": [], "margin": margin_of(tr, tb), "evidence": None}


# 한계에 「붙었다」의 판정 폭 — 풀이기(SLSQP)의 경계 해는 경계값 그대로 나온다
_LIMIT_TOL = 1e-6
_UNKNOWNS = ("alpha", "de", "throttle")
# 한계 채널 → (고정할 미지수 번호, 그 채널이 맡은 평형식, 한계 너머의 방향, 불가 사유). 평형식은 경로축 — 비행경로
# 가속도 V̇ · 경로 수직 가속도 · q̇. 스로틀은 V̇를, 엘레본은 q̇를 맡는다. 방향 +1은 상한(더 올려야 하면 불가), −1은 하한
_LIMIT_CHANNEL = {
    "throttle_high": (2, "vdot", +1, "thrust_deficit"),  # 최대 추력에서도 감속
    "throttle_low": (2, "vdot", -1, "idle_thrust_excess"),  # 아이들에서도 가속 — 수평으로는 그 속도를 못 지킨다
    "de_high": (1, "qdot", +1, "pitch_moment_short"),  # 엘레본 끝에서도 피치 모멘트가 남는다
    "de_low": (1, "qdot", -1, "pitch_moment_short"),
}
_FD_STEP = 1e-4  # 고정 채널의 편미분 유한차분 폭 [rad · 스로틀 비]


def _at_physical_limits(tr, tb) -> list:
    """미수렴 해가 붙은 **물리** 한계 채널 — 스로틀 0·1, 엘레본 한계(판정선 SAT_FRAC이 아니다)."""
    from claw.trim.trim import THR_BOUNDS

    thr = float(tr.control.throttle[0])
    de = float(tr.control.elevon[0])
    de_lo, de_hi = tb["de"]
    out = []
    if thr >= THR_BOUNDS[1] - _LIMIT_TOL:
        out.append("throttle_high")
    if thr <= THR_BOUNDS[0] + _LIMIT_TOL:
        out.append("throttle_low")
    if de >= de_hi - _LIMIT_TOL:
        out.append("de_high")
    if de <= de_lo + _LIMIT_TOL:
        out.append("de_low")
    return out


def _limit_evidence(tr, built, channel: str, cache: dict) -> tuple:
    """한계 채널을 고정하고 나머지 평형을 다시 풀어 불가 근거를 잰다 → (상태, 사유, 근거).

    수평비행(γ = 0, θ = α)을 지키고 트림과 같은 운동방정식(추력 성분 포함)을 쓰되, 식은 **경로축**으로 본다 — 비행경로
    가속도 V̇, 경로 수직 가속도, q̇. 기체축 ẇ = 0으로 풀면 V̇ ≠ 0인 해(바로 추력 부족인 해)에서 경로 수직 가속도가
    −tanα·V̇로 남아 받음각이 어긋난다. 고정한 채널이 맡은 식은 빼고 나머지 두 식을 나머지 두 미지수로 푼다 — 받음각은
    **모델 유효범위**(DB 받음각 범위, 없으면 트림 탐색 범위)에서, 조종량은 물리 한계 안에서. 초기값 여러 개에서 찾은
    서로 다른 평형 해를 모두 싣는다.

    남은 식을 없애는 데 필요한 고정 채널의 변화 −r/(∂r/∂채널)을 해마다 유한차분으로 잰다 — 그 변화가 **한계 너머**를
    가리켜야 부족이다(엘레본은 양 끝 어느 쪽에서도 q̇가 남으므로 크기만 보면 풀이기가 끝에서 멈춘 해도 불가가 된다). 판정:
    - 평형 해가 없다 → 제약 도달·미수렴(원인 미확인). 풀이 자체가 수치 오류면 그 사유(balance_error)
    - 해 가운데 한계 안쪽으로 식을 없앨 수 있는 것이 있다 → 한계 안쪽에 트림이 있다 → 계산 실패(다시 풀 대상)
    - 그 채널이 식을 움직이지 못한다(기울기 0) → 제약 도달·미수렴(limit_sensitivity_zero)
    - 실속표 축 밖의 마하 → 해가 실속 아래인지 근거가 없다 → 제약 도달·미수렴(stall_basis_missing)
    - 실속각 아래 해 전부가 한계 너머를 가리킨다 → 물리적 불가(사유 + 근거). 실속 아래 해가 없으면 제약 도달·미수렴
    """
    import numpy as np
    import scipy.optimize

    from claw.env import isa_atmosphere
    from claw.trim.trim import RESID_TOL, THR_BOUNDS, XE_Q, XE_U, XE_W, _xe

    fixed_i, eq, beyond, reason = _LIMIT_CHANNEL[channel]
    tb = built.trim_bounds
    case = tr.case
    pinned = (math.atan2(float(tr.state.vel_b[2]), float(tr.state.vel_b[0])),
              float(tr.control.elevon[0]), float(tr.control.throttle[0]))[fixed_i]
    if "aircraft" not in cache:
        cache["aircraft"] = built.aircraft()
    ac = cache["aircraft"]
    v = case.mach * isa_atmosphere(case.alt).a
    a_rng = tuple(built.db_ranges().get("alpha") or tb["alpha"])
    bounds = {0: a_rng, 1: tuple(tb["de"]), 2: THR_BOUNDS}
    free = [i for i in (0, 1, 2) if i != fixed_i]

    def eqs(z):
        xd = ac.deriv_euler(_xe(np.array(z), v, case.alt),
                            {"de": z[1], "da": 0.0, "dr": 0.0, "throttle": (z[2], z[2])}, case.fuel)
        c, s_ = math.cos(z[0]), math.sin(z[0])
        return {"vdot": float(c * xd[XE_U] + s_ * xd[XE_W]), "ndot": float(-s_ * xd[XE_U] + c * xd[XE_W]),
                "qdot": float(xd[XE_Q])}

    def full(zf):
        z = [0.0, 0.0, 0.0]
        z[fixed_i] = pinned
        z[free[0]], z[free[1]] = float(zf[0]), float(zf[1])
        return z

    solve_for = [k for k in ("vdot", "ndot", "qdot") if k != eq]
    lo = [bounds[i][0] for i in free]
    hi = [bounds[i][1] for i in free]
    evidence = {"channel": channel, "fixed": {_UNKNOWNS[fixed_i]: pinned}, "equation": eq, "tol": RESID_TOL,
                "alpha_range": list(a_rng), "solutions": []}
    found, errors = {}, 0
    if all(lo_i < hi_i for lo_i, hi_i in zip(lo, hi)):
        for s0 in np.linspace(0.05, 0.95, 5):
            for s1 in (0.2, 0.5, 0.8):
                x0 = [lo[0] + s0 * (hi[0] - lo[0]), lo[1] + s1 * (hi[1] - lo[1])]
                try:
                    r = scipy.optimize.least_squares(lambda zf: [eqs(full(zf))[k] for k in solve_for], x0,
                                                     bounds=(lo, hi), xtol=1e-12, ftol=1e-12, gtol=1e-12)
                except (ValueError, ArithmeticError, FloatingPointError):
                    errors += 1  # 이 초기값만 버린다 — 다른 초기값의 해까지 잃지 않게
                    continue
                z = full(r.x)
                d = eqs(z)
                if max(abs(d[k]) for k in solve_for) < RESID_TOL:
                    found.setdefault(tuple(round(x, 4) for x in z), (z, d))
    else:
        errors += 1  # 풀 범위가 비었다(퇴화한 DB 받음각 범위 등)
    if not found:
        why = "balance_error" if errors else "balance_not_found"
        return CONSTRAINT_HIT, [channel, "not_converged", why], evidence

    stall = built.stall_table()
    axis = stall.axes[0]
    in_axis = float(axis[0]) - _EPS <= case.mach <= float(axis[-1]) + _EPS
    a_stall = float(stall.interp(mach=case.mach)) if in_axis else None
    sols = []
    for z, d in found.values():
        # 남은 식을 없애려면 고정 채널을 얼마나 움직여야 하나 — 한계 너머(beyond 방향)를 가리키면 부족이다. 차분은 한계
        # **안쪽**으로 잰다: 스로틀은 1을 넘으면 잘려(0~1 클립) 바깥 차분의 기울기가 0이 된다
        zp = list(z)
        zp[fixed_i] -= beyond * _FD_STEP
        slope = (eqs(zp)[eq] - d[eq]) / (-beyond * _FD_STEP)
        need = -d[eq] / slope if slope != 0.0 else None
        # 기울기 0 — 그 채널이 식을 움직이지 못한다: 어느 쪽인지 판단하지 않는다(None)
        short = None if need is None else bool(abs(d[eq]) > RESID_TOL and beyond * need > 0.0)
        sols.append({**dict(zip(_UNKNOWNS, z)), **d, "slope": slope, "need": need, "short": short,
                     "alpha_stall": a_stall, "below_stall": None if a_stall is None else bool(z[0] < a_stall)})
    evidence["solutions"] = sols
    if any(s["short"] is False for s in sols):
        return CALC_FAILED, [channel, "not_converged", "trim_inside_limit"], evidence
    if any(s["short"] is None for s in sols):
        return CONSTRAINT_HIT, [channel, "not_converged", "limit_sensitivity_zero"], evidence
    if a_stall is None:
        return CONSTRAINT_HIT, [channel, "not_converged", "stall_basis_missing"], evidence
    if not any(s["below_stall"] for s in sols):
        return CONSTRAINT_HIT, [channel, "not_converged", "balance_not_found"], evidence
    return INFEASIBLE, [reason, channel], evidence


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
