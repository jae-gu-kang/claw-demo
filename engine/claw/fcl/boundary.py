"""계약 ↔ 그래프 입력의 **단일 경계** — 23키와 접기 규약이 한 자리에 산다 (07 §7).

이 함수가 생기기 전에는 같은 23키가 **세 벌**로 손에 적혀 있었다: `fcl/law.py`의 `step`
kwargs, `verify/trace.py`의 dict 리터럴, 그리고 `verify/trace.py`의 `INPUT_ORDER`. 앞의 둘은
값을 만들고 뒤의 하나는 C 하네스의 stdin 순서를 정한다.

**키를 빠뜨리면 런타임에 잡히지만 접기 규약의 어긋남은 아무도 안 본다.** 불리언 여섯
(`nav_valid`·`*_on`)은 IR에 불리언 타입이 없어 `float(bool(x))`로 접혀 나르는데(07 §7),
한쪽만 `float(x)`로 바뀌면 `nav_valid=0.5` 같은 값이 그래프 enable에 실린다 — 두 벌이
그대로 돌고 대조도 통과한다. v0.85에서 `typerules`가 「enable 자리는 불리언」을 요구하게
됐지만, 그 검사는 **선언**을 보지 이 조립을 안 본다.

파생값(사원수 → 오일러 · 항법 → 공력각 · `V/a`)은 실기에서 항법·ADC의 몫이라 여기 산다.
표는 셋이고 역할이 다르다: `DIRECT`가 계약 필드를 그대로 읽는 자리를 **구동**하고,
`DERIVED`는 파생값의 출처를 슬롯까지 **적어 두며**(테스트가 조립의 언패킹과 대조한다),
`BOUNDARY`는 둘을 합쳐 `FCL_INPUTS`와 **대조**하는 데만 쓴다.
"""

from claw.common.attitude import quat_to_euler
from claw.env import isa_atmosphere
from claw.env.constants import ISA_MIN_ALT, ISA_STRATO1_TOP_ALT
from claw.fcl.airdata import airdata_from_nav
from claw.fcl.graphs import FCL_INPUTS

# 계약 필드를 **그대로 읽는** 입력 — (계약, 필드, 불리언 접기 여부).
# `"cmd"`/`"nav"`는 `graph_inputs`의 인자 이름이다.
DIRECT = {
    "cmd_speed": ("cmd", "speed", False),
    "cmd_alt": ("cmd", "alt", False),
    "cmd_heading": ("cmd", "heading", False),
    "cmd_pitch": ("cmd", "pitch", False),
    "cmd_hdot": ("cmd", "hdot", False),
    "speed_on": ("cmd", "speed_on", True),
    "alt_on": ("cmd", "alt_on", True),
    "heading_on": ("cmd", "heading_on", True),
    "pitch_on": ("cmd", "pitch_on", True),
    "hdot_on": ("cmd", "hdot_on", True),
    "nav_valid": ("nav", "valid", True),
}

# 항법 원시 상태에서 **유도되는** 입력 — 값은 `graph_inputs`가 만들고, 표는 출처만 적는다.
# 실기에서는 이 자리가 항법·ADC의 몫이다.
# **슬롯까지 적는다.** 출처만 적으면 셋이 같은 문자열이라 「한 벡터에서 나온다」가
# 구조적으로 항상 참이 되고, `phi, theta, psi`를 `theta, phi, psi`로 뒤바꿔도 이 표는
# 아무 말을 안 한다. 순서는 조립의 튜플 언패킹이 정본이고 테스트가 둘을 대조한다.
DERIVED = {
    "phi": "quat_to_euler(nav.q_nb)[0]",
    "theta": "quat_to_euler(nav.q_nb)[1]",
    "psi": "quat_to_euler(nav.q_nb)[2]",
    "p": "nav.omega_b[0]",
    "q": "nav.omega_b[1]",
    "r": "nav.omega_b[2]",
    "V": "airdata_from_nav(nav)[0]",
    "alpha": "airdata_from_nav(nav)[1]",
    "beta": "airdata_from_nav(nav)[2]",
    "h": "-nav.pos_n[2]",
    "hdot": "-nav.vel_n[2]",
    "mach": "V / isa_atmosphere(h).a",
}

# 두 표를 합치면 그래프 경계가 된다. 어긋나면 여기서 죽는다 — `FCL_INPUTS`가 정본이다.
#
# **`assert`가 아니라 `raise`다.** `python -O`는 assert를 통째로 지우므로, 그 모드에서는
# 이 정본 대조가 사라지고 누락이 비행 제어 경로의 `step_all`까지 내려가 늦게 터진다.
# 저장소가 드리프트 가드에 assert를 널리 쓰지만, 그것들은 어휘 대조라 늦게 터져도 개발
# 중에만 아프다 — 여기는 계약과 법칙 사이라 성질이 다르다.
BOUNDARY = {**DIRECT, **DERIVED}
if set(BOUNDARY) != set(FCL_INPUTS):
    raise RuntimeError(
        f"경계 표가 그래프 입력과 어긋났다: {sorted(set(BOUNDARY) ^ set(FCL_INPUTS))}"
    )

# 불리언으로 접히는 신호 — `SIGNAL_TYPES`가 BOOL로 선언한 그 여섯이다.
BOOL_INPUTS = frozenset(k for k, (_, _, fold) in DIRECT.items() if fold)


def nav_derived(nav) -> dict:
    """`NavOutput` 원시 상태 → 공학량 12개. 실기에서는 이 자리가 항법·ADC의 몫이다.

    **축 단독 경로(`fcl/scas.py`)도 이 함수를 쓴다.** 거기서 여섯(θ·φ·β·p·q·r)을 손으로
    또 뽑고 있었고, 언패킹 순서가 여기와 갈려도 아무도 안 봤다 — 「정본은 하나」가 참이
    되려면 그 사본도 없어야 한다.

    ISA 클램프는 **양쪽 끝** 모두 필요하다. 하한이 없으면 해수면 아래(`h < -5000 m`)에서
    음속 조회가 `ValueError`를 던지는데, 그것은 **비행 제어 스텝 안에서 나는 예외**라
    「비행 중 예외 금지」와 정면으로 어긋난다.
    """
    V, alpha, beta = airdata_from_nav(nav)
    phi, theta, psi = quat_to_euler(nav.q_nb)
    h = -float(nav.pos_n[2])
    h_isa = min(max(h, ISA_MIN_ALT), ISA_STRATO1_TOP_ALT)
    p, q, r = nav.omega_b
    return {
        "theta": float(theta), "phi": float(phi), "psi": float(psi),
        "p": float(p), "q": float(q), "r": float(r),
        "V": float(V), "alpha": float(alpha), "beta": float(beta),
        "h": h, "hdot": -float(nav.vel_n[2]),
        "mach": float(V / isa_atmosphere(h_isa).a),
    }


def graph_inputs(cmd, nav) -> dict:
    """`GuidanceCommand`·`NavOutput` → 그래프 입력 23키.

    **불리언은 `float(bool(x))`로 접는다** — IR에 불리언 타입이 없어서다(07 §7). `bool()`을
    빼면 0/1이 아닌 값이 enable에 실릴 수 있고, 그 어긋남은 두 벌로 적혀 있을 때 아무도
    못 본다. 그래서 접기가 이 한 자리에만 있다.
    """
    out = nav_derived(nav)
    src = {"cmd": cmd, "nav": nav}
    for name, (obj, field, fold) in DIRECT.items():
        value = getattr(src[obj], field)
        out[name] = float(bool(value)) if fold else float(value)
    return out
