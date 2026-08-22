"""제어법칙 구조의 IR 선언 — 손으로 쓴 `fcl/`과 1:1로 대응하는 그래프들.

증분 A는 SCAS 한 축(`fcl/scas.py:26 ScasAxis`)만 표현한다. 기존 코드를 **대체하지
않고 옆에 세워** 같은 답을 내는지 대조한다 — IR이 제어법칙 전부를 표현할 수 있다고
확인된 뒤에야 정본을 옮긴다(플랜 증분 C).

여기 있는 것은 구조뿐이고 계산은 없다. 블록 로직은 M2 `claw.blocks`가, 실행은
`ir_exec`가, C 생성은 `emit_c`가 맡는다.
"""

from claw.blocks.basic import Gain, Product, Saturation, Sum
from claw.blocks.controllers import PID
from claw.blocks.filters import Washout
from claw.codegen.ir import Graph, Node

_SCHEDULABLE = ("kp", "ki", "k_rate")


def scas_axis_graph(
    name,
    *,
    kp,
    ki,
    k_rate,
    out_lo,
    out_hi,
    washout_tau=0.0,
    scheduled=(),
):
    """SCAS 한 축 (`fcl/scas.py:26`)의 IR.

        u = clip( PID(자세오차) + k_rate·rate' , out_lo, out_hi )
        rate' = washout(rate)   (washout_tau > 0일 때 — 요축 댐퍼, 01 §3.1)

    `scheduled`에 든 게인은 **신호**(스텝마다 주입되는 포트)가 되고, 나머지는
    상수 파라미터가 된다 — 게인 스케줄 유무가 구조에 그대로 드러난다.
    스케줄된 k_rate는 Product(신호×rate'), 상수 k_rate는 Gain 블록이 된다.
    """
    bad = set(scheduled) - set(_SCHEDULABLE)
    if bad:
        raise ValueError(f"{name}: 스케줄 불가 게인 {sorted(bad)} — 허용 {list(_SCHEDULABLE)}")
    if washout_tau < 0:
        raise ValueError(f"{name}: washout_tau는 음수 불가: {washout_tau}")

    sched = tuple(g for g in _SCHEDULABLE if g in scheduled)  # 선언 순서 고정
    inputs = ("att_err", "rate") + sched
    nodes = []

    rate_src = "rate"
    if washout_tau > 0:
        nodes.append(Node("wo", Washout, inputs=("rate",), params={"tau": washout_tau}))
        rate_src = "wo"

    # 적분기 클램프가 곧 축 출력 한계 — 안티와인드업은 PID 내부 클램프(scas.py:11)
    nodes.append(
        Node(
            "pid",
            PID,
            inputs=("att_err",),
            params={"kp": kp, "ki": ki, "kd": 0.0, "out_lo": out_lo, "out_hi": out_hi},
            gains={g: g for g in sched if g in ("kp", "ki")},
        )
    )

    if "k_rate" in sched:
        nodes.append(Node("damp", Product, inputs=("k_rate", rate_src)))
    else:
        nodes.append(Node("damp", Gain, inputs=(rate_src,), params={"k": k_rate}))

    # rate 항은 PID 클램프 밖에서 더해지므로 축 출력을 한 번 더 제한한다 (scas.py:11)
    nodes.append(Node("sum", Sum, inputs=("pid", "damp"), params={"signs": (1.0, 1.0)}))
    nodes.append(Node("sat", Saturation, inputs=("sum",), params={"lo": out_lo, "hi": out_hi}))

    return Graph(name, inputs=inputs, nodes=nodes, output="sat")
