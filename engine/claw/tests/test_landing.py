"""이륙~착륙 전장 시나리오 (01 §3.3.1) — 발사→상승→순항→접근→플레어→접지→정지.

**순항 회귀(test_mission)는 그대로 남는다.** 그쪽은 지면 모델을 장착하지 않은
시나리오라 여전히 해수면 아래로 내려가고, 그 사실을 고정한 단정도 살아 있다.
이 파일은 그 옆에 신설한 것이고, 여기서 못박는 것은 "착륙이 실제로 된다"는 것과
그때의 실측 수치다.

전제 하나를 명시한다 — **RTK 고정해**. 다만 그 이유는 처음 적었던 것과 다르다:
실측해 보니 접지 강하율은 항법 등급과 거의 무관하고(σ 0.07로 동일), 갈리는 것은
**접지 지점**이다 — 기본 GNSS 874 m 폭, RTK 92 m 폭. 활주로가 1,500 m이므로
그 산포가 곧 "활주로에 내리느냐"를 가른다.
test_rtk_buys_a_repeatable_touchdown_point_not_a_softer_one이 그 대비를 담는다.
"""

import math

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.fcl import make_demo_fcl
from claw.guidance import Guidance, ModeSpec
from claw.nav import NavErrorModel
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


def sink_rate(sig, k):
    """접지 순간의 승강률 [m/s] — 동체축 속도를 자세로 회전해 NED 상방 성분."""
    return float(sig["u"][k] * math.sin(sig["theta"][k]) - sig["w"][k] * math.cos(sig["theta"][k]))


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
    assert ph["touchdown_t"] == pytest.approx(110.1, abs=1.0)
    assert ph["stop_t"] == pytest.approx(132.8, abs=2.0)
    assert ph["touchdown_t"] < ph["stop_t"]


def test_touchdown_is_soft_enough(landed):
    """접지 강하율 ≈ −1.0 m/s — 플레어가 실제로 강하를 세운다.

    플레어 없이(개시 5 m·낮은 게인) 재면 −4.58 m/s가 나온다. 이 수가 −1 근처라는
    것이 곧 "플레어가 있다"의 증거다.
    """
    s = landed.signals
    k = int(round(landed.meta["phases"]["touchdown_t"] / DT))
    assert sink_rate(s, k) == pytest.approx(-1.0, abs=0.4)
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
    다섯 시드에서 접지 강하율은 기본 −0.72, RTK −0.89로 오히려 기본 쪽이 살짝
    부드럽고 산포(σ 0.07)는 같다. 강하율은 vel_std_v(0.45 m/s)가 지배하고 플레어
    개시 고도가 20 m라 4.5 m짜리 위치 잡음이 그 자릿수를 흔들지 못하기 때문이다.

    갈리는 것은 **어디에 내리는가**다 — 플레어 개시가 alt_le 20이므로 고도 오차가
    곧 개시 시점 오차이고, 88 m/s에서 그것이 접지 지점으로 증폭된다:

        기본 GNSS   접지 지점 폭 874 m (σ 344 m)
        RTK 고정해  접지 지점 폭  92 m (σ  33 m)

    활주로 길이가 1,500 m인데 ±437 m가 흔들리면 활주로에 못 내린다. 그래서 RTK가
    전제이고, **fix 상실은 미모델**이라는 것도 함께 적어야 한다 [TBD].
    """
    rtk = fly(nav=NavErrorModel.rtk_fixed(seed=seed))
    k = int(round(rtk.meta["phases"]["touchdown_t"] / DT))
    # RTK면 시드가 바뀌어도 같은 자리에 내린다 (5시드 실측 9902~9995 m)
    assert float(rtk.signals["pn"][k]) == pytest.approx(9957.0, abs=150.0)
    assert sink_rate(rtk.signals, k) == pytest.approx(-0.89, abs=0.25)


def test_default_nav_lands_but_scatters_the_touchdown_point():
    """기본 항법도 착륙은 한다 — 다만 접지 지점이 흩어진다. 못 하는 것과 다르다."""
    pns = []
    for seed in (3, 23):
        res = fly(nav=NavErrorModel(seed=seed))
        assert res.meta["phases"]["touchdown_t"] is not None, "착륙 자체는 한다"
        k = int(round(res.meta["phases"]["touchdown_t"] / DT))
        pns.append(float(res.signals["pn"][k]))
    # 이 두 시드만으로도 RTK 전체 폭(92 m)을 훌쩍 넘는다
    assert abs(pns[0] - pns[1]) > 300.0
