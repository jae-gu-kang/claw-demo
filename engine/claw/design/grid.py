"""coarse 트림 격자 자동 유도 — 엔벨로프(V-n 실속 경계)와 공력 DB 유효범위에서.

행(alt, fuel)마다 mach 하한이 다르다 — 실속 속도 V_S가 중량·밀도에 따라 움직이므로
직사각 격자를 강제하면 저고도·저연료 행에서 트림 불가 영역을 헛돌게 된다.
PointSet이 격자가 아니라 목록인 이유가 이것이다 (points.py).

- mach 하한·행 좌표: analysis.envelope의 stall_mach_lo·row_machs가 정본 —
  V_S(n=1) 역보간 × mach_margin(기본 1.1 — 실속 여유 10%, 기체 프로파일 trim.alpha_margin과
  같은 지위의 [기본값]). 교차가 없는 경우는 **둘로 갈린다**(01 §2.6 v0.31):
  전 구간 n>1이면 DB 하한 폴백이고, 전 구간 n<1이면 그 고도에서 1g 자체가
  도달 불가라 하한=상한이 되어 **빈 행**이 된다(귀속 "n_reach"). 후자를 종전처럼
  DB 하한으로 폴백하면 기체 천장 위에 격자점이 생긴다 — 실측(18 km·연료 200 kg)
  으로 5점이 0점으로 바뀌었다. 설계 엔벨로프 표시(01 §2.6)와 같은 좌표를 공유한다.
- mach 상한: min(구조 순항 한계 mach_no, DB 유효 상한, 실속표 축 상한) — 실 DB
  결선 시 db_ranges를 Table.axes에서 유도하는 어댑터가 이 인자 계약으로 들어온다.
- 고도(기본): 연료별 schedule_alts_auto(analysis.envelope 정본) — 쓸 수 있는 천장
  (공력 행 폭 + trim_probe 추력 천장)까지 σ 균일, 단수 2~4 적응. 구 고정 0·1·3·5 km
  (DEFAULT_SCHEDULE_ALTS)는 천장이 어디든 하단만 덮어 폐기, seed의 후보 목록으로만 남았다.
- 격자 생성 후 trim_batch 1회(서펜타인 인접 시드)로 trimmable 플래그를 채운다 —
  포화·α여유 실패점은 버리지 않고 False로 남긴다 (엔벨로프 실경계의 데이터화).
"""

from claw.analysis.envelope import (
    DEFAULT_SCHEDULE_N_ALT_MAX,
    row_machs,
    schedule_alts_auto,
)
from claw.common.contracts import TrimCase
from claw.design.points import (
    ROLE_ANCHOR,
    OperatingPoint,
    PointSet,
    case_name,
    envelope_ok,
)
from claw.trim import trim_batch, trim_level

DEFAULT_FUEL_FRACS = (0.1, 0.5, 1.0)  # × fuel_max [기본값]


def trim_probe(aircraft, fuel, fingerprint=""):
    """schedule_alts_auto의 트림 탐침 — (alt, machs) → 그 행 마하 중 하나라도 envelope_ok인가.

    천장 탐색 전용이라 결과를 격자에 싣지 않는다(격자 트림은 trim_batch가 인접 시드로 다시
    푼다). 가운데 마하부터 푼다 — 추력 천장 근처에서 트림이 서는 곳은 행 가운데 띠다(예제
    기체 6.6 km: M0.16~0.24만 선다). 한 점이 서면 거기서 멈춘다."""
    fuel = float(fuel)

    def probe(alt, machs):
        mid = (len(machs) - 1) / 2.0
        for i in sorted(range(len(machs)), key=lambda k: abs(k - mid)):
            m = float(machs[i])
            case = TrimCase(name=case_name(m, alt, fuel), mach=m, alt=alt, fuel=fuel)
            if envelope_ok(trim_level(aircraft, case, fingerprint=fingerprint)):
                return True
        return False

    return probe


def coarse_grid(
    aircraft, stall_table, limits, db_ranges, *,
    n_mach=5, alts=None, fuels=None, mach_margin=1.1, budget=60,
    alt_lo=0.0, alt_hi=None, fingerprint="", on_progress=None,
) -> dict:
    """엔벨로프·DB 유도 coarse 격자 + 1회 트림 — {"points", "trims", "alts_auto", "aborted"}.

    alts 미지정이면 연료(중량)별로 schedule_alts_auto(analysis.envelope 정본 —
    설계 엔벨로프 표시와 같은 유도)가 고도를 정한다: 쓸 수 있는 천장(공력 행 폭 +
    trim_probe 추력 천장)까지 σ 균일, 단수는 스팬과 예산에 맞춰 2~4로 적응(상한
    min(4, budget/(n_mach×연료 수)) — 구 고정 0·1·3·5 km는 천장이 어디든 하단만 덮었다).
    유도 귀속은 alts_auto에 연료별 {"fuel","alts","ceiling","ceiling_source","trim_probe"}로
    싣고, 지정 alts면 null이다. alt_lo·alt_hi는 유도 범위(운용 고도 한계 — 미지정이면 바닥
    0 m·표시 상한 [기본값]). 탐침 트림은 연료당 수십 회(점당 ~6 ms)라 진행률에 넣지 않는다.

    지정 alts의 budget 초과는 제출 시점 ValueError (influence.py MAX_CASES 원칙 —
    오타 예산이 단일 워커를 점유하기 전에 차단; 자동 유도는 애초에 예산 안이다).
    on_progress는 trim_batch 규약 그대로 (truthy 반환 = 협조적 취소, 완료분 보존).
    """
    if n_mach < 2:
        raise ValueError(f"n_mach는 2 이상: {n_mach}")
    if not mach_margin >= 1.0:
        raise ValueError(f"mach_margin은 1 이상 (실속 여유): {mach_margin}")
    if fuels is None:
        fuel_max = aircraft.fuel_mass.fuel_max
        fuels = tuple(fuel_max * f for f in DEFAULT_FUEL_FRACS)
    fuels = tuple(float(f) for f in fuels)

    db_mach_lo, db_mach_hi = (float(v) for v in db_ranges["mach"])
    mach_hi = min(float(limits["mach_no"]), db_mach_hi, float(stall_table.axes[0][-1]))

    alts_auto = None
    if alts is not None:
        alts = tuple(float(a) for a in alts)
        total = n_mach * len(alts) * len(fuels)
        if total > budget:
            raise ValueError(
                f"coarse 격자 {total}점이 예산 {budget}을 초과 — n_mach·alts·fuels를 줄이거나 "
                "budget을 명시적으로 올려라"
            )
        rows = [(fuel, alts) for fuel in fuels]
    else:
        # 연료가 비면 행도 없다(0점) — 나눗셈 전에 거른다
        n_alt_cap = (min(DEFAULT_SCHEDULE_N_ALT_MAX, budget // (n_mach * len(fuels)))
                     if fuels else DEFAULT_SCHEDULE_N_ALT_MAX)
        if n_alt_cap < 2:
            raise ValueError(
                f"예산 {budget}으로는 마하 {n_mach}점 × 연료 {len(fuels)}단에 고도 2단도 "
                "못 싣는다 — n_mach·fuels를 줄이거나 budget을 명시적으로 올려라"
            )
        alts_auto, rows = [], []
        for fuel in fuels:
            auto = schedule_alts_auto(
                aircraft, stall_table, fuel,
                mach_hi=mach_hi, db_mach_lo=db_mach_lo,
                alt_lo=alt_lo, alt_hi=alt_hi, mach_margin=mach_margin,
                n_mach=n_mach, n_alt_max=n_alt_cap,
                trim_probe=trim_probe(aircraft, fuel, fingerprint),
            )
            alts_auto.append({"fuel": fuel, "alts": auto["alts"],
                              "ceiling": auto["ceiling"],
                              "ceiling_source": auto["ceiling_source"],
                              "trim_probe": auto["trim_probe"]})
            rows.append((fuel, tuple(auto["alts"])))

    points = PointSet()
    for fuel, fuel_alts in rows:
        for alt in fuel_alts:
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
                    role=ROLE_ANCHOR,
                    origin="coarse",
                ))

    trims: dict = {}
    aborted = None

    def _progress(done, total_, tr):
        trims[tr.case.name] = tr
        pt = points.get(tr.case.name)
        pt.trimmable = envelope_ok(tr)
        if on_progress is not None and on_progress(done, total_, f"trim {tr.case.name}"):
            return True
        return False

    results = trim_batch(
        aircraft, points.serpentine(), fingerprint=fingerprint, on_progress=_progress
    )
    if len(results) < len(points):
        aborted = "cancelled"
    return {"points": points, "trims": trims, "alts_auto": alts_auto, "aborted": aborted}
