"""기본 연산 블록 — Gain, Sum, Product, Divide, Switch, Saturation (구현 문서 §2.2).

Sum/Product/Divide는 구조적 배선 블록(가변 입력)이라 레지스트리 등록 대상이 아니다
(registry.py 참조).
"""

from claw.blocks.base import Block
from claw.params.param import ParamDef


class Gain(Block):
    NAME = "Gain"
    PARAM_DEFS = (ParamDef("k", 1.0, "-", "게인"),)

    def __init__(self, k: float = 1.0):
        self.k = k

    def step(self, u):
        return self.k * u


class Sum(Block):
    """다중 입력 가중합. u는 signs와 같은 길이의 시퀀스."""

    NAME = "Sum"

    def __init__(self, signs=(1.0, 1.0)):
        self.signs = tuple(signs)

    def step(self, u):
        return sum(s * x for s, x in zip(self.signs, u, strict=True))


class Product(Block):
    """다중 입력의 곱. u는 시퀀스."""

    NAME = "Product"

    def step(self, u):
        out = 1.0
        for x in u:
            out *= x
        return out


class Divide(Block):
    """u = (분자, 분모) → 분자/분모."""

    NAME = "Divide"

    def step(self, u):
        num, den = u
        return num / den


class Switch(Block):
    """Simulink Switch 관례: u = (in1, ctrl, in3) → ctrl >= threshold면 in1, 아니면 in3."""

    NAME = "Switch"
    PARAM_DEFS = (ParamDef("threshold", 0.0, "-", "전환 임계값"),)

    def __init__(self, threshold: float = 0.0):
        self.threshold = threshold

    def step(self, u):
        in1, ctrl, in3 = u
        return in1 if ctrl >= self.threshold else in3


class Saturation(Block):
    NAME = "Saturation"
    PARAM_DEFS = (ParamDef("lo", -1.0, "-", "하한"), ParamDef("hi", 1.0, "-", "상한"))

    def __init__(self, lo: float = -1.0, hi: float = 1.0):
        if lo > hi:
            raise ValueError(f"lo({lo}) > hi({hi})")
        self.lo, self.hi = lo, hi

    def step(self, u, lo=None, hi=None):
        """한계는 스텝마다 덮어쓸 수 있다 — PID와 같은 포트 규약.

        엘레본 제어권한 배분이 축 한계를 시간에 따라 바꾸는 자리에서 쓴다
        (fcl/graphs.py). 안 넘기면 생성자 값이라 포트를 안 붙인 자리는 거동이 같다.
        """
        lo = self.lo if lo is None else lo
        hi = self.hi if hi is None else hi
        return min(max(u, lo), hi)
