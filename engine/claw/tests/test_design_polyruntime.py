"""다항 게인 스케줄 런타임 검증 — PolyBlock·그래프 실행·GainSchedule 수용 (01 §3.4)."""

import numpy as np
import pytest

from claw.blocks.lookup import PolyBlock
from claw.codegen.ir_exec import GraphRunner
from claw.design import fit_gain_surface
from claw.fcl.demo import make_demo_fcl, make_demo_gain_tables
from claw.fcl.graphs import gain_schedule_graph
from claw.fcl.schedule import GainSchedule
from claw.tables import PolyTable, Table

MACHS = np.round(np.arange(0.15, 0.951, 0.05), 4)
DP = np.minimum((0.6 / MACHS) ** 2, 4.0)


@pytest.fixture(scope="module")
def poly():
    out = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02)
    return PolyTable("mach", out["segments"], name="pitch.kp")


def test_polyblock_step(poly):
    blk = PolyBlock(poly).init(0.01)
    for x in (0.15, 0.3, 0.31, 0.62, 0.95, 0.05, 1.2):
        assert blk.step(x) == poly.interp(mach=x)  # 비트 일치 (같은 구현 경유)


def test_graph_runner_matches_interp(poly):
    """gain_schedule_graph에 다항 자리가 섞여도 실행 결과 == 직접 평가 (필터 통과)."""
    tab = Table({"mach": MACHS}, 0.4 * DP, name="pitch.k_rate", extrapolate="clip")
    graph = gain_schedule_graph(
        tables={"pitch.kp": poly, "pitch.k_rate": tab}, filter_tau=0.0
    )
    runner = GraphRunner(graph, 0.01)
    runner.reset()
    for x in (0.2, 0.45, 0.62, 1.1):
        out = runner.step_all(mach=x)
        assert out["pitch_kp"] == poly.interp(mach=x)
        assert out["pitch_k_rate"] == tab.interp(mach=x)


def test_gain_schedule_accepts_polytable(poly):
    sched = GainSchedule({"pitch.kp": poly}, filter_tau=0.0).init(0.01)
    g = sched.step(mach=0.62, alt=1000.0, fuel=200.0)
    assert g["pitch"]["kp"] == poly.interp(mach=0.62)
    assert sched.used_vars == ("mach",)


def test_gain_schedule_rejects_non_table():
    with pytest.raises(ValueError, match="Table/PolyTable"):
        GainSchedule({"pitch.kp": 1.0})


def test_make_demo_fcl_with_poly_slot(poly):
    """조립 정본(make_demo_fcl)에 다항 자리가 섞인 형상 — 초기화·스텝이 성립한다."""
    tables = make_demo_gain_tables()
    tables["pitch.kp"] = poly
    law = make_demo_fcl(gain_tables=tables)
    law.init(0.01)
    assert law.schedule.tables["pitch.kp"] is poly
