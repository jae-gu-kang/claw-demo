"""α 리미터 (01 §3.6 [확정]) — 실속 진입 자체를 방지하는 엔벨로프 보호.

θ_cmd ≤ θ + (α_max − α),  α_max = α_stall(mach) − margin
- α_stall: 실속 경계 테이블 (공력팀 정본, 01 §2.3 — 데모는 plant.demo)
- 위치: 피치 명령 경로(오토파일럿 θ 출력) 하드 클램프 [기본값]
- margin 기본 0.05 rad ≈ 2.9° [기본값] — 실데이터 확보 시 재검토 [TBD]
- 근거: θ = γ + α 근사에서 θ 증분 명령이 곧 α 증분 → 자세 명령을 현재
  α 여유만큼으로 제한하면 α가 α_max를 넘지 않는다 (γ 변화는 α 여유를
  회복시키는 방향). 폐루프 검증: 리미터 없음 α>0.34 → 장착 α≤0.31
- 적분기 처리: SCAS는 제한된 명령으로 적분(오차 축소 방향 — 와인드업 없음),
  AP 고도 적분기는 자체 클램프로 유계
- 반환 margin(α_max − α)은 엔벨로프 감시(02 §6.1 실속 마진 시계열)의 근거
"""

from claw.common.attitude import quat_to_euler
from claw.fcl.airdata import airdata_from_nav
from claw.fcl.graphs import alpha_limiter_graph, stateless_runner
from claw.tables import Table


class AlphaLimiter:
    def __init__(self, stall_table: Table, margin: float = 0.05):
        # 1차 구현은 1D α_stall(mach)만 — 다축 정본(예: mach·alt)이 오면 조용히
        # 잘못된 축값(0)으로 조회하는 대신 여기서 시끄럽게 거부한다
        if stall_table.axis_names != ("mach",):
            raise ValueError(
                f"실속 경계 테이블은 1D (mach,)만 지원: {stall_table.axis_names}"
            )
        if stall_table.extrapolate != "clip":
            raise ValueError(
                f"실속 경계는 extrapolate='clip' 필요(비행 중 예외 방지): "
                f"{stall_table.extrapolate!r}"
            )
        if margin < 0:
            raise ValueError(f"margin은 음수 불가: {margin}")
        self.stall_table = stall_table
        self.margin = margin
        self.cfg = {"stall_table": stall_table, "margin": margin}
        self._runner = stateless_runner(alpha_limiter_graph(**self.cfg))

    def alpha_max(self, mach) -> float:
        """제한 받음각 = α_stall(mach) − 보호마진. (설계 검토용 조회 — 법칙 경로는 그래프)"""
        return float(self.stall_table.interp(mach=mach)) - self.margin

    def step(self, theta_cmd, nav, mach):
        """→ (제한된 θ_cmd, 리미터 작동 여부, 실속 마진 α_max−α).

        보호 로직은 `fcl/graphs.py alpha_limiter_nodes`가 정본 — 여기서는 항법
        상태에서 공학량(α·θ)을 뽑아 넘기고 결과를 계약 형태로 되돌린다.
        """
        _V, alpha, _beta = airdata_from_nav(nav)
        _phi, theta, _psi = quat_to_euler(nav.q_nb)
        o = self._runner.step(
            theta_cmd=theta_cmd, theta=float(theta), alpha=float(alpha), mach=mach
        )
        return o["theta_cmd"], bool(o["active"]), o["alpha_margin"]
