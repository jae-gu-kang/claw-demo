"""신호 저장 블록 — Delay(N샘플), UnitDelay, Memory (구현 문서 §2.2)."""

from collections import deque

from claw.blocks.base import Block
from claw.params.param import ParamDef


class Delay(Block):
    """N 샘플 지연 (FIFO). UnitDelay는 n=1인 특수 사례."""

    NAME = "Delay"
    PARAM_DEFS = (
        ParamDef("n", 1, "-", "지연 샘플 수", lo=1, hi=100000),
        ParamDef("initial", 0.0, "-", "지연 버퍼 초기값"),
    )

    def __init__(self, n: int = 1, initial: float = 0.0):
        if int(n) != n or n < 1:
            raise ValueError(f"n은 1 이상의 정수여야 함: {n}")
        self.n = int(n)
        self.initial = initial

    def reset(self, state=None) -> None:
        if state is None:
            self._buf = deque([self.initial] * self.n, maxlen=self.n)
            return
        buf = list(state)  # deque(maxlen)은 초과분을 조용히 버리므로 길이 검사를 먼저
        if len(buf) != self.n:
            raise ValueError(f"웜스타트 버퍼 길이 불일치: {len(buf)} != {self.n}")
        self._buf = deque(buf, maxlen=self.n)

    def step(self, u):
        y = self._buf.popleft()
        self._buf.append(u)
        return y


class UnitDelay(Delay):
    NAME = "UnitDelay"
    PARAM_DEFS = (ParamDef("initial", 0.0, "-", "초기 출력값"),)

    def __init__(self, initial: float = 0.0):
        super().__init__(n=1, initial=initial)


class Memory(Block):
    """이전 스텝의 입력을 그대로 출력 (대수루프 차단용)."""

    NAME = "Memory"
    PARAM_DEFS = (ParamDef("initial", 0.0, "-", "초기 출력값"),)

    def __init__(self, initial: float = 0.0):
        self.initial = initial

    def reset(self, state=None) -> None:
        self.y = self.initial if state is None else float(state)

    def step(self, u):
        out = self.y
        self.y = u
        return out
