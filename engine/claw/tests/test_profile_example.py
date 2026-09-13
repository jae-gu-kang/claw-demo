"""예제 기체 문서 ≡ 구 데모 코드 — 한 프로세스 안에서 비트 동일 비교 (02 §5.6).

단계 1(데모 코드가 아직 원본)에서는 문서로 만든 객체를 원본 코드와 직접 대조한다. 데모 함수가
이 문서를 감싸는 래퍼로 바뀐 뒤에는 이 대조가 자기 자신과의 비교가 되므로, 그때부터의 독립
증거는 이관 전 HEAD에서 굳힌 골든(test_golden_profile_example.py)이다.
"""

import pathlib
import sys

import pytest

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"
sys.path.insert(0, str(GOLDEN))

import engine_goldens  # noqa: E402
import hexjson  # noqa: E402

from claw.fcl.autopilot import Autopilot  # noqa: E402
from claw.fcl.demo import (  # noqa: E402
    DEMO_ALLOC_RESV_FRAC,
    DEMO_ALPHA_MARGIN,
    DEMO_K_DIFF_THR,
    DEMO_PITCH,
    DEMO_ROLL,
    DEMO_YAW,
    demo_design_gains,
    demo_rate_filters,
    make_demo_gain_tables,
)
from claw.fcl.scas import ScasAxis  # noqa: E402
from claw.plant import (  # noqa: E402
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_launch_rail,
    make_demo_skid_gear,
    make_demo_stall_table,
    make_demo_structural_limits,
    make_demo_trim_elevator_table,
)
from claw.plant.demo import RAIL_ORIGIN_H  # noqa: E402
from claw.profile import EXAMPLE_ID, example_profile  # noqa: E402
from claw.trim.trim import ALPHA_BOUNDS, ALPHA_MARGIN, DE_BOUNDS  # noqa: E402


def same(a, b):
    ea, eb = hexjson.encode(a), hexjson.encode(b)
    assert hexjson.dumps(ea) == hexjson.dumps(eb), hexjson.first_diff(ea, eb)


@pytest.mark.parametrize("label,dispersion", engine_goldens.DISPERSIONS)
def test_aero_coefficients_are_bit_identical(label, dispersion):
    new = example_profile().aircraft(dispersion=dispersion).aero.coef_fn
    old = make_demo_aircraft(dispersion=dispersion).aero.coef_fn
    for inp in engine_goldens._aero_inputs():
        same(new(dict(inp)), old(dict(inp)))


@pytest.mark.parametrize("label,dispersion", engine_goldens.DISPERSIONS)
def test_mass_engine_and_reference_geometry(label, dispersion):
    new = example_profile().aircraft(dispersion=dispersion)
    old = make_demo_aircraft(dispersion=dispersion)
    same(new.fuel_mass, old.fuel_mass)
    same(new.engine, old.engine)
    assert type(new.engine) is type(old.engine)
    same((new.aero.S, new.aero.cbar, new.aero.b), (old.aero.S, old.aero.cbar, old.aero.b))


def test_boundary_tables_limits_and_ground():
    p = example_profile()
    same(p.stall_table(), make_demo_stall_table())
    same(p.alloc_trim_table(), make_demo_trim_elevator_table())
    same(p.db_ranges(), make_demo_db_ranges())
    same(p.structural_limits(), make_demo_structural_limits())
    same(p.skid_gear(), make_demo_skid_gear())
    same(p.launch_rail(), make_demo_launch_rail())
    assert p.rail_origin_height == RAIL_ORIGIN_H
    same(p.trim_alpha_bounds, ALPHA_BOUNDS)
    assert p.trim_alpha_margin == ALPHA_MARGIN
    same(p.surfaces["elevon"], DE_BOUNDS)
    assert p.q_max is None and p.operating == {"alt_min": None, "alt_max": None}


def test_tables_are_built_fresh_each_call():
    p = example_profile()
    assert p.stall_table() is not p.stall_table()
    assert p.stall_table().data is not p.stall_table().data


def test_law_data_matches_demo_assembly():
    p = example_profile()
    for axis, demo in (("pitch", DEMO_PITCH), ("roll", DEMO_ROLL), ("yaw", DEMO_YAW)):
        same(ScasAxis(**p.scas_axis_params(axis)).cfg, ScasAxis(**demo).cfg)
    same(p.autopilot_params(), Autopilot().cfg)
    assert p.k_diff_thr == DEMO_K_DIFF_THR
    assert p.law["alpha_margin"] == DEMO_ALPHA_MARGIN
    assert p.law["filter_tau"] == 0.5  # make_demo_fcl의 GainSchedule(filter_tau=0.5)
    assert p.alloc_resv_frac == DEMO_ALLOC_RESV_FRAC
    same(p.design_gains(), demo_design_gains())
    same(p.rate_filters(), demo_rate_filters())
    same(p.gain_tables(), make_demo_gain_tables())
    everything = sorted(demo_design_gains())
    same(p.gain_tables(everything), make_demo_gain_tables(everything))


def test_example_identity_and_dispersion_axes():
    p = example_profile()
    assert p.id == EXAMPLE_ID and p.is_example is True
    assert p.dispersion_axes == ("mass", "cmalpha", "cmq")
