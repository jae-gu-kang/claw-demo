"""M16 codegen — 제어법칙 구조 IR과 그 백엔드들 (02 §2.2, 03 M16).

구조의 정본은 IR 하나이고, Python 실행과 탑재 C 생성은 그 **백엔드**다.

    IR (정본) ──┬── ir_exec  Python 백엔드 — 설계·시뮬
                └── emit_c   C 백엔드   — FCC 탑재 코드

여기 있는 것은 **범용 기계**뿐이다 — 제어법칙 그래프 선언은 `claw.fcl.graphs`에
있다(그게 제어법칙이므로). 그래서 codegen은 blocks(L1)만 의존하고 fcl(L3)이
codegen을 의존한다 — 계층 규칙(03 §1)대로 위에서 아래로.
"""

from claw.codegen.emit_c import emit_c
from claw.codegen.ir import Graph, Node, Op
from claw.codegen.ir_exec import GraphRunner

__all__ = ["Graph", "GraphRunner", "Node", "Op", "emit_c"]
