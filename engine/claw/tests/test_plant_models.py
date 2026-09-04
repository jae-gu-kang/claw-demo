"""M5 mass·prop·actuator 검증 — 연료 보간, 차동추력 모멘트, 2차계 작동기 해석해 대조."""

import math

import numpy as np
import pytest

from claw.blocks.base import UNBOUNDED
from claw.params.registry import REGISTRY
from claw.plant import (
    FuelMass,
    PropEngine,
    SecondOrderActuator,
    SingleEngine,
    TwinEngine,
)

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


# ---- SingleEngine (데모 정본 형상) ----


def test_single_engine_uses_collective_and_makes_no_yaw():
    """중심선 1기 — 좌우 평균이 곧 집합 스로틀이고, 요 모멘트는 낼 수 없다."""
    eng = SingleEngine(max_thrust=8000.0)
    F, M = eng.forces(np.array([0.5, 0.5]))
    assert F == pytest.approx([4000.0, 0.0, 0.0])
    assert M == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)
    # 갈린 명령의 차분은 낼 데가 없다 — 평균만 남고 요 모멘트는 0
    F2, M2 = eng.forces(np.array([0.4, 0.6]))
    assert F2 == pytest.approx(F)
    assert M2[2] == pytest.approx(0.0, abs=1e-12)


def test_single_engine_clip_z_offset_and_custom_map():
    eng = SingleEngine(max_thrust=1000.0, z_offset=0.3)
    F, M = eng.forces(np.array([1.5, -0.2]))  # 좌우 각각 클립 후 평균 = 0.5
    assert F[0] == pytest.approx(500.0)
    assert M[1] == pytest.approx(0.3 * 500.0)  # 엔진선 하방 오프셋 → 기수 상승
    eng2 = SingleEngine(max_thrust=0.0, thrust_map=lambda th: 1000.0 * th**2)
    assert eng2.forces(np.array([0.5, 0.5]))[0][0] == pytest.approx(250.0)
    # 맵을 **평균에 한 번** 먹인다 (좌우 따로 먹여 더하지 않는다). 좌우가 같으면 두
    # 순서가 우연히 같은 답을 내므로 갈린 입력으로 구분한다: map(avg(0.2,0.8)) =
    # 1000·0.5² = 250이고, 0.5·(map(0.2)+map(0.8)) = 0.5·(40+640) = 340이다.
    # 중심선 1기에는 엔진이 하나뿐이라 map(avg)가 물리다
    assert eng2.forces(np.array([0.2, 0.8]))[0][0] == pytest.approx(250.0)


def test_single_engine_matches_twin_when_no_differential():
    """같은 총추력·무차동이면 쌍발과 **완전히 같다** — 형상 전환이 종방향을 안 건드린다는 근거.

    데모 전환(쌍발 4 kN×2 → 단발 8 kN)이 트림·엔벨로프·종방향 시뮬을 그대로 두는
    이유가 이것이다. 달라지는 것은 차동추력 요 모멘트 하나뿐이다."""
    single = SingleEngine(max_thrust=8000.0)
    twin = TwinEngine(max_thrust=4000.0, y_offset=0.5)
    for th in (0.0, 0.25, 0.7, 1.0):
        cmd = np.array([th, th])
        for a, b in zip(single.forces(cmd), twin.forces(cmd)):
            assert a == pytest.approx(b)
    # **주장을 나르는 케이스는 이쪽이다.** 좌우가 같으면 쌍발도 M=0이라 위 루프의
    # 모멘트 비교는 무조건 참이다. 차동 명령을 줘야 "총추력은 같고 요 모멘트만
    # 갈린다"가 실제로 고정된다 — 선형 맵에서 좌우 평균이 곧 집합 스로틀이므로.
    split = np.array([0.3, 0.9])
    f_s, m_s = single.forces(split)
    f_t, m_t = twin.forces(split)
    assert f_s == pytest.approx(f_t), "차동 명령에서도 총추력은 같아야 한다"
    assert m_s == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)
    assert m_t[2] == pytest.approx(0.5 * (4000.0 * 0.3 - 4000.0 * 0.9))  # 쌍발만 요 모멘트


def test_demo_profile_is_single_engine_and_differential_thrust_is_off():
    """정본 형상 짝 — 단발 기체에 차동추력이 켜져 있으면 안 된다.

    켜져 있으면 법칙은 요축을 돕는다고 믿는데 기체는 아무 요 모멘트도 안 내고,
    스로틀 포화 구간에서는 좌우 클립이 비대칭이라 평균이 밀려 **러더가 추력을 깎는다**.
    조용히 어긋날 수 있는 짝이라 여기서 묶는다 (plant/prop.py SingleEngine)."""
    from claw.fcl.demo import DEMO_K_DIFF_THR, make_demo_fcl
    from claw.plant.demo import make_demo_aircraft

    eng = make_demo_aircraft().engine
    assert isinstance(eng, PropEngine), "데모 정본은 단발 중심선 프로펠러 (models/shahed-136)"
    assert DEMO_K_DIFF_THR == 0.0, "단발인데 차동추력이 켜져 있다"
    assert make_demo_fcl().mixer.k_diff_thr == 0.0
    # 스키마 기본값 == 데모가 실제로 쓰는 값 — 다르면 폼이 안 나는 형상을 보여 준다
    defs = {d.name: d.default for d in PropEngine.PARAM_DEFS}
    assert eng.power_max == pytest.approx(defs["power_max"])
    assert eng.eta == pytest.approx(defs["eta"])
    assert eng.static_thrust == pytest.approx(defs["static_thrust"])
    assert eng.r[2] == pytest.approx(defs["z_offset"])


# ---- 추진 레지스트리 (교체 가능 컴포넌트) ----


@pytest.mark.parametrize(
    ("cls", "values", "keys"),
    [
        (PropEngine, {"power_max": 500_000.0},
         {"power_max", "eta", "static_thrust", "z_offset"}),
        (SingleEngine, {"max_thrust": 8000.0}, {"max_thrust", "z_offset"}),
        (TwinEngine, {"max_thrust": 4000.0, "y_offset": 0.5},
         {"max_thrust", "y_offset", "z_offset"}),
    ],
)
def test_propulsion_registered_and_factory_matches_direct(cls, values, keys):
    """레지스트리 create()가 직접 생성과 같은 모델을 낸다.

    같은 값을 두 경로로 만들었을 때 결과가 갈리면 폼이 보여 주는 수치와 실제로 나는
    수치가 달라진다. 여기가 그 둘을 묶는 자리다."""
    assert cls.NAME in REGISTRY.names("propulsion")
    schema = REGISTRY.schema("propulsion", cls.NAME)
    assert schema["title"] == f"propulsion/{cls.NAME}"
    assert set(schema["properties"]) == keys
    unit_key = "power_max" if "power_max" in schema["properties"] else "max_thrust"
    assert schema["properties"][unit_key]["description"].endswith(  # 단위 메타
        "[W]" if unit_key == "power_max" else "[N]")
    # 등록되는 추진은 능력을 **선언**해야 한다 — 철자를 틀리면(differential_thust)
    # getattr 기본값이 True라 조용히 "낼 수 있음"이 된다 (sim 조립 가드가 안 걸린다)
    assert isinstance(cls.differential_thrust, bool), "차동추력 능력 미선언 (오타?)"
    thr = np.array([1.0, 0.5])
    made = REGISTRY.create("propulsion", cls.NAME, values)
    for a, b in zip(made.forces(thr), cls(**values).forces(thr)):
        assert a == pytest.approx(b)


@pytest.mark.parametrize(
    ("cls", "excluded"),
    [(PropEngine, set()), (SingleEngine, {"thrust_map"}),
     (TwinEngine, {"x_offset", "thrust_map"})],
)
def test_propulsion_param_defaults_match_ctor(cls, excluded):
    """ParamDef 기본값 == 생성자 기본값 (test_fcl_law의 같은 규약).

    추진은 스키마가 생성자의 **부분집합**이라 등식이 아니라 포함으로 본다. 빠진 것은
    의도된 제외이고 그 목록을 여기서 핀한다 — 진짜 파라미터가 조용히 빠지는 것을 막는다:
    TwinEngine.x_offset은 F∥x라 모멘트에 기여하지 않는 죽은 인자이고, thrust_map은
    콜러블이라 JSON 스키마로 나갈 수 없다 (plant/prop.py 참조)."""
    import inspect

    sig = inspect.signature(cls.__init__)
    ctor = {k: p.default for k, p in sig.parameters.items() if k != "self"}
    defs = {d.name: d.default for d in cls.PARAM_DEFS}
    assert set(ctor) - set(defs) == excluded
    assert all(defs[k] == ctor[k] for k in defs), "ParamDef·생성자 기본값 불일치"
    assert all(type(defs[k]) is type(ctor[k]) for k in defs), "기본값 타입 불일치"


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


def test_single_engine_rejects_differential_thrust_law_at_assembly():
    """단발 기체 + k_diff_thr≠0은 **조립 시점에 거부**한다 (조용한 미장착 금지).

    모듈 상수 DEMO_K_DIFF_THR를 핀하는 것만으로는 부족하다 — 웹·파이프라인이
    mixer kwargs를 직접 주입하는 경로가 있어서 사용자가 만들 수 있는 조합이다.
    기체와 법칙이 만나는 곳은 Simulator 하나뿐이라 거기서 막는다."""
    from claw.fcl import make_demo_fcl
    from claw.fcl.mixer import Mixer
    from claw.guidance import Guidance, ModeSpec
    from claw.plant import make_demo_aircraft
    from claw.sim import Simulator

    modes = [ModeSpec(name="m", speed=80.0, alt=100.0, exit_when=("time_ge", 1e9))]
    kw = dict(aircraft=make_demo_aircraft(), guidance=Guidance(modes),
              dt_plant=0.01, control_hz=100.0)
    with pytest.raises(ValueError, match="차동추력"):
        Simulator(fcl=make_demo_fcl(mixer=Mixer(k_diff_thr=0.1)), **kw)
    Simulator(fcl=make_demo_fcl(mixer=Mixer(k_diff_thr=0.0)), **kw)  # 0이면 통과
    # 쌍발을 물리면 같은 법칙이 허용된다 — 능력 플래그가 형상을 따라간다
    ac = make_demo_aircraft()
    ac.engine = TwinEngine(max_thrust=4000.0, y_offset=0.5)
    Simulator(aircraft=ac, fcl=make_demo_fcl(mixer=Mixer(k_diff_thr=0.1)),
              guidance=Guidance(modes), dt_plant=0.01, control_hz=100.0)


# ---- PropEngine (속도·밀도 의존 추력) ----


def test_prop_thrust_falls_as_one_over_speed_above_crossover():
    """프로펠러의 본질 — 고속에서 추력이 빠진다. 상수 모델과 갈리는 지점이다."""
    eng = PropEngine(power_max=500_000.0, eta=0.8, static_thrust=6000.0)
    assert eng.crossover_speed == pytest.approx(0.8 * 500_000.0 / 6000.0)  # 66.7 m/s
    # 교차속도 아래는 정지추력이 상한 (V→0에서 P/V가 발산하는 것을 막는다)
    for V in (0.0, 30.0, eng.crossover_speed):
        assert eng.available_thrust(V) == pytest.approx(6000.0)
    # 위쪽은 1/V — 두 배 빠르면 절반이다
    t100 = eng.available_thrust(100.0)
    assert t100 == pytest.approx(0.8 * 500_000.0 / 100.0)
    assert eng.available_thrust(200.0) == pytest.approx(t100 / 2.0)


def test_prop_thrust_lapses_with_density_and_scales_with_throttle():
    from claw.env import isa_atmosphere

    eng = PropEngine(power_max=500_000.0, eta=0.8, static_thrust=6000.0)
    rho3k = isa_atmosphere(3000.0).rho
    sigma = rho3k / 1.225
    assert eng.available_thrust(100.0, rho3k) == pytest.approx(
        eng.available_thrust(100.0) * sigma)
    # 스로틀은 선형 배율 — 좌우 평균이 집합 스로틀 (단발 계약)
    F, M = eng.forces(np.array([0.5, 0.5]), 100.0, 1.225)
    assert F[0] == pytest.approx(0.5 * eng.available_thrust(100.0))
    assert M == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)  # 중심선 — 요 모멘트 없음
    assert eng.forces(np.array([0.2, 0.8]), 100.0)[0] == pytest.approx(F)  # 평균만 쓴다


def test_prop_engine_z_offset_and_validation():
    eng = PropEngine(power_max=100_000.0, eta=0.5, static_thrust=1000.0, z_offset=0.3)
    F, M = eng.forces(np.array([1.0, 1.0]), 10.0)  # 교차속도 아래 → 정지추력
    assert F[0] == pytest.approx(1000.0)
    assert M[1] == pytest.approx(0.3 * 1000.0)  # 하방 오프셋 → 기수 상승
    with pytest.raises(ValueError, match="eta"):
        PropEngine(eta=0.0)
    with pytest.raises(ValueError, match="eta"):
        PropEngine(eta=1.5)


def test_constant_thrust_models_ignore_speed_and_density():
    """SingleEngine·TwinEngine은 계약 폭만 맞춘다 — 받고 쓰지 않는다.

    이 무시가 **의도**임을 고정한다. 나중에 누가 이 클래스들에 속도 의존을 넣으면
    여기가 울고, 그때 데모 정본(PropEngine)과의 역할 분담을 다시 보게 된다."""
    for eng in (SingleEngine(max_thrust=8000.0), TwinEngine(max_thrust=4000.0, y_offset=0.5)):
        base = eng.forces(np.array([0.5, 0.5]))[0]
        for V, rho in ((0.0, 1.225), (300.0, 0.4), (100.0, 1.0)):
            assert eng.forces(np.array([0.5, 0.5]), V, rho)[0] == pytest.approx(base)


def test_aircraft_hands_the_same_airspeed_and_density_to_propulsion_as_to_aero():
    """`Aircraft.fm`이 추진에 V·ρ를 **실제로** 넘긴다 — 안 넘기면 조용히 정지추력이 난다.

    PropEngine.forces의 기본값이 V=0이라 인자를 빠뜨려도 예외가 아니라 **최대추력**이
    나온다(순항에서 2배 오차). 지금은 트림 수치가 간접적으로 잡지만, 그건 우연이라
    여기서 직접 못박는다. 밀도도 같이 본다 — 공력과 추진이 다른 대기를 보면 안 된다.
    """
    from claw.common.attitude import euler_to_quat
    from claw.env import isa_atmosphere
    from claw.plant.demo import make_demo_aircraft as demo

    seen = {}

    class Spy(PropEngine):
        def forces(self, throttle, V=0.0, rho=None):
            seen["V"], seen["rho"] = float(V), float(rho)
            return super().forces(throttle, V, rho)

    ac = demo()
    ac.engine = Spy(power_max=500_000.0)
    vel_b = np.array([120.0, 0.0, 6.0])
    h = 2000.0
    ac.fm(vel_b, np.zeros(3), euler_to_quat(0.0, 0.0, 0.0), h,
          {"de": 0.0, "da": 0.0, "dr": 0.0, "throttle": (0.5, 0.5)}, 200.0)
    assert seen["V"] == pytest.approx(float(np.linalg.norm(vel_b)))
    assert seen["rho"] == pytest.approx(isa_atmosphere(h).rho)
