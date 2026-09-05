"""IR의 Python 백엔드 — 그래프를 엔진 블록 인스턴스로 실행한다 (02 §2.2).

블록 로직을 **다시 구현하지 않는다**. 노드가 가리키는 M2 블록(`claw.blocks`)을
그대로 생성해 `init(dt)` → `step()`을 부를 뿐이다. 그래서 IR 실행 결과는 손으로 쓴
기존 제어법칙(`fcl/`)과 비트 단위로 같아야 하고, 이것이 IR이 구조를 옳게 옮겼는지
판정하는 기준이 된다.

부수 효과가 하나 더 있다 — `init(dt)`를 태우고 나면 각 인스턴스가 **이산 계수를
이미 갖고 있다**(예: `Washout._p = exp(-dt/tau)`, `filters.py:29`). C 생성기는
그 값을 인스턴스에서 그대로 읽어 구우므로, 이산화 공식이 어디에도 두 번 적히지
않는다 (`emit_c.py` 참조).

입력 전달 계약: 노드 입력이 1개면 스칼라, 2개 이상이면 시퀀스로 넘긴다 —
엔진 블록 계약과 같다(`basic.py:22` Sum·Product는 시퀀스를 받는다). 다만 게인 포트를
가진 블록(PID 등)은 첫 인자 + 키워드로 부른다.
"""

import math

from claw.codegen.blockspec import CALL_STYLE, SEQ_INPUT, set_state
from claw.codegen.ir import OPS

# 순수 연산의 Python 구현. C 구현은 emit_c.py가 갖는다 (원시 블록과 같은 취급 —
# 집합이 고정·유한하고 대조 테스트로 못박는다). 연산 순서는 원본 자구 그대로:
# autopilot.py:161·170의 `1.0 / math.cos(φ) - 1.0`, `1.0 / math.cos(φ) ** 2 - 1.0`
_OP_FN = {
    "wrap_pi": lambda a: -((-a + math.pi) % (2.0 * math.pi) - math.pi),
    "min2": lambda a, b: min(a, b),
    "gt": lambda a, b: 1.0 if a > b else 0.0,
    "add_const": lambda a, c: a + c,
    "sec_minus_1": lambda a: 1.0 / math.cos(a) - 1.0,
    "sec2_minus_1": lambda a: 1.0 / math.cos(a) ** 2 - 1.0,
}
assert set(_OP_FN) == set(OPS), "OPS와 Python 구현 목록이 어긋남"


def execute_node(instances, env, node) -> None:
    """노드 하나 실행 — env[node.id]를 채우고 필요하면 인스턴스 상태를 갱신한다.

    GraphRunner.step_all의 본문이던 것을 함수로 뺀 것뿐이다(동작 불변) — 유닛
    검증(claw.verify.units)이 **파티션 노드 부분열**을 같은 의미론으로 실행해야
    해서다. 실행 규칙이 두 곳에 적히면 유닛 오라클과 전체 실행이 갈라진다.
    """
    enable = getattr(node, "enable", None)
    if enable is not None and not env[enable]:
        for field, value in node.on_disable.items():
            set_state(
                instances[node.id],
                field,
                env[value] if isinstance(value, str) else value,
            )
        env[node.id] = node.disabled_output
        return
    if node.kind == "op":
        args = [env[r] for r in node.inputs]
        if node.value is not None:
            args.append(node.value)
        env[node.id] = float(_OP_FN[node.op](*args))
        return
    inst = instances[node.id]
    args = [env[r] for r in node.inputs]
    gains = {port: env[ref] for port, ref in node.gains.items()}
    style = CALL_STYLE.get(type(inst))
    if style == "positional":
        env[node.id] = inst.step(*args)  # CommandFilter.step(cmd, current)
    elif style == "positional+gains":
        # PID.step(e, u_ext, kp=, ki=) — 입력이 하나면 u_ext는 기본 0
        env[node.id] = inst.step(*args, **gains)
    else:
        u = tuple(args) if type(inst) in SEQ_INPUT else args[0]
        env[node.id] = inst.step(u, **gains)


class GraphRunner:
    """IR + 샘플주기 → 실행 가능한 제어법칙 한 덩이."""

    def __init__(self, graph, dt: float):
        if dt <= 0:
            raise ValueError(f"dt는 양수여야 함: {dt}")
        self.graph = graph
        self.dt = float(dt)
        # node_id → 블록 인스턴스 (init(dt) 완료). C 생성기가 구운 계수를 읽는 원천
        self.instances = {
            n.id: n.block(**n.params).init(self.dt)
            for n in graph.nodes
            if n.kind == "block"
        }
        self._hold = dict.fromkeys(graph.outputs, 0.0)
        self.last_env = {}  # 직전 스텝 중간 노드 값 (계측 전용 — step_all이 채운다)

    def reset(self, states=None, hold=None) -> None:
        """states={node_id: 웜스타트 값} — 미지정 노드는 파라미터 초기상태 (범프리스 계약).

        hold={출력명: 값} — 그래프 enable이 처음부터 0일 때 낼 값. 손으로 쓴 법칙은
        트림 웜스타트로 홀드 명령을 재구성하지만(`law.py:77`), 생성 코드에서는
        상태 필드와 마찬가지로 통합 계층이 채운다.
        """
        states = states or {}
        unknown = set(states) - set(self.instances)
        if unknown:
            raise KeyError(f"미정의 노드 웜스타트: {sorted(unknown)}")
        for node_id, inst in self.instances.items():
            inst.reset(states.get(node_id))
        self._hold = dict.fromkeys(self.graph.outputs, 0.0)
        for name, value in (hold or {}).items():
            if name not in self._hold:
                raise KeyError(f"미정의 출력 홀드: {name!r}")
            self._hold[name] = float(value)

    @property
    def last_outputs(self) -> dict:
        """직전 스텝의 그래프 출력 {출력명: 값} — 계측 전용 (읽기만 할 것).

        홀드 스텝(enable=0)을 포함해 "마지막으로 내보낸 값"이다 — 생성 C의
        `sta->hold`와 같은 의미라, 대조 기록(claw.verify.trace)이 출력 개수·이름에
        관계없이 같은 것을 읽을 수 있다. 법칙 경로는 읽지 않는다.
        """
        return dict(self._hold)

    def _result(self, values):
        return next(iter(values.values())) if len(values) == 1 else dict(values)

    def step(self, **inputs):
        """출력이 하나면 값을, 여럿이면 {출력명: 값}을 낸다 — 생성 C의 규약과 같다."""
        return self._result(self.step_all(**inputs))

    def step_all(self, **inputs) -> dict:
        """항상 {출력명: 값}. 출력 개수에 따라 반환형이 달라지면 곤란한 호출자용."""
        missing = set(self.graph.inputs) - set(inputs)
        extra = set(inputs) - set(self.graph.inputs)
        if missing or extra:
            raise TypeError(
                f"{self.graph.name} 입력 불일치 — 누락 {sorted(missing)}, 잉여 {sorted(extra)}"
            )
        # 그래프 enable 0 = 아무것도 실행하지 않고 직전 출력 유지 (상태도 동결)
        if self.graph.enable is not None and not inputs[self.graph.enable]:
            return dict(self._hold)

        env = dict(inputs)
        for node in self.graph.nodes:
            execute_node(self.instances, env, node)

        # 중간 노드 값 공개 — 계측 전용 창구 (읽기만 할 것). 그래프 출력(=생성 C의
        # 인터페이스)은 그대로이므로 코드 생성에 영향이 없다. 법칙 경로는 읽지 않는다.
        # enable=0 스텝은 위에서 조기 반환하므로 직전 env가 남는다 — 출력 홀드와
        # 같은 규약이다 (실행되지 않은 스텝이 0으로 보이면 계측이 거짓말을 한다).
        self.last_env = env
        self._hold = {name: env[nid] for name, nid in self.graph.outputs.items()}
        return dict(self._hold)
