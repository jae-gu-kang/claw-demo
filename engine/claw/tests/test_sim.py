"""M11 sim 검증 — 멀티레이트 스케줄러, 조립 루트 폐루프, 엔벨로프 감시, 계보.

조립: plant(쿼터니언 경로 RigidBody+RK4) + nav(오차 모델/이상) + guidance +
fcl — 전부 03 §4 계약으로만 연결. 트림 유지·고도 캡처는 회귀 수치 고정.
"""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.fcl import make_demo_fcl
from claw.guidance import Guidance, ModeSpec
from claw.nav import NavErrorModel
from claw.plant import make_demo_aircraft, make_demo_db_ranges, make_demo_stall_table
from claw.sim import Simulator
from claw.trim import trim_level

DB_RANGES = make_demo_db_ranges()


@pytest.fixture(scope="module")
def trim_design():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    return ac, tr


def hold_modes(V0, alt=1000.0):
    return [ModeSpec(name="hold", speed=V0, alt=alt, heading=0.0,
                     exit_when=("time_ge", 1e9))]


def make_sim(ac, tr, *, modes=None, nav_model=None, dt_plant=0.01, control_hz=100.0,
             actuator_params=None, min_altitude=0.0):
    V0 = float(np.linalg.norm(tr.state.vel_b))
    g = Guidance(modes if modes is not None else hold_modes(V0, tr.case.alt))
    return Simulator(
        aircraft=ac,
        fcl=make_demo_fcl(),
        guidance=g,
        nav_model=nav_model,
        stall_table=make_demo_stall_table(),
        db_ranges=DB_RANGES,
        dt_plant=dt_plant,
        control_hz=control_hz,
        actuator_params=actuator_params,
        min_altitude=min_altitude,
    )


def test_rate_ratio_validation(trim_design):
    ac, tr = trim_design
    with pytest.raises(ValueError):
        make_sim(ac, tr, dt_plant=0.02, control_hz=100.0)  # 플랜트가 제어보다 느림
    with pytest.raises(ValueError):
        make_sim(ac, tr, dt_plant=0.004, control_hz=150.0)  # 비정수배


def test_trim_hold_straight_level(trim_design):
    """트림 시작 + 유지 명령 → 20 s 정상수평비행 유지 (조립 정합성의 기준선)."""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    res = make_sim(ac, tr).run(tr, t_end=20.0, fingerprint="fp-sim")
    h = res.signals["h"]
    assert np.max(np.abs(h - 1000.0)) < 5.0
    assert np.max(np.abs(res.signals["V"] - V0)) < 2.0
    assert np.max(np.abs(res.signals["phi"])) < 0.01
    assert res.envelope["worst_margin"] > 0.2  # 실속 여유 충분
    assert not res.envelope["any_flag"]
    assert res.params_fingerprint == "fp-sim"
    assert res.meta["control_hz"] == 100.0 and res.meta["dt_plant"] == 0.01
    assert len(res.t) == len(h) == int(20.0 / 0.01)


def test_control_zoh_between_control_ticks(trim_design):
    """dt_plant=5 ms·제어 100 Hz → 타면 명령이 제어 틱 사이 ZOH (멀티레이트)."""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    res = make_sim(ac, tr, modes=hold_modes(V0, 1015.0), dt_plant=0.005).run(tr, t_end=4.0)
    de = res.signals["de"]
    assert np.allclose(de[0::2], de[1::2])  # 부틱 쌍 동일 (ZOH)
    assert np.std(de) > 1e-6  # 고도 명령 변화로 실제 타면 활동 존재


def test_nav_error_model_closed_loop_multirate(trim_design):
    """항법 50 Hz·지연 30 ms·잡음 — 폐루프 유지 + 지연 구간 홀드 (valid=False)."""
    ac, tr = trim_design
    nav = NavErrorModel(pos_std_h=1.0, pos_std_v=1.0, vel_std_h=0.1, vel_std_v=0.1,
                        att_std=0.001, psi_std=0.002,
                        rate_std=0.0005, bias_std_h=0.5, bias_std_v=0.5, bias_tau=60.0,
                        delay_s=0.03, update_hz=50.0, seed=7)
    res = make_sim(ac, tr, nav_model=nav, dt_plant=0.01).run(tr, t_end=30.0)
    de0 = float(tr.control.elevon[0])
    # 지연 릴리스 전(t<0.03) 항법 invalid → FCL 웜스타트 홀드
    assert np.allclose(res.signals["de"][:3], de0)
    # 항법 오차 하 유지 성능 (발산 없음, 잡음성 방황 허용)
    assert np.max(np.abs(res.signals["h"] - 1000.0)) < 15.0
    assert np.max(np.abs(res.signals["phi"])) < 0.05
    assert not res.envelope["any_flag"]


def test_guidance_mission_alt_capture(trim_design):
    """상승 모드 → 순항 전환 미션: 고도 1000→1200 캡처, 모드 체인 완주."""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    modes = [
        ModeSpec(name="climb", speed=V0, alt=1200.0, heading=0.0,
                 exit_when=("alt_ge", 1180.0), next="cruise"),
        ModeSpec(name="cruise", speed=V0, alt=1200.0, heading=0.0,
                 exit_when=("time_ge", 1e9)),
    ]
    res = make_sim(ac, tr, modes=modes).run(tr, t_end=90.0)
    assert res.signals["mode"][0] == "climb"
    assert res.signals["mode"][-1] == "cruise"
    assert abs(res.signals["h"][-1] - 1200.0) < 10.0
    assert np.max(res.signals["h"]) < 1200.0 + 25.0  # 오버슈트 한도
    assert res.envelope["worst_margin"] > 0.15


def test_envelope_flag_fires_and_reports_first_time(trim_design):
    """DB 유효범위 이탈 플래그 (02 §6.1) — α 상한을 트림 α 아래로 조여 강제 발화."""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    sim = make_sim(ac, tr)
    sim.db_ranges = dict(DB_RANGES, alpha=(-0.2, 0.01))  # 트림 α≈0.043 > 0.01
    res = sim.run(tr, t_end=1.0)
    assert res.envelope["any_flag"]
    assert res.envelope["first_flag_t"] == pytest.approx(0.0, abs=0.02)
    assert bool(res.envelope["flags"]["alpha"][0])
    assert not np.any(res.envelope["flags"]["mach"])


def test_actuator_bank_in_the_loop(trim_design):
    """2차계 작동기(01 §2.4 [기본값]) 포함 폐루프 — 트림 웜스타트로 유지 성능 보전.

    rate_max=10 rad/s [기본값] — 데모 폐루프 스터디에서 3 rad/s는 항법
    지연·잡음과 결합해 피치·롤 리밋사이클 유발 (작동기 요구 사양 도출).
    """
    ac, tr = trim_design
    act = {"wn": 30.0, "zeta": 0.7, "rate_max": 10.0}
    res = make_sim(ac, tr, actuator_params=act).run(tr, t_end=10.0)
    assert np.max(np.abs(res.signals["h"] - 1000.0)) < 5.0
    assert np.max(np.abs(res.signals["phi"])) < 0.01


def test_actuator_params_validated_at_construction(trim_design):
    """작동기 파라미터 오류는 Simulator 생성 시점에 검출 — run()까지 지연 금지
    (M13 제출 시점 422 계약, 리뷰 M1)."""
    ac, tr = trim_design
    with pytest.raises(TypeError):
        make_sim(ac, tr, actuator_params={"unknown_key": 3.0})
    with pytest.raises(ValueError):
        make_sim(ac, tr, actuator_params={"wn": -5.0})
    with pytest.raises(ValueError):  # 예약 키 — 믹서 한계·트림 웜스타트가 결정
        make_sim(ac, tr, actuator_params={"pos_lo": -1.0})


def test_actuator_params_empty_dict_means_defaults(trim_design, monkeypatch):
    """빈 dict = 기본 파라미터로 실제 장착 (조용한 미장착 금지 — 리뷰 Nit)."""
    ac, tr = trim_design
    built = []
    orig = Simulator._make_actuators

    def spy(self, de0):
        built.append(de0)
        return orig(self, de0)

    monkeypatch.setattr(Simulator, "_make_actuators", spy)
    res = make_sim(ac, tr, actuator_params={}).run(tr, t_end=0.1)
    assert built, "작동기 뱅크가 실제로 조립되어야 함"
    assert res.meta["actuators"] is True


def test_meta_carries_effector_limits(trim_design):
    """판정 기준선(타면 위치 한계·작동기 rate)이 결과와 함께 다닌다.

    타각 듀티(analysis/duty.py)는 "얼마나 움직였나"뿐 아니라 "한계에 얼마나
    붙어 있었나"를 세는데, 한계값이 결과에 없으면 소비자가 파라미터를 따로
    들고 와 맞춰야 하고 어긋나면 조용히 틀린 포화율이 나온다.
    """
    ac, tr = trim_design
    res = make_sim(ac, tr, actuator_params={"rate_max": 4.0}).run(tr, t_end=0.1)
    lim = res.meta["limits"]
    mixer = make_demo_fcl().mixer
    assert lim["elevon_lo"] == pytest.approx(mixer.elevon_lo)
    assert lim["elevon_hi"] == pytest.approx(mixer.elevon_hi)
    assert lim["rudder_lo"] == pytest.approx(mixer.rudder_lo)
    assert lim["rate_max"] == pytest.approx(4.0)


def test_meta_rate_limit_is_none_without_actuators(trim_design):
    """미장착은 "rate 한계 무제한"이 아니라 "rate 한계 부재" — 0이 아닌 None."""
    ac, tr = trim_design
    res = make_sim(ac, tr, actuator_params=None).run(tr, t_end=0.1)
    assert res.meta["limits"]["rate_max"] is None
    assert res.meta["limits"]["elevon_hi"] is not None  # 위치 한계는 믹서 소관 — 남는다


def test_actuator_rate_limit_observable(trim_design):
    """작동기가 실제 루프에 있는지 핀 — 낮은 rate 한계에서 타면 기울기 제한."""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    act = {"wn": 30.0, "zeta": 0.7, "rate_max": 0.05}
    res = make_sim(ac, tr, modes=hold_modes(V0, 1050.0), actuator_params=act).run(
        tr, t_end=2.0
    )
    d_de = np.diff(res.signals["de"])
    assert np.max(np.abs(d_de)) <= 0.05 * 0.01 + 1e-12  # rate_max·dt 상한
    assert np.max(np.abs(d_de)) > 0.0  # 실제로 움직이는 중


def test_fuel_burn_quasi_static(trim_design):
    """연료 소모 fuel_flow·평균 스로틀 — 로그 스로틀 적분과 일치."""
    ac, tr = trim_design
    sim = make_sim(ac, tr)
    sim.fuel_flow = 0.5
    res = sim.run(tr, t_end=10.0)
    thr_mean = 0.5 * (res.signals["thr_l"] + res.signals["thr_r"])
    expected = 200.0 - 0.5 * 0.01 * float(np.sum(thr_mean[:-1]))
    assert res.signals["fuel"][-1] == pytest.approx(expected, abs=1e-9)
    assert res.signals["fuel"][-1] < 200.0


def test_sim_progress_callback_monotonic(trim_design):
    """진행 콜백 (M13 서버 진행률 경로) — (done, total) 단조 증가, 완료 시 done=total."""
    ac, tr = trim_design
    calls = []

    def on_progress(done, total):
        calls.append((done, total))
        return False

    res = make_sim(ac, tr).run(tr, t_end=2.0, on_progress=on_progress)
    assert len(res.t) == 200  # 취소 없음 — 완주
    assert len(calls) == 100  # ~1% 주기 (n=200, stride=2)
    assert all(t == 200 for _, t in calls)
    dones = [d for d, _ in calls]
    assert dones == sorted(dones) and dones[-1] == 200
    assert res.meta["aborted"] is None


def test_sim_progress_final_call_when_stride_not_divisible(trim_design):
    """스트라이드가 n_steps를 나누지 못해도 완주 시 done==total 최종 콜백 보장."""
    ac, tr = trim_design
    calls = []
    res = make_sim(ac, tr).run(
        tr, t_end=2.01, on_progress=lambda d, t: calls.append((d, t)) and False
    )
    assert len(res.t) == 201  # n_steps=201, stride=2 — 나눠떨어지지 않음
    assert calls[-1] == (201, 201)
    assert res.meta["aborted"] is None


def test_sim_progress_cancel_truncates(trim_design):
    """콜백 truthy 반환 = 협조적 취소 — 절단 경로 재사용 (부분 결과·정합 길이)."""
    ac, tr = trim_design
    res = make_sim(ac, tr).run(
        tr, t_end=2.0, on_progress=lambda done, total: done >= total // 2
    )
    assert res.meta["aborted"] == "cancelled"
    # 취소 조건 충족 직후 콜백(done=100)에서 절단 — 느슨한 상한은 스트라이드
    # 회귀(예: 말미 단일 호출)를 잡기 위한 여유
    assert 100 <= len(res.t) < 120
    assert len(res.signals["h"]) == len(res.t) == len(res.signals["mode"])


def test_out_of_band_run_truncates_with_partial_result(trim_design):
    """ISA 범위 이탈 런은 직전 절단 — 부분 시계열·엔벨로프 보존 (리뷰 반영).

    해면 아래로 다이브 명령(지형 미모델) → h가 ISA 하한 접근 시 조기 종료.
    """
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    res = make_sim(ac, tr, modes=hold_modes(V0, -5500.0)).run(tr, t_end=600.0)
    assert res.meta["aborted"] == "alt_out_of_range"
    assert len(res.t) < int(600.0 / 0.01)
    assert len(res.signals["h"]) == len(res.t) == len(res.signals["mode"])
    assert res.signals["h"][-1] < -4900.0


def test_min_altitude_flag_marks_excursion_without_stopping(trim_design):
    """기준면(기본 0 m MSL) 아래는 플래그로 표시하되 런은 계속된다.

    이 가드가 없던 동안 저고도 임무가 해수면 아래 수십 m를 날면서도 any_flag=False로
    정상 완주 기록됐다 — ISA 하한(−4,990 m)이 유일한 바닥이었기 때문(대기 모델
    유효성 가드이지 지면이 아님). 지형·파고 미모델이라 "충돌 판정"이 아니라 특이
    상황 표시이므로 중단하지 않는다 (02 §6.1 엔벨로프 감시 항상 장착).
    """
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    res = make_sim(ac, tr, modes=hold_modes(V0, -50.0)).run(tr, t_end=60.0)
    assert res.meta["aborted"] is None  # 플래그일 뿐 — 절단 아님
    assert res.envelope["flags"]["altitude"].any()
    assert res.envelope["any_flag"]  # 단일 요약에 반영 — 무증상 통과 방지
    assert res.envelope["min_alt"] < 0.0
    assert 0.0 <= res.envelope["min_alt_t"] <= 60.0

    # 순항 런은 플래그가 뜨지 않고, 최저 고도는 감시 여부와 무관하게 보고된다
    clean = make_sim(ac, tr).run(tr, t_end=20.0)
    assert not clean.envelope["flags"]["altitude"].any()
    assert clean.envelope["min_alt"] > 0.0

    # 감시 끄기 — 플래그 키 자체가 사라지고 최저 고도 보고는 유지
    off = make_sim(ac, tr, modes=hold_modes(V0, -50.0), min_altitude=None).run(tr, t_end=60.0)
    assert "altitude" not in off.envelope["flags"]
    assert off.envelope["min_alt"] < 0.0


# ---------- 명령 사슬 계측 (구조도 재생 오버레이) ----------
# 최종 타면(de/da/dr)과 피드백만 로깅되던 시절엔 유도→AP→리미터→SCAS 구간이
# 시계열에 없어, 오버레이가 그릴 값이 없었다. _CHAIN_SIGNALS가 그 구간을 채운다.


def test_명령_사슬_신호가_전부_로깅된다(trim_design):
    """길이·유한성 — 하나라도 빠지면 오버레이 배선이 값 없이 남는다.

    형상 의존 프로브는 예외다: 데모 기본은 k_thr_turn=0이라 선회 스로틀 FF 노드가
    조립되지 않고 그 채널은 전부 NaN이어야 한다 (0으로 채우면 "FF가 0을 냈다"로
    위장된다). 그 부재 집합을 여기서 못박는다 — 다른 채널이 NaN이 되기 시작하면
    노드 id 드리프트다.
    """
    from claw.sim.simulator import _CHAIN_SIGNALS

    ac, tr = trim_design
    res = make_sim(ac, tr).run(tr, t_end=5.0)
    absent = set()
    for name in _CHAIN_SIGNALS:
        assert name in res.signals, f"{name} 미로깅"
        assert len(res.signals[name]) == len(res.t)
        arr = np.asarray(res.signals[name])
        if np.isnan(arr).all():
            absent.add(name)
        else:
            assert np.isfinite(arr).all(), f"{name}에 비유한값"
    assert absent == {"ap_thr_ff"}, f"형상 의존 프로브 부재 집합 드리프트: {sorted(absent)}"


def test_기여항_분해가_합산_항등을_만족한다(trim_design):
    """SCAS 축: pid + damp == sum(포화 전) — 기여 분해(진단 규칙 2)의 근거 항등.
    AP 고도 축도 같은 구조다. 어긋나면 프로브가 서로 다른 시각의 값을 섞은 것."""
    ac, tr = trim_design
    res = make_sim(ac, tr).run(tr, t_end=5.0)
    s = res.signals
    for pi, damp, raw in (
        ("pitch_pi", "pitch_damp", "pitch_raw"),
        ("roll_pi", "roll_damp", "roll_raw"),
        ("yaw_pi", "yaw_damp", "yaw_raw"),
        ("ap_alt_pi", "ap_alt_damp", "ap_alt_raw"),
    ):
        np.testing.assert_allclose(
            s[pi] + s[damp], s[raw], atol=1e-12,
            err_msg=f"{pi}+{damp} != {raw}",
        )


def test_적분기와_클램프_기준선이_함께_저장된다(trim_design):
    """meta["clamps"]는 신호가 아니라 기준선 — 저장된 결과만으로 "적분기가
    클램프에 주차했는가"를 판정하려면 한계값이 결과와 함께 다녀야 한다
    (duty의 meta["limits"]와 같은 이유). 적분기 계측은 항상 클램프 안이다."""
    ac, tr = trim_design
    res = make_sim(ac, tr).run(tr, t_end=5.0)
    clamps = res.meta["clamps"]
    for axis in ("pitch", "roll", "yaw", "alt", "spd", "hdg"):
        assert clamps[axis] is not None and clamps[axis]["lo"] < clamps[axis]["hi"]
    for name, axis in (("i_pitch", "pitch"), ("i_alt", "alt"), ("i_spd", "spd")):
        arr = res.signals[name]
        lo, hi = clamps[axis]["lo"], clamps[axis]["hi"]
        assert ((arr >= lo - 1e-9) & (arr <= hi + 1e-9)).all(), f"{name}이 클램프 밖"


def test_축_활성_플래그가_로깅된다(trim_design):
    """진단(오차 분해)은 활성 구간 게이팅이 필수다 — 비활성 스텝의 필터 노드는
    0(disabled_output)이라 게이팅 없이는 오차 분해가 거짓말을 한다."""
    ac, tr = trim_design
    res = make_sim(ac, tr).run(tr, t_end=5.0)
    for name in ("speed_on", "alt_on", "heading_on"):
        assert name in res.signals
        assert len(res.signals[name]) == len(res.t)
    # hold 미션은 세 축 모두 켠다 (hold_modes: speed·alt·heading 전부 지정)
    assert res.signals["alt_on"].all() and res.signals["speed_on"].all()


def test_유도_명령이_모드_전환에서_실제로_바뀐다(trim_design):
    """cmd_* 는 유도 출력을 그대로 실은 것 — 모드가 바뀌면 값도 바뀌어야 한다.
    (상수로 굳어 있으면 배선에 숫자는 뜨지만 아무것도 말해 주지 않는다.)"""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    modes = [
        ModeSpec(name="climb", speed=V0, alt=1300.0, heading=0.0,
                 exit_when=("alt_ge", 1280.0), next="cruise"),
        ModeSpec(name="cruise", speed=V0 - 40.0, alt=1300.0, heading=0.0,
                 exit_when=("time_ge", 1e9)),
    ]
    res = make_sim(ac, tr, modes=modes).run(tr, t_end=90.0)
    spd = res.signals["cmd_speed"]
    assert spd.max() - spd.min() > 30.0, "모드가 바뀌었는데 속도 명령이 그대로다"
    assert res.signals["cmd_alt"].max() == pytest.approx(1300.0)


def test_계측되지_않은_신호는_0이_아니라_NaN(trim_design):
    """리미터 미장착 형상에서 theta_lim은 '값이 0'이 아니라 '계측 안 됨'이다 —
    0으로 채우면 화면에서 '명령이 0으로 떨어졌다'와 구분되지 않는다."""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    sim = Simulator(
        aircraft=ac, fcl=make_demo_fcl(with_limiter=False),
        guidance=Guidance(hold_modes(V0, tr.case.alt)),
        stall_table=make_demo_stall_table(), db_ranges=DB_RANGES,
        dt_plant=0.01, control_hz=100.0,
    )
    res = sim.run(tr, t_end=3.0)
    assert np.isnan(res.signals["theta_lim"]).all()
    assert np.isfinite(res.signals["theta_cmd"]).all()  # 나머지 사슬은 살아 있다


def test_제어주기_사이_스텝은_직전_명령을_유지한다(trim_design):
    """계측도 de/da/dr과 같은 ZOH 규약 — 제어 틱 사이에 0으로 떨어지면 안 된다."""
    ac, tr = trim_design
    # 플랜트 5 ms · 제어 100 Hz → 제어 틱 사이 스텝이 1개씩 낀다
    res = make_sim(ac, tr, dt_plant=0.005, control_hz=100.0).run(tr, t_end=2.0)
    th = res.signals["theta_cmd"]
    assert np.isfinite(th).all()
    # 홀드 구간이면 인접 쌍이 정확히 같은 값이어야 한다 (ZOH)
    assert np.array_equal(th[0::2], th[1::2])
