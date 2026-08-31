"""M5 plant — 6DOF·공력·추진·질량특성·작동기·센서 (03 M5, 구현 문서 §3 모듈 4·5·6).

구현됨: eom(6DOF+RK4, 물리검증), mass(연료 의존 질량·CG·관성), prop(쌍발·차동추력),
actuator(2차계+위치/속도 제한, 레지스트리 "actuator" 카테고리), aero(계수 함수 소비),
ground(스키드 접촉·발사 레일 — 착륙장치 r×F 포함, 01 §3.3.1 이륙·착륙).
후속 증분: sensor(초기 이상센서 — nav 오차 모델이 대행 중), F-16 공개 모델 재현(데이터 반입 후),
CFD DB 축 규격 확정 시 aero coef_fn ← M3 Table 결선.
"""

from claw.params.registry import REGISTRY
from claw.plant.actuator import SecondOrderActuator
from claw.plant.aero import AeroModel, wind_to_body_coeffs
from claw.plant.aircraft import (
    XE_H,
    XE_NAMES,
    XE_P,
    XE_PE,
    XE_PHI,
    XE_PN,
    XE_PSI,
    XE_Q,
    XE_R,
    XE_THETA,
    XE_U,
    XE_V,
    XE_W,
    Aircraft,
)
from claw.plant.demo import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_launch_rail,
    make_demo_skid_gear,
    make_demo_stall_table,
    make_demo_structural_limits,
)
from claw.plant.eom import (
    N_STATES,
    OMEGA,
    POS,
    QUAT,
    VEL,
    RigidBody,
    gravity_body,
    pack,
    rk4_step,
    unpack,
)
from claw.plant.ground import LaunchRail, SkidGear
from claw.plant.mass import FuelMass
from claw.plant.prop import TwinEngine

SecondOrderActuator.register(REGISTRY, category="actuator")  # 교체 가능 컴포넌트 (02 §2.3)

__all__ = [
    "N_STATES",
    "POS",
    "VEL",
    "QUAT",
    "OMEGA",
    "RigidBody",
    "gravity_body",
    "pack",
    "unpack",
    "rk4_step",
    "FuelMass",
    "TwinEngine",
    "SkidGear",
    "LaunchRail",
    "SecondOrderActuator",
    "AeroModel",
    "wind_to_body_coeffs",
    "Aircraft",
    "make_demo_aircraft",
    "make_demo_db_ranges",
    "make_demo_launch_rail",
    "make_demo_skid_gear",
    "make_demo_stall_table",
    "make_demo_structural_limits",
    "XE_NAMES",
    "XE_U",
    "XE_V",
    "XE_W",
    "XE_P",
    "XE_Q",
    "XE_R",
    "XE_PHI",
    "XE_THETA",
    "XE_PSI",
    "XE_PN",
    "XE_PE",
    "XE_H",
]
