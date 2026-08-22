"""M16 codegen — 제어법칙 구조의 IR과 그 백엔드들 (02 §2.2, 03 M16).

구조의 정본은 IR 하나이고, Python 실행과 탑재 C 생성은 그 **백엔드**다.

    IR (정본) ──┬── ir_exec  Python 백엔드 — 설계·시뮬·대조 기준
                └── emit_c   C 백엔드   — FCC 탑재 코드

구현됨: Graph/Node/Op(C 생성 가능 제약 검증) / GraphRunner / SCAS 축 그래프 /
C 생성(PID·Washout·Saturation·Gain·Product·Sum 에미터).
"""

from claw.codegen.emit_c import emit_c
from claw.codegen.graphs import scas_axis_graph
from claw.codegen.ir import Graph, Node, Op
from claw.codegen.ir_exec import GraphRunner

__all__ = ["Graph", "GraphRunner", "Node", "Op", "emit_c", "scas_axis_graph"]
