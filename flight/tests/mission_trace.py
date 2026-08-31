"""대조용 미션 기록 — 실제 데모 미션을 돌리며 제어법칙의 입출력을 그대로 받아 적는다.

합성 신호 대신 실제 폐루프를 쓰는 이유는, 합성으로는 잘 안 밟히는 경로가 여기 다
들어 있기 때문이다: 모드 4개 전환(각 축 on/off), 게인 스케줄 이동, α 리미터 작동,
타면 포화, **항법 무효 구간의 출력 홀드**.

기록하는 값은 그래프 경계와 같은 **공학량**이다 — 쿼터니언·항법속도에서 오일러각과
에어데이터를 뽑는 일은 실기 FCC에서 항법·ADC의 몫이고, 생성 코드 밖에 있다.
"""

import numpy as np

from claw.common.attitude import quat_to_euler
from claw.common.contracts import TrimCase
from claw.env import isa_atmosphere
from claw.env.constants import ISA_MIN_ALT, ISA_STRATO1_TOP_ALT
from claw.fcl import make_demo_fcl
from claw.fcl.airdata import airdata_from_nav
from claw.guidance import Guidance, LosPath, ModeSpec
from claw.nav import NavErrorModel
from claw.plant import make_demo_aircraft, make_demo_stall_table
from claw.sim import Simulator
from claw.trim import trim_level

# fcl_graph의 입력 순서 — 하네스가 한 줄에 이 순서로 읽는다
INPUT_ORDER = (
    "nav_valid", "theta", "phi", "psi", "p", "q", "r", "V", "alpha", "beta",
    "h", "hdot", "mach", "cmd_speed", "cmd_alt", "cmd_heading",
    "cmd_pitch", "cmd_hdot",
    "speed_on", "alt_on", "heading_on", "pitch_on", "hdot_on",
)
OUTPUT_ORDER = (
    "elevon_l", "elevon_r", "rudder", "throttle_l", "throttle_r",
    "limiter_active", "alpha_margin",
)


def run(t_end=180.0):
    """→ (입력 dict 목록, 기준 출력 튜플 목록, 트림 웜스타트 (de0, th0, thr0))."""
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=300.0))
    assert tr.converged
    path = LosPath(waypoints=((8000.0, 0.0), (8000.0, 8000.0)), accept_radius=1500.0)
    V0 = float(np.linalg.norm(tr.state.vel_b))
    modes = [
        ModeSpec(name="climb", speed=V0, alt=1300.0, heading=0.0,
                 exit_when=("alt_ge", 1280.0), next="wpnav"),
        ModeSpec(name="wpnav", speed=140.0, alt=1300.0, heading="path",
                 exit_when=("path_done",), next="descent"),
        ModeSpec(name="descent", speed=140.0, alt=100.0,
                 exit_when=("alt_le", 130.0), next="arrest"),
        # 아래 두 모드는 **C 대조를 위해** 있다 — 종방향 축 선택(θ 출처 Switch)의
        # hdot·pitch 갈래를 실제로 밟지 않으면 생성 C의 그 분기가 검증되지 않는다.
        # 대조 트레이스가 test_mission의 사본이면서 여기만 갈라지는 이유가 이것이고,
        # 회귀 미션 자체는 engine 쪽에서 순항 시나리오 그대로 남는다.
        ModeSpec(name="arrest", speed=140.0, hdot=-2.0,
                 exit_when=("time_ge", 6.0), next="hold_att"),
        ModeSpec(name="hold_att", speed=140.0, pitch=0.02,
                 exit_when=("time_ge", 6.0), next="mission"),
        ModeSpec(name="mission", speed=140.0, alt=30.0, heading=None,
                 exit_when=("time_ge", 1e9)),
    ]
    fcl = make_demo_fcl()
    inputs, refs = [], []
    orig_step = fcl.step

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
        refs.append((
            float(out.elevon[0]), float(out.elevon[2]), float(out.rudder),
            float(out.throttle[0]), float(out.throttle[1]),
            float(fcl.limiter_active),
            fcl.alpha_margin,  # 첫 스텝 이전엔 None — 비교에서 건너뛴다
        ))
        return out

    fcl.step = spy
    sim = Simulator(
        aircraft=ac, fcl=fcl, guidance=Guidance(modes, path=path),
        nav_model=NavErrorModel(delay_s=0.02, update_hz=50.0, seed=11),
        stall_table=make_demo_stall_table(), dt_plant=0.01, control_hz=100.0,
        actuator_params={"wn": 30.0, "zeta": 0.7, "rate_max": 10.0}, fuel_flow=0.3,
    )
    res = sim.run(tr, t_end=t_end)
    assert res.meta["aborted"] is None, res.meta["aborted"]
    warm = (float(tr.control.elevon[0]), float(tr.state.euler()[1]),
            float(tr.control.throttle[0]))
    return inputs, refs, warm
