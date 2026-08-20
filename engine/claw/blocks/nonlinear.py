"""비선형 블록 — DeadZone, Backlash, Hysteresis (구현 문서 §2.2).

Saturation·RateLimiter는 basic·dynamics 참조. 셋 모두 정적 파라미터만 가지므로
이산화 불필요(_discretize 기본 no-op 상속).
"""

from claw.blocks.base import Block
from claw.params.param import ParamDef


class DeadZone(Block):
    """데드존 — [lo, hi] 구간 입력은 0, 밖은 경계로부터의 초과분을 출력 (Simulink 관례)."""

    NAME = "DeadZone"
    PARAM_DEFS = (
        ParamDef("lo", -0.1, "-", "데드존 하한"),
        ParamDef("hi", 0.1, "-", "데드존 상한"),
    )

    def __init__(self, lo: float = -0.1, hi: float = 0.1):
        if lo > hi:
            raise ValueError(f"lo({lo}) > hi({hi})")
        self.lo, self.hi = lo, hi

    def step(self, u):
        if u > self.hi:
            return u - self.hi
        if u < self.lo:
            return u - self.lo
        return 0.0


class Backlash(Block):
    """기계적 유격(백래시) — Simulink Backlash 관례: 출력은 입력 주위 폭 width의 갭
    안에 머물고, 입력이 갭 경계를 밀 때만 이동한다 (작동기 링키지 유격 모델, 02 §3)."""

    NAME = "Backlash"
    PARAM_DEFS = (
        ParamDef("width", 0.2, "-", "유격 전체 폭", lo=0.0),
        ParamDef("initial", 0.0, "-", "초기 출력값"),
    )

    def __init__(self, width: float = 0.2, initial: float = 0.0):
        if width < 0:
            raise ValueError(f"width는 음수 불가: {width}")
        self.width, self.initial = width, initial

    def reset(self, state=None) -> None:
        """state는 출력값 웜스타트 (범프리스 전환 계약)."""
        self.y = self.initial if state is None else float(state)

    def step(self, u):
        half = 0.5 * self.width
        if u - self.y > half:
            self.y = u - half
        elif u - self.y < -half:
            self.y = u + half
        return self.y


class Hysteresis(Block):
    """이력 릴레이(슈미트 트리거) — 상승 시 high_threshold에서 고상태로,
    하강 시 low_threshold에서 저상태로 전환. 임계값 사이에서는 직전 상태 유지."""

    NAME = "Hysteresis"
    PARAM_DEFS = (
        ParamDef("low_threshold", -1.0, "-", "하강 임계값(고→저 전환)"),
        ParamDef("high_threshold", 1.0, "-", "상승 임계값(저→고 전환)"),
        ParamDef("low_value", 0.0, "-", "저상태 출력"),
        ParamDef("high_value", 1.0, "-", "고상태 출력"),
    )

    def __init__(
        self,
        low_threshold: float = -1.0,
        high_threshold: float = 1.0,
        low_value: float = 0.0,
        high_value: float = 1.0,
    ):
        if low_threshold > high_threshold:
            raise ValueError(
                f"low_threshold({low_threshold}) > high_threshold({high_threshold})"
            )
        self.low_threshold, self.high_threshold = low_threshold, high_threshold
        self.low_value, self.high_value = low_value, high_value

    def reset(self, state=None) -> None:
        """state는 상태 웜스타트 — 참이면 고상태에서 시작."""
        self._high = False if state is None else bool(state)

    def step(self, u):
        if u >= self.high_threshold:
            self._high = True
        elif u <= self.low_threshold:
            self._high = False
        return self.high_value if self._high else self.low_value
