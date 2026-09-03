"""M11 sim — 멀티레이트 시뮬 프레임, 조립(composition root), 엔벨로프 감시 (02 §6).

plant + nav + guidance + fcl을 03 §4 계약으로만 연결한다. 몬테카를로 배치는
분산 대상 [TBD 02 §6] 확정 후 (백로그).
"""

from claw.sim.simulator import Simulator, check_law_plant_pairing

__all__ = ["Simulator", "check_law_plant_pairing"]
