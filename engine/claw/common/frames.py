"""좌표 변환·바람각 (conventions.md §1·§4). WGS-84 측지 변환은 env 모듈(M4) 소관."""

import numpy as np

from claw.common.attitude import quat_to_dcm


def ned_to_body(q_nb, v_n):
    return quat_to_dcm(q_nb) @ np.asarray(v_n, dtype=float)


def body_to_ned(q_nb, v_b):
    return quat_to_dcm(q_nb).T @ np.asarray(v_b, dtype=float)


def wind_angles(vel_air_b):
    """공기속도 동체 성분 (u, v, w) → (V, α, β). α = atan2(w, u), β = asin(v/V)."""
    u, v, w = np.asarray(vel_air_b, dtype=float)
    V = float(np.sqrt(u * u + v * v + w * w))
    if V == 0.0:
        return 0.0, 0.0, 0.0
    alpha = float(np.arctan2(w, u))
    beta = float(np.arcsin(np.clip(v / V, -1.0, 1.0)))
    return V, alpha, beta
