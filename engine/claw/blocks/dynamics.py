"""적분·미분·레이트 블록 — Integrator(3방식·안티와인드업), Derivative, RateLimiter (구현 문서 §2.2)."""

from claw.blocks.base import UNBOUNDED, Block
from claw.params.param import ParamDef


class Integrator(Block):
    """이산 적분 + 클램프 안티와인드업. 방식: forward / backward / tustin.

    기본값 forward(전진 오일러)는 Simulink Discrete-Time Integrator 기본과 일치 —
    폐쇄망 회귀 대조(구현 문서 §7) 정합을 위한 선택. 클램프는 적분 상태 자체를
    [lo, hi]로 제한하므로 입력 부호 반전 시 와인드업 지연 없이 포화영역을 벗어난다.
    back-calculation 방식은 SCAS 설계 시 결정 (도메인 문서 §3.1 [TBD]).
    """

    NAME = "Integrator"
    METHODS = ("forward", "backward", "tustin")
    PARAM_DEFS = (
        ParamDef("ki", 1.0, "-", "적분 게인"),
        ParamDef("lo", -UNBOUNDED, "-", "출력 하한(안티와인드업)"),
        ParamDef("hi", UNBOUNDED, "-", "출력 상한(안티와인드업)"),
        ParamDef("initial", 0.0, "-", "초기 출력값"),
        ParamDef("method", "forward", "-", "이산 적분 방식", choices=METHODS),
    )

    def __init__(
        self,
        ki: float = 1.0,
        lo: float = -UNBOUNDED,
        hi: float = UNBOUNDED,
        initial: float = 0.0,
        method: str = "forward",
    ):
        if lo > hi:
            raise ValueError(f"lo({lo}) > hi({hi})")
        if method not in self.METHODS:
            raise ValueError(f"지원하지 않는 적분 방식: {method} (허용 {self.METHODS})")
        self.ki, self.lo, self.hi, self.initial, self.method = ki, lo, hi, initial, method

    def reset(self, state=None) -> None:
        """state는 적분값 웜스타트. 직전 입력 이력은 0으로 초기화 —
        forward/tustin은 전환 직후 첫 스텝 1회의 과도가 있음 (M7 전환 설계 시 유의)."""
        self.y = self.initial if state is None else float(state)
        self._u_prev = 0.0

    def step(self, u):
        if self.method == "forward":
            du = self._u_prev
        elif self.method == "backward":
            du = u
        else:  # tustin (사다리꼴)
            du = 0.5 * (u + self._u_prev)
        self.y = min(max(self.y + self.dt * self.ki * du, self.lo), self.hi)
        self._u_prev = u
        return self.y


class Derivative(Block):
    """후진차분 미분: y[k] = kd*(u[k]-u[k-1])/dt. 비필터링(원시) — 잡음에 민감하므로
    필터가 필요하면 Lag와 조합해 사용."""

    NAME = "Derivative"
    PARAM_DEFS = (ParamDef("kd", 1.0, "-", "미분 게인"),)

    def __init__(self, kd: float = 1.0):
        self.kd = kd

    def reset(self, state=None) -> None:
        self._u_prev = 0.0 if state is None else float(state)

    def step(self, u):
        y = self.kd * (u - self._u_prev) / self.dt
        self._u_prev = u
        return y


class RateLimiter(Block):
    """출력 변화율 제한. rate_up/rate_dn은 양수 크기 — 스텝당 변화량을 ±rate·dt로 클립."""

    NAME = "RateLimiter"
    PARAM_DEFS = (
        ParamDef("rate_up", 1.0, "1/s", "상승률 한계(양수)", lo=0.0),
        ParamDef("rate_dn", 1.0, "1/s", "하강률 한계(양수 크기)", lo=0.0),
        ParamDef("initial", 0.0, "-", "초기 출력값"),
    )

    def __init__(self, rate_up: float = 1.0, rate_dn: float = 1.0, initial: float = 0.0):
        self.rate_up, self.rate_dn, self.initial = rate_up, rate_dn, initial

    def reset(self, state=None) -> None:
        self.y = self.initial if state is None else float(state)

    def step(self, u):
        dy = min(max(u - self.y, -self.rate_dn * self.dt), self.rate_up * self.dt)
        self.y = self.y + dy
        return self.y
