"""M2 blocks — 제어 요소 라이브러리 (구현 문서 §2.2).

프로토콜: init(dt) / step(u)->y / reset(state) / schema(). 이산화 계수는 주기로부터
자동 계산 (샘플레이트 파라미터화 원칙).

구현됨: 기본 연산(Gain/Sum/Product/Divide/Switch/Saturation),
신호 저장(Delay/UnitDelay/Memory), 적분/미분/레이트(Integrator/Derivative/RateLimiter),
선형 필터(Lag/LowPass/Washout/LeadLag/Notch/MovingAverage/IIRFilter),
제어기(PID/StateSpace/TransferFunction), 비선형(DeadZone/Backlash/Hysteresis), Fader.
"""

from claw.blocks.base import UNBOUNDED, Block
from claw.blocks.basic import Divide, Gain, Product, Saturation, Sum, Switch
from claw.blocks.controllers import PID, StateSpace, TransferFunction
from claw.blocks.dynamics import Derivative, Integrator, RateLimiter
from claw.blocks.extras import Fader
from claw.blocks.filters import IIRFilter, Lag, LeadLag, LowPass, MovingAverage, Notch, Washout
from claw.blocks.lookup import LookupBlock
from claw.blocks.memory import Delay, Memory, UnitDelay
from claw.blocks.nonlinear import Backlash, DeadZone, Hysteresis
from claw.blocks.registry import REGISTRABLE, register_all

register_all()  # 전역 REGISTRY에 1회 자동 등록 (import는 프로세스당 1회)

__all__ = [
    "Block",
    "UNBOUNDED",
    "Gain",
    "Sum",
    "Product",
    "Divide",
    "Switch",
    "Saturation",
    "Delay",
    "UnitDelay",
    "Memory",
    "Integrator",
    "Derivative",
    "RateLimiter",
    "Lag",
    "LowPass",
    "Washout",
    "LeadLag",
    "Notch",
    "MovingAverage",
    "IIRFilter",
    "PID",
    "StateSpace",
    "TransferFunction",
    "DeadZone",
    "Backlash",
    "Hysteresis",
    "Fader",
    "LookupBlock",
    "REGISTRABLE",
    "register_all",
]
