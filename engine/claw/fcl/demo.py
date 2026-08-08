"""데모 델타윙 M7 조립 — 설계 게인·동압 스케줄·α 리미터·믹서 일습.

"비행체 프로파일" 교체 단위(03 §7.2)의 법칙 측 절반 — plant.demo와 짝.
SCAS·AP 게인은 설계점 M0.6 h1000 fuel200에서 선형모델 고유치 스캔 + 비선형
폐루프 확인으로 선정한 설계값 (증분 A·B 테스트가 성능 회귀 고정).

게인 스케줄 [기본값]: 동압 역비 스케일 f = min((M_design/M)², 4) — 저속에서
루프 강성 유지(피치·롤 PI·레이트 게인 공통), 상한 4는 저속 타면 포화 억제.
전 비행영역(M0.25~0.8) 폐루프 고유치 안정 확인 완료. 1D mach 테이블이며
고도·연료 축 확장은 트림 격자 확보 후 [TBD].
"""

import numpy as np

from claw.fcl.autopilot import Autopilot
from claw.fcl.law import FlightControlLaw
from claw.fcl.limiter import AlphaLimiter
from claw.fcl.mixer import Mixer
from claw.fcl.scas import Scas, ScasAxis
from claw.fcl.schedule import GainSchedule
from claw.plant import make_demo_stall_table
from claw.tables import Table

# 설계점 M0.6 h1000 fuel200 SCAS 게인 (증분 A 설계 스캔)
DEMO_PITCH = dict(kp=-2.0, ki=-0.5, k_rate=0.4, out_lo=-0.35, out_hi=0.35)
DEMO_ROLL = dict(kp=1.0, ki=0.1, k_rate=-0.2, out_lo=-0.35, out_hi=0.35)
DEMO_YAW = dict(kp=0.5, ki=0.0, k_rate=0.8, washout_tau=2.0, out_lo=-0.35, out_hi=0.35)

_M_DESIGN = 0.6
_F_CAP = 4.0


def make_demo_gain_tables() -> dict:
    """동압 스케일 1D mach 게인 테이블 — 피치·롤 PI·레이트 게인."""
    machs = np.round(np.arange(0.15, 0.951, 0.05), 4)
    f = np.minimum((_M_DESIGN / machs) ** 2, _F_CAP)
    base = {
        "pitch.kp": DEMO_PITCH["kp"],
        "pitch.ki": DEMO_PITCH["ki"],
        "pitch.k_rate": DEMO_PITCH["k_rate"],
        "roll.kp": DEMO_ROLL["kp"],
        "roll.ki": DEMO_ROLL["ki"],
        "roll.k_rate": DEMO_ROLL["k_rate"],
    }
    return {
        name: Table({"mach": machs}, g0 * f, name=name, extrapolate="clip")
        for name, g0 in base.items()
    }


def make_demo_fcl(with_schedule: bool = True, with_limiter: bool = True) -> FlightControlLaw:
    """데모 기체 FCL 조립 — init(dt) 후 reset(트림 웜스타트)으로 사용."""
    scas = Scas(ScasAxis(**DEMO_PITCH), ScasAxis(**DEMO_ROLL), ScasAxis(**DEMO_YAW))
    ap = Autopilot()  # 기본값 = 증분 B 설계값
    mixer = Mixer(k_diff_thr=0.1)  # 차동추력 러더 보조 (Cn_dr<0 프로파일 기준 +)
    schedule = GainSchedule(make_demo_gain_tables(), filter_tau=0.5) if with_schedule else None
    limiter = AlphaLimiter(make_demo_stall_table(), margin=0.05) if with_limiter else None
    return FlightControlLaw(scas, ap, mixer, schedule=schedule, alpha_limiter=limiter)
