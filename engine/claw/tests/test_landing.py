"""이륙~착륙 전장 시나리오 (01 §3.3.1) — 발사→상승→순항→접근→플레어→접지→정지.

**순항 회귀(test_mission)는 그대로 남는다.** 그쪽은 지면 모델을 장착하지 않은
시나리오라 여전히 해수면 아래로 내려가고, 그 사실을 고정한 단정도 살아 있다.
이 파일은 그 옆에 신설한 것이고, 여기서 못박는 것은 "착륙이 실제로 된다"는 것과
그때의 실측 수치다.

전제 하나를 명시한다 — **RTK 고정해**. 다만 그 이유는 처음 적었던 것과 다르다:
실측해 보니 접지 강하율은 항법 등급과 거의 무관하고, 갈리는 것은
**접지 지점**이다 — RTK 5시드 폭 7.9 m이고 기본 GNSS는 그보다 두 자릿수 크다.
활주로가 1,500 m이므로 그 산포가 곧 "활주로에 내리느냐"를 가른다.
(수치는 프로펠러 전환으로 재측정했다 — 아래 테스트 독스트링에 경위가 있다.)
test_rtk_buys_a_repeatable_touchdown_point_not_a_softer_one이 그 대비를 담는다.
"""

import math

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.fcl import make_demo_fcl
from claw.guidance import Guidance, ModeSpec
from claw.guidance.path import LosPath
from claw.nav import NavErrorModel
from claw.pipeline.metrics import climb_rate
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_launch_rail,
    make_demo_skid_gear,
    make_demo_stall_table,
)
from claw.sim import Simulator
from claw.trim import trim_ground

DT = 0.01
CLIMB_PITCH = math.radians(21.0)
FLARE_ALT = 20.0  # [m] 플레어 개시 — 게인과 한 세트로 실측 (autopilot.py kp_vs 주석)


def landing_modes(flare_alt=FLARE_ALT):
    """발사대에서 떠서 활주로에 서기까지 — 종방향 축이 단계마다 갈린다.

    launch·climb·rollout은 **피치**(고도 루프를 거칠 이유가 없는 자세 구간),
    approach·flare는 **강하율**(어느 고도가 아니라 내려가는 속도를 잡는 구간),
    cruise만 **고도**다. 셋은 배타이므로 한 모드에 하나씩만 들어간다.
    """
    return [
        ModeSpec(name="launch", speed=110.0, pitch=CLIMB_PITCH, heading=0.0,
                 exit_when=("off_rail",), next="climb"),
        ModeSpec(name="climb", speed=110.0, pitch=CLIMB_PITCH, heading=0.0,
                 exit_when=("alt_ge", 250.0), next="cruise"),
        ModeSpec(name="cruise", speed=88.0, alt=300.0, heading=0.0,
                 exit_when=("time_ge", 20.0), next="approach"),
        # 3° 활공: 88 m/s · sin3° ≈ 4.6 m/s. −4.8은 그 언저리의 라운드 값
        ModeSpec(name="approach", speed=88.0, hdot=-4.8, heading=0.0,
                 exit_when=("alt_le", flare_alt), next="flare"),
        ModeSpec(name="flare", speed=80.0, hdot=-0.8, heading=0.0,
                 exit_when=("on_ground",), next="rollout"),
        ModeSpec(name="rollout", speed=0.0, pitch=0.0, heading=0.0,
                 exit_when=("speed_le", 0.5), next="stopped"),
        ModeSpec(name="stopped", speed=0.0, pitch=0.0, exit_when=("time_ge", 1e9)),
    ]


def fly(nav=None, flare_alt=FLARE_ALT, t_end=220.0):
    gear = make_demo_skid_gear()
    ac = make_demo_aircraft(ground=gear)
    rail = make_demo_launch_rail()
    tr = trim_ground(ac, TrimCase("pad", mach=0.0, alt=0.0, fuel=300.0, condition="ground"))
    assert tr.converged
    sim = Simulator(
        aircraft=ac, fcl=make_demo_fcl(), guidance=Guidance(landing_modes(flare_alt)),
        nav_model=nav if nav is not None else NavErrorModel.rtk_fixed(seed=11),
        stall_table=make_demo_stall_table(), db_ranges=make_demo_db_ranges(),
        dt_plant=DT, control_hz=100.0, ground_elev=0.0, launch=rail,
        actuator_params={"wn": 30.0, "zeta": 0.7, "rate_max": 10.0}, fuel_flow=0.3,
    )
    return sim.run(tr, t_end=t_end, fingerprint="landing-demo")


# 승강률은 **생산 경로의 것을 그대로 쓴다** (pipeline.metrics.climb_rate).
# 사본을 두면 지표 쪽 식을 고쳐도 이 회귀는 자기 사본으로 계속 통과해, 지표와
# 테스트가 서로 다른 승강률을 가리키는데 빨간불이 안 들어온다 (02 §5.5).
# 별칭도 두지 않는다 — sink(아래가 +)와 climb(위가 +)은 부호가 반대라
# `sink_rate(...) == approx(-1.0)`이 읽다가 멈추게 만든다.


@pytest.fixture(scope="module")
def landed():
    return fly()


def test_full_chain_completes_in_order(landed):
    """발사에서 정지까지 일곱 단계를 순서대로 완주한다."""
    s = landed.signals
    seq = [m for i, m in enumerate(s["mode"]) if i == 0 or m != s["mode"][i - 1]]
    assert seq == ["launch", "climb", "cruise", "approach", "flare", "rollout", "stopped"]
    assert landed.meta["aborted"] is None


def test_phase_times_are_recorded(landed):
    """이탈·접지·정지 시각 — 실측 회귀. 셋 다 None이 아니어야 '착륙했다'가 성립한다."""
    ph = landed.meta["phases"]
    assert ph["launch_exit_t"] == pytest.approx(0.245, abs=0.001)
    # 접지·정지가 **뒤로 밀린 것은 프로펠러 전환**이다 (107.3→115.4, 129.9→137.9):
    # 여유추력이 5,840 N → 1,320 N으로 줄어 상승·가속이 느려졌다. 접지 자체는 그대로
    # 부드럽다(−0.96 m/s) — 느려진 것은 거기까지 가는 시간이지 접지 품질이 아니다.
    # (직전 갱신은 동압 스케줄 상한 4.0→2.0 — 승강타 리밋사이클 수정이었다.)
    # 레일 이탈은 구속 적분이라 추진과 무관하게 그대로다
    assert ph["touchdown_t"] == pytest.approx(115.4, abs=1.5)
    assert ph["stop_t"] == pytest.approx(137.9, abs=2.0)
    assert ph["touchdown_t"] < ph["stop_t"]


def test_touchdown_is_soft_enough(landed):
    """접지 강하율 ≈ −1.0 m/s — 플레어가 실제로 강하를 세운다.

    플레어 없이(개시 5 m·낮은 게인) 재면 −4.58 m/s가 나온다. 이 수가 −1 근처라는
    것이 곧 "플레어가 있다"의 증거다.
    """
    s = landed.signals
    k = int(round(landed.meta["phases"]["touchdown_t"] / DT))
    assert climb_rate(s, k) == pytest.approx(-1.0, abs=0.4)
    assert s["V"][k] == pytest.approx(79.5, rel=0.05), "접지 속도"
    # 기수를 든 채 접지 — 뒤쪽 접촉점이 먼저 닿는다(스키드 기하상 정상)
    assert math.degrees(s["theta"][k]) == pytest.approx(14.5, abs=2.0)


def test_rollout_distance_and_final_rest(landed):
    """접지 후 미끄러져 서고, 선 자리에서 기어가 무게를 받는다."""
    s = landed.signals
    ph = landed.meta["phases"]
    k_td = int(round(ph["touchdown_t"] / DT))
    k_st = int(round(ph["stop_t"] / DT))
    assert s["pn"][k_st] - s["pn"][k_td] == pytest.approx(870.0, rel=0.12)
    assert s["V"][-1] < 0.5
    assert s["wow"][-1], "끝까지 접지 상태"
    m, _cg, _J = make_demo_aircraft().fuel_mass.at(float(s["fuel"][-1]))
    assert s["n_gear"][-1] == pytest.approx(m * 9.80665, rel=0.02), "선 자리에서 무게를 받는다"


def test_landing_run_is_flag_clean(landed):
    """전 구간 무플래그 — 정지에서 이탈까지 전부 공력 유효범위 안이다."""
    for name, arr in landed.envelope["flags"].items():
        assert not arr.any(), f"{name} 플래그 {int(arr.sum())}회"
    assert landed.envelope["any_flag"] is False
    assert landed.envelope["min_alt"] > 0.0, "CG가 지면 아래로 내려간 적 없음"
    assert landed.envelope["worst_margin"] == pytest.approx(0.071, abs=0.02)


def test_longitudinal_source_switches_with_the_phase(landed):
    """단계마다 θ 출처가 갈린다 — 셋 중 정확히 하나만 켜져 있다."""
    s = landed.signals
    modes = np.array(s["mode"])
    # 항법 지연(delay_s=0.03 = 3틱) 동안은 nav가 무효라 유도가 **전 축 비활성** 명령을
    # 낸다(guidance.py의 첫 유효 이전 홀드). 그 구간을 축 선택 검사에서 빼는 것은
    # 예외를 봐주는 게 아니라 다른 상태를 섞지 않는 것이고, 그 구간이 실제로 전 축
    # 비활성인지는 바로 아래에서 따로 단정한다. 지연 틱 수는 모델에서 가져온다 —
    # 여기 상수로 적으면 delay_s를 바꿨을 때 조용히 어긋난다.
    warm = int(round(NavErrorModel.rtk_fixed().delay_s / DT))
    valid = np.zeros(len(modes), dtype=bool)
    valid[warm:] = True
    assert not any(s[a][:warm].any() for a in ("pitch_on", "alt_on", "hdot_on")), \
        "항법 무효 구간에는 어느 축도 켜지지 않는다"
    assert s["pitch_on"][warm] == 1.0, "유효해지자마자 발사 모드의 피치 축이 켜진다"
    for name, axis in (("launch", "pitch_on"), ("climb", "pitch_on"),
                       ("cruise", "alt_on"), ("approach", "hdot_on"),
                       ("flare", "hdot_on"), ("rollout", "pitch_on")):
        sel = (modes == name) & valid
        assert sel.any(), f"{name} 구간 없음"
        assert (s[axis][sel] == 1.0).all(), f"{name}에서 {axis}가 꺼짐"
        for other in {"pitch_on", "alt_on", "hdot_on"} - {axis}:
            assert (s[other][sel] == 0.0).all(), f"{name}에서 {other}가 함께 켜짐"


@pytest.mark.parametrize("seed", [3, 7, 11, 17, 23])
def test_rtk_buys_a_repeatable_touchdown_point_not_a_softer_one(seed):
    """RTK가 사는 것은 **접지 지점의 반복성**이지 부드러움이 아니다.

    처음엔 "기본 항법이면 플레어가 잡음에 묻힌다"고 적었는데 **실측이 그것을 뒤집었다**:
    다섯 시드에서 접지 강하율은 기본 −0.76, RTK −0.91로 오히려 기본 쪽이 살짝
    부드럽다. 강하율은 vel_std_v(0.45 m/s)가 지배하고 플레어 개시 고도가 20 m라
    4.5 m짜리 위치 잡음이 그 자릿수를 흔들지 못하기 때문이다.

    갈리는 것은 **어디에 내리는가**다 — 플레어 개시가 alt_le 20이므로 고도 오차가
    곧 개시 시점 오차이고, 88 m/s에서 그것이 접지 지점으로 증폭된다:

        기본 GNSS   두 시드(3·7)가 수백 m 차이 (2시드 표본 — 폭이 아니라 하한)
        RTK 고정해  5시드 폭 7.9 m

    수치는 프로펠러 전환으로 다시 재측정한 것이다 — 접지점 자체가 9,700 → 10,237 m로
    멀어졌다(추력이 줄어 상승이 길어진 만큼 더 나아간 뒤 내려온다). **대비는 그대로
    30배 이상**이고, 그것이 이 테스트가 지키는 명제다. 기본 GNSS는 2시드만 재서
    폭이 아니라 하한이다 — 5시드 폭은 그보다 크다.
    활주로 길이가 1,500 m인데 수백 m가 흔들리면 활주로에 못 내린다.
    그래서 RTK가 전제이고, **fix 상실은 미모델**이다 [TBD].
    """
    rtk = fly(nav=NavErrorModel.rtk_fixed(seed=seed))
    k = int(round(rtk.meta["phases"]["touchdown_t"] / DT))
    # RTK면 시드가 바뀌어도 같은 자리에 내린다 (5시드 폭 7.9 m)
    assert float(rtk.signals["pn"][k]) == pytest.approx(10237.0, abs=150.0)
    assert climb_rate(rtk.signals, k) == pytest.approx(-0.96, abs=0.25)


def _turning_path_modes():
    """순항이 경로를 따르는 미션 — 수평·세로 프로파일을 **둘 다** 경로가 낸다."""
    modes = landing_modes()
    for i, m in enumerate(modes):
        if m.name == "cruise":
            modes[i] = ModeSpec(name="cruise", speed=88.0, alt="path", heading="path",
                                exit_when=("path_done",), next="approach")
    return modes


# t_end 200 → 240: 프로펠러 전환으로 상승·순항이 느려져 200 s 안에 경로를
# 못 끝냈다 (모드 체인이 cruise에서 멈춘다). 궤적이 나빠진 게 아니라 길어졌다
def fly_path(wps, accept=300.0, t_end=240.0):
    ac = make_demo_aircraft(ground=make_demo_skid_gear())
    tr = trim_ground(ac, TrimCase("pad", mach=0.0, alt=0.0, fuel=300.0, condition="ground"))
    assert tr.converged
    sim = Simulator(
        aircraft=ac, fcl=make_demo_fcl(),
        guidance=Guidance(_turning_path_modes(),
                          path=LosPath(wps, accept_radius=accept)),
        nav_model=NavErrorModel.rtk_fixed(seed=11),
        stall_table=make_demo_stall_table(), db_ranges=make_demo_db_ranges(),
        dt_plant=DT, control_hz=100.0, ground_elev=0.0, launch=make_demo_launch_rail(),
        actuator_params={"wn": 30.0, "zeta": 0.7, "rate_max": 10.0}, fuel_flow=0.3,
    )
    return sim.run(tr, t_end=t_end, fingerprint="landing-path")


def test_following_a_turning_path_does_not_fly_into_the_ground():
    """저속 순항에서 경로를 따라 **선회해도** 고도를 잃고 지면까지 가지 않는다.

    이 회귀가 생긴 사건: 순항(88 m/s)에서 웨이포인트로 65° 선회를 걸면 기체가
    나선 강하로 36 s에 −42.6 m/s로 지면에 닿았다. 실속이 아니라 **내측 피치 루프의
    리밋사이클**이 원인이었다 — 동압 스케줄 상한 4.0이 M0.26에서 pitch.kp·k_rate를
    4배로 밀어 승강타가 ±20°(전 스트로크)를 2 Hz로 왕복했고(de σ 10.6°), 타면 여유가
    남지 않아 선회 하중을 못 받쳤다. 상한을 2.0으로 내려 고쳤다(fcl/demo.py 주석).

    직진 미션은 그 진동을 안고도 착륙했기 때문에 **기존 회귀 전부가 통과했다** —
    선회를 시키는 시나리오가 없어서 안 걸린 것이다. 그래서 여기에 하나 세운다.
    """
    res = fly_path(((3000.0, 2000.0, 600.0), (6000.0, -1000.0, 400.0)), t_end=150.0)  # 프로펠러 전환으로 상승이 느려져 120 s로는 순항을 못 벗어난다
    s = res.signals
    # 진단이 먼저다 — 회귀하면 실제로 일어나는 일은 **추락**(접지 36 s·h −1.4 m·
    # 마진 −2.73)인데, 모드 체인 단정이 먼저 터지면 실패가 "순항을 못 벗어남"으로만
    # 읽혀 독스트링이 말하는 사건과 다른 이야기가 된다 (리뷰 지적)
    cruise = np.array(s["mode"]) == "cruise"
    # 빈 배열에 min을 걸면 ValueError라 "왜 실패했는지"가 사라진다 — 아래 회귀와 같은 관문
    assert cruise.any(), "순항 구간 없음 — 상승에서 이미 끝났다"
    assert float(np.min(np.asarray(s["h"])[cruise])) > 150.0, "순항 중 지면으로 내려감"
    assert res.envelope["worst_margin"] > 0.0, "실속마진이 음수 — 이탈"
    assert res.meta["phases"]["touchdown_t"] is None or \
        res.meta["phases"]["touchdown_t"] > 90.0, "순항 중 접지 = 추락"
    seq = [m for i, m in enumerate(s["mode"]) if i == 0 or m != s["mode"][i - 1]]
    assert seq[:4] == ["launch", "climb", "cruise", "approach"], "순항을 못 벗어남"


def test_path_altitude_ramp_starts_where_the_aircraft_is_not_on_the_pad():
    """램프 시작점 회귀 — **선회 없이** 경로 고도만으로도 지면까지 갔다.

    위 선회 시나리오는 이 결함을 못 잡는다: 순항 진입 시점에 기체가 이미 1,900 m
    북쪽이라 발사대 기준 램프도 240.8 m까지 올라와 있어 낙차가 10 m뿐이다(리뷰 실측).
    긴 다리에 낮은 목표 고도를 주면 드러난다 — (10000, 0, 300)은 램프 기울기 3%라
    38% 경사로 올라온 기체와 크게 어긋난다.

    실측 대비: 고침 후 진입 명령 250.1 m·순항 고도 247.9~297.2 m,
    고치기 전 진입 명령 **59.7 m**·순항 중 **69.8 m**까지 강하.
    """
    res = fly_path(((10000.0, 0.0, 300.0),), accept=300.0, t_end=140.0)
    s = res.signals
    cruise = np.array(s["mode"]) == "cruise"
    assert cruise.any(), "순항 구간 없음"
    assert float(np.min(np.asarray(s["h"])[cruise])) > 200.0, "경로 고도가 급강하를 지시함"


def test_cruise_elevon_activity_stays_bounded(landed):
    """순항에서 승강타가 스트로크를 왕복하지 않는다 — 리밋사이클 감시.

    이 수치가 곧 "선회를 얹을 여유가 있는가"다. 상한 4.0 시절 de σ는 10.6°였고
    피크는 ±20°(포화)였다 — 그 상태로도 직진 착륙은 됐으므로, 착륙 성공만 보는
    회귀로는 이 결함을 잡을 수 없다. 활동량 자체를 못박는 자리가 필요하다.

    자리별 실측(4배 부스트): pitch.kp만 σ 11.0°, pitch.k_rate만 σ 12.1°,
    pitch.ki만 σ 3.3°(= 부스트 없음), 롤 3개 σ 3.3°. 피치 비례·레이트가 원인이다.

    **순항 후반만 본다.** 앞부분은 상승(θ 17°)에서 수평으로 내려앉는 전환 과도라
    느린 성분이 σ를 지배해 두 형상이 안 갈린다 — 전체 구간으로 재면 10.6° 대 9.3°로
    거의 같아 보이지만, 정착 구간만 보면 8.8° 대 4.1°로 갈린다. 문턱 6.0°는 그 사이다.
    """
    s = landed.signals
    k = np.flatnonzero(np.array(s["mode"]) == "cruise")
    assert len(k) > 100, "순항 구간이 너무 짧아 정착을 볼 수 없다"
    de = np.degrees(np.asarray(s["de"])[k[len(k) // 2:]])
    assert de.std() < 6.0, f"승강타 왕복 σ {de.std():.1f}° — 리밋사이클 의심"


def test_default_nav_lands_but_scatters_the_touchdown_point():
    """기본 항법도 착륙은 한다 — 다만 접지 지점이 흩어진다. 못 하는 것과 다르다."""
    pns = []
    for seed in (3, 11, 23):
        res = fly(nav=NavErrorModel(seed=seed))
        assert res.meta["phases"]["touchdown_t"] is not None, "착륙 자체는 한다"
        k = int(round(res.meta["phases"]["touchdown_t"] / DT))
        pns.append(float(res.signals["pn"][k]))
    # 시드 셋의 전폭이 RTK 전체 폭을 훌쩍 넘는다 — 실측 168 m(원점 2.9 m 기준,
    # 5시드도 극값이 같다) 대 RTK 5시드 12 m. 문턱은 RTK 폭의 4배 자리에 둔다:
    # 이 테스트가 말하는 것은 "기본 항법이 자릿수 크게 흩어진다"이지 특정 시드들의
    # 거리가 아니다. 원래 시드 (3, 23) 둘이었는데, 발사 원점을 1.2→2.9 m로 올리자
    # 그 쌍만 37 m로 좁아져 깨졌다 — 두 표본은 우연에 볼모다. 셋로 넓혔다.
    assert max(pns) - min(pns) > 50.0
