"""운영점별 SCAS 게인 자동 튜닝 — 결정론적 2단 (댐퍼 감쇠 목표 → 자세 PI 루프쉐이핑).

docs -02의 "자동 PID 튜닝 스코프 제외 [확정]"을 번복하는 구현 (사용자 확정).
LQR 제외는 유지 — PI 구조 불변, 튜닝 방식만 자동화한다. 대상은 SCAS 내측
7자리(pitch/roll kp·ki·k_rate + yaw.k_rate)이고 AP 외측(고도·속도·헤딩)은 v1
제외 — 분리모델에 h·ψ 상태가 없다는 openloop.py GROUP_LOOPS의 정직성과 같은 이유.

2단 구조 (closure.py의 successive closure 조성과 같은 정의 — 튜닝과 검증이 같은
자로 잰다):
1. 레이트 댐퍼 — 폐쇄 모드 지표 목표의 단조 스캔+이분: pitch ζ_sp→zeta_sp,
   yaw ζ_dr→zeta_dr(먼저 — 더치롤 감쇠 없이는 횡축이 성립 안 함), roll
   λ_roll→roll_lambda. 부호는 설계값이 보유(방향만 쓴다), 탐색은 |설계값|×4 브래킷.
   댐퍼 안정 캡: 작동기·지연 포함 폐루프 고유치 안정을 위반하면 |k|를 안정 경계
   아래로 이분 축소 (01 §4.2 "PM 91°→−76.3°" 실증 사고의 재발 방지 가드 —
   교차 주파수 캡이 아니라 폐루프 안정성 판정이다: |L|<1 댐퍼는 교차가 없다).
2. 자세 PI — 목표 교차 ωc_att = (레이트 ωc 또는 기준 wn)/wc_ratio_att에서
   |PI·G′·Act·Delay|=1이 되게 |kp| 결정 (PI 영점 = ωc_att×ki_zero_frac),
   oriented_margins로 검증 → PM/GM 미달 시 ωc_att ← backoff× 기하 백오프,
   바닥(wc_att_floor_frac) 도달 시 status="infeasible" — **던지지 않는다**.
   infeasible도 결과다: 분류기(classify)의 structural_limit 판정 근거가 된다.

polish=True는 선택적 Nelder-Mead 마무리(kp·ki 2변수, 대역폭 보상−마진 벌점) —
기본 OFF, 결정론·재현성 우선.
"""

import math
from dataclasses import asdict, dataclass

import numpy as np

from claw.design.closure import (
    AXIS_SPECS,
    att_margin_loop,
    axis_metrics,
    oriented_margins,
    rate_loop_crossover,
    wn_reference,
)
from claw.trim import split_axes

_SCAN_N = 33  # 레이트 게인 브래킷 스캔 밀도
_BISECT_N = 24  # 이분 반복 (브래킷 폭 ×2^-24)


@dataclass(frozen=True)
class TuneTargets:
    pm_deg: float = 50.0  # 설계 목표 위상여유 — 합격 45°보다 여유 (히스테리시스)
    gm_db: float = 8.0  # 설계 목표 이득여유 — 합격 6 dB보다 여유
    zeta_sp: float = 0.7  # 단주기 감쇠 목표
    zeta_dr: float = 0.5  # 더치롤 감쇠 목표
    roll_lambda: float = 12.0  # 롤 수렴 모드 대역폭 목표 [rad/s]
    wc_ratio_att: float = 3.0  # 자세 교차 = 레이트 교차 ÷ 이 값 (successive closure 관례)
    ki_zero_frac: float = 0.125  # PI 영점 = ωc_att × 이 값 (한 옥타브×3 아래)
    backoff: float = 0.7  # 마진 미달 시 ωc_att 기하 축소비
    wc_att_floor_frac: float = 0.05  # ωc_att 탐색 바닥 = 초기 목표 × 이 값
    wc_att_ok_frac: float = 0.2  # 달성 대역폭 하한 — 이보다 낮은 ωc에서만 마진이
    # 통과하면 infeasible이다. 백오프는 대역폭을 버리면 거의 항상 마진을 만들 수
    # 있으므로(지연 위상 ∝ ω), 하한 없는 "통과"는 성능 붕괴를 조용히 합격으로 위장한다.

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TuneTargets":
        return cls(**{k: float(v) for k, v in d.items()})


# 레이트 자리 → (축, 지표 키, 목표 필드). 순서 = 닫는 순서(요 먼저 — closure.py).
_RATE_PLAN = (
    ("pitch", "lon", "zeta_sp", "zeta_sp"),
    ("yaw", "lat", "zeta_dr", "zeta_dr"),
    ("roll", "lat", "roll_lambda", "roll_lambda"),
)


def _metric(lm_axis, rate_gains, key):
    return axis_metrics(lm_axis, rate_gains)[key]


def _first_reach_bisect(f, k_lo, k_hi, target, n_scan=_SCAN_N):
    """|k| 오름차순 스캔으로 f ≥ target 첫 도달 구간을 잡아 이분 — (k, 도달 여부).

    f가 뒤에서 비단조여도(모드 교환) 첫 도달 구간만 쓰므로 안전하다. 브래킷 안에서
    한 번도 도달하지 못하면 argmax를 낸다 (최선 달성 — 목표 미달 플래그와 함께).
    """
    ks = np.linspace(k_lo, k_hi, n_scan)
    vals = [f(k) for k in ks]
    reach = [i for i, v in enumerate(vals) if v >= target]
    if not reach:
        return float(ks[int(np.argmax(vals))]), False
    i = reach[0]
    if i == 0:
        return float(ks[0]), True
    lo, hi = ks[i - 1], ks[i]
    for _ in range(_BISECT_N):
        mid = 0.5 * (lo + hi)
        if f(mid) >= target:
            hi = mid
        else:
            lo = mid
    return float(hi), True


def _damper_loop_stable(lm_axis, x_rate, u_in, k, act_kw, zeta_act_min=0.10) -> bool:
    """레이트 댐퍼 폐루프(작동기 2차계+Padé 지연 포함)의 안정 판정.

    01 §4.2 실증 사고(작동기·지연 포함 시 PM 91°→−76.3° 불안정 전환)를 직접 막는
    가드다. 교차 주파수 캡은 틀린 가드였다 — |L|<1인 댐퍼는 교차가 없고(소이득
    안정), 교차가 있어도 다중 교차(장주기 봉우리) 탓에 SISO PM이 진짜 안정성과
    어긋난다. 판정: 폐루프 극 전부 안정 + 작동기 대역 부근(>0.3×wn_act) 진동극의
    ζ ≥ zeta_act_min (간신히 안정한 작동기 공진을 합격으로 두지 않는다).
    """
    import control

    from claw.analysis import pi_loop

    loop = pi_loop(
        lm_axis, x_out=x_rate, u_in=u_in, kp=k, ki=0.0, sign=1.0, **act_kw
    )
    # 물리 댐퍼는 u = +k·rate (안정화 부호는 k가 보유, closure.close_rates의
    # A+Bk·eᵀ와 동일) — 폐루프 특성식은 1 − L = 0이므로 양의 되먹임으로 닫는다
    poles = control.feedback(loop, 1, sign=1).poles()
    if np.any(poles.real >= -1e-9):
        return False
    wn_act = act_kw.get("actuator_wn") or 0.0
    if wn_act:
        for p in poles:
            wn = abs(p)
            if p.imag > 1e-9 and wn > 0.3 * wn_act and (-p.real / wn) < zeta_act_min:
                return False
    return True


def _cap_by_stability(lm_axis, x_rate, u_in, k, act_kw):
    """댐퍼 폐루프가 불안정해지면 |k|를 이분 축소해 안정 경계 아래로 — (k', 캡 여부)."""
    if k == 0.0 or _damper_loop_stable(lm_axis, x_rate, u_in, k, act_kw):
        return k, False
    lo, hi = 0.0, abs(k)
    sign = math.copysign(1.0, k)
    for _ in range(_BISECT_N):
        mid = 0.5 * (lo + hi)
        if _damper_loop_stable(lm_axis, x_rate, u_in, sign * mid, act_kw):
            lo = mid
        else:
            hi = mid
    return sign * lo, True


def _tune_rates(lon, lat, design, targets, act_kw) -> tuple:
    """레이트 3자리 순차 튜닝 — (gains, achieved, notes)."""
    axes = {"lon": lon, "lat": lat}
    gains: dict = {}
    achieved: dict = {}
    notes: list = []
    for group, axis, metric_key, target_field in _RATE_PLAN:
        slot = f"{group}.k_rate"
        lm_axis = axes[axis]
        k_design = float(design[slot])
        if k_design == 0.0:
            gains[slot] = 0.0
            notes.append(f"{slot}: 설계값 0 — 방향 정보가 없어 튜닝하지 않는다")
            continue
        sign = math.copysign(1.0, k_design)
        target = getattr(targets, target_field)
        spec_rates = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
                      for g, _, _ in AXIS_SPECS[axis]["rates"]}

        def f(mag, _slot=slot, _lm=lm_axis, _sign=sign, _base=dict(spec_rates), _mk=metric_key):
            g = dict(_base)
            g[_slot] = _sign * mag
            return _metric(_lm, g, _mk)

        mag, reached = _first_reach_bisect(f, 0.0, 4.0 * abs(k_design), target)
        k = sign * mag
        x_rate, u_in = next((x, u) for g, x, u in AXIS_SPECS[axis]["rates"] if g == group)
        k, capped = _cap_by_stability(lm_axis, x_rate, u_in, k, act_kw)
        gains[slot] = k
        final = dict(spec_rates)
        final[slot] = k
        achieved[f"{group}_rate"] = {
            "kind": "damping" if metric_key != "roll_lambda" else "bandwidth",
            metric_key: _metric(lm_axis, final, metric_key),
            "target": target,
            "wc": rate_loop_crossover(lm_axis, group, x_rate, u_in, k, **act_kw),
            "capped": capped,
        }
        if not reached:
            notes.append(f"{slot}: 브래킷(±4×설계값) 내 목표 {target} 미달 — 최선 달성값 채택")
        if capped:
            notes.append(f"{slot}: 댐퍼 안정 캡 적용 — 작동기·지연 포함 폐루프 안정 경계 아래로 축소")
    return gains, achieved, notes


def _tune_att(lm_axis, group, rate_gains, rate_wc, design, targets, act_kw) -> tuple:
    """자세 PI 루프쉐이핑 + 마진 검증 백오프 — (kp, ki, achieved, status, evals)."""
    kp_design = float(design[f"{group}.kp"])
    sign = math.copysign(1.0, kp_design) if kp_design != 0.0 else 1.0
    wc0 = (rate_wc if rate_wc > 0 else wn_reference(lm_axis)) / targets.wc_ratio_att
    wc = wc0
    evals = 0
    best = None
    while wc >= targets.wc_att_floor_frac * wc0:
        zc = wc * targets.ki_zero_frac
        base = att_margin_loop(lm_axis, rate_gains, kp=1.0, ki=zc, **act_kw)
        mag = float(np.abs(base.frequency_response([wc]).magnitude).reshape(-1)[0])
        evals += 1
        if mag <= 0.0 or not math.isfinite(mag):
            wc *= targets.backoff
            continue
        kp = sign / mag
        ki = kp * zc
        m, orient = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
        evals += 1
        best = (kp, ki, {**m, "orientation": orient, "wc_att": wc})
        pm_ok = math.isfinite(m["pm_deg"]) and m["pm_deg"] >= targets.pm_deg
        gm_ok = not (math.isfinite(m["gm_db"]) and m["gm_db"] < targets.gm_db)
        if pm_ok and gm_ok:
            # 대역폭 하한 — 이 밑에서만 통과하는 것은 성능 붕괴다 (structural limit)
            status = "ok" if wc >= targets.wc_att_ok_frac * wc0 else "infeasible"
            return kp, ki, best[2], status, evals
        wc *= targets.backoff
    if best is None:
        return 0.0, 0.0, {"note": "기저 루프 응답이 무의미 — 자세 튜닝 불가"}, "infeasible", evals
    kp, ki, ach = best
    return kp, ki, ach, "infeasible", evals


def tune_point(
    lm_full, design, *, targets=None,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    polish=False, max_evals=60,
) -> dict:
    """한 운영점의 SCAS 7자리 자동 튜닝 — {"gains", "achieved", "status", "notes", "evals"}.

    status: "ok" | "infeasible"(어느 자세 축이든 목표 미달 잔존 — 자유 게인으로도
    기준을 못 맞춘 점, classify의 structural_limit 입력). 예외로 던지지 않는다.
    """
    targets = targets if targets is not None else TuneTargets()
    act_kw = dict(
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )
    lon, lat = split_axes(lm_full)
    gains, achieved, notes = _tune_rates(lon, lat, design, targets, act_kw)

    evals = 0
    status = "ok"
    for lm_axis, group in ((lon, "pitch"), (lat, "roll")):
        spec = AXIS_SPECS[lm_axis.axis]
        rate_gains = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
                      for g, _, _ in spec["rates"]}
        rate_wc = achieved.get(f"{group}_rate", {}).get("wc", 0.0)
        kp, ki, ach, st, ev = _tune_att(
            lm_axis, group, rate_gains, rate_wc, design, targets, act_kw
        )
        evals += ev
        gains[f"{group}.kp"] = kp
        gains[f"{group}.ki"] = ki
        achieved[f"{group}_att"] = ach
        if st != "ok":
            status = "infeasible"
            notes.append(f"{group}.kp/ki: 백오프 바닥까지 PM {targets.pm_deg}°/"
                         f"GM {targets.gm_db} dB 미달 — structural_limit 후보")
        if polish and st == "ok":
            kp, ki, ach, ev = _polish_att(
                lm_axis, group, rate_gains, kp, ki, targets, act_kw,
                max_evals=max(0, max_evals - evals),
            )
            evals += ev
            gains[f"{group}.kp"], gains[f"{group}.ki"] = kp, ki
            achieved[f"{group}_att"] = ach
    return {"gains": gains, "achieved": achieved, "status": status,
            "notes": notes, "evals": evals}


def _polish_att(lm_axis, group, rate_gains, kp0, ki0, targets, act_kw, max_evals) -> tuple:
    """선택적 마무리 — Nelder-Mead(kp·ki 로그 배율), 목적 = −교차 대역폭 + 마진 벌점."""
    from scipy.optimize import minimize

    def cost(x):
        kp, ki = kp0 * math.exp(x[0]), ki0 * math.exp(x[1])
        m, _ = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
        pen = 0.0
        if math.isfinite(m["pm_deg"]):
            pen += 10.0 * max(0.0, targets.pm_deg - m["pm_deg"])
        if math.isfinite(m["gm_db"]):
            pen += 10.0 * max(0.0, targets.gm_db - m["gm_db"])
        bw = m["wcp"] if math.isfinite(m["wcp"]) else 0.0
        return -bw + pen

    if max_evals < 4:
        m, orient = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp0, ki0, **act_kw))
        return kp0, ki0, {**m, "orientation": orient}, 1
    res = minimize(cost, [0.0, 0.0], method="Nelder-Mead",
                   options={"maxfev": max_evals, "xatol": 1e-3, "fatol": 1e-3})
    kp, ki = kp0 * math.exp(res.x[0]), ki0 * math.exp(res.x[1])
    m, orient = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
    if math.isfinite(m["pm_deg"]) and m["pm_deg"] >= targets.pm_deg:
        return kp, ki, {**m, "orientation": orient, "polished": True}, int(res.nfev) + 1
    m0, o0 = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp0, ki0, **act_kw))
    return kp0, ki0, {**m0, "orientation": o0}, int(res.nfev) + 2  # 후퇴 — 마무리가 악화시켰다


def tune_points(
    aircraft, points, lms, trims, *, design, targets=None,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    polish=False, max_evals=60, on_progress=None,
) -> dict:
    """앵커 전체 튜닝 → gain surface 샘플 — {"gains": {자리: {이름: 값}}, "results", "aborted"}.

    trimmable=False·미수렴 앵커는 건너뛰고 skipped로 보고한다 (조용한 누락 금지).
    """
    from claw.design.points import ROLE_ANCHOR

    targets = targets if targets is not None else TuneTargets()
    anchors = points.by_role(ROLE_ANCHOR)
    gains: dict = {}
    results: dict = {}
    skipped: list = []
    aborted = None
    total = len(anchors)
    for done, pt in enumerate(anchors, start=1):
        name = pt.case.name
        tr = trims.get(name)
        if tr is None or not tr.converged or pt.trimmable is False:
            skipped.append(name)
        else:
            out = tune_point(
                lms.get(aircraft, tr), design, targets=targets,
                actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
                delay_s=delay_s, pade_order=pade_order,
                polish=polish, max_evals=max_evals,
            )
            results[name] = out
            for slot, v in out["gains"].items():
                gains.setdefault(slot, {})[name] = v
        if on_progress is not None and on_progress(done, total, f"tune {name}"):
            aborted = "cancelled"
            break
    return {
        "gains": gains, "results": results, "skipped": skipped,
        "aborted": aborted, "targets": targets.to_dict(),
    }
