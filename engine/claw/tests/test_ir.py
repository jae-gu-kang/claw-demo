"""M16 codegen — IR 제약·실행·C 생성 (구현 문서 §2.2).

**손으로 쓴 오라클은 없다.** 증분 C에서 `fcl/`이 IR 백엔드로 이관되면서 구조가
한 곳으로 합쳐졌고, 비교할 두 번째 구현이 사라졌다. 이관이 옳았다는 증거는 그때
기존 회귀 전부(폐루프 미션 핀 포함)가 그대로 통과했다는 사실이고, 그 시점은 git
이력에 남아 있다.

그래서 지금 이 파일이 지키는 것은 셋이다:
  ① IR이 C 생성 가능 제약을 강제하는가 (대수 루프·dead code·예약 이름)
  ② 생성 C가 IR과 같은가 — 이건 여전히 **두 구현의 대조**다 (flight/tests가 본체)
  ③ 클래스 API가 그래프를 옳게 태우는가 (어댑터 배선 — 입출력 마샬링)
"""

import math

import pytest

from claw.blocks.basic import Gain, Product, Saturation
from claw.blocks.controllers import PID
from claw.blocks.dynamics import Integrator
from claw.blocks.filters import CommandFilter, Washout
from claw.codegen import GraphRunner, emit_c, emit_runtime, grouped
from claw.codegen.ir import Graph, Node, Op
from claw.fcl.demo import DEMO_PITCH, DEMO_YAW
from claw.fcl.graphs import (
    alpha_limiter_graph,
    gain_schedule_nodes,
    mixer_graph,
    scas_axis_graph,
)
from claw.fcl.scas import ScasAxis

DT = 0.01


def _gain_graph(name="g1"):
    return Graph(name, inputs=("u",), nodes=[Node("k", Gain, inputs=("u",))], outputs={"y": "k"})


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
            outputs={"y": "a"},
        )


def test_미정의_참조는_거부된다():
    with pytest.raises(ValueError, match="미정의 참조"):
        Graph("g", inputs=("u",), nodes=[Node("a", Gain, inputs=("nope",))], outputs={"y": "a"})


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
            outputs={"y": "used"},
        )


def test_노드_id가_그래프_입력과_충돌하면_거부된다():
    with pytest.raises(ValueError, match="이름 충돌"):
        Graph("g", inputs=("u",), nodes=[Node("u", Gain, inputs=("u",))], outputs={"y": "u"})


def test_C_예약어와_비식별자는_이름으로_쓸_수_없다():
    with pytest.raises(ValueError, match="예약어"):
        Node("double", Gain, inputs=("u",))
    with pytest.raises(ValueError, match="C 식별자"):
        Graph("g", inputs=("u-1",), nodes=[Node("k", Gain, inputs=("u-1",))], outputs={"y": "k"})


def test_출력이_노드가_아니면_거부된다():
    with pytest.raises(ValueError, match="출력"):
        Graph("g", inputs=("u",), nodes=[Node("k", Gain, inputs=("u",))], outputs={"y": "u"})


def test_연산_노드의_입력_개수는_검증된다():
    with pytest.raises(ValueError, match="입력 1개 필요"):
        Op("w", "wrap_pi", ("a", "b"))
    with pytest.raises(ValueError, match="미정의 연산"):
        Op("w", "없는연산", ("a",))


# ── 어댑터 배선 ───────────────────────────────────────────────────────────
# 클래스의 step()은 이제 그래프를 태우는 얇은 층이다. 여기서 잡는 것은 구조가
# 아니라 **마샬링** — 항법 상태에서 어떤 공학량을 뽑아 어느 입력에 넣고, 결과를
# 어떤 계약으로 되돌리는가. 구조 자체는 fcl/graphs.py 한 곳뿐이라 대조 대상이 없다.


@pytest.mark.parametrize(
    ("cfg", "scheduled"),
    [
        (DEMO_PITCH, ()),  # 워시아웃 없음 + 상수 게인
        (DEMO_PITCH, ("kp", "ki", "k_rate")),  # 게인이 신호(스케줄 경로)
        (DEMO_YAW, ()),  # 워시아웃 있음
        (DEMO_YAW, ("kp", "ki")),  # 일부만 스케줄
    ],
)
def test_ScasAxis_어댑터가_축_그래프와_같은_답을_낸다(cfg, scheduled):
    """클래스가 게인 덮어쓰기를 포트로 옳게 흘려보내는가 (기본값 복원 포함)."""
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


def _emit_module(graph):
    return emit_c(graph, GraphRunner(graph, DT))


def _emit(graph):
    runner = GraphRunner(graph, DT)
    return emit_c(graph, runner).files, runner


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
    """계수가 그 dt로 구워졌으므로 dt만 바꾸면 조용히 틀린다.

    매크로는 `_types.h`에 둔다 — 기능축 파티션 헤더가 진입점(`.h`)이 아니라 이
    파일만 의존하면 되고, 포함 관계가 DAG로 남는다.
    """
    files, _ = _emit(scas_axis_graph("ax", **DEMO_YAW))
    assert "#define AX_DT 0.01" in files["ax_types.h"]
    assert "double dt;" not in files["ax_types.h"], "dt가 튜닝 가능한 파라미터로 새어나갔다"
    # 진입점을 포함하면 dt도 따라온다 (harness.c가 그렇게 쓴다)
    assert '#include "ax_types.h"' in files["ax.h"]


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
        "g", inputs=("u",), nodes=[Node("i", Integrator, inputs=("u",))], outputs={"y": "i"}
    )
    with pytest.raises(NotImplementedError, match="C 에미터 미구현"):
        _emit(graph)


def test_비유한_파라미터는_탑재_코드로_나가지_않는다():
    graph = Graph(
        "g",
        inputs=("u",),
        nodes=[Node("s", Saturation, inputs=("u",), params={"lo": -1.0, "hi": math.inf})],
        outputs={"y": "s"},
    )
    with pytest.raises(ValueError, match="비유한"):
        _emit(graph)


def test_연산_노드는_Python과_C_양쪽에_난다():
    """wrap_pi는 Python `%`와 C `fmod`의 나머지 부호가 달라 보정이 필요하다."""
    graph = Graph("wrap_demo", inputs=("a",), nodes=[Op("w", "wrap_pi", ("a",))], outputs={"y": "w"})
    files, runner = _emit(graph)
    runner.reset()
    assert runner.step(a=3.0 * math.pi) == pytest.approx(math.pi)
    assert "claw_wrap_pi" in files["wrap_demo.c"]
    assert "char _unused;" in files["wrap_demo_types.h"]  # 상태·파라미터 없는 그래프
    # 보정 구현은 공용 런타임에 한 벌만 있다 — 부르는 쪽은 fmod도 math.h도 모른다
    rt = emit_runtime(_emit_module(graph).helpers)
    assert "fmod" in rt["claw_rt.c"]
    assert "fmod" not in files["wrap_demo.c"]
    assert "#include <math.h>" not in files["wrap_demo.c"]


def test_안티와인드업_클램프가_생성_코드에_남아_있다():
    """포화 중 적분기가 계속 자라면 리커버리가 늦는다 — 클램프는 필수 경로다."""
    files, _ = _emit(scas_axis_graph("ax", **DEMO_PITCH))
    step_body = files["ax.c"].split("_step(")[-1]
    assert step_body.count("claw_clip") >= 3  # PID 출력 + 적분기 + 최종 포화


# ── 증분 B: 다중 출력·모드 분기·테이블 ────────────────────────────────────


def test_enable_영역은_연속이어야_한다():
    """생성 C가 if/else 한 덩이가 되어야 "이 구간은 이 모드일 때만 돈다"가 눈에 잡힌다."""
    with pytest.raises(ValueError, match="영역이 끊겼다"):
        Graph(
            "g",
            inputs=("u", "en"),
            nodes=[
                Node("a", Gain, inputs=("u",), enable="en"),
                Node("b", Gain, inputs=("a",)),  # 영역 밖
                Node("c", Gain, inputs=("b",), enable="en"),  # 다시 같은 enable — 끊겼다
            ],
            outputs={"y": "c"},
        )


def test_on_disable은_enable_없이_쓸_수_없다():
    with pytest.raises(ValueError, match="on_disable은 enable과 함께"):
        Node("a", Gain, inputs=("u",), on_disable={"x": 0.0})


def test_예약된_함수_인자명은_그래프_입력이_될_수_없다():
    """실제로 겪은 사고 — 롤 각속도 입력 `p`가 파라미터 포인터를 가려 컴파일이 깨졌다."""
    for reserved in ("prm", "sta", "out"):
        with pytest.raises(ValueError, match="함수 인자 이름과 충돌"):
            Graph("g", inputs=(reserved,),
                  nodes=[Node("k", Gain, inputs=(reserved,))], outputs={"y": "k"})


def test_상수를_갖는_연산은_value가_강제된다():
    with pytest.raises(ValueError, match="상수 value가 필요"):
        Op("a", "add_const", inputs=("u",))
    with pytest.raises(ValueError, match="상수 value를 받지 않음"):
        Op("a", "wrap_pi", inputs=("u",), value=1.0)


def test_출력_개수가_C_시그니처를_가른다():
    """1개면 값을 반환하고 여럿이면 출력 구조체를 채운다 — 읽기 쉬운 쪽을 고른다."""
    single, _ = _emit(_gain_graph("one"))
    assert "double one_step(" in single["one.c"]
    assert "one_out_t" not in single["one_types.h"]

    two = Graph("two", inputs=("u",),
                nodes=[Node("a", Gain, inputs=("u",)), Node("b", Gain, inputs=("a",))],
                outputs={"first": "a", "second": "b"})
    files, _ = _emit(two)
    assert "void two_step(" in files["two.c"]
    assert "out->first" in files["two.c"] and "out->second" in files["two.c"]


def test_그래프_enable은_직전_출력을_유지하고_상태를_동결한다():
    """항법 무효 시 마지막 유효 명령 유지 (law.py:86) — 상태도 함께 멈춘다."""
    graph = Graph(
        "held",
        inputs=("en", "u"),
        nodes=[Node("pid", PID, inputs=("u",), params={"kp": 1.0, "ki": 1.0})],
        outputs={"y": "pid"},
        enable="en",
    )
    runner = GraphRunner(graph, DT)
    runner.reset(hold={"y": 7.0})
    assert runner.step(en=0.0, u=99.0) == 7.0, "비활성인데 계산했다"
    assert runner.instances["pid"]._i == 0.0, "비활성인데 상태가 움직였다"
    live = runner.step(en=1.0, u=1.0)
    assert runner.step(en=0.0, u=99.0) == live, "직전 출력을 유지하지 않았다"

    files, _ = _emit(graph)
    assert "if (en == 0.0)" in files["held.c"]
    assert "*out = sta->hold;" in files["held.c"] or "return sta->hold;" in files["held.c"]


def test_비활성_영역은_실행_대신_상태를_대입한다():
    """비활성 축의 명령필터가 측정을 추적해야 재관여가 범프리스다 (autopilot.py:151)."""
    graph = Graph(
        "track",
        inputs=("en", "cmd", "meas"),
        nodes=[
            Node("f", CommandFilter, inputs=("cmd", "meas"), params={"tau": 1.0},
                 enable="en", on_disable={"x": "meas"}),
        ],
        outputs={"y": "f"},
    )
    runner = GraphRunner(graph, DT)
    runner.reset()
    assert runner.step(en=0.0, cmd=100.0, meas=5.0) == 0.0  # disabled_output
    assert runner.instances["f"]._x == 5.0, "측정을 추적하지 않았다"
    # 추적된 값에서 출발하므로 첫 활성 스텝이 5.0 근처에서 시작한다 (킥 없음)
    assert 5.0 < runner.step(en=1.0, cmd=100.0, meas=5.0) < 6.0

    files, _ = _emit(graph)
    body = files["track.c"]
    assert "} else {" in body
    assert "sta->f_x = meas;" in body and "sta->f_seeded = 1;" in body


def test_테이블은_격자점과_값이_함께_구워진다():
    from claw.plant import make_demo_stall_table

    table = make_demo_stall_table()
    graph = alpha_limiter_graph(stall_table=table, margin=0.05)
    files, runner = _emit(graph)
    assert f"double stall_bp[{len(table.axes[0])}]" in files["alpha_limiter_types.h"]
    assert "claw_lookup1d" in files["alpha_limiter.c"]
    runner.reset()
    for mach in (0.1, 0.35, 0.6, 0.95, 2.0):  # 경계 밖 포함 (외삽 clip)
        got = runner.step(theta_cmd=0.0, theta=0.0, alpha=0.0, mach=mach)
        assert got["alpha_margin"] == float(table.interp(mach=mach)) - 0.05


def test_외삽_금지가_아닌_테이블은_탑재_코드로_나가지_않는다():
    from claw.tables import Table

    linear = Table({"mach": [0.2, 0.9]}, [0.3, 0.2], name="t", extrapolate="linear")
    with pytest.raises(NotImplementedError, match="extrapolate='clip'만"):
        _emit(alpha_limiter_graph(stall_table=linear, margin=0.05))


def test_믹서_어댑터가_4면_배열로_옳게_되돌린다():
    from claw.fcl.mixer import Mixer

    cfg = dict(elevon_lo=-0.35, elevon_hi=0.35, rudder_lo=-0.35, rudder_hi=0.35,
               k_diff_thr=0.1)
    oracle = Mixer(**cfg).init(DT)
    runner = GraphRunner(mixer_graph(**cfg), DT)
    runner.reset()
    for k in range(400):
        t = k * DT
        de, da = 0.5 * math.sin(t), 0.4 * math.cos(2.0 * t)
        dr, thr = 0.3 * math.sin(3.0 * t), 0.5 + 0.6 * math.sin(t)
        ref, got = oracle.step(de, da, dr, thr), runner.step(de=de, da=da, dr=dr, thr=thr)
        assert float(ref.elevon[0]) == got["elevon_l"]
        assert float(ref.elevon[2]) == got["elevon_r"]
        assert float(ref.rudder) == got["rudder"]
        assert float(ref.throttle[0]) == got["throttle_l"]
        assert float(ref.throttle[1]) == got["throttle_r"]


def test_리미터_어댑터가_항법에서_공학량을_옳게_뽑는다():
    import numpy as np

    from claw.common.attitude import euler_to_quat, quat_to_euler
    from claw.common.contracts import NavOutput
    from claw.fcl.airdata import airdata_from_nav
    from claw.fcl.limiter import AlphaLimiter
    from claw.plant import make_demo_stall_table

    table = make_demo_stall_table()
    oracle = AlphaLimiter(table, margin=0.05)
    runner = GraphRunner(alpha_limiter_graph(stall_table=table, margin=0.05), DT)
    runner.reset()
    hit = 0
    for k in range(400):
        t = k * DT
        theta_set, alpha_set = 0.1 * math.sin(t), 0.15 + 0.18 * math.sin(2.0 * t)
        mach, theta_cmd = 0.3 + 0.3 * math.sin(0.5 * t), 0.28 * math.sin(3.0 * t)
        u = math.sqrt(max(1.0 - math.sin(alpha_set) ** 2, 0.0))
        nav = NavOutput(q_nb=euler_to_quat(0.0, theta_set, 0.0),
                        vel_n=np.array([u, 0.0, math.sin(alpha_set)]))
        # 그래프 경계는 "이미 계산된 공학량"이다 — 통합 계층이 넘길 값을 그대로 넘긴다
        # (역구성한 값을 넣으면 쿼터니언·에어데이터 왕복 반올림이 차이로 나타난다)
        alpha = float(airdata_from_nav(nav)[1])
        theta = float(quat_to_euler(nav.q_nb)[1])
        ref_theta, ref_active, ref_margin = oracle.step(theta_cmd, nav, mach)
        got = runner.step(theta_cmd=theta_cmd, theta=theta, alpha=alpha, mach=mach)
        assert ref_margin == got["alpha_margin"], f"스텝 {k}"
        assert ref_theta == got["theta_cmd"], f"스텝 {k}"
        assert float(ref_active) == got["active"], f"스텝 {k}"
        hit += int(ref_active)
    assert hit > 0, "리미터가 한 번도 작동하지 않아 제한 경로가 검증되지 않았다"


def test_스케줄은_실제로_쓰이는_축의_필터만_만든다():
    """손으로 쓴 코드는 mach·alt·fuel 필터를 항상 셋 다 돌린다 — 출력은 같지만
    아무도 읽지 않는 상태를 탑재 코드에 둘 이유가 없다."""
    from claw.fcl.demo import make_demo_gain_tables

    nodes, outs = gain_schedule_nodes(
        "s", tables=make_demo_gain_tables(), filter_tau=0.5,
        srcs={"mach": "mach", "alt": "h", "fuel": "fuel"},
    )
    filters = [n.id for n in nodes if n.block is CommandFilter]
    assert filters == ["s_f_mach"], f"쓰이지 않는 스케줄 필터가 생겼다: {filters}"
    assert set(outs) == {"pitch", "roll"}


def test_오토파일럿_어댑터가_모드_전환을_포함해_같은_답을_낸다():
    """모드 on/off 경계가 이 구조의 급소다 — 필터 추적·적분기 소거·홀드가 얽혀 있다."""
    import numpy as np

    from claw.common.attitude import euler_to_quat, quat_to_euler
    from claw.common.contracts import GuidanceCommand, NavOutput
    from claw.fcl.airdata import airdata_from_nav
    from claw.fcl.autopilot import Autopilot
    from claw.fcl.graphs import autopilot_graph

    cfg = {d.name: d.default for d in Autopilot.PARAM_DEFS}
    oracle = Autopilot(**cfg).init(DT)
    oracle.reset()
    runner = GraphRunner(autopilot_graph(**cfg), DT)
    runner.reset()

    seen = set()
    for k in range(1500):
        t = k * DT
        on = (t < 4.0 or t >= 8.0, not (3.0 <= t < 6.0), t >= 1.0)  # heading, alt, speed
        seen.add(on)
        psi_set, h, hdot = 0.3 * math.sin(0.5 * t), 100.0 + 20.0 * math.sin(0.3 * t), 6.0
        V_set = 60.0 + 5.0 * math.sin(0.4 * t)
        vd = -hdot
        nav = NavOutput(
            q_nb=euler_to_quat(0.0, 0.0, psi_set), pos_n=np.array([0.0, 0.0, -h]),
            vel_n=np.array([math.sqrt(max(V_set**2 - vd**2, 0.0)), 0.0, vd]),
        )
        cmd = GuidanceCommand(
            speed=65.0, alt=120.0, heading=0.8 * math.sin(0.2 * t),
            heading_on=on[0], alt_on=on[1], speed_on=on[2],
        )
        ref = oracle.step(cmd, nav)
        # 통합 계층이 넘길 값 그대로 (원시 상태 → 공학량 변환은 그래프 밖)
        got = runner.step(
            psi=float(quat_to_euler(nav.q_nb)[2]), h=-float(nav.pos_n[2]),
            hdot=-float(nav.vel_n[2]), V=float(airdata_from_nav(nav)[0]),
            cmd_heading=cmd.heading, cmd_alt=cmd.alt, cmd_speed=cmd.speed,
            heading_on=float(on[0]), alt_on=float(on[1]), speed_on=float(on[2]),
        )
        for i, name in enumerate(("theta_cmd", "phi_cmd", "throttle")):
            assert ref[i] == got[name], f"스텝 {k} ({name}) 모드={on}"
    assert len(seen) >= 4, f"모드 조합을 충분히 밟지 않음: {seen}"


# ── 증분 D′: 기능축 분할 ──────────────────────────────────────────────────
#
# 이름표(`grouped`)는 **실행에 영향이 없어야 한다** — IR은 평탄한 채로 남고
# 에미터만 경계에서 자른다. 그래서 여기서 지키는 것은 두 가지다:
# ① 쪼갤 수 없는 배치를 IR이 거부하는가  ② 쪼개도 같은 제어법칙인가(지문·비트).
# 비트 일치 자체는 flight/tests/test_parity.py가 실제 미션으로 본다.


def _split_nodes():
    """두 덩이로 쪼갤 수 있는 최소 그래프의 노드 — 호출할 때마다 새로 만든다
    (`grouped`가 제자리에서 이름표를 찍으므로 재사용하면 앞 시험이 샌다)."""
    return [
        Node("a_k", Gain, inputs=("u",), params={"k": 2.0}),
        Node("b_s", Saturation, inputs=("a_k",), params={"lo": -1.0, "hi": 1.0}),
    ]


def _split_graph(tag=True):
    nodes = _split_nodes()
    if tag:
        nodes = grouped(nodes[:1], "first") + grouped(nodes[1:], "second")
    return Graph("sp", inputs=("u",), nodes=nodes, outputs={"y": "b_s"})


def test_group이_끊기면_거부한다():
    """같은 이름의 함수가 두 번 생길 배치 — 쪼갤 수 없다."""
    n = _split_nodes()
    n.append(Node("c_k", Gain, inputs=("b_s",), params={"k": 1.0}))
    nodes = grouped(n[:1], "one") + grouped(n[1:2], "two") + grouped(n[2:], "one")
    with pytest.raises(ValueError, match="group 'one' 영역이 끊겼다"):
        Graph("sp", inputs=("u",), nodes=nodes, outputs={"y": "c_k"})


def test_group_태그가_섞이면_거부한다():
    """일부만 쪼갠 코드는 '나머지는 어디 있나'를 읽는 사람에게 떠넘긴다."""
    nodes = _split_nodes()
    grouped(nodes[:1], "first")  # 뒤 노드는 이름표 없음
    with pytest.raises(ValueError, match="일부 노드에만 붙었다"):
        Graph("sp", inputs=("u",), nodes=nodes, outputs={"y": "b_s"})


def test_enable_영역이_group을_가로지르면_거부한다():
    """if 한 덩이가 두 함수에 걸칠 수 없다 — 모드 분기가 파일 경계에서 잘린다."""
    nodes = [
        Node("a_k", Gain, inputs=("u",), params={"k": 2.0}, enable="on"),
        Node("b_s", Saturation, inputs=("a_k",), params={"lo": -1.0, "hi": 1.0}, enable="on"),
    ]
    grouped(nodes[:1], "first")
    grouped(nodes[1:], "second")
    with pytest.raises(ValueError, match="영역이 group .* 경계를 가로지른다"):
        Graph("sp", inputs=("u", "on"), nodes=nodes, outputs={"y": "b_s"})


def test_group_이름이_신호와_충돌하면_거부한다():
    """`{base}_{group}`이 파일명·함수명이 된다 — 신호 이름과 겹치면 읽기가 무너진다."""
    nodes = _split_nodes()
    grouped(nodes[:1], "u")  # 그래프 입력과 같은 이름
    grouped(nodes[1:], "second")
    with pytest.raises(ValueError, match="노드 id·그래프 입력과 충돌"):
        Graph("sp", inputs=("u",), nodes=nodes, outputs={"y": "b_s"})


def test_이름표가_없으면_예전처럼_파일_하나다():
    files, _ = _emit(_split_graph(tag=False))
    assert sorted(files) == ["sp.c", "sp.h", "sp_data.c", "sp_types.h"]


def test_이름표가_붙으면_서브시스템별로_떨어진다():
    files, _ = _emit(_split_graph())
    assert sorted(files) == [
        "sp.c", "sp.h", "sp_data.c", "sp_first.c", "sp_first.h",
        "sp_second.c", "sp_second.h", "sp_types.h",
    ]
    # 조립부에는 계산이 없고 호출만 있다
    top = files["sp.c"]
    assert "sp_first_step(" in top and "sp_second_step(" in top
    assert "prm->" not in top, "조립부에 블록 계산이 남았다"
    # 출력 1개인 파티션은 값을 반환한다 (그래프 단위 규칙과 같다)
    assert "const double a_k_y = sp_first_step(prm, sta, u);" in top
    assert "const double b_s_y = sp_second_step(prm, sta, a_k_y);" in top
    # 경계를 넘어도 신호 이름이 그대로다 — 정의부·인자·호출부가 모두 a_k_y
    assert "double a_k_y" in files["sp_second.h"]
    assert "const double b_s_y = claw_clip(a_k_y" in files["sp_second.c"]


def test_분할은_지문을_바꾸지_않는다():
    """지문은 형상(파라미터·dt·구조)의 신원이다 — 파일을 어떻게 쪼개든 같은 법칙이다.

    배치가 바뀐 것은 파일 diff로 보이면 되고, 지문까지 흔들리면 "형상이 바뀌었나"를
    구별할 수 없게 된다.
    """
    def fp(files):
        line = next(ln for ln in files["sp.h"].splitlines() if "지문" in ln)
        return line.split(":")[1].strip()

    flat, _ = _emit(_split_graph(tag=False))
    split, _ = _emit(_split_graph())
    assert fp(flat) == fp(split)


def test_공용_런타임은_쓰는_것만_낸다():
    """안 쓰는 헬퍼를 탑재 코드에 두지 않는다 — IR이 dead code를 막는 것과 같은 이유."""
    only_clip = emit_runtime({"claw_clip"})
    assert "claw_lookup1d" not in only_clip["claw_rt.c"]
    assert "#include <math.h>" not in only_clip["claw_rt.c"]
    # lookup1d는 clip을 부른다 — 의존을 알아서 끌고 온다
    with_lut = emit_runtime({"claw_lookup1d"})
    assert "double claw_clip(" in with_lut["claw_rt.c"]
    assert emit_runtime(set()) == {}
