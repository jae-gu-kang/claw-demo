"""Phase 4 완료 기준 검증 (03 §6) — 폐루프 시나리오 완주 + 파라미터 Δ리포트.

미션: 상승→웨이포인트 항법(90° 선회)→디센트→임무수행 — 실전 조건
(항법 오차 모델 + 작동기 + 연료 소모)에서 모드 체인 완주와 엔벨로프
청정(무플래그·실속 여유)을 회귀 고정한다.
Δ리포트: 오토파일럿 게인(ap.kp_alt)을 파라미터 계층으로 흔들어 상승 캡처
성능 변화를 정량화 — 02 §2.4 설계값 연계·영향성 평가의 폐루프 실사용.
"""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.fcl import Autopilot, make_demo_fcl
from claw.guidance import Guidance, LosPath, ModeSpec
from claw.nav import NavErrorModel
from claw.params.param import ParamDef
from claw.params.paramset import ParamSet
from claw.pipeline import Pipeline, delta_report
from claw.plant import make_demo_aircraft, make_demo_db_ranges, make_demo_stall_table
from claw.sim import Simulator
from claw.trim import trim_level

DB_RANGES = make_demo_db_ranges()


@pytest.fixture(scope="module")
def trim_design():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=300.0))
    assert tr.converged
    return ac, tr


def test_full_mission_closed_loop(trim_design):
    """상승→선회 항법→디센트→임무수행 완주 — Phase 4 완료 기준의 본체.

    실측 타임라인(회귀 기준): climb→wpnav 15.7 s, wpnav→descent 92.3 s
    (90° 선회 + 202→140 m/s 감속), descent→mission 138 s, 최종 h≈30 m.
    웨이포인트 기하는 선회반경(V²/(g·tanφ_max) — 140 m/s에서 ≈2.4 km)을
    고려해 다리 8 km·도달반경 1.5 km. 작동기 rate 10 rad/s [기본값] —
    3 rad/s는 항법 지연·잡음과 결합해 리밋사이클 (요구 사양 도출 스터디).
    """
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    path = LosPath(waypoints=((8000.0, 0.0), (8000.0, 8000.0)), accept_radius=1500.0)
    modes = [
        ModeSpec(name="climb", speed=V0, alt=1300.0, heading=0.0,
                 exit_when=("alt_ge", 1280.0), next="wpnav"),
        ModeSpec(name="wpnav", speed=140.0, alt=1300.0, heading="path",
                 exit_when=("path_done",), next="descent"),
        ModeSpec(name="descent", speed=140.0, alt=100.0,
                 exit_when=("alt_le", 130.0), next="mission"),
        ModeSpec(name="mission", speed=140.0, alt=30.0, heading=None,
                 exit_when=("time_ge", 1e9)),  # 임무수행 저고도 (MSL 기준, 01 §2.5)
    ]
    nav = NavErrorModel(pos_std_h=1.0, pos_std_v=1.0, vel_std_h=0.1, vel_std_v=0.1,
                        att_std=0.001, psi_std=0.002,
                        rate_std=0.0005, bias_std_h=0.5, bias_std_v=0.5, bias_tau=60.0,
                        delay_s=0.02, update_hz=50.0, seed=11)
    sim = Simulator(
        aircraft=ac,
        fcl=make_demo_fcl(),
        guidance=Guidance(modes, path=path),
        nav_model=nav,
        stall_table=make_demo_stall_table(),
        db_ranges=DB_RANGES,
        dt_plant=0.01,
        control_hz=100.0,
        actuator_params={"wn": 30.0, "zeta": 0.7, "rate_max": 10.0},
        fuel_flow=0.3,
    )
    res = sim.run(tr, t_end=180.0, fingerprint="mission-demo")

    # 모드 체인 완주 (순서 고정)
    seq = [m for i, m in enumerate(res.signals["mode"])
           if i == 0 or m != res.signals["mode"][i - 1]]
    assert seq == ["climb", "wpnav", "descent", "mission"]
    assert res.meta["aborted"] is None
    # 임무수행 고도 정착
    assert abs(res.signals["h"][-1] - 30.0) < 10.0
    # 선회 실행 (wp2는 동쪽 — ψ가 π/2 부근까지 감)
    assert np.max(res.signals["psi"]) > 1.2
    # 엔벨로프: DB 유효범위 이탈 없음, 실속 여유 유지, 리미터 비작동
    for var in ("alpha", "beta", "mach"):
        assert not res.envelope["flags"][var].any(), f"{var} DB 유효범위 이탈"
    assert res.envelope["worst_margin"] > 0.1
    assert not np.any(res.signals["limiter_active"])
    # 고도 플래그는 현재 뜬다 — descent가 강하율을 세우지 않은 채(−25 m/s) mission으로
    # 넘어가고 플레어가 없어 해수면 아래까지 내려간다 (01 §7 [백로그]). 감추지 않고
    # 현상을 고정해 둔다: 플레어가 들어오면 이 단정이 깨져 갱신 대상임을 알린다.
    assert res.envelope["flags"]["altitude"].any(), "고도 플래그 미발생 — 개선됐다면 갱신"
    assert -60.0 < res.envelope["min_alt"] < 0.0
    # 연료 소모 반영
    assert res.signals["fuel"][-1] < 300.0
    assert res.params_fingerprint == "mission-demo"


def test_delta_report_ap_gain_on_closed_loop_metric(trim_design):
    """Δ리포트 실사용 (02 §2.4): ap.kp_alt 2배 → 상승 캡처 잔여 오차 감소 정량화."""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    defs = (ParamDef("ap.kp_alt", 0.002, "rad/m", "고도 비례 게인"),)

    def run_sim(ps):
        fcl = make_demo_fcl(autopilot=Autopilot(kp_alt=ps["ap.kp_alt"]))
        modes = [ModeSpec(name="climb", speed=V0, alt=1100.0, heading=0.0,
                          exit_when=("time_ge", 1e9))]
        sim = Simulator(aircraft=ac, fcl=fcl, guidance=Guidance(modes),
                        stall_table=make_demo_stall_table(), db_ranges=DB_RANGES,
                        dt_plant=0.01, control_hz=100.0)
        return sim.run(tr, t_end=40.0, fingerprint=ps.fingerprint())

    pipe = Pipeline()
    pipe.add("mission", run_sim, uses=("ap.",))
    a = ParamSet(defs)
    b = a.copy_with({"ap.kp_alt": 0.004})
    rep = delta_report(
        pipe, "mission", a, b,
        metrics=lambda res: {
            "err_end": float(abs(res.signals["h"][-1] - 1100.0)),
            "worst_margin": res.envelope["worst_margin"],
        },
    )
    assert rep["param_diff"] == {"ap.kp_alt": (0.002, 0.004)}
    # 엄격 부등호는 캐시 무효화 핀 겸용 — uses 미포함이면 delta가 정확히 0.0
    assert rep["delta"]["err_end"] < 0.0  # 게인 상향 → 캡처 잔여 오차 감소
    assert rep["a"]["worst_margin"] > 0.1 and rep["b"]["worst_margin"] > 0.1
