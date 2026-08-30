"""엔벨로프 수치 (01 §2.6·§3.6) — V-n 경계 n(V) + 제어법칙 설계 엔벨로프 합성.

V-n 선도의 공력쪽 절반: n = L(α경계)/W, α경계 = α_stall(M) − alpha_margin.
alpha_margin=0이면 실속 경계, α 리미터 마진(0.05 [기본값])을 주면 보호 경계.
가정: δe=0·β=0·각속도 0(준정적)·ISA. 양력은 동체축 공력힘의 풍축 투영
L = −F_z·cosα + F_x·sinα — 계수 부호 가정 없이 프로파일 DB를 그대로 소비.

구조 한계(±n·안전계수·M_NO·M_D)는 비행체 프로파일 데이터로 주입받아
(데모: plant.make_demo_structural_limits [기본값] 자리표시 — 실기체 값 아님)
vn_envelope가 한계선·특성 속도(V_S·V_A)까지 산출한다. Nz 제한 "기능" 채택
여부는 01 §3.6 [TBD] 유지.

설계 엔벨로프(01 §2.6): design_envelope가 M-h 평면에서 구조(마하·동압 한계)·
공력(실속·DB 범위)·운용(고도 상하한) 경계를 합성해 행별 승자 귀속과 함께
반환한다. 제어 가능 영역(트림 성립)은 여기 없다 — envelope_ok(design.points
정본)를 트림 격자에 적용하는 별도 스캔의 몫. stall_mach_lo·row_machs는
coarse 격자(design.grid)와 이 합성이 공유하는 mach 경계의 단일 정본이다.
"""

import math

import numpy as np

from claw.common.constants import G0
from claw.env import isa_atmosphere
from claw.env.constants import ISA_MIN_ALT, ISA_STRATO1_TOP_ALT

DEFAULT_SCHEDULE_ALTS = (0.0, 1000.0, 3000.0, 5000.0)  # [m] coarse 격자 고도 [기본값]
_ALT_DISPLAY_MAX = 12000.0  # [m] 설계 엔벨로프 표시 상한 [기본값] — 운용 상한 아님 (echo로 명기)
_SCAN_POINTS = 41  # 실속 경계 역보간용 mach 스캔 밀도 (구 design.grid._SCAN_POINTS)


def _check_limits(limits) -> None:
    """구조 한계 dict 검증 — 사용자 오버라이드가 열리면서 필요해진 공용 경계.

    데모 자리표시만 쓰던 시절에는 항상 유효했지만, 필요값 입력(01 §2.6)이
    한계를 요청으로 받으므로 부호·서열이 깨진 값을 계산 전에 막는다.
    """
    if not float(limits["n_limit_pos"]) > 0.0:
        raise ValueError(f"n_limit_pos는 양수여야 함: {limits['n_limit_pos']}")
    if not float(limits["n_limit_neg"]) < 0.0:
        raise ValueError(f"n_limit_neg는 음수여야 함: {limits['n_limit_neg']}")
    if not float(limits["safety_factor"]) >= 1.0:
        raise ValueError(f"safety_factor는 1 이상: {limits['safety_factor']}")
    mach_no = float(limits["mach_no"])
    mach_d = float(limits["mach_d"])
    if not 0.0 < mach_no <= mach_d:
        raise ValueError(f"0 < mach_no ≤ mach_d 서열 위반: M_NO {mach_no}, M_D {mach_d}")


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
    주의: −ratio×α_stall이 공력 DB α 유효범위 밖일 수 있음(데모 −0.24 <
    하한 −0.2) — 해석식 데모 계수라 무해하나, 테이블 DB(clip) 교체 시 이
    자리표시도 실데이터로 함께 교체하는 전제.
    """
    atm = isa_atmosphere(alt)
    _check_limits(limits)
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


def stall_mach_lo(
    aircraft, stall_table, alt, fuel, *,
    mach_hi, db_mach_lo=0.0, mach_margin=1.1, n_scan=_SCAN_POINTS,
) -> tuple:
    """행(alt, fuel)의 mach 하한 — (mach_lo, source). 구 design.grid._mach_lo의 정본 이동.

    V_S(n=1)를 실속 경계 곡선에서 역보간해 mach_margin(1.1 [기본값] — 실속 여유
    10%)을 곱한다. source는 경계 귀속: "stall"(실속이 결정) | "db"(스캔 범위에
    V_S가 없거나 DB 하한이 더 높아 실효 하한이 됨). 단조 n(V) 가정(동압 V²
    지배)은 vn_envelope와 공유 — 비단조 실 DB 결선 시 함께 재검토.
    """
    scan_lo = max(float(stall_table.axes[0][0]), db_mach_lo)
    machs = np.linspace(scan_lo, mach_hi, int(n_scan))
    bnd = vn_stall_boundary(aircraft, stall_table, alt, fuel, machs)
    n_arr = np.asarray(bnd["n"])
    v_arr = np.asarray(bnd["V"])
    if not n_arr[0] <= 1.0 <= n_arr[-1]:
        return max(db_mach_lo, scan_lo), "db"  # 스캔 범위에 V_S가 없다 — DB 하한이 실효 하한
    v_s = float(np.interp(1.0, n_arr, v_arr))
    atm = isa_atmosphere(alt)
    lo = (v_s / atm.a) * mach_margin
    if lo > db_mach_lo:
        return lo, "stall"
    return db_mach_lo, "db"


def row_machs(
    aircraft, stall_table, alt, fuel, *,
    mach_hi, db_mach_lo, mach_margin=1.1, n_mach=5,
) -> list:
    """행(alt, fuel)의 스케줄 mach 목록 — coarse 격자(design.grid)와 설계 엔벨로프
    표시가 공유하는 격자 좌표의 단일 정본. lo ≥ hi면 빈 목록(유효 구간 없음),
    round 4자리는 coarse 격자 관례 승계."""
    lo, _src = stall_mach_lo(
        aircraft, stall_table, alt, fuel,
        mach_hi=mach_hi, db_mach_lo=db_mach_lo, mach_margin=mach_margin,
    )
    if lo >= mach_hi:
        return []
    return [float(m) for m in np.round(np.linspace(lo, mach_hi, int(n_mach)), 4)]


def mach_qbar_limit(alt, q_max) -> float:
    """동압 한계의 마하 환산 — M_q̄(h) = √(2·q_max/ρ(h)) / a(h).

    q̄ = ½ρV² ≤ q_max (구조 동압 한계, 01 §2.6). ρ가 고도에 따라 줄어
    한계 마하는 고도 단조 증가 — M-h 설계 엔벨로프의 우측 경계 후보.
    """
    if not float(q_max) > 0.0:
        raise ValueError(f"q_max는 양수 [Pa]: {q_max}")
    atm = isa_atmosphere(alt)
    return math.sqrt(2.0 * float(q_max) / atm.rho) / atm.a


def design_envelope(
    aircraft, stall_table, limits, db_ranges, *, fuel,
    q_max=None, alt_min=None, alt_max=None, mach_margin=1.1,
    n_alt=41, schedule_n_mach=5, schedule_alts=None,
) -> dict:
    """제어법칙 설계 엔벨로프 M-h 합성 (01 §2.6) — 행별 경계와 승자 귀속.

    합성: mach_lo(h) = max(실속 V_S×여유, DB 하한), mach_hi(h) = min(M_NO,
    DB 상한, 실속표 축 상한, M_q̄(h)). lo_source/hi_source가 행마다 어느
    엔벨로프가 경계를 결정했는지 귀속한다("stall"|"db", "mach_no"|"db"|
    "stall_table"|"qbar"). lo ≥ hi인 행은 empty(자연 천장 — 설계 영역 없음).

    q_max·alt_min·alt_max는 실기체 값이라 기본값이 없다 — None이면 해당
    경계를 합성에서 제외하고 출력에도 null (없는 데이터를 그리지 않는다).
    표시 고도 상한만 _ALT_DISPLAY_MAX [기본값]로 채우고
    alt_max_is_display_default로 echo — 소비자(웹)가 자리표시임을 명기.

    schedule_grid는 coarse 격자(design.grid)와 같은 row_machs 좌표 —
    trimmable 판정 없는 좌표 표시용(판정은 트림 스캔 + envelope_ok 정본).
    """
    _check_limits(limits)
    if not mach_margin >= 1.0:
        raise ValueError(f"mach_margin은 1 이상 (실속 여유): {mach_margin}")
    if int(n_alt) < 2:
        raise ValueError(f"n_alt는 2 이상: {n_alt}")
    for name, v in (("alt_min", alt_min), ("alt_max", alt_max)):
        if v is not None and not ISA_MIN_ALT <= float(v) <= ISA_STRATO1_TOP_ALT:
            raise ValueError(
                f"{name} {v} m가 ISA 유효범위({ISA_MIN_ALT:.0f}~{ISA_STRATO1_TOP_ALT:.0f} m) 밖"
            )
    alt_lo_used = float(alt_min) if alt_min is not None else 0.0
    alt_hi_used = float(alt_max) if alt_max is not None else _ALT_DISPLAY_MAX
    if not alt_lo_used < alt_hi_used:
        raise ValueError(f"운용 고도 하한 ≥ 상한: {alt_lo_used} ≥ {alt_hi_used} m")

    db_mach_lo, db_mach_hi = (float(v) for v in db_ranges["mach"])
    axis_hi = float(stall_table.axes[0][-1])
    # 고도 무관 상한 3후보 — min 승자 귀속 (동률은 구조 우선 순서)
    static_hi, static_src = min(
        (float(limits["mach_no"]), "mach_no"),
        (db_mach_hi, "db"),
        (axis_hi, "stall_table"),
        key=lambda t: t[0],
    )

    alts = [float(a) for a in np.linspace(alt_lo_used, alt_hi_used, int(n_alt))]
    region = {"alt": alts, "mach_lo": [], "mach_hi": [], "lo_source": [], "hi_source": [], "empty": []}
    qbar_mach = [] if q_max is not None else None
    for alt in alts:
        lo, lo_src = stall_mach_lo(
            aircraft, stall_table, alt, fuel,
            mach_hi=static_hi, db_mach_lo=db_mach_lo, mach_margin=mach_margin,
        )
        hi, hi_src = static_hi, static_src
        if q_max is not None:
            qm = mach_qbar_limit(alt, q_max)
            qbar_mach.append(float(qm))
            if qm < hi:
                hi, hi_src = qm, "qbar"
        region["mach_lo"].append(float(lo))
        region["mach_hi"].append(float(hi))
        region["lo_source"].append(lo_src)
        region["hi_source"].append(hi_src)
        region["empty"].append(bool(lo >= hi))

    sched_alts = tuple(
        float(a) for a in (schedule_alts if schedule_alts is not None else DEFAULT_SCHEDULE_ALTS)
        if alt_lo_used <= float(a) <= alt_hi_used
    )
    points = []
    for alt in sched_alts:
        for m in row_machs(
            aircraft, stall_table, alt, fuel,
            mach_hi=static_hi, db_mach_lo=db_mach_lo,
            mach_margin=mach_margin, n_mach=schedule_n_mach,
        ):
            points.append({"mach": m, "alt": alt})

    return {
        "fuel": float(fuel),
        "mach_margin": float(mach_margin),
        "bounds": {
            "qbar_mach": qbar_mach,
            "q_max": float(q_max) if q_max is not None else None,
            "mach_no": float(limits["mach_no"]),
            "mach_d": float(limits["mach_d"]),
            "db_mach": [db_mach_lo, db_mach_hi],
            "alt_min": float(alt_min) if alt_min is not None else None,
            "alt_max": float(alt_max) if alt_max is not None else None,
            "alt_min_used": alt_lo_used,
            "alt_max_used": alt_hi_used,
            "alt_max_is_display_default": alt_max is None,
        },
        "region": region,
        "schedule_grid": {
            "n_mach": int(schedule_n_mach),
            "alts": list(sched_alts),
            "points": points,
        },
    }


def aero_envelope(stall_table, db_ranges, *, alpha_margin=0.0, trim_alpha_bounds=None, n_mach=81) -> dict:
    """공력 엔벨로프 선도 데이터 (01 §2.6) — α–Mach 평면의 경계 일습.

    실속 경계 α_stall(M)·보호선(α_stall − alpha_margin, §3.6 α 리미터와 같은
    마진 의미)·공력 DB 유효범위. trim_alpha_bounds는 트림 탐색 α 범위(trim
    상수 정본 — trim은 같은 계층이라 호출자가 주입, 미주입 시 null)."""
    if not float(alpha_margin) >= 0.0:
        raise ValueError(f"alpha_margin은 0 이상: {alpha_margin}")
    m0 = float(stall_table.axes[0][0])
    m1 = float(stall_table.axes[0][-1])
    machs = [float(m) for m in np.linspace(m0, m1, int(n_mach))]
    stall = [float(stall_table.interp(mach=m)) for m in machs]
    return {
        "mach": machs,
        "alpha_stall": stall,
        "alpha_prot": [a - float(alpha_margin) for a in stall],
        "alpha_margin": float(alpha_margin),
        "db": {
            "alpha": [float(v) for v in db_ranges["alpha"]],
            "mach": [float(v) for v in db_ranges["mach"]],
        },
        "trim_alpha_bounds": (
            [float(v) for v in trim_alpha_bounds] if trim_alpha_bounds is not None else None
        ),
    }
