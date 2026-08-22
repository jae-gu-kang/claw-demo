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

**모드 분기는 enable 영역으로 표현한다.** 제어법칙에는 "축이 비활성이면 필터가
측정을 추적하고 적분기를 소거한다" 같은 상태 부작용이 있어(`autopilot.py:147`),
순수 데이터흐름만으로는 표현되지 않는다. Simulink의 Enabled Subsystem과 같은
의미론을 노드 단위로 둔다 — 같은 enable을 가진 연속 노드가 한 영역이고, 비활성
스텝에는 노드가 실행되지 않는 대신 `on_disable`로 상태를 대입한다.

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
# (여기 두면 IR이 계산을 갖게 되고, 그러면 정본이 둘로 쪼개진다).
# sec_minus_1·sec2_minus_1은 선회 피드포워드 보상항(01 §3.3.1)의 도메인 원시항이다.
OPS = {
    "wrap_pi": 1,  # (-π, π] 래핑
    "min2": 2,  # min(a, b)
    "gt": 2,  # a > b → 1.0 / 0.0 (불리언은 0/1 double로 나른다)
    "add_const": 1,  # u + c  (상수 편차 — Simulink Bias 대응)
    "sec_minus_1": 1,  # 1/cos φ − 1   (선회 피치 FF)
    "sec2_minus_1": 1,  # 1/cos²φ − 1  (선회 스로틀 FF)
}

# 상수 파라미터를 갖는 연산 — 블록을 새로 만들지 않고 상수를 다루기 위한 최소 장치
OPS_VALUE = frozenset({"add_const"})


# 생성 C의 함수 인자로 쓰는 이름 — 그래프 입력이 이걸 가리면 `prm->x`가 깨진다.
# (실제로 겪었다: 롤 각속도 입력 `p`가 파라미터 포인터 `p`를 가려 컴파일이 깨졌다)
_RESERVED_ARGS = frozenset({"prm", "sta", "out"})


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
    enable: 활성 신호 참조. 0이면 이 노드는 **실행되지 않고** on_disable만 수행한다
    on_disable: {상태 필드: 값 또는 소스 참조} — 비활성 스텝의 상태 대입.
            숫자는 상수, 문자열은 신호 참조 (예: 비활성 축 필터가 측정을 추적)
    disabled_output: 비활성 스텝의 이 노드 출력값 [기본 0.0]
    """

    kind = "block"

    def __init__(
        self,
        id,
        block,
        inputs=(),
        params=None,
        gains=None,
        enable=None,
        on_disable=None,
        disabled_output=0.0,
    ):
        _check_ident(id, "노드 id")
        self.id = id
        self.block = block
        self.inputs = tuple(inputs)
        self.params = dict(params or {})
        self.gains = dict(gains or {})
        self.enable = enable
        self.on_disable = dict(on_disable or {})
        self.disabled_output = float(disabled_output)
        if not self.inputs:
            raise ValueError(f"{id}: 입력이 없는 블록 노드 — 상수는 파라미터로 둔다")
        for port in self.gains:
            _check_ident(port, f"{id} 게인 포트")
        if self.on_disable and self.enable is None:
            raise ValueError(f"{id}: on_disable은 enable과 함께여야 의미가 있다")

    @property
    def refs(self):
        """이 노드가 읽는 모든 신호 — 위상 검사·도달성의 근거."""
        extra = tuple(v for v in self.on_disable.values() if isinstance(v, str))
        en = (self.enable,) if self.enable is not None else ()
        return self.inputs + tuple(self.gains.values()) + extra + en

    def __repr__(self):
        return f"Node({self.id!r}, {self.block.__name__}, inputs={self.inputs})"


class Op:
    """상태 없는 순수 연산 노드 — 블록으로 두기엔 과한 것(wrap_pi·min2 등)."""

    kind = "op"
    params = {}
    gains = {}
    on_disable = {}
    disabled_output = 0.0

    def __init__(self, id, op, inputs=(), value=None, enable=None):
        _check_ident(id, "노드 id")
        if op not in OPS:
            raise ValueError(f"미정의 연산 {op!r} — 허용: {sorted(OPS)}")
        inputs = tuple(inputs)
        if len(inputs) != OPS[op]:
            raise ValueError(f"{id}: {op}는 입력 {OPS[op]}개 필요, {len(inputs)}개 받음")
        if (op in OPS_VALUE) != (value is not None):
            need = "상수 value가 필요" if op in OPS_VALUE else "상수 value를 받지 않음"
            raise ValueError(f"{id}: {op}는 {need}")
        self.id = id
        self.op = op
        self.inputs = inputs
        self.value = value
        self.enable = enable

    @property
    def refs(self):
        return self.inputs + ((self.enable,) if self.enable is not None else ())

    def __repr__(self):
        return f"Op({self.id!r}, {self.op!r}, inputs={self.inputs})"


class Graph:
    """제어법칙 한 덩이의 구조. 생성 시점에 C 생성 가능 제약을 전부 검사한다.

    선언 순서가 곧 실행 순서다 — 각 노드는 이미 정의된 것만 참조할 수 있다.
    이 하나로 대수 루프가 원천 차단되고(전방 참조 불가), 생성 C의 문장 순서가
    IR 선언과 1:1이 되어 사람이 대조해 읽을 수 있다.

    outputs: {출력명: 노드 id}. 1개면 C가 값을 반환하고, 여럿이면 출력 구조체를 채운다
    enable:  그래프 전체의 활성 신호(그래프 입력명). 0이면 **아무것도 실행하지 않고
             직전 출력을 그대로 낸다** — 항법 무효 시 마지막 유효 명령 유지
             (`law.py:86`)가 이 형태다. 상태도 함께 동결된다
    """

    def __init__(self, name, inputs, nodes, outputs, enable=None):
        _check_ident(name, "그래프 이름")
        self.name = name
        self.inputs = tuple(inputs)
        self.nodes = tuple(nodes)
        self.outputs = dict(outputs)
        self.enable = enable

        for u in self.inputs:
            _check_ident(u, "그래프 입력명")
            if u in _RESERVED_ARGS:
                raise ValueError(
                    f"{name}: 그래프 입력 {u!r}은 생성 C의 함수 인자 이름과 충돌한다 "
                    f"(예약: {sorted(_RESERVED_ARGS)})"
                )
        if len(set(self.inputs)) != len(self.inputs):
            raise ValueError(f"{name}: 중복된 그래프 입력명 {self.inputs}")
        if not self.nodes:
            raise ValueError(f"{name}: 노드가 없는 그래프")
        if not self.outputs:
            raise ValueError(f"{name}: 출력이 없는 그래프")
        if enable is not None and enable not in self.inputs:
            raise ValueError(f"{name}: 그래프 enable {enable!r}은 그래프 입력이어야 함")

        node_ids = {n.id for n in self.nodes}
        defined = set(self.inputs)
        for node in self.nodes:
            if node.id in defined:
                raise ValueError(
                    f"{name}: 이름 충돌 {node.id!r} — 노드 id는 그래프 입력·다른 노드와 달라야 함"
                )
            for ref in node.refs:
                if ref not in defined:
                    # 아직 선언되지 않았다면 전방 참조(=대수 루프이거나 순서 오류)
                    later = ref in node_ids
                    reason = "전방 참조 — 대수 루프이거나 선언 순서 오류" if later else "미정의 참조"
                    raise ValueError(f"{name}.{node.id}: {reason}: {ref!r}")
            defined.add(node.id)

        for out_name, node_id in self.outputs.items():
            _check_ident(out_name, "출력명")
            if node_id not in node_ids:
                raise ValueError(f"{name}: 출력 {out_name!r}의 {node_id!r}가 노드 id가 아님")

        self._check_enable_regions()

        dead = sorted(node_ids - self._reachable())
        if dead:
            raise ValueError(
                f"{name}: 출력에 도달하지 않는 노드 {dead} — 생성 C에 dead code가 된다"
            )

    def _check_enable_regions(self):
        """같은 enable을 가진 노드는 연속이어야 한다 — 생성 C가 if/else 한 덩이가 되고,
        읽는 사람이 "이 구간은 이 모드일 때만 돈다"를 눈으로 잡을 수 있다."""
        seen = set()
        prev = None
        for node in self.nodes:
            en = getattr(node, "enable", None)
            if en != prev:
                if en is not None and en in seen:
                    raise ValueError(
                        f"{self.name}.{node.id}: enable {en!r} 영역이 끊겼다 — "
                        "같은 enable 노드는 연속 선언해야 한다"
                    )
                if en is not None:
                    seen.add(en)
                prev = en

    def _reachable(self):
        """출력에서 역방향으로 도달 가능한 노드 id (선언 순서가 위상 순서라 1회 역주행)."""
        by_id = {n.id for n in self.nodes}
        seen = set(self.outputs.values())
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
        return (
            f"Graph({self.name!r}, inputs={self.inputs}, "
            f"nodes={len(self.nodes)}, outputs={list(self.outputs)})"
        )
