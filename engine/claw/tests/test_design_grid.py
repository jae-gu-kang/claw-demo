"""M17 grid 검증 — 엔벨로프 유도 하한, 행별 비직사각 격자, 예산·취소, 결정론."""

import pytest

from claw.design import coarse_grid
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_stall_table,
    make_demo_structural_limits,
)


@pytest.fixture(scope="module")
def env():
    return (
        make_demo_aircraft(),
        make_demo_stall_table(),
        make_demo_structural_limits(),
        make_demo_db_ranges(),
    )


def test_coarse_grid_basic(env):
    ac, stall, limits, db = env
    out = coarse_grid(
        ac, stall, limits, db, n_mach=4, alts=(0.0, 3000.0), fuels=(40.0, 400.0),
    )
    points, trims = out["points"], out["trims"]
    assert out["aborted"] is None
    assert 0 < len(points) <= 16
    assert set(trims) == set(points.names())
    # 상한: min(mach_no 0.75, DB 0.9, 실속표 0.9) = 0.75 — 전 행 공통
    machs = [p.case.mach for p in points]
    assert max(machs) == pytest.approx(0.75)
    # trim_batch가 돌았고 trimmable이 전 점 판정되어 있다 (None 없음)
    assert all(p.trimmable is not None for p in points)
    assert any(p.trimmable for p in points)


def test_mach_lo_reflects_stall_speed(env):
    """중량·고도가 크면 V_S가 커져 행의 mach 하한이 올라간다 (여유 1.1 포함)."""
    ac, stall, limits, db = env
    out = coarse_grid(ac, stall, limits, db, n_mach=3, alts=(0.0, 5000.0), fuels=(40.0, 400.0))

    def row_lo(alt, fuel):
        return min(
            p.case.mach for p in out["points"]
            if p.case.alt == alt and p.case.fuel == fuel
        )

    assert row_lo(0.0, 400.0) > row_lo(0.0, 40.0)  # 무거우면 하한 상승
    assert row_lo(5000.0, 40.0) > row_lo(0.0, 40.0)  # 높으면 하한 상승
    assert row_lo(0.0, 40.0) > db["mach"][0]  # DB 하한이 아니라 실속 유도 하한


def test_budget_rejected_at_submit(env):
    ac, stall, limits, db = env
    with pytest.raises(ValueError, match="예산"):
        coarse_grid(ac, stall, limits, db, n_mach=10, budget=30)


def test_auto_alts_follow_reachable_envelope(env):
    """alts 미지정 — 고정 4단 대신 연료별 도달 엔벨로프에서 고도를 유도한다.

    구 기본(0·1·3·5 km)은 천장이 어디든 하단만 덮었다(사용자 지적). 자동 유도는
    연료(중량)별 천장까지 σ 균일로 벌리고, 귀속을 alts_auto로 동봉한다."""
    ac, stall, limits, db = env
    out = coarse_grid(ac, stall, limits, db, fuels=(40.0, 400.0), budget=60)
    auto = out["alts_auto"]
    assert [e["fuel"] for e in auto] == [40.0, 400.0]
    for e in auto:
        assert e["alts"][0] == 0.0 and e["alts"] == sorted(e["alts"])
        assert e["ceiling"] == e["alts"][-1]
        assert e["ceiling_source"] in ("alt_hi", "reach", "trim")
        assert e["trim_probe"] == "applied"
    # 경량 연료는 구 기본의 5 km 위까지 편다 — 하단 편중이 풀렸다
    assert auto[0]["alts"][-1] > 5000.0
    # 무거우면 천장이 낮다 (같은 추력으로 더 큰 중량)
    assert auto[1]["ceiling"] < auto[0]["ceiling"]
    # 점의 (fuel, alt)는 전부 선언한 자동 격자 좌표 안이다
    declared = {(e["fuel"], a) for e in auto for a in e["alts"]}
    assert {(p.case.fuel, p.case.alt) for p in out["points"]} <= declared


def test_auto_alts_leave_no_fully_untrimmable_row(env):
    """추력 천장 — 자동 격자의 어느 행도 통째로 트림 불가가 아니다.

    실속·마하 경계만 보면 12 km 행이 전 점 스로틀 포화였다(리뷰 실측: trimmable 33/60 →
    21/60). 트림 탐침이 그 행을 격자에서 뺀다."""
    ac, stall, limits, db = env
    out = coarse_grid(ac, stall, limits, db, budget=60)
    for e in out["alts_auto"]:
        for alt in e["alts"]:
            row = [p for p in out["points"] if p.case.fuel == e["fuel"] and p.case.alt == alt]
            assert row and any(p.trimmable for p in row), (e["fuel"], alt)


def test_auto_alts_fit_budget_by_reducing_count(env):
    """자동 모드의 단수는 예산에 맞춰 준다 — 상한 4단이 예산을 넘으면 2단까지 내려간다.

    지정 alts의 초과는 종전대로 제출 시점 거부(오타 예산 차단)이고, 자동은 애초에
    예산 안에서 유도하므로 거부할 일이 없다. 2단도 못 실으면 거부다."""
    ac, stall, limits, db = env
    # 예산 30 = 마하 5 × 연료 3 × 고도 2 — 연료별 2단으로 준다
    out = coarse_grid(ac, stall, limits, db, budget=30)
    assert all(len(e["alts"]) == 2 for e in out["alts_auto"])
    assert len(out["points"]) <= 30
    # 지정 alts 경로는 alts_auto가 없다 (자동이 아닌 것을 자동이라 하지 않는다)
    explicit = coarse_grid(ac, stall, limits, db, n_mach=3, alts=(0.0,), fuels=(200.0,))
    assert explicit["alts_auto"] is None
    # 지정 alts의 예산 초과는 종전대로 제출 시점 거부 (5 × 4 × 3 = 60 > 30)
    with pytest.raises(ValueError, match="예산"):
        coarse_grid(ac, stall, limits, db, alts=(0.0, 1000.0, 3000.0, 5000.0), budget=30)
    # 빈 연료 목록은 0점이지 0 나눗셈이 아니다 (API가 "fuels": []를 받는다)
    empty = coarse_grid(ac, stall, limits, db, fuels=())
    assert len(empty["points"]) == 0 and empty["alts_auto"] == []


def test_deterministic(env):
    ac, stall, limits, db = env
    kw = dict(n_mach=3, alts=(1000.0,), fuels=(200.0,))
    a = coarse_grid(ac, stall, limits, db, **kw)
    b = coarse_grid(ac, stall, limits, db, **kw)
    assert a["points"].names() == b["points"].names()
    assert [p.trimmable for p in a["points"]] == [p.trimmable for p in b["points"]]


def test_cancel_preserves_partial(env):
    ac, stall, limits, db = env
    out = coarse_grid(
        ac, stall, limits, db, n_mach=3, alts=(1000.0,), fuels=(200.0,),
        on_progress=lambda done, total, msg: done >= 2,
    )
    assert out["aborted"] == "cancelled"
    assert len(out["trims"]) == 2  # 완료분 보존
