"""adaptive 트림점 삽입 — 인접 앵커 간 플랜트 거리(model_distance) 기반 우선순위 큐 이분법.

"선형화 결과의 변화량을 보고 트림 포인트를 자동 삽입한다"의 구현. 인접 앵커쌍의
무차원 거리 d_total이 tol을 넘으면 달라지는 축의 중점에 새 앵커를 넣고, 양쪽 절반을
재평가해 큐에 되넣는다. 최악 쌍부터 처리하는 우선순위 큐라 **예산 내 언제 끊어도
가장 필요한 곳부터 세분화돼 있다** (anytime — 협조적 취소·예산 소진과 정합).

종료 3겹: 큐 소진(전 쌍 d ≤ tol) ∨ max_points ∨ 쌍별 분할 깊이 max_depth
(기본 3 = 초기 간격의 1/8). 미수렴 중점은 삽입하되 trimmable=False로 남기고 그
쌍은 더 쪼개지 않는다 — "비수렴 갭"의 데이터화 (엔벨로프 구멍을 조용히 메우지
않는다).
"""

import heapq
import itertools

import numpy as np

from claw.common.contracts import TrimCase
from claw.design.linmodels import model_distance
from claw.design.points import AXES, ROLE_ANCHOR, OperatingPoint, case_name
from claw.trim import trim_level

_ROUND = 6  # 중점 좌표 반올림 자릿수 — depth 3(간격 1/8)까지 이름 안정


def _usable(points, trims, name):
    pt = points.get(name)
    tr = trims.get(name)
    return tr is not None and tr.converged and pt.trimmable is not False


def _pair_distance(aircraft, lms, trims, name_a, name_b):
    tr_a, tr_b = trims[name_a], trims[name_b]
    return model_distance(lms.get(aircraft, tr_a), lms.get(aircraft, tr_b), tr_a, tr_b)


def _midpoint_case(ca, cb, axis):
    coords = {
        "mach": (ca.mach + cb.mach) / 2.0,
        "alt": (ca.alt + cb.alt) / 2.0,
        "fuel": (ca.fuel + cb.fuel) / 2.0,
    }
    coords[axis] = round(coords[axis], _ROUND)
    return TrimCase(
        name=case_name(coords["mach"], coords["alt"], coords["fuel"]),
        mach=coords["mach"], alt=coords["alt"], fuel=coords["fuel"],
    )


def _seed_z(trims, name_a, name_b, ca, cb, mid, axis):
    """중점 초기값 — 축상 더 가까운 쪽 수렴해 (trim_batch 인접 시드와 같은 원리)."""
    da = abs(getattr(mid, axis) - getattr(ca, axis))
    db = abs(getattr(mid, axis) - getattr(cb, axis))
    tr = trims[name_a] if da <= db else trims[name_b]
    return np.array([tr.state.euler()[1], tr.control.elevon[0], tr.control.throttle[0]])


def refine_trim_points(
    aircraft, points, lms, trims, *,
    tol=0.25, max_points=120, max_depth=3,
    fingerprint="", on_progress=None,
) -> dict:
    """인접 앵커쌍 거리 > tol인 곳에 중점 앵커 삽입 (제자리 갱신) — 리포트 반환.

    points·lms·trims를 제자리 갱신한다. tol 0.25 [기본값] = "인접점 간 25% 이상
    플랜트 변화면 격자가 성기다". 이 상수는 분류기의 plant_variation 판정
    (classify.tol_plant)과 **같은 값을 공유해야 한다** — 기준 이원화 금지.
    """
    if tol <= 0:
        raise ValueError(f"tol은 양수: {tol}")

    counter = itertools.count()  # 동률 d에서 힙 비교가 dict로 넘어가지 않게 하는 단조 카운터
    heap: list = []

    def _push(name_a, name_b, axis, depth):
        if depth > max_depth:
            return None
        if not (_usable(points, trims, name_a) and _usable(points, trims, name_b)):
            return None
        d = _pair_distance(aircraft, lms, trims, name_a, name_b)
        if d["d_total"] > tol:
            heapq.heappush(heap, (-d["d_total"], next(counter), name_a, name_b, axis, depth))
        return d

    pairs0 = points.adjacent_pairs(ROLE_ANCHOR)
    for name_a, name_b, axis in pairs0:
        _push(name_a, name_b, axis, 0)

    inserted, gaps = [], []
    aborted = None
    while heap:
        if len(points.by_role(ROLE_ANCHOR)) >= max_points:
            aborted = "budget_points"
            break
        neg_d, _, name_a, name_b, axis, depth = heapq.heappop(heap)
        ca, cb = points.get(name_a).case, points.get(name_b).case
        mid = _midpoint_case(ca, cb, axis)
        if mid.name in points:
            continue  # 다른 축 경로로 이미 삽입된 좌표
        z0 = _seed_z(trims, name_a, name_b, ca, cb, mid, axis)
        tr = trim_level(aircraft, mid, z0=z0, fingerprint=fingerprint)
        trims[mid.name] = tr
        pt = OperatingPoint(case=mid, role=ROLE_ANCHOR, origin="refine")
        pt.trimmable = bool(
            tr.converged and tr.flags.get("saturation_ok") and tr.flags.get("alpha_margin_ok")
        )
        points.add(pt)
        inserted.append(mid.name)
        if tr.converged:
            _push(name_a, mid.name, axis, depth + 1)
            _push(mid.name, name_b, axis, depth + 1)
        else:
            gaps.append({
                "pair": (name_a, name_b), "midpoint": mid.name, "axis": axis,
                "d_total": -neg_d,
                "note": "미수렴 중점 — 이 구간은 더 쪼개지 않는다 (비수렴 갭)",
            })
        if on_progress is not None and on_progress(
            len(inserted), max_points, f"refine {mid.name}"
        ):
            aborted = "cancelled"
            break

    remaining = max((-h[0] for h in heap), default=0.0)
    return {
        "inserted": inserted,
        "gaps": gaps,
        "aborted": aborted,
        "pairs_initial": len(pairs0),
        "max_d_remaining": float(remaining),
        "tol": float(tol),
    }
