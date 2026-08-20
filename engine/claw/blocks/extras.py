"""신호 관리 블록 — Fader (범프리스 전환용) (구현 문서 §2.2).

M8 guidance의 모드 전환기가 소비: 전환 시점에 trigger()를 호출하면 duration에 걸쳐
이전 명령(a)에서 새 명령(b)으로 선형 블렌드된다 (01 §3.3.1 범프리스 전환).
"""

from claw.blocks.base import Block
from claw.params.param import ParamDef


class Fader(Block):
    """두 입력 (a, b)의 선형 블렌드 y = (1-w)·a + w·b.

    trigger() 전에는 w=0 (a 통과). trigger() 후 매 스텝 w가 dt/duration씩 증가해
    duration 경과 시 w=1 (b 통과)로 완료된다.
    """

    NAME = "Fader"
    PARAM_DEFS = (ParamDef("duration", 1.0, "s", "전환 소요시간", lo=1e-9),)

    def __init__(self, duration: float = 1.0):
        if duration <= 0:
            raise ValueError(f"duration은 양수여야 함: {duration}")
        self.duration = duration

    def reset(self, state=None) -> None:
        """state는 블렌드 가중치 w 웜스타트 (0~1). w>0이면 전환 진행 중 상태로 복원."""
        if state is None:
            self._w = 0.0
            self._active = False
            return
        w = float(state)
        if not (0.0 <= w <= 1.0):
            raise ValueError(f"블렌드 가중치는 0~1: {w}")
        self._w = w
        self._active = w > 0.0

    def trigger(self) -> None:
        """전환 시작 — 이미 진행 중이면 무시(재시작하지 않음)."""
        self._active = True

    def step(self, u):
        a, b = u
        if self._active and self._w < 1.0:
            self._w = min(1.0, self._w + self.dt / self.duration)
        return (1.0 - self._w) * a + self._w * b
