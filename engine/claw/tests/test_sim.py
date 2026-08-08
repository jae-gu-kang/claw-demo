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
             actuator_params=None):
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
    nav = NavErrorModel(pos_std=1.0, vel_std=0.1, att_std=0.001, psi_std=0.002,
                        rate_std=0.0005, bias_std=0.5, bias_tau=60.0,
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
    assert calls, "콜백이 호출되어야 함"
    assert all(t == 200 for _, t in calls)
    dones = [d for d, _ in calls]
    assert dones == sorted(dones) and dones[-1] == 200
    assert res.meta["aborted"] is None


def test_sim_progress_cancel_truncates(trim_design):
    """콜백 truthy 반환 = 협조적 취소 — 절단 경로 재사용 (부분 결과·정합 길이)."""
    ac, tr = trim_design
    res = make_sim(ac, tr).run(
        tr, t_end=2.0, on_progress=lambda done, total: done >= total // 2
    )
    assert res.meta["aborted"] == "cancelled"
    assert 100 <= len(res.t) < 120  # 취소 지연은 콜백 주기(스트라이드) 이내
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
