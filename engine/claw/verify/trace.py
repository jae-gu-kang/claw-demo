"""대조용 미션 기록 — 실제 데모 미션을 돌리며 제어법칙의 입출력을 그대로 받아 적는다.

`flight/tests/mission_trace.py`에 있던 것을 M12 verify로 이관한 것이다(그쪽은 이제
이 모듈을 부르는 얇은 껍데기다). 이관 이유는 소비자가 둘이 되어서다: 패리티 테스트
(flight/tests)와 **검증 탭**(claw.verify.autocode → 서버 /verify/flight)이 같은 대조
미션을 써야 하고, 미션 정의가 두 곳에 적히면 "테스트가 검증한 것"과 "화면이 검증한
것"이 조용히 갈라진다 (02 §5.5).

합성 신호 대신 실제 폐루프를 쓰는 이유는, 합성으로는 잘 안 밟히는 경로가 여기 다
들어 있기 때문이다: 모드 4개 전환(각 축 on/off), 게인 스케줄 이동, α 리미터 작동,
타면 포화, **항법 무효 구간의 출력 홀드**.

기록하는 값은 그래프 경계와 같은 **공학량**이다 — 쿼터니언·항법속도에서 오일러각과
에어데이터를 뽑는 일은 실기 FCC에서 항법·ADC의 몫이고, 생성 코드 밖에 있다.

출력은 러너의 계측 창구(`GraphRunner.last_outputs`)에서 읽는다 — 그래프 출력 이름
그대로라 법칙 형상(리미터 유무 등)이 바뀌어도 기록이 따라간다. 항법 무효 스텝은
홀드 값이 잡힌다(생성 C의 `sta->hold`와 같은 의미).
"""

import numpy as np

from claw.common.attitude import quat_to_euler
from claw.common.contracts import TrimCase
from claw.env import isa_atmosphere
from claw.env.constants import ISA_MIN_ALT, ISA_STRATO1_TOP_ALT
from claw.fcl.airdata import airdata_from_nav
from claw.guidance import Guidance, LosPath, ModeSpec
from claw.nav import NavErrorModel
from claw.plant import make_demo_aircraft, make_demo_stall_table
from claw.sim import Simulator
from claw.trim import trim_level

# fcl_graph의 입력 순서 — 대조 하네스가 한 줄에 이 순서로 읽는다
INPUT_ORDER = (
    "nav_valid", "theta", "phi", "psi", "p", "q", "r", "V", "alpha", "beta",
    "h", "hdot", "mach", "cmd_speed", "cmd_alt", "cmd_heading",
    "cmd_pitch", "cmd_hdot",
    "speed_on", "alt_on", "heading_on", "pitch_on", "hdot_on",
)


def _mission_modes(V0):
    """대조 미션의 모드 체인 — test_mission의 순항 시나리오에 arrest·hold_att를 얹는다.

    아래 두 모드는 **C 대조를 위해** 있다 — 종방향 축 선택(θ 출처 Switch)의
    hdot·pitch 갈래를 실제로 밟지 않으면 생성 C의 그 분기가 검증되지 않는다.
    """
    return [
        ModeSpec(name="climb", speed=V0, alt=1300.0, heading=0.0,
                 exit_when=("alt_ge", 1280.0), next="wpnav"),
        ModeSpec(name="wpnav", speed=140.0, alt=1300.0, heading="path",
                 exit_when=("path_done",), next="descent"),
        ModeSpec(name="descent", speed=140.0, alt=100.0,
                 exit_when=("alt_le", 130.0), next="arrest"),
        ModeSpec(name="arrest", speed=140.0, hdot=-2.0,
                 exit_when=("time_ge", 6.0), next="hold_att"),
        ModeSpec(name="hold_att", speed=140.0, pitch=0.02,
                 exit_when=("time_ge", 6.0), next="mission"),
        ModeSpec(name="mission", speed=140.0, alt=30.0, heading=None,
                 exit_when=("time_ge", 1e9)),
    ]


def record_mission(law, *, t_end=180.0, control_hz=100.0, on_progress=None) -> dict:
    """주어진 법칙으로 대조 미션 1회 → 입·출력 기록.

    돌려주는 dict:
      inputs        스텝별 그래프 입력 {이름: float} (INPUT_ORDER의 키 전부)
      outputs       스텝별 그래프 출력 {출력명: float} — 이름·개수는 형상을 따른다
      output_order  그래프 출력 선언 순서 (생성 C의 출력 구조체 순서와 같다)
      warm          (de0, th0, thr0) 트림 웜스타트 — 하네스 첫 줄
      meta          SimResult.meta (aborted 포함 — None이 아니면 완주 실패)

    on_progress(done, total)는 시뮬 스텝 기준 ~1% 주기 — truthy 반환 = 협조적 취소.
    취소·절단되어도 그때까지의 기록을 그대로 돌려준다 (판단은 부르는 쪽 몫).
    """
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=300.0))
    assert tr.converged
    path = LosPath(waypoints=((8000.0, 0.0), (8000.0, 8000.0)), accept_radius=1500.0)
    V0 = float(np.linalg.norm(tr.state.vel_b))

    inputs, outputs = [], []
    orig_step = law.step

    def spy(cmd, nav):
        V, alpha, beta = airdata_from_nav(nav)
        phi, theta, psi = quat_to_euler(nav.q_nb)
        h = -float(nav.pos_n[2])
        h_isa = min(max(h, ISA_MIN_ALT), ISA_STRATO1_TOP_ALT)
        p, q, r = (float(x) for x in nav.omega_b)
        out = orig_step(cmd, nav)
        inputs.append({
            "nav_valid": float(bool(nav.valid)),
            "theta": float(theta), "phi": float(phi), "psi": float(psi),
            "p": p, "q": q, "r": r, "V": float(V),
            "alpha": float(alpha), "beta": float(beta),
            "h": h, "hdot": -float(nav.vel_n[2]),
            "mach": float(V / isa_atmosphere(h_isa).a),
            "cmd_speed": float(cmd.speed), "cmd_alt": float(cmd.alt),
            "cmd_heading": float(cmd.heading),
            "cmd_pitch": float(cmd.pitch), "cmd_hdot": float(cmd.hdot),
            "speed_on": float(bool(cmd.speed_on)), "alt_on": float(bool(cmd.alt_on)),
            "heading_on": float(bool(cmd.heading_on)),
            "pitch_on": float(bool(cmd.pitch_on)), "hdot_on": float(bool(cmd.hdot_on)),
        })
        # 그래프 출력을 이름 그대로 — SurfaceCommand로 접으면 limiter_active처럼
        # 계약 밖 출력이 빠지고, 형상이 바뀔 때마다 여기를 고치게 된다
        outputs.append({k: float(v) for k, v in law.runner.last_outputs.items()})
        return out

    law.step = spy
    try:
        sim = Simulator(
            aircraft=ac, fcl=law, guidance=Guidance(_mission_modes(V0), path=path),
            nav_model=NavErrorModel(delay_s=0.02, update_hz=50.0, seed=11),
            stall_table=make_demo_stall_table(), dt_plant=0.01, control_hz=control_hz,
            actuator_params={"wn": 30.0, "zeta": 0.7, "rate_max": 10.0}, fuel_flow=0.3,
        )
        res = sim.run(tr, t_end=t_end, on_progress=on_progress)
    finally:
        law.step = orig_step
    warm = (float(tr.control.elevon[0]), float(tr.state.euler()[1]),
            float(tr.control.throttle[0]))
    return {
        "inputs": inputs,
        "outputs": outputs,
        "output_order": tuple(law.runner.graph.outputs),
        "warm": warm,
        "meta": res.meta,
    }
