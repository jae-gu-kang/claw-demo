"""IR semantic 타입 — 어휘와 선언 저장, 그리고 **비침습성** (07 §8).

이 파일의 절반은 타입이 **무엇을 하지 않는지**를 못박는다. Phase 1·2의 존재 이유가
"검증만 강화하고 생성물은 안 건드린다"이므로, 그 약속을 지키는 것이 곧 테스트다:
생성 C 바이트 동일 · 지문 불변 · 노드 서명 불변 · 두 백엔드가 import조차 안 함.
"""

import ast
import dataclasses
import re
from pathlib import Path

import pytest

from claw.codegen import GraphRunner, emit_c
from claw.codegen import irtypes as t
from claw.codegen.emit_c import _Ctx  # noqa: F401  (아래 폭 검사에서 쓴다)
from claw.codegen.ir import Graph, Node
from claw.fcl.demo import DEMO_YAW, make_demo_fcl
from claw.fcl import graphs as g_
from claw.fcl.graphs import scas_axis_graph
from claw.params.paramset import canonical_hash
from claw.pipeline.influence import node_signature

DT = 0.01
_SRC = Path(__file__).resolve().parents[1] / "codegen"


def _graph(types=None):
    """데모 축 그래프를 그대로 쓰되 선언만 얹는다 (그래프 정의에 다는 것은 뒤 단계다)."""
    g = scas_axis_graph("ax", **DEMO_YAW)
    return Graph(g.name, g.inputs, g.nodes, g.outputs, g.enable, signal_types=types)


def _module(graph):
    return emit_c(graph, GraphRunner(graph, DT))


# ── 어휘 ──────────────────────────────────────────────────────────────────


def test_단위는_저장하지_않고_물리량에서_파생한다():
    """필드로 두면 `quantity="angle", unit="deg"` 같은 자기모순이 표현 가능해진다."""
    assert t.ANGLE.unit == "rad" and t.ANGULAR_RATE.unit == "rad/s"
    assert t.REAL.unit is None, "미지정 물리량에 단위를 지어내지 않는다"
    # 표시도 kind를 잃지 않는다 — real만 물리량으로, 나머지는 kind로 읽힌다
    assert (str(t.BOOL), str(t.ANGLE), str(t.REAL)) == ("bool", "angle", "real")
    # 저장 방식과 무관하게 못박는다 — `slots=True`를 붙이면 `hasattr(__dict__)`가
    # False가 되어 예전 형태는 unit이 필드가 돼도 통과했다
    assert "unit" not in {f.name for f in dataclasses.fields(t.Type)}
    assert isinstance(vars(t.Type)["unit"], property)


def test_모순되는_타입은_만들_수_없다():
    for bad in (
        dict(kind="bool", quantity="angle"),  # quantity는 real 전용
        dict(quantity="furlong"),             # 모르는 물리량
        dict(kind="enum"),                    # choices 없는 enum
        dict(kind="vector"),                  # 길이 없는 vector
        dict(kind="vector", n=0),             # 길이 0도 벡터가 아니다
        dict(lo=1.0, hi=0.0),                 # 뒤집힌 범위
        dict(kind="quaternion"),              # 모르는 kind
        dict(kind="real", n=4),               # 길이는 vector 전용
        dict(kind="real", choices=("a",)),    # 멤버는 enum 전용
        dict(kind="bool", lo=-3.0, hi=7.0),   # 범위는 수치 전용
        dict(kind="enum", choices="hold"),    # 문자열은 4멤버로 조용히 굳는다
        dict(kind="real", choices=None),      # falsy도 같은 문으로 걸려야 한다
        dict(kind="real", choices=""),        # 조건부였다면 조용히 ()가 됐다
    ):
        with pytest.raises(ValueError):
            t.Type(**bad)


def test_단위_철자가_ParamDef와_같다():
    """갈라지면 같은 물리량이 두 철자로 산다 — conventions §3의 기계 판독본이 정본이다."""
    import importlib
    import pkgutil

    import claw
    from claw.params.param import ParamDef

    seen, failed = set(), []
    # onerror 기본값은 서브패키지 진입 실패를 **조용히 삼킨다** — 통째로 빠진 채
    # "철자가 다 있다"고 말하게 되므로 시끄럽게 만든다
    for mod_info in pkgutil.walk_packages(claw.__path__, "claw.", onerror=failed.append):
        if ".tests" in mod_info.name:
            continue
        try:
            mod = importlib.import_module(mod_info.name)
        except Exception as exc:
            failed.append(f"{mod_info.name}: {exc}")
            continue
        for obj in vars(mod).values():
            for d in getattr(obj, "PARAM_DEFS", ()) or ():
                if isinstance(d, ParamDef):
                    seen.add(d.unit)
    assert not failed, f"모듈을 못 읽어 훑기가 반쪽이다: {failed}"
    assert len(seen) > 10, f"ParamDef를 {len(seen)}종밖에 못 봤다 — 훑기가 안 돌았다"
    unknown = set(t.QUANTITY_UNIT.values()) - seen - {"-"}
    assert not unknown, f"ParamDef 어디에도 없는 단위 철자: {sorted(unknown)}"


def test_물리량과_단위의_짝을_직접_못박는다():
    """철자 **집합**만 보면 짝을 뒤섞어도 통과한다 — 「일관된 거짓」이 남는 자리다.

    `unit`을 파생 property로 둔 논지가 "표 하나가 정본이면 모순이 표현 불가능"인데,
    표 자체가 통째로 틀리면 전 신호가 한꺼번에 조용히 틀린다. 그래서 짝을 직접 적는다.
    """
    assert t.QUANTITY_UNIT == {
        "dimensionless": "-",
        "angle": "rad",
        "angular_rate": "rad/s",
        "airspeed": "m/s",
        "altitude": "m",
        "climb_rate": "m/s",
        "mach": "-",
        "normalized": "-",
        "time": "s",
    }, "물리량↔단위 짝이 바뀌었다 — conventions §3과 대조할 것"


def test_미지정_실수는_하나다():
    """`desc`가 신원에 들어가면 「이유를 적은 미지정」이 별개 타입이 된다.

    07 §10이 다음 단계의 전제로 "미지정은 무엇과도 통일된다"를 세워 뒀는데, 통일을
    `==`나 dict 키로 구현하는 첫 시도가 바로 그 전제를 깬다 — 게인 포트와 연료가
    서로, 그리고 `REAL`과 불일치로 잡힌다. 그러면서 이유는 선언에 남아 있어야 한다.
    """
    tops = (t.REAL, g_.SCHEDULED_GAIN, g_.SIGNAL_TYPES["fuel"])
    assert len(set(tops)) == 1, "미지정이 여럿으로 갈라졌다"
    assert len({hash(x) for x in tops}) == 1, "같은 타입인데 해시가 다르다"
    assert all(x.desc for x in tops[1:]), "미지정으로 둔 이유는 선언에 남아야 한다"
    assert t.Type(desc="아무 말") == t.REAL


def test_choices는_튜플로_굳는다():
    """리스트로 주면 **해시 불가**라 값 의미론이 조용히 깨진다 — 타입은 비교·통일되는 물건이다."""
    made = t.Type(kind="enum", choices=["hold", "track"])
    assert isinstance(made.choices, tuple)
    assert hash(made) == hash(t.enum_of("hold", "track")), "같은 멤버면 같은 타입이어야 한다"


# ── 선언 저장 ─────────────────────────────────────────────────────────────


def test_없는_신호에_타입을_달면_거부한다():
    """오타가 조용히 무시되면 선언했는데 아무도 안 보는 상태가 된다."""
    # 앞에 정상 선언을 둔다 — 검사가 첫 항목만 보고 끝내면 이 테스트가 살아남는다
    with pytest.raises(ValueError, match="노드 id도 아니다"):
        _graph({"rate": t.ANGULAR_RATE, "엉뚱한이름": t.ANGLE})


def test_Type이_아닌_선언은_거부한다():
    """이 분기를 지우면 나머지 테스트가 전부 통과한다 — 그래서 따로 못박는다."""
    with pytest.raises(TypeError, match="Type이 아니다"):
        _graph({"rate": "rad/s"})


def test_vector는_어휘에_있고_백엔드에는_없다():
    """선언 시점에 말한다 — 방출 깊은 곳에서 터지는 것보다 정직하다."""
    with pytest.raises(ValueError, match="백엔드가 없다"):
        _graph({"rate": t.vector_of(4)})


def test_선언이_없으면_검사_모듈을_만나지도_않는다():
    """지연 import가 계층 방어라는 주장의 지킴이 — 별도 프로세스로만 볼 수 있다.

    이 파일이 맨 위에서 `irtypes`를 import하므로 같은 프로세스의 `sys.modules`
    검사로는 못 잡는다. `if self.signal_types:`를 지워도 다른 테스트는 전부 통과한다.
    """
    import subprocess
    import sys

    assert _graph().signal_types == {}
    src = (
        "import sys\n"
        "from claw.codegen.ir import Graph, Op\n"
        "Graph('g', ('x',), [Op('y', 'add_const', inputs=('x',), value=1.0)], {'o': 'y'})\n"
        "print('irtypes' if 'claw.codegen.irtypes' in sys.modules else 'clean')\n"
    )
    out = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "clean", "선언 없는 그래프가 타입 모듈을 끌어들였다"


# ── 비침습성: 타입은 아무것도 만들지 않는다 ──────────────────────────────


DECLARED = {
    "att_err": t.ANGLE,
    "rate": t.ANGULAR_RATE,
    # 기대 범위를 촘촘히 준 자리 — 이것으로 clamp가 생기면 아래 바이트 대조가 죽는다
    "sat": t.Type(quantity="angle", lo=-0.35, hi=0.35, desc="타면 명령"),
}
# enum kind는 **저장소에 실물이 없다.** 그래서 진짜 신호에 거짓으로 달지 않고, 이
# 픽스처 하나에만 둔다 — 이름이 그것이 합성임을 말한다. bool은 실물이 있으므로
# (`lim_active`) 아래 실제 그래프 검사가 덮는다.
SYNTHETIC_ENUM = {"pid": t.enum_of("hold", "track", desc="실물 없음 — kind 축 커버리지")}


def test_타입_선언은_생성_C를_한_바이트도_바꾸지_않는다():
    assert _module(_graph()).files == _module(_graph(DECLARED)).files


def test_기대_범위는_포화를_만들지_않는다():
    """range = 분석 메타데이터, Saturation = 실행 동작. 둘을 섞으면 리미터가 두 벌이 된다."""
    ranged = {k: t.Type(quantity="angle", lo=-0.1, hi=0.1) for k in ("att_err", "rate", "sat")}
    plain, typed = _module(_graph()), _module(_graph(ranged))
    # 바이트 동일에 더해 **클램프 자리 수**를 직접 센다 — 이름이 말하는 것을 못박는다
    def clips(m):
        return sum(f.count("claw_clip") for f in m.files.values())

    assert clips(plain) == 2, "클램프 자리를 못 찾았다 — 세는 이름이 바뀌었나(0 == 0은 공허하다)"
    assert clips(plain) == clips(typed), "expected_range가 클램프를 낳았다"
    assert plain.files == typed.files


def test_없는_kind도_백엔드로_새지_않는다():
    """실물이 없는 enum까지 덮는다 — 백엔드가 kind로 분기하면 바이트가 갈린다."""
    assert _module(_graph()).files == _module(_graph(DECLARED | SYNTHETIC_ENUM)).files


def test_지문은_타입_선언에_반응하지_않는다():
    assert _module(_graph()).fingerprint == _module(_graph(DECLARED)).fingerprint


def test_지문_payload는_타입_항목을_품지_않는다(monkeypatch):
    """나중에 누가 무심코 타입을 넣으면 여기서 죽는다 — 지문은 형상의 신원이다."""
    seen = {}

    def spy(payload):
        seen.update(payload)
        return "0" * 16

    import importlib

    monkeypatch.setattr(importlib.import_module("claw.codegen.emit_c"),
                        "canonical_hash", spy)
    _module(_graph(DECLARED))
    kinds = {k.split(".")[0] for k in seen}
    allowed = {"param", "array", "dt", "structure", "outputs", "inputs", "enable"}
    assert kinds <= allowed, f"지문 payload에 새 항목이 생겼다: {sorted(kinds - allowed)}"
    # 공허하지 않게 — 스파이가 실제로 payload를 봤는지 함께 확인한다
    assert {"dt", "structure", "inputs", "outputs"} <= kinds


def test_두_백엔드는_타입_모듈을_임포트하지_않는다():
    """평범한 import 경로를 막는다 — `importlib` 우회나 `graph.signal_types` 직접 접근은
    이 검사가 못 잡고, 그쪽은 바이트·지문 대조가 뒤를 받는다.
    """
    for fname in ("emit_c.py", "ir_exec.py"):
        tree = ast.parse((_SRC / fname).read_text(encoding="utf-8"))
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        leaked = {n for n in names if "irtypes" in n or "typerules" in n}
        assert not leaked, f"{fname}가 타입 모듈을 본다: {leaked}"


def test_노드는_타입_필드를_갖지_않는다():
    """`Node`가 필드를 안 얻으면 영향성 노드 서명은 **바뀔 수 없다** — 제외 규칙이 아니라 구조다."""
    n = Node("x", block=object, inputs=("a",))
    assert set(vars(n)) == {
        "id", "block", "params", "inputs", "gains", "enable", "on_disable", "disabled_output",
    }, f"Node 속성이 늘었다 — pipeline/influence.py의 서명을 함께 볼 것: {sorted(vars(n))}"


def test_타입_선언은_노드_서명을_바꾸지_않는다():
    a, b = _graph(), _graph(DECLARED)
    assert [node_signature(n) for n in a.nodes] == [node_signature(n) for n in b.nodes]


def test_선언_dict는_복사된다():
    """복사를 안 하면 나중에 넣은 선언이 `check_declarations`를 **한 번도 안 거친 채** 산다."""
    mine = {"rate": t.ANGULAR_RATE}
    g = _graph(mine)
    mine["엉뚱한이름"] = t.ANGLE
    assert "엉뚱한이름" not in g.signal_types


def test_선언은_저장되고_읽힌다():
    g = _graph(DECLARED)
    assert g.signal_types["rate"] is t.ANGULAR_RATE
    assert g.signal_types["sat"].lo == -0.35
    assert str(g.signal_types["att_err"]) == "angle"


def test_문서가_이_모듈을_가리킨다():
    """어휘 정본의 위치가 문서와 코드에서 갈리면 다음 사람이 표를 하나 더 만든다."""
    doc = (Path(__file__).resolve().parents[3] / "docs"
           / "fcs-context-07-ir-and-backends.md").read_text(encoding="utf-8")
    assert re.search(r"irtypes", doc), "07이 어휘 정본(codegen/irtypes.py)을 안 가리킨다"


# ── 실제 그래프: 어휘가 진짜 신호를 표현하는가 ────────────────────────────
# 여기까지가 없으면 이 타입 시스템이 증명한 것은 "아무것도 안 한다" 뿐이다.
# 소비자가 픽스처밖에 없는 상태는 이 저장소가 결함으로 적어 둔 형태다 (04 §10).


def _all_graphs():
    """일곱 빌더 전부 — 게인 포트가 있는 두 개는 켠 판도 함께 본다."""
    from claw.plant import make_demo_stall_table

    law = make_demo_fcl()
    law.init(DT)
    return {
        "scas_axis": scas_axis_graph("ax", **DEMO_YAW),
        # 단독 축은 접두 없이 `kp`·`ki`·`k_rate`를 포트로 쓴다 — 이름 모양이 다른 판을
        # 함께 본다. 셋을 다 켜는 이유는 `k_rate` 자리를 아무도 안 밟고 있었기 때문이다
        "scas_axis_sched": scas_axis_graph(
            "ax", **dict(DEMO_YAW, scheduled=("kp", "ki", "k_rate"))),
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


def test_일곱_그래프가_전부_선언을_들고_있다():
    """선언이 조용히 떨어져 나가면 검사가 통과가 아니라 **빈 검사**가 된다."""
    for name, g in _all_graphs().items():
        assert g.signal_types, f"{name}에 선언이 하나도 없다"


def test_그래프_입력은_빠짐없이_선언된다():
    """미선언이 하나도 없다 — 게인 포트까지 포함해서다.

    조용히 건너뛰면 오타 하나가 「선언했는데 아무도 안 보는」 상태로 굳는다.
    """
    for name, g in _all_graphs().items():
        undeclared = [i for i in g.inputs if i not in g.signal_types]
        assert not undeclared, f"{name}: 미선언 입력 {undeclared}"
    # 공허하지 않게 — 게인 포트를 켠 판이 실제로 목록에 있어야 한다
    ports = [i for i in _all_graphs()["scas3_ports"].inputs if i.startswith("g_")]
    assert len(ports) == 9, f"게인 포트를 켠 판을 안 보고 있다: {ports}"


def test_모르는_신호는_조용히_넘어가지_않는다():
    """관대함이 곧 구멍이다 — 새 신호는 여기서 막혀야 한다."""
    with pytest.raises(KeyError, match="타입 선언이 없는 신호"):
        g_._types_for(("theta", "새로운신호"))


def test_게인은_물리량_없는_실수다():
    """자리마다 차원이 다르다(피치 kp는 무차원, 속도 kp는 s/m, 고도 kp는 rad/m).

    하나의 GAIN 타입으로 묶으면 거짓이라 **미지정(top)이 결론**이다. top이므로 무엇과도
    통일돼 거짓 양성을 안 만든다 — 규칙이 들어와도 게인이 검사를 망치지 않는다.
    """
    assert g_.SCHEDULED_GAIN.kind == "real"
    assert g_.SCHEDULED_GAIN.quantity is None, "게인에 물리량을 지어내면 거짓이 된다"
    assert g_.SCHEDULED_GAIN.desc, "미지정이 결론이라는 근거가 선언에 남아야 한다"
    # 자리 목록은 `SCHEDULABLE` 정본에서 파생한다 — 두 벌 적히면 반드시 어긋난다
    assert set(g_.GAIN_PORT_TYPES) == (
        {f"g_{grp}_{k}" for grp, keys in g_.SCHEDULABLE.items() for k in keys}
        | set(g_._SCHEDULABLE)
    )
    assert len(g_.GAIN_PORT_TYPES) == 19, "16 스케줄 자리 + 단독 축 3자리"


def test_fcl_입력_23개가_전부_선언된다():
    """경계는 빠짐없이 선언된다 — 하나만 빠져도 그 그래프가 조립되지 않는다."""
    missing = set(g_.FCL_INPUTS) - set(g_.SIGNAL_TYPES)
    assert not missing, f"FCL 입력인데 정본 표에 없다: {sorted(missing)}"
    assert len(g_.FCL_INPUTS) == 23, "경계가 바뀌었다 — law.py·verify/trace.py와 함께 볼 것"


def test_실제_fcl_그래프도_생성_C를_한_바이트도_바꾸지_않는다():
    """축 픽스처가 아니라 **탑재 코드가 나오는 그래프**로 본다 — 선언이 40개 붙어 있다."""
    law = make_demo_fcl()
    law.init(DT)
    typed = law.runner.graph
    assert len(typed.signal_types) == 40, "선언 수가 바뀌었다 — 아래 대조의 무게가 달라진다"
    plain = Graph(typed.name, typed.inputs, typed.nodes, typed.outputs, typed.enable)
    assert _module(plain).files == _module(typed).files
    assert _module(plain).fingerprint == _module(typed).fingerprint


def test_리미터의_cap은_자세각과_공력_마진의_합이다():
    """카탈로그가 거친 이유가 주석이 아니라 **선언**이 되는 자리다 (07 §10).

    ANGLE을 자세각/공력각으로 쪼개면 이 한 줄이 거부된다. 쪼개려는 다음 사람은
    여기서 반례를 만난다.
    """
    g = _all_graphs()["limiter"]
    cap = next(n for n in g.nodes if n.id == "cap")
    assert cap.inputs == ("theta", "a_margin"), f"cap의 인자가 바뀌었다: {cap.inputs}"
    # `alpha`·`alpha_max`·`stall`도 같은 사슬이다 — `a_margin = Sum(alpha_max, alpha)`
    margin = next(n for n in g.nodes if n.id == "a_margin")
    assert margin.inputs == ("alpha_max", "alpha"), f"마진 계산이 바뀌었다: {margin.inputs}"
    assert {str(g.signal_types[s]) for s in
            ("theta", "a_margin", "cap", "alpha", "alpha_max", "stall")} == {"angle"}


def test_불리언_실물은_lim_active_하나다():
    """`gt`가 낳는 진짜 불리언인데 `double`로 실려 나간다 (07 §7).

    Phase 3에서 native 타입으로 내릴 대상이 여기 적혀 있다 — 그때 찾아다니지 않는다.
    """
    g = _all_graphs()["fcl"]
    bools = {s for s, ty in g.signal_types.items() if ty.kind == "bool"}
    node_bools = {s for s in bools if s not in g.inputs}
    assert node_bools == {"lim_active"}, f"노드 불리언이 바뀌었다: {sorted(node_bools)}"
    assert next(n for n in g.nodes if n.id == "lim_active").op == "gt"
    assert g.outputs["limiter_active"] == "lim_active"


def test_리미터가_없으면_리미터_선언도_없다():
    """`stall_table=None`이면 그 노드가 아예 없다 — 선언만 남으면 `Graph`가 거부한다.

    조건부 부착은 가드다. 지킴이가 없으면 조건을 지운 채로 통과한다.
    """
    law = make_demo_fcl()
    law.init(DT)
    bare = g_.fcl_graph(autopilot=law.autopilot.cfg, scas_axes=law.scas.cfg,
                        mixer=law.mixer.cfg)
    assert not any(s.startswith("lim_") for s in bare.signal_types)
    # 리미터만 빠진다 — 입력과 믹서 경계는 그대로다
    assert set(g_.FCL_INPUTS) <= set(bare.signal_types)
    assert {"mix_elevon_l", "mix_thr_l"} <= set(bare.signal_types)
    # 조건을 지우면(무조건 부착) 여기가 아니라 Graph가 먼저 죽는다 — 그것을 못박는다
    with pytest.raises(ValueError, match="노드 id도 아니다"):
        Graph(bare.name, bare.inputs, bare.nodes, bare.outputs, bare.enable,
              signal_types=dict(bare.signal_types, lim_cap=t.ANGLE))


def test_스케줄_축_셋이_다_선언된다():
    """`_types_for`가 엄격해진 대가다 — 빠진 축은 **정당한 설계를 못 만들게** 만든다.

    데모가 `mach` 하나만 쓴다고 나머지를 안 적으면, `alt`·`fuel`로 스케줄한 설계가
    그래프 조립에서 죽는다. 서버·영향성·자동설계가 편집 형상마다 재조립하므로 그
    거짓 양성은 곧 화면의 500이다. 그래서 데모가 안 밟는 축까지 여기서 직접 밟는다.
    """
    from claw.fcl.schedule import SCHED_VARS
    from claw.tables import Table

    assert set(SCHED_VARS) <= set(g_.SIGNAL_TYPES), (
        f"스케줄 축인데 선언이 없다: {sorted(set(SCHED_VARS) - set(g_.SIGNAL_TYPES))}"
    )
    for var in SCHED_VARS:
        tab = Table({var: [0.0, 1.0]}, [1.0, 0.8], name="pitch.kp", extrapolate="clip")
        graph = g_.gain_schedule_graph(tables={"pitch.kp": tab}, filter_tau=0.0)
        # 축 하나(입력) + 게인 하나(낳는 노드) — 낳는 쪽도 선언된다
        assert set(graph.signal_types) == {var, "pitch_kp"}, \
            f"{var} 축 그래프의 선언이 이상하다: {sorted(graph.signal_types)}"
        # `desc`가 신원에서 빠졌으므로 `==`는 「미지정이기만 하면」 통과한다 — 그
        # 미지정이 **결론이라는 근거**까지 같은지 봐야 지킴이가 된다
        assert graph.signal_types["pitch_kp"] is g_.SCHEDULED_GAIN
    # 선언했다고 아무 물리량이나 붙이면 안 된다 — 「빠짐없이」가 「아무거나」가 되는 자리다
    assert g_.SIGNAL_TYPES["alt"] is t.ALTITUDE, "고도 축은 `h`와 같은 물리량이다"
    assert g_.SIGNAL_TYPES["fuel"].quantity is None, (
        "연료는 질량인데 어휘에 질량이 없다 — 다른 물리량을 지어내면 거짓 선언이다"
    )
    assert g_.SIGNAL_TYPES["fuel"].desc, "미지정으로 둔 이유가 선언에 남아야 한다"


def test_게인_차원표가_ParamDef와_맞는다():
    """게인을 하나로 못 묶는다는 **결론의 근거**를 저장소 값으로 확인한다.

    이 테스트가 지키는 것은 `ParamDef` 쪽이다 — 주석 표가 낡는 것은 못 잡는다(주석을
    읽지 않는다). 그래도 값이 바뀌면 여기서 죽고, 그때 주석을 함께 보게 된다.
    """
    from claw.fcl.autopilot import Autopilot
    from claw.fcl.scas import ScasAxis

    units = {d.name: d.unit
             for cls in (Autopilot, ScasAxis) for d in cls.PARAM_DEFS}
    assert units["kp_spd"] == "s/m", "속도축 kp가 무차원이 아님을 못박는다"
    assert units["kp_alt"] == "rad/m", "고도축 kp는 또 다른 차원이다"
    assert units["k_hdot"] == "rad·s/m"
    assert units["ki_spd"] == "1/m" and units["ki_alt"] == "rad/(m·s)"
    assert units["kp_hdg"] == "-" and units["ki_hdg"] == "1/s"
    assert units["kp"] == "-" and units["ki"] == "1/s" and units["k_rate"] == "s", \
        "SCAS 자세축만 「kp: -, ki: 1/s, k_rate: s」다 — 이것이 보편 주장이 아니다"
    # 같은 이름의 게인이 실제로 여러 차원을 갖는다는 것이 요지다 — 그것을 직접 센다
    kp_units = {units[n] for n in ("kp", "kp_spd", "kp_alt", "kp_hdg")}
    assert len(kp_units) == 3, f"`kp`가 한 차원으로 모였다: {kp_units}"


def test_명령은_그것이_명령하는_양과_같은_타입이다():
    """선언의 **내용**을 저장소가 스스로 확인하는 자리다.

    `SIGNAL_TYPES`의 주석이 "명령은 그것이 명령하는 양과 같은 타입이다 — 오토파일럿이
    실제로 빼는 짝이다"라고 주장한다. 그 짝은 그래프에 실물로 있다: `CommandFilter`가
    (명령, 측정) 둘을 받는다. 그러니 주장을 사람 눈이 아니라 구조가 지킨다 —
    `cmd_alt`를 각도라 하거나 `psi`를 속도라 하면 짝이 어긋나 여기서 죽는다.
    """
    from claw.blocks.filters import CommandFilter

    law = make_demo_fcl()
    law.init(DT)
    g = law.runner.graph
    pairs = [(n.id, n.inputs) for n in g.nodes if getattr(n, "block", None) is CommandFilter]
    assert len(pairs) >= 5, f"짝을 이룬 노드를 못 찾았다 — 검사가 공허하다: {pairs}"

    quantities = set()
    for nid, ins in pairs:
        assert len(ins) == 2, f"{nid}: CommandFilter가 두 입력이 아니다: {ins}"
        types = [g.signal_types.get(i) for i in ins]
        assert all(types), f"{nid}: 짝의 한쪽이 미선언이다 {ins} → {types}"
        assert types[0] == types[1], (
            f"{nid}: 명령과 측정의 타입이 다르다 {ins} → {[str(x) for x in types]}"
        )
        quantities.add(str(types[0]))
    # 한 물리량만 덮으면 「우연히 다 같다」와 구분이 안 된다
    assert len(quantities) >= 4, f"짝이 덮는 물리량이 좁다: {sorted(quantities)}"


def test_정본_표에_죽은_항목이_없다():
    """`check_declarations`가 그래프마다 막는 「선언했는데 아무도 안 보는 것」을
    정본 표 자신에도 건다. 두 표가 겹치지 않는 것도 함께 본다 — 겹치면 병합에서
    뒤가 조용히 이겨 앞의 선언이 흔적 없이 사라진다.
    """
    from claw.fcl.schedule import SCHED_VARS
    from claw.tables import Table

    assert not (set(g_.SIGNAL_TYPES) & set(g_.GAIN_PORT_TYPES)), \
        "두 표가 겹친다 — `SIGNAL_TYPES | GAIN_PORT_TYPES`에서 뒤가 조용히 이긴다"

    graphs = list(_all_graphs().values())
    for var in SCHED_VARS:
        tab = Table({var: [0.0, 1.0]}, [1.0, 0.8], name="pitch.kp", extrapolate="clip")
        graphs.append(g_.gain_schedule_graph(tables={"pitch.kp": tab}, filter_tau=0.0))
    seen = set()
    for graph in graphs:
        seen |= set(graph.inputs) | {n.id for n in graph.nodes} | set(graph.outputs)
    for table, label in ((g_.SIGNAL_TYPES, "SIGNAL_TYPES"),
                         (g_.GAIN_PORT_TYPES, "GAIN_PORT_TYPES")):
        dead = sorted(set(table) - seen)
        assert not dead, f"{label}에 어느 그래프도 안 쓰는 항목: {dead}"


# 아래 셋은 선언의 **내용**을 저장소의 독립 근거로 지킨다. 표를 사람이 눈으로 읽는 것과
# 기계가 다른 출처와 대조하는 것은 다르다 — 거짓 선언 하나가 다음 단계에서 정당한
# 설계를 막는 거짓 양성이 되므로, 표의 진위에도 지킴이가 필요하다.


def _contract_units(cls_name):
    """`common/contracts.py`의 `# [단위]` 주석을 필드별로 읽는다.

    계약은 **사람이 읽는 단위**를 이미 들고 있다. 그것과 선언이 갈리면 경계에서
    두 진실이 사는 것이므로, 파싱이 실패하면 조용히 넘어가지 않고 죽는다.
    """
    src = (Path(__file__).resolve().parents[1] / "common" / "contracts.py").read_text(
        encoding="utf-8"
    )
    body = src.split(f"class {cls_name}:", 1)[1].split("\n@", 1)[0]
    found = {}
    for line in body.splitlines():
        m = re.match(r"\s*(\w+):.*#\s*(?:0~1|\[([^\]]+)\])", line)
        if m:
            found[m.group(1)] = m.group(2)  # 0~1이면 None — 무차원 정규화
    return found


def test_명령_경계가_계약의_단위와_같다():
    """`GuidanceCommand`의 `# [m/s]`·`# [rad]`와 선언이 같은 말을 하는지 본다."""
    units = _contract_units("GuidanceCommand")
    expect = {"speed": "cmd_speed", "alt": "cmd_alt", "heading": "cmd_heading",
              "pitch": "cmd_pitch", "hdot": "cmd_hdot"}
    assert set(expect) <= set(units), (
        f"계약에서 단위 주석이 사라졌다: {sorted(set(expect) - set(units))}"
    )
    for field, signal in expect.items():
        declared = g_.SIGNAL_TYPES[signal].unit
        assert declared == units[field].split(",")[0].strip(), (
            f"{signal}: 선언 {declared!r} vs 계약 {units[field]!r}"
        )


def test_타면_명령_경계가_계약의_단위와_같다():
    """`SurfaceCommand`는 나가는 쪽 경계다 — `verify/units.py`가 기록한 사고 자리."""
    units = _contract_units("SurfaceCommand")
    assert {"elevon", "rudder", "throttle"} <= set(units), f"주석이 사라졌다: {units}"
    assert units["elevon"] == "rad" and units["rudder"] == "rad"
    assert units["throttle"] is None, "스로틀은 0~1 정규화라 단위가 없다"
    out = g_.MIXER_OUTPUT_TYPES
    assert {str(out[k]) for k in ("elevon_l", "elevon_r")} == {"angle"}
    assert str(out["rudder"]) == "angle"
    assert {str(out[k]) for k in ("throttle_l", "throttle_r")} == {"normalized"}


def test_정규화_선언과_그것을_묶는_Saturation이_같은_범위다():
    """`lo`/`hi`는 힘이 없지만 **거짓이어서도 안 된다** — 실물 포화가 곧 근거다.

    스로틀은 `Saturation(lo=0, hi=1)`이 실제로 묶는다. 선언의 범위가 그것과 다르면
    나중에 고정소수점이 스케일 근거로 쓸 때 틀린 값을 쓴다.
    """
    from claw.blocks.basic import Saturation

    law = make_demo_fcl()
    law.init(DT)
    g = g_.mixer_graph(**law.mixer.cfg)
    sats = {n.id: n.params for n in g.nodes if n.block is Saturation}
    for nid in ("thr_l", "thr_r"):
        declared = g.signal_types[nid]
        assert str(declared) == "normalized", f"{nid}가 정규화 선언이 아니다"
        assert (declared.lo, declared.hi) == (sats[nid]["lo"], sats[nid]["hi"]), (
            f"{nid}: 선언 [{declared.lo}, {declared.hi}] vs 실물 포화 {sats[nid]}"
        )
    # 집합 스로틀 입력은 좌/우로 갈리기 전의 같은 양이다 (`thr_l_raw = Sum(thr, diff)`)
    raw = next(n for n in g.nodes if n.id == "thr_l_raw")
    assert g.signal_types["thr"] == g.signal_types["thr_l"], (
        "집합 스로틀과 좌측 스로틀이 다른 타입이다 — 하나가 거짓이다"
    )
    assert raw.inputs[0] == "thr", f"스로틀 경로가 바뀌었다: {raw.inputs}"


def test_동체_각속도_셋과_자세각_셋은_각각_한_타입이다():
    """`law.py`가 한 벡터에서 셋을 함께 뜯는다 — 셋이 다른 타입일 수 없다.

    `p, q, r = nav.omega_b` · `phi, theta, psi = quat_to_euler(nav.q_nb)`. 그래서
    셋 중 하나만 다른 타입으로 적히면 그것이 거짓이다. 두 묶음이 **서로 달라야**
    하는 것도 함께 본다 — 안 그러면 전부 각도로 적어도 통과한다.
    """
    law_src = (Path(__file__).resolve().parents[1] / "fcl" / "law.py").read_text(
        encoding="utf-8"
    )
    assert "p, q, r = nav.omega_b" in law_src, "각속도 경계가 바뀌었다 — 근거를 다시 볼 것"
    assert "phi, theta, psi = quat_to_euler(nav.q_nb)" in law_src, "자세 경계가 바뀌었다"

    rates = {g_.SIGNAL_TYPES[x] for x in ("p", "q", "r")}
    atts = {g_.SIGNAL_TYPES[x] for x in ("theta", "phi", "psi")}
    assert len(rates) == 1, f"한 벡터에서 나온 셋이 다른 타입이다: {[str(x) for x in rates]}"
    assert len(atts) == 1, f"한 사원수에서 나온 셋이 다른 타입이다: {[str(x) for x in atts]}"
    assert rates != atts, "자세각과 각속도가 같은 타입이면 어느 한쪽이 거짓이다"
    assert str(next(iter(rates))) == "angular_rate"


def test_enable과_Switch_제어로_쓰이는_신호는_불리언이다():
    """구조가 곧 근거다 — 그 자리에 쓰인다는 것이 그 신호가 참·거짓이라는 뜻이다.

    `Switch`의 관례는 `(in1, ctrl, in3)`이라 **제어는 두 번째** 입력이다
    (`blocks/basic.py`). 여기 오는 신호를 각도라고 적으면 그것이 거짓이다.
    """
    from claw.blocks.basic import Switch

    law = make_demo_fcl()
    law.init(DT)
    g = law.runner.graph
    switches = [n for n in g.nodes if getattr(n, "block", None) is Switch]
    assert switches, "Switch 노드를 못 찾았다 — 검사가 공허하다"
    ctrl = set()
    for n in switches:
        assert len(n.inputs) == 3, f"{n.id}: Switch가 3입력이 아니다 {n.inputs}"
        ctrl.add(n.inputs[1])
    enables = {n.enable for n in g.nodes if getattr(n, "enable", None)}
    if g.enable:
        enables.add(g.enable)
    assert len(enables) >= 4, f"enable 자리가 너무 적다 — 공허하다: {enables}"

    for signal in sorted(enables | ctrl):
        # 제어가 노드면 그 노드의 타입은 아직 추론의 몫이라 입력만 본다
        if signal not in g.inputs:
            continue
        assert g.signal_types[signal].kind == "bool", (
            f"{signal}: enable·Switch 제어로 쓰이는데 {g.signal_types[signal]}로 선언됐다"
        )
    covered = {s for s in enables | ctrl if s in g.inputs}
    assert len(covered) == 6, f"불리언 입력 여섯을 다 못 덮었다: {sorted(covered)}"


def test_축_명령_셋은_타면_명령과_같은_타입이다():
    """`sum_l = Sum(de, da)` → `elevon_l = Saturation(sum_l)`, `rudder = Saturation(dr)`.

    믹서 산출물은 계약(`SurfaceCommand`)이 `[rad]`로 못박은 값이므로, 그것을 만드는
    축 명령도 같은 양이다. `de`를 무차원이라 적으면 이 사슬이 거짓이 된다.
    """
    law = make_demo_fcl()
    law.init(DT)
    g = g_.mixer_graph(**law.mixer.cfg)
    sum_l = next(n for n in g.nodes if n.id == "sum_l")
    rudder = next(n for n in g.nodes if n.id == "rudder")
    assert set(sum_l.inputs) == {"de", "da"}, f"엘레본 합성이 바뀌었다: {sum_l.inputs}"
    assert rudder.inputs == ("dr",), f"러더 경로가 바뀌었다: {rudder.inputs}"
    for axis, surface in (("de", "elevon_l"), ("da", "elevon_l"), ("dr", "rudder")):
        assert g.signal_types[axis] == g.signal_types[surface], (
            f"{axis}({g.signal_types[axis]})와 {surface}"
            f"({g.signal_types[surface]})가 다른 타입이다"
        )


def test_경계_출력에_선언이_빠지면_죽는다():
    """입력과 **같은 규약**이다 — 조용히 건너뛰면 경계 하나가 소리 없이 미선언이 된다."""
    with pytest.raises(KeyError, match="타입 선언이 없는 경계 출력"):
        g_._typed_outputs({"elevon_l": "x", "새_경계_출력": "y"}, g_.MIXER_OUTPUT_TYPES)
    # 오늘 거를 것이 없다는 사실도 함께 — 표와 이름표가 어긋나면 위가 아니라 여기서 죽는다
    assert set(g_.MIXER_OUTPUT_TYPES) == {"elevon_l", "elevon_r", "rudder",
                                          "throttle_l", "throttle_r"}


def test_짝지어지는_두_신호는_같은_타입이다():
    """`Sum`·`min2`·`gt`는 **두 값을 나란히 놓는** 연산이다 — 다른 물리량이면 그 자리가
    이미 틀렸다. T3의 규칙이 될 것을 지금은 선언에 대한 검사로 쓴다.

    이것이 `theta_cmd`(`pitch_err = Sum(theta_cmd, theta)` · `theta_lim =
    min2(theta_cmd, cap)`)와 `phi_cmd`(`roll_diff = Sum(phi_cmd, phi)`)를 잡는다.
    양쪽이 다 선언된 짝만 본다 — 노드는 아직 추론의 몫이라 한쪽이 비면 건너뛴다.
    """
    from claw.blocks.basic import Sum

    checked, quantities, covered = 0, set(), set()
    for name, g in _all_graphs().items():
        for n in g.nodes:
            # 2입력으로 좁히면 3입력 `Sum`이 생겼을 때 **조용히** 빠진다
            paired = (getattr(n, "block", None) is Sum and len(n.inputs) >= 2) or (
                getattr(n, "op", None) in ("min2", "gt")
            )
            if not paired:
                continue
            types = [g.signal_types.get(i) for i in n.inputs]
            if not all(types):
                continue  # 한쪽이 노드면 아직 모른다
            assert len(set(types)) == 1, (
                f"{name}.{n.id}: 다른 물리량을 나란히 놓았다 "
                f"{n.inputs} → {[str(x) for x in types]}"
            )
            checked += 1
            quantities.add(str(types[0]))
            covered.update(n.inputs)
    # 공허하지 않게 — 짝의 수가 아니라 **덮은 신호의 수**를 센다. 짝 하나가 여러 번
    # 반복돼도 개수는 늘기 때문이다. 오늘 짝은 전부 각도인데(그래서 물리량 종수를
    # 세는 것은 기준이 못 된다) 그래도 검사는 문다: `theta_cmd`를 각속도라 적으면
    # `pitch_err`·`theta_lim`·`active` 세 자리가 동시에 깨진다.
    assert checked >= 10, f"짝을 {checked}개밖에 못 봤다 — 검사가 공허하다"
    assert len(covered) >= 12, f"덮은 신호가 {len(covered)}종뿐이다: {sorted(covered)}"
    # 오늘 짝은 전부 각도지만 **그것을 단언하지는 않는다.** 건너뛴 짝 중에
    # `spd_err(fv, V)`·`alt_err(fh, h)`·`thr_l_raw(thr, diff)`처럼 각도가 아닌 것이
    # 있어서, 경계 선언이 한 걸음 더 나아가는 **옳은 변경**에 이 검사가 죽는다
    assert "angle" in quantities, f"짝이 덮는 물리량이 이상하다: {sorted(quantities)}"


def test_공력각_둘은_같은_타입이다():
    """`airdata_from_nav`가 (V, α, β)를 함께 낸다 — α = atan2(w,u), β = asin(v/V).

    둘 다 각도이므로 하나만 다르게 적히면 그것이 거짓이다. `alpha`는 리미터 사슬이
    독립으로 잡으므로, 이 한 줄이 `beta`까지 끌고 온다.
    """
    src = (Path(__file__).resolve().parents[1] / "fcl" / "airdata.py").read_text(
        encoding="utf-8"
    )
    assert "α = atan2(w,u), β = asin(v/V)" in src, "공력각 정의가 바뀌었다 — 근거를 다시 볼 것"
    assert g_.SIGNAL_TYPES["alpha"] == g_.SIGNAL_TYPES["beta"], "공력각 둘이 다른 타입이다"
    assert str(g_.SIGNAL_TYPES["alpha"]) == "angle"


def test_마하는_속도의_비라서_무차원이다():
    """`mach = V / a` — 같은 물리량의 비다. 단위가 붙으면 그것이 거짓이다."""
    src = (Path(__file__).resolve().parents[1] / "fcl" / "law.py").read_text(encoding="utf-8")
    assert "mach=float(V / isa_atmosphere(h_isa).a)" in src, "마하 계산이 바뀌었다"
    assert g_.SIGNAL_TYPES["mach"] is t.MACH, "마하가 다른 무차원 타입으로 바뀌었다"
    assert g_.SIGNAL_TYPES["mach"].unit == "-", "속도의 비에 단위가 붙었다"
    assert (t.MACH.lo, t.MACH.hi) == (None, None), "마하에 없는 범위가 붙었다"


def test_축_입력_둘은_초_하나만큼_다르다():
    """`damp = Gain(k_rate)`가 rate를 출력 영역으로 옮기고 `ParamDef("k_rate").unit == "s"`다.

    그래서 `[rate]·s = [출력] = [att_err]` — 즉 `rate`는 `att_err`의 「초당」 판이다.
    범용 축이라 출력의 물리량 자체는 모르지만, **둘 사이의 관계**는 안다.
    """
    from claw.fcl.scas import ScasAxis

    units = {d.name: d.unit for d in ScasAxis.PARAM_DEFS}
    assert units["k_rate"] == "s", f"rate 게인의 단위가 바뀌었다: {units['k_rate']}"
    err, rate = g_.SIGNAL_TYPES["att_err"], g_.SIGNAL_TYPES["rate"]
    assert rate.unit == f"{err.unit}/s", (
        f"축 입력 둘의 관계가 깨졌다: att_err {err.unit!r} · rate {rate.unit!r}"
    )
    # 관계식만으로는 둘을 **짝 맞춰** 옮기면(m·m/s) 그대로 만족한다 — 축을 땅에 박는다.
    # 출력 한계가 rad이고 `kp`가 무차원이므로 `att_err`도 rad다
    assert units["out_lo"] == "rad" and units["out_hi"] == "rad", (
        f"축 출력 한계의 단위가 바뀌었다: {units['out_lo']}/{units['out_hi']}"
    )
    assert units["kp"] == "-", "kp가 무차원이 아니면 이 유도가 성립하지 않는다"
    assert err.unit == "rad" and str(g_.AXIS_OUTPUT_TYPES["u"]) == "angle"


def test_그래프_출력도_빠짐없이_선언된다():
    """경계는 들어오는 쪽만이 아니다 — 나가는 값이 미선언이면 소비자가 타입을 못 읽는다.

    입력의 「빠짐없이」와 짝을 이루는 단언이고, 어느 그래프에서 출력 선언이 떨어져
    나가도 여기서 이름을 대며 죽는다.
    """
    for name, g in _all_graphs().items():
        undeclared = [k for k, nid in g.outputs.items() if nid not in g.signal_types]
        assert not undeclared, f"{name}: 미선언 출력 {undeclared}"
    total = sum(len(g.outputs) for g in _all_graphs().values())
    assert total >= 25, f"출력을 {total}개밖에 못 봤다 — 검사가 공허하다"


def test_출력표는_정본에서_파생한다():
    """출력명은 신호명의 **별칭**이다 — 값을 다시 적으면 같은 `de`가 그래프마다 다른
    타입을 갖는 것이 도로 표현 가능해진다(이 파일 머리말이 금지한 상태다).

    표가 하는 일은 철자가 어긋나는 자리를 잇는 것뿐이다: 출력명 `throttle` ↔ 신호명
    `thr`. 그래서 나머지 다섯 키는 정본과 **같은 객체**여야 한다.
    """
    for key in ("theta_cmd", "phi_cmd"):
        assert g_.AP_OUTPUT_TYPES[key] is g_.SIGNAL_TYPES[key], f"{key}가 두 벌 적혔다"
    assert g_.AP_OUTPUT_TYPES["throttle"] is g_.SIGNAL_TYPES["thr"], (
        "스로틀 별칭이 정본을 안 가리킨다"
    )
    for key in ("de", "da", "dr"):
        assert g_.SCAS3_OUTPUT_TYPES[key] is g_.SIGNAL_TYPES[key], f"{key}가 두 벌 적혔다"
    assert set(g_.AP_OUTPUT_TYPES) == {"theta_cmd", "phi_cmd", "throttle"}
    assert set(g_.SCAS3_OUTPUT_TYPES) == {"de", "da", "dr"}
