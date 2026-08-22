"""데모 델타윙 M7 조립 — 설계 게인·동압 스케줄·α 리미터·믹서 일습.

"비행체 프로파일" 교체 단위(03 §7.2)의 법칙 측 절반 — plant.demo와 짝.
SCAS·AP 게인은 설계점 M0.6 h1000 fuel200에서 선형모델 고유치 스캔 + 비선형
폐루프 확인으로 선정한 설계값 (증분 A·B 테스트가 성능 회귀 고정).

게인 스케줄 [기본값]: 동압 역비 스케일 f = min((M_design/M)², 4) — 저속에서
루프 강성 유지(피치·롤 PI·레이트 게인 공통), 상한 4는 저속 타면 포화 억제.
전 비행영역(M0.25~0.8) 폐루프 고유치 안정 확인 완료. 1D mach 테이블이며
고도·연료 축 확장은 트림 격자 확보 후 [TBD].

**어느 게인을 스케줄할지는 형상의 일부다** — 기본은 DEFAULT_SCHEDULED 6자리이고,
전체 자리는 fcl/graphs.py SCHEDULABLE(16자리)이다. 뺀 자리는 설계점 상수로 굳어
생성 C에서 룩업이 사라진다.
"""

import numpy as np

from claw.fcl.autopilot import Autopilot
from claw.fcl.law import FlightControlLaw
from claw.fcl.limiter import AlphaLimiter
from claw.fcl.mixer import Mixer
from claw.fcl.scas import Scas, ScasAxis
from claw.fcl.schedule import GainSchedule, design_gains
from claw.plant import make_demo_stall_table
from claw.tables import Table

# 설계점 M0.6 h1000 fuel200 SCAS 게인 (증분 A 설계 스캔)
DEMO_PITCH = dict(kp=-2.0, ki=-0.5, k_rate=0.4, out_lo=-0.35, out_hi=0.35)
DEMO_ROLL = dict(kp=1.0, ki=0.1, k_rate=-0.2, out_lo=-0.35, out_hi=0.35)
DEMO_YAW = dict(kp=0.5, ki=0.0, k_rate=0.8, washout_tau=2.0, out_lo=-0.35, out_hi=0.35)

_M_DESIGN = 0.6
_F_CAP = 4.0


# 기본 스케줄 대상 [기본값] — 피치·롤의 PI·레이트 게인. 요축과 AP 게인은 설계점
# 고정이다. 이 구성은 **선택 가능**하고(웹 게인 탭), 바꾸면 탑재 C 구조와 지문이
# 함께 바뀐다 — 스케줄한 자리는 룩업 + 필터 상태가 생기고 뺀 자리는 상수로 접힌다.
DEFAULT_SCHEDULED = (
    "pitch.kp", "pitch.ki", "pitch.k_rate",
    "roll.kp", "roll.ki", "roll.k_rate",
)


def demo_design_gains() -> dict:
    """데모 기체의 자리별 설계점 상수 — `make_demo_fcl`이 조립하는 값 그대로."""
    return design_gains(
        {"pitch": DEMO_PITCH, "roll": DEMO_ROLL, "yaw": DEMO_YAW}, Autopilot().cfg
    )


def make_demo_gain_tables(names=None) -> dict:
    """동압 스케일 1D mach 게인 테이블 — 기본은 피치·롤 PI·레이트 게인 6개.

    `names`로 스케줄 자리를 골라 만들 수 있다 (웹 게인 탭의 대상 선택 경로).
    새로 켠 자리도 **같은 동압 스케일**로 채운다 — 자리마다 다른 규칙을 쓰면 켜는
    순간 형상이 튀어서, 켜기 전후를 비교할 수가 없다. 설계점(M0.6)에서는 어느
    자리든 설계 상수 그대로다.
    """
    machs = np.round(np.arange(0.15, 0.951, 0.05), 4)
    f = np.minimum((_M_DESIGN / machs) ** 2, _F_CAP)
    design = demo_design_gains()
    wanted = DEFAULT_SCHEDULED if names is None else tuple(names)
    unknown = [n for n in wanted if n not in design]
    if unknown:
        raise ValueError(f"스케줄 불가 자리 {unknown} — 허용: {sorted(design)}")
    return {
        name: Table({"mach": machs}, design[name] * f, name=name, extrapolate="clip")
        for name in wanted
    }


# 설계 기본값 — 조립이 쓰는 값 그대로. 주입 인자가 None일 때 여기서 만든다
DEMO_K_DIFF_THR = 0.1  # 차동추력 러더 보조 (Cn_dr<0 프로파일 기준 +)
DEMO_ALPHA_MARGIN = 0.05  # α 리미터 실속 마진 [rad] (01 §3.6)


def make_demo_fcl(
    with_schedule: bool = True,
    with_limiter: bool = True,
    autopilot: Autopilot | None = None,
    gain_tables: dict | None = None,
    scas: Scas | None = None,
    mixer: Mixer | None = None,
    alpha_margin: float | None = None,
) -> FlightControlLaw:
    """데모 기체 FCL 조립 — init(dt) 후 reset(트림 웜스타트)으로 사용.

    **조립 정본은 이 함수 하나다** (02 v0.24) — 생성기·서버·해석 모듈이 전부 여기를
    지난다. 아래 주입 인자들은 그 정본을 우회하는 통로가 아니라, 정본이 받는 손잡이다.

    autopilot·scas·mixer·alpha_margin 주입은 **파라미터 스터디용** (파이프라인
    Δ리포트·민감도 스윕에서 게인을 흔들 때, M15) — None이면 설계 기본값.
    gain_tables 주입은 게인 스케줄 편집 경로 (M13/M14, 02 §8 4단계) — None이면
    설계 테이블. 주입은 **전체 교체**(설계 테이블과 병합 아님 — 일부만 주입하면
    나머지 게인은 스케줄 없이 설계점 고정값). 그룹·키 검증은 FCL 조립이 수행.

    alpha_margin은 with_limiter=True에서만 뜻이 있다 — 리미터 없는 형상에 마진을
    주는 것은 조용히 무시되면 안 되는 모순이라 예외로 막는다.
    """
    if gain_tables is not None and not with_schedule:
        raise ValueError("gain_tables 주입은 with_schedule=True에서만 유효")
    if alpha_margin is not None and not with_limiter:
        raise ValueError("alpha_margin 주입은 with_limiter=True에서만 유효")
    scas = scas if scas is not None else Scas(
        ScasAxis(**DEMO_PITCH), ScasAxis(**DEMO_ROLL), ScasAxis(**DEMO_YAW)
    )
    ap = autopilot if autopilot is not None else Autopilot()  # 기본값 = 증분 B 설계값
    mixer = mixer if mixer is not None else Mixer(k_diff_thr=DEMO_K_DIFF_THR)
    schedule = (
        GainSchedule(
            gain_tables if gain_tables is not None else make_demo_gain_tables(),
            filter_tau=0.5,
        )
        if with_schedule
        else None
    )
    limiter = (
        AlphaLimiter(
            make_demo_stall_table(),
            margin=DEMO_ALPHA_MARGIN if alpha_margin is None else float(alpha_margin),
        )
        if with_limiter
        else None
    )
    return FlightControlLaw(scas, ap, mixer, schedule=schedule, alpha_limiter=limiter)
