"""추월 동기화(IR `Node.resync`)와 선회 스로틀 FF 제곱 — 두 백엔드가 같은 의미론을 내는지.

추월 동기화는 속도 명령필터가 레일 발진에서 V = 0에 붙잡혀 이탈 뒤 스로틀을 끄던 결함의 수리다(fcl/graphs.py 속도 절).
의미론의 정본은 `codegen/blockspec.py`의 `resync_state` 하나이고, C는 같은 식을 문자 그대로 낸다. 비트 대조는
flight/tests(한 실행 파일 × 세 기체 이미지)가 하고, 여기서는 규칙·거부·생성 문장을 못박는다.
"""

import math

import pytest

from claw.blocks.filters import CommandFilter, Washout
from claw.codegen import GraphRunner, emit_c
from claw.codegen.blockspec import resync_state
from claw.codegen.emit_c import _OP_C
from claw.codegen.ir import Graph, Node
from claw.codegen.ir_exec import _OP_FN

DT = 0.01


def _seeded(x, tau=1.0):
    f = CommandFilter(tau=tau).init(DT)
    f.reset(x)
    return f


@pytest.mark.parametrize("x, cmd, meas, want", [
    (0.0, 10.0, 3.0, 3.0),     # 가속 방향 — 측정이 상태와 목표 사이면 측정으로
    (10.0, 0.0, 4.0, 4.0),     # 감속 방향도 같다
    (0.0, 10.0, 12.0, 0.0),    # 목표를 넘어선 측정은 건드리지 않는다(기준을 목표 너머로 끌지 않는다)
    (5.0, 10.0, 1.0, 5.0),     # 뒤처진 측정 — 평소의 추종이다
    (5.0, 10.0, 5.0, 5.0),     # 경계(같음)는 거짓
    (5.0, 10.0, 10.0, 5.0),    # 목표와 같아도 거짓
    (5.0, 5.0, 5.0, 5.0),
    (0.0, 10.0, math.nan, 0.0),  # NaN은 판정이 거짓 — 상태를 오염시키지 않는다
])
def test_추월_동기화는_측정이_상태와_목표_사이에_있을_때만_측정으로_되시드한다(x, cmd, meas, want):
    f = _seeded(x)
    resync_state(f, cmd, meas)
    assert f._x == want


def test_미시드_필터는_동기화가_건드리지_않는다():
    """첫 step이 측정으로 시드하므로 그 스텝의 판정은 어차피 거짓이다 — C가 시드 뒤에 판정하는 것과 같은 결과."""
    f = CommandFilter(tau=1.0).init(DT)
    f.reset()
    resync_state(f, 10.0, 3.0)
    assert f._x is None
    assert f.step(10.0, 3.0) == pytest.approx(3.0 + (1.0 - math.exp(-DT)) * 7.0)


def _filter_graph(resync):
    return Graph("cf", inputs=("cmd", "meas"),
                 nodes=[Node("f", CommandFilter, inputs=("cmd", "meas"), params={"tau": 2.0}, resync=resync)],
                 outputs={"y": "f"})


def _run(resync, rows):
    r = GraphRunner(_filter_graph(resync), DT)
    r.reset()
    return [r.step(cmd=c, meas=m) for c, m in rows]


def test_평소의_추종에서는_동기화가_아무것도_바꾸지_않는다():
    """기준이 기체를 목표 쪽으로 끄는 보통의 경우(측정이 뒤처진다) — 비트로 같아야 한다."""
    rows = [(150.0, 100.0 + 0.1 * k) for k in range(300)]  # 기준이 늘 앞선다(300스텝 뒤 138.8 대 129.9)
    assert _run(True, rows) == _run(False, rows)


def test_사출기처럼_측정이_앞지르면_기준이_측정에서_출발한다():
    """레일 발진의 모양 — V가 0에서 1 s에 40 m/s로 오르고 목표는 45 m/s다.

    동기화가 없으면 기준이 0에서 τ로 기어올라 이탈 순간 16 m/s 근처에 있고(명령 < 속도 → 스로틀 0),
    있으면 기준이 측정 위에 붙어 올라가 이탈 순간 ≥ 40 m/s다.
    """
    ramp = [(45.0, 40.0 * k / 100.0) for k in range(101)]
    on, off = _run(True, ramp), _run(False, ramp)
    assert all(y >= m for y, (_c, m) in zip(on, ramp)), "동기화된 기준이 측정보다 뒤처졌다"
    assert on[-1] >= 40.0
    assert off[-1] < 0.5 * 40.0, "전제 — 동기화가 없으면 기준이 한참 뒤처진다"


def test_지원하지_않는_블록과_각도_필터는_조립에서_거부된다():
    with pytest.raises(ValueError, match="두 입력"):
        Node("w", Washout, inputs=("u",), resync=True)
    g = Graph("wo", inputs=("u", "v"),
              nodes=[Node("w", CommandFilter, inputs=("u", "v"), params={"tau": 1.0, "angle": True}, resync=True)],
              outputs={"y": "w"})
    with pytest.raises(ValueError, match="resync 미지원"):
        GraphRunner(g, DT)


def test_생성_C는_같은_판정식을_시드_뒤에_한_줄로_낸다():
    """곱 하나의 단일 조건 결정이다 — &&로 이으면 MC/DC 가드 형태가 되어 계측 대상이 바뀐다(verify/mcdc.py)."""
    def c_text(resync):
        g = _filter_graph(resync)
        return emit_c(g, GraphRunner(g, DT)).files["cf.c"]

    on, off = c_text(True), c_text(False)
    line = "if ((meas - sta->f_x) * (cmd - meas) > 0.0) { sta->f_x = meas; }"
    assert line in on and line not in off
    assert on.index("sta->f_seeded = 1; }") < on.index(line) < on.index("const double f_d = cmd - sta->f_x;")
    assert "&&" not in line


def test_선회_스로틀_FF의_제곱은_pow가_아니라_곱이다():
    """`pow(x, 2.0)`은 -O2에서 `x*x`로 접히고 -O0·Python(libm pow)은 아니라서 빌드마다 1 ulp 갈렸다.

    검증 탭 커버리지 세트(k_thr_turn을 켠 합성 값)가 제품 예제에서 이 자리로 대조 실패를 냈다 — φ = 0.08216586412600088
    rad에서 macOS libm pow는 c·c와 1 ulp 다르다. 곱 하나는 IEEE 정확 반올림이라 최적화 수준과 무관하다.
    """
    a = 0.08216586412600088
    c = math.cos(a)
    assert _OP_FN["sec2_minus_1"](a) == 1.0 / (c * c) - 1.0
    expr, needs = _OP_C["sec2_minus_1"]("phi")
    assert expr == "1.0 / (cos(phi) * cos(phi)) - 1.0" and "pow" not in expr
    assert needs == ("math",)
