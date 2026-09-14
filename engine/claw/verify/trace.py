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

from claw.common.contracts import TrimCase
from claw.fcl.boundary import graph_inputs
from claw.fcl.graphs import FCL_INPUTS
from claw.guidance import Guidance, LosPath, ModeSpec
from claw.nav import NavErrorModel
from claw.sim import Simulator
from claw.trim import trim_level

# fcl_graph의 입력 순서 — 대조 하네스가 한 줄에 이 순서로 읽는다
# **그래프 입력 순서가 곧 이 순서다.** 손으로 적은 사본이면 순서가 갈릴 수 있는데,
# 이 순서는 C 하네스의 stdin 배열을 정하고 인자 순서는 `graph.inputs`가 정하므로,
# 갈리는 순간 값이 자리를 바꿔 실린다 — `verify/units.py`가 기록한 믹서 사고와 같은 병이다.
INPUT_ORDER = FCL_INPUTS

# 대조 미션의 **모양은 한 벌**이고 크기는 기체가 정한다. 모양을 처음 잡은 기체(구 합성 기체 — 설계 마하 0.6)의 값을
# 기준으로, 기체의 설계 마하(law.schedule.m_design)와의 비 k만큼 속도·고도 변화는 k배, 경로의 수평 거리(웨이포인트·도달
# 반경)는 k²배로 줄이거나 늘린다. 수평 거리를 k²로 두는 이유는 선회 반경(V²/g·tanφ)과 같은 비라서다 — k로만 줄이면 느린
# 기체에게 꺾임이 상대적으로 완만해져 롤 명령이 배분 한계(동적 롤 예산)에 한 번도 닿지 않고, 그러면 그 경로의 C 대조가
# 반쪽이 된다(flight/tests test_trace_exercises_the_hard_paths). 모드 체류(time_ge)와 t_end는 그대로 둔다 — 빠른 기체(k > 1)는
# 경로 시간이 k배라 기본 180 s 안에 descent·arrest·hold_att가 안 올 수 있으니 **부르는 쪽이 t_end를 늘린다**(여기서 몰래 늘리면
# 보고서의 t_end·스팬 id·서버 상한이 실제로 난 시간과 어긋난다 — 밟지 못한 갈래는 exercised가 말한다). 느린 기체에
# 원래 미션을 그대로 주면 설계점(M0.6)부터 트림이 안 풀린다(200 kg급 예제의 수평비행 상한이 M0.24다). 구 기체는 k = 1이라
# 기록이 비트 그대로다.
_REF_M_DESIGN = 0.6
_START_ALT = 1000.0  # [m] 대조 미션 시작 고도 — 아래 고도들은 이 고도에서의 변화량으로 적는다


def _mission_modes(V0, k=1.0):
    """대조 미션의 모드 체인 — test_mission의 순항 시나리오에 arrest·hold_att를 얹는다.

    아래 두 모드는 **C 대조를 위해** 있다 — 종방향 축 선택(θ 출처 Switch)의
    hdot·pitch 갈래를 실제로 밟지 않으면 생성 C의 그 분기가 검증되지 않는다.
    k: 기준 미션 대비 속도·거리 비(모듈 머리 주석). 각도(pitch)와 시간은 그대로다.
    """
    spd = 140.0 * k
    return [
        ModeSpec(name="climb", speed=V0, alt=_START_ALT + 300.0 * k, heading=0.0,
                 exit_when=("alt_ge", _START_ALT + 280.0 * k), next="wpnav"),
        ModeSpec(name="wpnav", speed=spd, alt=_START_ALT + 300.0 * k, heading="path",
                 exit_when=("path_done",), next="descent"),
        ModeSpec(name="descent", speed=spd, alt=_START_ALT - 900.0 * k,
                 exit_when=("alt_le", _START_ALT - 870.0 * k), next="arrest"),
        ModeSpec(name="arrest", speed=spd, hdot=-2.0 * k,
                 exit_when=("time_ge", 6.0), next="hold_att"),
        ModeSpec(name="hold_att", speed=spd, pitch=0.02,
                 exit_when=("time_ge", 6.0), next="mission"),
        ModeSpec(name="mission", speed=spd, alt=_START_ALT - 970.0 * k, heading=None,
                 exit_when=("time_ge", 1e9)),
    ]


def record_mission(law, *, profile, t_end=180.0, control_hz=100.0, on_progress=None) -> dict:
    """주어진 법칙으로 대조 미션 1회 → 입·출력 기록.

    profile: 미션을 나는 기체 프로파일 — 법칙을 조립한 **그 기체**여야 한다. 시작 트림은 그 기체의 설계
    마하(law.schedule.m_design)·1000 m·연료 ¾이고, 모드·경로의 속도·거리·고도 변화는 설계 마하 비로 맞춘다(모듈 머리).
    작동기·연료 소모율도 그 기체 문서(actuator.params · mission_template.sim.fuel_flow)에서 읽는다.

    돌려주는 dict:
      inputs        스텝별 그래프 입력 {이름: float} (INPUT_ORDER의 키 전부)
      outputs       스텝별 그래프 출력 {출력명: float} — 이름·개수는 형상을 따른다
      output_order  그래프 출력 선언 순서 (생성 C의 출력 구조체 순서와 같다)
      warm          (de0, th0, thr0) 트림 웜스타트 — 하네스 첫 줄
      meta          SimResult.meta (aborted 포함 — None이 아니면 완주 실패)

    on_progress(done, total)는 시뮬 스텝 기준 ~1% 주기 — truthy 반환 = 협조적 취소.
    취소·절단되어도 그때까지의 기록을 그대로 돌려준다 (판단은 부르는 쪽 몫).
    """
    doc = profile.doc
    schedule = doc["law"]["schedule"]
    if schedule is None:
        raise ValueError("대조 미션은 설계 마하(law.schedule.m_design)로 크기를 정한다 — 게인 스케줄이 없는 기체")
    m_design = float(schedule["m_design"])
    k = m_design / _REF_M_DESIGN
    ac = profile.aircraft()
    fuel = 0.75 * doc["mass"]["fuel_max"]
    # 설계점이 수평비행 상한에 붙은 기체(200 kg급 예제 — 설계 마하 0.245, 1000 m 상한 ~0.24)는 거기서 트림이 안 풀린다.
    # 설계 마하에서 k·0.01 간격으로 아래·위를 번갈아(0, −1, +1, −2, +2 …칸) 처음 풀리는 자리에서 출발한다 — 상한에 붙은 기체는
    # 아래에서, 하한에 붙은 기체는 위에서 풀린다. 첫 자리는 설계 마하 그대로라 구 기체(M0.6에서 풀린다)는 기록이 비트 그대로다
    tried = []
    for i in range(13):
        steps = (i + 1) // 2 * (1 if i % 2 == 0 else -1)
        mach = round(m_design + steps * 0.01 * k, 6)
        if mach <= 0.0:
            continue
        tried.append(mach)
        tr = trim_level(ac, TrimCase("design", mach=mach, alt=_START_ALT, fuel=fuel))
        if tr.converged:
            break
    else:
        raise ValueError(f"대조 미션 시작 트림이 안 풀린다 — 설계 마하 M{m_design:g} 둘레 {len(tried)}곳"
                         f"(M{min(tried):g}~M{max(tried):g})·{_START_ALT:.0f} m (기체의 설계 마하가 수평비행 범위 밖)")
    kk = k * k  # 수평 거리는 선회 반경과 같은 비(모듈 머리)
    path = LosPath(waypoints=((8000.0 * kk, 0.0), (8000.0 * kk, 8000.0 * kk)), accept_radius=1500.0 * kk)
    V0 = float(np.linalg.norm(tr.state.vel_b))
    template = doc.get("mission_template")
    fuel_flow = float(template["sim"]["fuel_flow"]) if template else 0.0

    inputs, outputs = [], []
    orig_step = law.step

    def spy(cmd, nav):
        # 조립은 `fcl/boundary.py`가 정본 — 법칙이 실제로 받는 값과 **같은 함수**로 만든다.
        # 두 벌로 적혀 있을 때는 불리언 접기가 한쪽만 바뀌어도 대조가 통과했다.
        # **스텝보다 먼저** 조립한다: 뒤에 두면 「법칙이 cmd·nav를 안 건드린다」는 가정에
        # 기대게 되고, 그 가정이 깨지는 날 기록과 실행이 다른 값을 보면서도 조용하다
        inputs.append(graph_inputs(cmd, nav))
        out = orig_step(cmd, nav)
        # 그래프 출력을 이름 그대로 — SurfaceCommand로 접으면 limiter_active처럼
        # 계약 밖 출력이 빠지고, 형상이 바뀔 때마다 여기를 고치게 된다
        outputs.append({k: float(v) for k, v in law.runner.last_outputs.items()})
        return out

    law.step = spy
    try:
        sim = Simulator(
            aircraft=ac, fcl=law, guidance=Guidance(_mission_modes(V0, k), path=path),
            nav_model=NavErrorModel(delay_s=0.02, update_hz=50.0, seed=11),
            stall_table=profile.stall_table(), dt_plant=0.01, control_hz=control_hz,
            actuator_params=profile.actuator_params(),
            fuel_flow=fuel_flow,
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
