"""M17 refine 검증 — 저마하 집중 세분화, anytime 예산·취소, 깊이 상한, 결정론."""

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    LinearModelSet,
    OperatingPoint,
    PointSet,
    case_name,
    refine_trim_points,
)
from claw.plant import make_demo_aircraft
from claw.trim import trim_level


def _setup(machs, alt=1000.0, fuel=200.0):
    ac = make_demo_aircraft()
    points = PointSet()
    trims = {}
    for m in machs:
        case = TrimCase(name=case_name(m, alt, fuel), mach=m, alt=alt, fuel=fuel)
        tr = trim_level(ac, case, fingerprint="fp")
        assert tr.converged
        trims[case.name] = tr
        pt = OperatingPoint(case=case, role=ROLE_ANCHOR, origin="coarse")
        pt.trimmable = True
        points.add(pt)
    return ac, points, LinearModelSet(), trims


def test_refine_concentrates_at_low_mach():
    """같은 Δmach 간격에서 저마하(동압 급변) 구간이 먼저·더 많이 쪼개진다."""
    # 격자는 새 엔벨로프(해면 M0.21~0.60 @연료200) 안에서 종전 간격 구조를 유지한다
    ac, points, lms, trims = _setup((0.25, 0.40, 0.55))
    report = refine_trim_points(ac, points, lms, trims, tol=0.25, max_points=12)
    assert report["inserted"], "세분화가 한 점도 없다 — tol이 데모 격자에 못 미침"
    # 최악 쌍부터 — 첫 삽입은 저마하 쌍(0.25-0.40)의 중점
    assert points.get(report["inserted"][0]).case.mach == pytest.approx(0.325)
    low = sum(1 for n in report["inserted"] if points.get(n).case.mach < 0.40)
    high = len(report["inserted"]) - low
    assert low >= high
    # 삽입점은 전부 anchor·refine 계보, 트림·선형모델이 채워져 있다
    for n in report["inserted"]:
        assert points.get(n).origin == "refine"
        assert n in trims


def test_refine_terminates_and_reports_remaining():
    ac, points, lms, trims = _setup((0.3, 0.4, 0.5))
    report = refine_trim_points(ac, points, lms, trims, tol=0.25, max_points=40, max_depth=2)
    # 종료: 큐 소진 또는 깊이 상한 — 남은 최대 거리가 보고된다
    assert report["aborted"] in (None, "budget_points")
    assert report["max_d_remaining"] >= 0.0


def test_max_depth_actually_limits_subdivision():
    """깊이 상한이 종료 3겹의 한 겹이라면 값이 결과를 바꿔야 한다.

    종전 테스트는 `aborted in (None, 'budget_points')`와 `max_d_remaining >= 0`만
    봤는데 둘 다 무조건 참이라, max_depth를 2에서 999로 바꿔도 통과했다.
    """
    shallow = refine_trim_points(*_setup((0.25, 0.35, 0.45)), tol=0.25,
                                 max_points=60, max_depth=1)
    deep = refine_trim_points(*_setup((0.25, 0.35, 0.45)), tol=0.25,
                              max_points=60, max_depth=4)
    assert len(shallow["inserted"]) < len(deep["inserted"]), (
        f"깊이 상한이 삽입 수를 제한하지 못한다: {len(shallow['inserted'])} vs "
        f"{len(deep['inserted'])}"
    )
    # 깊이 d는 초기 쌍마다 이분 트리 depth d까지 — 상한이 그 산술을 넘지 않는다
    assert len(shallow["inserted"]) <= shallow["pairs_initial"] * (2 ** 2 - 1)


def test_budget_counts_all_points_not_just_anchors():
    """예산 단위는 **전체 점 수** — orchestrator·서버 상한과 같은 단위여야 한다.

    anchor만 세면 검증점이 쌓인 뒤 앵커를 상한까지 채워 총점이 상한을 넘는다.
    """
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_VALIDATION, OperatingPoint, case_name

    ac, points, lms, trims = _setup((0.25, 0.35, 0.45))
    # 검증점 3개를 미리 얹어 둔다 (이터 2 상황)
    for m in (0.3, 0.5, 0.6):
        points.add(OperatingPoint(
            case=TrimCase(name=case_name(m, 1000.0, 200.0), mach=m, alt=1000.0, fuel=200.0),
            role=ROLE_VALIDATION, origin="test",
        ))
    before = len(points)
    refine_trim_points(ac, points, lms, trims, tol=0.25, max_points=before + 2)
    assert len(points) <= before + 2


def test_budget_is_anytime():
    """max_points에 걸려 끊겨도 삽입된 것은 가장 필요한 곳(최악 쌍)부터다."""
    full_report = refine_trim_points(*_setup((0.25, 0.35, 0.45)), tol=0.25, max_points=40)
    cut = refine_trim_points(*_setup((0.25, 0.35, 0.45)), tol=0.25, max_points=4)
    assert cut["aborted"] == "budget_points"
    # 예산 내 삽입 목록 = 전체 실행의 앞부분 (우선순위 순서 동일)
    assert cut["inserted"] == full_report["inserted"][: len(cut["inserted"])]


def test_deterministic():
    a = refine_trim_points(*_setup((0.25, 0.35, 0.45)), tol=0.25, max_points=12)
    b = refine_trim_points(*_setup((0.25, 0.35, 0.45)), tol=0.25, max_points=12)
    assert a["inserted"] == b["inserted"]


def test_cancel_preserves_partial():
    ac, points, lms, trims = _setup((0.25, 0.35, 0.45))
    report = refine_trim_points(
        ac, points, lms, trims, tol=0.25, max_points=40,
        on_progress=lambda done, total, msg: done >= 2,
    )
    assert report["aborted"] == "cancelled"
    assert len(report["inserted"]) == 2
