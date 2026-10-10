"""보강 — 보강 지표 d · 허용치·예산·합격 기준 분리 (05 §11.7 — 이관 4단계).

검증 구간(절점 사이, 또는 앞선 보강이 쪼갠 조각)의 중간점에서 판정 자리마다

    d = |m_mid − lerp(m_a, m_b, t)| / s

를 잰다 — 양끝 점 사이를 직선으로 이었을 때 중간점 지표가 그 선에서 벗어난 양을 보강 척도 s로 나눈 값이다. 선형 보간 표의
최악이 중점이 아닐 수 있어 두는 **격자 규칙**이지 판정선이 아니다(보강 허용치와 성능 합격선은 별개 — 분포를 보고 합격선을
완화하지 않는다).

- **척도 s는 튜닝 목표와 독립이다**(04 §1 세 층 분리): ζ(피치·요 레이트)는 권장선 − 합격선의 폭, PM(자세)은 권장선이 없어
  독립 잠정 상수 5°, λ_roll은 판정선이 목표의 비율이라 기준 독립화 전까지 당시 값(목표 12 × (0.8 − 0.5) = 3.6 rad/s)으로 고정한다.
  목표를 바꿔도 보강 우선순위가 움직이지 않게 — 실험 코드 d_scales와 같은 규칙이다
- **허용치 tol 0.10 [기본값 — 2026-10-10]** — 합격–권장 폭(척도 s)의 10 %. 첫 실측(S1 한 줄 5구간 자리별 최대 d
  0.008~0.037 · 축소 격자 0.046/0.17)을 넘는 자리에서 잡힌다. 단일 값이 기본이고 자리별 값 {slot: tol}도 받는다(빠진 자리는
  단일 기본값 — 자리별 기본값은 분포가 쌓이면 [TBD]). None이면 이분하지 않고 d 분포만 보고한다(tol_unset)
- 허용치가 있으면 자리별 d가 그 자리 허용치를 넘는 구간을 최악(d / 허용치)부터 그 구간의 중간점에서 둘로 나누고 두 조각의
  중점을 새 검증점으로 잰다. **이웃 판정이 다른 구간**(양끝·중간의 최악 자리 판정 ok·warn·fail이 갈림)은 d와 무관한 별도
  보강 사유로 쪼갠다(on_verdict_change, 기본 켬) — 척도만으로는 판정이 뒤집히지 않음을 보장하지 못해서다. 판정 다름만으로
  쪼갠 구간이 깊이 max_depth에 닿으면 판정이 바뀌는 자리를 그 폭까지 좁힌 것이라 남은 구간이 아니다(d 초과는 깊이에 닿아도
  남은 구간). 합격선 근접 보강(near_line_frac)은 예약 칸만 있고 아직 쓰지 않는다 [TBD]
- 예산(추가점 · 이분 깊이 · 시간)은 실행 **전에** 받는다 — 예산이 끊기면 「보강 종료 · 추가 검증 필요」(남은 구간과 최대
  d)이고 합격이나 설계 불가로 바꾸지 않는다
- **잴 수 없는 구간은 사라지지 않는다** — 양끝·중간 중 계산 불가(트림 실패·요구영역 밖·미계산)나 지표가 없는 자리는 「잴 수
  없는 구간」 목록에 남고, 보강 대상을 다 끝내도 그런 구간이 있으면 「보강 완료」가 아니다(실험 코드가 조용히 버려 「보강
  완료」로 보고됐던 결함 — 05 §11.10 리뷰)

루프(재계산) 자체는 오케스트레이터(_stage_verify)가 돈다 — 여기는 점을 고르고 상태를 정하는 순수 함수다.
"""

from __future__ import annotations

import math

import numpy as np

from claw.common.contracts import TrimCase
from claw.design.points import ROLE_VALIDATION, OperatingPoint, case_name
from claw.opspace.states import NOT_RUN, STATE_LABEL

# 보강 지표에 쓰는 자리별 대표 지표 (05 §11.7) — 레이트 자리는 모드 지표(ζ·λ), 자세 자리는 PM
D_METRIC = {"pitch_rate": "zeta", "yaw_rate": "zeta", "roll_rate": "roll_lambda",
            "pitch_att": "pm_deg", "roll_att": "pm_deg"}
# 권장선이 없는 PM의 보강 척도 — 튜닝 목표(50° − 45°)에서 계산하지 않는 독립 잠정값 (05 §11.7) [잠정]
PM_D_SCALE_PROVISIONAL = 5.0  # [deg]
# λ_roll 판정선은 아직 목표의 비율이라 두 선의 폭도 목표에 매인다 — 기준값이 독립될 때까지 당시 값
# (목표 12 × (권장 0.8 − 합격 0.5))으로 고정해, 목표를 바꿔도 척도가 움직이지 않게 한다 (05 §11.7) [잠정]
ROLL_LAMBDA_D_SCALE_PROVISIONAL = 3.6  # [rad/s]

# [기본값 — 사용자 결정 2026-09-30 · 허용치 2026-10-10] 허용치 0.10(척도 s의 10 %, 단일 값) · 추가점 24 · 이분 깊이 3 ·
# 시간 제한 없음 · 이웃 판정 다름도 쪼갬 · 합격선 근접(near_line_frac)은 예약(None — 미구현)
DEFAULT_TOL = 0.10
DEFAULT_REINFORCE = {"tol": DEFAULT_TOL, "max_points": 24, "max_depth": 3, "max_time_s": None,
                     "on_verdict_change": True, "near_line_frac": None}
# 구간별 보강 상태(reinforcement.intervals[].status) — 쪼갬 · 쪼갤 사유가 남음(예산·깊이) · 잴 수 없음 · 충족
INTERVAL_STATUS = ("split", "remaining", "unmeasured", "ok")
MAX_REINFORCE_POINTS = 200  # 서버 점 상한(MAX_POINTS)과 같은 수 — 그 위는 점 예산이 먼저 막는다
MAX_REINFORCE_DEPTH = 8
REINFORCE_STATUS_TEXT = {
    "tol_unset": "허용치 미설정 — d 분포만",
    "done": "보강 완료",
    "budget": "보강 종료 · 추가 검증 필요",
    "unmeasured": "보강 종료 · 잴 수 없는 구간 있음",
}

_EPS = 1e-9


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def d_scales(criteria) -> dict:
    """자리별 보강 척도 s — **튜닝 목표와 독립**(인자가 판정 기준뿐이다). ζ는 권장선 − 합격선, PM·λ는 독립 잠정값."""
    zeta = abs(float(criteria.zeta_good) - float(criteria.zeta_min))
    return {"pitch_rate": zeta, "yaw_rate": zeta, "roll_rate": ROLL_LAMBDA_D_SCALE_PROVISIONAL,
            "pitch_att": PM_D_SCALE_PROVISIONAL, "roll_att": PM_D_SCALE_PROVISIONAL}


def d_scale_sources(criteria) -> dict:
    """자리별 척도의 출처 문구 — 결과에 함께 싣는다(λ는 고정한 당시 값을 적는다)."""
    z = (f"권장선 ζ_good {criteria.zeta_good!r} − 합격선 ζ_min {criteria.zeta_min!r} (기체 기준, 튜닝 목표 무관)")
    pm = (f"독립 잠정 척도 {PM_D_SCALE_PROVISIONAL!r}° — PM은 권장선이 없다(합격 아니면 불합격). 튜닝 목표에서 계산하지 않는다")
    lam = (f"잠정 고정 {ROLL_LAMBDA_D_SCALE_PROVISIONAL!r} rad/s = 당시 목표 12 × (권장 비율 0.8 − 합격 비율 0.5) "
           "(λ 판정선의 기준 독립화 전까지)")
    return {"pitch_rate": z, "yaw_rate": z, "roll_rate": lam, "pitch_att": pm, "roll_att": pm}


def check_reinforce_config(cfg: dict) -> dict:
    """보강 설정 검증 — 정규형 dict(AutoDesignConfig가 부른다 — 서버 422도 이 ValueError다). 없는 칸은 기본값."""
    if not isinstance(cfg, dict):
        raise ValueError(f"reinforce는 dict: {cfg!r}")
    unknown = sorted(set(cfg) - set(DEFAULT_REINFORCE))
    if unknown:
        raise ValueError(f"reinforce: 미정의 키 {unknown} — 허용: {sorted(DEFAULT_REINFORCE)}")
    out = {**DEFAULT_REINFORCE, **cfg}
    tol = out["tol"]
    if isinstance(tol, dict):
        # 자리별 허용치 — 아는 자리만, 빠진 자리는 단일 기본값으로 채운 정규형(적용되는 값이 설정에 다 보이게)
        bad = [k for k in tol if k not in D_METRIC]
        if not tol or bad:
            raise ValueError(f"reinforce.tol 자리별 값은 {sorted(D_METRIC)} 중에서(비어 있지 않게): {bad or tol!r}")
        for slot, v in tol.items():
            if not _finite(v) or v <= 0:
                raise ValueError(f"reinforce.tol.{slot}은 양의 유한값: {v!r}")
        out["tol"] = {slot: float(tol.get(slot, DEFAULT_TOL)) for slot in D_METRIC}
    elif tol is not None:
        if not _finite(tol) or tol <= 0:
            raise ValueError(f"reinforce.tol은 양의 유한값·자리별 값 {{slot: 값}}·없음(허용치 미설정 — d 분포만): {tol!r}")
        out["tol"] = float(tol)
    if not isinstance(out["on_verdict_change"], bool):  # 참거짓만 — 0/1이나 "false"를 참거짓으로 읽지 않는다
        raise ValueError(f"reinforce.on_verdict_change는 참/거짓: {out['on_verdict_change']!r}")
    if out["near_line_frac"] is not None:  # 예약 칸 — 값은 검사만 하고 아직 쓰지 않는다
        if not _finite(out["near_line_frac"]) or not 0 < out["near_line_frac"] <= 1:
            raise ValueError(f"reinforce.near_line_frac은 0 초과 1 이하 또는 없음(예약 — 미구현): {out['near_line_frac']!r}")
        out["near_line_frac"] = float(out["near_line_frac"])
    for key, lo, hi in (("max_points", 0, MAX_REINFORCE_POINTS), ("max_depth", 1, MAX_REINFORCE_DEPTH)):
        v = out[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not lo <= v <= hi:
            raise ValueError(f"reinforce.{key}은 {lo}~{hi} 정수: {v!r}")
        out[key] = int(v)
    if out["max_time_s"] is not None:
        if not _finite(out["max_time_s"]) or out["max_time_s"] <= 0:
            raise ValueError(f"reinforce.max_time_s는 양의 유한값 또는 없음: {out['max_time_s']!r}")
        out["max_time_s"] = float(out["max_time_s"])
    return out


def tol_for(tol, slot):
    """자리의 허용치 — 단일 값이면 그 값, 자리별이면 그 자리 값(빠진 자리는 단일 기본값), 미설정이면 None."""
    if tol is None:
        return None
    return float(tol.get(slot, DEFAULT_TOL)) if isinstance(tol, dict) else float(tol)


def _excess(r, tol) -> float:
    """d / 그 자리 허용치 — 1을 넘으면 허용치 초과. 허용치가 없으면 d 그대로(순서만 쓴다)."""
    t = tol_for(tol, r["slot"])
    return r["d"] / t if t else r["d"]


def _key(r) -> tuple:
    return tuple(r["row"]), float(r["interval"][0]), float(r["interval"][1])


def _metric(case, slot):
    v = (((case or {}).get("loops") or {}).get(slot) or {}).get(D_METRIC[slot])
    return float(v) if _finite(v) else None


def _worst_status(case):
    sts = [m.get("status") for m in ((case or {}).get("loops") or {}).values()]
    for s in ("fail", "warn", "ok"):
        if s in sts:
            return s
    return None


def _interval_of(entry, knots):
    """(a, b, depth) — 내분점은 둘러싼 절점, 보강점은 자기 조각. 절점 밖(clip)이면 None."""
    if entry["kind"] == "reinforce":
        a, b = entry["interval"]
        return float(a), float(b), int(entry.get("depth", 1))
    m = entry["mach"]
    lo = [k for k in knots if k < m - _EPS]
    hi = [k for k in knots if k > m + _EPS]
    if not lo or not hi:
        return None
    return lo[-1], hi[0], 0


def segment_d(entries, margin_cases, union, scales) -> dict:
    """보강 지표 — {"d": [{row, interval, slot, d, t, point, mach, depth}], "unmeasured": [{row, interval, point, why(, slot)}],
    "verdict_change": 구간 수, "verdict_change_intervals": [{row, interval}], "intervals": [{row, interval, point, mach, depth,
    points(양끝·중간 이름), verdicts{a, mid, b} | None(판정 없음)}]} — intervals는 본 구간 전부(잴 수 없는 구간 포함).

    잰 자리: 검증 행(row가 있는) 내분점·보강점. 양끝은 같은 행의 절점(보강점은 자기 조각 끝) 점이다. 끝·중간 점 하나라도 결과가
    없거나(미계산·요구영역 밖 등 — 계획 상태를 이유로 적는다) 트림이 안 서 판정이 없으면 그 구간 전체를, 한 자리 지표만 없으면
    그 자리를 unmeasured에 남긴다 — 조용히 빼지 않는다. 판정이 이웃 사이에서 다른 구간(최악 자리 판정 ok·warn·fail 기준)도
    센다 — 척도만으로 판정이 뒤집히지 않음을 보장하지 못해서 두는 별도 보강 사유다(05 §11.7)."""
    knots = sorted(float(k) for k in union)
    by_name: dict = {}
    for e in entries:  # 같은 이름의 재기만 하는 항목(measure_only)이 본 항목의 상태를 덮지 않게
        if not e.get("measure_only"):
            by_name.setdefault(e["name"], e)
    for e in entries:
        by_name.setdefault(e["name"], e)
    d_out, unmeasured, changed, seen = [], [], [], {}

    def why_of(name):
        case = margin_cases.get(name)
        if case is None:
            e = by_name.get(name)
            if e is None:  # 행의 요구 마하 범위가 첫·끝 절점 안쪽에서 끝난다 — 그 절점에는 검증점이 없다
                return "절점 점이 계획에 없다 — 이 행의 마하 범위 밖"
            return f"{STATE_LABEL[e['pre_state']]} — 결과 없음"
        if not case.get("loops"):
            return "트림 미수렴 — 판정 없음"
        return None

    for e in entries:
        if e["kind"] not in ("midpoint", "reinforce") or e["row"] is None:
            continue
        if e.get("gap"):  # 중점을 둘 수 없는 조각 — 버리지 않고 사유와 함께 남긴다
            unmeasured.append({"row": list(e["row"]), "interval": list(e["interval"]), "point": None, "why": e["gap"]})
            seen.setdefault(_key(e), {"row": list(e["row"]), "interval": list(e["interval"]), "point": None,
                                      "mach": None, "depth": int(e.get("depth", 1)), "points": [], "verdicts": None})
            continue
        iv = _interval_of(e, knots)
        if iv is None:
            continue
        a, b, depth = iv
        alt, fuel = e["row"]
        row, interval = [alt, fuel], [a, b]
        ends = (case_name(a, alt, fuel), e["name"], case_name(b, alt, fuel))
        whys = [(tag, why_of(n)) for tag, n in zip(("끝점", "중간점", "끝점"), ends)]
        bad = [f"{tag} {w}" for tag, w in whys if w]
        info = seen.setdefault((tuple(row), float(a), float(b)), {
            "row": row, "interval": interval, "point": e["name"], "mach": float(e["mach"]), "depth": depth,
            "points": list(ends), "verdicts": None})
        if bad:
            unmeasured.append({"row": row, "interval": interval, "point": e["name"], "why": " · ".join(bad)})
            continue
        cases = [margin_cases[n] for n in ends]
        t = (e["mach"] - a) / (b - a)
        for slot, s in scales.items():
            vals = [_metric(c, slot) for c in cases]
            if not (s > 0) or any(v is None for v in vals):
                unmeasured.append({"row": row, "interval": interval, "point": e["name"], "slot": slot,
                                   "why": f"{slot} 지표 없음(비유한·미정의)" if s > 0 else f"{slot} 척도 미설정"})
                continue
            d = abs(vals[1] - (vals[0] + t * (vals[2] - vals[0]))) / s
            d_out.append({"row": row, "interval": interval, "slot": slot, "d": d, "t": t, "point": e["name"],
                          "mach": e["mach"], "depth": depth})
        verdicts = [_worst_status(c) for c in cases]
        if info["verdicts"] is None:
            info["verdicts"] = dict(zip(("a", "mid", "b"), verdicts))
        if len(set(verdicts) - {None}) > 1 and {"row": row, "interval": interval} not in changed:
            changed.append({"row": row, "interval": interval})
    return {"d": d_out, "unmeasured": unmeasured, "verdict_change": len(changed), "verdict_change_intervals": changed,
            "intervals": list(seen.values())}


def _split_parents(entries) -> set:
    return {(tuple(e["row"]), float(e["parent"][0]), float(e["parent"][1]))
            for e in entries if e.get("kind") == "reinforce" and e.get("parent") is not None}


def _worst_by_interval(dres, tol=None) -> dict:
    """(row, a, b) → 그 구간 자리별 d / 그 자리 허용치가 최대인 레코드 — 그 값이 1을 넘으면(어느 자리든 허용치 초과) 쪼갠다
    (D3). 단일 허용치·미설정이면 자리별 d의 최대와 같다."""
    out: dict = {}
    for r in dres["d"]:
        key = _key(r)
        if key not in out or _excess(r, tol) > _excess(out[key], tol):
            out[key] = r
    return out


def _flip_keys(dres) -> set:
    return {_key(c) for c in dres.get("verdict_change_intervals", ())}


def _triggers(dres, tol, on_verdict_change) -> dict:
    """쪼갤 사유가 있는 구간 → {"r": 최악 d 레코드 | None, "reasons": ["d", "verdict_change"] 부분, "mach", "depth"}.
    허용치가 없으면 아무 구간도 아니다(보강 끔 — 판정 다름도 쪼개지 않는다)."""
    if tol is None:
        return {}
    worst = _worst_by_interval(dres, tol)
    flips = _flip_keys(dres) if on_verdict_change else set()
    info = {_key(i): i for i in dres.get("intervals", ())}
    out = {}
    # 순서를 고정한다 — d 레코드 순(옛 동작) 다음 판정 다름만인 구간(정렬). 집합 순회는 같은 값의 구간 순서를 흔든다
    for key in dict.fromkeys([*worst, *sorted(flips)]):
        r = worst.get(key)
        reasons = (["d"] if r is not None and r["d"] > tol_for(tol, r["slot"]) else []) + (
            ["verdict_change"] if key in flips else [])
        src = r if r is not None else info.get(key)
        if not reasons or src is None or src.get("mach") is None:
            continue  # 판정 다름인데 중간점을 모르는 구간(이 함수 밖에서 만든 dres) — 쪼갤 자리가 없다
        out[key] = {"r": r, "reasons": reasons, "mach": float(src["mach"]), "depth": int(src["depth"])}
    return out


def reinforce_candidates(dres, *, tol, max_points_left, max_depth, points, entries=(), on_verdict_change=False) -> list:
    """이분할 새 검증점의 계획 항목 — 최악 d 구간부터. 구간 [a, b]를 잰 중간점 p에서 [a, p]·[p, b]로 나누고 두 조각의 중점을
    더한다(항목 kind "reinforce" · origin `reinforce:<자리>:<lo>|<hi>` · interval 조각 · parent [a, b] · depth).

    한 이분은 두 조각이 한 묶음이다 — 조각마다 항목이 **반드시** 하나 나온다(하나라도 빠지면 그 조각은 d도 남은 구간도
    잴 수 없는 구간도 아니게 되어 「보강 완료」가 거짓으로 뜬다 — 리뷰 MUST 1):
    - 새 점: existing False — 점 예산을 쓴다
    - 중점이 이미 점(설계점 등): existing True — 공짜(절점 자리 설계점과 같다). 그 이름이 이미 계획 항목이거나 이 판의 다른
      조각이면 measure_only(요청 수에 두 번 세지 않고 d만 잰다)
    - 조각이 반올림 자릿수보다 좁아 중점을 둘 자리가 없음: gap(사유) · measure_only — 점이 아니고 segment_d가 「잴 수 없는
      구간」으로 남긴다

    쪼갤 사유는 자리별 d > 그 자리 허용치(reasons "d")와, on_verdict_change면 이웃 판정 다름("verdict_change" — d와 무관)이다.
    순서는 d / 허용치가 큰 구간부터(판정 다름만인 구간은 그 뒤). 사유가 없는 구간 · 깊이 max_depth에 닿은 구간 · 이미 쪼갠
    구간(entries의 parent)은 건너뛴다. 새 점이 max_points_left를 넘게 되는 구간에서 멈춘다. 항목의 slot·d_trigger는 최악 자리와
    그 d(판정 다름만이면 d를 잰 자리가 없을 때 None), reasons는 쪼갠 사유다."""
    from claw.design.refine import _ROUND  # 순환 import 회피 — 중점 반올림 자릿수의 정본은 refine

    if tol is None:
        return []
    split = _split_parents(entries)
    planned = {e["name"] for e in entries if not e.get("gap")}
    out, taken, n_new = [], set(), 0
    trig = _triggers(dres, tol, on_verdict_change)
    order = sorted(trig.items(), key=lambda kv: (-("d" in kv[1]["reasons"]),
                                                 -(_excess(kv[1]["r"], tol) if kv[1]["r"] else 0.0)))
    for key, tg in order:
        r = tg["r"]
        if tg["depth"] >= max_depth or key in split:
            continue
        (alt, fuel), a, b = key
        p = tg["mach"]
        tag = r["slot"] if "d" in tg["reasons"] else "verdict_change"
        new = []
        for lo, hi in ((a, p), (p, b)):
            q = round((lo + hi) / 2.0, _ROUND)
            base = {"mach": q, "alt": alt, "fuel": fuel, "kind": "reinforce", "row": [alt, fuel],
                    "origin": f"reinforce:{tag}:{lo:.12g}|{hi:.12g}", "pre_state": NOT_RUN,
                    "interval": [lo, hi], "parent": [a, b], "depth": tg["depth"] + 1,
                    "slot": r["slot"] if r else None, "d_trigger": r["d"] if r else None,
                    "reasons": list(tg["reasons"])}
            if not lo + _EPS < q < hi - _EPS:
                # 이름을 점 이름과 겹치지 않게 — 점 집합·결과에서 찾히면 안 된다
                new.append({**base, "name": f"gap:{case_name(q, alt, fuel)}:{lo:.12g}|{hi:.12g}", "existing": False,
                            "measure_only": True,
                            "gap": f"조각 M{lo:.12g}–M{hi:.12g}이 반올림 자릿수({_ROUND})보다 좁아 중점을 둘 수 없다"})
                continue
            name = case_name(q, alt, fuel)
            existing = name in points or name in taken
            new.append({**base, "name": name, "existing": existing,
                        "measure_only": existing and (name in planned or name in taken)})
        cost = sum(1 for e in new if not e["existing"] and not e.get("gap"))
        if cost and n_new + cost > max_points_left:
            break
        out.extend(new)
        n_new += cost
        taken.update(e["name"] for e in new if not e.get("gap"))
    return out


def reinforce_points(dres, *, tol, max_points_left, max_depth, points, entries=(), on_verdict_change=False) -> list:
    """reinforce_candidates의 **새** 검증점(OperatingPoint, 역할 validation) — 점 집합에 더할 것(공짜·gap 항목 제외)."""
    return [OperatingPoint(case=TrimCase(name=e["name"], mach=e["mach"], alt=e["alt"], fuel=e["fuel"]),
                           role=ROLE_VALIDATION, origin=e["origin"])
            for e in reinforce_candidates(dres, tol=tol, max_points_left=max_points_left, max_depth=max_depth,
                                          points=points, entries=entries, on_verdict_change=on_verdict_change)
            if not e["existing"] and not e.get("gap")]


def reinforce_intervals(dres, entries, *, tol, on_verdict_change=False, max_depth=None) -> list:
    """구간별 보강 기록 — ⑥(다음 단계)의 입력. [{row, interval, depth, slot, d, tol, exceeds, verdict_change, verdicts{a, mid, b},
    points, status, reasons, why}] (본 구간 전부 · 행·구간 순).

    slot·d는 d / 허용치가 최대인 자리와 그 d(잰 자리가 없으면 None), tol은 그 자리 허용치, exceeds는 그 d가 허용치를 넘음,
    verdict_change는 양끝·중간 판정이 갈림(사실 — on_verdict_change와 무관하게 적는다), points는 양끝·중간 점 이름, reasons는
    쪼갤 사유(허용치 미설정이면 []). status: split 쪼갬(자식 조각이 대신 잰다) · remaining 사유가 있는데 쪼개지 못함(추가점·
    깊이·시간 예산 — 판정 다름만인 구간이 깊이에 닿은 것은 판정이 바뀌는 자리를 그 폭까지 좁힌 것이라 아니다) · unmeasured
    한 자리라도 잴 수 없음(why) · ok 충족."""
    split = _split_parents(entries)
    worst = _worst_by_interval(dres, tol)
    flips = _flip_keys(dres)
    trig = _triggers(dres, tol, on_verdict_change)
    info = {_key(i): i for i in dres.get("intervals", ())}
    un: dict = {}
    for u in dres.get("unmeasured", ()):
        un.setdefault(_key(u), []).append(u)
    keys = list(dict.fromkeys([*info, *worst, *un]))
    out = []
    for key in sorted(keys, key=lambda k: (k[0], k[1], k[2])):
        r, i, tg = worst.get(key), info.get(key, {}), trig.get(key)
        t = tol_for(tol, r["slot"]) if r is not None else (None if isinstance(tol, dict) else tol)
        depth = int(r["depth"] if r is not None else i.get("depth", 0))
        localized = (tg is not None and tg["reasons"] == ["verdict_change"] and max_depth is not None
                     and depth >= max_depth)
        if key in split:
            status = "split"
        elif tg is not None and not localized:
            status = "remaining"
        elif key in un:
            status = "unmeasured"
        else:
            status = "ok"
        out.append({"row": list(key[0]), "interval": [key[1], key[2]], "depth": depth,
                    "slot": r["slot"] if r else None, "d": r["d"] if r else None, "tol": t,
                    "exceeds": bool(r is not None and t is not None and r["d"] > t),
                    "verdict_change": key in flips, "verdicts": i.get("verdicts"),
                    "points": list(i.get("points") or ([r["point"]] if r else [])),
                    "status": status, "reasons": list(tg["reasons"]) if tg else [],
                    "why": " · ".join(f"{u['slot']}: {u['why']}" if u.get("slot") else u["why"] for u in un[key])
                    if key in un else None})
    return out


def reinforce_status(dres, entries, *, tol, on_verdict_change=False, max_depth=None) -> dict:
    """보강 상태 — {"status", "label", "remaining": [{row, interval, d, slot, tol, reasons}], "max_d_remaining", "unmeasured":
    구간 수}.

    남은 구간은 reinforce_intervals의 remaining — 쪼갤 사유(d > 허용치 · 판정 다름)가 있는데 깊이·추가점·시간 예산에 막혀
    쪼개지 못한 잎 구간이다. 남은 구간이 있으면 budget, 없는데 잴 수 없는 구간이 있으면 unmeasured, 둘 다 없어야 done이다.
    tol이 없으면 tol_unset(이분하지 않았다)."""
    n_un = len({_key(u) for u in dres.get("unmeasured", ())})
    if tol is None:
        return {"status": "tol_unset", "label": REINFORCE_STATUS_TEXT["tol_unset"], "remaining": [],
                "max_d_remaining": None, "unmeasured": n_un}
    rows = [iv for iv in reinforce_intervals(dres, entries, tol=tol, on_verdict_change=on_verdict_change,
                                             max_depth=max_depth) if iv["status"] == "remaining"]
    remaining = sorted(({"row": iv["row"], "interval": iv["interval"], "d": iv["d"], "slot": iv["slot"], "tol": iv["tol"],
                         "reasons": iv["reasons"]} for iv in rows),
                       key=lambda x: (-("d" in x["reasons"]), -(x["d"] / x["tol"] if x["d"] is not None and x["tol"]
                                                               else 0.0)))
    top = max((x["d"] for x in remaining if x["d"] is not None), default=0.0)
    if remaining:
        status = "budget"
        over = [x for x in remaining if "d" in x["reasons"]]
        n_vc = sum("verdict_change" in x["reasons"] for x in remaining)
        label = f"{REINFORCE_STATUS_TEXT['budget']} — 남은 구간 {len(remaining)}개"
        if over:
            label += f" · 최대 d {over[0]['d']:.3g} > 허용치 {over[0]['tol']:g}"
        if n_vc:
            label += f" · 이웃 판정 다름 {n_vc}"
    elif n_un:
        status, label = "unmeasured", REINFORCE_STATUS_TEXT["unmeasured"]
    else:
        status, label = "done", REINFORCE_STATUS_TEXT["done"]
    return {"status": status, "label": label, "remaining": remaining, "max_d_remaining": top, "unmeasured": n_un}


def split_reasons(entries) -> dict:
    """쪼갠 구간 수의 사유별 합 — {"d": n, "verdict_change": m}(한 구간이 둘 다면 둘에 센다). 보강 항목의 reasons를 부모
    구간마다 한 번 센다(사유를 적기 전 세션의 항목은 d로 센다 — 그때는 d만 사유였다)."""
    by: dict = {}
    for e in entries:
        if e.get("kind") == "reinforce" and e.get("parent") is not None:
            by.setdefault((tuple(e["row"]), float(e["parent"][0]), float(e["parent"][1])), e.get("reasons") or ["d"])
    return {k: sum(k in v for v in by.values()) for k in ("d", "verdict_change")}


def d_distribution(dres) -> dict:
    """자리별 d 분포 — {slot: {n, max, p50, p90}} (허용치 [TBD]를 정할 실측 자료)."""
    by: dict = {}
    for r in dres["d"]:
        by.setdefault(r["slot"], []).append(float(r["d"]))
    return {slot: {"n": len(v), "max": max(v), "p50": float(np.percentile(v, 50)), "p90": float(np.percentile(v, 90))}
            for slot, v in by.items()}
