"""조건 판정 (05 §11.3 · 이관 8단계) — 한 조건의 트림 해를 **항목별로** 판정하고, 자동 설계 채택은 그 결과로 정한다.

종전에는 `design/points.py envelope_ok` 한 비트(수렴 + 포화 여유 + α 여유)가 트림 성립·제한 준수·여유 충족을 한꺼번에
대신했고, 트림 탭은 따로 조건 상태를 냈다 — 같은 조건에 두 판정이 섰다. 여기서는 항목을 나눈다:

- trim    트림이 성립하는가 — 조건 상태(opspace/states.py). 근거까지 잰 상태를 받으면 그대로 싣는다
- model   계산·판정에 필요한 데이터 범위 안인가 — DB 마하·받음각, 연료 0~만재
- limits  적용 제한을 지키는가 — 실속 경계, α 리미터가 트림을 유지하지 못하게 하는지, 최대 동압, M_NO
- margin  판정선 여유가 설계 기준을 채우는가 — 스로틀·엘레본 포화 등고선, 트림 α 여유
- adopted 위 결과와 공통 정책으로 정한 자동 설계 채택 여부, exclusion은 빠진 첫 항목과 그 사유

**채택 정책**(v1.65, 사용자 결정): 트림 계산 가능 ∧ 모델 유효 ∧ 제한 충족. **여유 미달은 채택을 막지 않는다** — 스로틀
95~99 %에서 수렴한 해는 날 수 있는 평형이라 설계에 쓰고, 여유 미달 표시(margin)는 그대로 남긴다.

**α 리미터**: 리미터는 피치 명령을 θ_cmd ≤ θ + (α_max − α)로 자른다(fcl/limiter.py, α_max = α_stall − 리미터 여유). 수평
정상비행(θ = α)에서 이 식은 θ_cmd ≤ α_max — 정상상태 받음각이 α_max에 묶인다. 그래서 α_trim > α_max인 수평 트림은 그
리미터를 켠 법칙의 폐루프가 **유지할 수 없다**(받음각이 묶인 채 하강한다) — 문턱을 넘었다는 사실만이 아니라 이 작동식이
근거다. 리미터를 끈 분석(limiter_margin None)에는 적용하지 않는다. 근거 수치는 limits.detail에 싣는다.

**잴 근거가 없는 항목은 미평가이고 통과가 아니다** — 실속표가 없는 기체처럼 근거가 없으면 채택하지 않는다. 실속표 축
밖의 마하는 근거 없음이 아니다: 실속표의 외삽(clip)은 데이터가 **선언한 정책**이라(analysis/envelope.py `pitch_limit_table`
· 이착륙 속도대가 그 자리다) 그 값으로 판정한다. 채택하지 않은 점도 결과 목록에는 남는다(호출자 몫) — 여유 미달·모델
부족·트림 실패는 후속 조치가 다르다.

**트림 탭과 자동 설계는 같은 판정을 낸다** — 기체를 아는 문맥(`from_profile`)이면 미수렴 트림도 트림 탭과 같은 근거
판정(opspace/states.py `trim_assessment` — 한계 고정 평형·V_S)을 거쳐 트림 사유가 「미수렴」 한 낱말로 뭉치지 않는다.

**질량 조건**(v3 — 05 §11.13 11단계): 판정은 늘 기본 질량 모델(탑재 없음 = 대표 구성)의 트림이고 CG는 동역학에 없다
(02 §5.6 [한계]). 문서가 탑재 구성(mass.loadings)을 적었어도 계산은 그 구성을 반영하지 않으므로 `mass_condition`
{"loading": None, "loadings_declared": n, "cg_supported": False}로 그렇다고 싣는다 — **CG에 매인 검증은 이 판정으로 통과한
것이 아니다**(구성별·CG 범위 검증은 「CG 영향 미지원」이고 합격으로 세지 않는다). 채택 정책은 바꾸지 않는다(기본 구성의
판정은 그대로 유효하다).

요구영역 포함 여부는 문맥의 요구영역으로 분류해 `region`에 싣되 채택에는 쓰지 않는다 — 자동 설계 격자는 이관 2단계부터
요구영역의 기본 격자에서 나오므로(design/grid.py `region_grid`) 격자점은 애초에 요구영역 안이다. 기본 격자가 트림 **전에**
모델 부족·요구영역 밖·요구 미정의로 표시한 점은 트림을 돌리지 않고 `pre_trim_verdict`로 같은 모양의 판정을 싣는다 —
버리지 않고 왜 설계하지 않았는지를 남긴다(05 §11.13 2단계).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from claw.opspace.states import COMPUTABLE, MODEL_GAP, OUT_OF_REGION, UNDEFINED

_EPS = 1e-9


@dataclass(frozen=True)
class VerdictContext:
    """판정에 드는 기체 값 — 트림 탐색 범위(실속표 포함) · DB 범위 · 제한. 없는 제한(None)은 검사하지 않는다.

    built·region·model은 근거 판정과 요구영역 분류에 쓰고 cache는 그 근거 계산(기체·V_S)을 한 작업 안에서 나눠 쓴다 —
    넷 다 판정 값이 아니라 도구라 비교에서 뺀다. 문맥은 `from_profile` 하나로만 만든다(부품으로 따로 만들면 최대 동압·
    리미터 같은 제한이 조용히 빠진 문맥이 생긴다)."""

    trim_bounds: dict | None
    db_ranges: dict
    q_max: float | None
    mach_no: float | None
    limiter_margin: float | None
    fuel_max: float | None
    loadings_declared: int = 0
    built: object = field(default=None, compare=False, repr=False)
    region: object = field(default=None, compare=False, repr=False)
    model: object = field(default=None, compare=False, repr=False)
    cache: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_profile(cls, built, *, cache: dict | None = None) -> "VerdictContext":
        from claw.opspace.region import model_range_of, region_of

        return cls(trim_bounds=built.trim_bounds, db_ranges=dict(built.db_ranges()), q_max=built.q_max,
                   mach_no=built.structural_limits()["mach_no"], limiter_margin=built.law["alpha_margin"],
                   fuel_max=float(built.doc["mass"]["fuel_max"]), loadings_declared=built.loadings_declared,
                   built=built, region=region_of(built.doc),
                   model=model_range_of(built), cache={} if cache is None else cache)


def _alpha(tr) -> float:
    return math.atan2(float(tr.state.vel_b[2]), float(tr.state.vel_b[0]))


def _stall_at(trim_bounds, mach: float):
    """α_stall(M) — 실속표가 선언한 외삽 정책까지 포함한 값. 실속표가 없으면 None(근거 없음)."""
    stall = trim_bounds.get("stall")
    return None if stall is None else float(stall.interp(mach=mach))


def alpha_margin_short(tr, trim_bounds) -> bool | None:
    """트림 α 여유 미달인가 — α_trim ≥ α_stall(M) − trim_bounds["alpha_margin"](지금 기준의 판정선). 실속표가 없으면 None.

    트림이 풀 때 찍은 플래그(alpha_margin_ok)를 읽지 않고 지금 판정선으로 다시 잰다 — 판정선을 바꿔도 트림을 다시 풀지 않고
    여유 판정만 다시 한다(05 §11.3). α는 트림 여유 수치(reserve)의 값을 써 trim_level 플래그와 같은 산술이다(자세에서 되짚으면
    1 ulp가 갈려 경계 해의 판정이 뒤집힐 수 있다). 여유 수치가 없는 옛 해만 자세에서 잰다."""
    a_stall = _stall_at(trim_bounds, tr.case.mach)
    if a_stall is None:
        return None
    r = getattr(tr, "reserve", None) or {}
    alpha = float(r["alpha"]["trim"]) if r.get("alpha") else _alpha(tr)
    return not bool(alpha < a_stall - float(trim_bounds["alpha_margin"]))


def margin_of(tr, trim_bounds) -> dict:
    """여유 판정 {"status": "met"|"short"|"unevaluated", "reasons"} — 트림 탭 조건 상태와 자동 설계가 같이 쓰는 한 규칙.
    판정선(sat_frac·thr_margin·alpha_margin)은 trim_bounds가 싣는 적용 기준이다(criteria.trim_margin, 이관 12단계)."""
    from claw.trim import saturation_detail

    if not tr.converged:
        return {"status": "unevaluated", "reasons": []}
    short = [ch for ch, on in saturation_detail(tr, trim_bounds).items() if on]
    missing = []
    a_short = alpha_margin_short(tr, trim_bounds)
    if a_short is None:
        missing.append("stall_basis_missing")
    elif a_short:
        short.append("alpha_margin")
    status = "short" if short else ("unevaluated" if missing else "met")
    return {"status": status, "reasons": short + missing}


def _model(tr, ctx, converged: bool) -> dict:
    reasons = []
    mach_rng = ctx.db_ranges.get("mach")
    if mach_rng is not None and not mach_rng[0] - _EPS <= tr.case.mach <= mach_rng[1] + _EPS:
        reasons.append("db_mach")
    a_rng = ctx.db_ranges.get("alpha")
    if converged and a_rng is not None and not a_rng[0] - _EPS <= _alpha(tr) <= a_rng[1] + _EPS:
        reasons.append("db_alpha")
    if ctx.fuel_max is not None and not -_EPS <= tr.case.fuel <= ctx.fuel_max + _EPS:
        reasons.append("fuel_range")
    return {"status": "gap" if reasons else "valid", "reasons": reasons}


def _limits(tr, ctx, converged: bool) -> dict:
    from claw.env import isa_atmosphere

    violated, missing, detail = [], [], {}
    if converged:
        a_stall = _stall_at(ctx.trim_bounds, tr.case.mach)
        if a_stall is None:
            missing.append("stall_basis_missing")
        else:
            alpha = _alpha(tr)
            if alpha >= a_stall:
                violated.append("stall_boundary")
            elif ctx.limiter_margin is not None and alpha > a_stall - float(ctx.limiter_margin):
                violated.append("limiter_clips_trim")
                detail["limiter"] = {"alpha_trim": alpha, "alpha_max": a_stall - float(ctx.limiter_margin),
                                     "law": "theta_cmd <= theta + (alpha_max - alpha)"}
    if ctx.q_max is not None:
        atm = isa_atmosphere(tr.case.alt)
        if 0.5 * atm.rho * (tr.case.mach * atm.a) ** 2 > float(ctx.q_max) + _EPS:
            violated.append("q_max")
    if ctx.mach_no is not None and tr.case.mach > float(ctx.mach_no) + _EPS:
        violated.append("mach_no")
    status = "violated" if violated else ("unevaluated" if missing else "met")
    out = {"status": status, "reasons": violated + missing}
    if detail:
        out["detail"] = detail
    return out


def _region(tr, ctx) -> dict | None:
    """요구영역 분류 {"status": "in"|"out_of_region"|"undefined", "confirmed"} — 요구영역이 없으면 None."""
    if ctx.region is None:
        return None
    cls = ctx.region.classify(tr.case.mach, tr.case.alt, tr.case.fuel)
    return {"status": cls or "in", "confirmed": bool(ctx.region.confirmed)}


def mass_condition(ctx: VerdictContext) -> dict:
    """판정이 가정한 질량 조건 — 기본 질량 모델(탑재 구성 없음). CG는 동역학에 없어 늘 cg_supported False(머리말)."""
    return {"loading": None, "loadings_declared": int(ctx.loadings_declared), "cg_supported": False}


def condition_verdict(tr, ctx: VerdictContext, *, trim=None, assess: bool = True) -> dict:
    """트림 해 → {"trim", "model", "limits", "margin", "region", "mass_condition", "adopted", "exclusion"}.

    trim: 이미 잰 조건 상태 (state, reasons) — 트림 탭처럼 근거까지 잰 호출자가 넘긴다. 없으면 수렴 → 계산 가능, 미수렴은
    문맥이 기체를 알면(built) `trim_assessment`로 근거까지 재고, 모르거나 assess=False면 미평가(수렴 여부만 — δe_trim 도출처럼
    제외 범주만 쓰는 호출자가 근거 계산 비용을 치르지 않게).
    채택 정책: 트림 계산 가능 ∧ 모델 유효 ∧ 제한 충족 — 여유 미달은 막지 않는다(표시만). 미평가는 통과가 아니다.
    """
    converged = bool(tr.converged)
    if trim is not None:
        t = {"status": trim[0], "reasons": list(trim[1])}
    elif converged:
        t = {"status": COMPUTABLE, "reasons": []}
    elif assess and ctx.built is not None:
        from claw.opspace.states import trim_assessment

        a = trim_assessment(tr, ctx.built, ctx.model, cache=ctx.cache)
        t = {"status": a["state"], "reasons": list(a["reasons"])}
    else:
        t = {"status": "unassessed", "reasons": ["not_converged"]}
    ok_trim = t["status"] == COMPUTABLE
    model = _model(tr, ctx, ok_trim)
    limits = _limits(tr, ctx, ok_trim)
    margin = margin_of(tr, ctx.trim_bounds) if ok_trim else {"status": "unevaluated", "reasons": []}
    exclusion = None
    for category, item, ok in (("trim", t, ok_trim), ("model", model, model["status"] == "valid"),
                               ("limits", limits, limits["status"] == "met")):
        if not ok:
            exclusion = {"category": category, "reasons": list(item["reasons"])}
            break
    return {"trim": t, "model": model, "limits": limits, "margin": margin, "region": _region(tr, ctx),
            "mass_condition": mass_condition(ctx), "adopted": exclusion is None, "exclusion": exclusion}


# 트림 전 제외 상태 → 채택 제외 범주. 모델 부족은 요구 안이라 모델 범주, 요구영역 밖·미정의는 요구영역 범주다
PRE_TRIM_CATEGORY = {MODEL_GAP: "model", OUT_OF_REGION: "region", UNDEFINED: "region"}


def pre_trim_verdict(state: str, ctx: VerdictContext) -> dict:
    """트림 전 제외 상태(model_gap · out_of_region · undefined) → condition_verdict와 같은 모양의 판정.

    기본 격자(opspace/basegrid.py)가 트림 전에 정한 상태라 트림을 돌리지 않는다 — 모델·제한·여유는 미평가(통과가 아니다),
    채택하지 않고, 제외 사유는 그 상태 하나다. 모델 부족은 요구영역 **안**이라 region은 "in"이고 제외 범주는 model,
    요구영역 밖·미정의는 region 범주다. 문맥에 요구영역이 없으면 region은 None(condition_verdict와 같은 규약)."""
    if state not in PRE_TRIM_CATEGORY:
        raise ValueError(f"트림 전 제외 상태가 아니다: {state!r} — 허용: {sorted(PRE_TRIM_CATEGORY)}")
    unevaluated = {"status": "unevaluated", "reasons": []}
    region = None if ctx.region is None else {
        "status": "in" if state == MODEL_GAP else state, "confirmed": bool(ctx.region.confirmed)}
    return {"trim": {"status": state, "reasons": [state]}, "model": dict(unevaluated), "limits": dict(unevaluated),
            "margin": dict(unevaluated), "region": region, "mass_condition": mass_condition(ctx), "adopted": False,
            "exclusion": {"category": PRE_TRIM_CATEGORY[state], "reasons": [state]}}
