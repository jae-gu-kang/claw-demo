"""플랜트 조립(Aircraft Dynamics) — aero + prop + 중력 + 지면 + 질량(연료 준정적) + ISA 대기.

두 가지 상태 표현을 제공한다:
- fm(): 동체축 총 힘·모멘트 — 쿼터니언 경로(RigidBody, M11 sim)용
- deriv_euler(): 오일러각 12-상태 미분 — 트림·수치섭동 선형화(M9)용
  상태: [u, v, w, p, q, r, φ, θ, ψ, pn, pe, h] (XE_* 인덱스, h = −z_n)

바람은 0 가정(vel_air = vel_b) — 바람/난류는 확장 항목 (01 §2.5).
지면 접촉(ground)은 선택 항목이다 — None이면 힘 합성이 공력+추진+중력 세 항으로
지면 도입 전과 완전히 동일하다. 장착 시에는 접촉점 위치가 필요해 pos_n을 함께 받는다.
모멘트 기준점 CG 이전은 DB 규격 확정 시 이 조립 지점에서 수행 [TBD] (aero.py 참조) —
착륙장치의 r×F만 plant/ground.py에서 이미 구현돼 있고 공력 DB 쪽은 미구현이다.
"""

import numpy as np

from claw.common.attitude import euler_to_dcm, euler_to_quat
from claw.common.constants import G0
from claw.common.frames import ned_to_body
from claw.env import isa_atmosphere

XE_NAMES = ("u", "v", "w", "p", "q", "r", "phi", "theta", "psi", "pn", "pe", "h")
(XE_U, XE_V, XE_W, XE_P, XE_Q, XE_R, XE_PHI, XE_THETA, XE_PSI, XE_PN, XE_PE, XE_H) = range(12)


class Aircraft:
    def __init__(self, fuel_mass, aero, engine, ground=None):
        self.fuel_mass = fuel_mass
        self.aero = aero
        self.engine = engine
        self.ground = ground  # plant.ground.SkidGear | None — None이면 지면 없음

    def fm(self, vel_b, omega_b, q_nb, h, controls, fuel, pos_n=None, ground_elev=0.0):
        """동체축 총 힘·모멘트 → (F_b, M_b, m, J). 중력 포함, 지면은 장착 시에만.

        pos_n은 지면 접촉점의 고도를 재는 데만 쓴다 — ground가 없으면 불필요하다.
        ground가 있는데 pos_n이 없으면 **조용히 지면 없이 계산하지 않고 거부**한다
        (조용한 미장착 금지 — 지면이 빠진 결과는 기체가 활주로를 통과하는 결과다).
        """
        m, _cg, J = self.fuel_mass.at(fuel)  # cg는 기준점 이전 [TBD]에서 소비 예정
        atm = isa_atmosphere(h)
        V = float(np.linalg.norm(vel_b))
        mach = V / atm.a
        f_aero, m_aero = self.aero.forces(atm.rho, vel_b, omega_b, controls, mach)
        f_eng, m_eng = self.engine.forces(controls.get("throttle", (0.0, 0.0)))
        f_grav = ned_to_body(q_nb, np.array([0.0, 0.0, m * G0]))
        force_b = f_aero + f_eng + f_grav
        moment_b = m_aero + m_eng
        if self.ground is not None:
            if pos_n is None:
                raise ValueError("지면 장착 상태에서는 pos_n이 필요함 (접촉점 고도 판정)")
            f_gnd, m_gnd = self.ground.forces(pos_n, vel_b, q_nb, omega_b, ground_elev)
            force_b = force_b + f_gnd
            moment_b = moment_b + m_gnd
        return force_b, moment_b, m, J

    def deriv_euler(self, xe, controls, fuel, ground_elev=0.0):
        """오일러 12-상태 미분 (트림·선형화용). θ = ±π/2 특이점 근방 사용 금지."""
        u, v, w, p, q, r, phi, theta, psi = xe[:9]
        h = xe[XE_H]
        vel_b = np.array([u, v, w])
        omega = np.array([p, q, r])
        q_nb = euler_to_quat(phi, theta, psi)
        pos_n = np.array([xe[XE_PN], xe[XE_PE], -h])
        force_b, moment_b, m, J = self.fm(
            vel_b, omega, q_nb, h, controls, fuel, pos_n=pos_n, ground_elev=ground_elev
        )

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
