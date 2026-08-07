"""공력 모델 (03 M5.aero) — 공력 DB 계수 함수 소비, 무차원화·차원화 담당.

규약 원칙(conventions.md): 계수·모멘트 부호는 공력 DB가 정의하며 코드는 가정하지
않는다 → coef_fn은 **동체축 계수** {CX, CY, CZ, Cl, Cm, Cn}를 직접 반환한다.
양력/항력(풍축) 형태 DB를 위한 wind_to_body_coeffs 헬퍼 제공 [기본값 변환식].

coef_fn 입력(dict): alpha, beta [rad], V [m/s], mach, phat/qhat/rhat(무차원 각속도
p·b/2V, q·c̄/2V, r·b/2V) + controls로 전달한 타면각. 실제 CFD DB 축 규격은 [TBD]
(02 §5.1) — 확정 시 M3 Table 조회를 이 인터페이스로 감싼다.

    F_b = q̄·S·[CX, CY, CZ],  M_b = q̄·S·[b·Cl, c̄·Cm, b·Cn],  q̄ = ½ρV²

[TBD — 책임 소재 기록] 모멘트 기준점 이전: conventions.md [확정] "DB 기준점의 모멘트를
현재 CG 기준으로 이전"은 아직 미구현 — DB 규격 확정 시 플랜트 조립자(Phase 3~4)가
FuelMass.at의 cg와 DB 메타 기준점으로 M += r×F 이전을 수행해야 한다.
TwinEngine 엔진 위치도 같은 지점에서 CG 이동을 반영할 것.
"""

import math

import numpy as np

from claw.common.frames import wind_angles


def wind_to_body_coeffs(CL, CD, alpha, beta):
    """풍축 양력·항력 계수 → 동체축 (CX, CY, CZ) [기본값 변환]:
    CX = CL·sinα − CD·cosα·cosβ, CY = −CD·sinβ, CZ = −CL·cosα − CD·sinα·cosβ.
    """
    sa, ca = math.sin(alpha), math.cos(alpha)
    sb, cb = math.sin(beta), math.cos(beta)
    return CL * sa - CD * ca * cb, -CD * sb, -CL * ca - CD * sa * cb


class AeroModel:
    def __init__(self, S, cbar, b, coef_fn):
        if S <= 0 or cbar <= 0 or b <= 0:
            raise ValueError(f"기준값은 양수여야 함: S={S}, cbar={cbar}, b={b}")
        self.S, self.cbar, self.b = float(S), float(cbar), float(b)
        self.coef_fn = coef_fn

    def forces(self, rho, vel_air_b, omega_b, controls=None, mach=None):
        """(밀도, 공기속도[동체축], 각속도, 타면각 dict, 마하) → (F_b, M_b). V=0이면 0."""
        V, alpha, beta = wind_angles(vel_air_b)
        if V <= 0.0:
            return np.zeros(3), np.zeros(3)
        p, q, r = np.asarray(omega_b, dtype=float)
        inv2v = 1.0 / (2.0 * V)
        inputs = {
            "alpha": alpha,
            "beta": beta,
            "V": V,
            "mach": mach if mach is not None else 0.0,
            "phat": p * self.b * inv2v,
            "qhat": q * self.cbar * inv2v,
            "rhat": r * self.b * inv2v,
        }
        if controls:
            inputs.update(controls)
        c = self.coef_fn(inputs)
        qbar_s = 0.5 * rho * V * V * self.S
        force_b = qbar_s * np.array([c["CX"], c["CY"], c["CZ"]])
        moment_b = qbar_s * np.array([self.b * c["Cl"], self.cbar * c["Cm"], self.b * c["Cn"]])
        return force_b, moment_b
