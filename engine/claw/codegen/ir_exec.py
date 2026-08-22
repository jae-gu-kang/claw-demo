"""IR의 Python 백엔드 — 그래프를 엔진 블록 인스턴스로 실행한다 (02 §2.2).

블록 로직을 **다시 구현하지 않는다**. 노드가 가리키는 M2 블록(`claw.blocks`)을
그대로 생성해 `init(dt)` → `step()`을 부를 뿐이다. 그래서 IR 실행 결과는 손으로 쓴
기존 제어법칙(`fcl/scas.py` 등)과 비트 단위로 같아야 하고, 이것이 IR이 구조를
옳게 옮겼는지 판정하는 기준이 된다.

부수 효과가 하나 더 있다 — `init(dt)`를 태우고 나면 각 인스턴스가 **이산 계수를
이미 갖고 있다**(예: `Washout._p = exp(-dt/tau)`, `filters.py:29`). C 생성기는
그 값을 인스턴스에서 그대로 읽어 구우므로, 이산화 공식이 어디에도 두 번 적히지
않는다 (`emit_c.py` 참조).

입력 전달 계약: 노드 입력이 1개면 스칼라, 2개 이상이면 시퀀스로 넘긴다 —
엔진 블록 계약과 같다(`basic.py:22` Sum·Product는 시퀀스를 받는다).
"""

import math

from claw.codegen.ir import OPS

# 순수 연산의 Python 구현. C 구현은 emit_c.py가 갖는다 (원시 블록과 같은 취급 —
# 집합이 고정·유한하고 대조 테스트로 못박는다)
_OP_FN = {
    "wrap_pi": lambda a: -((-a + math.pi) % (2.0 * math.pi) - math.pi),
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

    def reset(self, states=None) -> None:
        """states={node_id: 웜스타트 값} — 미지정 노드는 파라미터 초기상태 (범프리스 계약)."""
        states = states or {}
        unknown = set(states) - set(self.instances)
        if unknown:
            raise KeyError(f"미정의 노드 웜스타트: {sorted(unknown)}")
        for node_id, inst in self.instances.items():
            inst.reset(states.get(node_id))

    def step(self, **inputs):
        missing = set(self.graph.inputs) - set(inputs)
        extra = set(inputs) - set(self.graph.inputs)
        if missing or extra:
            raise TypeError(
                f"{self.graph.name} 입력 불일치 — 누락 {sorted(missing)}, 잉여 {sorted(extra)}"
            )
        env = dict(inputs)
        for node in self.graph.nodes:
            if node.kind == "op":
                env[node.id] = float(_OP_FN[node.op](*(env[r] for r in node.inputs)))
                continue
            u = (
                env[node.inputs[0]]
                if len(node.inputs) == 1
                else tuple(env[r] for r in node.inputs)
            )
            gains = {port: env[ref] for port, ref in node.gains.items()}
            env[node.id] = self.instances[node.id].step(u, **gains)
        return env[self.graph.output]
