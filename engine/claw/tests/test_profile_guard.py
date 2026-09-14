"""가드 — 제품 코드는 예제 기체를 전제하지 않는다 (02 §5.6).

`plant/demo.py`·`fcl/demo.py`는 예제 프로파일을 감싸는 호환 층이라 테스트는 쓸 수 있다. 제품 코드
(엔진·서버·생성기)가 그것을 부르면 "기체를 고르면 모든 계산이 그 기체를 쓴다"가 조용히 깨진다 —
예제 기체로 계산하고 선택한 기체의 이름을 붙이게 된다. 그래서 **알려진 길을 막는다**: 모듈
import(상대 포함), 부모 패키지에서 `demo`·`*`를 꺼내기, `importlib.import_module`, 그리고 어디서
나오든 `make_demo_*`·`DEMO_*` **이름 자체**(별칭·속성 접근·`getattr` 문자열). 그 이름들은 호환 층에만
있으므로 이름으로 잡는 것이 경로를 하나하나 세는 것보다 넓다. 문자열을 조립하는 의도적 우회까지
막지는 못한다 — 가드는 실수를 막는 장치다.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]  # 저장소 루트
# (훑을 경로, 그 경로의 import 루트) — 상대 import를 절대 이름으로 풀 때 쓴다
SCOPES = [
    (ROOT / "engine/claw", ROOT / "engine"),
    (ROOT / "server/claw_server", ROOT / "server"),
    (ROOT / "flight/generate.py", ROOT / "flight"),
]
# 호환 층 자신과 그 재수출 — 여기만 예제 이름을 들고 있어도 된다
ALLOWED = {"engine/claw/plant/demo.py", "engine/claw/fcl/demo.py",
           "engine/claw/plant/__init__.py", "engine/claw/fcl/__init__.py"}
DEMO_MODULES = ("claw.plant.demo", "claw.fcl.demo")
PARENTS = ("claw.plant", "claw.fcl")
DEMO_NAME_PREFIXES = ("make_demo_", "demo_", "DEMO_")
# 이름만 보고 잡는 접두 — `demo_`는 제품 코드의 평범한 이름(라우트 함수 등)과 겹쳐 뺀다
DEMO_ONLY_PREFIXES = ("make_demo_", "DEMO_")


def _files():
    for scope, import_root in SCOPES:
        paths = [scope] if scope.is_file() else sorted(scope.rglob("*.py"))
        for p in paths:
            rel = p.relative_to(ROOT)  # 체크아웃 위치의 폴더 이름에 휘둘리지 않게 저장소 기준으로
            if "tests" in rel.parts or rel.as_posix() in ALLOWED:
                continue
            yield p, import_root


def _package(path, import_root):
    parts = path.relative_to(import_root).with_suffix("").parts
    return parts[:-1]  # 모듈(또는 __init__)이 사는 패키지


def _is_demo_module(name):
    return any(name == m or name.startswith(m + ".") for m in DEMO_MODULES)


def _dotted(node):
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
        return ".".join(reversed(names))
    return None


def _violations(source, package=()):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(package[: len(package) - (node.level - 1)]) if node.level > 1 else list(package)
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            if _is_demo_module(module):
                yield node.lineno, f"from {module} import …"
            elif module in PARENTS:
                for alias in node.names:
                    if alias.name in ("demo", "*") or alias.name.startswith(DEMO_NAME_PREFIXES):
                        yield node.lineno, f"from {module} import {alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _is_demo_module(alias.name):
                    yield node.lineno, f"import {alias.name}"
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node) or node.attr
            if dotted in DEMO_MODULES or node.attr.startswith(DEMO_ONLY_PREFIXES):
                yield node.lineno, f"속성 접근 {dotted}"
        elif isinstance(node, ast.Name) and node.id.startswith(DEMO_ONLY_PREFIXES):
            yield node.lineno, f"이름 {node.id}"
        elif isinstance(node, ast.Call):
            fn = _dotted(node.func) or ""
            consts = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if fn.endswith("import_module") or fn == "__import__":
                name = consts[0] if consts else ""
                if name.startswith(".") and len(consts) > 1:  # import_module(".demo", "claw.fcl")
                    name = consts[1] + name
                if _is_demo_module(name.replace("..", ".")):
                    yield node.lineno, f"{fn}({', '.join(map(repr, consts))})"
            elif fn == "getattr" and any(c.startswith(DEMO_ONLY_PREFIXES) or c == "demo" for c in consts):
                yield node.lineno, f"getattr(…, {consts!r})"


def test_product_code_does_not_reach_the_example_aircraft():
    files = list(_files())
    rels = {p.relative_to(ROOT).as_posix() for p, _ in files}
    # 훑은 파일이 없으면 가드가 아무것도 안 보고 통과한다 — 대표 파일이 실제로 들어왔는지 본다
    assert {"engine/claw/fcl/assemble.py", "server/claw_server/refs.py", "flight/generate.py"} <= rels
    found = [f"{p.relative_to(ROOT)}:{line}: {what}"
             for p, root in files
             for line, what in _violations(p.read_text(encoding="utf-8"), _package(p, root))]
    assert not found, "제품 코드가 예제 기체 호환 층에 닿는다 — 기체 프로파일로 받을 것:\n" + "\n".join(found)


def test_the_guard_catches_every_route():
    bad = [
        "from claw.plant import make_demo_aircraft",
        "from claw.plant import make_demo_aircraft as mk",
        "from claw.fcl.demo import DEMO_PITCH",
        "import claw.fcl.demo as x",
        "from claw.fcl import demo",
        "from claw.plant import demo as pd",
        "import claw.plant\nclaw.plant.make_demo_aircraft()",
        "import claw.fcl\nclaw.fcl.demo.make_demo_fcl()",
        "import importlib\nimportlib.import_module('claw.fcl.demo')",
        "from claw.plant import *",
        "import claw.plant as P\nP.make_demo_aircraft()",
        "from claw import plant\nplant.make_demo_aircraft()",
        "import claw.plant\ngetattr(claw.plant, 'make_demo_aircraft')",
        "import importlib\nimportlib.import_module('.demo', 'claw.fcl')",
    ]
    for src in bad:
        assert list(_violations(src)), src
    # 상대 import — claw.fcl 패키지 안의 모듈이라고 보고 푼다
    assert list(_violations("from .demo import DEMO_PITCH", package=("claw", "fcl")))
    assert list(_violations("from . import demo", package=("claw", "fcl")))
    assert list(_violations("from ..plant.demo import make_demo_aircraft", package=("claw", "fcl")))
    # 정상 코드는 걸리지 않는다
    assert not list(_violations("import claw.plant\nclaw.plant.aero\nfrom claw.fcl import assemble"))
