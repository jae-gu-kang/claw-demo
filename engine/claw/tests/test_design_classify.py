"""M17 classify 검증 — 4-verdict 분기·evidence 수치·supersede (합성 시나리오)."""

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    ROLE_VALIDATION,
    LinearModelSet,
    MarginCriteria,
    OperatingPoint,
    PointSet,
    case_name,
    tune_point,
)
from claw.design.classify import classify_failures, classify_margin_deficit
from claw.fcl.demo import demo_design_gains
from claw.plant import make_demo_aircraft
from claw.tables import Table
from claw.trim import trim_level

ACT = dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2)


def _setup(machs, v_mach, alt=1000.0, fuel=200.0):
    ac = make_demo_aircraft()
    points, trims = PointSet(), {}
    for m in machs:
        case = TrimCase(name=case_name(m, alt, fuel), mach=m, alt=alt, fuel=fuel)
        tr = trim_level(ac, case, fingerprint="fp")
        assert tr.converged
        trims[case.name] = tr
        role = ROLE_VALIDATION if v_mach is not None and m == v_mach else ROLE_ANCHOR
        pt = OperatingPoint(case=case, role=role, origin="test")
        pt.trimmable = True
        points.add(pt)
    return ac, points, LinearModelSet(), trims


def _fail_cases(v, lo, hi, loop="pitch_att"):
    """합성 마진맵 케이스 — v만 fail, 이웃은 ok."""
    entry = {"kind": "margin", "pm_deg": 42.0, "gm_db": 7.0, "status": "fail"}
    ok = {"kind": "margin", "pm_deg": 60.0, "gm_db": 10.0, "status": "ok"}
    return {
        v: {"role": "validation", "loops": {loop: entry}},
        lo: {"role": "anchor", "loops": {loop: dict(ok)}},
        hi: {"role": "anchor", "loops": {loop: dict(ok)}},
    }


def test_structural_limit_with_excess_delay():
    """과대 지연 — 자유 게인으로도 미달 → escalate (보고 전용) + 병목 수치."""
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, {}, design, _fail_cases(v, lo, hi),
        criteria=MarginCriteria(),
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.6, pade_order=2,
    )
    assert out["verdict"] == "structural_limit"
    assert out["action"]["type"] == "escalate"
    assert "bottleneck" in out["evidence"]
    assert "delay_phase_deg_at_wc" in out["evidence"]["bottleneck"]


def test_plant_variation_promotes_to_anchor():
    """플랜트 급변(tol_plant 낮춤) — validation → anchor 승격, valley 동시 성립 시 병기."""
    ac, points, lms, trims = _setup((0.25, 0.35, 0.45), v_mach=0.35)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.35, 0.25, 0.45))
    design = demo_design_gains()
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, {}, design, _fail_cases(v, lo, hi),
        criteria=MarginCriteria(), tol_plant=0.05, **ACT,
    )
    assert out["verdict"] == "plant_variation"
    assert out["action"]["type"] == "promote" and out["action"]["to"] == ROLE_ANCHOR
    assert out["evidence"]["plant"]["d_total"] > 0.05


def test_gain_interp_valley_promotes_to_breakpoint():
    """이웃 통과 + 보간 게인 괴리 큼 (plant 분기는 tol 완화로 배제) → breakpoint 승격."""
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    opt = tune_point(lms.get(ac, trims[v]), design, **ACT)["gains"]
    # 보간 게인을 최적의 3배로 — 괴리 200% > tol_gain 10%
    tables = {
        "pitch.kp": Table({"mach": (0.55, 0.65)},
                          (opt["pitch.kp"] * 3.0,) * 2, extrapolate="clip"),
    }
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, tables, design,
        _fail_cases(v, lo, hi), criteria=MarginCriteria(), tol_plant=99.0, **ACT,
    )
    assert out["verdict"] == "gain_interp_valley"
    act = out["action"]
    assert act["type"] == "promote" and act["to"] == "breakpoint"
    assert act["gains"]["pitch.kp"] == pytest.approx(opt["pitch.kp"])
    assert out["evidence"]["interp_gap"]["max"] > 0.10


def test_simple_deficit_adds_validation():
    """괴리 작고 플랜트 완만 — 검증점 추가 처방."""
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    opt = tune_point(lms.get(ac, trims[v]), design, **ACT)["gains"]
    tables = {
        "pitch.kp": Table({"mach": (0.55, 0.65)}, (opt["pitch.kp"],) * 2,
                          extrapolate="clip"),
        "pitch.ki": Table({"mach": (0.55, 0.65)}, (opt["pitch.ki"],) * 2,
                          extrapolate="clip"),
    }
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, tables, design,
        _fail_cases(v, lo, hi), criteria=MarginCriteria(), tol_plant=99.0, **ACT,
    )
    assert out["verdict"] == "simple_deficit"
    assert out["action"]["type"] == "add_validation"


def test_classify_failures_supersede():
    """같은 점의 다중 실패 — 승격 처방 중 상위 하나만 유효, 나머지는 supersede."""
    ac, points, lms, trims = _setup((0.25, 0.35, 0.45), v_mach=0.35)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.35, 0.25, 0.45))
    cases = _fail_cases(v, lo, hi)
    cases[v]["loops"]["pitch_rate"] = {"kind": "damping", "zeta": 0.2, "status": "fail"}
    margin_out = {
        "cases": cases,
        "failures": [
            {"case": v, "loop": "pitch_att", "severity": 42.0},
            {"case": v, "loop": "pitch_rate", "severity": 18.0},
        ],
    }
    actions = classify_failures(
        ac, points, lms, trims, {}, demo_design_gains(), margin_out,
        criteria=MarginCriteria(), tol_plant=0.05, **ACT,
    )
    assert len(actions) == 2
    promotes = [a for a in actions if a["action"]["type"] == "promote"]
    assert promotes, "승격 처방이 없다"
    superseded = [a for a in actions if "superseded_by" in a]
    assert len(promotes) - len(superseded) <= 1  # 같은 점 유효 승격은 1개
    assert all(a["id"].count(":") == 2 for a in actions)


def test_valley_on_anchor_prescribes_refit_not_promotion():
    """이미 breakpoint 이상인 점의 보간 괴리 — 승격은 래칫 위반이라 세션을 죽인다.

    anchor는 breakpoint 역할을 겸하므로(서열) 그 점의 괴리는 격자가 성긴 게 아니라
    적합이 못 맞춘 것이다 → 재적합 처방이어야 한다.
    """
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=None)  # 전부 anchor
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    opt = tune_point(lms.get(ac, trims[v]), design, **ACT)["gains"]
    tables = {
        "pitch.kp": Table({"mach": (0.55, 0.65)},
                          (opt["pitch.kp"] * 3.0,) * 2, extrapolate="clip"),
    }
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, tables, design,
        _fail_cases(v, lo, hi), criteria=MarginCriteria(), tol_plant=99.0, **ACT,
    )
    assert out["verdict"] == "gain_interp_valley"
    assert out["action"]["type"] == "refit_at", "anchor에 승격 처방을 내면 래칫이 터진다"
    assert out["action"]["gains"]["pitch.kp"] == pytest.approx(opt["pitch.kp"])


def test_sign_flip_gets_its_own_verdict_not_promotion():
    """부호 뒤집힘은 격자 문제가 아니다 — 승격을 처방하면 재개해도 그대로다.

    실제로 겪었다: plant_variation으로 분류돼 앵커 승격을 반영했는데 다항이 다시
    0을 가로질러 실패가 유지됐다.
    """
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    cases = _fail_cases(v, lo, hi)
    # 검증이 부호 뒤집힘을 표시한 상태 (schedmap._apply_sign_check가 하는 일)
    cases[v]["loops"]["pitch_att"].update({
        "sign_flip": ["pitch.ki"],
        "gains": {"kp": -2.0, "ki": +0.5},  # ki가 설계(-0.5)와 반대
    })
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, {}, design, cases,
        criteria=MarginCriteria(), tol_plant=0.001, **ACT,  # plant도 걸리게 낮춘다
    )
    assert out["verdict"] == "gain_sign_flip", "부호 뒤집힘이 다른 원인으로 분류됐다"
    assert out["action"]["type"] == "refit_at"
    assert out["evidence"]["sign_flip"]["slots"] == ["pitch.ki"]
