"""연료 의존 질량특성 — 잔여 연료 선형 보간 [기본값] (구현 문서 §5.5).

연료 소모에 따른 질량·CG·관성 변화는 준정적 상태 의존 파라미터로 취급 —
시뮬 루프가 스텝 사이에 at(fuel)로 조회해 RigidBody.m/J를 갱신한다.
"""

import numpy as np


class FuelMass:
    def __init__(
        self,
        m_empty,
        fuel_max,
        J_empty,
        J_full,
        cg_empty=(0.0, 0.0, 0.0),
        cg_full=(0.0, 0.0, 0.0),
    ):
        if m_empty <= 0:
            raise ValueError(f"공허중량은 양수여야 함: {m_empty}")
        if fuel_max < 0:
            raise ValueError(f"최대 연료량은 음수 불가: {fuel_max}")
        self.m_empty = float(m_empty)
        self.fuel_max = float(fuel_max)
        self.J_empty = np.asarray(J_empty, dtype=float)
        self.J_full = np.asarray(J_full, dtype=float)
        self.cg_empty = np.asarray(cg_empty, dtype=float)
        self.cg_full = np.asarray(cg_full, dtype=float)

    def at(self, fuel):
        """잔여 연료 [kg] → (질량, CG 위치[동체축·기준점 대비], 관성행렬). 범위 밖 클립."""
        f = min(max(float(fuel), 0.0), self.fuel_max)
        r = f / self.fuel_max if self.fuel_max > 0 else 0.0
        m = self.m_empty + f
        cg = self.cg_empty + r * (self.cg_full - self.cg_empty)
        J = self.J_empty + r * (self.J_full - self.J_empty)
        return m, cg, J
