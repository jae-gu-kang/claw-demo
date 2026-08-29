"""M16 schedmap 검증 — 실효 게인 보간, 상수 게인 마진맵과의 차이, actuator/delay 조성 일치."""

import numpy as np
import pytest

from claw.analysis import loop_margins, pi_loop
from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    ROLE_BREAKPOINT,
    LinearModelSet,
    MarginCriteria,
    OperatingPoint,
    PointSet,
    case_name,
    midpoint_validation_points,
    scheduled_gains,
    scheduled_margin_map,
    scheduled_margin_point,
)
from claw.fcl.demo import demo_design_gains, make_demo_gain_tables
from claw.plant import make_demo_aircraft
from claw.trim import linearize, trim_level


@pytest.fixture(scope="module")
def setup():
    ac = make_demo_aircraft()
    tables = make_demo_gain_tables()
    design = demo_design_gains()
    return ac, tables, design


def _case(mach, alt=1000.0, fuel=200.0):
    return TrimCase(name=case_name(mach, alt, fuel), mach=mach, alt=alt, fuel=fuel)


def test_effective_gain_on_breakpoint_equals_table(setup):
    """breakpoint 좌표에서 보간 게인 == 테이블 값, 스케줄 안 덮는 자리는 설계 상수."""
    _, tables, design = setup
    case = _case(0.4)  # 데모 테이블 breakpoint (0.15~0.95 step 0.05)
    eff = scheduled_gains(tables, design, case)
    t = tables["pitch.kp"]
    i = int(np.argwhere(np.isclose(t.axes[0], 0.4))[0][0])
    assert eff["pitch.kp"] == pytest.approx(float(t.data[i]))
    assert eff["yaw.k_rate"] == pytest.approx(design["yaw.k_rate"])  # 스케줄 밖 자리


def test_midpoint_gain_is_interpolated(setup):
    """breakpoint 사이 중점은 선형 보간값 — 상수도 어느 한쪽 breakpoint 값도 아니다."""
    _, tables, design = setup
    eff = scheduled_gains(tables, design, _case(0.425))
    t = tables["pitch.kp"]
    lo = float(t.interp(mach=0.4))
    hi = float(t.interp(mach=0.45))
    assert eff["pitch.kp"] == pytest.approx((lo + hi) / 2.0)
    assert eff["pitch.kp"] != pytest.approx(design["pitch.kp"])


def test_margin_point_matches_direct_pi_loop(setup):
    """scheduled_margin_point == 실효 게인으로 직접 조성한 pi_loop (actuator+delay 포함)."""
    ac, tables, design = setup
    case = _case(0.6)
    tr = trim_level(ac, case)
    assert tr.converged
    lm = linearize(ac, tr)
    out = scheduled_margin_point(
        lm, tables, design, case,
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    )
    from claw.trim import split_axes

    lon, _ = split_axes(lm)
    eff = scheduled_gains(tables, design, case)
    ref = loop_margins(pi_loop(
        lon, x_out="q", u_in="de", kp=eff["pitch.k_rate"], ki=0.0, sign=-1.0,
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    ))
    assert out["pitch_rate"]["pm_deg"] == pytest.approx(ref["pm_deg"])
    assert out["pitch_rate"]["gm_db"] == pytest.approx(ref["gm_db"], nan_ok=True)


def test_scheduled_differs_from_constant_gain_map(setup):
    """저마하에서 스케줄 실효 게인(동압 스케일 ×배)의 마진은 설계 상수 마진과 유의미하게 다르다.

    기존 마진맵(상수 게인) 경로가 §3.4 검증 요구를 대신할 수 없다는 실증.
    """
    ac, tables, design = setup
    case = _case(0.3)  # f = (0.6/0.3)² = 4 (상한) — 실효 게인이 설계값의 4배
    tr = trim_level(ac, case)
    assert tr.converged
    lm = linearize(ac, tr)
    sched = scheduled_margin_point(lm, tables, design, case)["pitch_rate"]
    from claw.trim import split_axes

    lon, _ = split_axes(lm)
    const = loop_margins(pi_loop(
        lon, x_out="q", u_in="de", kp=design["pitch.k_rate"], ki=0.0, sign=-1.0
    ))
    assert sched["gains"]["kp"] == pytest.approx(design["pitch.k_rate"] * 4.0)
    assert abs(sched["gm_db"] - const["gm_db"]) > 1.0 or abs(
        sched["pm_deg"] - const["pm_deg"]
    ) > 5.0


def test_midpoint_validation_points():
    ps = PointSet([
        OperatingPoint(case=_case(0.4), role=ROLE_ANCHOR, origin="coarse"),
        OperatingPoint(case=_case(0.6), role=ROLE_BREAKPOINT, origin="coarse"),
    ])
    mids = midpoint_validation_points(ps)
    assert len(mids) == 1
    assert mids[0].case.mach == pytest.approx(0.5)
    assert mids[0].role == "validation"
    ps.add(mids[0])
    # 검증점 밀도 기본값 = breakpoint 구간당 중점 1개 — 검증점은 새 구간을 만들지
    # 않으므로(인접 정의가 breakpoint 이상) 재생성해도 추가분이 없다 (멱등)
    assert midpoint_validation_points(ps) == []
    # 검증점을 breakpoint로 승격하면 구간이 쪼개져 새 중점 2개가 나온다
    ps.promote(mids[0].case.name, ROLE_BREAKPOINT, reason="valley")
    more = sorted(p.case.mach for p in midpoint_validation_points(ps))
    assert more == pytest.approx([0.45, 0.55])


def test_margin_map_end_to_end_and_cancel(setup):
    ac, tables, design = setup
    ps = PointSet([
        OperatingPoint(case=_case(m), role=ROLE_ANCHOR, origin="coarse")
        for m in (0.4, 0.6)
    ])
    for mid in midpoint_validation_points(ps):
        ps.add(mid)
    lms = LinearModelSet()
    crit = MarginCriteria()
    trims = {}
    out = scheduled_margin_map(
        ac, ps, lms, tables, design, criteria=crit, trims=trims,
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035,
    )
    assert out["aborted"] is None
    assert set(out["cases"]) == set(ps.names())
    assert set(trims) == set(ps.names())  # 호출자 dict가 제자리 갱신된다
    v = out["cases"]["M0.5_h1000_f200"]
    assert v["role"] == "validation"
    assert "pitch_rate" in v["loops"] and "status" in v["loops"]["pitch_rate"]
    assert out["criteria_fingerprint"] == crit.fingerprint()
    # 협조적 취소 — 첫 마진 계산 후 중단해도 완료분은 남는다
    cancelled = scheduled_margin_map(
        ac, ps, lms, tables, design, criteria=crit, trims=dict(trims),
        on_progress=lambda done, total, msg: msg.startswith("margin"),
    )
    assert cancelled["aborted"] == "cancelled"
    assert len(cancelled["cases"]) == 1
