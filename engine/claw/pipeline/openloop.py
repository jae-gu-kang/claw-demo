"""2단 개루프 — 게인 Δ가 케이스별 개루프 마진(PM/GM)을 얼마나 움직이는가.

influence.py 머리말의 `openloop_delta` 이름 계약을 이 파일이 구현한다 (influence가
760줄이라 분리). 핵심 비용 구조: **LinearModel은 게인과 무관하다** — 케이스당
`linearize()` 1회면 기준/섭동 게인의 `pi_loop()`+`loop_margins()` 재계산은 ms
단위다. 재선형화하지 않는다.

**GROUP_LOOPS는 유도가 아니라 선언이다** (METRICS의 declared 간선과 같은 지위).
FCL 게인 → SISO 루프 대응은 그래프에서 기계적으로 나오지 않는다: SCAS 한 축의
PI+레이트 중첩을 자세 루프(θ←δe)와 레이트 루프(q←δe)의 두 SISO 근사로 나눠 본다.
레이트 루프 3개는 웹 마진 탭의 DEFAULT_LOOPS(lib/loops.js — pitch q←de·roll
p←da·yaw r←dr, sign −1)와 정합이며 test_openloop이 핀한다. 선언에 없는 자리
(믹서·리미터·요축 자세 PI — 분리모델에 β/ψ/h 상태가 없다)는 Δ=0으로 위장하지
않고 **no_loop로 분리 보고**한다.

스케줄이 덮는 상수(그 자리에 테이블이 붙어 있는 fcl/* 게인)는 "1단은 잡는데
2단이 0인 자리"(influence 머리말) — **overridden으로 분리 보고**하고, 실효
손잡이인 `table.그룹.게인` 배율은 케이스 실효 게인(테이블@케이스 × 배율)으로
루프에 잡는다.
"""

import numpy as np

from claw.analysis import loop_margins, pi_loop
from claw.fcl.graphs import AP_PARAM
from claw.pipeline.influence import Shape, make_law, param_universe, probe_value
from claw.trim import linearize, split_axes

# 그룹 → SISO 루프 선언. gains: pi_loop 인자(kp·ki) → 그룹 게인 키.
# sign −1: 데모 부호 관례(Cmde<0 등)에서 음피드백 개루프가 양의 DC를 갖도록
# (analysis/margins.py pi_loop 참조). 속도 루프만 +1 — thr→u는 DC가 이미 양이다.
GROUP_LOOPS = {
    "pitch": (
        {"name": "pitch_att", "axis": "lon", "x_out": "theta", "u_in": "de",
         "sign": -1.0, "gains": {"kp": "kp", "ki": "ki"}},
        {"name": "pitch_rate", "axis": "lon", "x_out": "q", "u_in": "de",
         "sign": -1.0, "gains": {"kp": "k_rate"}},
    ),
    "roll": (
        {"name": "roll_att", "axis": "lat", "x_out": "phi", "u_in": "da",
         "sign": -1.0, "gains": {"kp": "kp", "ki": "ki"}},
        {"name": "roll_rate", "axis": "lat", "x_out": "p", "u_in": "da",
         "sign": -1.0, "gains": {"kp": "k_rate"}},
    ),
    "yaw": (
        # 요축 자세 오차는 −β(항법 추정)라 분리모델 상태로 직접 대응이 없다 —
        # 레이트 댐퍼 루프만 선언한다 (kp·ki는 no_loop로 남는 것이 맞다)
        # filter: 이 자리의 댐퍼는 워시아웃을 거친 rate를 먹는다 (01 §3.1, 데모
        # τ=2 s). 선언하지 않으면 루프가 정적 게인이 되어 **법칙에 있는 필터를
        # 안 본 마진**이 나온다 — 아래 _effective_filter가 법칙에서 실값을 읽는다
        {"name": "yaw_rate", "axis": "lat", "x_out": "r", "u_in": "dr",
         "sign": -1.0, "gains": {"kp": "k_rate"},
         "filter": ("washout", "washout_tau", "tau")},
    ),
    "speed": (
        {"name": "spd_u", "axis": "lon", "x_out": "u", "u_in": "thr",
         "sign": 1.0, "gains": {"kp": "kp", "ki": "ki"}},
    ),
    # alt·heading: 분리모델(lon: u,w,q,θ / lat: v,p,r,φ)에 h·ψ 상태가 없다 —
    # 그 외곽 루프는 3단(폐루프 스윕)에서만 보인다. 여기 선언하지 않는 것이 정직하다.
}

# AP 파라미터 이름 → (스케줄 그룹, 게인 키) — 정본 AP_PARAM의 역방향
_AP_GROUP_OF = {param: gk for gk, param in AP_PARAM.items()}


def _group_key(pid):
    """ParamRef id → (그룹, 게인 키) — 루프 대응이 없는 자리는 (None, None)."""
    if pid.startswith("table."):
        _, group, key = pid.split(".", 2)
        return group, key
    if pid.startswith("fcl/ScasAxis."):
        _, axis, key = pid.split(".", 2)
        return axis, key
    if pid.startswith("fcl/Autopilot."):
        gk = _AP_GROUP_OF.get(pid.split(".", 1)[1])
        return gk if gk is not None else (None, None)
    return None, None


def _effective_gain(law, group, key, case):
    """케이스 실효 게인 — 스케줄 자리는 테이블@케이스(배율 반영본), 아니면 상수.

    make_law가 gain_scale을 테이블 데이터에 이미 곱해 두므로(influence.make_law)
    조회값이 곧 배율 반영 실효값이다. 스케줄 필터는 준정적 조회라 생략한다 —
    트림점 해석과 같은 정상상태 전제다.
    """
    tables = law.schedule.tables if law.schedule is not None else {}
    name = f"{group}.{key}"
    if name in tables:
        t = tables[name]
        coords = {"mach": case.mach, "alt": case.alt, "fuel": case.fuel}
        return float(t.interp(**{ax: coords[ax] for ax in t.axis_names}))
    if group in ("pitch", "roll", "yaw"):
        return float(law.scas.cfg[group][key])
    return float(law.autopilot.cfg[AP_PARAM[(group, key)]])


def _effective_filter(law, group, sp):
    """루프 선언의 filter 항 → pi_loop 필터 스펙 (선언이 없거나 꺼져 있으면 None).

    선언은 (필터 종류, 법칙 파라미터 이름, 스펙 파라미터 이름)이다. 값 0은
    "그 필터 없음"이라는 법칙 쪽 관용(graphs.py: washout_tau > 0일 때만 노드 생성)을
    그대로 따른다 — 해석이 법칙에 없는 필터를 만들어 내지 않는다.

    위 _effective_gain의 "스케줄 필터는 준정적이라 생략" 주석과 **다른 사안**이다.
    그쪽은 게인 스케줄 변수의 입력 필터(정상상태 전제로 생략 가능)이고, 이쪽은
    피드백 경로에 직접 있는 댐퍼 필터라 루프 대역에서 그대로 작용한다.
    """
    decl = sp.get("filter")
    if decl is None:
        return None
    kind, law_param, spec_param = decl
    value = float(law.scas.cfg[group][law_param])
    if value <= 0.0:
        return None
    return {"kind": kind, spec_param: value}


def _delta(base, pert):
    out = {}
    for k in ("pm_deg", "gm_db"):
        b, p = base[k], pert[k]
        if np.isfinite(b) and np.isfinite(p):
            out[k] = float(p - b)
        elif b == p:  # inf == inf — 여유가 계속 무한이면 변화 없음
            out[k] = 0.0
        else:
            out[k] = float("nan")  # 유한↔무한 전이 — 수치 Δ가 정의되지 않는다
    return out


def openloop_delta(aircraft, trs, shape: Shape, param_ids=None, *,
                   probe_rel: float = 0.01, on_progress=None) -> dict:
    """케이스별 개루프 마진의 기준/섭동/Δ — 2단.

    trs: TrimResult 목록 (미수렴은 건너뛰고 경고). param_ids: ParamRef id 목록
    (None이면 루프 선언이 있는 전 자리). on_progress(done, total): 케이스 단위 —
    truthy 반환은 협조적 취소로 완료 케이스를 보존한다 (margin-map 패턴).
    """
    law = make_law(shape)
    universe = {r.id: r for r in param_universe(shape)}
    if param_ids is None:
        param_ids = [pid for pid in universe if _group_key(pid)[0] in GROUP_LOOPS]
    unknown = [pid for pid in param_ids if pid not in universe]
    if unknown:
        raise ValueError(f"알 수 없는 파라미터 id: {unknown}")

    tables = law.schedule.tables if law.schedule is not None else {}
    params: dict = {}
    active = []  # (pid, group, key, loops, probe_to)
    for pid in param_ids:
        ref = universe[pid]
        group, key = _group_key(pid)
        entry = {"status": "ok", "reason": None, "value": ref.value,
                 "probe_to": None, "loops": {}}
        params[pid] = entry
        if group not in GROUP_LOOPS:
            entry["status"] = "no_loop"
            entry["reason"] = "선언된 SISO 루프가 없는 자리 — 3단(폐루프)에서만 보인다"
            continue
        if pid.startswith("fcl/") and f"{group}.{key}" in tables:
            entry["status"] = "overridden"
            entry["reason"] = (f"게인 스케줄 {group}.{key}가 매 스텝 덮어쓴다 — "
                               f"실효 손잡이는 table.{group}.{key}")
            continue
        loops = [sp for sp in GROUP_LOOPS[group] if key in sp["gains"].values()]
        if not loops:
            entry["status"] = "no_loop"
            entry["reason"] = "이 게인 키를 쓰는 선언 루프가 없다"
            continue
        target, clipped = probe_value(ref, probe_rel)
        if target is None:
            entry["status"] = "error"
            entry["reason"] = clipped
            continue
        if pid.startswith("table.") and ref.value == 0.0:
            entry["status"] = "error"
            entry["reason"] = "배율 0 — 실효 게인이 0이라 상대 섭동이 정의되지 않는다"
            continue
        entry["probe_to"] = target
        entry["loops"] = {sp["name"]: {} for sp in loops}
        active.append((pid, group, key, loops, target))

    warnings = []
    cases = []
    aborted = None
    total = len(trs)
    for done, tr in enumerate(trs, start=1):
        if not tr.converged:
            warnings.append(f"미수렴 트림 케이스 건너뜀: {tr.case.name}")
            if on_progress is not None and on_progress(done, total):
                aborted = "cancelled"
                break
            continue
        lon, lat = split_axes(linearize(aircraft, tr))
        models = {"lon": lon, "lat": lat}
        base_cache = {}

        def margins_for(sp, gains, rate_filter=None):
            loop = pi_loop(models[sp["axis"]], x_out=sp["x_out"], u_in=sp["u_in"],
                           kp=gains.get("kp", 0.0), ki=gains.get("ki", 0.0),
                           sign=sp["sign"], rate_filter=rate_filter)
            return loop_margins(loop)

        for pid, group, key, loops, target in active:
            ref = universe[pid]
            for sp in loops:
                gains = {p: _effective_gain(law, group, k, tr.case)
                         for p, k in sp["gains"].items()}
                if all(v == 0.0 for v in gains.values()):
                    params[pid]["loops"][sp["name"]][tr.case.name] = {
                        "base": None, "perturbed": None, "delta": None,
                        "note": "제로 개루프 — 이 케이스 실효 게인이 전부 0",
                    }
                    continue
                rate_filter = _effective_filter(law, group, sp)
                if sp["name"] not in base_cache:
                    base_cache[sp["name"]] = margins_for(sp, gains, rate_filter)
                base = base_cache[sp["name"]]
                pert_gains = dict(gains)
                # 섭동 반영 — 배율 자리는 실효 게인에 비율로, 상수 자리는 값 직접
                slot = next(p for p, k in sp["gains"].items() if k == key)
                if pid.startswith("table."):
                    pert_gains[slot] = gains[slot] * (target / ref.value)
                else:
                    pert_gains[slot] = target
                pert = margins_for(sp, pert_gains, rate_filter)
                params[pid]["loops"][sp["name"]][tr.case.name] = {
                    "base": base, "perturbed": pert, "delta": _delta(base, pert),
                }
        cases.append(tr.case.name)
        if on_progress is not None and on_progress(done, total):
            aborted = "cancelled"
            break

    return {
        "fingerprint": shape.fingerprint(),
        "probe_rel": probe_rel,
        "cases": cases,
        "params": params,
        "warnings": warnings,
        "aborted": aborted,
    }
