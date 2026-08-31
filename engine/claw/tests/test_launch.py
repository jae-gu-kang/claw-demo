"""M11 발사 레일 구간 + 지면 결선 검증 (01 §3.3.1 이륙).

레일은 힘이 아니라 구속이다 — RK4를 타지 않고 등가속 해석해로 전진한다.
여기서 못박는 것은 (a) 구속 구간이 해석해와 일치하는가, (b) 이탈 시각이 스텝
경계에 없을 때 손실 없이 넘어가는가, (c) 레일이 받치는 동안 기어가 받는 것처럼
기록되지 않는가 — 셋 다 화면이 사실을 말하려면 필요한 것들이다.
"""

import math

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.fcl import make_demo_fcl
from claw.guidance import Guidance, ModeSpec
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_launch_rail,
    make_demo_skid_gear,
    make_demo_stall_table,
)
from claw.sim import Simulator
from claw.trim import trim_ground, trim_level

DT = 0.01


def _sim(t_end=40.0, launch=True, ground=True):
    gear = make_demo_skid_gear() if ground else None
    ac = make_demo_aircraft(ground=gear)
    rail = make_demo_launch_rail() if launch else None
    # 기어가 없으면 지상 평형이 성립하지 않는다(받칠 것이 없다) — 비행 트림에서 출발
    tr = (
        trim_ground(ac, TrimCase("pad", mach=0.0, alt=0.0, fuel=300.0, condition="ground"))
        if ground
        else trim_level(ac, TrimCase("air", mach=0.4, alt=1000.0, fuel=300.0))
    )
    assert tr.converged
    modes = [ModeSpec(name="climb", speed=110.0, alt=300.0, heading=0.0,
                      exit_when=("time_ge", 1e9))]
    sim = Simulator(
        aircraft=ac, fcl=make_demo_fcl(), guidance=Guidance(modes),
        stall_table=make_demo_stall_table(), db_ranges=make_demo_db_ranges(),
        dt_plant=DT, control_hz=100.0, ground_elev=0.0, launch=rail,
    )
    return rail, sim.run(tr, t_end=t_end, fingerprint="launch-test")


@pytest.fixture(scope="module")
def launched():
    return _sim()


def test_rail_run_matches_the_closed_form(launched):
    """레일 구간의 속도·거리가 등가속 해석해와 일치 — 적분 근사가 아니다."""
    rail, res = launched
    t, s = res.t, res.signals
    on = s["on_rail"]
    assert on[0], "t=0에는 레일 위"
    for k in np.flatnonzero(on):
        tk = float(t[k])
        assert s["V"][k] == pytest.approx(rail.accel * tk, rel=1e-9, abs=1e-9)
        # 자세는 레일이 잡는다 — 앙각 고정, 롤·요 없음
        assert s["theta"][k] == pytest.approx(rail.elev_angle, abs=1e-12)
        assert s["phi"][k] == pytest.approx(0.0, abs=1e-12)
        assert s["q"][k] == pytest.approx(0.0, abs=1e-12)
        # 레일에 물려 있으므로 속도는 동체 x축뿐 → α = 0
        assert s["alpha"][k] == pytest.approx(0.0, abs=1e-12)


def test_exit_lands_between_steps_without_losing_speed(launched):
    """이탈 시각(0.2454 s)은 스텝 경계에 없다 — 남은 시간만 자유비행으로 적분한다.

    다음 경계까지 통째로 레일에 두면 최대 dt만큼 늦게 놓여 81.5 m/s에서 0.8 m가
    밀린다. 이탈 직후 표본의 속도가 이탈 속도와 같은 자리에 있어야 한다.
    """
    rail, res = launched
    t, s = res.t, res.signals
    assert rail.exit_time % DT != 0.0, "이 테스트의 전제 — 이탈이 경계에 떨어지지 않는다"
    i = int(np.searchsorted(t, rail.exit_time))
    assert s["on_rail"][i - 1] and not s["on_rail"][i]
    assert s["V"][i - 1] < rail.exit_speed
    # 이탈 후 첫 표본은 이탈 상태에서 (t_i − exit_time)만큼만 자유비행한 것
    assert s["V"][i] == pytest.approx(rail.exit_speed, rel=2e-3)
    assert res.meta["phases"]["launch_exit_t"] == pytest.approx(rail.exit_time)


def test_rail_carries_the_aircraft_not_the_gear(launched):
    """레일 구간에 wow가 서면 거짓이다 — 받치는 것은 레일이지 스키드가 아니다."""
    _rail, res = launched
    s = res.signals
    assert not s["wow"][s["on_rail"]].any()
    # 레일 원점 높이가 접촉점을 지면 위에 띄운다 (0으로 두면 0.55 m 파묻힌 채 출발)
    assert res.signals["h"][0] == pytest.approx(1.2)
    assert res.envelope["min_alt"] >= 0.0, "지면 아래로 내려간 적 없음"


def test_launch_load_is_recorded_only_on_the_rail(launched):
    """사출 하중은 레일 위에서만 — 이탈 후 0은 '가속 없음'이지 미계측이 아니다."""
    rail, res = launched
    s = res.signals
    on = s["on_rail"]
    assert np.allclose(s["launch_gx"][on], rail.launch_gx)
    assert np.allclose(s["launch_gx"][~on], 0.0)
    assert rail.launch_gx == pytest.approx(33.9, abs=0.1)


def test_launch_run_is_flag_clean(launched):
    """이착륙 속도대가 유효범위 안이라 발사 구간에 플래그가 서지 않는다.

    마하 하한이 0.1이던 때는 0→34 m/s 구간 전체가 "DB 범위 밖"이었다 —
    엔벨로프 요약이 상시 참이 되어 볼 수 없는 화면이 된다.
    """
    _rail, res = launched
    assert res.meta["aborted"] is None
    for name, arr in res.envelope["flags"].items():
        assert not arr.any(), f"{name} 플래그 발생"
    assert res.envelope["any_flag"] is False


def test_launch_reaches_commanded_climb(launched):
    """이탈 후 실제로 난다 — 지령 고도 300 m·속도 110 m/s로 붙는다."""
    _rail, res = launched
    s = res.signals
    assert s["h"][-1] == pytest.approx(300.0, rel=0.15)
    assert s["V"][-1] == pytest.approx(110.0, rel=0.05)


def test_without_launch_nothing_changes(launched):
    """레일 미장착이면 단계 시각이 전부 None이고 지상에서 출발한다."""
    _rail, res = _sim(t_end=2.0, launch=False)
    assert res.meta["phases"] == {
        "launch_exit_t": None, "touchdown_t": None, "stop_t": None,
    }
    assert not res.signals["on_rail"].any()
    assert res.signals["wow"][0], "지상 평형에서 출발하므로 처음부터 접지"


def test_gear_absent_reports_unmeasured_not_zero():
    """착륙장치가 없으면 반력은 NaN — 0이면 '닿았는데 반력 0'과 구분되지 않는다."""
    _rail, res = _sim(t_end=1.0, launch=False, ground=False)
    assert np.isnan(res.signals["n_gear"]).all()
    assert not res.signals["wow"].any()
    assert res.meta["phases"]["touchdown_t"] is None


# ---- 단계 시각 판정 (합성 신호로 직접) ----


def _phase_times(sig, n, ground=True):
    gear = make_demo_skid_gear() if ground else None
    sim = Simulator(
        aircraft=make_demo_aircraft(ground=gear), fcl=make_demo_fcl(),
        guidance=Guidance([ModeSpec(name="m", exit_when=("time_ge", 1e9))]),
        dt_plant=DT, control_hz=100.0,
    )
    return sim._phase_times(np.arange(n) * DT, sig, None)


def test_touchdown_and_stop_are_found_in_order():
    n = 10
    sig = {
        "wow": np.array([0, 0, 0, 1, 1, 1, 1, 1, 1, 1], dtype=bool),
        "V": np.array([80.0, 70, 60, 50, 40, 20, 5, 0.4, 0.2, 0.1]),
    }
    out = _phase_times(sig, n)
    assert out["touchdown_t"] == pytest.approx(0.03)
    assert out["stop_t"] == pytest.approx(0.07)


def test_never_landing_reports_none_not_zero():
    """0으로 채우면 't=0에 접지'가 되어 착륙하지 않은 런이 완벽한 착륙으로 읽힌다."""
    n = 5
    sig = {"wow": np.zeros(n, dtype=bool), "V": np.full(n, 90.0)}
    out = _phase_times(sig, n)
    assert out["touchdown_t"] is None
    assert out["stop_t"] is None


def test_starting_on_the_ground_is_not_a_touchdown():
    n = 5
    sig = {"wow": np.ones(n, dtype=bool), "V": np.zeros(n)}
    assert _phase_times(sig, n)["touchdown_t"] is None


def test_touchdown_without_stopping_reports_no_stop():
    """접지했지만 아직 안 멈췄으면 정지 시각은 None — 미래를 지어내지 않는다."""
    n = 6
    sig = {
        "wow": np.array([0, 0, 1, 1, 1, 1], dtype=bool),
        "V": np.array([80.0, 78, 76, 60, 40, 30]),
    }
    out = _phase_times(sig, n)
    assert out["touchdown_t"] == pytest.approx(0.02)
    assert out["stop_t"] is None


def test_ground_elev_validation():
    with pytest.raises(ValueError, match="ground_elev"):
        Simulator(
            aircraft=make_demo_aircraft(), fcl=make_demo_fcl(),
            guidance=Guidance([ModeSpec(name="m", exit_when=("time_ge", 1e9))]),
            ground_elev=math.inf,
        )
    with pytest.raises(ValueError, match="LaunchRail"):
        Simulator(
            aircraft=make_demo_aircraft(), fcl=make_demo_fcl(),
            guidance=Guidance([ModeSpec(name="m", exit_when=("time_ge", 1e9))]),
            launch=object(),
        )


# ---- 피치 지령으로 발사 구성 잡기 (사용자 제기) ----


def _pitch_launch(t_end=40.0):
    """레일 위에서 **엘러본 상향**으로 자리잡고 이탈하는 발사 — 종방향 피치 축 사용."""
    gear = make_demo_skid_gear()
    ac = make_demo_aircraft(ground=gear)
    rail = make_demo_launch_rail()
    tr = trim_ground(ac, TrimCase("pad", mach=0.0, alt=0.0, fuel=300.0, condition="ground"))
    modes = [
        ModeSpec(name="launch", speed=110.0, pitch=math.radians(21.0), heading=0.0,
                 exit_when=("off_rail",), next="climb"),
        ModeSpec(name="climb", speed=110.0, pitch=math.radians(21.0), heading=0.0,
                 exit_when=("alt_ge", 150.0), next="cruise"),
        ModeSpec(name="cruise", speed=110.0, alt=300.0, heading=0.0,
                 exit_when=("time_ge", 1e9)),
    ]
    sim = Simulator(
        aircraft=ac, fcl=make_demo_fcl(), guidance=Guidance(modes),
        stall_table=make_demo_stall_table(), db_ranges=make_demo_db_ranges(),
        dt_plant=DT, control_hz=100.0, ground_elev=0.0, launch=rail,
    )
    return rail, sim.run(tr, t_end=t_end, fingerprint="pitch-launch")


@pytest.fixture(scope="module")
def pitch_launched():
    return _pitch_launch()


def test_elevons_sit_trailing_edge_up_on_the_rail(pitch_launched):
    """무미익에서 "플랩 역할"은 **상향(리플렉스)**이 한다 (사용자 제기).

    하향은 Cm_δe(−1.0)이 CL_δe(+0.4)를 압도해 기수를 내리고 트림 α를 깎지만,
    상향은 기수를 들어 α를 키우고 3.5α가 0.4δe 손실을 이긴다. 레일 위에서
    자세는 구속돼 있으므로 타면이 하는 일은 **이탈 직후를 준비하는 것**이다.
    피치 축이 없던 때는 고도 루프가 기수 내림(δe +0.31)을 물고 이탈했다.
    """
    _rail, res = pitch_launched
    s = res.signals
    on = s["on_rail"]
    assert (s["de"][on] < -0.25).all(), "레일 구간 내내 엘러본이 상향이어야 함"
    i = int(np.flatnonzero(on)[-1])
    assert s["de"][i] < 0.0, "이탈 직전 타면이 기수 올림 쪽"


def test_pitch_axis_is_the_theta_source_on_the_rail(pitch_launched):
    """θ가 어디서 왔는지 화면이 말할 수 있어야 한다 — 출처를 계측한다."""
    _rail, res = pitch_launched
    s = res.signals
    on = s["on_rail"]
    assert (s["pitch_on"][on] == 1.0).all()
    assert (s["hdot_on"][on] == 0.0).all()
    assert (s["alt_on"][on] == 0.0).all()
    # 피치 지령 21°는 축 한계 0.3 rad(17.2°)로 잘린다 — 잘린 값이 곧 θ 출처
    assert np.allclose(s["ap_theta_pitch"][on], 0.3)
    assert np.allclose(s["ap_theta_src"][on], 0.3)
    assert np.allclose(s["theta_cmd"][on], 0.3)


def test_off_rail_switches_the_mode_without_restating_the_rail(pitch_launched):
    """레일 이탈이 곧 모드 전이 — 모드표가 0.245 s를 다시 적지 않는다.

    airborne으로는 이걸 못 한다: 레일이 받치는 동안 기어는 닿지 않아 airborne이
    t=0부터 참이다(그때는 첫 스텝에 바로 넘어가 버린다).
    """
    rail, res = pitch_launched
    s, t = res.signals, res.t
    seq = [m for i, m in enumerate(s["mode"]) if i == 0 or m != s["mode"][i - 1]]
    assert seq == ["launch", "climb", "cruise"]
    # launch → climb 전이가 레일 이탈 시각과 같은 스텝에서 일어난다
    first_climb = int(np.flatnonzero(np.array(s["mode"]) == "climb")[0])
    assert not s["on_rail"][first_climb]
    assert s["on_rail"][first_climb - 1]
    assert t[first_climb] == pytest.approx(rail.exit_time, abs=DT)


def test_pitch_launch_climbs_out_cleanly(pitch_launched):
    _rail, res = pitch_launched
    s = res.signals
    assert res.meta["aborted"] is None
    assert res.envelope["any_flag"] is False
    assert res.envelope["min_alt"] >= 1.0, "발사대 높이 아래로 내려간 적 없음"
    assert s["h"][-1] == pytest.approx(300.0, rel=0.15)
