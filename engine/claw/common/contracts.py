"""모듈 간 인터페이스 계약 (모듈 문서 §4) — 모듈 결합은 이 데이터 구조로만.

산출물 계약(TrimResult, LinearModel, SimResult)은 params_fingerprint(계보)를 보유한다 —
설계값 연계·정량 영향성 평가(구현 문서 §2.4)의 키. 단위는 전부 SI + rad (conventions.md).
"""

from dataclasses import dataclass, field

import numpy as np

from claw.common.attitude import QUAT_IDENTITY, quat_to_dcm, quat_to_euler


@dataclass
class VehicleState:
    """플랜트 참값 상태 (M5 생산). vel_b는 동체축, q_nb는 NED→동체."""

    t: float = 0.0
    pos_n: np.ndarray = field(default_factory=lambda: np.zeros(3))  # NED [m]
    vel_b: np.ndarray = field(default_factory=lambda: np.zeros(3))  # 동체축 [m/s]
    q_nb: np.ndarray = field(default_factory=lambda: QUAT_IDENTITY.copy())
    omega_b: np.ndarray = field(default_factory=lambda: np.zeros(3))  # [rad/s]
    fuel: float = 0.0  # 잔여 연료 [kg]

    def vel_n(self):
        return quat_to_dcm(self.q_nb).T @ self.vel_b

    def euler(self):
        return quat_to_euler(self.q_nb)


@dataclass
class NavOutput:
    """항법 출력 (M6 생산) — 법칙(M7·M8)이 소비하는 유일한 상태 정보.

    VehicleState 동형 + 유효성. t_meas는 지연이 반영된 측정 시각.
    """

    t: float = 0.0
    pos_n: np.ndarray = field(default_factory=lambda: np.zeros(3))
    vel_n: np.ndarray = field(default_factory=lambda: np.zeros(3))  # 항법 관례상 NED [m/s]
    q_nb: np.ndarray = field(default_factory=lambda: QUAT_IDENTITY.copy())
    omega_b: np.ndarray = field(default_factory=lambda: np.zeros(3))
    t_meas: float = 0.0
    valid: bool = True


@dataclass
class GuidanceCommand:
    """유도→오토파일럿 명령 (M8→M7). 축별 활성화 플래그는 비행모드 테이블이 정의."""

    speed: float = 0.0  # [m/s]
    alt: float = 0.0  # [m], MSL 기준 (씨스키밍 0 ft = MSL, 도메인 문서 §2.5)
    heading: float = 0.0  # [rad]
    speed_on: bool = False
    alt_on: bool = False
    heading_on: bool = False
    mode: str = ""


@dataclass
class SurfaceCommand:
    """법칙→작동기 명령 (M7→M5.actuator). elevon 순서 [내좌, 외좌, 내우, 외우] [기본값]."""

    elevon: np.ndarray = field(default_factory=lambda: np.zeros(4))  # [rad], TE down +
    rudder: float = 0.0  # [rad], TE left +
    throttle: np.ndarray = field(default_factory=lambda: np.zeros(2))  # 0~1 [좌, 우]


@dataclass
class TrimCase:
    """트림 케이스 정의 (UI/파일 → M9)."""

    name: str
    mach: float
    alt: float  # [m]
    fuel: float  # [kg]
    condition: str = "level"  # 수평정상비행부터 (도메인 문서 §4.1)
    extras: dict = field(default_factory=dict)


@dataclass
class TrimResult:
    """트림 해 (M9 생산). flags: 자동 판정 (도메인 문서 §4.1 — 잔차·포화·α 여유·연속성)."""

    case: TrimCase
    state: VehicleState
    control: SurfaceCommand
    converged: bool
    cost: float
    flags: dict = field(default_factory=dict)
    params_fingerprint: str = ""


@dataclass
class LinearModel:
    """트림점 선형모델 (M9 생산 → M10 소비). dt=0이면 연속시간."""

    A: np.ndarray
    B: np.ndarray
    C: np.ndarray
    D: np.ndarray
    x_names: tuple = ()
    u_names: tuple = ()
    y_names: tuple = ()
    axis: str = "full"  # 'lon' | 'lat' | 'full' (종/횡축 분리, 도메인 문서 §4.2)
    dt: float = 0.0
    case: TrimCase | None = None
    params_fingerprint: str = ""


@dataclass
class SimResult:
    """폐루프 시뮬 결과 (M11 생산). envelope: 감시 플래그·실속 마진 (구현 문서 §6.1)."""

    t: np.ndarray
    signals: dict = field(default_factory=dict)  # 이름 → 시계열 ndarray
    envelope: dict = field(default_factory=dict)
    params_fingerprint: str = ""
    meta: dict = field(default_factory=dict)
