"""델타윙 데모 비행체 프로파일 — 합성 선형 계수 (검증·예제·튜토리얼용).

CFD DB 반입 전의 대역(placeholder) 프로파일이며 "비행체 프로파일" 교체 단위(03 §7.2)의
첫 사례. 정적 안정(Cmα<0)·피치 댐핑(Cmq<0)·더치롤류 횡방향 계수를 갖는 아음속 소형
델타윙 상정. 수치는 검증 손계산이 쉬운 라운드 값 — 실기체 값 아님.
"""

import math

import numpy as np

from claw.plant.aero import AeroModel, wind_to_body_coeffs
from claw.plant.aircraft import Aircraft
from claw.plant.ground import LaunchRail, SkidGear
from claw.plant.mass import FuelMass
from claw.plant.prop import SingleEngine
from claw.tables import Table

# 스키드 접촉 [기본값] — 강성은 "정지 침투량"으로 정한다. 총중량 10.8 kN을 5 cm에서
# 받으려면 k_total = W/0.05 ≈ 216 kN/m, 4점이면 점당 54 kN/m. 감쇠는 ζ≈0.7:
# ω_n = √(k_total/m) ≈ 14 rad/s → c_total = 2ζmω_n ≈ 21.6 kN·s/m, 점당 5.4 kN·s/m.
# 접촉 고유주파수 2.2 Hz라 dt_plant 0.005~0.01에서 RK4가 충분히 분해한다.
SKID_K = 54_000.0  # [N/m] 점당
SKID_C = 5_400.0  # [N·s/m] 점당
SKID_MU = 0.35  # [-] 미끄럼 마찰 (바퀴 아님 — 구름이 아니라 미끄럼)


def make_demo_skid_gear() -> SkidGear:
    """데모 스키드 — 좌·우 스키드를 각각 앞·뒤 2점으로, 총 4점.

    좌우 2점만 두면 피치 자유도가 없어 접지 후 기수 내려앉음이 나오지 않는다.

    **접촉점 중심을 CG에 맞춘다(x 대칭).** 어긋나면 수평 자세가 평형이 아니게 되어
    기체가 지상에서 늘 한쪽으로 기운 채 선다 — 접촉 중심이 CG보다 Δx 앞이면 정지
    상태에서 M_y = Δx·W 의 기수 올림이 남는다(0.10 m면 1.08 kN·m). 활주 이륙이라면
    CG를 주기어 앞에 두어 회전(rotation)을 얻지만, 이 기체는 발사대 이륙이라
    그럴 이유가 없고 수평 정지가 더 쓸모 있다.
    수치는 데모 프로파일용 라운드 값 — 실기체 값 아님.
    """
    contacts = np.array(
        [
            [0.60, -0.60, 0.55],  # 좌 앞
            [-0.60, -0.60, 0.55],  # 좌 뒤
            [0.60, 0.60, 0.55],  # 우 앞
            [-0.60, 0.60, 0.55],  # 우 뒤
        ]
    )
    return SkidGear(contacts, k=SKID_K, c=SKID_C, mu=SKID_MU)


# 발사대 위 CG 시작 높이 [m] [기본값] — 레일 구조물이 기체를 지면에서 들어 올린 높이.
# 0으로 두면 스키드 접촉점(CG 아래 0.55 m)이 지면 0.55 m 아래에 박힌 채 시작해,
# 레일 구간 내내 wow·기어 반력이 거짓으로 선다(레일이 받치는데 기어가 받는 것처럼
# 기록된다). 2.9 m는 발사관 시각화 모델의 캐니스터 축(관 뒤끝 기준 2.83 m,
# models/launcher/README.md 2026-09-02 2차 개정 실측)과 맞춘 값이다 — 기체가 관
# 속에서 사출되는 그림이 되고, 접촉점(지면 위 2.35 m)은 여전히 지면에 안 닿는다.
RAIL_ORIGIN_H = 2.9


def make_demo_launch_rail() -> LaunchRail:
    """데모 발사대 [기본값] — 레일 10 m, 앙각 15°, 이탈 81.5 m/s.

    이탈 속도는 트림 정합 실속속도 70.9 m/s의 1.15배다. α_stall 0.40에서 CL 1.40이
    나오지만 거기까지 가려면 상향 엘러본이 필요하고 그것이 양력을 깎으므로
    (Cm = 0.02 − 0.8α − 1.0δe = 0 동시 만족), 실제 최대 트림 CL은 1.169다.
    레일 10 m에서 이 속도는 **33.9 g**를 요구한다 — 판정 기준은 구조 한계
    n_x_launch이고 그 값은 아직 [TBD]라 "미판정"으로 표시된다.
    """
    return LaunchRail(
        length=10.0,
        elev_angle=math.radians(15.0),
        exit_speed=81.5,
        origin_n=np.array([0.0, 0.0, -RAIL_ORIGIN_H]),
    )


def make_demo_aircraft(ground=None) -> Aircraft:
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
    # 추진 [기본값] — **단발 중심선 8 kN**. 시각화 모델(models/shahed-136: 2엽 푸셔
    # 1기)이 정본이고 동역학을 거기 맞췄다. 총추력은 종전 쌍발(4 kN×2)과 같게 두어
    # 종방향은 한 톨도 안 바뀐다 — 바뀌는 것은 **차동추력 요 모멘트가 사라지는 것
    # 하나뿐**이고, 그래서 믹서의 k_diff_thr도 0이다(fcl/demo.py DEMO_K_DIFF_THR).
    # 요축 재튜닝은 하지 않았다: 실측상 필요가 없다 (그 근거는 fcl/demo.py에).
    # 값을 고칠 곳은 여기 하나다 (plant/prop.py 스키마 기본값도 이 값과 같게 유지).
    engine = SingleEngine(max_thrust=8000.0)
    return Aircraft(fuel_mass, aero, engine, ground=ground)


def make_demo_db_ranges() -> dict:
    """데모 프로파일 공력 DB 유효범위 — 엔벨로프 감시(M11) db_ranges 입력.

    합성 선형 계수의 대역 상정값 — CFD DB 반입 시 DB 축 범위로 교체.

    **마하 하한은 0이다.** 위 coef 함수는 마하를 입력으로 받기만 하고 **쓰지 않는다**
    (M0.15와 M0.85의 계수가 동일). 즉 종전 하한 0.1은 데이터의 성질이 아니라
    "아음속 소형 델타윙 상정"이라는 대역 서술이었고, 그 값 때문에 해면 34 m/s 아래가
    전부 "DB 범위 밖"으로 찍혀 발사 레일 구간과 착륙 미끄럼 구간 전체에 마하 플래그가
    섰다 — 이착륙 미션에서 엔벨로프 요약(any_flag)이 상시 참이 되어 변별력을 잃는다.
    상한 0.9는 다르다: 천음속에서 이 선형식이 무의미해지는 것은 실제 주장이라 남긴다.
    CFD DB가 들어오면 두 경계 모두 DB의 실제 축 범위로 대체되고 하한은 다시 오를 것이다.
    """
    return {"alpha": (-0.2, 0.45), "beta": (-0.3, 0.3), "mach": (0.0, 0.9)}


def make_demo_structural_limits() -> dict:
    """데모 구조 한계 [기본값] — V-n 선도 표시용 자리표시 (실기체 값 아님).

    구조팀 정본 확보 시 교체 (01 §3.6 — Nz 제한 [TBD]와 한 세트).
    제한하중배수(운용 허용) ±, 극한 = 제한 × 안전계수 1.5 [관례],
    mach_no = 최대 구조 순항 마하(V_NO 상당), mach_d = 급강하 한계 마하(V_D).

    n_x_launch는 **종방향** 발사 하중 한계다 [TBD — 값 없음]. n_limit_pos 6.0은 Nz(수직)
    이라 레일 사출의 34 g를 판정할 수 없다. 값이 None인 동안 시뮬은 사출 가속도를
    기록하되 판정은 "미판정"으로 낸다 — None을 0이나 통과로 바꾸면 "판정 불가"와
    "한계 이내"가 같은 화면이 된다 (01 §4.2와 같은 자리).
    """
    return {
        "n_limit_pos": 6.0,
        "n_limit_neg": -3.0,
        "safety_factor": 1.5,
        "mach_no": 0.75,
        "mach_d": 0.9,
        "n_x_launch": None,
    }


def make_demo_stall_table() -> Table:
    """데모 실속 경계 α_stall = f(Mach) — 공력팀 정본 대역 (01 §2.3).

    소비자: α 리미터(M7), 엔벨로프 감시(M11). 외삽 금지(clip).
    수치는 데모 프로파일용 라운드 값 — 델타윙 고α 특성 상정, 실기체 값 아님.

    이착륙 속도대(정지~이탈)는 M0.1 아래라 **clip이 답한다** — 0.40으로 고정된다.
    격자점을 M=0에 하나 더 두어 정의역을 명시할 수도 있지만 수치가 완전히 같고
    (clip이 이미 0.40을 낸다) 생성 비행코드의 룩업 표 데이터·지문만 바뀌므로 두지
    않는다. 여기서 clip은 외삽 회피가 아니라 **선언된 정책**이다.
    """
    return Table(
        {"mach": (0.1, 0.3, 0.5, 0.7, 0.9)},
        (0.40, 0.35, 0.33, 0.30, 0.27),
        name="alpha_stall",
        extrapolate="clip",
    )
