"""제어법칙 구조의 중간 표현(IR) — 구조를 코드가 아니라 데이터로 적는다 (02 §2.2·§4).

지금 제어법칙의 구조는 명령형 Python 안에 있다. 예컨대 `scas.py:73`의
"워시아웃 → 게인 → PID와 합산 → 포화"는 사람은 읽지만 프로그램은 읽을 수 없어
탑재 C를 뽑을 수 없다. IR은 그 연결을 노드 목록 + 참조로 적은 것으로,
Simulink의 .slx가 맡는 자리다. 파라미터는 이미 데이터고(ParamDef → JSON 스키마
→ 웹 폼) IR은 **구조에 같은 일**을 한다.

소비자는 둘이며 **같은 IR을 읽는다** — 그래서 어긋날 수 없다:
    ir_exec.py  → Python 실행 (설계·시뮬, 대조 기준)
    emit_c.py   → 탑재 C 생성

**C 생성 가능 제약을 IR 단계에서 강제한다**: 선언 순서 = 실행 순서(전방 참조 금지
→ 대수 루프 원천 차단), 정적 크기, 출력에 도달하지 않는 노드 금지(생성 C에
dead code를 만들지 않는다 — DO-178C 논점). "Python으로는 되는데 C로는 안 되는"
그래프를 애초에 만들 수 없어야, 나중의 C 전환이 재작업이 아니라 백엔드 추가가 된다.

블록 로직 자체는 여기 없다 — 노드는 엔진 블록 클래스(M2 `claw.blocks`)를 가리키기만
한다. 실행은 그 블록 인스턴스가, C 생성은 블록별 에미터가 맡는다.
"""

import re

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 생성 C가 그대로 쓰는 이름이므로 C 예약어와 충돌하면 안 된다
_C_KEYWORDS = frozenset(
    """auto break case char const continue default do double else enum extern float for
    goto if inline int long register restrict return short signed sizeof static struct
    switch typedef union unsigned void volatile while""".split()
)

# 상태 없는 순수 연산 — 이름 → 입력 개수. 실제 연산은 실행기·에미터가 보유한다
# (여기 두면 IR이 계산을 갖게 되고, 그러면 정본이 둘로 쪼개진다)
OPS = {"wrap_pi": 1}


def _check_ident(name, what):
    if not isinstance(name, str) or not _IDENT.match(name):
        raise ValueError(f"{what}는 C 식별자여야 함: {name!r}")
    if name in _C_KEYWORDS:
        raise ValueError(f"{what}가 C 예약어와 충돌: {name!r}")


class Node:
    """블록 노드 — 엔진 블록 클래스 + 생성자 인자 + 입력 연결.

    inputs: 소스 참조 튜플 (그래프 입력명 또는 **앞서 선언된** 노드 id)
    gains:  스텝마다 덮어쓰는 게인 포트 {포트명: 소스 참조}. 게인 스케줄이 붙으면
            게인은 파라미터가 아니라 신호가 된다(`controllers.py:46`
            PID.step(e, kp=, ki=)) — 포트로 모델링해야 스케줄 유무가 구조 분기가
            아니라 연결 차이가 된다.
    """

    kind = "block"

    def __init__(self, id, block, inputs=(), params=None, gains=None):
        _check_ident(id, "노드 id")
        self.id = id
        self.block = block
        self.inputs = tuple(inputs)
        self.params = dict(params or {})
        self.gains = dict(gains or {})
        if not self.inputs:
            raise ValueError(f"{id}: 입력이 없는 블록 노드 — 상수는 파라미터로 둔다")
        for port in self.gains:
            _check_ident(port, f"{id} 게인 포트")

    @property
    def refs(self):
        return self.inputs + tuple(self.gains.values())

    def __repr__(self):
        return f"Node({self.id!r}, {self.block.__name__}, inputs={self.inputs})"


class Op:
    """상태 없는 순수 연산 노드 — 블록으로 두기엔 과한 것(wrap_pi 등)."""

    kind = "op"
    params = {}
    gains = {}

    def __init__(self, id, op, inputs=()):
        _check_ident(id, "노드 id")
        if op not in OPS:
            raise ValueError(f"미정의 연산 {op!r} — 허용: {sorted(OPS)}")
        inputs = tuple(inputs)
        if len(inputs) != OPS[op]:
            raise ValueError(f"{id}: {op}는 입력 {OPS[op]}개 필요, {len(inputs)}개 받음")
        self.id = id
        self.op = op
        self.inputs = inputs

    @property
    def refs(self):
        return self.inputs

    def __repr__(self):
        return f"Op({self.id!r}, {self.op!r}, inputs={self.inputs})"


class Graph:
    """제어법칙 한 덩이의 구조. 생성 시점에 C 생성 가능 제약을 전부 검사한다.

    선언 순서가 곧 실행 순서다 — 각 노드는 이미 정의된 것만 참조할 수 있다.
    이 하나로 대수 루프가 원천 차단되고(전방 참조 불가), 생성 C의 문장 순서가
    IR 선언과 1:1이 되어 사람이 대조해 읽을 수 있다.
    """

    def __init__(self, name, inputs, nodes, output):
        _check_ident(name, "그래프 이름")
        self.name = name
        self.inputs = tuple(inputs)
        self.nodes = tuple(nodes)
        self.output = output

        for u in self.inputs:
            _check_ident(u, "그래프 입력명")
        if len(set(self.inputs)) != len(self.inputs):
            raise ValueError(f"{name}: 중복된 그래프 입력명 {self.inputs}")
        if not self.nodes:
            raise ValueError(f"{name}: 노드가 없는 그래프")

        defined = set(self.inputs)
        for node in self.nodes:
            if node.id in defined:
                raise ValueError(
                    f"{name}: 이름 충돌 {node.id!r} — 노드 id는 그래프 입력·다른 노드와 달라야 함"
                )
            for ref in node.refs:
                if ref not in defined:
                    # 아직 선언되지 않았다면 전방 참조(=대수 루프이거나 순서 오류)
                    later = any(n.id == ref for n in self.nodes)
                    reason = "전방 참조 — 대수 루프이거나 선언 순서 오류" if later else "미정의 참조"
                    raise ValueError(f"{name}.{node.id}: {reason}: {ref!r}")
            defined.add(node.id)

        if self.output not in {n.id for n in self.nodes}:
            raise ValueError(f"{name}: 출력 {output!r}이 노드 id가 아님")

        dead = sorted(defined - self._reachable() - set(self.inputs))
        if dead:
            raise ValueError(
                f"{name}: 출력에 도달하지 않는 노드 {dead} — 생성 C에 dead code가 된다"
            )

    def _reachable(self):
        """출력에서 역방향으로 도달 가능한 노드 id (선언 순서가 위상 순서라 1회 역주행)."""
        by_id = {n.id: n for n in self.nodes}
        seen = {self.output}
        for node in reversed(self.nodes):
            if node.id in seen:
                seen.update(r for r in node.refs if r in by_id)
        return seen

    def node(self, node_id):
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def __repr__(self):
        return f"Graph({self.name!r}, inputs={self.inputs}, nodes={len(self.nodes)})"
