"""정량 처방 — "어떤 설계변수를 **얼마나** 고쳐야 문턱을 넘는가" (02 §2.4의 마지막 조각).

진단(diagnose — 무엇을·어느 방향)과 스윕(sweep — 흔들면 얼마나 변하나) 위에
얹히는 세 번째 답이다: 저장된 스윕 행을 **다시 세워**(새 시뮬 없음) 단일 설계변수의
필요 변화량과 복수 설계변수의 최소 조합을 낸다. 확정은 언제나 실측 1회다 — 제안
형상(proposal_shape)을 evaluate()에 넣어 확인하는 것은 호출자(서버 라우트)의 몫.

**제안 생성기와 채점기의 분리가 계약이다**: 이 모듈은 후보(스팬 조합)를 만들 뿐
합격 판정은 하지 않는다 — 판정은 evaluate가 하고, 향후 복수 게인 조정 최적화기
(AI든 탐색이든)는 이 모듈을 갈아끼우고 evaluate를 그대로 쓴다.

외삽의 규율 (웹 trendMatrix와 같은 규칙 — lib/influence.js trendOf):
- 단조 판정은 **연속 차분의 부호**다. 스팬 안에 극점이 있는(mixed) 설계변수는
  "한쪽으로 밀면 안 된다"가 답이라 필요 변화량을 내지 않는다
- 표본 스팬(±20 %) 밖 교차는 참고 추정치만 내고 solvable=False를 유지한다 —
  "20 % 안에서 못 잡는다"는 사실을 흐리지 않는다
- 케이스마다 요구 방향이 갈리면 게인 수준이 아니라 **스케줄 셀** 문제다(국소) —
  단일 배율로 풀 수 없음을 사유로 낸다

조합 해(solve_joint)는 스윕 단독 런의 기울기 행렬(선형 국소 모델) 위에서
SLSQP(트림과 같은 방식 — 신규 의존 없음)로 하드 지표 제약을 만족하는 최소 변화
(min Σx²)를 찾는다. 쌍 런의 비가산성은 차단이 아니라 경고로 동봉한다 — 선형
모델의 신뢰도를 화면이 알게. objective="performance"는 같은 모델·같은 하드 제약 위에서
목적만 바꾼다 — 최소 수정 대신 성능 지표(추종 RMS·정착·오버슈트)를 줄인다. 선형 목적은
경계로 달리므로 경계를 스윕의 유효 표본까지로 줄이고(bound_limits) 평활항이 그 안쪽을
보조한다(04 §7.3).
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
    out.append(("de_dyn_reserve_min_frac", float(crit.authority.dyn_reserve_min_frac), False))
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
            continue  # 쌍 런·다른 설계변수 — 단독 귀속만 (웹 sweepKnobs와 같은 규칙)
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
    """저장된 스윕에서 설계변수 하나의 필요 변화량 — {"solvable", "required_span", …}.

    반환 스팬은 상대 변화(0.1 = +10 %, |값| 기준 — sweep._value_at과 같은 의미)다.
    전 결함 케이스를 고치는 값(방향 공통·크기 최댓값)이고, binding_case가 그 크기를
    정한 케이스다.
    """
    threshold = float(threshold)
    by_case = _solo_points(rows, knob, metric)
    if not by_case:
        return {"solvable": False, "required_span": None,
                "reason": "이 설계변수·지표의 단독 런이 없다 — 스윕이 흔든 적 없다"}

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
                    "reason": f"{case}: 이 설계변수는 이 지표를 사실상 안 움직인다(평탄)"}
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
                          "셀(국소) 문제다. 스캔의 국소성 판정과 대조할 것"}
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


# 「바뀐 게인」으로 세는 문턱 — 서버의 확인 런 생략(1e-6)보다 거칠다: 0.1 % 배율
# 변화는 스윕 표본(±10·20 %)의 선형 모델이 구분해 말할 수 있는 크기가 아니다
CHANGED_TOL = 1e-3

# 성능 목적의 기본 지표 — 추종 RMS·정착시간·오버슈트(04 §7.3 「추종오차·응답시간·
# 오버슈트」). 전부 influence.METRICS에서 lower다(테스트가 대조)
PERF_METRICS_DEFAULT = ("alt_rms", "spd_rms", "hdg_rms",
                        "alt_ts", "spd_ts", "hdg_ts",
                        "alt_mp", "spd_mp", "hdg_mp")
IMPROVEMENT_LOOPS = ("pitch_att", "roll_att", "spd_u", "pitch_rate", "roll_rate", "yaw_rate")
IMPROVEMENT_HIGHER_METRICS = (
    *(f"gm.{loop}" for loop in IMPROVEMENT_LOOPS),
    *(f"pm.{loop}" for loop in IMPROVEMENT_LOOPS),
    "zeta_sp", "zeta_dr", "roll_lambda",
)

# 정규화 바닥 — scale = max(|base|, floor). 단위가 다른 지표를 더하려면 상대 변화로
# 세야 하는데, base가 0 근처면(오버슈트 0 %·정착 즉시) 상대 변화가 폭발해 목적 전체를
# 그 한 항이 끌고 간다. 바닥은 「그 지표에서 의미 있는 최소 크기」다:
# RMS는 축 단위(m·m/s·rad)별 센서 잡음 수준, 정착·상승시간은 제어 주기보다 한참 큰
# 0.5 s, 오버슈트는 스텝 대비 1 %.
_PERF_FLOOR = {"alt_rms": 0.1, "spd_rms": 0.05, "hdg_rms": 0.002}
_PERF_FLOOR_BY_SUFFIX = {"_ts": 0.5, "_tr": 0.5, "_mp": 0.01}
# 표에 없는 lower 지표(sse·포화 지속 등)의 방어값 — 0 나눗셈만 막는다. 그 지표를
# 성능 목적에 넣는 호출자는 스케일이 base에 달린다는 것을 안고 넣는다
_PERF_FLOOR_FALLBACK = 1e-3

_BOUND_EPS = 1e-6
_NO_GAIN_TOL = 1e-9

_REASON_NONE = "판정 불가 — 기준 런에 값이 없다"
_REASON_INF = "창 안 미정착·발산 — 선형 모델 정의역 밖"
_REASON_MIXED = "비단조 — 스팬 안 경향이 뒤집혀 선형 모델에서 제외"
_REASON_NO_GAIN = "제약 안에서 성능을 더 낫게 하는 방향이 선형 모델에 없다"


def _perf_floor(metric: str) -> float:
    if metric in _PERF_FLOOR:
        return _PERF_FLOOR[metric]
    for suf, f in _PERF_FLOOR_BY_SUFFIX.items():
        if metric.endswith(suf):
            return f
    return _PERF_FLOOR_FALLBACK


def _state(v) -> str:
    """원시 지표값 → 'ok' | 'none' | 'inf'. _num은 둘 다 None으로 접는데, 성능 목적은
    「판정 불가」와 「미정착(느림의 극한)」을 다른 사유로 말해야 한다."""
    if v is None:
        return "none"
    if isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            return "none"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "none"
    if math.isnan(v):
        return "none"
    return "ok" if math.isfinite(v) else "inf"


def _check_perf_args(perf_metrics, perf_weights, smooth_weight):
    from claw.pipeline.influence import METRICS

    better = {m.key: m.better for m in METRICS}
    pm = list(PERF_METRICS_DEFAULT if perf_metrics is None else perf_metrics)
    if not pm:
        raise ValueError("perf_metrics가 비었다")
    for m in pm:
        if m not in better:
            raise ValueError(f"알 수 없는 성능 지표: {m}")
        # higher 지표는 받지 않는다 — 부호 뒤집기로 받으면 「실속 여유를 키우는 것이
        # 성능」이 되는데, 여유류는 목적이 아니라 제약(하드 문턱)의 자리다
        if better[m] != "lower":
            raise ValueError(f"성능 지표는 lower만 받는다 ({m}은 higher) — "
                             "여유류는 목적이 아니라 하드 제약이다")
    w = {m: 1.0 for m in pm}
    for k, v in (perf_weights or {}).items():
        if k not in w:
            raise ValueError(f"perf_weights에 성능 지표가 아닌 키: {k} (지표: {pm})")
        v = float(v)
        if not (math.isfinite(v) and v >= 0.0):
            raise ValueError(f"perf_weights[{k}]는 0 이상 유한값이어야 한다: {v}")
        w[k] = v
    # 가중이 전부 0이면 남는 것은 평활항뿐 — 답은 늘 「안 바꾼다」라 목적이 없다(웹 objectiveFields와 같은 거절)
    if not any(v > 0.0 for v in w.values()):
        raise ValueError("perf_weights가 전부 0 — 줄일 성능 목적이 없다")
    sw = float(smooth_weight)
    if not (math.isfinite(sw) and sw >= 0.0):
        raise ValueError(f"smooth_weight는 0 이상 유한값이어야 한다: {sw}")
    return pm, w, sw


def _changed(knobs, spans):
    ch = [k for k in knobs if abs(spans.get(k, 0.0)) > CHANGED_TOL]
    return {"changed_knobs": ch, "changed_count": len(ch)}


def perf_compare(base_metrics: dict, new_metrics: dict,
                 perf_metrics=PERF_METRICS_DEFAULT) -> dict:
    """확인 런 대 기준 런의 성능 지표 비교 — {metric: {base, new, delta_frac, …}}.

    delta_frac = (new − base)/max(|base|, floor) — 목적함수와 같은 정규화라 화면이
    예측(perf_predicted)과 실측을 같은 자로 잰다. 한쪽이라도 비유한이면 None이고,
    base_state·new_state('ok'|'none'|'inf')가 「판정 불가」와 「미정착」을 가른다.
    """
    base_metrics = base_metrics or {}
    new_metrics = new_metrics or {}
    out = {}
    for m in perf_metrics:
        rb, rn = base_metrics.get(m), new_metrics.get(m)
        b, n = _num(rb), _num(rn)
        d = None
        if b is not None and n is not None:
            d = (n - b) / max(abs(b), _perf_floor(m))
        out[m] = {"base": b, "new": n, "delta_frac": d,
                  "base_state": _state(rb), "new_state": _state(rn)}
    return out


def _hard_constraints(cases, targets, bases, S, idx, n, *, with_jac=False):
    """하드 지표 선형 제약 — min_change·performance 공통 (같은 부등식·같은 판정).

    with_jac: 해석 야코비안 동봉 — performance만 켠다. min_change는 종전 수치 미분
    그대로 둬야 서버 골든이 한 자리도 안 바뀐다."""
    cons, meta = [], []
    for case in cases:
        for metric, limit, above in targets:
            b = bases[case].get(metric)
            if b is None:
                continue  # 판정 불가 지표는 제약을 세우지 않는다 (0 위장 금지)
            srow = np.zeros(n)
            for knob, sl in (S.get(case, {}).get(metric, {}) or {}).items():
                srow[idx[knob]] = sl
            sign = -1.0 if above else 1.0  # above: limit − (b + s·x) ≥ 0
            con = {"type": "ineq",
                   "fun": (lambda x, b=b, srow=srow, limit=limit, sign=sign:
                           sign * ((b + srow @ x) - limit))}
            if with_jac:
                con["jac"] = (lambda x, srow=srow, sign=sign: sign * srow)
            cons.append(con)
            meta.append((case, metric, b, srow, limit, above))
    return cons, meta


def _judge(meta, x):
    predicted, violated = {}, []
    for case, metric, b, srow, limit, above in meta:
        v = float(b + srow @ x)
        predicted.setdefault(case, {})[metric] = v
        ok = v <= limit + 1e-9 if above else v >= limit - 1e-9
        if not ok:
            violated.append({"case": case, "metric": metric,
                             "predicted": v, "limit": limit})
    return predicted, violated


def _pct(s: float) -> str:
    return f"{s * 100:+.3g} %"


def _solo_rows(rows, knob):
    """단독 런 행 {case: {스팬: 행}} — 중단 행도 **남긴다**(경계 판정이 「발산」을 말해야 한다).
    귀속·스팬 파싱은 _solo_points와 같은 규칙."""
    out: dict = {}
    for r in rows:
        if r.get("label") == "base":
            continue
        if list((r.get("overrides") or {}).keys()) != [knob]:
            continue
        label = r.get("label") or ""
        if "@" not in label:
            continue
        try:
            s = float(label.rsplit("@", 1)[1])
        except ValueError:
            continue
        out.setdefault(r["case"], {})[s] = r
    return out


def _sample_fault(row, used):
    """표본 행 하나가 선형 모델의 근거가 될 수 있나 — 안 되면 사유, 되면 None."""
    if row is None:
        return "없음(취소·미수렴)"
    if row.get("aborted"):
        return "발산으로 중단"
    rm = row.get("metrics") or {}
    bad = {"inf": [], "none": []}
    for m in sorted(used):
        st = _state(rm.get(m))
        if st != "ok":
            bad[st].append(m)
    if bad["inf"]:
        return f"미정착({', '.join(bad['inf'])})"
    if bad["none"]:
        return f"판정 불가({', '.join(bad['none'])})"
    return None


def _perf_bounds(rows, knobs, cases, used, span_bound, unmodelled):
    """성능 목적의 설계변수별 탐색 경계 — 스윕이 **실제로 재어 본** 자리까지만.

    선형 목적은 늘 경계로 달린다. 경계가 ±span_bound 고정이면 ① 스윕이 ±0.1만 흔들었을 때
    2배 외삽이 되고 ② 경계 표본이 미정착(inf)·발산(중단)이었으면 _solo_points가 그 행을 조용히
    버린 채 「스윕이 실패로 본 게인」을 제안한다. 그래서 0에서 바깥으로 걸으며 **전 케이스에서**
    행이 있고·안 잘렸고·쓰는 지표(하드 제약 + 성능 항)가 전부 유한한 표본까지만 믿는다(첫 불량
    표본에서 멈춘다 — 불량 너머의 양호 표본은 사이를 보증하지 못한다). 하드 지표가 비단조인
    설계변수는 선형 모델이 그 지표를 0 기울기로 보므로, 가장 작은 표본 스팬 너머를 믿지 않는다.

    반환: (bounds [(lo, hi)…], bound_limits {knob: {lo, hi, reason?}}, 사람용 사유 목록).
    """
    bounds, limits, reasons = [], {}, []
    for knob in knobs:
        by_case = _solo_rows(rows, knob)
        sampled = sorted({s for c in cases for s in by_case.get(c, {})})
        lims, why = {}, []
        for side in (+1, -1):
            side_spans = sorted((s for s in sampled if s * side > 0), key=abs)
            lim = 0.0
            fault = None
            for s in side_spans:
                for c in cases:
                    f = _sample_fault(by_case.get(c, {}).get(s), used.get(c, ()))
                    if f:
                        fault = (s, c, f)
                        break
                if fault:
                    break
                lim = min(abs(s), span_bound)
                if lim >= span_bound:
                    break
            if fault:
                s, c, f = fault
                tail = (f"탐색을 {_pct(side * lim)}로 줄였다" if lim > 0.0
                        else "그쪽으로는 움직이지 않는다")
                why.append(f"{_pct(s)} 표본이 {f}@{c} — {tail}")
            elif not side_spans:
                why.append(f"{'+' if side > 0 else '-'}쪽 표본이 없다 — 그쪽으로는 움직이지 않는다")
            elif lim < span_bound:
                why.append(f"표본이 {_pct(side * lim)}까지뿐 — 밖은 외삽이라 탐색을 "
                           f"{_pct(side * lim)}로 줄였다")
            ms = unmodelled.get(knob)
            if ms:
                smallest = abs(side_spans[0]) if side_spans else 0.0
                if smallest < lim:
                    lim = smallest
                    why.append(f"하드 지표 {', '.join(ms)} 경향이 비단조(선형 모델이 0 기울기로 본다) — "
                               f"믿을 수 있는 최소 표본 {_pct(side * lim)}로 줄였다")
            lims[side] = lim
        lo, hi = (-lims[-1] if lims[-1] else 0.0), lims[+1]
        bounds.append((lo, hi))
        rec = {"lo": lo, "hi": hi}
        if why:
            rec["reason"] = " · ".join(why)
            reasons.extend(f"{knob}: {w}" for w in why)
        limits[knob] = rec
    return bounds, limits, reasons


def solve_joint(rows, knobs, criteria: GainEvalCriteria, *,
                span_bound: float = 0.2, metrics=None,
                objective: str = "min_change", perf_metrics=None,
                perf_weights=None, smooth_weight: float = 0.1,
                goal_limits=None, knob_bounds=None) -> dict:
    """복수 설계변수 소폭 조합 — 선형 국소 모델(slope_matrix) 위의 SLSQP.

    objective:
    - "min_change" — 하드 지표를 전 케이스에서 만족하는 최소 변화(min Σx²).
      「기준을 넘기는 최소 수정」이지 가장 좋은 설계가 아니다.
    - "performance" — 하드 문턱을 전부 지키며 성능 지표(lower)를 줄인다:
      J(x) = Σ_(case,m) w_m·(b + S·x)/scale / Σw + smooth_weight·Σ(x/span_bound)²
      (앞 항은 정규화 지표의 가중 평균 — smooth_weight의 뜻이 지표 수·가중에 무관하다).
      선형 목적은 늘 경계로 달리므로 경계는 스윕이 실제로 재어 본 유효 표본까지로 줄이고
      (bound_limits — 미정착·발산 표본 너머와 표본 밖 외삽은 탐색하지 않는다), 평활항이
      그 안쪽의 보조 목적이다. bound_active가 그 실제 경계에서 멈춘 게인을 든다.

    결과는 **후보**다 — 합격 선언은 확인 런(evaluate)의 몫이고, 비가산성(쌍 런)이
    크면 경고가 그 신뢰도를 깎는다. 바뀐 게인 수(changed_count)는 최소화 대상이
    아니라 결과 정보다.

    metrics: min_change에서만 풀 지표를 좁힌다(평가가 실패라고 한 것만 — 승계).
    None이면 기준의 하드 지표 전부. 통과한 지표까지 제약으로 세우면 이미 만족하는
    부등식이 해를 좁혀 "고칠 수 있는데 못 고친다"가 나올 수 있다.
    **performance는 metrics를 무시하고 하드 지표 전부를 제약으로 세운다** — 성능을
    밀면 통과하던 지표가 넘어갈 수 있고, 성능 설계는 모든 하드 기준을 지켜야 한다.
    """
    if objective not in ("min_change", "performance"):
        raise ValueError(f"objective는 'min_change'|'performance': {objective!r}")
    perf = objective == "performance"
    if perf:
        pm, weights, sw = _check_perf_args(perf_metrics, perf_weights, smooth_weight)

    targets = _targets(criteria)
    for metric, limit in (goal_limits or {}).items():
        if metric not in (*PERF_METRICS_DEFAULT, *IMPROVEMENT_HIGHER_METRICS) or not math.isfinite(limit) or limit < 0:
            raise ValueError(f"지원하지 않는 목표: {metric}={limit}")
        targets.append((metric, float(limit), metric not in IMPROVEMENT_HIGHER_METRICS))
    if metrics and not perf:
        want = set(metrics)
        focused = [t for t in targets if t[0] in want]
        if focused:
            targets = focused
    metrics = [m for m, _t, _a in targets]
    hard_set = set(metrics)
    all_metrics = metrics + ([m for m in pm if m not in hard_set] if perf else [])
    S, excluded_all = slope_matrix(rows, knobs, all_metrics)
    excluded = [e for e in excluded_all if e["metric"] in hard_set]
    bases: dict = {}
    raw_bases: dict = {}
    for r in rows:
        if r["label"] == "base" and not r.get("aborted"):
            rm = r.get("metrics") or {}
            bases[r["case"]] = {m: _num(rm.get(m)) for m in metrics}
            raw_bases[r["case"]] = rm
    cases = [c for c in bases if c in S or all(
        v is not None for v in bases[c].values())]
    if not cases:
        out = {"solvable": False, "spans": None, "excluded": excluded,
               "violated": [], "reason": "기준 런이 없다 — 스윕부터",
               "objective": objective, "changed_knobs": [], "changed_count": 0}
        return out

    n = len(knobs)
    x0 = np.zeros(n)
    idx = {k: i for i, k in enumerate(knobs)}
    bounds = [(-span_bound, span_bound)] * n
    if knob_bounds:
        bounds = [tuple(knob_bounds.get(k, b)) for k, b in zip(knobs, bounds)]
    cons, con_meta = _hard_constraints(cases, targets, bases, S, idx, n, with_jac=perf)

    if not perf:
        res = minimize(lambda x: float(x @ x), x0, method="SLSQP",
                       bounds=bounds, constraints=cons,
                       options={"maxiter": 200, "ftol": 1e-12})
        x = res.x
        predicted, violated = _judge(con_meta, x)
        spans = {k: float(x[i]) for k, i in idx.items()}
        solvable = bool(res.success) and not violated
        return {
            "solvable": solvable,
            "spans": spans,  # 실패해도 최선해를 근거로 남긴다
            "predicted": predicted,
            "excluded": excluded,
            "violated": violated,
            "reason": (None if solvable else
                       "선형 모델에서 하드 문턱을 전부 만족하는 해가 표본 스팬 안에 없다"
                       if violated else f"최적화 실패: {res.message}"),
            "span_bound": span_bound,
            "objective": objective,
            **_changed(knobs, spans),
        }

    # ── 성능 목적 ──
    perf_excluded = []
    seen = set()

    def _drop(metric, case, reason, **extra):
        key = (metric, case, reason)
        if key in seen:
            return
        seen.add(key)
        perf_excluded.append({"metric": metric, "case": case, "reason": reason, **extra})

    # 비단조는 케이스 무관으로 지표째 뺀다 — 어느 게인이든 그 지표에서 경향이 뒤집히면
    # 선형 목적이 그 방향으로 경계까지 밀어 「극점 너머」를 개선이라 부르게 된다
    mixed = {}
    for e in excluded_all:
        if e["metric"] in pm:
            mixed.setdefault(e["metric"], []).append(e["knob"])
    for m in pm:
        if m in mixed:
            _drop(m, None, _REASON_MIXED, knobs=mixed[m])
    terms = []  # (case, metric, b, srow, scale, w)
    for case in cases:
        rm = raw_bases[case]
        for m in pm:
            if m in mixed:
                continue
            st = _state(rm.get(m))
            if st == "none":
                _drop(m, case, _REASON_NONE)
                continue
            if st == "inf":
                _drop(m, case, _REASON_INF)
                continue
            b = _num(rm.get(m))
            srow = np.zeros(n)
            for knob, sl in (S.get(case, {}).get(m, {}) or {}).items():
                srow[idx[knob]] = sl
            terms.append((case, m, b, srow, max(abs(b), _perf_floor(m)), weights[m]))

    # 하드 지표 비단조(선형 모델이 그 제약을 0 기울기로 본다) — 성능 목적은 경계로 달리므로
    # 그 지표가 경계에서 넘어가도 모델은 모른다. 경고로 들고 경계를 가장 작은 표본까지 줄인다
    unmodelled: dict = {}
    hard_unmodelled = []
    for e in excluded:
        unmodelled.setdefault(e["knob"], []).append(e["metric"])
        hard_unmodelled.append({"knob": e["knob"], "metric": e["metric"]})

    common = {"objective": objective, "perf_metrics": pm, "perf_weights": weights,
              "smooth_weight": sw, "perf_excluded": perf_excluded,
              "excluded": excluded, "hard_unmodelled": hard_unmodelled,
              "span_bound": span_bound}
    w_sum = sum(t[5] for t in terms)
    if not terms or w_sum <= 0.0:
        return {**common, "solvable": False, "spans": None, "predicted": {},
                "violated": [], "perf_predicted": {}, "objective_value": None,
                "bound_active": [], "bound_limits": {}, "bound_reasons": [],
                "changed_knobs": [], "changed_count": 0,
                "reason": ("성능 목적 지표가 하나도 선형 모델에 들지 않는다" if not terms else
                           "선형 모델에 든 성능 지표의 가중이 전부 0 — 줄일 목적이 없다")}

    # 탐색 경계 — 케이스별로 **쓰는** 지표(세운 하드 제약 + 성능 항)가 표본에서 유한해야 한다
    used: dict = {}
    for case, _metric, *_r in con_meta:
        used.setdefault(case, set()).add(_metric)
    for case, m, *_r in terms:
        used.setdefault(case, set()).add(m)
    bounds, bound_limits, bound_reasons = _perf_bounds(
        rows, knobs, cases, used, span_bound, unmodelled)
    if knob_bounds:
        bounds = [(max(b[0], knob_bounds.get(k, b)[0]), min(b[1], knob_bounds.get(k, b)[1]))
                  for k, b in zip(knobs, bounds)]
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])

    # 목적은 Σw로 정규화한다 — J = Σ_t w·(b + S·x)/scale / Σw + sw·Σ(x/span_bound)².
    # 앞 항은 「정규화 지표의 가중 평균」(기준 형상에서 ≈1)이라 평활 가중 sw가 지표 수·가중
    # 크기와 무관하게 같은 뜻이다. 케이스 평균도 겸한다(항 수가 다른 케이스는 항 수만큼 무겁다).
    # 평활 척도는 줄인 경계가 아니라 span_bound — 경계가 바뀌어도 sw의 뜻이 안 바뀌게
    c0 = sum(w * b / sc for _c, _m, b, _s, sc, w in terms) / w_sum
    g = sum(w * srow / sc for _c, _m, _b, srow, sc, w in terms) / w_sum
    k2 = sw / (span_bound * span_bound)

    def fun(x):
        return float(c0 + g @ x + k2 * (x @ x))

    def jac(x):
        return g + 2.0 * k2 * x

    res = minimize(fun, x0, jac=jac, method="SLSQP", bounds=list(bounds),
                   constraints=cons, options={"maxiter": 200, "ftol": 1e-12})
    x = np.clip(res.x, lo, hi)
    _p0, viol0 = _judge(con_meta, x0)
    _p1, viol1 = _judge(con_meta, x)
    reason = None
    trusted = bool(res.success)
    if not viol0 and (viol1 or not trusted):
        # 기준 형상(0 변화)이 이미 하드를 지키는데 최적화가 위반해·실패를 냈다 — 수치 실패다.
        # x0가 실현 가능하다는 것은 방금 판정했으니 「못 푼다」가 아니라 「안 바꾼다」가 답이다
        x = np.zeros(n)
        trusted = True
        reason = (f"최적화가 하드 제약을 지키는 개선해를 못 냈다({res.message}) — "
                  "기준 형상이 이미 하드를 지키므로 0 변화로 둔다")
    j_pred = float(c0 + g @ x)
    # 개선이 없으면 0 변화 — 단 기준 런이 이미 하드를 지킬 때만: 기준이 위반이면
    # 0은 해가 아니고 제약이 요구한 변화(성능 손해를 감수한)가 답이다
    if reason is None and not viol0 and j_pred >= c0 - _NO_GAIN_TOL:
        x = np.zeros(n)
        j_pred = c0
        reason = _REASON_NO_GAIN
    predicted, violated = _judge(con_meta, x)
    spans = {k: float(x[i]) for k, i in idx.items()}
    solvable = trusted and not violated
    if reason is None and not solvable:
        reason = ("선형 모델에서 하드 문턱을 전부 만족하는 해가 표본 스팬 안에 없다"
                  if violated else f"최적화 실패: {res.message}")
    perf_predicted: dict = {}
    for case, m, b, srow, sc, _w in terms:
        v = float(b + srow @ x)
        perf_predicted.setdefault(case, {})[m] = {
            "base": b, "predicted": v, "delta_frac": (v - b) / sc}
    # 경계에 닿은 설계변수 — 실제 경계(bound_limits) 기준. 경계가 0인 쪽은 x=0이 곧 경계라
    # 목적 기울기가 그쪽을 가리킬 때만 든다(「가고 싶었는데 표본이 막았다」)
    grad = g + 2.0 * k2 * x
    active = []
    for k, i in idx.items():
        at_hi = (hi[i] > 0.0 and x[i] >= hi[i] - _BOUND_EPS) or (
            hi[i] == 0.0 and abs(x[i]) <= _BOUND_EPS and grad[i] < -_NO_GAIN_TOL)
        at_lo = (lo[i] < 0.0 and x[i] <= lo[i] + _BOUND_EPS) or (
            lo[i] == 0.0 and abs(x[i]) <= _BOUND_EPS and grad[i] > _NO_GAIN_TOL)
        if at_hi or at_lo:
            active.append(k)
    if reason == _REASON_NO_GAIN and active:
        reason = "개선 방향이 있으나 탐색 경계(스윕 표본)가 막았다 — 0 변화. 사유는 bound_reasons"
    return {
        **common,
        "solvable": solvable,
        "spans": spans,
        "predicted": predicted,
        "violated": violated,
        "reason": reason,
        # 전부 정규화 척도(Σw로 나눈 가중 평균) — base·predicted는 성능 항, smoothing은 평활항
        "objective_value": {"base": float(c0), "predicted": j_pred,
                            "smoothing": float(k2 * (x @ x))},
        "perf_predicted": perf_predicted,
        "bound_active": active,
        "bound_limits": bound_limits,
        "bound_reasons": bound_reasons,
        **_changed(knobs, spans),
    }


# ── 단계화 처방 (04 §7.3 — v1.93) ─────────────────────────────────────────────
# 실패 지표를 두 층으로 가른다. hard = 평가의 하드 게이트가 지목한 지표(≤ 한계, 제약), goal = 국소성
# 판정이 나쁜 주의 지표(제약이 아니라 목표). 종전에는 goal까지 하드 제약으로 넣어, 기준 설계에서도 이미
# 한계 밖인 지표(예: alt_rms > 10)가 있으면 조합 해가 늘 불가능 → x≈0 → 「바뀐 게인 0개」가 되고 그 사실이
# 화면에 안 나왔다. 이제는 ① hard만 ② hard + goal 한계 안 ③ (②가 안 되면) hard + goal 「퇴행 금지 + 개선
# 목적」 순서로 풀고, 각 단계가 풀리는지와 「얼마나 모자라는가(best_reachable)」를 feasibility로 싣는다.

# 안의 층 — 작을수록 앞선다. goal: 목표 지표까지 전부 한계 안 / nonregress: 하드는 만족, 한계 밖 목표 지표는
# 기준값보다 나빠지지 않음(한계 안 목표 지표는 한계 유지) / hard: 하드만 만족(목표 지표 퇴행을 감수 — 앞 두 층이
# 전부 안 풀릴 때만 나온다) / hard_boundary: 선형 모델로는 하드도 못 맞춘다 — 탐색 상자 안에서 하드 부족분을 가장
# 줄이는 경계 해(대개 탐색 한계에 붙는다). 선형 모델은 길잡이이고 판정자는 비선형 확인 런이라, 「모델 예측 미달」을
# 숨기지 않은 채 확인 런에 올린다(v1.87까지 k_hdot 시연이 바로 이 해로 확인 PASS였다)
TIER_RANK = {"goal": 0, "nonregress": 1, "hard": 2, "hard_boundary": 3}
TIER_LABEL = {"goal": "목표까지 충족", "nonregress": "하드 충족·목표 퇴행 금지", "hard": "하드만 충족(목표 퇴행 감수)",
              "hard_boundary": "모델 예측 미달 — 확인 런으로 판정"}

# 하드 층의 기본 — _targets 중 evaluate 하드 게이트(HARD_CHECKS)가 실제로 판정하는 지표. 추종 RMS는 하드 게이트가
# 아니라(evaluate는 RMS로 Fail을 내지 않는다) 기본 목표 층이다. 서버 _HARD_CHECK_METRICS(검사 이름 → 지표)의 값과 같은 집합
HARD_GATE_METRICS = ("surf_sat_frac", "worst_stall_margin", "de_dyn_reserve_min_frac")

# 개선 목적의 평활 가중 — 성능 목적(smooth_weight 기본 0.1)과 같은 뜻: 선형 개선항은 늘 경계로 달리므로
# Σ(x/span_bound)²가 안쪽 해를 고른다
_GOAL_SMOOTH = 0.1
# 순위의 「목표 개선량」 비교 눈금 — 정규화 변화 1 %p보다 작은 차이는 같은 개선으로 보고 게인 수·변화 크기로 가른다
# (선형 모델이 그보다 잘게 말할 수 없다)
_SCORE_QUANTUM = 0.01
# 부분집합 전수 열거의 풀 상한 — 넘으면 기울기 민감도 상위만 남긴다(04 §7.3)
MAX_FULL_POOL = 8


def _passes(v, limit, above):
    return v <= limit + 1e-9 if above else v >= limit - 1e-9


def _tier_model(rows, knobs, criteria, hard_metrics, goal_metrics):
    """단계화 풀이의 공통 재료 — 하드·목표 항목(케이스×지표)의 기준값·기울기·한계.

    hard_metrics가 None이면 하드 게이트 지표(HARD_GATE_METRICS) 중 목표로 지정되지 않은 것, goal_metrics가
    None이면 하드 층에 들지 않은 나머지 기준 지표 전부(추종 RMS) — 승계(평가 결과) 없이 부를 때의 기본값이다.
    """
    targets = {m: (lim, above) for m, lim, above in _targets(criteria)}
    goal_set = set(goal_metrics or ())
    if hard_metrics is None:
        hard = [m for m in targets if m in HARD_GATE_METRICS and m not in goal_set]
    else:
        want = set(hard_metrics)
        hard = [m for m in targets if m in want]
    if goal_metrics is None:
        goal = [m for m in targets if m not in hard]
    else:
        goal = [m for m in targets if m in goal_set and m not in hard]
    metrics = hard + goal
    S, excluded = slope_matrix(rows, knobs, metrics)
    bases: dict = {}
    for r in rows:
        if r["label"] == "base" and not r.get("aborted"):
            rm = r.get("metrics") or {}
            bases[r["case"]] = {m: _num(rm.get(m)) for m in metrics}
    cases = [c for c in bases if c in S or all(v is not None for v in bases[c].values())]
    idx = {k: i for i, k in enumerate(knobs)}
    n = len(knobs)

    def entries(ms):
        out = []
        for case in cases:
            for m in ms:
                b = bases[case].get(m)
                if b is None:
                    continue  # 판정 불가 지표는 제약도 목표도 세우지 않는다 (0 위장 금지)
                lim, above = targets[m]
                srow = np.zeros(n)
                for knob, sl in (S.get(case, {}).get(m, {}) or {}).items():
                    srow[idx[knob]] = sl
                out.append({"case": case, "metric": m, "b": b, "srow": srow,
                            "limit": lim, "above": above, "inside": _passes(b, lim, above)})
        return out

    return {"knobs": list(knobs), "idx": idx, "n": n, "cases": cases,
            "hard_metrics": hard, "goal_metrics": goal,
            "hard": entries(hard), "goal": entries(goal), "excluded": excluded}


def _box(model, span_bound, knob_bounds=None, active=None):
    """설계변수별 탐색 상자 — active 밖(이 안에 안 쓰는 게인)은 (0, 0)에 묶는다."""
    out = []
    for k in model["knobs"]:
        if active is not None and k not in active:
            out.append((0.0, 0.0))
            continue
        out.append(tuple((knob_bounds or {}).get(k, (-span_bound, span_bound))))
    return out


def _best_reachable(e, bounds):
    """그 항목 하나만 최선으로 민 예측값 — 선형 모델이라 상자 꼭짓점이 답이다(「얼마나 모자라나」)."""
    v = e["b"]
    for s, (lo, hi) in zip(e["srow"], bounds):
        pick = min if e["above"] else max
        v += pick(s * lo, s * hi)
    return float(v)


def _scale(e):
    return max(abs(e["b"]), _perf_floor(e["metric"]))


def _improve_terms(model):
    """개선 목적 항 — 기준에서 이미 한계 밖인 목표 항목(정규화, 낮을수록 좋게 부호를 맞춘다)."""
    return [e for e in model["goal"] if not e["inside"]]


def _score(model, x):
    """목표 개선량 — 한계 밖 목표 항목의 정규화 예측 변화 평균(음수 = 개선). 대상이 없으면 0."""
    terms = _improve_terms(model)
    if not terms:
        return 0.0
    tot = 0.0
    for e in terms:
        d = float(e["srow"] @ x) / _scale(e)
        tot += d if e["above"] else -d
    return tot / len(terms)


def _solve_tier(model, tier, bounds, span_bound):
    """한 층의 규칙으로 풀기 — (x, feasible, message).

    goal: 하드 + 목표 ≤ 한계, min Σx². nonregress: 하드 + 한계 안 목표는 한계 유지 + 한계 밖 목표는 기준값
    유지(퇴행 금지), 목적은 개선량 + 평활. hard: 하드만, min Σx².
    """
    n = model["n"]
    cons_rows = [(e, e["limit"]) for e in model["hard"]]
    if tier == "goal":
        cons_rows += [(e, e["limit"]) for e in model["goal"]]
    elif tier == "nonregress":
        cons_rows += [(e, e["limit"] if e["inside"] else e["b"]) for e in model["goal"]]
    cons = []
    for e, rhs in cons_rows:
        sign = -1.0 if e["above"] else 1.0
        cons.append({"type": "ineq",
                     "fun": (lambda x, b=e["b"], srow=e["srow"], rhs=rhs, sign=sign:
                             sign * ((b + srow @ x) - rhs)),
                     "jac": (lambda x, srow=e["srow"], sign=sign: sign * srow)})
    terms = _improve_terms(model) if tier == "nonregress" else []
    g = np.zeros(n)
    for e in terms:
        g += (e["srow"] / _scale(e)) * (1.0 if e["above"] else -1.0)
    if terms:
        g /= len(terms)
    k2 = (_GOAL_SMOOTH / (span_bound * span_bound)) if terms else 1.0

    def fun(x):
        return float(g @ x + k2 * (x @ x))

    def jac(x):
        return g + 2.0 * k2 * x

    x0 = np.zeros(n)
    res = minimize(fun, x0, jac=jac, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 200, "ftol": 1e-12})
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    x = np.clip(res.x, lo, hi)
    ok = all(_passes(float(e["b"] + e["srow"] @ x), rhs, e["above"]) for e, rhs in cons_rows)
    return x, bool(ok), str(res.message)


def _metric_word(above):
    return ("아래로 못 내려간다", "위로 못 올라간다")[0 if above else 1]


def _tier_violations(model, entries, x, bounds):
    out = []
    for e in entries:
        v = float(e["b"] + e["srow"] @ x)
        if not _passes(v, e["limit"], e["above"]):
            out.append({"metric": e["metric"], "case": e["case"], "base": e["b"],
                        "limit": e["limit"], "predicted": v, "above_is_bad": e["above"],
                        "best_reachable": _best_reachable(e, bounds)})
    return out


def _unmet_reason(violated, range_text, what):
    """「못 맞춤」 사유 — 지표마다 한 문장. 그 지표 하나만 최선으로 밀어도 한계에 못 닿는 케이스가 있으면
    그 최선값과 케이스를(가장 모자란 케이스), 따로는 닿는데 함께는 안 되면 그 사실을 말한다."""
    by: dict = {}
    for v in violated:
        by.setdefault(v["metric"], []).append(v)
    parts = []
    for m, vs in by.items():
        short = [v for v in vs if not _passes(v["best_reachable"], v["limit"], v["above_is_bad"])]
        if short:
            worst = max(short, key=lambda v: abs(v["best_reachable"] - v["limit"]))
            parts.append(f"{m}는 탐색 범위({range_text}) 안 어떤 조합으로도 {worst['limit']:g} "
                         f"{_metric_word(worst['above_is_bad'])}(최선 {worst['best_reachable']:.3g} "
                         f"@{worst['case']})")
        else:
            parts.append(f"{m}는 케이스마다 따로는 닿지만 {what}과 함께 전 케이스를 한계 안에 넣는 조합이 "
                         f"탐색 범위({range_text}) 안에 없다")
    return " · ".join(parts)


def _feasibility(model, bounds, span_bound, range_text):
    """단계 ①·② — hard만, hard + goal 한계 안. {hard, goal, reason, mode}."""
    xh, ok_h, msg_h = _solve_tier(model, "hard", bounds, span_bound)
    hard = {"solvable": ok_h, "violated": [] if ok_h else _tier_violations(model, model["hard"], xh, bounds),
            "metrics": list(model["hard_metrics"])}
    goal = {"solvable": None, "violated": [], "metrics": list(model["goal_metrics"]),
            "nonregress_solvable": None}
    reason = None
    mode = None
    if not ok_h:
        reason = (_unmet_reason(hard["violated"], range_text, "다른 하드 지표") if hard["violated"]
                  else f"하드 풀이 실패: {msg_h}")
    elif not model["goal"]:
        goal["solvable"] = True
        mode = "goal"
    else:
        xg, ok_g, _m = _solve_tier(model, "goal", bounds, span_bound)
        goal["solvable"] = ok_g
        mode = "goal" if ok_g else "nonregress"
        if not ok_g:
            goal["violated"] = _tier_violations(model, model["goal"], xg, bounds)
            reason = _unmet_reason(goal["violated"], range_text, "하드 기준")
    # 지표별 한계·방향·층 — 화면이 안의 예측값을 한계와 같은 자로 읽는다(방향을 웹에서 다시 정하지 않는다)
    limits = {}
    for tier, es in (("hard", model["hard"]), ("goal", model["goal"])):
        for e in es:
            limits.setdefault(e["metric"], {"limit": e["limit"], "above_is_bad": e["above"], "tier": tier})
    return {"hard": hard, "goal": goal, "reason": reason, "mode": mode, "span_bound": span_bound,
            "limits": limits}


def _range_text(span_bound, knob_bounds):
    return "설계변수별 경계" if knob_bounds else f"±{span_bound * 100:g} %"


def _plan_of(model, tier, x, active_knobs, bounds):
    """풀린 해 → 안 하나. spans는 쓴 게인만, predicted는 하드·목표 항목 전부(케이스×지표)."""
    spans = {k: float(x[model["idx"][k]]) for k in active_knobs}
    predicted: dict = {}
    unmet, regressed = [], []
    for e in model["hard"] + model["goal"]:
        v = float(e["b"] + e["srow"] @ x)
        predicted.setdefault(e["case"], {})[e["metric"]] = v
    for e in model["goal"]:
        v = predicted[e["case"]][e["metric"]]
        if not _passes(v, e["limit"], e["above"]):
            unmet.append({"metric": e["metric"], "case": e["case"], "base": e["b"],
                          "limit": e["limit"], "predicted": v,
                          "best_reachable": _best_reachable(e, bounds)})
        if not _passes(v, e["b"], e["above"]):
            regressed.append({"metric": e["metric"], "case": e["case"], "base": e["b"], "predicted": v})
    ch = _changed(model["knobs"], spans)
    max_pct = max((abs(spans[k]) * 100.0 for k in ch["changed_knobs"]), default=0.0)
    hard_unmet = [{"metric": e["metric"], "case": e["case"], "base": e["b"], "limit": e["limit"],
                   "predicted": predicted[e["case"]][e["metric"]], "best_reachable": _best_reachable(e, bounds)}
                  for e in model["hard"] if not _passes(predicted[e["case"]][e["metric"]], e["limit"], e["above"])]
    return {"knobs": ch["changed_knobs"], "spans": {k: spans[k] for k in ch["changed_knobs"]},
            "tier": tier, "solvable": tier != "hard_boundary", "predicted": predicted,
            "unmet": unmet, "regressed": regressed if tier in ("hard", "hard_boundary") else [],
            "hard_unmet": hard_unmet,
            "score": _score(model, x),
            "cost": {"n_changed": ch["changed_count"], "max_pct": max_pct}}


def _boundary_x(model, bounds):
    """하드를 선형 모델로 못 맞출 때의 경계 해 — 탐색 상자 안에서 하드 부족분(정규화 힌지)의 제곱합을 최소화한다.

    한 항목만 보면 그 항목의 best_reachable 꼭짓점과 같고, 여럿이면 부족분을 고르게 줄이는 쪽이다. 아주 작은
    Σx² 항은 부족분에 영향 없는 게인을 0에 둔다(평탄한 방향으로 표류하지 않게)."""
    n = model["n"]
    rows_ = [(e["srow"], e["b"], e["limit"], 1.0 if e["above"] else -1.0,
              max(abs(e["limit"]), abs(e["b"]), _perf_floor(e["metric"]))) for e in model["hard"]]

    def fun(x):
        tot = 1e-6 * float(x @ x)
        for srow, b, lim, sg, sc in rows_:
            v = sg * ((b + srow @ x) - lim) / sc
            if v > 0:
                tot += v * v
        return tot

    def jac(x):
        g = 2e-6 * x
        for srow, b, lim, sg, sc in rows_:
            v = sg * ((b + srow @ x) - lim) / sc
            if v > 0:
                g = g + 2.0 * v * sg * srow / sc
        return g

    res = minimize(fun, np.zeros(n), jac=jac, method="L-BFGS-B", bounds=bounds)
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    return np.clip(res.x, lo, hi)


def _plan_key(p):
    return (TIER_RANK[p["tier"]], round(p["score"] / _SCORE_QUANTUM),
            p["cost"]["n_changed"], round(p["cost"]["max_pct"], 4), tuple(p["knobs"]))


def solve_tiered(rows, knobs, criteria: GainEvalCriteria, *, hard_metrics=None,
                 goal_metrics=None, span_bound: float = 0.2, knob_bounds=None) -> dict:
    """단계화 조합 해 — 전 설계변수를 한꺼번에 쓰는 안 하나 + feasibility(못 맞춤 보고).

    solve_joint(min_change)와 같은 선형 모델·같은 SLSQP 위에서 제약을 두 층으로 가른다(모듈 위 설명).
    반환은 solve_joint 결과 모양(spans·predicted·violated·excluded·changed_*) + tier·feasibility·unmet.
    solvable은 「그 층의 규칙을 만족한다」이고, 목표 미달(unmet)은 feasibility.goal이 말한다.
    """
    model = _tier_model(rows, knobs, criteria, hard_metrics, goal_metrics)
    common = {"objective": "min_change", "span_bound": span_bound, "excluded": list(model["excluded"])}
    if not model["cases"]:
        return {**common, "solvable": False, "spans": None, "predicted": {}, "violated": [],
                "unmet": [], "tier": None, "reason": "기준 런이 없다 — 스윕부터",
                "feasibility": None, "changed_knobs": [], "changed_count": 0}
    bounds = _box(model, span_bound, knob_bounds)
    feas = _feasibility(model, bounds, span_bound, _range_text(span_bound, knob_bounds))
    tiers = [feas["mode"]] if feas["mode"] == "goal" else (
        ["nonregress", "hard"] if feas["mode"] == "nonregress" else ["hard"])
    for tier in tiers:
        x, ok, msg = _solve_tier(model, tier, bounds, span_bound)
        if ok or tier == tiers[-1]:
            break
    if feas["mode"] == "nonregress":
        feas["goal"]["nonregress_solvable"] = tier == "nonregress" and ok
    plan = _plan_of(model, tier, x, model["knobs"], bounds)
    spans = {k: float(x[i]) for k, i in model["idx"].items()}
    violated = [] if ok else [
        {"case": v["case"], "metric": v["metric"], "predicted": v["predicted"], "limit": v["limit"]}
        for v in _tier_violations(model, model["hard"], x, bounds)]
    return {**common, "solvable": ok, "spans": spans, "predicted": plan["predicted"],
            "violated": violated, "unmet": plan["unmet"], "regressed": plan["regressed"],
            "tier": tier if ok else None, "score": plan["score"],
            "reason": None if ok else (feas["reason"] or f"최적화 실패: {msg}"),
            "feasibility": feas, **_changed(model["knobs"], spans)}


def _sensitivity(model, knob):
    """풀 가지치기의 민감도 — 고쳐야 할 항목(기준에서 하드 위반 + 한계 밖 목표)에 대한 정규화 |기울기| 합.
    고칠 항목이 없으면 전 항목."""
    i = model["idx"][knob]
    need = [e for e in model["hard"] + model["goal"] if not e["inside"]] or model["hard"] + model["goal"]
    return sum(abs(float(e["srow"][i])) / _scale(e) for e in need)


def enumerate_plans(rows, pool_knobs, criteria: GainEvalCriteria, *, hard_metrics=None,
                    goal_metrics=None, K: int = 5, max_candidates: int = 30,
                    span_bound: float = 0.2, knob_bounds=None) -> dict:
    """게인 수별 복수 안 — 풀의 부분집합(크기 1…K)마다 단계화 규칙으로 풀고 순위를 매긴다(04 §7.3).

    풀이 MAX_FULL_POOL(8) 이하면 부분집합 전부, 넘으면 기울기 민감도 상위 8개로 줄여(pruned에 근거) 전부.
    각 부분집합은 feasibility가 정한 층(goal, 아니면 nonregress)으로 풀고, nonregress로 풀리는 부분집합이
    하나도 없을 때만 hard 층(목표 퇴행 감수)으로 다시 푼다. 풀린 것만 안이 된다.

    순위(_plan_key): ① 층(goal → nonregress → hard) ② 목표 개선량(한계 밖 목표 항목의 정규화 예측 변화
    평균, 1 %p 눈금) ③ 바뀐 게인 수 적을수록 ④ 최대 변화 % 작을수록 ⑤ 게인 이름(결정적 순서).
    같은 바뀐 게인 집합은 하나로 접는다(부분집합의 게인 하나가 0에 머물면 더 작은 부분집합과 같은 안이다).

    반환: {"feasibility", "plans"(게인 수 k마다 최선 1안, 순위순 — 화면·확인 런은 앞 3안),
    "candidates"(접은 안 전부 순위순, max_candidates까지), "pool", "pruned", "n_subsets", "joint"
    (solve_tiered — 전 풀 한꺼번에 쓴 해, plans가 비었을 때의 근거)}. 순수 함수 — 시뮬 없음.
    """
    from itertools import combinations

    knobs = list(dict.fromkeys(pool_knobs))
    joint = solve_tiered(rows, knobs, criteria, hard_metrics=hard_metrics, goal_metrics=goal_metrics,
                         span_bound=span_bound, knob_bounds=knob_bounds)
    feas = joint["feasibility"]
    out = {"feasibility": feas, "plans": [], "candidates": [], "pool": knobs, "pruned": [],
           "n_subsets": 0, "joint": joint, "K": K}
    if feas is None:
        return out
    model = _tier_model(rows, knobs, criteria, hard_metrics, goal_metrics)
    if not feas["hard"]["solvable"]:
        # 하드부터 선형 모델로 못 맞춘다 — feasibility는 그대로 「못 맞춤」을 말하고, 전 풀 경계 해 하나를 안으로 세워
        # 확인 런(비선형)이 판정하게 한다. 부분집합 열거는 하지 않는다(풀리는 층이 없으니 순위가 뜻이 없다)
        bounds = _box(model, span_bound, knob_bounds)
        p = _plan_of(model, "hard_boundary", _boundary_x(model, bounds), model["knobs"], bounds)
        if p["knobs"]:
            out["plans"] = [p]
            out["candidates"] = [p]
        return out
    pool = knobs
    if len(pool) > MAX_FULL_POOL:
        ranked = sorted(pool, key=lambda k: (-_sensitivity(model, k), pool.index(k)))
        keep = set(ranked[:MAX_FULL_POOL])
        out["pruned"] = [{"knob": k, "sensitivity": _sensitivity(model, k),
                          "reason": f"민감도 상위 {MAX_FULL_POOL}개 밖 — 부분집합 열거에서 뺐다"}
                         for k in ranked[MAX_FULL_POOL:]]
        pool = [k for k in pool if k in keep]
    kmax = max(0, min(int(K), len(pool)))
    subsets = [c for k in range(1, kmax + 1) for c in combinations(pool, k)]
    out["n_subsets"] = len(subsets)

    def solve_all(tier):
        found = {}
        for sub in subsets:
            bounds = _box(model, span_bound, knob_bounds, active=set(sub))
            x, ok, _m = _solve_tier(model, tier, bounds, span_bound)
            if not ok:
                continue
            p = _plan_of(model, tier, x, list(sub), _box(model, span_bound, knob_bounds))
            if not p["knobs"]:
                continue  # 0 변화 — 고칠 것이 없다는 말이지 안이 아니다
            key = tuple(p["knobs"])
            if key not in found or _plan_key(p) < _plan_key(found[key]):
                found[key] = p
        return sorted(found.values(), key=_plan_key)

    mode = feas["mode"]
    cands = solve_all(mode)
    if not cands and mode == "nonregress":
        cands = solve_all("hard")
    if mode == "nonregress":
        feas["goal"]["nonregress_solvable"] = bool(cands) and cands[0]["tier"] == "nonregress"
    out["candidates"] = cands[:max(0, int(max_candidates))]
    best_by_k: dict = {}
    for p in cands:
        best_by_k.setdefault(p["cost"]["n_changed"], p)
    out["plans"] = sorted(best_by_k.values(), key=_plan_key)
    return out


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
            out.append(f"{'·'.join(pair)}의 {metric} 비가산성 {v:+.3g} — 두 설계변수가 "
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
