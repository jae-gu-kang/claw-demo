"""M2 블록 → M1 컴포넌트 레지스트리 등록 (구현 문서 §2.3 레지스트리+스키마 원칙).

스칼라 파라미터로 완전히 기술되는(=스키마 노출이 의미 있는) 블록만 등록 대상.
Sum/Product/Divide는 구조적 배선 블록(가변 입력 시퀀스)이라 제외 —
추후 StateSpace/TransferFunction/Lookup(행렬·테이블 데이터 입력)도 같은 이유로 제외.
"""

from claw.blocks.basic import Gain, Saturation, Switch
from claw.blocks.dynamics import Derivative, Integrator, RateLimiter
from claw.blocks.memory import Delay, Memory, UnitDelay
from claw.params.registry import REGISTRY

REGISTRABLE = (
    Gain,
    Switch,
    Saturation,
    Delay,
    UnitDelay,
    Memory,
    Integrator,
    Derivative,
    RateLimiter,
)


def register_all(registry=REGISTRY, category: str = "blocks") -> None:
    for cls in REGISTRABLE:
        cls.register(registry, category=category)
