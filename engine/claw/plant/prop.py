"""쌍발 추진 — 스로틀-추력 맵 + 차동추력 모멘트 (01 §2.1·§2.4).

thrust_map(throttle) -> 추력[N] 콜러블 주입 가능 (추력 맵 데이터 [TBD] 대비),
기본은 max_thrust·throttle 선형. 엔진 위치는 CG 기준 동체축
r_L = (x_offset, -y_offset, z_offset), r_R = (x_offset, +y_offset, z_offset).
좌측 추력 우세 시 +N(기수 우측) — 요축 보조 차동추력의 부호 기준.
"""

import numpy as np


class TwinEngine:
    def __init__(self, max_thrust, y_offset, x_offset=0.0, z_offset=0.0, thrust_map=None):
        if y_offset < 0:
            raise ValueError(f"y_offset은 음수 불가: {y_offset}")
        self.thrust_map = thrust_map if thrust_map is not None else (lambda th: max_thrust * th)
        self.r_left = np.array([x_offset, -y_offset, z_offset])
        self.r_right = np.array([x_offset, y_offset, z_offset])

    def forces(self, throttle):
        """throttle (2,) [좌, 우] 0~1 (SurfaceCommand 규약, 범위 밖 클립) → (F_b, M_b)."""
        t_left = float(self.thrust_map(min(max(float(throttle[0]), 0.0), 1.0)))
        t_right = float(self.thrust_map(min(max(float(throttle[1]), 0.0), 1.0)))
        f_left = np.array([t_left, 0.0, 0.0])
        f_right = np.array([t_right, 0.0, 0.0])
        force_b = f_left + f_right
        moment_b = np.cross(self.r_left, f_left) + np.cross(self.r_right, f_right)
        return force_b, moment_b
