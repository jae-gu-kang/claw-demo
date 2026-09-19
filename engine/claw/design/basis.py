"""초기 게인 산출 근거 — 한 트림점의 저차 근사에서 레이트 댐퍼 초기값을 닫힌꼴로 재고, 전체 모델로
확인한다 (05 §10.1).

빠른 탐색(quick_seed — 05 §10)은 크기를 로그 스캔으로 **찾는다**. 여기는 같은 목표를 저차 근사 모델의
**닫힌꼴로 계산한다**: 롤은 1차 근사 극배치(폐루프 극 a + b·k = −λ → k = −(λ + a)/b), 피치·요는 2차
근사(단주기 w–q · 더치롤 v–r)의 특성방정식 계수 비교(목표 ζ — match_zeta_2x2). 닫힌꼴이 주는 것은 수치가
아니라 **근거**다: a(감쇠)·b(조종효율)·목표가 자리마다 남아 "왜 이 크기인가"에 답한다.

후보마다 세 가지를 확인한다 — 저차 근사는 후보를 만들 뿐, 채택 판단은 전체 모델이 한다:
1. 전체 선형 모델 지표(axis_metrics — 튜너·검증과 같은 자, 최종 조성에서)와 작동기·지연 포함 폐루프
   안정(tune._damper_loop_stable — 같은 가드, 튜너와 같은 프리픽스 조성에서)
2. 조종면 예산 — 대표 오차 e_ref × |k|가 트림 잔여 변위(피치는 방향별 최소·롤은 엘레본 롤 몫·요는
   러더)에 드는가. P 몫만이므로 통과해도 자세 PI·다른 명령의 몫은 따로 남겨야 한다
3. ×0.7/1.0/1.3 주변 후보의 지표·안정 — 하나의 시작점 대신 주변을 본다

자세 PI는 새 식을 만들지 않는다 — 튜너의 루프쉐이핑(tune._tune_att: 목표 교차 = 레이트 교차 ÷
wc_ratio_att, |PI·G·Act·지연| = 1에서 |kp|, PI 영점 = 교차 × ki_zero_frac, PM/GM 검증·백오프)을 그대로
부른다. 같은 방법이 두 곳에 적히면 갈린다. 바깥 루프(헤딩·고도·속도)는 시간척도 분리(자세 교차 ÷
SEPARATION)만 적는다 — 게인 유도는 quick_seed의 휴리스틱이 정본이다.

읽기 전용 분석이다 — 문서를 고치지 않고, 시드 채택(스케줄 검증 포함)은 여전히 quick_seed가 한다.
"""

import math
import time

import numpy as np

from claw.common.contracts import TrimCase
from claw.design.closure import axis_metrics, close_rates, rate_loop_crossover
from claw.design.seed import REASON_SEED_SIGN_AMBIGUOUS, SEPARATION, _clean
from claw.design.seed import reason_text as _seed_reason_text
from claw.design.tune import (
    _FINAL_METRIC_RTOL,
    _PASSING,
    _RATE_PLAN,
    SLOT_DESIGN_FAILED,
    TuneTargets,
    _damper_loop_stable,
    _tune_att,
)
from claw.trim import linearize, split_axes, trim

E_REF_DPS = 10.0  # [기본값] 대표 레이트 오차 [°/s] — 예산 점검의 자. 요청이 바꾼다(조회 조건)
NEIGHBOR_MULTS = (0.7, 1.0, 1.3)  # 주변 후보 배수 — 하나의 시작점 대신 주변을 본다

# (자리, 축, 지표 키, 목표 필드, 저차 모델 상태·입력) — 순서 = 닫는 순서. 앞 넷은 튜너의
# _RATE_PLAN과 같아야 한다(아래 assert) — 두 곳에 손으로 적히면 갈린다
_SLOTS = (
    ("pitch", "lon", "zeta_sp", "zeta_sp", ("w", "q", "de")),
    ("yaw", "lat", "zeta_dr", "zeta_dr", ("v", "r", "dr")),
    ("roll", "lat", "roll_lambda", "roll_lambda", ("p", "da")),
)
assert tuple(s[:4] for s in _SLOTS) == _RATE_PLAN, "닫는 순서·지표가 튜너와 갈렸다"
_MODEL_LABEL = {"pitch": "단주기 2차 근사 (w–q)", "yaw": "더치롤 2차 근사 (v–r)",
                "roll": "롤 수렴 1차 근사 (p)"}
_XU = {"pitch": ("q", "de"), "yaw": ("r", "dr"), "roll": ("p", "da")}  # 자리 → (레이트 상태, 입력)

REASON_BASIS_TRIM_FAILED = "basis_trim_failed"
REASON_BASIS_NO_MATCH = "basis_no_match"
REASON_TEXT = {
    REASON_BASIS_TRIM_FAILED: "이 조건의 트림이 수렴하지 않는다 — 저차 근사를 세울 기준점이 없다."
                              " 트림 탭에서 성립 영역을 먼저 확인한다",
    REASON_BASIS_NO_MATCH: "저차 근사가 목표 감쇠를 어떤 게인으로도 못 만든다(계수 비교 2차식에 유효한"
                           " 근이 없다) — 근사가 유효하지 않거나 플랜트 한계다. 빠른 탐색(스캔)으로 확인한다",
}


def reason_text(reason) -> str | None:
    """산출 근거 사유 + 시드·튜너 사유를 한 표로."""
    return REASON_TEXT.get(reason) or _seed_reason_text(reason)


def match_zeta_2x2(A2, b2, zeta):
    """2×2 저차 근사 + 레이트 되먹임 u = k·x₂ → 목표 ζ를 만드는 k (특성방정식 계수 비교).

    폐루프 A′ = A₂ + k·b₂·e₂ᵀ의 특성식 s² + c₁s + c₀에서
      c₁ = c₁₀ − k·b₂[1] (c₁₀ = −tr A₂),  c₀ = d₀ + k·d₁ (d₀ = det A₂, d₁ = A₂[0,0]·b₂[1] − A₂[1,0]·b₂[0])
    목표 c₁ = 2ζ√c₀을 제곱해 k의 2차식으로 풀고, **c₁ > 0·c₀ > 0(안정)** 인 실근만 남긴다 — 제곱이
    들여온 c₁ = −2ζ√c₀(발산) 근을 거른다. 여럿이면 감쇠 부호 관례(−sign(b₂[1]) — u = +k·rate가 감쇠를
    더한다)에 맞는 근을 먼저, 그중 |k|가 작은 쪽(조종면 예산). 반환 (k | None, 유효 근 전부).
    """
    A2 = np.asarray(A2, dtype=float)
    b2 = np.asarray(b2, dtype=float).reshape(-1)
    c10 = -float(np.trace(A2))
    t = float(b2[1])
    d0 = float(np.linalg.det(A2))
    d1 = float(A2[0, 0] * b2[1] - A2[1, 0] * b2[0])
    z4 = 4.0 * zeta * zeta
    coeffs = [t * t, -(2.0 * c10 * t + z4 * d1), c10 * c10 - z4 * d0]
    roots = np.roots(coeffs) if any(c != 0.0 for c in coeffs) else np.array([])
    valid = sorted((float(r.real) for r in roots
                    if abs(r.imag) <= 1e-9 * max(1.0, abs(r))
                    and (c10 - r.real * t) > 0.0 and (d0 + r.real * d1) > 0.0),
                   key=abs)
    if not valid:
        return None, []
    want = -math.copysign(1.0, t) if t != 0.0 else 0.0
    preferred = [k for k in valid if want and math.copysign(1.0, k) == want]
    return (preferred or valid)[0], valid


def _lo_model(group, spec, lon, lat, lm_prefix):
    """저차 근사 모델 dict — 1차(롤)는 {a, b}, 2차는 특성식 계수(개루프·k 기울기)까지.

    롤의 a는 **요 댐퍼를 접은** 횡축에서 읽는다(lm_prefix) — 튜너·검증과 같은 조성이다."""
    if len(spec) == 2:  # 1차 — (레이트 상태, 입력)
        x, u = spec
        m = lm_prefix
        a = float(m.A[m.x_names.index(x), m.x_names.index(x)])
        b = float(m.B[m.x_names.index(x), m.u_names.index(u)])
        return {"kind": "first_order", "label": _MODEL_LABEL[group], "states": [x], "input": u,
                "a": a, "b": b}
    xo, x, u = spec  # 2차 — (동반 상태, 레이트 상태, 입력)
    m = lon if group == "pitch" else lat
    idx = [m.x_names.index(xo), m.x_names.index(x)]
    A2 = m.A[np.ix_(idx, idx)]
    b2 = m.B[idx, m.u_names.index(u)]
    c10 = -float(np.trace(A2))
    d0 = float(np.linalg.det(A2))
    wn0 = math.sqrt(d0) if d0 > 0.0 else None
    return {"kind": "second_order", "label": _MODEL_LABEL[group], "states": [xo, x], "input": u,
            "b": float(b2[1]), "c1": c10, "c1_k": -float(b2[1]), "c0": d0,
            "c0_k": float(A2[0, 0] * b2[1] - A2[1, 0] * b2[0]),
            "open_wn": wn0, "open_zeta": (c10 / (2.0 * wn0)) if wn0 else None,
            "_A2": A2, "_b2": b2}


def _candidate(group, model, targets):
    """저차 근사 → (후보 dict | None, 사유 | None)."""
    if model["b"] == 0.0 or not math.isfinite(model["b"]):
        return None, REASON_SEED_SIGN_AMBIGUOUS
    if model["kind"] == "first_order":
        lam = targets.roll_lambda
        a, b = model["a"], model["b"]
        if -a >= lam:  # 개루프가 이미 목표 이상 — 게인을 줄여 늦추는 것은 초기값의 일이 아니다
            return {"k": 0.0, "poles": [[a, 0.0]],
                    "note": "개루프 롤 감쇠가 이미 목표 이상 — 댐퍼 없이 목표 달성"}, None
        k = -(lam + a) / b
        return {"k": k, "poles": [[a + b * k, 0.0]], "note": None}, None
    zeta = getattr(targets, "zeta_sp" if group == "pitch" else "zeta_dr")
    k, _roots = match_zeta_2x2(model["_A2"], model["_b2"], zeta)
    if k is None:
        return None, REASON_BASIS_NO_MATCH
    c1 = model["c1"] + model["c1_k"] * k
    c0 = model["c0"] + model["c0_k"] * k
    disc = c1 * c1 - 4.0 * c0
    poles = ([[(-c1 + s * math.sqrt(disc)) / 2.0, 0.0] for s in (1.0, -1.0)] if disc >= 0.0
             else [[-c1 / 2.0, s * math.sqrt(-disc) / 2.0] for s in (1.0, -1.0)])
    return {"k": k, "poles": poles, "note": None}, None


def _budget(group, k, tr, rudder_bounds, e_ref):
    """P 출력 |k|·e_ref 대 트림 잔여 변위 — 방향별 최소(피치)·롤 몫(롤)·러더(요).

    피치·롤의 여유는 트림이 계산한 reserve(trim.trim_reserve)를 그대로 쓴다 — 두 번 재지 않는다.
    요는 reserve에 러더 항이 없어 러더 한계·트림값에서 직접 잰다. reserve가 없거나 절반만
    있으면(옛 저장물) 여유를 0으로 위장하지 않고 None을 낸다 — min에 nan을 섞으면 인자 순서에
    따라 nan이 아니라 유한값이 나오므로(파이썬 min은 nan을 전파하지 않는다) 결측을 먼저 가른다."""
    rv = tr.reserve or {}
    if group == "pitch":
        de = rv.get("de", {})
        hi, lo = de.get("reserve_hi"), de.get("reserve_lo")
        margin = min(hi, lo) if hi is not None and lo is not None else math.nan
        surface = "elevon"
    elif group == "roll":
        roll_avail = rv.get("elevon_roll_avail")
        margin = roll_avail if roll_avail is not None else math.nan
        surface = "elevon"
    else:
        lo, hi = rudder_bounds
        dr = float(tr.control.rudder)
        margin = min(hi - dr, dr - lo)
        surface = "rudder"
    delta = abs(k) * e_ref
    if not math.isfinite(margin):
        return {"surface": surface, "margin": None, "delta_cmd": delta, "share": None, "ok": None}
    return {"surface": surface, "margin": margin, "delta_cmd": delta,
            "share": (delta / margin) if margin > 0.0 else None,
            "ok": bool(delta <= margin)}


def _axis_slots(axis):
    """그 축의 레이트 자리 이름들 — 조성 dict의 키 집합."""
    return [f"{g}.k_rate" for g, ax, *_ in _SLOTS if ax == axis]


def seed_basis(built, mach, alt, fuel, *, e_ref_dps=E_REF_DPS, targets=None,
               delay_s=0.035, pade_order=2) -> dict:
    """BuiltProfile + 트림점 → 초기 게인 산출 근거 (JSON 직렬화 가능 dict).

    {"ok", "reason", "reason_text", "case", "e_ref_dps", "targets", "act", "trim",
     "order", "rates": {자리: {slot, model, target, candidate, full, budget, neighbors, reason, …}},
     "attitude": {pitch_att·roll_att: 튜너 루프쉐이핑 결과}, "outer", "design_now", "elapsed_s"}.

    ok는 **분석이 섰는가**(트림 수렴)다 — 자리별 성패는 rates[*].reason이 따로 말한다.
    """
    t0 = time.perf_counter()
    targets = targets if targets is not None else TuneTargets()
    ac = built.aircraft()
    case = TrimCase(f"M{mach:.2f}_h{alt:.0f}_f{fuel:.0f}", mach=float(mach), alt=float(alt),
                    fuel=float(fuel))
    act = built.actuator_params()
    existing = built.doc["law"]["design"]
    rate_filters = built.rate_filters() if existing is not None else {}
    act_kw = {"actuator_wn": act.get("wn"), "actuator_zeta": act.get("zeta"),
              "delay_s": delay_s, "pade_order": pade_order, "rate_filters": rate_filters}
    base = {
        "case": {"name": case.name, "mach": case.mach, "alt": case.alt, "fuel": case.fuel},
        "e_ref_dps": float(e_ref_dps), "targets": targets.to_dict(),
        "act": {"actuator_wn": act.get("wn"), "actuator_zeta": act.get("zeta"),
                "delay_s": delay_s, "pade_order": pade_order},
    }
    tr = trim(ac, case, fingerprint=built.plant_fingerprint)
    if not tr.converged:
        return _clean({**base, "ok": False, "reason": REASON_BASIS_TRIM_FAILED,
                       "reason_text": reason_text(REASON_BASIS_TRIM_FAILED),
                       "trim": {"converged": False, "cost": tr.cost},
                       "order": [], "rates": {}, "attitude": {}, "outer": None,
                       "design_now": _design_now(existing, built),
                       "elapsed_s": time.perf_counter() - t0})
    lm = linearize(ac, tr)
    lon, lat = split_axes(lm)
    axis_lm = {"lon": lon, "lat": lat}
    e_ref = math.radians(float(e_ref_dps))
    rudder_bounds = built.surfaces["rudder"]

    # 1차 패스 — 닫는 순서대로 후보를 만든다. 프리픽스 조성(자기보다 앞서 닫힌 자리만)은 튜너의
    # 탐색·캡 판정과 같은 플랜트다 (05 §4.1)
    gains, rates, order, prefix_of = {}, {}, [], {}
    for group, axis, metric_key, target_field, spec in _SLOTS:
        name = f"{group}_rate"
        order.append(name)
        lm_axis = axis_lm[axis]
        prefix = {s: gains.get(s, 0.0) for s in _axis_slots(axis)}
        prefix[f"{group}.k_rate"] = 0.0
        prefix_of[group] = prefix
        lm_prefix = close_rates(lm_axis, prefix, rate_filters)
        model = _lo_model(group, spec, lon, lat, lm_prefix)
        cand, why = _candidate(group, model, targets)
        x, u = _XU[group]
        rec = {"slot": f"{group}.k_rate",
               "model": {k: v for k, v in model.items() if not k.startswith("_")},
               "target": {"metric": metric_key, "value": getattr(targets, target_field)},
               "sign_basis": f"B[{x},{u}]={model['b']:.4g}",
               "candidate": cand, "full": None, "budget": None, "neighbors": [],
               "reason": why, "reason_text": reason_text(why) if why else None}
        rates[name] = rec
        if cand is not None:
            gains[f"{group}.k_rate"] = cand["k"]
            rec["budget"] = _budget(group, cand["k"], tr, rudder_bounds, e_ref)

    # 2차 패스 — 보고 지표는 **최종 조성**(그 축의 채택 후보를 다 닫음)에서 잰다: 검증(schedmap)과 같은
    # 자다 (05 §4.3). 안정은 튜너의 캡 판정과 같은 프리픽스 조성에서 본다. 주변 후보는 이 자리만 배수로
    # 흔들고 나머지는 채택값에 둔다
    for group, axis, metric_key, _tf, _spec in _SLOTS:
        rec = rates[f"{group}_rate"]
        if rec["candidate"] is None:
            continue
        lm_axis = axis_lm[axis]
        final = {s: gains.get(s, 0.0) for s in _axis_slots(axis)}
        x, u = _XU[group]
        lm_prefix = close_rates(lm_axis, prefix_of[group], rate_filters)
        target = rec["target"]["value"]

        def measure(k, _lm=lm_axis, _final=final, _slot=f"{group}.k_rate", _mk=metric_key):
            got = axis_metrics(_lm, {**_final, _slot: k}, rate_filters).get(_mk)
            return got if got is not None and math.isfinite(got) else None

        k0 = rec["candidate"]["k"]
        got = measure(k0)
        rec["full"] = {
            "achieved": got,
            "stable": _damper_loop_stable(lm_prefix, group, x, u, k0, act_kw),
            "ok": None if got is None else bool(got >= target * (1.0 - _FINAL_METRIC_RTOL)),
        }
        # k = 0 후보(개루프가 이미 목표 이상 — 댐퍼 불요)는 배수가 전부 0이라 같은 줄 셋이 된다
        rec["neighbors"] = [] if k0 == 0.0 else [{
            "mult": mult, "k": k0 * mult, "achieved": measure(k0 * mult),
            "stable": _damper_loop_stable(lm_prefix, group, x, u, k0 * mult, act_kw),
        } for mult in NEIGHBOR_MULTS]

    # 자세 PI — 튜너 루프쉐이핑 그대로 (부호는 조종효율에서: quick_seed와 같은 규칙). 레이트 게인은
    # 최종 조성, 레이트 교차는 튜너처럼 프리픽스 조성에서 잰다. **구제 마무리(_polish_att)는 부르지
    # 않는다** — tune_point는 실패 자리를 구제로 살릴 수 있어(REASON_RESCUED) 같은 점에서 여기가 더
    # 엄격하게 「미달」일 수 있다. 초기값 근거로는 백오프 해까지가 닫힌 절차이고, 구제 블록을 여기
    # 다시 적으면 두 벌이 된다 (05 §10.1에 적음)
    attitude = {}
    for group in ("pitch", "roll"):
        axis = "lon" if group == "pitch" else "lat"
        lm_axis = axis_lm[axis]
        x, u = _XU[group]
        b = float(lm_axis.B[lm_axis.x_names.index(x), lm_axis.u_names.index(u)])
        entry = {"slot": f"{group}.kp/ki", "sign_basis": f"B[{x},{u}]={b:.4g}",
                 "kp": 0.0, "ki": 0.0}
        if b == 0.0 or not math.isfinite(b):
            entry.update(reason=REASON_SEED_SIGN_AMBIGUOUS,
                         reason_text=reason_text(REASON_SEED_SIGN_AMBIGUOUS))
            attitude[f"{group}_att"] = entry
            continue
        final = {s: gains.get(s, 0.0) for s in _axis_slots(axis)}
        rate_wc = 0.0
        rec = rates[f"{group}_rate"]
        if rec["candidate"] is not None:
            lm_prefix = close_rates(lm_axis, prefix_of[group], rate_filters)
            wc = rate_loop_crossover(lm_prefix, group, x, u, rec["candidate"]["k"], **act_kw)
            rate_wc = wc if wc and math.isfinite(wc) else 0.0
        kp, ki, ach, why, _ev = _tune_att(lm_axis, group, final, rate_wc,
                                          {f"{group}.kp": math.copysign(1.0, b)}, targets, act_kw)
        # passing은 여기서 판정해 동봉한다 — 화면이 통과 사유 집합(_PASSING)을 재기술하지 않게
        entry.update(kp=kp, ki=ki, reason=why, reason_text=reason_text(why),
                     passing=why in _PASSING, **ach)
        attitude[f"{group}_att"] = entry

    inner = [a.get("wc_att") for a in attitude.values()
             if a.get("wc_att") and a.get("reason") not in SLOT_DESIGN_FAILED]
    outer = {"separation": SEPARATION,
             "wc_outer": (min(inner) / SEPARATION) if inner else None}

    return _clean({
        **base, "ok": True, "reason": None, "reason_text": None,
        "trim": {"converged": True, "alpha": tr.state.euler()[1],
                 "de": float(tr.control.elevon[0]), "throttle": float(tr.control.throttle[0])},
        "order": order, "rates": rates, "attitude": attitude, "outer": outer,
        "design_now": _design_now(existing, built),
        "elapsed_s": time.perf_counter() - t0,
    })


def _design_now(existing, built) -> dict | None:
    """문서의 지금 게인(7자리) — 가이드의 출처 우선순위 2(같은 점의 이전 설계)를 나란히 놓는 자리."""
    if existing is None:
        return None
    hand = built.design_gains()
    slots = ("pitch.k_rate", "yaw.k_rate", "roll.k_rate", "pitch.kp", "pitch.ki", "roll.kp", "roll.ki")
    return {"source": (existing.get("provenance") or {}).get("source"),
            "gains": {s: hand.get(s) for s in slots}}
