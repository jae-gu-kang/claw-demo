"""예제 기체(구 데모) 엔진 산출 골든 — 프로파일 이관 전 HEAD에서 굳힌다 (02 §5.6).

각 항목은 **값을 계산하는 함수**다. 저장된 값(profile_example/*.json)은 이관 내내 고정이고,
이관이 진행되며 바뀌는 것은 이 함수들의 **호출 경로**뿐이다(make_demo_* → 프로파일 빌드).
그래서 함수가 옛 API를 부르든 새 API를 부르든 같은 수가 나와야 테스트가 통과한다.

mode: "full"은 값 전체를 저장, "digest"는 조각별 sha256 + 표본(긴 목록).
"""

import numpy as np

from claw.analysis import aero_envelope, design_envelope, vn_envelope
from claw.common.contracts import TrimCase
from claw.design.points import envelope_verdict
from claw.fcl.demo import demo_design_gains, demo_rate_filters, make_demo_gain_tables
from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.evaluate import _corner_dispersions, evaluate, verify
from claw.pipeline.influence import Shape
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_launch_rail,
    make_demo_skid_gear,
    make_demo_stall_table,
    make_demo_structural_limits,
    make_demo_trim_elevator_table,
)
from claw.plant.demo import RAIL_ORIGIN_H, DispersionSet
from claw.trim import linearize, split_axes, trim_batch
from claw.trim.trim import trim
from claw.profile import example_profile

SEED = 20260914
DISPERSIONS = (
    ("nominal", None),
    ("mass+cma-cmq+", DispersionSet(mass=0.2, cmalpha=-0.2, cmq=0.2)),
    ("cma+cmq-", DispersionSet(cmalpha=0.2, cmq=-0.2)),
)


def _aircraft(dispersion=None, ground=None):
    return make_demo_aircraft(ground=ground, dispersion=dispersion)


def _aero_inputs():
    rs = np.random.RandomState(SEED)
    out = []
    for _ in range(1500):
        out.append({
            "alpha": rs.uniform(-0.25, 0.5), "beta": rs.uniform(-0.3, 0.3),
            "V": rs.uniform(5.0, 300.0), "mach": rs.uniform(0.0, 0.95),
            "phat": rs.uniform(-0.2, 0.2), "qhat": rs.uniform(-0.2, 0.2),
            "rhat": rs.uniform(-0.2, 0.2),
            "de": rs.uniform(-0.35, 0.35), "da": rs.uniform(-0.35, 0.35),
            "dr": rs.uniform(-0.35, 0.35),
        })
    # 부호 있는 0과 타면 입력 누락 — 합을 0.0에서 시작하면 −0.0이 +0.0으로 바뀐다
    out.append({"alpha": -0.0, "beta": -0.0, "V": 50.0, "mach": 0.15,
                "phat": -0.0, "qhat": -0.0, "rhat": -0.0})
    out.append({"alpha": 0.0, "beta": 0.0, "V": 0.0, "mach": 0.0, "phat": 0.0,
                "qhat": 0.0, "rhat": 0.0, "de": 0.0, "da": 0.0, "dr": 0.0})
    out.append({"alpha": 0.1, "beta": 0.05, "V": 80.0, "mach": 0.24, "phat": 0.01,
                "qhat": 0.02, "rhat": -0.01, "de": -0.0})
    return out


def aero_coef():
    inputs = _aero_inputs()
    rows = []
    for _label, d in DISPERSIONS:
        coef = _aircraft(d).aero.coef_fn
        rows.extend(coef(dict(inp)) for inp in inputs)
    return rows


def aero_forces():
    rs = np.random.RandomState(SEED + 1)
    rows = []
    for _label, d in DISPERSIONS:
        aero = _aircraft(d).aero
        for _ in range(150):
            rho = rs.uniform(0.3, 1.3)
            vel = np.array([rs.uniform(10.0, 250.0), rs.uniform(-10, 10), rs.uniform(-20, 30)])
            omega = np.array([rs.uniform(-1, 1), rs.uniform(-1, 1), rs.uniform(-1, 1)])
            controls = {"de": rs.uniform(-0.35, 0.35), "da": rs.uniform(-0.35, 0.35),
                        "dr": rs.uniform(-0.35, 0.35)}
            mach = rs.uniform(0.02, 0.9)
            rows.append(aero.forces(rho, vel, omega, controls, mach=mach))
    return rows


def mass_and_propulsion():
    rows = {}
    for label, d in DISPERSIONS:
        ac = _aircraft(d)
        rows[label] = [ac.fuel_mass.at(f) for f in (0.0, 100.0, 200.0, 300.0, 400.0, 450.0)]
    ac = _aircraft()
    rs = np.random.RandomState(SEED + 2)
    thrust = [ac.engine.forces((t, t), v, rho)
              for t, v, rho in [(0.0, 0.0, 1.225), (1.0, 0.0, 1.225), (0.5, 66.7, 1.0)]
              + [(rs.uniform(0, 1), rs.uniform(0, 280), rs.uniform(0.3, 1.3)) for _ in range(60)]]
    rows["thrust"] = thrust
    return rows


def plant_data():
    ac = _aircraft()
    return {
        "aero_ref": (ac.aero.S, ac.aero.cbar, ac.aero.b),
        "fuel_mass": ac.fuel_mass,
        "engine": ac.engine,
        "stall_table": make_demo_stall_table(),
        "trim_elevator_table": make_demo_trim_elevator_table(),
        "db_ranges": make_demo_db_ranges(),
        "structural_limits": make_demo_structural_limits(),
        "skid_gear": make_demo_skid_gear(),
        "launch_rail": make_demo_launch_rail(),
        "rail_origin_h": RAIL_ORIGIN_H,
        "trim_alpha_bounds": ac.trim_bounds["alpha"],
    }


def deriv_euler():
    rs = np.random.RandomState(SEED + 3)
    rows = []
    free = _aircraft()
    gear = _aircraft(ground=make_demo_skid_gear())
    for ac, h_lo, h_hi, u_hi in ((free, 0.0, 5000.0, 250.0), (gear, -0.3, 3.0, 45.0)):
        for _ in range(80):
            xe = np.array([
                rs.uniform(0.0, u_hi), rs.uniform(-3, 3), rs.uniform(-5, 5),
                rs.uniform(-0.5, 0.5), rs.uniform(-0.5, 0.5), rs.uniform(-0.5, 0.5),
                rs.uniform(-0.4, 0.4), rs.uniform(-0.3, 0.4), rs.uniform(-3, 3),
                rs.uniform(-500, 500), rs.uniform(-500, 500), rs.uniform(h_lo, h_hi),
            ])
            t = rs.uniform(0.0, 1.0)
            controls = {"de": rs.uniform(-0.35, 0.35), "da": rs.uniform(-0.35, 0.35),
                        "dr": rs.uniform(-0.35, 0.35), "throttle": (t, t)}
            rows.append(ac.deriv_euler(xe, controls, rs.uniform(0.0, 400.0)))
    return rows


def _grid_cases():
    return [TrimCase(name=f"M{m:g}_h{h:g}_f{f:g}", mach=m, alt=h, fuel=f)
            for f in (0.0, 200.0, 400.0)
            for h in (0.0, 1000.0, 3000.0, 5000.0)
            for m in np.round(np.arange(0.15, 0.751, 0.05), 4).tolist()]


def trim_grid():
    ac = _aircraft()
    trs = trim_batch(ac, _grid_cases(), fingerprint="golden")
    return [(tr, envelope_verdict(tr, ac.trim_bounds["de"])) for tr in trs]


def trim_special():
    gear = _aircraft(ground=make_demo_skid_gear())
    ground = trim(gear, TrimCase(name="ground", mach=0.0, alt=0.0, fuel=300.0,
                                 condition="ground"))
    cases = [TrimCase(name="a", mach=0.4, alt=1000.0, fuel=200.0),
             TrimCase(name="b", mach=0.3, alt=0.0, fuel=400.0)]
    dispersed = [trim_batch(_aircraft(d), cases) for _label, d in DISPERSIONS[1:]]
    return {"ground": ground, "dispersed": dispersed}


def linear_models():
    ac = _aircraft()
    cases = [TrimCase(name="lo", mach=0.3, alt=0.0, fuel=200.0),
             TrimCase(name="mid", mach=0.45, alt=1000.0, fuel=200.0),
             TrimCase(name="hi", mach=0.55, alt=3000.0, fuel=0.0)]
    out = []
    for tr in trim_batch(ac, cases):
        lm = linearize(ac, tr)
        out.append({"full": lm, "split": split_axes(lm)})
    return out


def envelopes():
    ac = _aircraft()
    stall, limits, db = make_demo_stall_table(), make_demo_structural_limits(), make_demo_db_ranges()
    return {
        "vn_prot": vn_envelope(ac, stall, limits, alt=1000.0, fuel=200.0, alpha_margin=0.05),
        "vn_stall": vn_envelope(ac, stall, limits, alt=3000.0, fuel=400.0),
        "design_default": design_envelope(ac, stall, limits, db, fuel=200.0),
        "design_full": design_envelope(ac, stall, limits, db, fuel=300.0, q_max=20000.0,
                                       alt_min=0.0, alt_max=9000.0, nz=3.0),
        "aero": aero_envelope(stall, db, alpha_margin=0.05, trim_alpha_bounds=ac.trim_bounds["alpha"]),
    }


def gains():
    design = demo_design_gains()
    return {
        "design": design,
        "rate_filters": demo_rate_filters(),
        "tables_default": make_demo_gain_tables(),
        "tables_all": make_demo_gain_tables(sorted(design)),
    }


def evaluate_linear():
    ac = _aircraft()
    cases = [TrimCase(name=f"M{m}", mach=m, alt=1000.0, fuel=200.0) for m in (0.35, 0.45, 0.55)]
    return evaluate(ac, trim_batch(ac, cases), Shape(profile=example_profile()), GainEvalCriteria(), depth="linear")


def verify_linear():
    crit = GainEvalCriteria()
    cases = [TrimCase(name=f"M{m}", mach=m, alt=1000.0, fuel=200.0) for m in (0.4, 0.5)]
    return {
        "corners": _corner_dispersions(crit),
        "result": verify(make_demo_aircraft, cases, Shape(profile=example_profile()), crit, depth="linear"),
    }


GOLDENS = {
    "aero_coef": (aero_coef, "digest"),
    "aero_forces": (aero_forces, "digest"),
    "mass_and_propulsion": (mass_and_propulsion, "full"),
    "plant_data": (plant_data, "full"),
    "deriv_euler": (deriv_euler, "digest"),
    "trim_grid": (trim_grid, "full"),
    "trim_special": (trim_special, "full"),
    "linear_models": (linear_models, "full"),
    "envelopes": (envelopes, "full"),
    "gains": (gains, "full"),
    "evaluate_linear": (evaluate_linear, "full"),
    "verify_linear": (verify_linear, "full"),
}
