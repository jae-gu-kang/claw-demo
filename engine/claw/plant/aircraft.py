"""플랜트 조립(Aircraft Dynamics) — aero + prop + 중력 + 질량(연료 준정적) + ISA 대기.

두 가지 상태 표현을 제공한다:
- fm(): 동체축 총 힘·모멘트 — 쿼터니언 경로(RigidBody, M11 sim)용
- deriv_euler(): 오일러각 12-상태 미분 — 트림·수치섭동 선형화(M9)용
  상태: [u, v, w, p, q, r, φ, θ, ψ, pn, pe, h] (XE_* 인덱스, h = −z_n)

바람은 0 가정(vel_air = vel_b) — 바람/난류는 확장 항목 (01 §2.5).
모멘트 기준점 CG 이전은 DB 규격 확정 시 이 조립 지점에서 수행 [TBD] (aero.py 참조).
"""

import numpy as np

from claw.common.attitude import euler_to_dcm, euler_to_quat
from claw.common.constants import G0
from claw.common.frames import ned_to_body
from claw.env import isa_atmosphere

XE_NAMES = ("u", "v", "w", "p", "q", "r", "phi", "theta", "psi", "pn", "pe", "h")
(XE_U, XE_V, XE_W, XE_P, XE_Q, XE_R, XE_PHI, XE_THETA, XE_PSI, XE_PN, XE_PE, XE_H) = range(12)


class Aircraft:
    def __init__(self, fuel_mass, aero, engine):
        self.fuel_mass = fuel_mass
        self.aero = aero
        self.engine = engine

    def fm(self, vel_b, omega_b, q_nb, h, controls, fuel):
        """동체축 총 힘·모멘트 → (F_b, M_b, m, J). 중력 포함."""
        m, _cg, J = self.fuel_mass.at(fuel)  # cg는 기준점 이전 [TBD]에서 소비 예정
        atm = isa_atmosphere(h)
        V = float(np.linalg.norm(vel_b))
        mach = V / atm.a
        f_aero, m_aero = self.aero.forces(atm.rho, vel_b, omega_b, controls, mach)
        f_eng, m_eng = self.engine.forces(controls.get("throttle", (0.0, 0.0)))
        f_grav = ned_to_body(q_nb, np.array([0.0, 0.0, m * G0]))
        return f_aero + f_eng + f_grav, m_aero + m_eng, m, J

    def deriv_euler(self, xe, controls, fuel):
        """오일러 12-상태 미분 (트림·선형화용). θ = ±π/2 특이점 근방 사용 금지."""
        u, v, w, p, q, r, phi, theta, psi = xe[:9]
        h = xe[XE_H]
        vel_b = np.array([u, v, w])
        omega = np.array([p, q, r])
        q_nb = euler_to_quat(phi, theta, psi)
        force_b, moment_b, m, J = self.fm(vel_b, omega, q_nb, h, controls, fuel)

        uvw_dot = force_b / m - np.cross(omega, vel_b)
        pqr_dot = np.linalg.solve(J, moment_b - np.cross(omega, J @ omega))
        sphi, cphi = np.sin(phi), np.cos(phi)
        cth, tth = np.cos(theta), np.tan(theta)
        eul_dot = np.array(
            [
                p + tth * (q * sphi + r * cphi),
                q * cphi - r * sphi,
                (q * sphi + r * cphi) / cth,
            ]
        )
        v_n = euler_to_dcm(phi, theta, psi).T @ vel_b
        return np.concatenate([uvw_dot, pqr_dot, eul_dot, [v_n[0], v_n[1], -v_n[2]]])
