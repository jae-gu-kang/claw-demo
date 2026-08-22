"""GraphRunner 계측 창구 — 중간 노드 값 공개 (구조도 재생 오버레이의 원천).

그래프 **출력**(=생성 C의 인터페이스)에는 최종 타면·리미터 상태만 있어서,
명령 사슬 중간값(θ_cmd·θ_lim·SCAS 축 출력)은 매 스텝 계산되고도 버려졌다.
`last_env`는 그 값들을 읽기 전용으로 내주는 창구다. 여기서 지키는 것은 둘:
  ① 중간값이 실제로 담기는가 (담기지 않으면 오버레이 배선이 값 없이 남는다)
  ② 실행되지 않은 스텝이 0으로 보이지 않는가 (enable=0은 직전 값 유지)
"""

import pytest

from claw.blocks.basic import Gain, Saturation
from claw.codegen import GraphRunner
from claw.codegen.ir import Graph, Node, Op

DT = 0.01


def _chain_graph():
    """u → ×2 → 포화[-1, 1] → y. 중간 노드 'mid'가 계측 대상."""
    return Graph(
        "chain",
        inputs=("u",),
        nodes=[
            Node("mid", Gain, inputs=("u",), params={"k": 2.0}),
            Node("out", Saturation, inputs=("mid",), params={"lo": -1.0, "hi": 1.0}),
        ],
        outputs={"y": "out"},
    )


def test_중간_노드_값이_계측_창구에_담긴다():
    r = GraphRunner(_chain_graph(), DT)
    y = r.step(u=0.3)
    assert y == pytest.approx(0.6)
    # 출력에는 최종값만 있지만, 중간값도 읽을 수 있어야 한다
    assert r.last_env["mid"] == pytest.approx(0.6)
    assert r.last_env["out"] == pytest.approx(0.6)


def test_포화가_물린_스텝은_중간값과_출력이_갈라진다():
    """오버레이가 '보호가 물렸다'를 보여줄 수 있는 근거 — 두 값이 달라야 한다."""
    r = GraphRunner(_chain_graph(), DT)
    y = r.step(u=5.0)
    assert y == pytest.approx(1.0)  # 포화
    assert r.last_env["mid"] == pytest.approx(10.0)  # 포화 전 명령
    assert r.last_env["mid"] != r.last_env["out"]


def test_입력도_창구에_함께_담긴다():
    """배선 표시는 노드 출력뿐 아니라 그래프 입력(명령)도 필요하다."""
    r = GraphRunner(_chain_graph(), DT)
    r.step(u=0.25)
    assert r.last_env["u"] == pytest.approx(0.25)


def _enabled_graph():
    """enable이 0이면 아무것도 실행하지 않는 그래프 (법칙의 nav_valid 대응)."""
    return Graph(
        "gated",
        inputs=("u", "on"),
        nodes=[Node("mid", Gain, inputs=("u",), params={"k": 3.0})],
        outputs={"y": "mid"},
        enable="on",
    )


def test_실행되지_않은_스텝은_직전_계측값을_유지한다():
    """enable=0 스텝이 0으로 보이면 오버레이가 '명령이 0으로 떨어졌다'고 거짓말한다.
    출력 홀드와 같은 규약으로 계측값도 직전 스텝을 유지해야 한다."""
    r = GraphRunner(_enabled_graph(), DT)
    r.step(u=2.0, on=1.0)
    assert r.last_env["mid"] == pytest.approx(6.0)
    r.step(u=99.0, on=0.0)  # 실행 안 됨
    assert r.last_env["mid"] == pytest.approx(6.0), "정지 스텝이 계측값을 덮어썼다"


def test_계측_창구는_스텝_전에도_안전하게_비어_있다():
    """한 번도 돌지 않은 러너를 읽어도 터지지 않아야 한다 (뷰가 먼저 그릴 수 있다)."""
    r = GraphRunner(_chain_graph(), DT)
    assert r.last_env == {}


def test_계측은_그래프_출력을_바꾸지_않는다():
    """생성 C의 인터페이스는 graph.outputs가 정본 — 계측이 여기 새면 C가 달라진다.
    중간 노드는 last_env에만 있고 outputs에는 없어야 한다."""
    g = _chain_graph()
    r = GraphRunner(g, DT)
    r.step(u=0.3)
    assert set(g.outputs) == {"y"}
    assert "mid" in r.last_env and "mid" not in g.outputs


def test_op_노드_결과도_계측된다():
    """Op(순수 함수) 노드는 블록이 아니라 별도 경로로 계산된다 — 함께 담겨야 한다."""
    g = Graph(
        "withop",
        inputs=("a",),
        nodes=[Op("s", "add_const", inputs=("a",), value=2.5)],
        outputs={"y": "s"},
    )
    r = GraphRunner(g, DT)
    r.step(a=1.5)
    assert r.last_env["s"] == pytest.approx(4.0)
