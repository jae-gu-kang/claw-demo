"""V-n 보호 경계 수치 (01 §3.6 관련) — 실속 하중배수 경계 n(V).

V-n 선도의 공력쪽 절반: n = L(α경계)/W, α경계 = α_stall(M) − alpha_margin.
alpha_margin=0이면 실속 경계, α 리미터 마진(0.05 [기본값])을 주면 보호 경계.
가정: δe=0·β=0·각속도 0(준정적)·ISA. 양력은 동체축 공력힘의 풍축 투영
L = −F_z·cosα + F_x·sinα — 계수 부호 가정 없이 프로파일 DB를 그대로 소비.

구조 한계(±n)·급강하 한계속도 V_D는 [TBD] — 구조하중 데이터 확보 시
이 모듈이 함께 반환하도록 확장 (Nz 제한 기능 여부도 01 §3.6 [TBD]).
"""

import math

import numpy as np

from claw.common.constants import G0
from claw.env import isa_atmosphere


def vn_stall_boundary(aircraft, stall_table, alt, fuel, machs, alpha_margin=0.0):
    """마하 격자 → {"mach", "V", "n"} — 고도·연료(중량) 고정 V-n 경계 곡선."""
    atm = isa_atmosphere(alt)
    m, _cg, _J = aircraft.fuel_mass.at(fuel)
    weight = m * G0
    out = {"mach": [], "V": [], "n": []}
    controls = {"de": 0.0, "da": 0.0, "dr": 0.0}
    for mach in machs:
        mach = float(mach)
        v = mach * atm.a
        a_b = float(stall_table.interp(mach=mach)) - alpha_margin
        vel_b = np.array([v * math.cos(a_b), 0.0, v * math.sin(a_b)])
        F, _M = aircraft.aero.forces(atm.rho, vel_b, np.zeros(3), controls, mach=mach)
        lift = -float(F[2]) * math.cos(a_b) + float(F[0]) * math.sin(a_b)
        out["mach"].append(mach)
        out["V"].append(v)
        out["n"].append(lift / weight)
    return out
