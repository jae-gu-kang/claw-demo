"""델타윙 데모 비행체 프로파일 — 합성 선형 계수 (검증·예제·튜토리얼용).

CFD DB 반입 전의 대역(placeholder) 프로파일이며 "비행체 프로파일" 교체 단위(03 §7.2)의
첫 사례. 정적 안정(Cmα<0)·피치 댐핑(Cmq<0)·더치롤류 횡방향 계수를 갖는 아음속 소형
델타윙 상정. 수치는 검증 손계산이 쉬운 라운드 값 — 실기체 값 아님.
"""

import numpy as np

from claw.plant.aero import AeroModel, wind_to_body_coeffs
from claw.plant.aircraft import Aircraft
from claw.plant.mass import FuelMass
from claw.plant.prop import TwinEngine


def make_demo_aircraft() -> Aircraft:
    def coef(inp):
        a, b_ = inp["alpha"], inp["beta"]
        de = inp.get("de", 0.0)
        da = inp.get("da", 0.0)
        dr = inp.get("dr", 0.0)
        cl = 3.5 * a + 0.4 * de
        cd = 0.02 + 0.25 * cl * cl  # 델타윙 유도항력 큼 (01 §3.3.1)
        cx, cy_d, cz = wind_to_body_coeffs(cl, cd, a, b_)
        return {
            "CX": cx,
            "CY": cy_d - 0.8 * b_ + 0.10 * dr,
            "CZ": cz,
            "Cl": -0.05 * b_ - 0.30 * inp["phat"] + 0.15 * da,
            "Cm": 0.02 - 0.8 * a - 1.0 * de - 6.0 * inp["qhat"],
            "Cn": 0.12 * b_ - 0.15 * inp["rhat"] - 0.08 * dr,
        }

    aero = AeroModel(S=3.0, cbar=1.5, b=2.5, coef_fn=coef)
    fuel_mass = FuelMass(
        m_empty=800.0,
        fuel_max=400.0,
        J_empty=np.diag([300.0, 900.0, 1100.0]),
        J_full=np.diag([350.0, 1100.0, 1350.0]),
        # CG 이동은 모멘트 기준점 이전 [TBD] 구현 전까지 동역학에 무효 — 오해 방지 위해 0
        cg_empty=np.zeros(3),
        cg_full=np.zeros(3),
    )
    engine = TwinEngine(max_thrust=4000.0, y_offset=0.5)
    return Aircraft(fuel_mass, aero, engine)
