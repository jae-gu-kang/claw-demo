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


def test_condition_arity_and_type_validated_at_construction():
    """인자 누락·비수치 임계값은 구성 시 거부 — 배치 시뮬 도중 예외 방지 (리뷰 Must fix)."""
    from claw.guidance import ModeSequencer

    with pytest.raises(ValueError):
        ModeSequencer([ModeSpec(name="a", exit_when=("time_ge",))])  # 임계값 누락
    with pytest.raises(ValueError):
        ModeSequencer([ModeSpec(name="a", exit_when=("alt_ge", "500"))])  # 문자열
    with pytest.raises(ValueError):
        ModeSequencer([ModeSpec(name="a", exit_when=("always", 1.0))])  # 잉여 인자


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


def test_path_done_condition_without_follower_raises():
    """path 없으면 path_done 영원히 False → 조용한 미이탈 — 구성 시 거부 (리뷰 반영)."""
    modes = [
        ModeSpec(name="a", alt=100.0, exit_when=("path_done",), next="b"),
        _hold_forever(name="b", alt=50.0),
    ]
    with pytest.raises(ValueError):
        Guidance(modes)


def test_guidance_invalid_nav_freezes_transitions_and_holds_command():
    """nav.valid=False → 전환 동결 + 마지막 명령 유지 (첫 유효 이전엔 전 축 비활성)."""
    modes = [
        ModeSpec(name="lo", alt=500.0, exit_when=("alt_ge", 2000.0), next="hi"),
        _hold_forever(name="hi", alt=3000.0),
    ]
    g = Guidance(modes).init(DT)
    first = g.step(NavOutput(valid=False))
    assert first.mode == "lo" and not (first.alt_on or first.speed_on or first.heading_on)
    valid_cmd = g.step(_nav(t=1.0, h=1000.0))
    assert valid_cmd.mode == "lo" and valid_cmd.alt_on
    # invalid인데 고도값은 전환 조건 충족 — 평가되면 안 됨
    frozen = g.step(NavOutput(t=2.0, pos_n=np.array([0.0, 0.0, -2500.0]), valid=False))
    assert frozen.mode == "lo" and frozen.alt == valid_cmd.alt and frozen.alt_on
    assert g.step(_nav(t=3.0, h=1000.0)).mode == "lo"  # 유효 복귀 후에도 전환 없음


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
    hdg, alt, done = path.step(_nav(n=0.0, e=0.0))
    assert hdg == pytest.approx(0.0) and not done  # 정북 wp1
    assert alt is None  # 고도 없는 웨이포인트 열 — 없는 명령을 0으로 위장하지 않는다
    hdg, _alt, done = path.step(_nav(n=990.0, e=0.0))  # wp1 반경 내 → wp2로 전환
    assert hdg == pytest.approx(math.atan2(1000.0, 10.0)) and not done
    hdg, _alt, done = path.step(_nav(n=1000.0, e=980.0))  # wp2 반경 내 → 소진
    assert done
    assert hdg == pytest.approx(math.atan2(1000.0, 10.0))  # 마지막 헤딩 유지


def test_los_chained_skip_within_radius():
    """반경 내 웨이포인트 여러 개를 한 스텝에 연쇄 스킵 (docstring 계약 핀)."""
    path = LosPath(waypoints=((10.0, 0.0), (20.0, 20.0), (1000.0, 1000.0)),
                   accept_radius=50.0).init(DT)
    hdg, _alt, done = path.step(_nav(n=0.0, e=0.0))
    assert hdg == pytest.approx(math.atan2(1000.0, 1000.0)) and not done


def test_los_exhausted_before_first_heading_uses_current_course():
    """빈 리스트/반경 내 시작 — 정북(0) 급선회 대신 현재 침로 유지 (리뷰 반영)."""
    path = LosPath(waypoints=()).init(DT)
    hdg, alt, done = path.step(_nav(psi=math.pi / 2))  # 동쪽 비행 중
    assert done and hdg == pytest.approx(math.pi / 2) and alt is None


def test_los_registry_swappable():
    """경로추종은 레지스트리 교체 가능 컴포넌트 (03 M8) — LOS [기본값] 등록."""
    import claw.guidance  # noqa: F401 — import 시 등록

    los = REGISTRY.create("guidance", "LOS", {"accept_radius": 120.0})
    assert los.accept_radius == 120.0
    los.set_waypoints(((500.0, 0.0),))
    hdg, _alt, done = los.init(DT).step(_nav())
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


# ---------- LOS 세로 프로파일 (웨이포인트 고도, 01 §3.3) ----------


def test_los_leg_altitude_is_linear_not_a_step():
    """구간 선형 보간 — 활성 웨이포인트 고도를 곧바로 명령(계단)하지 않는다.

    계단이면 화면의 세로 프로파일(거리-고도 꺾은선)이 실제 명령과 다른 것을
    그리게 된다. 첫 구간의 시작 고도는 **첫 스텝의 기체 고도**다 — 출발점은
    웨이포인트가 아니라 계획에 없으므로, 기체가 실제 있는 자리에서 이어야 한다.
    """
    path = LosPath(waypoints=((1000.0, 0.0, 1500.0),), accept_radius=50.0).init(DT)
    # 첫 스텝: 기체 500 m, 남은 거리 = 구간 전체 → 시작 고도 그대로
    hdg, alt, done = path.step(_nav(n=0.0, e=0.0, h=500.0))
    assert not done and hdg == pytest.approx(0.0)
    assert alt == pytest.approx(500.0)
    # 램프는 **반경 경계**까지다 — 유효 구간 1000-50=950, 절반은 rem=525 (n=475)
    _h, alt, _d = path.step(_nav(n=475.0, e=0.0, h=900.0))
    assert alt == pytest.approx(1000.0)  # 500↔1500의 중간
    # 구간을 벗어나 뒤로 물러나도 계획 밖 고도로 외삽하지 않는다 ([0,1] 클램프)
    _h, alt, _d = path.step(_nav(n=-4000.0, e=0.0, h=900.0))
    assert alt == pytest.approx(500.0)
    # 반경 경계 직전(rem=51)에 이미 목표 고도에 거의 닿아 있다 — 전환이 반경에서
    # 일어나므로 명령이 연속이다. 중심 기준으로 이었다면 여기서 Δ·r/seg = 50 m
    # 모자란 1450에 머물다 다음 구간 시작에 1500으로 튄다
    _h, alt, done = path.step(_nav(n=949.0, e=0.0, h=1400.0))
    assert not done and alt == pytest.approx(1500.0, abs=2.0)


def test_los_altitude_carries_across_legs_and_holds_after_done():
    """구간이 바뀌면 시작 고도도 그 웨이포인트 고도로 — 소진 후엔 마지막 값 유지."""
    path = LosPath(
        waypoints=((1000.0, 0.0, 800.0), (1000.0, 1000.0, 400.0)), accept_radius=50.0
    ).init(DT)
    path.step(_nav(n=0.0, e=0.0, h=800.0))
    # wp1 반경 진입 → wp2 구간 시작(고도 800에서 400으로). 갓 전환한 시점은 800 근처
    _h, alt, done = path.step(_nav(n=990.0, e=0.0, h=800.0))
    assert not done and alt == pytest.approx(800.0)  # 새 구간의 시작이라 정확히 800
    # 유효 구간 1000-50=950, 절반은 rem=525 (e=475)
    _h, alt, _d = path.step(_nav(n=1000.0, e=475.0, h=600.0))
    assert alt == pytest.approx(600.0)  # 800↔400의 중간
    _h, alt, done = path.step(_nav(n=1000.0, e=980.0, h=420.0))
    # 소진 — "마지막 명령 유지"가 아니라 **마지막 웨이포인트 고도로 정착**이다.
    # 유지였다면 직전 스텝의 600이 남는다 (그것이 계획보다 200 m 높은 수평비행)
    assert done and alt == pytest.approx(400.0)


def test_los_altitude_all_or_none():
    """고도는 전부 있거나 전부 없거나 — 섞이면 구성 시점 거부.

    없는 쪽을 0이나 이웃 값으로 메우면 화면의 세로 프로파일이 사용자가 넣지 않은
    고도를 넣은 것처럼 그린다 (판정 불가를 정상으로 위장하지 않는 것과 같은 자리).
    """
    with pytest.raises(ValueError, match="전부 있거나"):
        LosPath(waypoints=((1000.0, 0.0, 800.0), (2000.0, 0.0)))
    with pytest.raises(ValueError, match="n, e"):
        LosPath(waypoints=((1000.0,),))
    assert LosPath(waypoints=((1000.0, 0.0),)).has_alt is False
    assert LosPath(waypoints=((1000.0, 0.0, 800.0),)).has_alt is True


def test_mode_alt_path_selects_the_path_altitude():
    """alt="path"는 heading="path"와 **같은 규약** — 모드가 축별 출처를 고른다.

    경로와 모드 중 누가 이기는지 따로 정하지 않는 이유가 이것이다.
    """
    path = LosPath(waypoints=((1000.0, 0.0, 1500.0),), accept_radius=50.0)
    g = Guidance([_hold_forever(name="climb", speed=170.0, alt="path", heading="path")],
                 path=path).init(DT)
    cmd = g.step(_nav(n=500.0, e=0.0, h=500.0))
    assert cmd.alt_on and cmd.alt == pytest.approx(500.0)  # 첫 스텝 기준 고도
    # 유효 구간 (1000-500)-50 = 450, 절반은 rem=275 (n=725)
    cmd = g.step(_nav(n=725.0, e=0.0, h=900.0))
    assert cmd.alt == pytest.approx(1000.0)  # 500↔1500의 중간
    # 같은 경로라도 수치를 적은 모드는 그 수치가 이긴다 (경로가 덮지 않는다)
    g2 = Guidance([_hold_forever(name="hold", alt=300.0, heading="path")],
                  path=LosPath(waypoints=((1000.0, 0.0, 1500.0),))).init(DT)
    assert g2.step(_nav(n=0.0, e=0.0, h=500.0)).alt == pytest.approx(300.0)


def test_alt_axis_engagement_reanchors_the_ramp_where_the_aircraft_is():
    """고도 축이 경로를 **잡는 순간** 구간 램프를 그 자리에서 다시 긋는다.

    첫 스텝 자리에 램프를 박아 두면 지상 출발에서 그 자리는 발사대(h≈1.2 m)다.
    고도 축은 한참 뒤 순항에서야 경로를 잡는데, 그때까지 기체가 250 m를 올라와도
    램프는 여전히 지상에서 재어져 **한참 아래**를 명령한다 — 고도 루프는 그것을
    급강하 지령으로 읽는다. 여기서 못박는 것은 그 재기준이다.

    수치: 첫 구간 (0,0,1.2)→(10000,0,300), 도달반경 300 → 유효 램프 9700 m.
    기체가 (2000, 0, 250)에 있을 때 옛 규약이면 rem 8000에서
    1.2 + 298.8·(1 − 7700/9700) = 62.8 m — 실제 고도보다 187 m 낮다.
    재기준 후에는 그 자리가 곧 램프의 시작이라 첫 명령이 250 m다.
    """
    path = LosPath(waypoints=((10000.0, 0.0, 300.0),), accept_radius=300.0)
    modes = [
        ModeSpec(name="climb", speed=110.0, pitch=0.36, heading=0.0,
                 exit_when=("alt_ge", 250.0), next="cruise"),
        _hold_forever(name="cruise", speed=88.0, alt="path", heading="path"),
    ]
    g = Guidance(modes, path=path).init(DT)
    # 지상에서 출발 — 고도 축은 아직 경로를 안 잡는다 (피치 축 구간)
    cmd = g.step(_nav(t=0.0, n=0.0, e=0.0, h=1.2))
    assert cmd.mode == "climb" and not cmd.alt_on
    # 2 km 북쪽·250 m에서 순항 진입 → 여기서부터 램프를 다시 긋는다
    g.step(_nav(t=20.0, n=2000.0, e=0.0, h=250.0))  # 이 스텝에 전환 (명령은 다음 스텝)
    cmd = g.step(_nav(t=20.01, n=2000.0, e=0.0, h=250.0))
    assert cmd.mode == "cruise" and cmd.alt_on
    assert cmd.alt == pytest.approx(250.0, abs=1.0), "재기준 없으면 62.8 m가 나온다"
    # 램프는 여기서 목표까지 — 남은 8000 m의 절반쯤에서 중간 고도
    # 유효 구간 8000−300 = 7700, rem 4150 → frac = 1 − 3850/7700 = 0.5
    cmd = g.step(_nav(t=60.0, n=5850.0, e=0.0, h=280.0))
    assert cmd.alt == pytest.approx(275.0, abs=1.0)  # 250↔300의 중간
    # **진입 때 한 번만** 긋는다 — 매 스텝 다시 그으면 frac이 늘 0이라 명령이 현재
    # 고도에 얼어붙고, 세로 경로추종이 "지금 고도 유지"로 조용히 무너진다(리뷰 실측:
    # 선회 미션 순항 고도대가 250→525 m 상승에서 241→278 m 제자리로 붕괴). 위 단정만
    # 으로는 그 변이가 안 잡힌다 — begin_alt_leg가 path.step **뒤**에 불려 한 스텝
    # 늦게 드러나기 때문이다. 같은 자리를 한 번 더 밟아 그 차이를 본다
    assert g.step(_nav(t=60.01, n=5850.0, e=0.0, h=280.0)).alt == pytest.approx(275.0, abs=1.0)


def test_alt_axis_reengagement_reanchors_again():
    """껐다 켜면 **그때마다** 다시 긋는다 — 재진입은 곧 재계획이다.

    한 번만 긋고 마는 규약이면, 중간에 수치 고도로 빠졌다 돌아온 미션이 옛
    시작점을 계속 들고 있어 같은 낙차가 되살아난다.
    """
    path = LosPath(waypoints=((10000.0, 0.0, 1000.0),), accept_radius=100.0)
    modes = [
        ModeSpec(name="a", alt="path", exit_when=("alt_ge", 400.0), next="b"),
        ModeSpec(name="b", alt=500.0, exit_when=("alt_ge", 600.0), next="c"),
        _hold_forever(name="c", alt="path"),
    ]
    g = Guidance(modes, path=path).init(DT)
    g.step(_nav(t=0.0, n=0.0, h=300.0))          # a — (0,0,300)에서 램프 시작
    g.step(_nav(t=1.0, n=100.0, h=450.0))        # a→b 전환
    assert g.step(_nav(t=2.0, n=200.0, h=520.0)).alt == pytest.approx(500.0)  # b는 수치
    g.step(_nav(t=3.0, n=300.0, h=650.0))        # b→c 전환 (여기서 다시 긋는다)
    cmd = g.step(_nav(t=3.01, n=300.0, h=650.0))
    assert cmd.mode == "c"
    # 재기준했으면 (300, 650)에서 시작 → 첫 명령이 650. 안 했으면 300에서 재어진 값
    assert cmd.alt == pytest.approx(650.0, abs=1.0)


def test_mode_alt_path_without_usable_path_is_rejected_loudly():
    """경로가 없거나 고도가 없는데 alt="path"면 구성 시점 거부.

    허용하면 고도 축이 조용히 꺼진 채 날거나(alt_on=False) None을 0으로 읽어
    해면을 명령한다 — 둘 다 요청한 것과 다르다.
    """
    with pytest.raises(ValueError, match='alt="path".*경로추종기가 없음'):
        Guidance([_hold_forever(name="m", alt="path")])
    with pytest.raises(ValueError, match='alt="path".*고도가 없음'):
        Guidance([_hold_forever(name="m", alt="path")],
                 path=LosPath(waypoints=((1000.0, 0.0),)))


def test_mode_alt_path_detects_a_path_swapped_out_after_construction():
    """구성 뒤 set_waypoints로 고도를 없애면 시끄럽게 터진다.

    __init__ 가드는 그때의 has_alt를 본 스냅샷이라 뒤에서 뚫린다. 조용히 두면
    alt_on=False로 고도 축이 꺼진 채 날아 가드가 막으려던 결과가 그대로 난다.
    """
    path = LosPath(waypoints=((1000.0, 0.0, 1500.0),), accept_radius=50.0)
    g = Guidance([_hold_forever(name="m", alt="path")], path=path).init(DT)
    assert g.step(_nav(n=0.0, e=0.0, h=500.0)).alt_on  # 아직은 정상
    path.set_waypoints(((1000.0, 0.0),))  # 고도를 뺀 열로 교체
    # ValueError면 서버가 422(사용자 입력 오류)로 매핑한다 — 이건 계약 위반이다
    with pytest.raises(RuntimeError, match="고도를 내지 않는다"):
        g.step(_nav(n=0.0, e=0.0, h=500.0))


def test_los_altitude_command_is_continuous_across_waypoint_transitions():
    """구간 전환에서 고도 명령이 튀지 않는다 — 이 기하의 **유일한 존재 이유**.

    램프를 웨이포인트 중심까지 이으면 전환(반경 진입) 시점에 목표에 닿기 전에
    끊기고 다음 구간 시작이 wa로 점프한다: Δalt·r/seg. 실측 201 m(구간 500 m·
    반경 200 m·Δ500 m)였다. 반경 경계에서 끝내면 그 점프가 사라진다.

    핀하는 방식: 촘촘히 밟으며 스텝 간 명령 변화가 **구간 기울기 × 이동거리**를
    넘지 않아야 한다. 넘는 순간이 곧 점프다.
    """
    wps = ((2000.0, 0.0, 1500.0), (2000.0, 2000.0, 900.0))
    r, dx = 200.0, 5.0
    path = LosPath(waypoints=wps, accept_radius=r).init(DT)
    # 두 구간 다 seg=2000 → 유효 구간 1800, 최대 기울기는 |Δalt|/1800
    slope = max(abs(1500.0 - 1000.0), abs(900.0 - 1500.0)) / (2000.0 - r)
    prev = None
    worst = 0.0
    for n in [i * dx for i in range(int(2000 / dx) + 1)]:  # 1구간: 북으로
        _h, alt, _d = path.step(_nav(n=n, e=0.0, h=1000.0))
        if prev is not None:
            worst = max(worst, abs(alt - prev))
        prev = alt
    for e in [i * dx for i in range(int(2000 / dx) + 1)]:  # 2구간: 동으로
        _h, alt, _d = path.step(_nav(n=2000.0, e=e, h=1200.0))
        if prev is not None:
            worst = max(worst, abs(alt - prev))
        prev = alt
    assert worst <= slope * dx + 1e-9, (
        f"전환에서 명령이 튀었다 — 최대 스텝간 변화 {worst:.3f} m > 기울기 한계 "
        f"{slope * dx:.3f} m (중심 기준 램프였다면 Δ·r/seg = 60 m 점프)"
    )
    assert prev == pytest.approx(900.0)  # 끝에는 마지막 웨이포인트 고도로 정착


# ---- 종방향 축 (01 §3.3.1 이륙·착륙) ----


def test_longitudinal_axes_are_exclusive():
    """alt·pitch·hdot은 셋 다 θ_cmd로 간다 — 둘을 켜면 구성 시점에 거부한다.

    우선순위를 두면 화면이 "무엇이 먹었는지"를 말할 수 없다. 축마다 출처를 고르는
    기존 규약과 같은 정신이고, 이번엔 검증으로 못박는다.
    """
    from claw.guidance.modes import validate_longitudinal

    ok = ModeSpec(name="m", alt=100.0, exit_when=("time_ge", 1.0))
    validate_longitudinal(ok)  # 하나면 통과
    validate_longitudinal(ModeSpec(name="m", pitch=0.1, exit_when=("time_ge", 1.0)))
    validate_longitudinal(ModeSpec(name="m", hdot=-2.0, exit_when=("time_ge", 1.0)))
    validate_longitudinal(ModeSpec(name="m", exit_when=("time_ge", 1.0)))  # 전부 꺼짐도 통과
    for bad in (
        ModeSpec(name="b", alt=100.0, pitch=0.1),
        ModeSpec(name="b", alt=100.0, hdot=-2.0),
        ModeSpec(name="b", pitch=0.1, hdot=-2.0),
        ModeSpec(name="b", alt=100.0, pitch=0.1, hdot=-2.0),
    ):
        with pytest.raises(ValueError, match="종방향 축은 하나만"):
            validate_longitudinal(bad)
    # 시퀀서 구성에서도 같은 검증이 걸린다
    with pytest.raises(ValueError, match="종방향 축은 하나만"):
        ModeSequencer([ModeSpec(name="b", alt=100.0, hdot=-2.0)])


def test_pitch_and_hdot_reach_the_command():
    g = Guidance([
        ModeSpec(name="p", speed=100.0, pitch=0.15, exit_when=("time_ge", 1.0), next="v"),
        ModeSpec(name="v", speed=100.0, hdot=-3.0, exit_when=("time_ge", 1e9)),
    ]).init(0.01)
    cmd = g.step(_nav(t=0.0))
    assert cmd.pitch_on and not cmd.alt_on and not cmd.hdot_on
    assert cmd.pitch == pytest.approx(0.15)
    cmd = g.step(_nav(t=2.0))
    assert cmd.hdot_on and not cmd.pitch_on
    assert cmd.hdot == pytest.approx(-3.0)
    # 축이 꺼진 자리의 값은 0이고 플래그가 그 사실을 말한다
    assert cmd.pitch == 0.0 and cmd.alt == 0.0


def test_hdot_conditions_use_climb_positive_sign():
    """승강률은 상승 +다 — 강하 4 m/s보다 가파른 것은 ("hdot_le", -4.0)."""
    from claw.guidance.modes import eval_condition

    ctx = {"t_mode": 0.0, "path_done": False, "on_ground": None, "on_rail": None}

    def vertical(vd):  # NED 하방 + — 강하가 양수인 성분
        return NavOutput(t=0.0, pos_n=np.array([0.0, 0.0, -500.0]),
                         vel_n=np.array([50.0, 0.0, vd]),
                         q_nb=euler_to_quat(0.0, 0.0, 0.0))

    descending = vertical(5.0)  # 강하 5 m/s → ḣ = −5
    assert eval_condition(("hdot_le", -4.0), descending, ctx) is True
    assert eval_condition(("hdot_ge", -4.0), descending, ctx) is False
    climbing = vertical(-3.0)  # 상승 3 m/s → ḣ = +3
    assert eval_condition(("hdot_ge", 2.0), climbing, ctx) is True
    assert eval_condition(("hdot_le", -4.0), climbing, ctx) is False


def test_ground_and_rail_conditions_refuse_to_guess():
    """판정 불가를 False로 눙치면 모드가 조용히 그 자리에 멈춘다."""
    from claw.guidance.modes import eval_condition

    base = {"t_mode": 0.0, "path_done": False, "on_ground": None, "on_rail": None}
    nav = _nav(t=0.0)
    for cond in (("on_ground",), ("airborne",), ("off_rail",)):
        with pytest.raises(RuntimeError):
            eval_condition(cond, nav, base)
    on = {**base, "on_ground": True, "on_rail": True}
    assert eval_condition(("on_ground",), nav, on) is True
    assert eval_condition(("airborne",), nav, on) is False
    assert eval_condition(("off_rail",), nav, on) is False
    off = {**base, "on_ground": False, "on_rail": False}
    assert eval_condition(("on_ground",), nav, off) is False
    assert eval_condition(("airborne",), nav, off) is True
    assert eval_condition(("off_rail",), nav, off) is True


def test_guidance_declares_what_the_table_needs():
    """접지·레일 조건을 쓰면 그 사실이 드러나야 시뮬이 형상을 대조할 수 있다."""
    plain = Guidance([ModeSpec(name="m", exit_when=("time_ge", 1e9))])
    assert plain.needs_ground is False and plain.needs_rail is False
    g = Guidance([
        ModeSpec(name="a", exit_when=("off_rail",), next="b"),
        ModeSpec(name="b", exit_when=("on_ground",), next="c"),
        ModeSpec(name="c", exit_when=("time_ge", 1e9)),
    ])
    assert g.needs_ground is True and g.needs_rail is True
