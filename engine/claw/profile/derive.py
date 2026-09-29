"""δe_trim 표 도출 — 법칙 할당이 읽는 마하 표를 기체에서 잰다 (02 §5.6 · 02 §5.6.1).

할당은 선회 하중 n에서 롤 예산의 피치 몫을 먼저 뗀다: R = clip(δe_trim(M)·n, 0, resv_frac·B)(fcl/graphs.py
_roll_budget_nodes). 그 표는 기체의 1g 트림 승강타 요구다 — 예제 기체에서 M0.23의 14.88°부터 M0.6의 0.68°까지
22배 움직여 상수로는 양 끝을 못 맞춘다. 예제 표를 만든 절차(02 §5.6.1 `/law/alloc/de_trim`)를 코드로 옮겼다:

1. 요구 — 마하마다 연료 × 고도 격자로 trim_level을 돌려 최악 |δe|를 취한다. 넣는 트림은 조건 판정
   (opspace/verdict.py — 트림 탭과 같은 판정)이 트림 계산 가능 ∧ 모델 유효 ∧ 제한 충족이라 한 것이다. **여유 판정은
   보지 않는다** — 스로틀 96 %에서 수렴한 트림도 날 수 있는 평형이라 그 δe는 예약해야 할 요구다(종전에는 포화라며
   뺐다 — 이관 8단계). 제한 밖(실속 경계·리미터·M_NO·최대 동압)이나 모델 밖(DB·연료 범위) 트림은 기체가 거기서
   날지 않으니 요구가 아니다. 근거가 없어 판정 못 한 제한(실속표 축 밖)도 통과가 아니라 뺀다. 뺀 수를 범주별로
   출처에 적는다(excluded_by). 플랜트가 다른 형상 변형이 있으면 그 변형들까지 재어 최악을 취하고, 잰 플랜트
   지문을 모두 출처에 남긴다 — 표는 문서에 하나라 변형이 함께 쓴다.
   **격자는 요구 운용영역에서 나온다** (이관 9단계 — 05 §11.13): 표 마하 격자는 요구영역 마하 전 구간의 기본 격자 공통
   좌표(opspace/basegrid.py와 같은 linspace — 문서 표의 격자를 이어 쓰지도, DB×M_NO로 잡지도 않는다), 검사 고도는 기본
   격자 고도 + 요구 고도 끝, 검사 연료는 요구 연료 끝 + 기본 격자 연료(kg). 확정 요구영역이면 요구영역 밖·요구 미정의
   조건은 요구가 아니라 재지 않고 excluded_by["region"]으로 센다(초안 draft:trim_grid는 판정에 쓰지 않는다 — 05 §11.2).
   인자(machs·alts·fuel_fracs)를 주면 그 값이 이긴다. 요구영역이 없는 기체만 옛 규칙(문서 표 격자 → DB 범위, 운용 고도로
   거른 DEFAULT_ALTS, 연료 DEFAULT_FUEL_FRACS × fuel_max)이다.
2. 보정 — 표 격자 사이 선형보간(표는 clip 룩업이다)이 검사 격자(check_step 간격)의 요구를 밑돌면, 그 구간 양
   끝을 부족분만큼 올리기를 부족이 없어질 때까지 반복한다. 공유 끝점은 두 구간 중 큰 쪽만큼 올린다.

3. 범위 정직성 (이관 10단계) — provenance.coverage에 요구 마하 범위와 표 축을 나란히 적는다. **표의 축이 요구를 덮는 것과
   그 구간의 도출 근거가 있는 것은 다르다**: 요구 범위 안인데 날 수 있는 트림이 하나도 없던 검사 마하 구간(unsupported)과
   표 축 밖이라 런타임이 끝값을 쓰는 요구 구간(beyond_table — 「표 범위 밖 · 끝값 사용 · 성능 미확인」)을 따로 싣고,
   표 격자점 중 자기 요구가 없어 보간값으로 시작한 점(undefined_machs)도 싣는다 — 끝값·보간값으로 채운 구간을 완료로
   세지 않는다. 저장된 표는 `de_trim_coverage`가 다시 도출하지 않고 같은 형식으로 답한다.

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
from claw.opspace.basegrid import _r
from claw.opspace.region import region_of
from claw.opspace.verdict import VerdictContext, condition_verdict
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
    REASON_NO_REQUIREMENT: "표 격자에서 날 수 있는 트림(계산 가능·모델 안·제한 안)이 있는 마하가 둘 미만이다 — 트림 탭에서 성립 영역을 먼저 확인한다",
    REASON_NOT_CONVERGED: "보정을 다 돌려도 검사 격자에 요구를 밑도는 점이 남았다",
    REASON_CANCELLED: "취소됐다",
}


def region_mach_axis(region) -> list:
    """요구영역 마하 전 구간의 기본 격자 공통 좌표 — basegrid와 같은 linspace·같은 반올림(_r)이라 표 절점이 기본 격자
    좌표와 같은 값이다(자릿수가 다르면 0.133333 대 0.133333333으로 갈린다)."""
    return [_r(m) for m in np.linspace(region.mach[0], region.mach[1], int(region.grid["n_mach"]))]


def region_echo(region) -> dict | None:
    """도출이 잰 요구영역의 기록 — provenance.region. 저장 표의 근거(unsupported)가 지금 요구영역에서 잰 것인지를
    이것 전체로 가른다(de_trim_coverage) — 마하 구간만 같고 고도·연료·경계표·격자가 바뀐 영역을 같은 요구로 보지 않게."""
    if region is None:
        return None
    boundary = None if region.boundary is None else [
        [float(f), [[float(a), float(lo), float(hi)] for a, lo, hi in rows]] for f, rows in region.boundary]
    return {"source": region.source, "confirmed": bool(region.confirmed),
            "mach": [float(m) for m in region.mach], "alt": [float(a) for a in region.alt],
            "fuel": [float(f) for f in region.fuel], "boundary": boundary,
            "grid": {"n_mach": int(region.grid["n_mach"]), "alts": [float(a) for a in region.grid["alts"]],
                     "fuels": [float(f) for f in region.grid["fuels"]]}}


def region_check_alts(region) -> list:
    """검사 고도 — 기본 격자 고도 + 요구 고도 끝(격자 사이의 끝이 빠지면 상한의 1g 요구를 놓친다 — alts_within과 같은 이유)."""
    return sorted({float(a) for a in region.grid["alts"]} | {float(a) for a in region.alt})


def region_check_fuels(region) -> list:
    """검사 연료 [kg] — 요구 연료 끝 + 기본 격자 연료."""
    return sorted({float(f) for f in region.fuel} | {float(f) for f in region.grid["fuels"]})


def _grid(built, machs, region=None):
    if machs is not None:
        return [float(m) for m in machs]
    if region is not None:
        return region_mach_axis(region)
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


def _coverage(required, grid, undefined, checks, need) -> dict:
    """provenance.coverage — 요구 마하 범위 대 표 축, 근거 없는 요구 구간, 표 밖 요구 구간 (이관 10단계).

    unsupported: 요구 범위 안 검사 마하 중 날 수 있는 트림이 없던(요구 없음 — 트림 실패·모델 부족·제한 위반·요구영역 밖)
    것의 연속 구간. beyond_table: 요구 범위 중 표 축 [첫, 끝] 밖 — 런타임이 끝값을 쓴다(clip). 요구영역이 없으면 둘 다
    None(비교할 요구가 없다 — 비었다고 쓰면 「다 덮었다」로 읽힌다)."""
    out = {"required_mach": None if required is None else [float(required[0]), float(required[1])],
           "table_mach": [float(grid[0]), float(grid[-1])], "undefined_machs": list(undefined),
           "unsupported": None, "beyond_table": None}
    if required is None:
        return out
    lo, hi = out["required_mach"]
    inside = [m for m in checks if lo - 1e-9 <= m <= hi + 1e-9]
    runs, cur = [], []
    for m in inside:  # 검사 격자 순서로 연속한 「요구 없음」 점들을 한 구간으로
        if need[m] is None:
            cur.append(m)
        elif cur:
            runs.append([cur[0], cur[-1]])
            cur = []
    if cur:
        runs.append([cur[0], cur[-1]])
    out["unsupported"] = runs
    beyond = []
    if lo < grid[0] - 1e-9:
        beyond.append([lo, float(grid[0])])
    if grid[-1] < hi - 1e-9:
        beyond.append([float(grid[-1]), hi])
    out["beyond_table"] = beyond
    return out


def de_trim_coverage(built) -> dict | None:
    """저장된 δe_trim 표의 범위 정직성 — derive provenance.coverage와 같은 키 + {basis, basis_current, stale}.

    다시 도출하지 않는다(기체 탭이 「표 범위 밖 · 끝값 사용 · 성능 미확인」을 그리는 데 쓴다). 요구 마하는 지금 문서의
    요구영역, 표 축은 저장된 표. 근거 없는 구간(unsupported)은 **도출이 지금 요구영역에서 잰 기록**이 있을 때만 싣고
    (basis_current True), 요구영역이 도출 뒤에 바뀌었거나 손으로 넣은 표(basis "document")면 None — 모르는 것을 비었다고
    하지 않는다. beyond_table은 늘 지금 요구영역 대 표 축으로 계산한다. 표가 없으면 None."""
    alloc = built.doc["law"]["alloc"]
    if alloc is None or alloc["de_trim"] is None:
        return None
    de = alloc["de_trim"]
    axis = [float(m) for m in de["table"]["axes"]["mach"]]
    region = region_of(built.doc)
    required = None if region is None else region.mach
    prov = de["provenance"] if isinstance(de["provenance"], dict) else {}
    cov = _coverage(required, axis, list(prov.get("undefined_machs") or ()), [], {})
    stored = prov.get("coverage") if de["source"] == "derived" else None
    # 요구영역 기록 전체가 같아야 지금 것이다 — 기록이 없는 옛 도출은 모른다(None)
    current = bool(stored) and stored.get("required_mach") == cov["required_mach"] \
        and stored.get("table_mach") == cov["table_mach"] \
        and prov.get("region") == region_echo(region)
    cov["unsupported"] = stored["unsupported"] if current else None
    if not current and de["source"] != "derived":
        cov["undefined_machs"] = []
    return {**cov, "basis": "derived" if de["source"] == "derived" else "document", "basis_current": current,
            "stale": bool(built.de_trim_stale)}


def derive_de_trim(built, *, variants=(), machs=None, alts=None, fuel_fracs=None,
                   check_step=CHECK_STEP, on_progress=None) -> dict:
    """BuiltProfile → {"ok", "reason", "reason_text", "alloc", "requirement", "elapsed_s"}.

    alloc은 law.alloc 모양({resv_frac, de_trim{source "derived", table, provenance}}) — resv_frac은 문서 값을
    그대로 두고, 할당 섹션이 없던 기체면 법칙 기본값이다. 표의 양 끝은 **요구가 있는 검사점**으로 정한다 — 첫(마지막)
    요구 검사점을 덮는 가장 안쪽 격자점까지 남기고 그 밖의 격자점은 표에서 뺀다(trimmed_machs). 격자점만 보고 자르면
    잘린 격자점과 첫 요구 격자점 사이의 검사점 요구가 버려져, clip 룩업이 끝값을 답하는 자리가 모자란다(격자 0.1·0.3에서
    M0.25 요구 0.188을 0.128로 답했다). 남긴 격자점 중 자기 요구가 없는 점은 요구 검사점들의 보간값으로 시작하고
    보정이 덮는다(undefined_machs) — 이웃 격자값을 복사하지 않는다. variants는 같은 문서의 형상 변형 BuiltProfile들 — 플랜트
    지문이 기본 문서와 같은 변형은 다시 재지 않는다. 격자·검사 고도·연료는 요구영역에서(머리말 1), 인자가 이긴다 —
    요구영역이 없고 alts를 주지 않으면 기체마다 운용 범위로 거른 DEFAULT_ALTS, fuel_fracs를 주지 않으면 DEFAULT_FUEL_FRACS."""
    t0 = time.perf_counter()
    region = region_of(built.doc)
    grid_source = ("explicit" if machs is not None else "region" if region is not None
                   else "document" if (built.doc["law"]["alloc"] or {}).get("de_trim") else "db")
    grid = _grid(built, machs, region)
    if not grid:
        return {"ok": False, "reason": REASON_NO_RANGE, "reason_text": REASON_TEXT[REASON_NO_RANGE],
                "alloc": None, "requirement": None, "elapsed_s": time.perf_counter() - t0}
    configs, seen = [], set()
    for cfg in (built, *variants):
        if cfg.plant_fingerprint in seen:
            continue
        seen.add(cfg.plant_fingerprint)
        if alts is not None:
            cfg_alts = [float(a) for a in alts]
        elif region is not None:
            cfg_alts = region_check_alts(region)
        else:
            cfg_alts = cfg.alts_within(DEFAULT_ALTS)
        if fuel_fracs is not None:
            cfg_fuels = [cfg.doc["mass"]["fuel_max"] * f for f in fuel_fracs]
        elif region is not None:
            cfg_fuels = region_check_fuels(region)
        else:
            cfg_fuels = [cfg.doc["mass"]["fuel_max"] * f for f in DEFAULT_FUEL_FRACS]
        configs.append((cfg, cfg.aircraft(), cfg_fuels, cfg_alts, VerdictContext.from_profile(cfg)))
    # 확정 요구영역만 제외에 쓴다 — 초안은 판정에 쓰지 않는다(05 §11.2). 요구영역은 형상 변형이 못 고친다(한 문서에 하나)
    judge_region = region if region is not None and region.confirmed else None
    n_check = int(math.floor((grid[-1] - grid[0]) / check_step + 1e-9)) + 1
    checks = sorted({round(grid[0] + i * check_step, 6) for i in range(n_check)} | {round(g, 6) for g in grid})
    need, excluded_by = {}, {}
    for k, m in enumerate(checks):
        if on_progress is not None and on_progress(k, len(checks), f"δe_trim 요구 M{m:g}"):
            return {"ok": False, "reason": REASON_CANCELLED, "reason_text": REASON_TEXT[REASON_CANCELLED],
                    "alloc": None, "requirement": None, "elapsed_s": time.perf_counter() - t0}
        worst = None
        for _cfg, ac, fuels, cfg_alts, ctx in configs:
            for fuel, alt in ((f, a) for f in fuels for a in cfg_alts):
                if judge_region is not None and judge_region.classify(m, alt, fuel) is not None:
                    excluded_by["region"] = excluded_by.get("region", 0) + 1  # 요구가 아닌 조건 — 재지 않는다
                    continue
                tr = trim_level(ac, TrimCase(name=case_name(m, alt, fuel), mach=m, alt=alt, fuel=fuel))
                # 범주만 쓴다 — 미수렴의 근거 판정(한계 고정 평형)은 도출에 필요 없어 비용을 치르지 않는다
                category = ((condition_verdict(tr, ctx, assess=False)["exclusion"]) or {}).get("category")
                if category is not None:
                    excluded_by[category] = excluded_by.get(category, 0) + 1
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
                    "excluded_trims": sum(excluded_by.values()), "excluded_by": dict(sorted(excluded_by.items())),
                    "undefined_machs": undefined, "trimmed_machs": trimmed,
                    "grid_source": grid_source,
                    "region": region_echo(region),
                    "coverage": _coverage(None if region is None else region.mach, grid, undefined, checks, need),
                },
            },
        },
        "requirement": {"mach": [m for m, _ in pts], "need": [r for _, r in pts], "have": have},
        "elapsed_s": time.perf_counter() - t0,
    }
