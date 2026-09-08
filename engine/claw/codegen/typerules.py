"""블록·연산의 타입 규칙과 그래프 전방 추론 — **검사만 하고 아무것도 만들지 않는다** (07 §8).

이 모듈은 IR의 세 번째 소비자다. 두 백엔드가 타입을 못 읽는 것처럼(`ast` 검사가 단정한다)
이 모듈도 **코드를 내지 않는다** — 읽고, 어긋나면 거부할 뿐이다.

**선언은 추론의 입력이 아니라 대조 대상이다.** 추론은 그래프 입력의 선언에서만 출발하고,
내부 노드에 이미 붙어 있는 선언(α 리미터 사슬·스케줄이 낳는 게인)은 씨앗으로 쓰지 않는다.
추론이 그 노드에 닿으면 **대조**해서 어긋나면 거부한다. 이 방향이라야 선언과 규칙이 두 벌이
안 된다 — 손으로 베낀 사본이면 갈라질 때 조용하지만, 추론이 맞는지 묻는 물음이면 갈라질 때
시끄럽다.

**확신하는 것만 거부한다.** 미지정(top)은 무엇과도 통일된다. Gain·Lookup·PID는 물리량을
바꾸고 그 변환은 **파라미터 단위에 사는데**, 거기까지 읽으면 검사가 아니라 실행이 된다
(07 §8의 하드 규칙: 어떤 규칙도 파라미터의 수치를 읽지 않는다). 그래서 그 블록들의 출력은
top이다. 「Gain은 물리량을 보존한다」로 두고 싶은 유혹이 있지만 `mix_thr_l_raw =
Sum(thr, diff)`가 정당한 반례다 — `diff = Gain(rudder)`인데 `k_diff_thr`의 단위가 `1/rad`라
결과는 무차원이고, 스로틀과 더하는 것이 맞다 (07 §10).

거짓 양성은 곧 화면의 500이다. 서버·영향성·자동설계가 편집 형상으로 그래프를 수천 번
재조립하기 때문이다.
"""

from claw.blocks.basic import Gain, Product, Saturation, Sum, Switch
from claw.blocks.controllers import PID
from claw.blocks.filters import CommandFilter, Washout
from claw.blocks.lookup import LookupBlock, PolyBlock
from claw.codegen import irtypes as it
from claw.codegen.ir import OPS

# ── 통일 ──────────────────────────────────────────────────────────────────


# **`None`은 미지정(top)이고, 충돌은 별도 센티널이다.** 둘을 같은 값으로 쓰면
# 「아무것도 모른다」와 「모순이다」가 구분되지 않는다. `_top_rule`이 내는 값이 곧 「모순」이
# 되어 Gain·Lookup·PID·Product 노드마다 즉시 걸리고, 그 산출끼리 더하는 정당한 자리
# (`Sum(pid, damp)`)도 함께 죽는다. 합쳐 보면 실물 아홉 그래프가 **아홉 다** 거부된다
# (`CONFLICT = None`으로 되돌려 재현할 수 있다).
CONFLICT = object()


def _is_top(t):
    return t is None or (t.kind == "real" and t.quantity is None)


def unify(a, b):
    """두 타입의 통일 — 못 하면 `CONFLICT`. **미지정은 무엇과도 통일된다.**

    `Type`은 값 타입이라 `==`로 비교한다(`desc`는 신원에서 빠져 있고 `lo`/`hi`는 저장 시
    굳는다 — v0.84). 범위는 **의미를 좁힐 뿐 다르게 만들지 않는다**: 같은 물리량이면
    통일되고, 결과는 두 범위의 **교집합**이다. 「먼저 온 쪽」을 고르면 교환법칙이 깨지고
    `unify(Type(angle, lo=-1), Type(angle, hi=1))`이 `hi`를 조용히 버린다.

    교집합이 뒤집히면(겹치는 구간이 없으면) **범위를 버리고 물리량만 남긴다.** 범위는
    07 §8 [확정]대로 아무 힘이 없는 메타데이터라, 그것으로 거부를 만들면 「확신하는 것만
    거부한다」를 어긴다.
    """
    if a is CONFLICT or b is CONFLICT:
        return CONFLICT  # 합성해서 부를 수 있게 — `unify(unify(a, b), c)`가 터지지 않는다
    if _is_top(a):
        return b
    if _is_top(b):
        return a
    if a.kind != b.kind or a.quantity != b.quantity:
        return CONFLICT
    if a.lo is None and a.hi is None:
        return b
    if b.lo is None and b.hi is None:
        return a
    lo = max(x for x in (a.lo, b.lo) if x is not None) if (a.lo, b.lo) != (None, None) else None
    hi = min(x for x in (a.hi, b.hi) if x is not None) if (a.hi, b.hi) != (None, None) else None
    if lo is not None and hi is not None and lo > hi:
        lo = hi = None  # 겹치는 구간이 없다 — 범위로 거부를 만들지는 않는다
    return it.Type(kind=a.kind, quantity=a.quantity, lo=lo, hi=hi,
                   desc=a.desc or b.desc)


def unify_all(types):
    """여럿을 한 번에 — 하나라도 못 붙으면 `CONFLICT`, 전부 미지정이면 `None`."""
    out = None
    for t in types:
        out = unify(out, t)
        if out is CONFLICT:
            return CONFLICT
    return out


# ── 연산 규칙 ─────────────────────────────────────────────────────────────
# (입력 요구, 출력) — 요구가 None이면 무엇이든 받는다. 출력이 callable이면 입력에서 만든다.


def _same(types):
    return unify_all(types)


def _to_bool(types):
    return it.BOOL


def _to_dimensionless(types):
    return it.DIMENSIONLESS


OP_RULES = {
    # 래핑은 각도만 의미가 있고 각도를 낸다
    "wrap_pi": (it.ANGLE, _same),
    # 두 값을 나란히 놓는다 — 같은 물리량이어야 하고 그 물리량을 낸다
    "min2": (None, _same),
    # 비교도 나란히 놓는 것이지만 산출은 참·거짓이다
    "gt": (None, _to_bool),
    # 상수 편차 — 같은 물리량을 더한다 (상수의 단위는 파라미터에 살지만 읽지 않는다)
    "add_const": (None, _same),
    # 1/cos φ − 1: 각도를 받아 **무차원**을 낸다
    "sec_minus_1": (it.ANGLE, _to_dimensionless),
    "sec2_minus_1": (it.ANGLE, _to_dimensionless),
}

# 어휘 드리프트 가드 — `ir_exec`·`emit_c`가 같은 자리에 둔 것의 세 번째 짝.
# 연산이 늘면 규칙을 안 적은 채 지나가지 않는다
assert set(OP_RULES) == set(OPS), (
    f"연산 규칙표가 OPS와 어긋났다: {sorted(set(OPS) ^ set(OP_RULES))}"
)


# ── 블록 규칙 ─────────────────────────────────────────────────────────────


def _sum_rule(types, node):
    """모든 입력이 같은 물리량이어야 하고, 그 물리량을 낸다."""
    return unify_all(types)


def _pass_rule(types, node):
    """첫 입력의 타입을 그대로 — 포화·고역통과는 값을 자를 뿐 물리량을 안 바꾼다."""
    return types[0] if types else None


def _top_rule(types, node):
    """물리량을 바꾸는 블록 — 변환이 파라미터 단위에 살고 우리는 그것을 안 읽는다."""
    return None


def _switch_rule(types, node):
    """`(in1, ctrl, in3)` — 두 값 갈래는 통일되고, 제어는 참·거짓이다."""
    return unify_all([types[0], types[2]]) if len(types) == 3 else None


def _cmdfilter_rule(types, node):
    """`(명령, 측정)` — 명령은 그것이 명령하는 양과 같다. 하나면 그대로 통과."""
    return unify_all(types)


BLOCK_RULES = {
    Sum: _sum_rule,
    Product: _top_rule,      # 물리량끼리의 곱 — 차원해석 없이는 모른다
    Saturation: _pass_rule,
    Washout: _pass_rule,
    Switch: _switch_rule,
    CommandFilter: _cmdfilter_rule,
    Gain: _top_rule,         # 변환이 `k`의 단위에 산다 (`k_diff_thr`: 1/rad)
    PID: _top_rule,          # 변환이 kp·ki·k_rate의 단위에 산다
    LookupBlock: _top_rule,  # 축 → 값, 테이블이 곧 변환이다
    PolyBlock: _top_rule,
}


def known_blocks():
    """규칙이 있는 블록 — 드리프트 가드가 이 집합을 `emit_c._EMITTERS`와 대조한다."""
    return frozenset(BLOCK_RULES)


# ── 그래프 검사 ───────────────────────────────────────────────────────────


class TypeConflict(ValueError):
    """추론과 선언이, 또는 규칙과 실제 입력이 어긋났다."""


def _describe(t):
    return "미지정" if _is_top(t) else str(t)


def check_graph(graph):
    """전방 1회 주행. 반환은 {노드 id: 추론된 타입}이고, 어긋나면 `TypeConflict`.

    **선언된 그래프 입력만이 씨앗이다.** 노드 선언은 대조 대상이라 추론에 안 먹인다 —
    그래서 이 함수를 지워도 선언은 그대로 남고, 반대로 선언을 지워도 추론은 돈다.
    """
    env = {}
    for name in graph.inputs:
        env[name] = graph.signal_types.get(name)

    inferred = {}
    for node in graph.nodes:
        types = [env.get(i) for i in node.inputs]
        op = getattr(node, "op", None)
        if op is not None:
            want, make = OP_RULES[op]
            if want is not None:
                for src, got in zip(node.inputs, types):
                    if unify(want, got) is CONFLICT:
                        raise TypeConflict(
                            f"{graph.name}.{node.id}: {op}는 {_describe(want)}를 받는데 "
                            f"{src!r}가 {_describe(got)}다"
                        )
            out = make(types)
            if out is CONFLICT:
                raise TypeConflict(
                    f"{graph.name}.{node.id}: {op}가 다른 물리량을 나란히 놓았다 "
                    f"{node.inputs} → {[_describe(t) for t in types]}"
                )
        else:
            rule = BLOCK_RULES.get(node.block)
            if rule is None:
                out = None  # 규칙을 모르는 블록은 아무 말도 안 한다
            else:
                out = rule(types, node)
                if out is CONFLICT:
                    raise TypeConflict(
                        f"{graph.name}.{node.id}: {node.block.__name__}이 다른 물리량을 "
                        f"나란히 놓았다 {node.inputs} → {[_describe(t) for t in types]}"
                    )
        env[node.id] = out
        inferred[node.id] = out

    _check_declarations(graph, inferred)
    _check_boolean_positions(graph, env)
    return inferred


def _check_declarations(graph, inferred):
    """추론과 선언을 대조한다 — **선언을 덮어쓰지도, 무시하지도 않는다.**"""
    for name, declared in graph.signal_types.items():
        if name in graph.inputs:
            continue  # 입력 선언은 씨앗이라 대조 대상이 아니다
        got = inferred.get(name)
        if got is None:
            continue  # 규칙이 모르는 자리 — 확신하는 것만 거부한다
        if unify(declared, got) is CONFLICT:
            raise TypeConflict(
                f"{graph.name}.{name}: 선언은 {_describe(declared)}인데 "
                f"규칙은 {_describe(got)}를 낸다"
            )


def _check_boolean_positions(graph, env):
    """참·거짓 자리에 온 신호는 불리언이다 — 그 자리에 쓰인다는 것이 곧 근거다."""
    spots = []
    if graph.enable:
        spots.append((graph.enable, "그래프 enable"))
    for node in graph.nodes:
        if getattr(node, "enable", None):
            spots.append((node.enable, f"{node.id}의 enable"))
        if getattr(node, "block", None) is Switch and len(node.inputs) == 3:
            spots.append((node.inputs[1], f"{node.id}의 Switch 제어"))
    for signal, where in spots:
        got = env.get(signal)
        # `_is_top`으로 본다. `is not None`으로 두면 **명시적 미지정**이 걸린다 —
        # `it.REAL`이나 `SCHEDULED_GAIN`처럼 「봤는데 물리량을 못 정한다」를 적어 둔
        # 타입이 그것이고, 이 저장소는 그 표기를 규약으로 삼았다(`fcl/graphs.py`의
        # `fuel`·게인 포트). 오류 문구가 「미지정다」라고 부르면서 거부하고 있었다.
        if not _is_top(got) and got.kind != "bool":
            raise TypeConflict(
                f"{graph.name}: {where}에 {signal!r}이 왔는데 {_describe(got)}다 — "
                "그 자리는 참·거짓이다"
            )
