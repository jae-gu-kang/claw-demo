"""M17 grid 검증 — 엔벨로프 유도 하한, 행별 비직사각 격자, 예산·취소, 결정론."""

import functools

import pytest

from claw.design import coarse_grid
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_stall_table,
    make_demo_structural_limits,
)
from claw.opspace.verdict import VerdictContext
from claw.profile import example_profile


@functools.lru_cache(maxsize=None)
def _ctx():
    """예제 기체의 조건 판정 문맥 — 트림 탭과 같은 생성자(from_profile)."""
    return VerdictContext.from_profile(example_profile())


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
        ac, stall, limits, db, ctx=_ctx(), n_mach=4, alts=(0.0, 3000.0), fuels=(40.0, 400.0),
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
    out = coarse_grid(ac, stall, limits, db, ctx=_ctx(), n_mach=3, alts=(0.0, 5000.0), fuels=(40.0, 400.0))

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
        coarse_grid(ac, stall, limits, db, ctx=_ctx(), n_mach=10, budget=30)


def test_deterministic(env):
    ac, stall, limits, db = env
    kw = dict(n_mach=3, alts=(1000.0,), fuels=(200.0,))
    a = coarse_grid(ac, stall, limits, db, ctx=_ctx(), **kw)
    b = coarse_grid(ac, stall, limits, db, ctx=_ctx(), **kw)
    assert a["points"].names() == b["points"].names()
    assert [p.trimmable for p in a["points"]] == [p.trimmable for p in b["points"]]


def test_cancel_preserves_partial(env):
    ac, stall, limits, db = env
    out = coarse_grid(
        ac, stall, limits, db, ctx=_ctx(), n_mach=3, alts=(1000.0,), fuels=(200.0,),
        on_progress=lambda done, total, msg: done >= 2,
    )
    assert out["aborted"] == "cancelled"
    assert len(out["trims"]) == 2  # 완료분 보존


# ── 이관 2단계 — COARSE는 요구영역의 기본 격자에서 (05 §11.13 2단계) ──────────────────────────────────────────
from claw.design.grid import region_grid, select_coarse  # noqa: E402
from claw.opspace import MODEL_GAP, NOT_RUN, ModelRange, Region, base_grid  # noqa: E402


def _region(mach=(0.3, 0.55), alts=(100.0, 1000.0, 3000.0), fuels=(200.0,), n_mach=6, boundary=None):
    return Region(mach=mach, alt=(min(alts), max(alts)), fuel=(min(fuels), max(fuels)), boundary=boundary,
                  grid={"n_mach": n_mach, "alts": alts, "fuels": fuels}, confirmed=True, source="profile")


_MODEL = ModelRange(mach=(0.0, 0.9), fuel=(0.0, 400.0))


def test_select_coarse_takes_the_whole_base_grid_within_budget():
    base = base_grid(_region(), _MODEL)
    sel = select_coarse(base, budget=100)
    assert [p["name"] for p in sel["points"]] == [p["name"] for p in base["points"]]
    assert sel["dropped"] == [] and sel["axis_kept"] == sel["axis_interior"]


def test_select_coarse_keeps_row_ends_and_thins_common_coordinates_to_the_budget():
    base = base_grid(_region(n_mach=11), _MODEL)  # 행마다 0.3~0.55 공통 좌표 11점 × 3행 = 33점
    sel = select_coarse(base, budget=15)
    names = {p["name"] for p in sel["points"]}
    assert len(names) == 15  # 행 끝 6 + 내부 공통 좌표 3개 × 3행
    for alt in (100.0, 1000.0, 3000.0):
        row = sorted(p["mach"] for p in sel["points"] if p["alt"] == alt)
        assert row[0] == 0.3 and row[-1] == 0.55  # 행 경계는 늘 남는다
        assert row[1:-1] == sel["axis_kept"]  # 내부는 모든 행이 같은 공통 좌표 — 절점·검증점과 어긋나지 않게
    assert len(sel["axis_kept"]) == 3 and len(sel["dropped"]) == 33 - 15
    assert {p["name"] for p in base["points"]} == names | set(sel["dropped"])  # 뺀 점은 이름으로 남는다


def test_select_coarse_keeps_required_conditions_and_refuses_a_budget_below_the_boundary():
    base = base_grid(_region(n_mach=11), _MODEL)
    req = next(p for p in base["points"] if p["mach"] == 0.425 and p["alt"] == 1000.0)
    sel = select_coarse(base, budget=8, required=[req["name"]])
    assert req["name"] in {p["name"] for p in sel["points"]} and len(sel["points"]) == 7
    with pytest.raises(ValueError, match="예산"):
        select_coarse(base, budget=5)  # 행 끝 6점도 못 담는다 — 제출 시점에 거부(요구 경계를 몰래 빼지 않는다)


def test_select_coarse_keeps_central_coordinates_not_the_lowest():
    """안쪽 좌표를 하나만 남길 수 있으면 가운데를 남긴다 — 양 끝 포함 linspace(k=1)는 [0]이라 하한 바로 옆만 남겼다.
    k개는 가운데 정렬 간격((i+½)·n/k)이다 — 행 끝점이 이미 경계를 덮으므로 안쪽은 구간 가운데로 퍼진다."""
    base = base_grid(_region(n_mach=11), _MODEL)  # 안쪽 공통 좌표 9개(0.325~0.525)
    sel = select_coarse(base, budget=9)  # 행 끝 6 + 안쪽 1 × 3행
    assert sel["axis_kept"] == [0.425]
    sel = select_coarse(base, budget=15)
    assert sel["axis_kept"] == [0.35, 0.425, 0.5]
    assert select_coarse(base, budget=15) == sel  # 결정적


def test_region_grid_trims_only_points_to_compute_and_keeps_model_gaps_with_a_verdict(env):
    ac = env[0]
    region = _region(mach=(0.5, 0.95), alts=(1000.0,), n_mach=4)  # 0.95는 DB 상한 0.9 밖 — 모델 부족
    out = region_grid(ac, region, _MODEL, ctx=_ctx(), budget=20)
    pts = out["points"]
    assert out["aborted"] is None
    assert [p.case.mach for p in pts] == [0.5, 0.65, 0.8, 0.95]
    gap = pts.get(next(n for n in pts.names() if n.startswith("M0.95_")))
    assert gap.name not in out["trims"]  # 트림을 돌리지 않는다
    assert gap.trimmable is False and gap.verdict["trim"]["status"] == MODEL_GAP
    assert gap.verdict["exclusion"] == {"category": "model", "reasons": [MODEL_GAP]}
    assert set(out["trims"]) == {p.name for p in pts if p is not gap}
    assert all(p.verdict is not None and p.trimmable is p.verdict["adopted"] for p in pts)
    assert [p["state"] for p in out["base"]["points"]] == [NOT_RUN, NOT_RUN, NOT_RUN, MODEL_GAP]
    assert all(p["selected"] for p in out["base"]["points"])


def test_region_grid_does_not_shrink_the_requirement_to_the_stall_floor(env):
    """coarse_grid는 행마다 실속 하한 × 1.1부터 등분했다 — 요구를 물리로 깎는 반례(05 §11.2). 기본 격자는 요구 하한부터
    두고, 날 수 없는 점은 버리지 않고 판정(제외 사유)으로 남긴다."""
    ac = env[0]
    region = _region(mach=(0.1, 0.4), alts=(0.0,), fuels=(400.0,), n_mach=4)
    out = region_grid(ac, region, _MODEL, ctx=_ctx(), budget=20)
    low = out["points"].get(next(n for n in out["points"].names() if n.startswith("M0.1_")))
    assert low.trimmable is False and low.verdict["exclusion"] is not None
