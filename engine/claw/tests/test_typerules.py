"""블록·연산 타입 규칙과 전방 추론 (07 §8 · 07 §10).

이 파일이 지키는 것은 셋이다.

두 백엔드가 이 모듈을 import하지 않는다는 것은 여기서 다시 안 본다 —
`test_ir_types.py`의 `test_두_백엔드는_타입_모듈을_임포트하지_않는다`가 `irtypes`와
`typerules`를 **함께** 이름으로 덮는다. 순회 코드를 두 벌 두면 한쪽만 넓어질 때 갈라진다.

1. **거짓 양성 0** — 실물 아홉 그래프가 전부 통과한다. 서버·영향성·자동설계가 편집
   형상으로 그래프를 수천 번 재조립하므로 거짓 양성 하나가 곧 화면의 500이다.
2. **그런데 실제로 문다** — 합성 반례가 거부된다. 1만 있으면 「아무것도 안 하는 검사」와
   구분이 안 된다.
3. **선언은 추론의 입력이 아니라 대조 대상이다** — 노드 선언을 바꿔도 추론은 안 바뀐다.
"""

import ast
import inspect
from pathlib import Path

import pytest

from claw.blocks.basic import Saturation, Sum, Switch
from claw.codegen import irtypes as it
from claw.codegen import typerules as tr
from claw.codegen.emit_c import _EMITTERS
from claw.codegen.ir import OPS, Graph, Node, Op
from claw.fcl import graphs as g_
from claw.fcl.demo import DEMO_YAW, make_demo_fcl
from claw.plant import make_demo_stall_table

DT = 0.01


def _all_graphs():
    law = make_demo_fcl()
    law.init(DT)
    return {
        "scas_axis": g_.scas_axis_graph("ax", **DEMO_YAW),
        "mixer": g_.mixer_graph(**law.mixer.cfg),
        "limiter": g_.alpha_limiter_graph(stall_table=make_demo_stall_table(), margin=0.05),
        "autopilot": g_.autopilot_graph(**law.autopilot.cfg),
        "autopilot_ports": g_.autopilot_graph(ports=True, **law.autopilot.cfg),
        "scas3": g_.scas3_graph(**law.scas.cfg),
        "scas3_ports": g_.scas3_graph(ports=True, **law.scas.cfg),
        "gain_schedule": g_.gain_schedule_graph(
            tables=law.schedule.tables, filter_tau=law.schedule.filter_tau
        ),
        "fcl": law.runner.graph,
    }


# ── 거짓 양성 0 ───────────────────────────────────────────────────────────


def test_실물_아홉_그래프가_전부_통과한다():
    """거짓 양성 하나가 곧 화면의 500이다 — 편집 형상마다 재조립되기 때문이다."""
    for name, g in _all_graphs().items():
        tr.check_graph(g)  # 어긋나면 TypeConflict


def test_미지정은_아무것과도_충돌하지_않는다():
    """Gain·Lookup·PID 산출끼리 더하는 자리가 실물에 널려 있다 (`Sum(pid, damp)`).

    미지정을 「모른다」가 아니라 「모순」으로 다루면 그 자리가 전부 거부된다 — 실제로
    그렇게 만들었다가 일곱 그래프 중 다섯이 죽었다.
    """
    assert tr.unify(None, it.ANGLE) is it.ANGLE
    assert tr.unify(it.ANGLE, None) is it.ANGLE
    assert tr.unify(it.REAL, it.AIRSPEED) is it.AIRSPEED
    assert tr.unify_all([None, None]) is None
    assert tr.unify_all([None, it.ANGLE, it.REAL]) is it.ANGLE
    # 그리고 진짜 모순은 여전히 잡는다 — 위가 「전부 통과」가 아님을 함께 못박는다
    assert tr.unify(it.ANGLE, it.AIRSPEED) is tr.CONFLICT
    assert tr.unify(it.ANGLE, it.BOOL) is tr.CONFLICT


def test_추론은_파라미터의_수치를_읽지_않는다():
    """읽기 시작하면 그것은 검사가 아니라 실행이다 (07 §8의 하드 규칙).

    구조가 같고 값만 다른 두 그래프의 추론이 같아야 한다.
    """
    a = tr.check_graph(g_.scas_axis_graph("x", **DEMO_YAW))
    b = tr.check_graph(g_.scas_axis_graph("x", **dict(DEMO_YAW, kp=99.0, out_hi=9.0)))
    assert a == b
    assert any(v is not None for v in a.values()), (
        "추론된 타입이 하나도 없다 — 값만 바꿔도 같은 것이 당연해진다"
    )


# ── 그런데 실제로 문다 ────────────────────────────────────────────────────


def _g(nodes, inputs, outputs, types, **kw):
    return Graph("g", inputs, nodes, outputs, signal_types=types, **kw)


def test_다른_물리량은_나란히_못_놓는다():
    """`Sum`·`min2`·`gt`는 두 값을 나란히 놓는 연산이다."""
    with pytest.raises(tr.TypeConflict, match="나란히 놓았다"):
        tr.check_graph(_g(
            [Node("s", Sum, inputs=("a", "b"), params={"signs": (1.0, 1.0)})],
            ("a", "b"), {"o": "s"}, {"a": it.ANGLE, "b": it.AIRSPEED}))
    with pytest.raises(tr.TypeConflict, match="나란히 놓았다"):
        tr.check_graph(_g([Op("m", "min2", inputs=("a", "b"))],
                          ("a", "b"), {"o": "m"}, {"a": it.ANGLE, "b": it.ALTITUDE}))


def test_wrap_pi는_각도만_받는다():
    with pytest.raises(tr.TypeConflict, match="angle를 받는데"):
        tr.check_graph(_g([Op("w", "wrap_pi", inputs=("a",))],
                          ("a",), {"o": "w"}, {"a": it.ANGULAR_RATE}))
    # 각도면 통과하고 각도를 낸다 — 거부만 하는 검사가 아님을 함께 본다
    inferred = tr.check_graph(_g([Op("w", "wrap_pi", inputs=("a",))],
                                 ("a",), {"o": "w"}, {"a": it.ANGLE}))
    assert inferred["w"] is it.ANGLE


def test_비교는_참거짓을_낳고_할선은_무차원을_낳는다():
    """산출 물리량이 입력과 **다른** 두 연산 — 규칙이 없으면 조용히 각도로 흐른다."""
    with pytest.raises(tr.TypeConflict, match="규칙은 bool"):
        tr.check_graph(_g([Op("c", "gt", inputs=("a", "b"))], ("a", "b"), {"o": "c"},
                          {"a": it.ANGLE, "b": it.ANGLE, "c": it.ANGLE}))
    with pytest.raises(tr.TypeConflict, match="규칙은 dimensionless"):
        tr.check_graph(_g([Op("s", "sec_minus_1", inputs=("a",))], ("a",), {"o": "s"},
                          {"a": it.ANGLE, "s": it.ANGLE}))


def test_참거짓_자리에_온_신호는_불리언이다():
    """`enable`·`Switch` 제어 — 그 자리에 쓰인다는 것이 곧 근거다."""
    with pytest.raises(tr.TypeConflict, match="참·거짓이다"):
        tr.check_graph(_g([Op("y", "wrap_pi", inputs=("x",), enable="e")],
                          ("e", "x"), {"o": "y"}, {"e": it.ANGLE, "x": it.ANGLE}))
    with pytest.raises(tr.TypeConflict, match="참·거짓이다"):
        tr.check_graph(_g(
            [Node("w", Switch, inputs=("a", "c", "b"), params={"threshold": 0.0})],
            ("a", "c", "b"), {"o": "w"},
            {"a": it.ANGLE, "b": it.ANGLE, "c": it.ANGLE}))
    # 불리언이면 통과한다
    tr.check_graph(_g(
        [Node("w", Switch, inputs=("a", "c", "b"), params={"threshold": 0.0})],
        ("a", "c", "b"), {"o": "w"}, {"a": it.ANGLE, "b": it.ANGLE, "c": it.BOOL}))


def test_포화는_물리량을_보존하고_게인은_안_한다():
    """`Gain`을 보존으로 두면 `mix_thr_l_raw = Sum(thr, diff)`가 첫 거짓 양성이 된다.

    `k_diff_thr`의 단위가 `1/rad`라 `diff`는 무차원이고, 스로틀과 더하는 것이 옳다.
    변환이 파라미터 단위에 사는 한 `Gain` 출력은 미지정이 정직하다 (07 §10).
    """
    from claw.blocks.basic import Gain

    keep = tr.check_graph(_g(
        [Node("s", Saturation, inputs=("a",), params={"lo": -1.0, "hi": 1.0})],
        ("a",), {"o": "s"}, {"a": it.ANGLE}))
    assert keep["s"] is it.ANGLE
    lose = tr.check_graph(_g([Node("k", Gain, inputs=("a",), params={"k": 2.0})],
                             ("a",), {"o": "k"}, {"a": it.ANGLE}))
    assert lose["k"] is None, "Gain이 물리량을 보존한다고 두면 거짓 양성이 시작된다"


# ── 선언은 씨앗이 아니라 대조 대상 ────────────────────────────────────────


def test_노드_선언은_추론의_씨앗이_아니다():
    """선언을 먹이면 규칙과 선언이 두 벌이 되어, 갈라져도 조용하다.

    같은 그래프에 노드 선언만 바꿔 넣어도 추론 결과는 그대로여야 한다.
    """
    law = make_demo_fcl()
    law.init(DT)
    g = law.runner.graph
    bare = Graph(g.name, g.inputs, g.nodes, g.outputs, g.enable,
                 signal_types=g_._types_for(g_.FCL_INPUTS))
    assert tr.check_graph(bare) == tr.check_graph(g), (
        "노드 선언 유무가 추론을 바꿨다 — 선언이 씨앗으로 새고 있다"
    )
    assert len(g.signal_types) > len(bare.signal_types), "대조할 노드 선언이 없다"


def test_리미터_사슬이_규칙의_첫_시험지다():
    """실물에 이미 선언이 붙어 있는 유일한 사슬 — 규칙이 그것을 **재현**해야 한다.

    `lim_cap = Sum(theta, a_margin)`이 세 각도로 선언돼 있으니, `Sum` 규칙이 그걸 못
    내면 규칙이 틀린 것이다. 재현하지 못하면 이 테스트가 죽는다.
    """
    inferred = tr.check_graph(_all_graphs()["limiter"])
    assert str(inferred["a_margin"]) == "angle"
    assert str(inferred["cap"]) == "angle"
    assert str(inferred["theta_lim"]) == "angle"
    assert str(inferred["active"]) == "bool"
    # `stall`·`alpha_max`는 Lookup 계열이라 미지정이 맞다 — 「전부 각도」가 아님을 못박는다
    assert inferred["stall"] is None and inferred["alpha_max"] is None


def test_선언과_규칙이_어긋나면_거부한다():
    """대조 대상이라는 말의 실체 — 덮어쓰지도, 무시하지도 않는다."""
    law = make_demo_fcl()
    law.init(DT)
    g = law.runner.graph
    lied = Graph(g.name, g.inputs, g.nodes, g.outputs, g.enable,
                 signal_types=dict(g.signal_types, lim_active=it.ANGLE))
    with pytest.raises(tr.TypeConflict, match="선언은 angle인데"):
        tr.check_graph(lied)


# ── 드리프트 가드 ─────────────────────────────────────────────────────────


def test_규칙표가_어휘와_어긋나지_않는다():
    """연산·블록이 늘면 규칙을 안 적은 채 지나가지 않는다.

    `ir_exec`·`emit_c`가 각각 같은 자리에 둔 가드의 세 번째 짝이다.
    """
    assert set(tr.OP_RULES) == set(OPS)
    assert tr.known_blocks() == frozenset(_EMITTERS), (
        "C 에미터가 있는데 타입 규칙이 없는 블록이 있다 — 그 블록은 조용히 통과한다"
    )
    assert len(_EMITTERS) == 10 and len(OPS) == 6, "어휘 크기가 바뀌었다"


def test_규칙_모듈은_코드를_내지_않는다():
    """검사 패스는 방출자가 아니다 — 파일을 쓰거나 백엔드를 부르면 안 된다.

    **텍스트가 아니라 AST로 본다.** 이 모듈의 주석은 `emit_c`·`ir_exec`를 근거로
    인용하는데(드리프트 가드의 짝이라고), 문자열 검색은 그 인용과 실제 호출을 못 가른다.
    """
    tree = ast.parse(inspect.getsource(tr))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    leaked = {m for m in imported if m.endswith(("emit_c", "ir_exec"))}
    assert not leaked, f"규칙 모듈이 백엔드를 부른다: {leaked}"
    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    } | {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    banned = {"open", "write", "write_text", "emit_c"}
    assert not (called & banned), f"규칙 모듈이 무언가를 내고 있다: {sorted(called & banned)}"
    # 공허하지 않게 — 실제로 호출을 봤는지 함께 확인한다
    assert len(called) > 5, f"호출을 {len(called)}개밖에 못 봤다 — 파싱이 반쪽이다"


# ── 전파와 나머지 규칙 ────────────────────────────────────────────────────
# 위의 리미터 사슬은 네 마디가 전부 한쪽에 **그래프 입력**을 물고 있어 1홉이면 풀린다.
# 그래서 `env[node.id] = out`을 `= None`으로 바꿔 전파를 끊어도 위 테스트들은 통과한다.
# 여기서부터가 여러 홉을 실제로 요구하는 자리다.


def test_추론이_여러_홉을_건너간다():
    """전파를 끊으면(`env[node.id] = None`) 여기가 죽는다 — 사슬을 주장하는 자리다.

    믹서는 `de/da → sum_l → elevon_l`과 `thr → thr_l_raw → thr_l`이 2홉이고, 두 끝이
    계약 경계(`SurfaceCommand`)라 값도 확실하다.
    """
    inferred = tr.check_graph(_all_graphs()["mixer"])
    assert str(inferred["sum_l"]) == "angle", "1홉이 안 갔다"
    assert str(inferred["elevon_l"]) == "angle", "2홉이 안 갔다"
    assert str(inferred["elevon_r"]) == "angle"
    assert str(inferred["thr_l"]) == "normalized", "스로틀 사슬이 안 갔다"
    assert str(inferred["thr_r"]) == "normalized"
    # 오토파일럿은 네 홉이다: cmd_pitch → pitch_sat → theta_src → theta_ff → theta_out
    ap = tr.check_graph(_all_graphs()["autopilot"])
    assert str(ap["theta_out"]) == "angle", "Saturation·Switch·Sum을 지나는 사슬이 끊겼다"


def test_명령_필터는_두_입력을_통일한다():
    """`CommandFilter(명령, 측정)` — 규칙을 통째로 지워도 아무도 안 죽던 자리."""
    from claw.blocks.filters import CommandFilter

    node = [Node("f", CommandFilter, inputs=("a", "b"), params={"tau": 0.5})]
    with pytest.raises(tr.TypeConflict, match="나란히 놓았다"):
        tr.check_graph(_g(node, ("a", "b"), {"o": "f"},
                          {"a": it.ALTITUDE, "b": it.AIRSPEED}))
    ok = tr.check_graph(_g(node, ("a", "b"), {"o": "f"},
                           {"a": it.ALTITUDE, "b": it.ALTITUDE}))
    assert ok["f"] is it.ALTITUDE


def test_Switch의_두_갈래는_통일된다():
    """제어가 불리언이어도 값 갈래가 다른 물리량이면 거부한다 — 별개의 규칙이다."""
    node = [Node("w", Switch, inputs=("a", "c", "b"), params={"threshold": 0.0})]
    with pytest.raises(tr.TypeConflict, match="나란히 놓았다"):
        tr.check_graph(_g(node, ("a", "c", "b"), {"o": "w"},
                          {"a": it.ANGLE, "c": it.BOOL, "b": it.AIRSPEED}))
    ok = tr.check_graph(_g(node, ("a", "c", "b"), {"o": "w"},
                           {"a": it.ANGLE, "c": it.BOOL, "b": it.ANGLE}))
    assert ok["w"] is it.ANGLE


def test_Washout도_물리량을_보존한다():
    """`_pass_rule`이 `Saturation`으로만 핀돼 있었다 — 같은 규칙을 쓰는 둘째 블록."""
    from claw.blocks.filters import Washout

    out = tr.check_graph(_g([Node("w", Washout, inputs=("a",), params={"tau": 2.0})],
                            ("a",), {"o": "w"}, {"a": it.ANGULAR_RATE}))
    assert out["w"] is it.ANGULAR_RATE


def test_할선_둘이_같은_규칙을_쓴다():
    """`sec2_minus_1`은 `sec_minus_1`의 쌍둥이다 — 복사본이 조용히 갈라지는 전형."""
    for op in ("sec_minus_1", "sec2_minus_1"):
        out = tr.check_graph(_g([Op("s", op, inputs=("a",))], ("a",), {"o": "s"},
                                {"a": it.ANGLE}))
        assert out["s"] is it.DIMENSIONLESS, f"{op}가 무차원을 안 낸다"
        with pytest.raises(tr.TypeConflict, match="angle를 받는데"):
            tr.check_graph(_g([Op("s", op, inputs=("a",))], ("a",), {"o": "s"},
                              {"a": it.AIRSPEED}))


def test_곱과_다항도_물리량을_잃는다():
    """「top이다」가 Gain·Lookup·PID 셋만 핀돼 있었다. `Product`는 스케줄 게인이 붙은
    축의 `damp`가 전부 그것이라 실물에서 자주 지난다.
    """
    from claw.blocks.basic import Product
    from claw.blocks.lookup import PolyBlock
    from claw.tables import PolyTable

    out = tr.check_graph(_g([Node("p", Product, inputs=("a", "b"))], ("a", "b"),
                            {"o": "p"}, {"a": it.ANGLE, "b": it.ANGLE}))
    assert out["p"] is None, "곱이 물리량을 보존한다고 두면 차원해석 없이 거짓말이 된다"
    poly = PolyTable("mach", [{"x0": 0.0, "x1": 2.0, "coeffs": [1.0, 0.5],
                               "c": 1.0, "h": 1.0}])
    out = tr.check_graph(_g([Node("q", PolyBlock, inputs=("a",), params={"table": poly})],
                            ("a",), {"o": "q"}, {"a": it.MACH}))
    assert out["q"] is None


def test_비교는_입력_물리량을_가리지_않는다():
    """규칙을 **더 엄하게** 만드는 변이에도 지킴이가 필요하다 — 제약 4를 지키는 방향이다.

    `gt`가 각도만 받게 조이면 `mach > 0.8` 같은 정당한 비교가 거부된다.
    """
    for ty in (it.MACH, it.AIRSPEED, it.ALTITUDE, it.ANGLE):
        out = tr.check_graph(_g([Op("c", "gt", inputs=("a", "b"))], ("a", "b"),
                                {"o": "c"}, {"a": ty, "b": ty}))
        assert out["c"] is it.BOOL


def test_명시적_미지정은_참거짓_자리에서_거부되지_않는다():
    """이 저장소는 **의도한 미지정을 명시적 `Type`으로 적는 것**을 규약으로 삼았다
    (`fcl/graphs.py`의 `fuel`·`SCHEDULED_GAIN`). 그 표기가 곧 트리거 값이면 안 된다 —
    「미지정은 무엇과도 통일된다」를 선언해 놓고 미지정이라 부르며 거부하는 꼴이 된다.
    """
    for top in (it.REAL, g_.SCHEDULED_GAIN, g_.SIGNAL_TYPES["fuel"]):
        tr.check_graph(_g([Op("y", "wrap_pi", inputs=("x",), enable="e")],
                          ("e", "x"), {"o": "y"}, {"e": top, "x": it.ANGLE}))
    # 그래도 확실히 다른 것은 여전히 거부한다
    with pytest.raises(tr.TypeConflict, match="참·거짓이다"):
        tr.check_graph(_g([Op("y", "wrap_pi", inputs=("x",), enable="e")],
                          ("e", "x"), {"o": "y"}, {"e": it.ANGLE, "x": it.ANGLE}))


def test_통일은_교환적이고_범위를_안_버린다():
    """독스트링이 「교집합」이라고 적었으니 그것이 사실이어야 한다."""
    a = it.Type(quantity="angle", lo=-1.0, hi=1.0)
    b = it.Type(quantity="angle", lo=-3.0, hi=3.0)
    assert tr.unify(a, b) == tr.unify(b, a) == a, "먼저 온 쪽을 고르면 교환법칙이 깨진다"
    half_lo = it.Type(quantity="angle", lo=-1.0)
    half_hi = it.Type(quantity="angle", hi=1.0)
    both = tr.unify(half_lo, half_hi)
    assert (both.lo, both.hi) == (-1.0, 1.0), "반쪽 범위 하나를 조용히 버렸다"
    # 겹치지 않는 범위로 거부를 만들지는 않는다 — 범위는 힘이 없는 메타데이터다
    far = tr.unify(it.Type(quantity="angle", lo=5.0),
                   it.Type(quantity="angle", hi=1.0))
    assert far is not tr.CONFLICT and (far.lo, far.hi) == (None, None)
    # 합성해서 불러도 터지지 않는다
    assert tr.unify(tr.unify(it.ANGLE, it.AIRSPEED), it.ANGLE) is tr.CONFLICT
