"""M5 ground 검증 — 스키드 접촉(정적 평형·감쇠·마찰·r×F)과 발사 레일 구속.

지면은 이 엔진에 새로 들어온 것이라, "기체를 실제로 받치는가"를 먼저 못박는다.
그 전까지 h<0은 플래그일 뿐이었고 기체는 지면을 통과했다.
"""

import math

import numpy as np
import pytest

from claw.common.attitude import euler_to_quat
from claw.common.constants import G0
from claw.plant import (
    LaunchRail,
    RigidBody,
    SkidGear,
    make_demo_aircraft,
    make_demo_launch_rail,
    make_demo_skid_gear,
    make_demo_structural_limits,
    pack,
    unpack,
)

LEVEL = euler_to_quat(0.0, 0.0, 0.0)
Z3 = np.zeros(3)
FUEL = 300.0
CTRL = {"de": 0.0, "da": 0.0, "dr": 0.0, "throttle": (0.0, 0.0)}


def gear_and_weight():
    gear = make_demo_skid_gear()
    ac = make_demo_aircraft(ground=gear)
    m, _cg, _J = ac.fuel_mass.at(FUEL)
    return gear, ac, m * G0


# ---- 접촉 기본 ----


def test_no_contact_gives_no_force():
    """접촉점이 지면 위에 있으면 힘·모멘트가 정확히 0 — 자유비행에 영향 없음."""
    gear, _ac, _w = gear_and_weight()
    pos = np.array([0.0, 0.0, -100.0])  # h = 100 m
    f, m = gear.forces(pos, np.array([80.0, 0.0, 0.0]), LEVEL, Z3)
    assert np.allclose(f, 0.0)
    assert np.allclose(m, 0.0)
    st = gear.contact_state(pos, np.array([80.0, 0.0, 0.0]), LEVEL, Z3)
    assert st["wow"] is False
    assert st["n_total"] == 0.0


def test_rest_penetration_carries_exactly_the_weight():
    """정지 침투 δ = W/(n·k)에서 수직반력 합이 무게와 같다 — 강성 규약의 정의."""
    gear, _ac, weight = gear_and_weight()
    delta = gear.rest_penetration(weight)
    assert delta == pytest.approx(weight / (4 * gear.k))
    # 접촉점은 CG 아래 0.55 m → CG 고도가 (0.55 − δ)일 때 침투가 δ
    pos = np.array([0.0, 0.0, -(0.55 - delta)])
    f, _m = gear.forces(pos, Z3, LEVEL, Z3)
    assert f[2] == pytest.approx(-weight, rel=1e-9)  # NED 상방 = z 음수
    st = gear.contact_state(pos, Z3, LEVEL, Z3)
    assert st["wow"] is True
    assert st["n_total"] == pytest.approx(weight, rel=1e-9)
    assert st["max_pen"] == pytest.approx(delta)


def test_contact_is_compression_only():
    """되튈 때 감쇠항이 기체를 끌어내리지 않는다 — 스키드는 지면을 당기지 못한다."""
    gear, _ac, weight = gear_and_weight()
    delta = gear.rest_penetration(weight)
    pos = np.array([0.0, 0.0, -(0.55 - delta)])
    # 아주 빠르게 튀어오르는 중: c·δ̇ 가 k·δ 를 압도 → 총합이 음수가 될 자리
    up_fast = np.array([0.0, 0.0, -50.0])  # 동체 z 음수 = 상방
    f, _m = gear.forces(pos, up_fast, LEVEL, Z3)
    assert f[2] >= 0.0 or f[2] == pytest.approx(0.0)
    assert np.allclose(f, 0.0), "인장(끌어내림)이 생기면 안 됨"


# ---- 마찰 ----


def test_friction_opposes_motion_and_scales_with_normal():
    gear, _ac, weight = gear_and_weight()
    delta = gear.rest_penetration(weight)
    pos = np.array([0.0, 0.0, -(0.55 - delta)])
    v = np.array([60.0, 0.0, 0.0])
    f, _m = gear.forces(pos, v, LEVEL, Z3)
    assert f[0] < 0.0, "전진 중 마찰은 감속 방향"
    # v ≫ v_eps 이므로 정칙화 항이 거의 사라져 μN 에 수렴
    assert f[0] == pytest.approx(-gear.mu * weight * 60.0 / (60.0 + gear.v_eps), rel=1e-9)
    assert f[2] == pytest.approx(-weight, rel=1e-9)


def test_friction_regularization_kills_zero_speed_chatter():
    """v=0에서 마찰이 정확히 0 — sign(v)였다면 부호가 부단계마다 뒤집힌다."""
    gear, _ac, weight = gear_and_weight()
    delta = gear.rest_penetration(weight)
    pos = np.array([0.0, 0.0, -(0.55 - delta)])
    f, _m = gear.forces(pos, Z3, LEVEL, Z3)
    assert f[0] == pytest.approx(0.0)
    assert f[1] == pytest.approx(0.0)


# ---- 모멘트 r×F ----


def test_front_contact_only_gives_nose_up_moment():
    """앞 접촉점만 닿으면 기수가 들린다 — M += r×F 가 실제로 걸린다는 증거."""
    gear, _ac, _w = gear_and_weight()
    # 기수를 숙여(θ<0) 앞점만 닿게 한다
    q = euler_to_quat(0.0, math.radians(-8.0), 0.0)
    pos = np.array([0.0, 0.0, -0.50])
    f, m = gear.forces(pos, Z3, q, Z3)
    assert f[2] < 0.0, "떠받치는 힘이 있어야 함"
    assert m[1] > 0.0, "피치 모멘트가 기수 올림(+)이어야 함"


def test_one_side_contact_rolls_toward_the_free_side():
    """좌측만 닿으면 좌측이 밀려올라 우현이 내려간다 = 롤 + (FRD 규약)."""
    gear, _ac, _w = gear_and_weight()
    q = euler_to_quat(math.radians(-8.0), 0.0, 0.0)  # 좌현 하강
    pos = np.array([0.0, 0.0, -0.50])
    f, m = gear.forces(pos, Z3, q, Z3)
    assert f[2] < 0.0
    assert m[0] > 0.0


def test_symmetric_level_contact_has_no_moment():
    """수평 정지가 평형이려면 접촉점 중심이 CG와 일치해야 한다.

    어긋나면 M_y = Δx·W 가 남아 기체가 지상에서 늘 기운 채 선다. 기하를 손대면
    이 단정이 먼저 깨져 그 사실을 알린다.
    """
    gear, _ac, weight = gear_and_weight()
    assert gear.contacts[:, 0].mean() == pytest.approx(0.0), "접촉 중심이 CG 앞뒤로 어긋남"
    assert gear.contacts[:, 1].mean() == pytest.approx(0.0), "접촉 중심이 좌우로 어긋남"
    delta = gear.rest_penetration(weight)
    pos = np.array([0.0, 0.0, -(0.55 - delta)])
    _f, m = gear.forces(pos, Z3, LEVEL, Z3)
    assert np.allclose(m, 0.0, atol=1e-9), "수평·대칭 접촉은 모멘트가 0"


# ---- 적분 안정성 (이 작업의 최대 수치 리스크) ----


@pytest.mark.parametrize("dt", [0.005, 0.01])
def test_drop_settles_without_divergence(dt):
    """지면 위에 떨어뜨리면 정지 침투로 정착한다 — 발산도, 지면 통과도 없다.

    RK4는 스텝당 힘을 4번 평가하므로 h=0에서 끊기는 힘을 넣으면 부단계가 지면
    안팎을 오간다. 스프링-댐퍼 연속 근사를 쓴 이유가 이것이고, dt_plant가 쓰는
    두 값에서 모두 서는지 여기서 못박는다.
    """
    gear, ac, weight = gear_and_weight()
    m0, _cg, J0 = ac.fuel_mass.at(FUEL)
    rb = RigidBody(m0, J0)
    x = pack(np.array([0.0, 0.0, -0.60]), Z3, LEVEL, Z3)  # 접촉점 5 cm 위에서 낙하

    def fm(xx):
        pos, vel, q, w = unpack(xx)
        f, mm, _m, _J = ac.fm(vel, w, q, -pos[2], CTRL, FUEL, pos_n=pos)
        return f, mm

    for _ in range(int(5.0 / dt)):
        x = rb.step(x, fm, dt)
        assert np.all(np.isfinite(x)), "발산"

    pos, vel, q, _w = unpack(x)
    delta = gear.rest_penetration(weight)
    h = -pos[2]
    assert h == pytest.approx(0.55 - delta, abs=2e-3), "정지 침투로 정착해야 함"
    assert abs(vel[2]) < 1e-2, "수직 속도가 잦아들어야 함"
    assert -pos[2] > 0.0, "지면을 통과하면 안 됨"


def test_skid_rollout_distance():
    """접지 81.5 m/s → 정지까지의 미끄럼 거리 — 활주로 길이를 정하는 수치.

    설계 근사(항력 + μW 등감속)로 937 m를 예상했고 실적분은 907 m다. μ를 바꾸면
    이 값이 곧바로 움직이므로(0.25면 1.3 km) 활주로 기본 길이와 한 세트로 본다.
    """
    gear, ac, weight = gear_and_weight()
    m0, _cg, J0 = ac.fuel_mass.at(FUEL)
    rb = RigidBody(m0, J0)
    delta = gear.rest_penetration(weight)
    x = pack(
        np.array([0.0, 0.0, -(0.55 - delta)]), np.array([81.5, 0.0, 0.0]), LEVEL, Z3
    )

    def fm(xx):
        pos, vel, q, w = unpack(xx)
        f, mm, _m, _J = ac.fm(vel, w, q, -pos[2], CTRL, FUEL, pos_n=pos)
        return f, mm

    dt, t = 0.01, 0.0
    while x[3] > 0.5 and t < 120.0:
        x = rb.step(x, fm, dt)
        t += dt
    assert t == pytest.approx(23.1, abs=0.5)
    assert x[0] == pytest.approx(907.0, rel=0.02), "미끄럼 거리 — 활주로 길이 근거"


def test_ground_absent_matches_pre_ground_behaviour():
    """지면 미장착 기체는 도입 전과 완전히 동일 — 기존 회귀가 흔들리지 않는 근거."""
    plain = make_demo_aircraft()
    withg = make_demo_aircraft(ground=make_demo_skid_gear())
    vel = np.array([200.0, 0.0, 5.0])
    pos = np.array([0.0, 0.0, -1000.0])  # 접촉 없는 고도
    a = plain.fm(vel, Z3, LEVEL, 1000.0, CTRL, FUEL)
    b = withg.fm(vel, Z3, LEVEL, 1000.0, CTRL, FUEL, pos_n=pos)
    assert np.allclose(a[0], b[0])
    assert np.allclose(a[1], b[1])


def test_ground_without_position_is_refused():
    """지면이 붙었는데 위치가 없으면 거부 — 조용히 지면 없이 계산하지 않는다."""
    ac = make_demo_aircraft(ground=make_demo_skid_gear())
    with pytest.raises(ValueError, match="pos_n"):
        ac.fm(np.array([50.0, 0.0, 0.0]), Z3, LEVEL, 10.0, CTRL, FUEL)


# ---- 검증 ----


def test_skid_gear_validation():
    ok = np.array([[0.0, 0.0, 0.5]])
    with pytest.raises(ValueError):
        SkidGear(np.zeros((0, 3)), k=1.0, c=1.0, mu=0.1)
    with pytest.raises(ValueError):
        SkidGear(np.zeros((4, 2)), k=1.0, c=1.0, mu=0.1)
    with pytest.raises(ValueError):
        SkidGear(ok, k=0.0, c=1.0, mu=0.1)
    with pytest.raises(ValueError):
        SkidGear(ok, k=1.0, c=-1.0, mu=0.1)
    with pytest.raises(ValueError):
        SkidGear(ok, k=1.0, c=1.0, mu=-0.1)
    with pytest.raises(ValueError):
        SkidGear(ok, k=1.0, c=1.0, mu=0.1, v_eps=0.0)


# ---- 발사 레일 ----


def test_rail_speed_accel_are_one_relation():
    rail = LaunchRail(length=10.0, elev_angle=math.radians(15.0), exit_speed=81.5)
    assert rail.accel == pytest.approx(81.5**2 / 20.0)
    same = LaunchRail(length=10.0, elev_angle=math.radians(15.0), accel=rail.accel)
    assert same.exit_speed == pytest.approx(81.5)
    assert rail.exit_time == pytest.approx(2 * 10.0 / 81.5)
    assert rail.launch_gx == pytest.approx(rail.accel / G0)


def test_demo_rail_matches_design_numbers():
    """계획서에 적은 설계 수치가 코드와 같은 값인지 — 문서와 코드가 갈라지지 않게."""
    rail = make_demo_launch_rail()
    assert rail.length == 10.0
    assert rail.exit_speed == pytest.approx(81.5)
    assert rail.launch_gx == pytest.approx(33.9, abs=0.1)
    assert rail.exit_time == pytest.approx(0.245, abs=0.001)


def test_rail_state_at_endpoints():
    rail = make_demo_launch_rail()
    pos0, vel0, q0, w0 = rail.state_at(0.0)
    assert np.allclose(pos0, 0.0)
    assert vel0[0] == pytest.approx(0.0)
    assert np.allclose(w0, 0.0)
    assert np.allclose(q0, rail.attitude())

    posL, velL, _q, _w = rail.state_at(rail.length)
    assert velL[0] == pytest.approx(rail.exit_speed)
    assert velL[1] == 0.0 and velL[2] == 0.0, "레일에 물려 있으므로 속도는 동체 x축뿐"
    # 앙각 15°·길이 10 m → 이탈 고도 = 10·sin15°
    assert -posL[2] == pytest.approx(10.0 * math.sin(math.radians(15.0)))
    assert posL[0] == pytest.approx(10.0 * math.cos(math.radians(15.0)))


def test_rail_advance_is_the_closed_form_not_an_approximation():
    """등가속 해석해와 스텝 전진이 반올림 오차 안에서 일치 — 근사가 아니다."""
    rail = make_demo_launch_rail()
    dt = 0.01
    s, _v = 0.0, 0.0
    t = 0.0
    while s < rail.length:
        s, _v = rail.advance(s, dt)
        t += dt
        assert s == pytest.approx(0.5 * rail.accel * t * t, rel=1e-9)


def test_rail_azimuth_rotates_the_direction():
    east = LaunchRail(length=10.0, elev_angle=0.0, azimuth=math.pi / 2, exit_speed=50.0)
    d = east.direction()
    assert d[0] == pytest.approx(0.0, abs=1e-12)
    assert d[1] == pytest.approx(1.0)
    assert d[2] == pytest.approx(0.0)


def test_rail_validation():
    with pytest.raises(ValueError):
        LaunchRail(length=0.0, elev_angle=0.0, exit_speed=50.0)
    with pytest.raises(ValueError):
        LaunchRail(length=10.0, elev_angle=math.pi, exit_speed=50.0)
    with pytest.raises(ValueError, match="정확히 하나"):
        LaunchRail(length=10.0, elev_angle=0.0, exit_speed=50.0, accel=100.0)
    with pytest.raises(ValueError, match="정확히 하나"):
        LaunchRail(length=10.0, elev_angle=0.0)
    with pytest.raises(ValueError):
        LaunchRail(length=10.0, elev_angle=0.0, exit_speed=-1.0)
    with pytest.raises(ValueError):
        LaunchRail(length=10.0, elev_angle=0.0, accel=0.0)
    with pytest.raises(ValueError):
        LaunchRail(length=10.0, elev_angle=0.0, exit_speed=50.0, origin_n=[0.0, 0.0])


# ---- 구조 한계 ----


def test_launch_load_limit_is_unjudged_not_zero():
    """종방향 발사 한계는 값이 없다 — None이어야 하고 0이면 '한계 0'으로 읽힌다."""
    lim = make_demo_structural_limits()
    assert "n_x_launch" in lim, "항목 자체가 있어야 '미판정'을 말할 수 있다"
    assert lim["n_x_launch"] is None
    assert lim["n_limit_pos"] == 6.0, "Nz 한계는 종방향 판정에 쓸 수 없다"
