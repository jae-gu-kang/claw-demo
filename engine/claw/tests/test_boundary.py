"""계약 ↔ 그래프 입력 경계 (07 §7).

여기서 지키는 것은 **두 벌이 없다**는 것이다. 이 함수가 생기기 전에는 같은 23키가 세 벌로
손에 적혀 있었고(`law.py`의 kwargs · `trace.py`의 dict · `trace.py`의 `INPUT_ORDER`), 키
누락은 런타임에 잡히지만 **불리언 접기 규약의 어긋남은 아무도 안 봤다.**
"""

import ast
import inspect
import re
from pathlib import Path

import numpy as np
import pytest

from claw.common.contracts import GuidanceCommand, NavOutput
from claw.fcl import boundary as bd
from claw.fcl.graphs import FCL_INPUTS, SIGNAL_TYPES
from claw.verify.trace import INPUT_ORDER

_SRC = Path(__file__).resolve().parents[1]


def _sample():
    nav = NavOutput(
        pos_n=np.array([120.0, -30.0, -1200.0]),
        vel_n=np.array([50.0, 2.0, -3.0]),
        q_nb=np.array([0.9974, 0.0199, 0.0499, 0.0100]),
        omega_b=np.array([0.011, 0.022, 0.033]),
        valid=True,
        fuel=180.0,
    )
    cmd = GuidanceCommand(
        speed=55.0, alt=1500.0, heading=0.3, pitch=0.05, hdot=2.0,
        speed_on=True, alt_on=True, heading_on=False, pitch_on=False, hdot_on=True,
    )
    return cmd, nav


def test_경계_표가_그래프_입력과_같다():
    """`BOUNDARY`가 빠뜨린 키는 조립에서 안 만들어지고, 남는 키는 아무도 안 본다."""
    assert set(bd.BOUNDARY) == set(FCL_INPUTS)
    assert len(FCL_INPUTS) == 23, "경계 크기가 바뀌었다 — 세 자리를 함께 볼 것"
    assert not (set(bd.DIRECT) & set(bd.DERIVED)), "한 키가 두 표에 있다"


def test_INPUT_ORDER는_사본이_아니라_그래프_입력이다():
    """C 하네스의 stdin 순서가 여기서 나오고, 인자 순서는 `graph.inputs`가 정한다.

    둘이 갈리면 값이 자리를 바꿔 실린다 — `verify/units.py`가 기록한 믹서 사고와 같은
    병이다. 사본이면 순서만 어긋나도 조용하므로 **같은 객체**여야 한다.
    """
    assert INPUT_ORDER is FCL_INPUTS, "INPUT_ORDER가 다시 사본이 됐다"
    src = (_SRC / "verify" / "trace.py").read_text(encoding="utf-8")
    assert "INPUT_ORDER = FCL_INPUTS" in src, "파생이 아니라 다시 적혔다"


def test_조립이_23키를_모두_만든다():
    cmd, nav = _sample()
    out = bd.graph_inputs(cmd, nav)
    assert set(out) == set(FCL_INPUTS)
    assert all(isinstance(v, float) for v in out.values()), "float이 아닌 값이 있다"


def test_불리언_여섯은_0이나_1로만_접힌다():
    """IR에 불리언 타입이 없어 `float(bool(x))`로 나른다 (07 §7).

    `bool()`을 빼면 0/1이 아닌 값이 그래프 enable에 실린다. 두 벌로 적혀 있을 때는
    한쪽만 그렇게 바뀌어도 대조가 통과했다 — 접기가 한 자리에 있는 이유다.
    """
    assert bd.BOOL_INPUTS == {"nav_valid", "speed_on", "alt_on", "heading_on",
                              "pitch_on", "hdot_on"}
    # 선언이 BOOL이라고 말한 것과 같은 여섯이어야 한다 (v0.83의 `SIGNAL_TYPES`)
    declared = {k for k in FCL_INPUTS if SIGNAL_TYPES[k].kind == "bool"}
    assert bd.BOOL_INPUTS == declared, (
        f"접는 것과 불리언이라 선언한 것이 다르다: {sorted(bd.BOOL_INPUTS ^ declared)}"
    )
    cmd, nav = _sample()
    # 계약이 참·거짓 아닌 값을 들고 와도 0/1로 접힌다 — 그것이 접기의 요지다
    cmd.speed_on = 0.5
    nav.valid = 3
    out = bd.graph_inputs(cmd, nav)
    for name in bd.BOOL_INPUTS:
        assert out[name] in (0.0, 1.0), f"{name}이 {out[name]}로 실렸다"
    assert out["speed_on"] == 1.0 and out["nav_valid"] == 1.0


def test_직접_읽는_자리는_계약_필드와_이름이_맞는다():
    """표가 실재하지 않는 필드를 가리키면 조립이 `AttributeError`로 죽는다 — 그 전에 본다."""
    cmd, nav = _sample()
    src = {"cmd": cmd, "nav": nav}
    for name, (obj, field, _fold) in bd.DIRECT.items():
        assert hasattr(src[obj], field), f"{name}: {obj}.{field}가 계약에 없다"
    assert len(bd.DIRECT) == 11 and len(bd.DERIVED) == 12


def test_직접_읽는_자리의_이름이_계약_필드를_따른다():
    """불리언 플래그는 단위가 없어 단위 대조가 못 잡는다 — 이름 규약이 그 자리를 맡는다.

    `heading_on`과 `pitch_on`의 필드를 맞바꿔도 값은 여전히 bool이라 아무 검사도 안
    걸리고, 죽는 곳은 착륙 테스트다(진단이 「경계가 뒤바뀌었다」를 안 말한다).
    이름 규약은 셋뿐이다: 그대로 · `cmd_` 접두 · `nav_valid ← nav.valid`.
    """
    for signal, (obj, field, _fold) in bd.DIRECT.items():
        # `obj == "cmd"`로 좁히면 예정된 확장을 막는다 — `NavOutput.fuel`은 이미 스케줄
        # 변수라(`schedule.SCHED_VARS`) `DIRECT["fuel"] = ("nav", "fuel", False)`가
        # 자연스러운 추가인데 「명령 경계가 아닌 것이 섞였다」로 죽는다. 옳은 변경에
        # 틀린 진단 — 이번에 고친 병과 같은 종류다. 접두를 `obj`에서 만들면
        # `nav_valid`가 바로 `nav_valid`라 특수 케이스도 함께 사라진다
        assert signal in (field, f"{obj}_{field}"), (
            f"{signal}이 {obj}.{field}를 읽는다 — 이름이 짝을 안 이룬다"
        )
    # 규약이 셋 다 실제로 쓰이는지 — 하나만 쓰이면 나머지는 검사되지 않는다
    same = [s for s, (_, f, _) in bd.DIRECT.items() if s == f]
    prefixed = [s for s, (_, f, _) in bd.DIRECT.items() if s == f"cmd_{f}"]
    assert len(same) == 5 and len(prefixed) == 5


def test_파생값의_출처_설명이_실제_계산과_맞는다():
    """`DERIVED`는 값을 만들지 않고 출처만 적는다 — 그 설명이 낡으면 읽는 사람을 속인다.

    **문자열의 머리만 보면 안 된다.** 그렇게 짰더니 `isa_atmosphere(h).a`의 `.a`가
    `.rho`로 바뀌어도 통과했다 — 「같은 물리량의 비라서 무차원」이라는 주장의 무게가
    전부 그 `.a`에 있는데도. 조립을 AST로 읽어 **실제로 접근한 속성과 부른 함수**를
    모아, 출처 설명이 말하는 것이 거기 있는지 본다.
    """
    # 파생 계산은 `nav_derived`에 산다 — `graph_inputs`는 그것을 부르고 직접 읽기를 얹는다
    tree = ast.parse(inspect.getsource(bd.nav_derived))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    calls = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert attrs and calls, "조립에서 속성·호출을 못 읽었다 — 파싱이 반쪽이다"
    for name, origin in bd.DERIVED.items():
        found = re.findall(r"\.(\w+)", origin)
        called_here = re.findall(r"(\w+)\s*\(", origin)
        # **키마다** 대조할 토큰이 있어야 한다. 전역 합으로 세면 토큰이 없는 출처는 루프
        # 본문이 아예 안 돌고 다른 키가 그 수를 메워 준다 — 실제로 열두 출처 중 다섯을
        # 한국어 산문으로 바꿔도 통과했다. 근거를 표로 옮기면서 근거가 사라지는 문이다
        assert found or called_here, (
            f"{name}의 출처 {origin!r}에 대조할 토큰이 없다 — 산문은 근거가 아니다"
        )
        for attr in found:
            assert attr in attrs, f"{name}의 출처가 말하는 `.{attr}`를 조립이 안 읽는다"
        for fn in called_here:
            assert fn in calls, f"{name}의 출처가 말하는 {fn}()를 조립이 안 부른다"


def test_파생값의_슬롯_순서가_조립의_언패킹과_같다():
    """출처만 적으면 `phi, theta, psi`를 `theta, phi, psi`로 뒤바꿔도 표가 아무 말을 안 한다.

    옛 근거(정규식)는 그 순서를 붙잡고 있었다. 표로 옮기면서 잃었던 것을 슬롯 표기
    (`quat_to_euler(nav.q_nb)[1]`)로 되찾고, 그 슬롯이 **조립의 실제 언패킹**과 같은지 본다.
    뒤바뀌면 착륙 테스트가 죽지만 그 진단은 「자세 경계가 뒤바뀌었다」를 안 말한다.
    """
    tree = ast.parse(inspect.getsource(bd.nav_derived))
    slots = {}  # 이름 → (출처 소스, 슬롯)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple)):
            continue
        origin = ast.unparse(node.value)
        for i, el in enumerate(node.targets[0].elts):
            if isinstance(el, ast.Name):
                slots[el.id] = (origin, i)
    assert len(slots) >= 9, f"언패킹을 {len(slots)}개밖에 못 읽었다 — 파싱이 반쪽이다"
    for name, (origin, i) in slots.items():
        if name not in bd.DERIVED:
            continue
        assert bd.DERIVED[name] == f"{origin}[{i}]", (
            f"{name}: 표는 {bd.DERIVED[name]!r}인데 조립은 {origin}의 {i}번째다"
        )
    # 셋씩 묶인 세 벌이 다 덮였는지 — 하나만 맞고 나머지가 안 읽혀도 위가 통과한다
    assert {"phi", "theta", "psi", "p", "q", "r", "V", "alpha", "beta"} <= set(slots)
    # **코드와 표를 함께 뒤집으면 위가 통과한다.** 슬롯의 뜻을 바깥 근거에 못박는다:
    # `common/attitude.py`가 `q_nb → (φ, θ, ψ)`를 규약으로 적고 `test_attitude.py`가
    # `euler_to_quat` 왕복으로 그 순서를 실제로 핀한다
    assert (bd.DERIVED["phi"], bd.DERIVED["theta"], bd.DERIVED["psi"]) == tuple(
        f"quat_to_euler(nav.q_nb)[{i}]" for i in range(3)
    ), "quat_to_euler는 (φ, θ, ψ)를 낸다 — common/attitude.py의 규약이다"
    assert (bd.DERIVED["V"], bd.DERIVED["alpha"], bd.DERIVED["beta"]) == tuple(
        f"airdata_from_nav(nav)[{i}]" for i in range(3)
    ), "airdata_from_nav는 (V, α, β)를 낸다 — fcl/airdata.py의 규약이다"


def test_조립을_손으로_두_벌_적지_않는다():
    """세 소비자가 같은 함수를 부른다 — 사본이 다시 생기면 여기서 죽는다.

    `fcl/scas.py`가 오래 남은 사본이었다: 여섯(θ·φ·β·p·q·r)을 손으로 또 뽑아서
    언패킹 순서가 `boundary.py`와 갈려도 아무도 안 봤다. 07 §7의 「정본은 하나」가
    참이 되려면 그것도 없어야 한다.
    """
    for rel, who in (("fcl/law.py", "법칙"), ("verify/trace.py", "대조 기록"),
                     ("fcl/scas.py", "축 단독 경로")):
        src = (_SRC / rel).read_text(encoding="utf-8")
        assert ("graph_inputs(cmd, nav)" in src) or ("nav_derived(nav)" in src), (
            f"{who}가 경계 함수를 안 쓴다"
        )
        assert "float(bool(" not in src, f"{who}에 불리언 접기가 다시 적혔다"
        # 「큰 dict」 같은 어림 기준은 정당한 코드를 잡는다(법칙의 홀드 출력이 그렇다).
        # **경계 키를 여럿 들고 있는 자리**만 본다 — 그것이 사본의 정의다
        tree = ast.parse(src)
        groups = [
            {k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            for n in ast.walk(tree) if isinstance(n, ast.Dict)
        ] + [
            {kw.arg for kw in n.keywords if kw.arg}
            for n in ast.walk(tree) if isinstance(n, ast.Call)
        ]
        for g in groups:
            shared = g & set(FCL_INPUTS)
            assert len(shared) < 5, (
                f"{who}에 경계 키 {len(shared)}개를 든 자리가 있다 — 사본이다: {sorted(shared)}"
            )


def test_법칙이_실제로_받는_값이_경계_함수의_산출이다():
    """이름이 주장하는 소비자를 **실제로 태운다** — 두 번 불러 결정성만 보면 이름이 크다.

    법칙의 `step`을 감싸 그래프 러너가 받은 kwargs를 가로채고, 같은 입력으로 만든
    경계 산출과 대조한다. 두 벌이던 시절 이것은 **가정**이었다.
    """
    from claw.fcl.demo import make_demo_fcl

    cmd, nav = _sample()
    law = make_demo_fcl()
    law.init(0.01)
    seen = {}
    orig = law.runner.step

    def spy(**kw):
        seen.update(kw)
        return orig(**kw)

    law.runner.step = spy
    law.step(cmd, nav)
    assert seen == bd.graph_inputs(cmd, nav), "법칙이 받은 값과 경계 산출이 다르다"
    assert len(seen) == 23

    # 값이 실제로 계약을 따라가는지 — 상수를 내는 함수가 아님을 함께 본다
    cmd2 = GuidanceCommand(**{**vars(cmd), "alt": 9999.0})
    assert bd.graph_inputs(cmd2, nav)["cmd_alt"] == 9999.0


def test_마하는_고도를_ISA_범위로_묶어_구한다():
    """`h`가 성층권 밖으로 나가도 음속 조회가 터지지 않아야 한다 — 원본이 하던 클램프다."""
    cmd, nav = _sample()
    nav.pos_n = np.array([0.0, 0.0, -60_000.0])  # ISA 상한 밖
    out = bd.graph_inputs(cmd, nav)
    assert out["h"] == 60_000.0, "고도 자체는 클램프하지 않는다"
    assert out["mach"] > 0.0 and np.isfinite(out["mach"])
    # **하한도 필요하다.** 없으면 해수면 아래에서 음속 조회가 `ValueError`를 던지는데,
    # 그것은 비행 제어 스텝 안에서 나는 예외라 「비행 중 예외 금지」와 정면으로 어긋난다.
    # 상한만 시험하면 이 변이가 저장소 어디서도 안 죽는다
    nav.pos_n = np.array([0.0, 0.0, 6_000.0])  # h = -6000 m, ISA 하한 밖
    out = bd.graph_inputs(cmd, nav)
    assert out["h"] == -6_000.0, "고도 자체는 클램프하지 않는다"
    assert out["mach"] > 0.0 and np.isfinite(out["mach"]), "하한 클램프가 사라졌다"


def test_승강률은_상승이_양수다():
    """`hdot = -nav.vel_n[2]` — NED는 아래가 양수라 부호를 뒤집는다.

    부호를 그대로 두면 상승 지령에 하강한다. 폐루프 테스트가 잡지만 진단이 멀다.
    """
    cmd, nav = _sample()
    nav.vel_n = np.array([50.0, 0.0, -3.0])  # 아래로 -3 = 상승
    assert bd.graph_inputs(cmd, nav)["hdot"] == 3.0, "상승인데 승강률이 음수다"
    nav.vel_n = np.array([50.0, 0.0, 4.0])
    assert bd.graph_inputs(cmd, nav)["hdot"] == -4.0


def test_경계_함수는_그래프를_모른다():
    """조립은 계약 → 값이고, 그래프 구조는 `fcl/graphs.py`가 정본이다.

    경계가 그래프를 조립하거나 실행하기 시작하면 「구조의 정본은 IR 하나」가 깨진다.
    """
    tree = ast.parse((_SRC / "fcl" / "boundary.py").read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    leaked = {x for x in names if "ir_exec" in x or "emit_c" in x or "typerules" in x}
    assert not leaked, f"경계가 백엔드를 본다: {leaked}"
    # `FCL_INPUTS`만 읽는다 — 그래프 빌더를 부르지 않는다
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "fcl_graph" not in called


@pytest.mark.parametrize("missing", ["cmd_alt", "nav_valid", "mach"])
def test_키를_빠뜨리면_경계_표가_먼저_죽는다(missing):
    """정말 지우고 import한다 — 문자열 존재만 보면 독스트링에만 있어도 통과한다.

    `raise`인 것도 함께 지킨다. `assert`였다면 `python -O`에서 이 대조가 통째로
    사라지고, 누락이 비행 제어 경로의 `step_all`까지 내려가 늦게 터진다.
    """
    src = (_SRC / "fcl" / "boundary.py").read_text(encoding="utf-8")
    # `count=1`은 **파일에서 처음 나오는** 그 키를 지운다. 표가 조립보다 위라 지금은
    # 정확히 표 항목이 지워지지만, 순서가 뒤집히면 조립의 `"mach": float(...)` 쪽을
    # 지우고 「지킴이가 사라졌다」는 엉뚱한 실패가 난다 — 표 모양인지 먼저 본다
    assert re.search(rf'^\s*"{missing}": [("]', src, flags=re.M), (
        f"{missing}이 표 항목 모양이 아니다 — 표의 형태가 바뀌었다"
    )
    cut = re.sub(rf'^\s*"{missing}": [("].*\n', "", src, count=1, flags=re.M)
    assert cut != src, f"{missing} 항목을 못 찾았다 — 표의 모양이 바뀌었다"
    with pytest.raises(RuntimeError, match="경계 표가 그래프 입력과 어긋났다"):
        exec(compile(cut, "boundary_mut", "exec"), {"__name__": "boundary_mut"})
