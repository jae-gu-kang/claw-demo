"""coarse 트림 격자 자동 유도 — 엔벨로프(V-n 실속 경계)와 공력 DB 유효범위에서.

행(alt, fuel)마다 mach 하한이 다르다 — 실속 속도 V_S가 중량·밀도에 따라 움직이므로
직사각 격자를 강제하면 저고도·저연료 행에서 트림 불가 영역을 헛돌게 된다.
PointSet이 격자가 아니라 목록인 이유가 이것이다 (points.py).

- mach 하한: vn_stall_boundary(envelope.py 재사용)의 n(M) 곡선에서 n=1 교차(=V_S)를
  역보간해 mach_margin(기본 1.1 — 실속 여유 10%, trim.ALPHA_MARGIN과 같은 지위의
  [기본값])을 곱한다. 교차가 없으면(전 구간 n>1) DB 하한으로 폴백.
- mach 상한: min(구조 순항 한계 mach_no, DB 유효 상한, 실속표 축 상한) — 실 DB
  결선 시 db_ranges를 Table.axes에서 유도하는 어댑터가 이 인자 계약으로 들어온다.
- 격자 생성 후 trim_batch 1회(서펜타인 인접 시드)로 trimmable 플래그를 채운다 —
  포화·α여유 실패점은 버리지 않고 False로 남긴다 (엔벨로프 실경계의 데이터화).
"""

import numpy as np

from claw.analysis.envelope import vn_stall_boundary
from claw.common.contracts import TrimCase
from claw.design.points import (
    ROLE_ANCHOR,
    OperatingPoint,
    PointSet,
    case_name,
    envelope_ok,
)
from claw.env import isa_atmosphere
from claw.trim import trim_batch

DEFAULT_ALTS = (0.0, 1000.0, 3000.0, 5000.0)  # [m] ISA 유효범위 내 [기본값]
DEFAULT_FUEL_FRACS = (0.1, 0.5, 1.0)  # × fuel_max [기본값]
_SCAN_POINTS = 41  # 실속 경계 역보간용 mach 스캔 밀도


def _mach_lo(aircraft, stall_table, alt, fuel, mach_hi, db_mach_lo, mach_margin):
    """행(alt, fuel)의 mach 하한 — V_S(n=1) × 여유. 교차 없으면 DB 하한 폴백."""
    scan_lo = max(float(stall_table.axes[0][0]), db_mach_lo)
    machs = np.linspace(scan_lo, mach_hi, _SCAN_POINTS)
    bnd = vn_stall_boundary(aircraft, stall_table, alt, fuel, machs)
    n_arr = np.asarray(bnd["n"])
    v_arr = np.asarray(bnd["V"])
    if not n_arr[0] <= 1.0 <= n_arr[-1]:
        return max(db_mach_lo, scan_lo)  # 스캔 범위에 V_S가 없다 — DB 하한이 실효 하한
    v_s = float(np.interp(1.0, n_arr, v_arr))
    atm = isa_atmosphere(alt)
    return max((v_s / atm.a) * mach_margin, db_mach_lo)


def coarse_grid(
    aircraft, stall_table, limits, db_ranges, *,
    n_mach=5, alts=None, fuels=None, mach_margin=1.1, budget=60,
    fingerprint="", on_progress=None,
) -> dict:
    """엔벨로프·DB 유도 coarse 격자 + 1회 트림 — {"points", "trims", "aborted"}.

    budget 초과는 제출 시점 ValueError (influence.py MAX_CASES 원칙 — 오타 예산이
    단일 워커를 점유하기 전에 차단). on_progress는 trim_batch 규약 그대로
    (truthy 반환 = 협조적 취소, 완료분 보존).
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
            lo = _mach_lo(aircraft, stall_table, alt, fuel, mach_hi, db_mach_lo, mach_margin)
            if lo >= mach_hi:
                continue  # 이 행은 유효 mach 구간이 없다 (고고도·고중량 — 데이터로 남길 것 없음)
            machs = np.round(np.linspace(lo, mach_hi, n_mach), 4)
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
    return {"points": points, "trims": trims, "aborted": aborted}
