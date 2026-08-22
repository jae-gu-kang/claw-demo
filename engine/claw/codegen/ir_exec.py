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
            enable = getattr(node, "enable", None)
            if enable is not None and not env[enable]:
                for field, value in node.on_disable.items():
                    set_state(
                        self.instances[node.id],
                        field,
                        env[value] if isinstance(value, str) else value,
                    )
                env[node.id] = node.disabled_output
                continue
            if node.kind == "op":
                args = [env[r] for r in node.inputs]
                if node.value is not None:
                    args.append(node.value)
                env[node.id] = float(_OP_FN[node.op](*args))
                continue
            inst = self.instances[node.id]
            args = [env[r] for r in node.inputs]
            gains = {port: env[ref] for port, ref in node.gains.items()}
            if CALL_STYLE.get(type(inst)) == "positional":
                env[node.id] = inst.step(*args)  # CommandFilter.step(cmd, current)
            else:
                u = tuple(args) if type(inst) in SEQ_INPUT else args[0]
                env[node.id] = inst.step(u, **gains)

        self._hold = {name: env[nid] for name, nid in self.graph.outputs.items()}
        return dict(self._hold)
