"""M8 guidance 검증 — 조건 프리미티브, 선언적 모드 테이블+실행기, LOS 경로추종.

모드 전환 로직은 선언적 모드 테이블 + 실행기 [확정 01 §3.3.1] — 각 모드
{활성 명령, 이탈조건, next}. 진입조건은 순차 체인(이전 모드의 이탈)으로 대체
[기본값]. 경로추종은 LOS [기본값], 레지스트리 교체 가능.
"""

import math

import numpy as np
import pytest

from claw.common.attitude import euler_to_dcm, euler_to_quat
from claw.common.contracts import NavOutput
from claw.guidance import Guidance, LosPath, ModeSequencer, ModeSpec, eval_condition
from claw.params.registry import REGISTRY

DT = 0.01


def _nav(t=0.0, n=0.0, e=0.0, h=1000.0, speed=200.0, psi=0.0):
    q = euler_to_quat(0.0, 0.0, psi)
    vel_b = np.array([speed, 0.0, 0.0])
    return NavOutput(t=t, pos_n=np.array([n, e, -h]),
                     vel_n=euler_to_dcm(0.0, 0.0, psi).T @ vel_b, q_nb=q)


# ---------- 조건 프리미티브 ----------


def test_condition_primitives():
    ctx = {"t_mode": 3.0, "path_done": True}
    nav = _nav(h=1200.0, speed=150.0)
    assert eval_condition(("always",), nav, ctx)
    assert eval_condition(("alt_ge", 1100.0), nav, ctx)
    assert not eval_condition(("alt_ge", 1300.0), nav, ctx)
    assert eval_condition(("alt_le", 1200.0), nav, ctx)
    assert eval_condition(("speed_ge", 149.0), nav, ctx)
    assert not eval_condition(("speed_le", 100.0), nav, ctx)
    assert eval_condition(("time_ge", 2.5), nav, ctx)
    assert not eval_condition(("time_ge", 3.5), nav, ctx)
    assert eval_condition(("path_done",), nav, ctx)
    assert not eval_condition(("path_done",), nav, {"t_mode": 0.0, "path_done": False})
    with pytest.raises(ValueError):
        eval_condition(("unknown_cond",), nav, ctx)


# ---------- 모드 → GuidanceCommand ----------


def _hold_forever(**kw):
    return ModeSpec(exit_when=("time_ge", 1e9), **kw)


def test_mode_commands_and_flags():
    g = Guidance([_hold_forever(name="cruise", speed=150.0, alt=1000.0, heading=0.5)]).init(DT)
    cmd = g.step(_nav())
    assert cmd.mode == "cruise"
    assert cmd.speed == 150.0 and cmd.speed_on
    assert cmd.alt == 1000.0 and cmd.alt_on
    assert cmd.heading == 0.5 and cmd.heading_on


def test_mode_none_means_axis_off():
    g = Guidance([_hold_forever(name="glide", alt=500.0)]).init(DT)
    cmd = g.step(_nav())
    assert cmd.alt_on and not cmd.speed_on and not cmd.heading_on


def test_mode_heading_path_uses_los():
    path = LosPath(waypoints=((1000.0, 1000.0),))
    g = Guidance([_hold_forever(name="wpnav", heading="path")], path=path).init(DT)
    cmd = g.step(_nav(n=0.0, e=0.0))
    assert cmd.heading_on
    assert cmd.heading == pytest.approx(math.atan2(1000.0, 1000.0))


def test_mode_heading_path_without_follower_raises():
    with pytest.raises(ValueError):
        Guidance([_hold_forever(name="wpnav", heading="path")])


# ---------- 실행기 (전환) ----------


def test_sequencer_transitions_on_alt_and_resets_mode_clock():
    modes = [
        ModeSpec(name="climb", alt=900.0, speed=150.0, exit_when=("alt_ge", 850.0),
                 next="cruise"),
        ModeSpec(name="cruise", alt=900.0, speed=180.0, exit_when=("time_ge", 0.5),
                 next="descent"),
        _hold_forever(name="descent", alt=300.0),
    ]
    g = Guidance(modes).init(DT)
    assert g.step(_nav(t=0.0, h=500.0)).mode == "climb"
    assert g.step(_nav(t=10.0, h=840.0)).mode == "climb"  # 이탈조건 미충족
    cmd = g.step(_nav(t=20.0, h=860.0))
    assert cmd.mode == "cruise" and cmd.speed == 180.0  # 전환 + 새 명령
    # t_mode는 진입 시점부터: 20.4 s(체류 0.4)엔 유지, 20.6 s(체류 0.6)엔 이탈
    assert g.step(_nav(t=20.4, h=860.0)).mode == "cruise"
    assert g.step(_nav(t=20.6, h=860.0)).mode == "descent"


def test_sequencer_terminal_mode_stays():
    g = Guidance([ModeSpec(name="dive", alt=0.0, exit_when=("always",), next=None)]).init(DT)
    for t in (0.0, 1.0, 2.0):
        assert g.step(_nav(t=t)).mode == "dive"  # next 없음 → 종단 모드 유지


def test_sequencer_unknown_next_raises_at_construction():
    with pytest.raises(ValueError):
        ModeSequencer([ModeSpec(name="a", exit_when=("always",), next="nope")])


# ---------- LOS 경로추종 ----------


def test_los_heading_switching_and_done():
    path = LosPath(waypoints=((1000.0, 0.0), (1000.0, 1000.0)), accept_radius=50.0).init(DT)
    hdg, done = path.step(_nav(n=0.0, e=0.0))
    assert hdg == pytest.approx(0.0) and not done  # 정북 wp1
    hdg, done = path.step(_nav(n=990.0, e=0.0))  # wp1 반경 내 → wp2로 전환
    assert hdg == pytest.approx(math.atan2(1000.0, 10.0)) and not done
    hdg, done = path.step(_nav(n=1000.0, e=980.0))  # wp2 반경 내 → 소진
    assert done
    assert hdg == pytest.approx(math.atan2(1000.0, 10.0))  # 마지막 헤딩 유지


def test_los_registry_swappable():
    """경로추종은 레지스트리 교체 가능 컴포넌트 (03 M8) — LOS [기본값] 등록."""
    import claw.guidance  # noqa: F401 — import 시 등록

    los = REGISTRY.create("guidance", "LOS", {"accept_radius": 120.0})
    assert los.accept_radius == 120.0
    los.set_waypoints(((500.0, 0.0),))
    hdg, done = los.init(DT).step(_nav())
    assert hdg == pytest.approx(0.0) and not done


def test_guidance_full_mission_logic_scripted_nav():
    """상승→웨이포인트 순항→디센트 — 스크립트 항법 궤적으로 모드 체인 완주."""
    path = LosPath(waypoints=((5000.0, 0.0), (5000.0, 5000.0)), accept_radius=100.0)
    modes = [
        ModeSpec(name="climb", alt=1500.0, speed=170.0, exit_when=("alt_ge", 1450.0),
                 next="wpnav"),
        ModeSpec(name="wpnav", alt=1500.0, speed=170.0, heading="path",
                 exit_when=("path_done",), next="descent"),
        _hold_forever(name="descent", alt=50.0, speed=170.0),
    ]
    g = Guidance(modes, path=path).init(DT)
    seen = [g.step(_nav(t=0.0, h=500.0)).mode]
    seen.append(g.step(_nav(t=30.0, h=1460.0)).mode)  # 상승 완료
    g.step(_nav(t=40.0, h=1500.0, n=4950.0, e=0.0))  # wp1 도달 → wp2
    cmd = g.step(_nav(t=41.0, h=1500.0, n=4950.0, e=10.0))
    assert cmd.heading == pytest.approx(math.atan2(4990.0, 50.0), rel=1e-6)
    final = g.step(_nav(t=60.0, h=1500.0, n=5000.0, e=4950.0))  # wp2 도달 → 소진
    seen.append(final.mode)
    assert seen == ["climb", "wpnav", "descent"]
    assert final.alt == 50.0  # 디센트 명령 반영
