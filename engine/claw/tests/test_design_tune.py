"""M17 tune 검증 — 설계점 목표 달성, 부호·캡 준수, infeasible 경로, 결정론."""

import math

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    LinearModelSet,
    OperatingPoint,
    PointSet,
    TuneTargets,
    case_name,
    tune_point,
    tune_points,
)
from claw.fcl.demo import demo_design_gains
from claw.plant import make_demo_aircraft
from claw.trim import linearize, trim_level

ACT = dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2)


@pytest.fixture(scope="module")
def setup():
    ac = make_demo_aircraft()
    design = demo_design_gains()
    tr = trim_level(ac, TrimCase("t", mach=0.6, alt=1000.0, fuel=200.0), fingerprint="fp")
    assert tr.converged
    return ac, design, tr, linearize(ac, tr)


def test_design_point_meets_targets(setup):
    """데모 설계점(M0.6)에서 자동 튜닝이 목표(PM≥50°/GM≥8dB, ζ 목표)를 달성한다."""
    _, design, _, lm = setup
    out = tune_point(lm, design, **ACT)
    assert out["status"] == "ok"
    g = out["gains"]
    assert set(g) == {
        "pitch.k_rate", "pitch.kp", "pitch.ki",
        "roll.k_rate", "roll.kp", "roll.ki", "yaw.k_rate",
    }
    for axis in ("pitch", "roll"):
        att = out["achieved"][f"{axis}_att"]
        assert att["pm_deg"] >= 50.0
        assert not (math.isfinite(att["gm_db"]) and att["gm_db"] < 8.0)
    # 피치 댐퍼는 작동기 캡(ωc≤9 rad/s, wn_sp≈9.2)이 먼저 묶는다 — ζ 목표 0.7 대신
    # 캡 내 최선 달성. 합격선(zeta_min 0.3)은 넘어야 한다
    pr = out["achieved"]["pitch_rate"]
    assert pr["capped"] or pr["zeta_sp"] == pytest.approx(0.7, abs=0.05)
    assert pr["zeta_sp"] >= 0.3
    assert out["achieved"]["yaw_rate"]["zeta_dr"] >= 0.45


def test_signs_follow_design(setup):
    """게인 부호는 설계값이 보유 — 크기만 튜닝한다 (diagnose.py 방향 관례)."""
    _, design, _, lm = setup
    g = tune_point(lm, design, **ACT)["gains"]
    for slot in g:
        if g[slot] != 0.0 and design[slot] != 0.0:
            assert math.copysign(1.0, g[slot]) == math.copysign(1.0, design[slot]), slot


def test_damper_closed_loop_stable_with_actuator(setup):
    """튜닝된 댐퍼는 작동기·지연 포함 폐루프가 안정 — 01 §4.2 실증 사고 재발 방지 가드."""
    import control

    from claw.analysis import pi_loop
    from claw.trim import split_axes

    _, design, _, lm = setup
    out = tune_point(lm, design, **ACT)
    lon, lat = split_axes(lm)
    for lm_axis, x_rate, u_in, slot in (
        (lon, "q", "de", "pitch.k_rate"),
        (lat, "p", "da", "roll.k_rate"),
        (lat, "r", "dr", "yaw.k_rate"),
    ):
        loop = pi_loop(lm_axis, x_out=x_rate, u_in=u_in,
                       kp=out["gains"][slot], ki=0.0, sign=1.0, **ACT)
        # 물리 댐퍼 u = +k·rate → 특성식 1 − L (tune._damper_loop_stable과 동일 규약)
        poles = control.feedback(loop, 1, sign=1).poles()
        assert (poles.real < 0).all(), slot


def test_infeasible_with_excess_delay(setup):
    """지연을 인위로 키우면 백오프 바닥에서 infeasible — 던지지 않고 결과로 낸다."""
    _, design, _, lm = setup
    out = tune_point(lm, design, actuator_wn=30.0, actuator_zeta=0.7,
                     delay_s=0.6, pade_order=2)
    assert out["status"] == "infeasible"
    assert any("structural_limit" in n for n in out["notes"])
    assert "pitch.kp" in out["gains"]  # 최선 달성 게인은 그래도 낸다


def test_deterministic(setup):
    _, design, _, lm = setup
    a = tune_point(lm, design, **ACT)
    b = tune_point(lm, design, **ACT)
    assert a["gains"] == b["gains"]


def test_tune_points_skips_untrimmable(setup):
    ac, design, _, _ = setup
    points = PointSet()
    trims = {}
    for m in (0.5, 0.7):
        case = TrimCase(name=case_name(m, 1000.0, 200.0), mach=m, alt=1000.0, fuel=200.0)
        tr = trim_level(ac, case, fingerprint="fp")
        trims[case.name] = tr
        pt = OperatingPoint(case=case, role=ROLE_ANCHOR, origin="coarse")
        pt.trimmable = True
        points.add(pt)
    bad = OperatingPoint(
        case=TrimCase(name=case_name(0.9, 1000.0, 200.0), mach=0.9, alt=1000.0, fuel=200.0),
        role=ROLE_ANCHOR, origin="coarse",
    )
    bad.trimmable = False
    points.add(bad)
    out = tune_points(ac, points, LinearModelSet(), trims, design=design, **ACT)
    assert out["skipped"] == [bad.case.name]
    assert set(out["results"]) == {case_name(0.5, 1000.0, 200.0), case_name(0.7, 1000.0, 200.0)}
    # gain surface 샘플 형식 — 자리별 {이름: 값}
    assert set(out["gains"]["pitch.kp"]) == set(out["results"])


def test_polish_does_not_break_criteria(setup):
    """선택적 마무리(polish=True) — 기본 OFF라 회귀에 안 걸리던 경로.

    대역폭을 밀어 올리되 합격선을 깨면 후퇴하는 계약이라, 켜도 마진이 나빠지면 안 된다.
    """
    _, design, _, lm = setup
    base = tune_point(lm, design, **ACT)
    pol = tune_point(lm, design, polish=True, max_evals=40, **ACT)
    assert pol["status"] == "ok"
    assert pol["evals"] > base["evals"]  # 마무리가 실제로 돌았다
    for axis in ("pitch", "roll"):
        b, p = base["achieved"][f"{axis}_att"], pol["achieved"][f"{axis}_att"]
        assert p["pm_deg"] >= 45.0, f"{axis} 폴리시가 합격선을 깼다"
        assert p["wcp"] >= b["wcp"] * 0.99, f"{axis} 폴리시가 대역폭을 되레 깎았다"


def test_polish_falls_back_when_budget_too_small(setup):
    """예산이 최소 미만이면 최적화를 돌리지 않고 원 게인을 그대로 낸다."""
    _, design, _, lm = setup
    base = tune_point(lm, design, **ACT)
    tiny = tune_point(lm, design, polish=True, max_evals=2, **ACT)
    assert tiny["gains"] == base["gains"]


def test_targets_reject_nonterminating_backoff():
    """백오프 루프의 종료가 이 검증에 걸려 있다 — 서버가 config로 받는 값이다.

    backoff ≥ 1이면 wc가 줄지 않고, floor_frac = 0이면 언더플로 후에도 조건이 참이라
    `_tune_att`가 영원히 돈다. 그 루프는 on_progress를 안 불러 취소도 안 된다.
    """
    with pytest.raises(ValueError, match="backoff"):
        TuneTargets(backoff=1.0)
    with pytest.raises(ValueError, match="backoff"):
        TuneTargets(backoff=0.0)
    with pytest.raises(ValueError, match="wc_att_floor_frac"):
        TuneTargets(wc_att_floor_frac=0.0)
    with pytest.raises(ValueError, match="wc_ratio_att"):
        TuneTargets(wc_ratio_att=0.0)
    with pytest.raises(ValueError, match="감쇠 목표"):
        TuneTargets(zeta_sp=0.0)
    TuneTargets()  # 기본값은 유효해야 한다


def test_cap_reports_no_stable_gain_separately(setup):
    """안정한 댐퍼 게인이 없는 경우와 경계까지 줄인 경우를 구분해 보고한다.

    lo가 0인 채 끝나면 "경계를 찾았다"가 아니라 댐퍼를 끈 것이다 — 한 플래그로
    뭉개면 로그가 "캡 적용"이라 말하면서 아무 댐핑도 없는 형상을 내놓는다.
    """
    import numpy as np

    from claw.common.contracts import LinearModel
    from claw.design.tune import _cap_by_stability
    from claw.trim import split_axes

    _, _design, _, lm = setup
    lon, _lat = split_axes(lm)
    # 개루프가 크게 불안정한 합성 종축 — 어떤 |k|도 안정화하지 못한다
    A = lon.A.copy()
    A[2, 2] += 40.0  # q̇/q 를 크게 양수로
    unstable = LinearModel(A=A, B=lon.B, C=lon.C, D=lon.D, x_names=lon.x_names,
                           u_names=lon.u_names, axis="lon")
    k, reason = _cap_by_stability(unstable, "q", "de", 0.4, ACT)
    assert reason == "no_stable_gain"
    assert k == 0.0
    # 정상 축에서는 캡이 아예 안 걸리거나(None) 경계까지 줄인다('capped')
    k2, reason2 = _cap_by_stability(lon, "q", "de", 0.4, ACT)
    assert reason2 in (None, "capped")
