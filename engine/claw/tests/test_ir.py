"""M16 codegen — IR 제약·실행·C 생성 (구현 문서 §2.2).

IR의 가치는 "구조를 데이터로 옮겼다"가 아니라 **옮긴 것이 원본과 같다**는 데 있다.
그래서 여기서 가장 무거운 단정은 손으로 쓴 제어법칙과의 비트 일치다.
"""

import math

import pytest

from claw.blocks.basic import Gain, Product, Saturation
from claw.blocks.controllers import PID
from claw.blocks.dynamics import Integrator
from claw.blocks.filters import Washout
from claw.codegen import GraphRunner, emit_c, scas_axis_graph
from claw.codegen.ir import Graph, Node, Op
from claw.fcl.demo import DEMO_PITCH, DEMO_YAW
from claw.fcl.scas import ScasAxis

DT = 0.01


def _gain_graph(name="g1"):
    return Graph(name, inputs=("u",), nodes=[Node("k", Gain, inputs=("u",))], output="k")


# ── C 생성 가능 제약 ──────────────────────────────────────────────────────
# 이 제약이 IR 단계에서 막히지 않으면 "Python으로는 되는데 C로는 안 되는" 그래프가
# 만들어지고, 그때 가서 다시 쓰게 된다.


def test_전방_참조는_대수_루프로_거부된다():
    with pytest.raises(ValueError, match="전방 참조"):
        Graph(
            "loop",
            inputs=("u",),
            nodes=[
                Node("a", Gain, inputs=("b",)),  # 아직 없는 b를 참조
                Node("b", Gain, inputs=("u",)),
            ],
            output="a",
        )


def test_미정의_참조는_거부된다():
    with pytest.raises(ValueError, match="미정의 참조"):
        Graph("g", inputs=("u",), nodes=[Node("a", Gain, inputs=("nope",))], output="a")


def test_출력에_도달하지_않는_노드는_거부된다():
    """생성 C에 dead code를 남기지 않는다 (DO-178C 논점)."""
    with pytest.raises(ValueError, match="dead code"):
        Graph(
            "g",
            inputs=("u",),
            nodes=[
                Node("used", Gain, inputs=("u",)),
                Node("orphan", Gain, inputs=("u",)),  # 아무도 안 쓴다
            ],
            output="used",
        )


def test_노드_id가_그래프_입력과_충돌하면_거부된다():
    with pytest.raises(ValueError, match="이름 충돌"):
        Graph("g", inputs=("u",), nodes=[Node("u", Gain, inputs=("u",))], output="u")


def test_C_예약어와_비식별자는_이름으로_쓸_수_없다():
    with pytest.raises(ValueError, match="예약어"):
        Node("double", Gain, inputs=("u",))
    with pytest.raises(ValueError, match="C 식별자"):
        Graph("g", inputs=("u-1",), nodes=[Node("k", Gain, inputs=("u-1",))], output="k")


def test_출력이_노드가_아니면_거부된다():
    with pytest.raises(ValueError, match="출력"):
        Graph("g", inputs=("u",), nodes=[Node("k", Gain, inputs=("u",))], output="u")


def test_연산_노드의_입력_개수는_검증된다():
    with pytest.raises(ValueError, match="입력 1개 필요"):
        Op("w", "wrap_pi", ("a", "b"))
    with pytest.raises(ValueError, match="미정의 연산"):
        Op("w", "없는연산", ("a",))


# ── IR ≡ 손으로 쓴 제어법칙 ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cfg", "scheduled"),
    [
        (DEMO_PITCH, ()),  # 워시아웃 없음 + 상수 게인
        (DEMO_PITCH, ("kp", "ki", "k_rate")),  # 게인이 신호(스케줄 경로)
        (DEMO_YAW, ()),  # 워시아웃 있음
        (DEMO_YAW, ("kp", "ki")),  # 일부만 스케줄
    ],
)
def test_IR_실행이_ScasAxis와_비트_일치(cfg, scheduled):
    oracle = ScasAxis(**cfg).init(DT)
    oracle.reset()
    runner = GraphRunner(scas_axis_graph("ax", scheduled=scheduled, **cfg), DT)
    runner.reset()
    for k in range(300):
        t = k * DT
        att_err = 0.4 * math.sin(2.0 * t) + (0.6 if t < 1.0 else 0.0)  # 포화 진입
        rate = 0.3 * math.cos(3.0 * t)
        gains = {g: cfg[g] * (1.0 + 0.3 * math.sin(t)) for g in scheduled}
        assert oracle.step(att_err, rate, **gains) == runner.step(
            att_err=att_err, rate=rate, **gains
        ), f"스텝 {k}에서 어긋남"


def test_게인_스케줄_유무가_구조에_드러난다():
    """스케줄된 게인은 신호(포트)라 파라미터가 아니다 — 구조 분기가 아니라 연결 차이."""
    fixed = scas_axis_graph("f", scheduled=(), **DEMO_PITCH)
    sched = scas_axis_graph("s", scheduled=("kp", "ki", "k_rate"), **DEMO_PITCH)
    assert fixed.inputs == ("att_err", "rate")
    assert sched.inputs == ("att_err", "rate", "kp", "ki", "k_rate")
    assert fixed.node("damp").block is Gain  # 상수 게인 → Gain 블록
    assert sched.node("damp").block is Product  # 신호 × rate' → Product


def test_웜스타트는_노드별로_주입된다():
    """범프리스 전환 계약 — 리셋 시 적분기·필터 상태를 지정할 수 있어야 한다."""
    runner = GraphRunner(scas_axis_graph("ax", **DEMO_YAW), DT)
    runner.reset({"pid": 0.1, "wo": 0.2})
    assert runner.instances["pid"]._i == 0.1
    assert runner.instances["wo"]._x == 0.2
    with pytest.raises(KeyError, match="미정의 노드 웜스타트"):
        runner.reset({"없는노드": 0.0})


def test_입력_이름이_틀리면_시끄럽게_실패한다():
    runner = GraphRunner(_gain_graph(), DT)
    runner.reset()
    with pytest.raises(TypeError, match="입력 불일치"):
        runner.step(wrong=1.0)


# ── C 생성 ────────────────────────────────────────────────────────────────


def _emit(graph):
    runner = GraphRunner(graph, DT)
    return emit_c(graph, runner), runner


def test_이산계수는_엔진이_계산한_값을_그대로_굽는다():
    """이산화 공식이 Python과 C에 두 번 적히면 그 순간 어긋난다 (filters.py:29)."""
    files, runner = _emit(scas_axis_graph("ax", **DEMO_YAW))
    expected = math.exp(-DT / DEMO_YAW["washout_tau"])
    assert runner.instances["wo"]._p == expected
    assert repr(expected) in files["ax_data.c"]
    assert repr(1.0 - expected) in files["ax_data.c"]


def test_스케줄된_게인은_파라미터_구조체에_남지_않는다():
    """신호로 들어오는 값을 파라미터에 두면 아무도 안 읽는 dead data가 된다."""
    sched, _ = _emit(scas_axis_graph("ax", scheduled=("kp", "ki"), **DEMO_PITCH))
    fixed, _ = _emit(scas_axis_graph("ax", scheduled=(), **DEMO_PITCH))
    assert "pid_kp" not in sched["ax_types.h"]
    assert "pid_kp" in fixed["ax_types.h"]


def test_kd가_0이면_미분항과_그_상태가_사라진다():
    """죽은 항 하나가 상태 필드 하나와 매 스텝 나눗셈 하나를 함께 끌고 다닌다."""
    files, _ = _emit(scas_axis_graph("ax", **DEMO_PITCH))
    assert "e_prev" not in files["ax_types.h"], "쓰이지 않는 상태가 남았다"
    assert " / " not in files["ax.c"], "쓰이지 않는 미분항의 나눗셈이 남았다"


def test_생성_코드가_블록_id와_신호_이름을_보존한다():
    """FCC팀이 읽고 시험한다 — rtb_Sum_p_idx_1 류를 만들지 않는다."""
    files, _ = _emit(scas_axis_graph("ax", scheduled=("kp",), **DEMO_YAW))
    body = files["ax.c"]
    for token in ("att_err", "rate", "kp", "wo_y", "pid_y", "damp_y", "sum_y", "sat_y"):
        assert token in body, f"이름 {token}이 생성 코드에서 사라졌다"


def test_dt는_런타임_파라미터가_아니라_매크로다():
    """계수가 그 dt로 구워졌으므로 dt만 바꾸면 조용히 틀린다."""
    files, _ = _emit(scas_axis_graph("ax", **DEMO_YAW))
    assert "#define AX_DT 0.01" in files["ax.h"]
    assert "double dt;" not in files["ax_types.h"], "dt가 튜닝 가능한 파라미터로 새어나갔다"


def test_빌드_요구가_생성_헤더에_박힌다():
    """FMA 축약을 켜면 비트 일치가 깨진다 — 컴파일하는 사람이 읽는 자리에 둔다."""
    files, _ = _emit(scas_axis_graph("ax", **DEMO_YAW))
    assert "-ffp-contract=off" in files["ax.h"]
    assert "ffast-math" in files["ax.h"]


def test_지문은_파라미터와_구조_양쪽에_반응한다():
    base, _ = _emit(scas_axis_graph("ax", **DEMO_YAW))
    other = dict(DEMO_YAW, kp=DEMO_YAW["kp"] + 0.1)
    changed_param, _ = _emit(scas_axis_graph("ax", **other))
    changed_struct, _ = _emit(scas_axis_graph("ax", scheduled=("kp",), **DEMO_YAW))

    def fp(files):
        line = next(ln for ln in files["ax.h"].splitlines() if "지문" in ln)
        return line.split(":")[1].strip()

    assert fp(base) != fp(changed_param), "파라미터가 바뀌었는데 지문이 같다"
    assert fp(base) != fp(changed_struct), "구조가 바뀌었는데 지문이 같다"


def test_생성은_결정적이다():
    """산출물을 커밋하므로 재생성 차이가 곧 실제 변경이어야 한다 (시각 미포함)."""
    graph = scas_axis_graph("ax", **DEMO_YAW)
    assert emit_c(graph, GraphRunner(graph, DT)) == emit_c(graph, GraphRunner(graph, DT))


def test_에미터_없는_블록은_조용히_넘어가지_않는다():
    graph = Graph(
        "g", inputs=("u",), nodes=[Node("i", Integrator, inputs=("u",))], output="i"
    )
    with pytest.raises(NotImplementedError, match="C 에미터 미구현"):
        _emit(graph)


def test_비유한_파라미터는_탑재_코드로_나가지_않는다():
    graph = Graph(
        "g",
        inputs=("u",),
        nodes=[Node("s", Saturation, inputs=("u",), params={"lo": -1.0, "hi": math.inf})],
        output="s",
    )
    with pytest.raises(ValueError, match="비유한"):
        _emit(graph)


def test_연산_노드는_Python과_C_양쪽에_난다():
    """wrap_pi는 Python `%`와 C `fmod`의 나머지 부호가 달라 보정이 필요하다."""
    graph = Graph("wrap_demo", inputs=("a",), nodes=[Op("w", "wrap_pi", ("a",))], output="w")
    files, runner = _emit(graph)
    runner.reset()
    assert runner.step(a=3.0 * math.pi) == pytest.approx(math.pi)
    assert "claw_wrap_pi" in files["wrap_demo.c"]
    assert "fmod" in files["wrap_demo.c"]
    assert "char _unused;" in files["wrap_demo_types.h"]  # 상태·파라미터 없는 그래프


def test_안티와인드업_클램프가_생성_코드에_남아_있다():
    """포화 중 적분기가 계속 자라면 리커버리가 늦는다 — 클램프는 필수 경로다."""
    files, _ = _emit(scas_axis_graph("ax", **DEMO_PITCH))
    step_body = files["ax.c"].split("_step(")[-1]
    assert step_body.count("claw_clip") >= 3  # PID 출력 + 적분기 + 최종 포화
