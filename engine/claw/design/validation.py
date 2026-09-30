"""검증점 생성과 결과 요약 격자 (05 §11.6 · 05 §11.8 — 이관 4단계).

검증점은 **스케줄 표를 실제로 평가한 게인**으로 마진을 보는 점이다(05 §6 원칙). v1.70까지는 설계점 행(고도·연료)마다 그 행
채택 설계점의 마하 범위 안에서 절점 구간 내분점만 놓았다(`schedmap.validation_points` — 설정 rule "midpoint"로 남긴다). 그
규칙은 설계점에서 빠진 조건이 검증에서도 빠지고, 표가 끝값으로 버티는 요구영역 끝과 요구영역 경계를 보지 않았다. 여기서는
05 §11.6 생성 절차를 따른다:

1. 검증조건(고도·연료 조합)은 설계점과 따로 정한다 — 설정 `conditions`, 없으면 설계 격자 행을 **초기 목록**으로 쓴다
   (validation_conditions). 대표 조합은 끝값·중앙 + 직전 검증의 실패 행이고, 생략한 행을 결과에 남긴다
2. 절점 합집합으로 마하 구간을 나누고 구간마다 내분점(schedmap._fractions 배치 — 설계점 자리는 옮긴다). 행의 마하 범위는
   **요구영역의 그 행 범위**다(채택 설계점 범위가 아니다 — 트림이 안 서는 끝도 요구면 검증 대상이다)
3. 절점 마하 점(설계점이 이미 있으면 그 점이 판정을 겸한다 — 공짜) · clip 구간 점(요구영역이 첫·끝 절점 밖으로 뻗은 부분)
4. 요구영역 경계점(행마다 마하 하한·상한, 고도·연료 끝값 ∪ 경계표 행·층) · 추가 조건(출처 필수)
5. 점마다 트림 전 상태(opspace.states.pre_state) — 요구영역 밖·요구 미정의·모델 부족은 **계획에만** 남는다(점 집합에 넣지 않고
   트림하지 않으며 예산을 쓰지 않는다)

예산 순서는 내분점 1라운드 → clip → 절점 → 경계 → 추가 → 내분점 2라운드 이후다 — 예산이 끊겨도 구간당 한 점과 표 끝·요구
경계가 먼저 찬다. 고도·연료 축 설계점 인접쌍의 내분점(v1.70 규칙)은 between_rows로 남긴다(마하 1축 표라 그 축에는 절점이
없다 — 표본 행 사이를 본다).

요약 격자(summary_grid)는 세 축(계산 상태 · 성능 판정 · 검증 범위)을 섞지 않는다(05 §11.8): 성능 판정은 계산 가능한 점에만
붙고, 분모는 요청한 점 전부(요구영역 밖만 따로 센다), 대표 문구는 불합격 → 미완료 → 「검사한 점 모두 충족」이다 — 「구간
합격」이라 쓰지 않는다(표본이 모두 통과한 것과 구간 전체가 보장된 것은 다르다).
"""

from __future__ import annotations

import math

from claw.design.points import ROLE_DESIGN, case_name
from claw.opspace.states import (
    CALC_FAILED,
    COMPUTABLE,
    MODEL_GAP,
    NOT_RUN,
    OUT_OF_REGION,
    STATE_LABEL,
    UNDEFINED,
    pre_state,
)

VALIDATION_RULES = ("plan", "midpoint")  # plan = 05 §11.6 생성 절차 · midpoint = v1.70 규칙(옛 세션 재개)
VALIDATION_MODES = {"full": "전체 조합", "representative": "대표 조합"}
VALIDATION_KINDS = {
    "midpoint": "구간 내분점", "knot": "절점", "clip": "clip 구간", "boundary": "요구영역 경계",
    "extra": "추가 조건", "between_rows": "고도·연료 사이", "reinforce": "보강",
    # 앞선 VERIFY가 넣은 검증점 중 이번 계획에 없는 점 — 점 집합에 남아 판정받고 CLASSIFY로 가니 요약에도 보인다(리뷰 5)
    "prior": "이전 계획",
}
# [기본값 — 사용자 결정 2026-09-30] 경계점 켬. 조건 None = 설계 격자 행을 초기 목록으로
DEFAULT_VALIDATION = {"rule": "plan", "conditions": None, "mode": "full", "boundary": True, "extras": []}
# 목록 상한 — 오타 목록이 단일 워커를 물지 않게(기본 격자 상한 400과 같은 취지). 실측 근거는 없다 [기본값]
MAX_CONDITIONS = 64
MAX_EXTRAS = 64
PLAN_ONLY_STATES = frozenset({OUT_OF_REGION, UNDEFINED, MODEL_GAP})  # 계획에만 남는 트림 전 상태
EXTRA_ROW = "extra"
EXTRA_ROW_LABEL = "경계·추가"
VERDICT_KEYS = ("fail", "caution", "good", "na", "excluded")
VERDICT_LABEL = {"fail": "불합격", "caution": "합격·주의", "good": "합격·권장 충족", "na": "판정 불가",
                 "excluded": "채택 제외"}
# 대표 문구 — 코드와 문구. 우선순위는 불합격 → 미완료 → (판정 불가·채택 제외 포함) → 검사한 점 모두 충족. 가운데 둘은 계산은
# 됐는데 성능을 못 잰(판정 불가)·채택하지 않은(제한 위반 등) 점이 있는 칸이다 — 「모두 충족」으로 뭉개지 않는다
HEADLINE_TEXT = {"fail": "불합격", "incomplete": "미완료", "na": "판정 불가 포함", "excluded": "채택 제외 포함",
                 "all_met": "검사한 점 모두 충족"}

_EPS = 1e-9
_ROW_ROUND = 9  # 경계 마하 반올림 — 기본 격자 행 끝점(basegrid._r)과 같은 자릿수라 이름이 맞는다(그 설계점이 판정을 겸한다)


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def check_validation_config(cfg: dict) -> dict:
    """검증점 설정 검증 — 정규형 dict(AutoDesignConfig가 부른다 — 서버 422도 이 ValueError다). 없는 칸은 기본값."""
    if not isinstance(cfg, dict):
        raise ValueError(f"validation은 dict: {cfg!r}")
    unknown = sorted(set(cfg) - set(DEFAULT_VALIDATION))
    if unknown:
        raise ValueError(f"validation: 미정의 키 {unknown} — 허용: {sorted(DEFAULT_VALIDATION)}")
    out = {**DEFAULT_VALIDATION, **cfg}
    if out["rule"] not in VALIDATION_RULES:
        raise ValueError(f"validation.rule은 {list(VALIDATION_RULES)} 중 하나: {out['rule']!r}")
    if out["mode"] not in VALIDATION_MODES:
        raise ValueError(f"validation.mode는 {list(VALIDATION_MODES)} 중 하나: {out['mode']!r}")
    if not isinstance(out["boundary"], bool):
        raise ValueError(f"validation.boundary는 true/false: {out['boundary']!r}")
    if out["conditions"] is not None:
        rows = out["conditions"]
        if not isinstance(rows, (list, tuple)) or not rows:
            raise ValueError("validation.conditions는 [[고도 m, 연료 kg], …] 비어 있지 않은 목록 또는 없음(설계 격자 행)")
        norm = set()
        for r in rows:
            if not isinstance(r, (list, tuple)) or len(r) != 2 or not all(_finite(x) for x in r):
                raise ValueError(f"validation.conditions 항목은 유한한 [고도 m, 연료 kg]: {r!r}")
            if r[1] < 0:
                raise ValueError(f"validation.conditions 연료는 0 이상 kg: {r!r}")
            norm.add((float(r[0]), float(r[1])))
        if len(norm) > MAX_CONDITIONS:
            raise ValueError(f"validation.conditions {len(norm)}개가 상한 {MAX_CONDITIONS}을 넘는다")
        # 정렬·중복 제거 — 같은 조건이 두 번이면 같은 이름의 점이 두 번 계획된다
        out["conditions"] = [list(r) for r in sorted(norm)]
    extras = out["extras"]
    if not isinstance(extras, (list, tuple)):
        raise ValueError("validation.extras는 [{mach, alt, fuel, source}, …] 목록")
    if len(extras) > MAX_EXTRAS:
        raise ValueError(f"validation.extras {len(extras)}개가 상한 {MAX_EXTRAS}을 넘는다")
    norm_x = []
    for e in extras:
        if not isinstance(e, dict) or set(e) != {"mach", "alt", "fuel", "source"}:
            raise ValueError(f"validation.extras 항목은 {{mach, alt, fuel, source}} 네 칸: {e!r}")
        if not all(_finite(e[k]) for k in ("mach", "alt", "fuel")) or e["mach"] <= 0 or e["fuel"] < 0:
            raise ValueError(f"validation.extras 좌표는 유한하고 마하 > 0 · 연료 ≥ 0: {e!r}")
        # 출처 필수 — 사용자 지정·다른 탭 요청·실패 조사 중 무엇인지 모르는 점은 결과에서 읽을 수 없다(05 §11.6 ⑦)
        if not isinstance(e["source"], str) or not e["source"].strip():
            raise ValueError(f"validation.extras 출처(source)가 비었다: {e!r}")
        norm_x.append({"mach": float(e["mach"]), "alt": float(e["alt"]), "fuel": float(e["fuel"]),
                       "source": e["source"].strip()})
    out["extras"] = norm_x
    return out


def _mid3(vals) -> set:
    s = sorted(set(vals))
    return {s[0], s[(len(s) - 1) // 2], s[-1]}


def validation_conditions(cfg: dict, *, design_rows, prior_failure_rows=()) -> dict:
    """검증조건 목록 — {"rows": [[alt, fuel]], "source": "user"|"design_rows", "mode", "omitted": [[alt, fuel]]}.

    대표 조합은 고도·연료 각각의 {최소·중앙·최대} 곱 + 직전 검증에서 실패가 난 행이다(05 §11.6 — 경계·중앙·기존 취약점). 생략한
    행은 omitted로 남는다 — 끝값만 검사한 결과를 완전한 검증으로 표시하지 않게(coverage_gaps가 말한다). 실패 행은 목록에 있는
    행만 되살린다 — 생략 목록의 분모가 목록 자신이어야 「k개 생략」이 뜻을 갖는다."""
    cfg = check_validation_config(dict(cfg))
    src = cfg["conditions"]
    source = "user" if src is not None else "design_rows"
    rows = sorted({(float(a), float(f)) for a, f in (src if src is not None else design_rows)})
    omitted = []
    if cfg["mode"] == "representative" and rows:
        keep_a, keep_f = _mid3(r[0] for r in rows), _mid3(r[1] for r in rows)
        weak = {(float(a), float(f)) for a, f in prior_failure_rows}
        kept = [r for r in rows if (r[0] in keep_a and r[1] in keep_f) or r in weak]
        omitted = [r for r in rows if r not in kept]
        rows = kept
    return {"rows": [list(r) for r in rows], "source": source, "mode": cfg["mode"],
            "omitted": [list(r) for r in omitted]}


def _pre(region, model, mach, alt, fuel) -> str:
    if region is not None:
        return pre_state(region, model, mach, alt, fuel)
    if model is not None and not model.covers(mach, fuel):
        return MODEL_GAP
    return NOT_RUN


def validation_plan(points, union, region, model, *, rows, n_between: int = 1, boundary: bool = True,
                    extras=()) -> dict:
    """검증점 계획 — {"entries": [...], "moved": n, "unplaceable": n, "gaps": [{row, interval, why}]}.

    entry = {name, mach, alt, fuel, kind, row, origin, pre_state, existing}. row는 검증조건 [alt, fuel](경계·추가·고도·연료
    사이 점은 None — 요약의 「경계·추가」 행), existing은 그 이름의 점이 이미 점 집합에 있는가(절점 자리 설계점이면 공짜다).
    points: 설계 보기(designable). region None(요구영역 없는 기체의 옛 격자)이면 행의 마하 범위는 채택 설계점 범위이고
    경계·clip 점은 없다. 목록 순서가 곧 예산 순서다(머리말). moved·unplaceable은 내분점 배치의 옮김·빈 자리 없음 수다
    (schedmap.validation_candidates와 같은 뜻).

    절점 구간이 행 범위에 **일부만** 걸치면(행 [0.35, 0.9] · 구간 [0.2, 0.4]) 구간 중점은 행 밖이어도 안쪽 부분(0.35–0.4)은
    요구다 — 그 부분의 내분점을 kind midpoint로 두고 origin은 안쪽 부분 `midpoint:M<lo>|M<hi>`다. 안쪽 부분이 반올림
    자릿수보다 좁아 점을 둘 수 없으면 gaps에 남긴다(구간째 조용히 빼지 않는다 — 리뷰 3)."""
    from claw.design.refine import _ROUND  # 순환 import 회피 — 중점 반올림 자릿수의 정본은 refine
    from claw.design.schedmap import _fractions

    if n_between < 1:
        raise ValueError(f"n_between은 1 이상: {n_between}")
    knots = sorted(float(k) for k in union)
    intervals = list(zip(knots, knots[1:]))
    ks = sorted(range(1, n_between + 1), key=lambda k: abs(2 * k - (n_between + 1)))  # 중점 우선 라운드
    step = 1.0 / (n_between + 1.0)
    rows = sorted({(float(a), float(f)) for a, f in rows})
    design_range: dict = {}
    for p in points.by_role(ROLE_DESIGN):
        if p.trimmable is not False:
            design_range.setdefault((p.case.alt, p.case.fuel), []).append(p.case.mach)

    def bounds(alt, fuel):
        """행의 마하 범위 — (lo, hi) | None(요구 미정의 · 옛 격자에서 채택 설계점 없음)."""
        if region is None:
            ms = design_range.get((alt, fuel))
            return (min(ms), max(ms)) if ms else None
        b = region.mach_bounds(alt, fuel)
        return None if b is None else (round(b[0], _ROW_ROUND), round(b[1], _ROW_ROUND))

    row_b = {r: bounds(*r) for r in rows}
    entries, seen, gaps = [], set(), []
    moved = unplaceable = 0

    def add(m, a, f, kind, row, origin):
        name = case_name(m, a, f)
        if name in seen:
            return
        seen.add(name)
        entries.append({"name": name, "mach": float(m), "alt": float(a), "fuel": float(f), "kind": kind,
                        "row": None if row is None else [row[0], row[1]], "origin": origin,
                        "pre_state": _pre(region, model, m, a, f), "existing": name in points})

    def _is_design(name):
        return name in points and points.get(name).role == ROLE_DESIGN

    def place(coord_at, t, kind, row, origin, ok=lambda m: True):
        """t부터 설계점이 아닌 첫 내분점에 둔다 — schedmap.validation_candidates와 같은 배치(설계점은 적합 표본이라 거기서
        재면 보간이 아니라 적합 잔차다)."""
        nonlocal moved, unplaceable
        for i, fr in enumerate(_fractions(t, step)):
            m, a, f = coord_at(fr)
            if not ok(m) or _is_design(case_name(m, a, f)):
                continue
            if i:
                moved += 1
            add(m, a, f, kind, row, origin)
            return
        unplaceable += 1

    def partial(lo2, hi2, t, row, ka, kb):
        nonlocal unplaceable
        ok = lambda m: lo2 + _EPS < m < hi2 - _EPS  # noqa: E731 — 안쪽 부분의 **내부**(끝은 절점·경계 점이 본다)
        before = unplaceable
        place(lambda fr: (round(lo2 + (hi2 - lo2) * fr, _ROUND), row[0], row[1]), t, "midpoint", row,
              f"midpoint:M{lo2:.12g}|M{hi2:.12g}", ok=ok)
        if unplaceable > before and not any(ok(round(lo2 + (hi2 - lo2) * fr, _ROUND)) for fr in _fractions(t, step)):
            unplaceable = before  # 설계점에 막힌 게 아니라 자리가 없다 — 공백으로 센다
            gaps.append({"row": [row[0], row[1]], "interval": [ka, kb],
                         "why": f"요구 범위 안 부분 M{lo2:.12g}–M{hi2:.12g}이 반올림 자릿수({_ROUND})보다 좁아 점을 둘 수 없다"})

    pairs = [(points.get(a).case, points.get(b).case, a, b, axis)
             for a, b, axis in points.adjacent_pairs(ROLE_DESIGN) if axis != "mach"]

    def midpoint_round(t, first):
        for row in rows:
            b = row_b[row]
            if b is None and region is None:
                continue  # 옛 격자에서 채택 설계점이 없는 행 — 잴 범위를 모른다
            # 미정의 행은 전 구간을 계획에 남긴다(상태 undefined) — 계산하지 못한 조건이 요약에서 사라지지 않게(05 §11.8)
            lo, hi = (-math.inf, math.inf) if b is None else b
            for ka, kb in intervals:
                if not lo - _EPS <= round(ka + (kb - ka) * t, _ROUND) <= hi + _EPS:
                    lo2, hi2 = max(ka, lo), min(kb, hi)
                    if first and hi2 - lo2 > _EPS:  # 일부만 걸친 구간 — 안쪽 부분에 한 점(첫 라운드만)
                        partial(lo2, hi2, t, row, ka, kb)
                    continue
                place(lambda fr, ka=ka, kb=kb, row=row: (round(ka + (kb - ka) * fr, _ROUND), row[0], row[1]),
                      t, "midpoint", row, f"midpoint:M{ka:.12g}|M{kb:.12g}",
                      ok=lambda m, lo=lo, hi=hi: lo - _EPS <= m <= hi + _EPS)
        for ca, cb, a, b, axis in pairs:
            def _at(fr, ca=ca, cb=cb, axis=axis):
                c = {ax: getattr(ca, ax) + (getattr(cb, ax) - getattr(ca, ax)) * fr for ax in ("mach", "alt", "fuel")}
                c[axis] = round(c[axis], _ROUND)
                return c["mach"], c["alt"], c["fuel"]
            place(_at, t, "between_rows", None, f"midpoint:{a}|{b}")

    midpoint_round(ks[0] * step, True)
    if knots and region is not None:
        for row in rows:  # clip — 표가 끝값으로 버티는 요구영역 끝(05 §11.6 ③)
            b = row_b[row]
            if b is None:
                continue
            if b[0] < knots[0] - _EPS:
                add(round((b[0] + knots[0]) / 2.0, _ROUND), row[0], row[1], "clip", row, "clip:lo")
            if b[1] > knots[-1] + _EPS:
                add(round((knots[-1] + b[1]) / 2.0, _ROUND), row[0], row[1], "clip", row, "clip:hi")
    for row in rows:  # 절점 — 설계점이 있으면 그 점이 판정을 겸한다(existing)
        b = row_b[row]
        if b is None and region is None:
            continue
        for k in knots:
            if b is None or b[0] - _EPS <= k <= b[1] + _EPS:
                add(k, row[0], row[1], "knot", row, f"knot:M{k:.12g}")
    if boundary and region is not None:
        for row in rows:  # 검증 행의 마하 하한·상한
            b = row_b[row]
            if b is not None:
                for m in b:
                    add(m, row[0], row[1], "boundary", None, "boundary:row")
        # 요구영역 경계 — 고도·연료 끝값 ∪ 경계표 행·층(끝값만 쓰면 경계표가 끝값까지 안 닿을 때 정의된 끝 행을 놓친다)
        layers = [f for f, _ in (region.boundary or ())]
        b_fuels = sorted({float(f) for f in region.fuel} | set(layers))
        b_alts = sorted({float(a) for a in region.alt} | {r[0] for _, rs in (region.boundary or ()) for r in rs})
        for f in b_fuels:
            for a in b_alts:
                b = region.mach_bounds(a, f)
                if b is not None:
                    for m in b:
                        add(round(m, _ROW_ROUND), a, f, "boundary", None, "boundary:region")
    for e in extras:
        add(float(e["mach"]), float(e["alt"]), float(e["fuel"]), "extra", None, f"extra:{e['source']}")
    for k in ks[1:]:
        midpoint_round(k * step, False)
    return {"entries": entries, "moved": moved, "unplaceable": unplaceable, "gaps": gaps}


# ── 결과 요약 격자 (05 §11.8) ─────────────────────────────────────────────────────────


def summary_columns(union) -> list:
    """열 — clip_lo | knot1 | seg1-2 | knot2 | … | clip_hi. 절점은 평가 대상 표들의 합집합이다(한 점이 두 칸에 세어지지 않는다).
    절점이 없으면(전 자리 상수) 열 하나(all)."""
    u = sorted(float(k) for k in union)
    if not u:
        return [{"key": "all", "kind": "all", "lo": None, "hi": None}]
    cols = [{"key": "clip_lo", "kind": "clip", "lo": None, "hi": u[0]}]
    for i, k in enumerate(u):
        cols.append({"key": f"knot{i + 1}", "kind": "knot", "lo": k, "hi": k})
        if i + 1 < len(u):
            cols.append({"key": f"seg{i + 1}-{i + 2}", "kind": "seg", "lo": k, "hi": u[i + 1]})
    cols.append({"key": "clip_hi", "kind": "clip", "lo": u[-1], "hi": None})
    return cols


def column_of(mach: float, union) -> str:
    u = sorted(float(k) for k in union)
    if not u:
        return "all"
    if mach < u[0] - _EPS:
        return "clip_lo"
    if mach > u[-1] + _EPS:
        return "clip_hi"
    for i, k in enumerate(u):
        if abs(mach - k) <= _EPS:
            return f"knot{i + 1}"
    i = max(j for j, k in enumerate(u) if k < mach)
    return f"seg{i + 1}-{i + 2}"


def row_key(alt: float, fuel: float) -> str:
    return f"h{alt:.12g}_f{fuel:.12g}"


def entry_state(entry: dict, points, margin_cases) -> str:
    """계산 상태 — 트림 전 상태, 아니면 점 판정의 트림 상태. 점 집합·결과에 없으면 미계산(예산·취소)."""
    if entry["pre_state"] != NOT_RUN:
        return entry["pre_state"]
    name = entry["name"]
    if name not in points or name not in margin_cases:
        return NOT_RUN
    v = points.get(name).verdict
    if v is None:
        return COMPUTABLE if margin_cases[name].get("loops") else CALC_FAILED
    st = v["trim"]["status"]
    # 근거를 못 잰 미수렴(문맥이 기체를 모름 — unassessed)은 어느 한계에 붙었다고 못 한다 — 계산 실패로 센다
    return st if st in STATE_LABEL else CALC_FAILED


def entry_verdict(entry: dict, points, margin_cases) -> str | None:
    """성능 판정 — 계산 가능한 점에만. 채택하지 않은 점(엔벨로프 밖)은 excluded, 아니면 자리 판정의 최악(fail > na > warn > ok)."""
    if entry_state(entry, points, margin_cases) != COMPUTABLE:
        return None
    case = margin_cases.get(entry["name"]) or {}
    if case.get("outside_envelope") or points.get(entry["name"]).trimmable is False:
        return "excluded"
    sts = [m.get("status") for m in (case.get("loops") or {}).values()]
    if not sts:
        return "na"
    if "fail" in sts:
        return "fail"
    if any(s not in ("ok", "warn") for s in sts):
        return "na"
    return "caution" if "warn" in sts else "good"


def _headline(cell) -> str:
    if cell["verdicts"]["fail"]:
        return "fail"
    if cell["done"] < cell["n"]:
        return "incomplete"
    if cell["verdicts"]["na"]:
        return "na"
    if cell["verdicts"]["excluded"]:
        return "excluded"
    return "all_met"


def _cell_text(cell) -> str:
    v = cell["verdicts"]
    parts = [f"불합격 {v['fail']}"] if v["fail"] else []
    parts.append(f"완료 {cell['done']}/{cell['n']}")
    parts += [f"{STATE_LABEL[st]} {k}" for st, k in sorted(cell["states"].items()) if st != COMPUTABLE and k]
    parts += [f"{VERDICT_LABEL[key]} {v[key]}" for key in ("na", "excluded") if v[key]]
    if cell["out_of_region"]:
        parts.append(f"요구영역 밖 {cell['out_of_region']}(분모 밖)")
    return " · ".join(parts)


def _new_cell() -> dict:
    return {"n": 0, "done": 0, "out_of_region": 0, "states": {}, "verdicts": {k: 0 for k in VERDICT_KEYS},
            "names": []}


def summary_grid(entries, points, margin_cases, union, *, rows=None) -> dict:
    """요약 격자 — {"columns", "rows", "cells": {행 키: {열 키: 칸}}, "totals"}.

    칸 = {n, done, out_of_region, states, verdicts{fail,caution,good,na,excluded}, headline, headline_code, text, names}.
    n은 요청한 점(요구영역 밖 제외 — 그 수는 out_of_region), done은 계산 가능한 점, 결과 데이터에 없는 요청 점은 미계산이다.
    rows: 검증조건 [[alt, fuel]] — 주면 점이 없는 행도 남는다. 경계·추가·고도·연료 사이 점은 「경계·추가」 행에 모은다 —
    가까운 행에 끼워 넣지 않는다(05 §11.8)."""
    cols = summary_columns(union)
    row_list = sorted({(float(a), float(f)) for a, f in (rows or ())}
                      | {tuple(e["row"]) for e in entries if e["row"] is not None})
    out_rows = [{"key": row_key(a, f), "alt": a, "fuel": f, "kind": "condition", "label": f"{a:g} m · {f:g} kg"}
                for a, f in row_list]
    out_rows.append({"key": EXTRA_ROW, "alt": None, "fuel": None, "kind": "extra", "label": EXTRA_ROW_LABEL})
    cells: dict = {}
    tot = _new_cell()
    for e in entries:
        if e.get("measure_only"):  # 보강의 재기만 하는 항목(같은 이름의 본 항목이 세거나, 점이 아닌 공백) — 두 번 세지 않는다
            continue
        rk = EXTRA_ROW if e["row"] is None else row_key(*e["row"])
        cell = cells.setdefault(rk, {}).setdefault(column_of(e["mach"], union), _new_cell())
        st = entry_state(e, points, margin_cases)
        if st == OUT_OF_REGION:  # 판정 대상이 아니다 — 분모에서 빼고 따로 센다(05 §11.8)
            cell["out_of_region"] += 1
            tot["out_of_region"] += 1
            continue
        verdict = entry_verdict(e, points, margin_cases)
        for c in (cell, tot):
            c["n"] += 1
            c["states"][st] = c["states"].get(st, 0) + 1
            if st == COMPUTABLE:
                c["done"] += 1
                c["verdicts"][verdict] += 1
        cell["names"].append(e["name"])
    for by_col in cells.values():
        for cell in by_col.values():
            code = _headline(cell)
            cell.update(headline_code=code, headline=HEADLINE_TEXT[code], text=_cell_text(cell))
    tot.pop("names")
    code = _headline(tot)
    tot.update(headline_code=code, headline=HEADLINE_TEXT[code], text=_cell_text(tot))
    return {"columns": cols, "rows": out_rows, "cells": cells, "totals": tot}
