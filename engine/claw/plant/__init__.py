"""M5 plant — 6DOF·공력·추진·질량특성·작동기·센서 (03 M5, 구현 문서 §3 모듈 4·5·6).

구현됨: eom(6DOF 강체 운동방정식 + RK4, 물리검증 통과).
후속 증분: mass(연료 의존 질량·CG·관성), prop(쌍발 추력·차동), actuator(2차계+제한),
aero(공력 DB 소비), sensor(초기 이상센서). F-16 공개 모델 재현은 데이터 반입 후.
"""

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
]
