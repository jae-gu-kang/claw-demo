"""δe_trim 표 도출 — 법칙 할당이 읽는 마하 표를 기체에서 잰다 (02 §5.6 · 02 §5.6.1).

할당은 선회 하중 n에서 롤 예산의 피치 몫을 먼저 뗀다: R = clip(δe_trim(M)·n, 0, resv_frac·B)(fcl/graphs.py
_roll_budget_nodes). 그 표는 기체의 1g 트림 승강타 요구다 — 예제 기체에서 M0.23의 14.88°부터 M0.6의 0.68°까지
22배 움직여 상수로는 양 끝을 못 맞춘다. 예제 표를 만든 절차(02 §5.6.1 `/law/alloc/de_trim`)를 코드로 옮겼다:

1. 요구 — 마하마다 연료 × 고도 격자로 trim_level을 돌려 최악 |δe|를 취한다. 수렴하지 않았거나 포화한 트림은
   뺀다(포화 트림의 δe는 요구가 아니라 한계다). 뺀 수를 출처에 적는다. 플랜트가 다른 형상 변형이 있으면 그
   변형들까지 재어 최악을 취하고, 잰 플랜트 지문을 모두 출처에 남긴다 — 표는 문서에 하나라 변형이 함께 쓴다.
   고도 격자는 기체의 운용 고도 범위로 거른다(범위 밖 고고도 트림이 요구를 부풀리면 선회 롤 권한을 더 묶는다).
2. 보정 — 표 격자 사이 선형보간(표는 clip 룩업이다)이 검사 격자(check_step 간격)의 요구를 밑돌면, 그 구간 양
   끝을 부족분만큼 올리기를 부족이 없어질 때까지 반복한다. 공유 끝점은 두 구간 중 큰 쪽만큼 올린다.

문서에 쓰지 않는다 — 결과 dict를 돌려주고 저장(새 리비전)은 호출자(서버 잡)가 한다. 출처에 plant_fingerprint를
남긴다: 플랜트가 바뀌면 BuiltProfile.alloc_trim_table이 낡은 표로 법칙을 조립하지 않는다.
"""

import bisect
import inspect
import math
import time

import numpy as np

from claw.common.contracts import TrimCase
from claw.design.points import case_name
from claw.trim import trim_level

DEFAULT_FUEL_FRACS = (0.0, 0.25, 0.5, 0.75, 1.0)  # × fuel_max [기본값] — 무게 전 범위에서 최악을 취한다
DEFAULT_ALTS = (0.0, 500.0, 1000.0, 1500.0, 2000.0, 2500.0, 3000.0)  # [m] [기본값] — 예제 표의 고도 7점(운용 범위로 거른다)
CHECK_STEP = 0.005  # [기본값] 검사 격자 마하 간격 — 예제 표를 검사한 간격
TABLE_STEP = 0.05  # [기본값] 표 격자가 문서에 없을 때 새로 만드는 간격
MAX_ITER = 20
DERIVE_SOURCE = "derive_de_trim"

REASON_NO_RANGE = "de_trim_no_range"
REASON_NO_REQUIREMENT = "de_trim_no_requirement"
REASON_NOT_CONVERGED = "de_trim_not_converged"
REASON_CANCELLED = "de_trim_cancelled"
REASON_TEXT = {
    REASON_NO_RANGE: "표 마하 격자를 정할 수 없다 — 문서에 δe_trim 표가 없고 공력 DB 마하 범위(aero.db_ranges.mach)도 없다",
    REASON_NO_REQUIREMENT: "표 격자에서 수렴·비포화 트림이 있는 마하가 둘 미만이다 — 트림 탭에서 성립 영역을 먼저 확인한다",
    REASON_NOT_CONVERGED: "보정을 다 돌려도 검사 격자에 요구를 밑도는 점이 남았다",
    REASON_CANCELLED: "취소됐다",
}


def _grid(built, machs):
    if machs is not None:
        return [float(m) for m in machs]
    alloc = built.doc["law"]["alloc"]
    if alloc is not None and alloc["de_trim"] is not None:
        return [float(m) for m in alloc["de_trim"]["table"]["axes"]["mach"]]
    r = built.doc["aero"]["db_ranges"]["mach"]
    if r is None:
        return None
    hi = min(float(r[1]), float(built.doc["structural"]["mach_no"]))
    lo = max(float(r[0]), TABLE_STEP)
    n = int(math.floor((hi - lo) / TABLE_STEP + 1e-9)) + 1
    return [round(lo + i * TABLE_STEP, 4) for i in range(n)] if n >= 2 else None


def _law_default_resv_frac() -> float:
    from claw.fcl.law import FlightControlLaw

    return float(inspect.signature(FlightControlLaw.__init__).parameters["alloc_resv_frac"].default)


def derive_de_trim(built, *, variants=(), machs=None, alts=None, fuel_fracs=DEFAULT_FUEL_FRACS,
                   check_step=CHECK_STEP, on_progress=None) -> dict:
    """BuiltProfile → {"ok", "reason", "reason_text", "alloc", "requirement", "elapsed_s"}.

    alloc은 law.alloc 모양({resv_frac, de_trim{source "derived", table, provenance}}) — resv_frac은 문서 값을
    그대로 두고, 할당 섹션이 없던 기체면 법칙 기본값이다. 표의 양 끝은 **요구가 있는 검사점**으로 정한다 — 첫(마지막)
    요구 검사점을 덮는 가장 안쪽 격자점까지 남기고 그 밖의 격자점은 표에서 뺀다(trimmed_machs). 격자점만 보고 자르면
    잘린 격자점과 첫 요구 격자점 사이의 검사점 요구가 버려져, clip 룩업이 끝값을 답하는 자리가 모자란다(격자 0.1·0.3에서
    M0.25 요구 0.188을 0.128로 답했다). 남긴 격자점 중 자기 요구가 없는 점은 요구 검사점들의 보간값으로 시작하고
    보정이 덮는다(undefined_machs) — 이웃 격자값을 복사하지 않는다. variants는 같은 문서의 형상 변형 BuiltProfile들 — 플랜트
    지문이 기본 문서와 같은 변형은 다시 재지 않는다. alts를 주지 않으면 기체마다 운용 범위로 거른 DEFAULT_ALTS."""
    t0 = time.perf_counter()
    grid = _grid(built, machs)
    if not grid:
        return {"ok": False, "reason": REASON_NO_RANGE, "reason_text": REASON_TEXT[REASON_NO_RANGE],
                "alloc": None, "requirement": None, "elapsed_s": time.perf_counter() - t0}
    configs, seen = [], set()
    for cfg in (built, *variants):
        if cfg.plant_fingerprint in seen:
            continue
        seen.add(cfg.plant_fingerprint)
        cfg_alts = cfg.alts_within(DEFAULT_ALTS) if alts is None else [float(a) for a in alts]
        configs.append((cfg, cfg.aircraft(), [cfg.doc["mass"]["fuel_max"] * f for f in fuel_fracs], cfg_alts))
    n_check = int(math.floor((grid[-1] - grid[0]) / check_step + 1e-9)) + 1
    checks = sorted({round(grid[0] + i * check_step, 6) for i in range(n_check)} | {round(g, 6) for g in grid})
    need, excluded = {}, 0
    for k, m in enumerate(checks):
        if on_progress is not None and on_progress(k, len(checks), f"δe_trim 요구 M{m:g}"):
            return {"ok": False, "reason": REASON_CANCELLED, "reason_text": REASON_TEXT[REASON_CANCELLED],
                    "alloc": None, "requirement": None, "elapsed_s": time.perf_counter() - t0}
        worst = None
        for _cfg, ac, fuels, cfg_alts in configs:
            for fuel, alt in ((f, a) for f in fuels for a in cfg_alts):
                tr = trim_level(ac, TrimCase(name=case_name(m, alt, fuel), mach=m, alt=alt, fuel=fuel))
                if not tr.converged or not tr.flags.get("saturation_ok"):
                    excluded += 1
                    continue
                de = abs(float(tr.control.elevon[0]))
                worst = de if worst is None else max(worst, de)
        need[m] = worst

    req_m = [m for m in checks if need[m] is not None]
    if len(req_m) < 2:
        return {"ok": False, "reason": REASON_NO_REQUIREMENT, "reason_text": REASON_TEXT[REASON_NO_REQUIREMENT],
                "alloc": None, "requirement": None, "elapsed_s": time.perf_counter() - t0}
    lo_m, hi_m = req_m[0], req_m[-1]
    first = max((i for i, g in enumerate(grid) if g <= lo_m + 1e-9), default=0)
    last = min((i for i, g in enumerate(grid) if g >= hi_m - 1e-9), default=len(grid) - 1)
    if last - first < 1:  # 요구 검사점들이 한 격자 칸 안 — 그 칸의 양 끝을 남긴다
        first, last = (first, first + 1) if first + 1 < len(grid) else (last - 1, last)
    trimmed = [g for i, g in enumerate(grid) if i < first or i > last]
    grid = grid[first:last + 1]
    req_need = [need[m] for m in req_m]
    values, undefined = [], []
    for g in grid:
        v = need[round(g, 6)]
        if v is None:
            undefined.append(g)
            v = float(np.interp(g, req_m, req_need))
        values.append(v)

    pts = [(m, need[m]) for m in checks if need[m] is not None]
    iterations, short = 0, []
    for iterations in range(1, MAX_ITER + 1):
        raise_by = {}
        short = []
        for m, req in pts:
            gap = req - float(np.interp(m, grid, values))
            if gap > 1e-12:
                i = min(max(bisect.bisect_right(grid, m) - 1, 0), len(grid) - 2)
                short.append(m)
                for j in (i, i + 1):
                    raise_by[j] = max(raise_by.get(j, 0.0), gap)
        if not short:
            break
        for j, d in raise_by.items():
            values[j] += d
    have = [float(np.interp(m, grid, values)) for m, _ in pts]
    excess = max((h - req for h, (_, req) in zip(have, pts)), default=0.0)
    ok = not short
    alloc = built.doc["law"]["alloc"]
    return {
        "ok": ok, "reason": None if ok else REASON_NOT_CONVERGED,
        "reason_text": None if ok else REASON_TEXT[REASON_NOT_CONVERGED],
        "alloc": {
            "resv_frac": alloc["resv_frac"] if alloc is not None else _law_default_resv_frac(),
            "de_trim": {
                "source": "derived",
                "table": {"axes": {"mach": list(grid)}, "data": values, "extrapolate": "clip"},
                "provenance": {
                    "source": DERIVE_SOURCE, "plant_fingerprint": built.plant_fingerprint,
                    "plant_fingerprints": [cfg.plant_fingerprint for cfg, *_ in configs],
                    "configurations": [cfg.variant or "base" for cfg, *_ in configs],
                    "fuels": configs[0][2], "alts": configs[0][3], "check_step": check_step,
                    "iterations": iterations, "shortfall": len(short), "excess_max": excess,
                    "excluded_trims": excluded, "undefined_machs": undefined, "trimmed_machs": trimmed,
                },
            },
        },
        "requirement": {"mach": [m for m, _ in pts], "need": [r for _, r in pts], "have": have},
        "elapsed_s": time.perf_counter() - t0,
    }
