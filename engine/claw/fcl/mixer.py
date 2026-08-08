"""제어면 혼합 (01 §2.2) — 엘레본4 고정 믹싱 + 러더 + 차동추력 보상 (01 §3.2).

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

    def step(self, de, da, dr, thr) -> SurfaceCommand:
        """(피치·롤·요 축 명령, 집합 스로틀) → SurfaceCommand. 무상태(순수) 블록."""
        left = min(max(de + da, self.elevon_lo), self.elevon_hi)
        right = min(max(de - da, self.elevon_lo), self.elevon_hi)
        rudder = min(max(dr, self.rudder_lo), self.rudder_hi)
        # 차동추력은 클램프된 실 러더 기준 — 러더가 내지 못하는 명령에 추력이
        # 반응하지 않도록 (포화 시 추력 인계는 별도 설계 항목)
        d = self.k_diff_thr * rudder
        return SurfaceCommand(
            elevon=np.array([left, left, right, right]),
            rudder=rudder,
            throttle=np.array(
                [min(max(thr - d, 0.0), 1.0), min(max(thr + d, 0.0), 1.0)]
            ),
        )
