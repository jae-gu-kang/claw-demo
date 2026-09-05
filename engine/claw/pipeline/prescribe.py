"""정량 처방 — "어떤 손잡이를 **얼마나** 고쳐야 문턱을 넘는가" (02 §2.4의 마지막 조각).

진단(diagnose — 무엇을·어느 방향)과 스윕(sweep — 흔들면 얼마나 변하나) 위에
얹히는 세 번째 답이다: 저장된 스윕 행을 **다시 세워**(새 시뮬 없음) 단일 손잡이의
필요 변화량과 복수 손잡이의 최소 조합을 낸다. 확정은 언제나 실측 1회다 — 제안
형상(proposal_shape)을 evaluate()에 넣어 확인하는 것은 호출자(서버 라우트)의 몫.

**제안 생성기와 채점기의 분리가 계약이다**: 이 모듈은 후보(스팬 조합)를 만들 뿐
합격 판정은 하지 않는다 — 판정은 evaluate가 하고, 향후 복수 게인 조정 최적화기
(AI든 탐색이든)는 이 모듈을 갈아끼우고 evaluate를 그대로 쓴다.

외삽의 규율 (웹 trendMatrix와 같은 규칙 — lib/influence.js trendOf):
- 단조 판정은 **연속 차분의 부호**다. 스팬 안에 극점이 있는(mixed) 손잡이는
  "한쪽으로 밀면 안 된다"가 답이라 필요 변화량을 내지 않는다
- 표본 스팬(±20 %) 밖 교차는 참고 추정치만 내고 solvable=False를 유지한다 —
  "20 % 안에서 못 잡는다"는 사실을 흐리지 않는다
- 케이스마다 요구 방향이 갈리면 게인 수준이 아니라 **스케줄 셀** 문제다(국소) —
  단일 배율로 풀 수 없음을 사유로 낸다

조합 해(solve_joint)는 스윕 단독 런의 기울기 행렬(선형 국소 모델) 위에서
SLSQP(트림과 같은 방식 — 신규 의존 없음)로 하드 지표 제약을 만족하는 최소 변화
(min Σx²)를 찾는다. 쌍 런의 비가산성은 차단이 아니라 경고로 동봉한다 — 선형
모델의 신뢰도를 화면이 알게.
"""

import math

import numpy as np
from scipy.optimize import minimize

from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.influence import Shape, apply_param, param_universe
from claw.pipeline.sweep import _value_at

# 단조 판정의 상대 문턱 — 웹 trendOf(TREND_EPS_REL)와 같은 값: 1 ulp 차이가
# 「비단조」를 세우면 이 모듈에서 가장 센 거절이 부동소수 끝자리로 나온다
_EPS_REL = 1e-12

# 조합 해가 존중하는 하드 지표 — (metric, criteria 경로, above_is_bad).
# evaluate의 하드 게이트 중 **스윕 행이 실측하는 지표**만이 대상이다(선형 모델의
# 정의역). 마진·ζ류(선형 단계)는 확인 런의 evaluate가 잡는다.
def _targets(crit: GainEvalCriteria):
    out = []
    for axis, mkey in (("alt", "alt_rms"), ("spd", "spd_rms"), ("hdg", "hdg_rms")):
        limit = crit.response.rms_max.get(axis)
        if limit is not None:
            out.append((mkey, float(limit), True))
    out.append(("surf_sat_frac", float(crit.actuator.sat_frac_max), True))
    out.append(("worst_stall_margin", float(crit.envelope.alpha_margin_min), False))
    return out


def _num(v):
    if v is None:
        return None
    if isinstance(v, str):  # 직렬화 왕복의 "inf"/"-inf"
        try:
            v = float(v)
        except ValueError:
            return None
    v = float(v)
    return v if math.isfinite(v) else None


def _solo_points(rows, knob, metric):
    """케이스별 (스팬, 값) 점열 — base(스팬 0) 포함, 유한값만. {case: [(s, v), …]}."""
    by_case: dict = {}
    for r in rows:
        if r.get("aborted"):
            continue
        case = r["case"]
        if r["label"] == "base":
            v = _num((r.get("metrics") or {}).get(metric))
            if v is not None:
                by_case.setdefault(case, {})[0.0] = v
            continue
        ov = r.get("overrides") or {}
        if list(ov.keys()) != [knob]:
            continue  # 쌍 런·다른 손잡이 — 단독 귀속만 (웹 sweepKnobs와 같은 규칙)
        label = r["label"]
        if "@" not in label:
            continue
        try:
            s = float(label.rsplit("@", 1)[1])
        except ValueError:
            continue
        v = _num((r.get("metrics") or {}).get(metric))
        if v is not None:
            by_case.setdefault(case, {})[s] = v
    return {c: sorted(pts.items()) for c, pts in by_case.items()
            if 0.0 in pts and len(pts) >= 2}


def _trend(pts):
    """연속 차분 부호 → 'up' | 'down' | 'flat' | 'mixed' (상대 문턱 _EPS_REL)."""
    up = down = False
    for (s0, v0), (s1, v1) in zip(pts[:-1], pts[1:]):
        d = v1 - v0
        scale = max(abs(v0), abs(v1), 1e-30)
        if abs(d) <= _EPS_REL * scale:
            continue
        if d > 0:
            up = True
        else:
            down = True
    if up and down:
        return "mixed"
    if up:
        return "up"
    if down:
        return "down"
    return "flat"


def _first_crossing(pts, threshold, above_is_bad):
    """0에서 바깥쪽으로 걸으며 합격 쪽으로 넘는 첫 교차 스팬 — (span|None, 방향).

    양·음 두 방향을 각각 걷고, 교차가 있는 쪽(둘 다면 |스팬| 작은 쪽)을 취한다.
    """
    def passes(v):
        return v <= threshold if above_is_bad else v >= threshold

    def walk(side):
        # base(0)는 두 방향 걷기의 공통 출발점이다 — 한쪽에서 빠지면 그 방향의
        # 첫 구간 교차를 통째로 놓친다
        seq = [(s, v) for s, v in pts
               if s == 0.0 or (s > 0) == (side > 0)]
        seq = sorted(seq, key=lambda p: abs(p[0]))
        for (s0, v0), (s1, v1) in zip(seq[:-1], seq[1:]):
            if passes(v1):
                if v1 == v0:
                    return s1
                t = (threshold - v0) / (v1 - v0)
                t = min(max(t, 0.0), 1.0)
                return s0 + t * (s1 - s0)
        return None

    cands = [s for s in (walk(+1), walk(-1)) if s is not None]
    if not cands:
        return None
    return min(cands, key=abs)


def solve_single_knob(rows, knob, metric, threshold, *, above_is_bad) -> dict:
    """저장된 스윕에서 손잡이 하나의 필요 변화량 — {"solvable", "required_span", …}.

    반환 스팬은 상대 변화(0.1 = +10 %, |값| 기준 — sweep._value_at과 같은 의미)다.
    전 결함 케이스를 고치는 값(방향 공통·크기 최댓값)이고, binding_case가 그 크기를
    정한 케이스다.
    """
    threshold = float(threshold)
    by_case = _solo_points(rows, knob, metric)
    if not by_case:
        return {"solvable": False, "required_span": None,
                "reason": "이 손잡이·지표의 단독 런이 없다 — 스윕이 흔든 적 없다"}

    def passes(v):
        return v <= threshold if above_is_bad else v >= threshold

    bad = {c: pts for c, pts in by_case.items() if not passes(pts_base(pts))}
    if not bad:
        return {"solvable": True, "required_span": 0.0, "direction": None,
                "reason": "이미 전 케이스가 문턱 안이다", "binding_case": None}

    needs = {}
    for case, pts in bad.items():
        tr = _trend(pts)
        if tr == "mixed":
            return {"solvable": False, "required_span": None,
                    "reason": f"{case}: 스팬 안 경향이 비단조(mixed) — 한쪽으로 밀면 "
                              "안 된다는 사실이 답이라 외삽하지 않는다"}
        if tr == "flat":
            return {"solvable": False, "required_span": None,
                    "reason": f"{case}: 이 손잡이는 이 지표를 사실상 안 움직인다(평탄)"}
        s = _first_crossing(pts, threshold, above_is_bad)
        if s is None:
            # 참고 추정 — 0 주변 기울기로 선형 외삽 (참고일 뿐 solvable은 아니다)
            spans = [p[0] for p in pts]
            vals = [p[1] for p in pts]
            slope = _ls_slope(spans, vals)
            est = ((threshold - pts_base(pts)) / slope
                   if slope not in (None, 0.0) else None)
            return {"solvable": False, "required_span": None,
                    "extrapolated_span": est,
                    "reason": f"{case}: 표본 스팬(±{max(abs(min(spans)), abs(max(spans))):g})"
                              " 안에 교차 없음 — 추정치는 참고용이다"}
        needs[case] = s

    signs = {math.copysign(1.0, s) for s in needs.values() if s != 0.0}
    if len(signs) > 1:
        return {"solvable": False, "required_span": None,
                "reason": "케이스마다 요구 방향이 상충 — 단일 배율이 아니라 스케줄 "
                          "셀(국소) 문제다. 3단 A 국소성 판정과 대조할 것"}
    binding = max(needs, key=lambda c: abs(needs[c]))
    span = needs[binding]
    return {"solvable": True, "required_span": span,
            "direction": "increase" if span > 0 else "decrease",
            "binding_case": binding,
            "reason": None}


def pts_base(pts):
    return dict(pts)[0.0]


def _ls_slope(spans, vals):
    """원점(base) 기준 Δ의 최소제곱 기울기 — Δv ≈ slope·s."""
    b = dict(zip(spans, vals))[0.0]
    num = sum(s * (v - b) for s, v in zip(spans, vals) if s != 0.0)
    den = sum(s * s for s in spans if s != 0.0)
    return (num / den) if den > 0.0 else None


def slope_matrix(rows, knobs, metrics):
    """케이스별 기울기 행렬 S[case][metric][knob] (Δ지표/스팬) + 제외 목록.

    mixed는 행렬에서 **아예 뺀다**(0으로 두지 않는다 — 0은 "영향 없음"이라는
    다른 사실이다). 제외는 근거와 함께 기록해 화면이 말하게 한다.
    """
    S: dict = {}
    excluded = []
    seen_excl = set()
    for knob in knobs:
        for metric in metrics:
            by_case = _solo_points(rows, knob, metric)
            for case, pts in by_case.items():
                tr = _trend(pts)
                if tr == "mixed":
                    key = (knob, metric)
                    if key not in seen_excl:
                        seen_excl.add(key)
                        excluded.append({"knob": knob, "metric": metric,
                                         "reason": "스팬 안 경향 비단조 — 선형 모델에서 제외"})
                    continue
                slope = _ls_slope([p[0] for p in pts], [p[1] for p in pts])
                if slope is None:
                    continue
                S.setdefault(case, {}).setdefault(metric, {})[knob] = float(slope)
    return S, excluded


def solve_joint(rows, knobs, criteria: GainEvalCriteria, *,
                span_bound: float = 0.2) -> dict:
    """복수 손잡이 소폭 조합 — 하드 지표를 전 케이스에서 만족하는 최소 변화(min Σx²).

    선형 국소 모델(slope_matrix) 위의 SLSQP다. 결과는 **후보**다 — 합격 선언은
    확인 런(evaluate)의 몫이고, 비가산성(쌍 런)이 크면 경고가 그 신뢰도를 깎는다.
    """
    targets = _targets(criteria)
    metrics = [m for m, _t, _a in targets]
    S, excluded = slope_matrix(rows, knobs, metrics)
    bases: dict = {}
    for r in rows:
        if r["label"] == "base" and not r.get("aborted"):
            bases[r["case"]] = {m: _num((r.get("metrics") or {}).get(m))
                                for m in metrics}
    cases = [c for c in bases if c in S or all(
        v is not None for v in bases[c].values())]
    if not cases:
        return {"solvable": False, "spans": None, "excluded": excluded,
                "violated": [], "reason": "기준 런이 없다 — 스윕부터"}

    x0 = np.zeros(len(knobs))
    idx = {k: i for i, k in enumerate(knobs)}

    cons = []
    con_meta = []
    for case in cases:
        for metric, limit, above in targets:
            b = bases[case].get(metric)
            if b is None:
                continue  # 판정 불가 지표는 제약을 세우지 않는다 (0 위장 금지)
            srow = np.zeros(len(knobs))
            for knob, sl in (S.get(case, {}).get(metric, {}) or {}).items():
                srow[idx[knob]] = sl
            sign = -1.0 if above else 1.0  # above: limit − (b + s·x) ≥ 0
            cons.append({"type": "ineq",
                         "fun": (lambda x, b=b, srow=srow, limit=limit, sign=sign:
                                 sign * ((b + srow @ x) - limit))})
            con_meta.append((case, metric, b, srow, limit, above))

    res = minimize(lambda x: float(x @ x), x0, method="SLSQP",
                   bounds=[(-span_bound, span_bound)] * len(knobs),
                   constraints=cons,
                   options={"maxiter": 200, "ftol": 1e-12})

    x = res.x
    predicted = {}
    violated = []
    for case, metric, b, srow, limit, above in con_meta:
        v = float(b + srow @ x)
        predicted.setdefault(case, {})[metric] = v
        ok = v <= limit + 1e-9 if above else v >= limit - 1e-9
        if not ok:
            violated.append({"case": case, "metric": metric,
                             "predicted": v, "limit": limit})

    spans = {k: float(x[i]) for k, i in idx.items()}
    solvable = bool(res.success) and not violated
    return {
        "solvable": solvable,
        "spans": spans if solvable else spans,  # 실패해도 최선해를 근거로 남긴다
        "predicted": predicted,
        "excluded": excluded,
        "violated": violated,
        "reason": (None if solvable else
                   "선형 모델에서 하드 문턱을 전부 만족하는 해가 표본 스팬 안에 없다"
                   if violated else f"최적화 실패: {res.message}"),
        "span_bound": span_bound,
    }


def nonadditivity_warnings(payload, knobs, rel_floor: float = 0.2) -> list:
    """저장된 스윕의 쌍별 비가산성 → 선형 모델 신뢰 경고 문장들.

    |dAB − (dA+dB)|가 |dA|+|dB|의 rel_floor를 넘는 (쌍, 지표)만 — 차단이 아니라
    정보다(확인 런이 최종 판정자다).
    """
    out = []
    for na in payload.get("nonadditivity") or []:
        pair = na.get("knobs") or []
        if not set(pair) & set(knobs):
            continue
        for metric, v in (na.get("values") or {}).items():
            v = _num(v)
            if v is None or v == 0.0:
                continue
            out.append(f"{'·'.join(pair)}의 {metric} 비가산성 {v:+.3g} — 두 손잡이가 "
                       "상호작용한다: 조합 예측은 선형 근사이고 확인 런이 판정한다")
            break  # 쌍당 한 문장이면 충분
    return out


def proposal_shape(shape: Shape, spans: dict):
    """스팬 조합 → 제안 형상 (+클립 노트). 절대값 환산·클립 의미론은 sweep._value_at
    정본을 그대로 쓴다 — 스윕이 흔든 방식과 제안이 적용되는 방식이 갈리면 확인 런이
    다른 것을 확인한다."""
    universe = {r.id: r for r in param_universe(shape)}
    unknown = [k for k in spans if k not in universe]
    if unknown:
        raise ValueError(f"알 수 없는 파라미터 id: {unknown}")
    notes: list = []
    s2 = shape
    for knob, span in spans.items():
        v = _value_at(universe[knob], float(span), notes)
        if v is None:
            continue  # 클립으로 무의미 — notes가 사실을 든다
        s2 = apply_param(s2, universe[knob], float(v))
    return s2, notes


def proposal_export(shape2: Shape) -> dict:
    """제안 형상 → 웹 적용 페이로드 — {tables, constants}.

    tables는 배율이 **이미 곱힌** 실효 테이블(웹 gainTables 형식 그대로 — 적용은
    전체 교체 계약, gains 탭과 동일 경로)이고 constants는 fcl/* 덮어쓰기다.
    웹이 배율을 다시 곱하게 하면 같은 산술이 두 곳에 적힌다.
    """
    from claw.pipeline.influence import make_law

    law = make_law(shape2)
    tables = {}
    if law.schedule is not None:
        for name, t in law.schedule.tables.items():
            tables[name] = {
                "axes": {ax: [float(v) for v in vals]
                         for ax, vals in zip(t.axis_names, t.axes)},
                "data": np.asarray(t.data, dtype=float).tolist(),
            }
    return {
        "tables": tables or None,
        "constants": {"scas": {a: dict(v) for a, v in shape2.scas.items()},
                      "autopilot": dict(shape2.autopilot)},
    }
