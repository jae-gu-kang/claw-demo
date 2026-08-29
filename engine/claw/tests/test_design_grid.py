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
