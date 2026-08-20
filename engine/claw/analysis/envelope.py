"""V-n 보호 경계 수치 (01 §3.6 관련) — 실속 하중배수 경계 n(V).

V-n 선도의 공력쪽 절반: n = L(α경계)/W, α경계 = α_stall(M) − alpha_margin.
alpha_margin=0이면 실속 경계, α 리미터 마진(0.05 [기본값])을 주면 보호 경계.
가정: δe=0·β=0·각속도 0(준정적)·ISA. 양력은 동체축 공력힘의 풍축 투영
L = −F_z·cosα + F_x·sinα — 계수 부호 가정 없이 프로파일 DB를 그대로 소비.

구조 한계(±n·안전계수·M_NO·M_D)는 비행체 프로파일 데이터로 주입받아
(데모: plant.make_demo_structural_limits [기본값] 자리표시 — 실기체 값 아님)
vn_envelope가 한계선·특성 속도(V_S·V_A)까지 산출한다. Nz 제한 "기능" 채택
여부는 01 §3.6 [TBD] 유지.
"""

import math

import numpy as np

from claw.common.constants import G0
from claw.env import isa_atmosphere


def vn_envelope(
    aircraft, stall_table, limits, alt, fuel,
    n_points=81, alpha_margin=0.0, mach_min=0.02, neg_alpha_ratio=0.6,
):
    """V-n 선도 일습 — 실속·보호 곡선 + 구조 한계선 + 특성 속도.

    limits: 프로파일 구조 한계 dict (n_limit_pos/neg, safety_factor,
    mach_no, mach_d). 특성 속도는 실속 곡선 보간 역산: V_S(n=1)·V_A(n=제한하중)
    — 마하 격자 범위 밖이면 None.

    mach_min [기본값 0.02]: 격자 시작 마하 — 실속 테이블 최저점보다 낮으면
    clip 외삽(α_stall 경계값 고정)으로 포물선 뿌리(n→0)까지 산출 (교과서형 표현).

    음의 실속 곡선은 공력 데이터 부재 — **자리표시 [기본값]**: 경계 받음각을
    −neg_alpha_ratio×α_stall(M)로 가정해 n_stall_neg 산출 (델타윙 음의 α
    실속각이 양보다 작은 일반 경향 반영, 실데이터 아님 — 공력 정본 확보 시
    교체). ratio는 출력에 echo — 소비자(웹)가 자리표시임을 명기 표시.
    """
    atm = isa_atmosphere(alt)
    if not 0.0 < neg_alpha_ratio <= 1.0:
        raise ValueError(f"neg_alpha_ratio는 (0, 1] 범위: {neg_alpha_ratio}")
    m0 = min(float(stall_table.axes[0][0]), float(mach_min))
    m1 = max(float(stall_table.axes[0][-1]), float(limits["mach_d"]))
    machs = np.linspace(m0, m1, int(n_points))
    stall = vn_stall_boundary(aircraft, stall_table, alt, fuel, machs)
    prot = vn_stall_boundary(
        aircraft, stall_table, alt, fuel, machs, alpha_margin=alpha_margin
    )
    neg = vn_stall_boundary(
        aircraft, stall_table, alt, fuel, machs, alpha_scale=-neg_alpha_ratio
    )
    v_arr = np.array(stall["V"])
    n_arr = np.array(stall["n"])  # 동압 V² 지배 — 단조 증가 (보간 역산 전제)
    n_lim = float(limits["n_limit_pos"])
    sf = float(limits["safety_factor"])

    def crossing(n_target):
        if n_arr[0] <= n_target <= n_arr[-1]:
            return float(np.interp(n_target, n_arr, v_arr))
        return None

    out_limits = {
        "n_limit_pos": n_lim,
        "n_limit_neg": float(limits["n_limit_neg"]),
        "safety_factor": sf,
        "n_ultimate_pos": n_lim * sf,
        "n_ultimate_neg": float(limits["n_limit_neg"]) * sf,
        "mach_no": float(limits["mach_no"]),
        "mach_d": float(limits["mach_d"]),
        "v_no": float(limits["mach_no"]) * atm.a,
        "v_d": float(limits["mach_d"]) * atm.a,
    }
    return {
        "mach": stall["mach"],
        "V": stall["V"],
        "n_stall": stall["n"],
        "n_prot": prot["n"],
        "n_stall_neg": neg["n"],
        "neg_alpha_ratio": float(neg_alpha_ratio),
        "limits": out_limits,
        "speeds": {"v_s": crossing(1.0), "v_a": crossing(n_lim)},
    }


def vn_stall_boundary(aircraft, stall_table, alt, fuel, machs, alpha_margin=0.0, alpha_scale=1.0):
    """마하 격자 → {"mach", "V", "n"} — 고도·연료(중량) 고정 V-n 경계 곡선.

    경계 받음각 = alpha_scale × α_stall(M) − alpha_margin. alpha_scale 음수면
    음의 실속 자리표시 경계 (vn_envelope의 neg_alpha_ratio 경로 전용).
    """
    atm = isa_atmosphere(alt)
    m, _cg, _J = aircraft.fuel_mass.at(fuel)
    weight = m * G0
    out = {"mach": [], "V": [], "n": []}
    controls = {"de": 0.0, "da": 0.0, "dr": 0.0}
    for mach in machs:
        mach = float(mach)
        v = mach * atm.a
        a_b = alpha_scale * float(stall_table.interp(mach=mach)) - alpha_margin
        vel_b = np.array([v * math.cos(a_b), 0.0, v * math.sin(a_b)])
        F, _M = aircraft.aero.forces(atm.rho, vel_b, np.zeros(3), controls, mach=mach)
        lift = -float(F[2]) * math.cos(a_b) + float(F[0]) * math.sin(a_b)
        out["mach"].append(mach)
        out["V"].append(v)
        out["n"].append(lift / weight)
    return out
