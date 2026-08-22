"""엘레본 믹싱 · 제어 할당 (01 §2.2) — 엘레본4 고정 믹싱 + 러더 + 차동추력 보상 (01 §3.2).

[기본값] 내/외측 쌍 1:1 고정 믹싱 (믹싱 비율·4면 배치는 기체 데이터 확인 시 [TBD]):
    좌측(내좌·외좌) = de + da,  우측(내우·외우) = de − da
    → 재구성 항등: 평균 = de, (좌−우)/2 = da
차동추력: thr_l = thr − k_diff_thr·dr, thr_r = thr + k_diff_thr·dr —
계수 크기·부호는 설계값 소관 (데모 프로파일: Cn_dr<0, N = y·(T_L−T_R)
기준으로 k>0가 러더 보조 방향). 기본 0 = 미사용.
면별 위치 클램프만 담당 — rate 한계는 작동기 모델(M5) 소관.
SurfaceCommand 계약: elevon [내좌, 외좌, 내우, 외우], TE down +.
"""

import numpy as np

from claw.blocks.base import Block
from claw.common.contracts import SurfaceCommand
from claw.fcl.graphs import mixer_graph, stateless_runner
from claw.params.param import ParamDef


class Mixer(Block):
    NAME = "Mixer"
    PARAM_DEFS = (
        ParamDef("elevon_lo", -0.35, "rad", "엘레본 하한"),
        ParamDef("elevon_hi", 0.35, "rad", "엘레본 상한"),
        ParamDef("rudder_lo", -0.35, "rad", "러더 하한"),
        ParamDef("rudder_hi", 0.35, "rad", "러더 상한"),
        ParamDef("k_diff_thr", 0.0, "1/rad", "차동추력 보상 계수 (0=미사용)"),
    )

    def __init__(
        self,
        elevon_lo: float = -0.35,
        elevon_hi: float = 0.35,
        rudder_lo: float = -0.35,
        rudder_hi: float = 0.35,
        k_diff_thr: float = 0.0,
    ):
        if elevon_lo > elevon_hi or rudder_lo > rudder_hi:
            raise ValueError("타면 한계 하한 > 상한")
        self.elevon_lo, self.elevon_hi = elevon_lo, elevon_hi
        self.rudder_lo, self.rudder_hi = rudder_lo, rudder_hi
        self.k_diff_thr = k_diff_thr
        self.cfg = {
            "elevon_lo": elevon_lo, "elevon_hi": elevon_hi,
            "rudder_lo": rudder_lo, "rudder_hi": rudder_hi,
            "k_diff_thr": k_diff_thr,
        }
        self._runner = stateless_runner(mixer_graph(**self.cfg))

    def step(self, de, da, dr, thr) -> SurfaceCommand:
        """(피치·롤·요 축 명령, 집합 스로틀) → SurfaceCommand. 무상태(순수) 블록.

        믹싱 구조는 `fcl/graphs.py mixer_nodes`가 정본 — 여기서는 실행하고
        SurfaceCommand 계약으로 포장만 한다. 내/외측 1:1 고정 믹싱이라 좌·우
        두 값이 4면을 재구성한다.
        """
        o = self._runner.step(de=de, da=da, dr=dr, thr=thr)
        left, right = o["elevon_l"], o["elevon_r"]
        return SurfaceCommand(
            elevon=np.array([left, left, right, right]),
            rudder=o["rudder"],
            throttle=np.array([o["throttle_l"], o["throttle_r"]]),
        )
