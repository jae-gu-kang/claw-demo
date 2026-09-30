"""COARSE 트림 격자 — 요구영역의 기본 격자(region_grid, 이관 2단계)와 옛 엔벨로프 유도 격자(coarse_grid).

**region_grid** (05 §11.13 2단계 — 요구영역이 있는 기체의 정본 경로): 요구 운용영역의 기본 격자(opspace/basegrid.py —
공통 마하 좌표 + 행 끝점)를 그대로 설계점 후보로 쓴다. 요구를 모델·물리로 깎지 않는다(05 §11.2): 실속 하한·DB 상한·
실속표 축으로 행을 자르지 않고, 날 수 없는 점은 트림 뒤 조건 판정(opspace/verdict.py)의 제외 사유로, 모델 부족·요구
영역 밖·요구 미정의 점은 트림 **전에** `pre_trim_verdict`로 남긴다 — 버리지 않는다. 기본 격자가 계산 예산을 넘으면
`select_coarse`가 대표점을 고른다(경계·필수 조건은 늘 남긴다).

**coarse_grid** (옛 경로 — 요구영역이 없는 기체만): 아래 설명대로 엔벨로프(V-n 실속 경계)와 공력 DB 유효범위에서
유도한다. 요구영역이 있으면 쓰지 않는다 — 요구를 물리로 깎는 반례라서다(05 §11.2).

행(alt, fuel)마다 mach 하한이 다르다 — 실속 속도 V_S가 중량·밀도에 따라 움직이므로
직사각 격자를 강제하면 저고도·저연료 행에서 트림 불가 영역을 헛돌게 된다.
PointSet이 격자가 아니라 목록인 이유가 이것이다 (points.py).

- mach 하한·행 좌표: analysis.envelope의 stall_mach_lo·row_machs가 정본 —
  V_S(n=1) 역보간 × mach_margin(기본 1.1 — 실속 여유 10%, 트림 α 여유 criteria.trim_margin.alpha_margin과
  같은 지위의 [기본값]). 교차가 없는 경우는 **둘로 갈린다**(01 §2.6 v0.31):
  전 구간 n>1이면 DB 하한 폴백이고, 전 구간 n<1이면 그 고도에서 1g 자체가
  도달 불가라 하한=상한이 되어 **빈 행**이 된다(귀속 "n_reach"). 후자를 종전처럼
  DB 하한으로 폴백하면 기체 천장 위에 격자점이 생긴다 — 실측(18 km·연료 200 kg)
  으로 5점이 0점으로 바뀌었다. 설계 엔벨로프 표시(01 §2.6)와 같은 좌표를 공유한다.
- mach 상한: min(구조 순항 한계 mach_no, DB 유효 상한, 실속표 축 상한) — 실 DB
  결선 시 db_ranges를 Table.axes에서 유도하는 어댑터가 이 인자 계약으로 들어온다.
- 격자 생성 후 trim_batch 1회(서펜타인 인접 시드)로 점마다 조건 판정(opspace/verdict.py)을 싣고 채택을
  trimmable로 세운다 — 채택 안 한 점(트림 실패·모델 밖·제한 위반 — 여유 미달은 채택)은 버리지 않고 False로 남긴다
  (엔벨로프 실경계의 데이터화). 판정 문맥 ctx는 트림 탭과 같은 것(VerdictContext.from_profile)이라야 같은
  조건에 같은 사유가 선다(이관 8단계).
"""

from claw.analysis.envelope import DEFAULT_SCHEDULE_ALTS, row_machs
from claw.common.contracts import TrimCase
from claw.design.points import (
    ROLE_DESIGN,
    OperatingPoint,
    PointSet,
    case_name,
)
from claw.opspace.basegrid import MAX_BASE_POINTS, base_grid
from claw.opspace.states import NOT_RUN, pre_state
from claw.opspace.verdict import PRE_TRIM_CATEGORY, condition_verdict, pre_trim_verdict
from claw.trim import trim_batch

DEFAULT_ALTS = DEFAULT_SCHEDULE_ALTS  # 정본은 analysis.envelope — 설계 엔벨로프 표시와 공유
DEFAULT_FUEL_FRACS = (0.1, 0.5, 1.0)  # × fuel_max [기본값]


def coarse_grid(
    aircraft, stall_table, limits, db_ranges, *, ctx,
    n_mach=5, alts=None, fuels=None, mach_margin=1.1, budget=60,
    fingerprint="", on_progress=None, store=None,
) -> dict:
    """엔벨로프·DB 유도 coarse 격자 + 1회 트림 — {"points", "trims", "aborted"}.

    budget 초과는 제출 시점 ValueError (influence.py MAX_CASES 원칙 — 오타 예산이
    단일 워커를 점유하기 전에 차단). on_progress는 trim_batch 규약 그대로
    (truthy 반환 = 협조적 취소, 완료분 보존). ctx: 조건 판정 문맥(VerdictContext) — 필수다.
    store(TrimStoreScope | None): 트림 저장소 창(05 §11.10) — trim_batch에 그대로: 수렴 기록은 풀지 않고
    조립(origin "reused", 판정은 지금 기준), 새로 푼 해는 저장. None이면 종전 그대로다(설계 골든). 재시도는
    안 켠다(retry=None — 설계 경로는 종전과 같은 풀이 구성이라야 저장소 유무가 해를 못 바꾼다).
    """
    if n_mach < 2:
        raise ValueError(f"n_mach는 2 이상: {n_mach}")
    if not mach_margin >= 1.0:
        raise ValueError(f"mach_margin은 1 이상 (실속 여유): {mach_margin}")
    alts = tuple(float(a) for a in (alts if alts is not None else DEFAULT_ALTS))
    if fuels is None:
        fuel_max = aircraft.fuel_mass.fuel_max
        fuels = tuple(fuel_max * f for f in DEFAULT_FUEL_FRACS)
    fuels = tuple(float(f) for f in fuels)

    total = n_mach * len(alts) * len(fuels)
    if total > budget:
        raise ValueError(
            f"coarse 격자 {total}점이 예산 {budget}을 초과 — n_mach·alts·fuels를 줄이거나 "
            "budget을 명시적으로 올려라"
        )

    db_mach_lo, db_mach_hi = (float(v) for v in db_ranges["mach"])
    mach_hi = min(float(limits["mach_no"]), db_mach_hi, float(stall_table.axes[0][-1]))

    points = PointSet()
    for fuel in fuels:
        for alt in alts:
            machs = row_machs(
                aircraft, stall_table, alt, fuel,
                mach_hi=mach_hi, db_mach_lo=db_mach_lo,
                mach_margin=mach_margin, n_mach=n_mach,
            )
            # 빈 행 = 유효 mach 구간 없음 (고고도·고중량 — 데이터로 남길 것 없음)
            for mach in machs:
                name = case_name(float(mach), alt, fuel)
                if name in points:
                    continue
                points.add(OperatingPoint(
                    case=TrimCase(name=name, mach=float(mach), alt=alt, fuel=fuel),
                    role=ROLE_DESIGN,
                    origin="coarse",
                ))

    trims: dict = {}
    aborted = None

    def _progress(done, total_, tr):
        trims[tr.case.name] = tr
        pt = points.get(tr.case.name)
        pt.verdict = condition_verdict(tr, ctx)
        pt.trimmable = pt.verdict["adopted"]
        if on_progress is not None and on_progress(done, total_, f"trim {tr.case.name}"):
            return True
        return False

    results = trim_batch(
        aircraft, points.serpentine(), fingerprint=fingerprint, on_progress=_progress, store=store
    )
    if len(results) < len(points):
        aborted = "cancelled"
    return {"points": points, "trims": trims, "aborted": aborted}


# ── 요구영역 기본 격자 경로 (이관 2단계) ───────────────────────────────────────────────────────────


def select_coarse(base: dict, *, budget: int, required=()) -> dict:
    """기본 격자에서 계산 예산에 맞는 대표점 — {"points", "dropped", "axis_interior", "axis_kept", "rule", "floor"}.

    floor는 늘 남기는 점(행 끝점 + 필수 조건) 수 — 예산의 바닥이다.

    선택 규칙 (05 §11.13 2단계 — 「계산량에 맞춰 대표점을 고르되 경계·필수 조건을 넣는다」):
    1. 기본 격자 전체가 예산 안이면 전부 쓴다.
    2. 넘으면 **행 끝점**(행마다 요구 마하 하한·상한 — 요구영역 경계)과 **필수 조건**(required — 이름 목록)은 늘 남기고,
       나머지(행 안쪽 점 — 모두 공통 마하 좌표 위)는 **공통 좌표를 통째로** 솎는다: 안쪽 좌표 n개 중 k개를 가운데 정렬
       간격(색인 ⌊(i+½)·n/k⌋)으로 고르고, 모든 행이 같은 좌표를 쓴다. k는 예산을 넘지 않는 가장 큰 값이다. 행 끝점이
       경계를 이미 덮으므로 안쪽은 구간 가운데로 퍼진다(k=1이면 가운데 좌표 — 하한 옆이 아니다). 행마다 따로 솎으면
       좌표가 어긋나 절점·검증점(공통 좌표)과 기본 격자가 재사용되지 않는다(05 §11.11).
    3. 행 끝점 + 필수 조건만으로 예산을 넘으면 ValueError — 요구 경계를 몰래 빼지 않는다. 서버는 같은 계산을 잡 제출
       전에 `coarse_preflight`로 돌려 422로 거부한다(잡 안에서 처음 터지지 않게).
    예산은 목록에 남는 점 전부로 센다(트림 전 제외 점 포함) — 세션의 점 예산(len(points))과 같은 단위다. 뺀 점은
    이름으로 돌려준다(dropped — 보고가 「기본 격자 중 설계에서 고르지 않은 점」을 셀 수 있게).
    """
    pts = base["points"]
    required = set(required)
    ends = set()
    for row in base["rows"]:
        if row["bounds"] is None:
            continue
        for p in pts:
            if p["alt"] == row["alt"] and p["fuel"] == row["fuel"] and p["mach"] in row["bounds"]:
                ends.add(p["name"])
    keep_always = ends | (required & {p["name"] for p in pts})
    interior = sorted({p["mach"] for p in pts if p["name"] not in keep_always})
    if len(pts) <= budget:
        return {"points": list(pts), "dropped": [], "axis_interior": interior, "axis_kept": interior,
                "rule": "all", "floor": len(keep_always)}
    for k in range(len(interior), -1, -1):
        n = len(interior)
        # 가운데 정렬 간격 — n/k ≥ 1이라 색인이 겹치지 않는다
        idx = [int((i + 0.5) * n / k) for i in range(k)]
        kept_axis = [interior[i] for i in idx]
        chosen = [p for p in pts if p["name"] in keep_always or p["mach"] in kept_axis]
        if len(chosen) <= budget:
            chosen_names = {p["name"] for p in chosen}
            return {"points": chosen, "dropped": [p["name"] for p in pts if p["name"] not in chosen_names],
                    "axis_interior": interior, "axis_kept": kept_axis, "rule": "thinned",
                    "floor": len(keep_always)}
    raise ValueError(
        f"기본 격자의 행 끝점·필수 조건 {len(keep_always)}점이 예산 {budget}을 넘는다 — 요구영역 경계를 빼지 않는다."
        " 예산(budget_points)을 올리거나 고도·연료 목록을 줄여라"
    )


def coarse_preflight(region, model, *, n_mach=None, alts=None, fuels=None, budget: int) -> dict:
    """COARSE 격자가 예산에 들어가는지 트림 없이 미리 잰다 — {"base_points", "floor", "budget"}. 넘으면 ValueError.

    region_grid와 같은 base_grid·select_coarse를 그대로 부른다(같은 규칙 — 따로 세면 둘이 갈린다). 거부 사유는 둘이다:
    기본 격자 상한(MAX_BASE_POINTS — 명세 덮음이 키울 수 있다)과 행 끝점·필수 조건 바닥(floor)이 COARSE 예산을 넘는 것.
    설정이 명세를 덮으면 요구(영역 자신의 명세) 격자도 만들어 본다 — 커버리지 분모를 세션이 그 격자로 싣기 때문이다.
    """
    base = base_grid(region, model, n_mach=n_mach, alts=alts, fuels=fuels)
    if (n_mach, alts, fuels) != (None, None, None):
        base_grid(region, model)
    sel = select_coarse(base, budget=budget)
    return {"base_points": len(base["points"]), "floor": sel["floor"], "budget": int(budget)}


def region_grid(
    aircraft, region, model, *, ctx, n_mach=None, alts=None, fuels=None, budget=MAX_BASE_POINTS, required=(),
    fingerprint="", on_progress=None, store=None,
) -> dict:
    """요구영역 기본 격자 COARSE + 1회 트림 — {"points", "trims", "aborted", "base", "selection"}.

    n_mach·alts·fuels를 주면 영역의 기본 격자 명세(region.grid)를 덮는다(설정 우선). 격자점은 `select_coarse`로 예산에
    맞춘다. 트림 전 상태가 미계산(NOT_RUN)인 점만 트림한다(서펜타인 인접 시드) — 모델 부족·요구영역 밖·요구 미정의 점은
    목록에 남기고 `pre_trim_verdict`를 싣는다(트림하지 않음, trimmable False). 트림한 점은 coarse_grid와 같은
    조건 판정(ctx)을 싣고 채택을 trimmable로 세운다. required: 늘 넣을 조건 [(mach, alt, fuel)] — 기본 격자에 없으면
    그 좌표를 더한다(05 §11.4 고정점 자리 — 아직 부르는 곳은 없다).
    base는 기본 격자 dict에 점마다 selected를 붙인 것 — 요구영역 커버리지 보고(orchestrator region_coverage)의 분모다.
    store: coarse_grid와 같은 계약(트림 저장소 창, 05 §11.10) — 트림 탭이 같은 기본 격자를 먼저 풀었으면 여기서 재사용된다.
    """
    base = base_grid(region, model, n_mach=n_mach, alts=alts, fuels=fuels)
    names = {p["name"] for p in base["points"]}
    req_names = []
    for m, a, f in required:
        name = case_name(float(m), float(a), float(f))
        req_names.append(name)
        if name not in names:
            names.add(name)
            base["points"].append({"mach": float(m), "alt": float(a), "fuel": float(f), "name": name,
                                   "state": pre_state(region, model, float(m), float(a), float(f))})
    sel = select_coarse(base, budget=budget, required=req_names)
    chosen = {p["name"] for p in sel["points"]}
    for p in base["points"]:
        p["selected"] = p["name"] in chosen

    points, targets = PointSet(), PointSet()
    for p in sel["points"]:
        pt = OperatingPoint(case=TrimCase(name=p["name"], mach=p["mach"], alt=p["alt"], fuel=p["fuel"]),
                            role=ROLE_DESIGN, origin="coarse")
        if p["state"] in PRE_TRIM_CATEGORY:
            pt.verdict = pre_trim_verdict(p["state"], ctx)
            pt.trimmable = False
        elif p["state"] == NOT_RUN:
            targets.add(pt)
        else:  # 기본 격자가 내는 트림 전 상태는 위 넷뿐이다 — 새 상태가 생기면 조용히 트림하지 않게 멈춘다
            raise ValueError(f"{p['name']}: 기본 격자의 알 수 없는 트림 전 상태 {p['state']!r}")
        points.add(pt)

    trims: dict = {}
    aborted = None

    def _progress(done, total_, tr):
        trims[tr.case.name] = tr
        pt = points.get(tr.case.name)
        pt.verdict = condition_verdict(tr, ctx)
        pt.trimmable = pt.verdict["adopted"]
        if on_progress is not None and on_progress(done, total_, f"trim {tr.case.name}"):
            return True
        return False

    if len(targets):
        results = trim_batch(aircraft, targets.serpentine(), fingerprint=fingerprint, on_progress=_progress,
                             store=store)
        if len(results) < len(targets):
            aborted = "cancelled"
    selection = {k: sel[k] for k in ("dropped", "axis_interior", "axis_kept", "rule")}
    selection.update(budget=int(budget), base_points=len(base["points"]), selected=len(sel["points"]))
    return {"points": points, "trims": trims, "aborted": aborted, "base": base, "selection": selection}
