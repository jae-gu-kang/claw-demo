"""M5 plant — 6DOF·공력·추진·질량특성·작동기·센서 (03 M5, 구현 문서 §3 모듈 4·5·6).

구현됨: eom(6DOF+RK4, 물리검증), mass(연료 의존 질량·CG·관성), prop(쌍발·차동추력),
actuator(2차계+위치/속도 제한, 레지스트리 "actuator" 카테고리).
후속 증분: aero(공력 DB 소비), sensor(초기 이상센서). F-16 공개 모델 재현은 데이터 반입 후.
"""

from claw.params.registry import REGISTRY
from claw.plant.actuator import SecondOrderActuator
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
    "SecondOrderActuator",
]
