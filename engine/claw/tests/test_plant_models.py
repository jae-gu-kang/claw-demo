"""M5 mass·prop·actuator 검증 — 연료 보간, 차동추력 모멘트, 2차계 작동기 해석해 대조."""

import math

import numpy as np
import pytest

from claw.blocks.base import UNBOUNDED
from claw.params.registry import REGISTRY
from claw.plant import FuelMass, SecondOrderActuator, TwinEngine

DT = 1e-3


# ---- FuelMass ----


def make_fuel_mass():
    return FuelMass(
        m_empty=800.0,
        fuel_max=400.0,
        J_empty=np.diag([100.0, 200.0, 280.0]),
        J_full=np.diag([120.0, 260.0, 360.0]),
        cg_empty=np.array([0.10, 0.0, 0.0]),
        cg_full=np.array([-0.10, 0.0, 0.0]),
    )


def test_fuel_mass_endpoints():
    fm = make_fuel_mass()
    m, cg, J = fm.at(0.0)
    assert m == pytest.approx(800.0)
    assert cg == pytest.approx([0.10, 0.0, 0.0])
    assert np.allclose(J, np.diag([100.0, 200.0, 280.0]))
    m, cg, J = fm.at(400.0)
    assert m == pytest.approx(1200.0)
    assert cg == pytest.approx([-0.10, 0.0, 0.0])
    assert np.allclose(J, np.diag([120.0, 260.0, 360.0]))


def test_fuel_mass_linear_midpoint_and_clip():
    fm = make_fuel_mass()
    m, cg, J = fm.at(200.0)
    assert m == pytest.approx(1000.0)
    assert cg[0] == pytest.approx(0.0)
    assert J[1, 1] == pytest.approx(230.0)
    assert fm.at(-50.0)[0] == pytest.approx(800.0)  # 음수 연료 클립
    assert fm.at(999.0)[0] == pytest.approx(1200.0)  # 초과 클립


def test_fuel_mass_validation():
    with pytest.raises(ValueError):
        FuelMass(m_empty=0.0, fuel_max=1.0, J_empty=np.eye(3), J_full=np.eye(3))
    with pytest.raises(ValueError):
        FuelMass(m_empty=1.0, fuel_max=-1.0, J_empty=np.eye(3), J_full=np.eye(3))


# ---- TwinEngine ----


def test_twin_engine_symmetric():
    eng = TwinEngine(max_thrust=5000.0, y_offset=1.2)
    F, M = eng.forces(np.array([0.6, 0.6]))
    assert F == pytest.approx([6000.0, 0.0, 0.0])
    assert M == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)


def test_twin_engine_differential_yaw():
    """좌측 추력 우세 → 기수 우측(+N) 요 모멘트 (01 §2.1 차동추력 요축 보조)."""
    y_off = 1.5
    eng = TwinEngine(max_thrust=4000.0, y_offset=y_off)
    F, M = eng.forces(np.array([1.0, 0.5]))
    assert F[0] == pytest.approx(6000.0)
    assert M[2] == pytest.approx(y_off * (4000.0 - 2000.0))  # N = y_off·(T_L − T_R)


def test_twin_engine_z_offset_pitch():
    eng = TwinEngine(max_thrust=1000.0, y_offset=1.0, z_offset=0.3)
    _, M = eng.forces(np.array([1.0, 1.0]))
    assert M[1] == pytest.approx(0.3 * 2000.0)  # 엔진선 하방 오프셋 → 기수 상승 모멘트


def test_twin_engine_throttle_clip_and_custom_map():
    eng = TwinEngine(max_thrust=1000.0, y_offset=1.0)
    F, _ = eng.forces(np.array([1.5, -0.2]))  # 0~1 클립 (SurfaceCommand 규약)
    assert F[0] == pytest.approx(1000.0)
    eng2 = TwinEngine(max_thrust=0.0, y_offset=1.0, thrust_map=lambda th: 1000.0 * th**2)
    F2, _ = eng2.forces(np.array([0.5, 0.5]))
    assert F2[0] == pytest.approx(500.0)


# ---- SecondOrderActuator ----


def test_actuator_step_response_analytic():
    """제한 미작동 영역에서 2차계 스텝응답 해석해 대조 (ZOH 상수 입력 → RK4)."""
    wn, zeta = 30.0, 0.7
    act = SecondOrderActuator(wn=wn, zeta=zeta, pos_lo=-10.0, pos_hi=10.0, rate_max=1e6).init(DT)
    wd = wn * math.sqrt(1.0 - zeta**2)
    for k in range(1, 501):
        y = act.step(1.0)
        t = k * DT
        ref = 1.0 - math.exp(-zeta * wn * t) * (
            math.cos(wd * t) + zeta / math.sqrt(1.0 - zeta**2) * math.sin(wd * t)
        )
        assert y == pytest.approx(ref, abs=1e-5)
    assert y == pytest.approx(1.0, abs=1e-4)  # DC 이득 1


def test_actuator_rate_limit():
    act = SecondOrderActuator(wn=200.0, zeta=0.7, pos_lo=-10.0, pos_hi=10.0, rate_max=2.0).init(DT)
    prev, max_step = 0.0, 0.0
    for _ in range(3000):  # 이동 5.0/rate 2.0 = 2.5초 + 정착
        y = act.step(5.0)
        max_step = max(max_step, abs(y - prev))
        prev = y
    assert max_step <= 2.0 * DT + 1e-12  # 스텝당 변화량 상한 = rate_max·dt
    assert y == pytest.approx(5.0, abs=1e-3)


def test_actuator_default_rate_is_the_documented_assumption():
    """rate_max 기본값 = 데모 가정값 10 rad/s [기본값 01 §7] — 무제한 기본값은
    미지정 시 조용히 낙관적인 해석을 만든다(01 §4.2). 위치 한계·초기값은 믹서·
    트림이 결정하므로 그쪽만 무제한 기본값 유지."""
    act = SecondOrderActuator()
    assert act.rate_max == 10.0
    assert act.pos_lo == -UNBOUNDED and act.pos_hi == UNBOUNDED

    # 기본 구성만으로도 rate 한계가 실제 작동해야 한다 (기본값이 장식이 아님)
    a = SecondOrderActuator(wn=200.0).init(DT)
    prev, max_step = 0.0, 0.0
    for _ in range(300):
        y = a.step(5.0)
        max_step = max(max_step, abs(y - prev))
        prev = y
    assert max_step <= 10.0 * DT + 1e-12


def test_actuator_position_limit_and_recovery():
    act = SecondOrderActuator(wn=50.0, zeta=0.8, pos_lo=-0.3, pos_hi=0.3, rate_max=1e6).init(DT)
    for _ in range(500):
        y = act.step(1.0)  # 한계 밖 명령
    assert y == pytest.approx(0.3, abs=1e-12)
    for _ in range(500):
        y = act.step(0.0)  # 복귀 명령 — 한계에서 즉시 이탈해야 함
    assert y == pytest.approx(0.0, abs=1e-3)


def test_actuator_warm_start_and_validation():
    act = SecondOrderActuator(wn=30.0, zeta=0.7).init(DT)
    act.reset((0.2, 0.0))
    assert act.step(0.2) == pytest.approx(0.2, abs=1e-6)  # 평형 웜스타트 → 정지 유지
    limited = SecondOrderActuator(wn=30.0, zeta=0.7, pos_lo=-0.3, pos_hi=0.3, rate_max=2.0).init(DT)
    limited.reset((1.0, 100.0))  # 한계 밖 웜스타트 → 한계로 클램프
    assert limited.step(1.0) <= 0.3 + 1e-12
    with pytest.raises(ValueError):
        SecondOrderActuator(wn=0.0)
    with pytest.raises(ValueError):
        SecondOrderActuator(wn=30.0, zeta=0.0)
    with pytest.raises(ValueError):
        SecondOrderActuator(wn=30.0, pos_lo=1.0, pos_hi=-1.0)


def test_actuator_registered():
    assert "SecondOrderActuator" in REGISTRY.names("actuator")
