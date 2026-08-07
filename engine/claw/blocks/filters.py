"""선형 필터 블록 — Lag, LowPass, Washout, LeadLag(ZOH-정확), Notch(Tustin+프리워핑).

1차 블록은 스텝 불변(ZOH-정확) 이산화: p = e^(-dt/tau). ZOH 입력 가정에서 표본점
출력이 연속 해석해와 기계정밀도로 일치 — 해석해 대조 완료 기준을 허용오차 없이
만족하고 Simulink(연속 블록 + ZOH 입력) 회귀 대조에도 유리하다.
노치는 RBJ biquad(=Tustin+프리워핑과 동치)로 중심주파수가 정확히 f0에 유지된다.

샘플 규약: step(u_k)의 반환은 t_k = k·dt 시점 출력 (내부 lag 상태는 호출 후 갱신,
직달항 없는 Lag는 현재 입력에 무의존 — 연속계와 동일한 인과성).
"""

import math

from claw.blocks.base import Block
from claw.params.param import ParamDef


class Lag(Block):
    """1차 지연 1/(tau·s+1)."""

    NAME = "Lag"
    PARAM_DEFS = (ParamDef("tau", 0.1, "s", "시정수", lo=1e-9),)

    def __init__(self, tau: float = 0.1):
        if tau <= 0:
            raise ValueError(f"tau는 양수여야 함: {tau}")
        self.tau = tau

    def _discretize(self, dt: float) -> None:
        self._p = math.exp(-dt / self.tau)

    def reset(self, state=None) -> None:
        self._x = 0.0 if state is None else float(state)

    def step(self, u):
        y = self._x
        self._x = self._p * self._x + (1.0 - self._p) * u
        return y


class LowPass(Lag):
    """1차 저역통과 — 차단주파수 fc[Hz] 지정 (tau = 1/(2π·fc)인 Lag)."""

    NAME = "LowPass"
    PARAM_DEFS = (ParamDef("fc", 1.0, "Hz", "차단주파수", lo=1e-9),)

    def __init__(self, fc: float = 1.0):
        if fc <= 0:
            raise ValueError(f"fc는 양수여야 함: {fc}")
        self.fc = fc
        super().__init__(tau=1.0 / (2.0 * math.pi * fc))


class Washout(Block):
    """워시아웃(HPF) tau·s/(tau·s+1) — 정상상태 신호 제거 (SCAS 러더 채널, 01 §3.1)."""

    NAME = "Washout"
    PARAM_DEFS = (ParamDef("tau", 0.1, "s", "시정수", lo=1e-9),)

    def __init__(self, tau: float = 0.1):
        if tau <= 0:
            raise ValueError(f"tau는 양수여야 함: {tau}")
        self.tau = tau

    def _discretize(self, dt: float) -> None:
        self._p = math.exp(-dt / self.tau)

    def reset(self, state=None) -> None:
        self._x = 0.0 if state is None else float(state)

    def step(self, u):
        y = u - self._x
        self._x = self._p * self._x + (1.0 - self._p) * u
        return y


class LeadLag(Block):
    """리드-래그 (t1·s+1)/(t2·s+1) = c + (1-c)/(t2·s+1), c = t1/t2."""

    NAME = "LeadLag"
    PARAM_DEFS = (
        ParamDef("t1", 0.1, "s", "분자(리드) 시정수", lo=1e-9),
        ParamDef("t2", 0.1, "s", "분모(래그) 시정수", lo=1e-9),
    )

    def __init__(self, t1: float = 0.1, t2: float = 0.1):
        if t1 <= 0 or t2 <= 0:
            raise ValueError(f"시정수는 양수여야 함: t1={t1}, t2={t2}")
        self.t1, self.t2 = t1, t2

    def _discretize(self, dt: float) -> None:
        self._p = math.exp(-dt / self.t2)
        self._c = self.t1 / self.t2

    def reset(self, state=None) -> None:
        self._x = 0.0 if state is None else float(state)

    def step(self, u):
        y = self._c * u + (1.0 - self._c) * self._x
        self._x = self._p * self._x + (1.0 - self._p) * u
        return y


class Notch(Block):
    """노치 필터 (RBJ biquad) — 중심주파수 f0[Hz]를 정확히 차단, DC 이득 1.

    순수 Tustin은 주파수 워핑으로 노치 중심이 밀리므로 프리워핑 동치인 RBJ
    계수를 사용한다. f0가 나이퀴스트(0.5/dt) 이상이면 init에서 ValueError.
    """

    NAME = "Notch"
    PARAM_DEFS = (
        ParamDef("f0", 5.0, "Hz", "노치 중심주파수", lo=1e-9),
        ParamDef("q", 2.0, "-", "Q 인자(대역폭 = f0/q)", lo=1e-9),
    )

    def __init__(self, f0: float = 5.0, q: float = 2.0):
        if f0 <= 0 or q <= 0:
            raise ValueError(f"f0, q는 양수여야 함: f0={f0}, q={q}")
        self.f0, self.q = f0, q

    def _discretize(self, dt: float) -> None:
        nyquist = 0.5 / dt
        if self.f0 >= nyquist:
            raise ValueError(f"노치 주파수 {self.f0} Hz는 나이퀴스트({nyquist} Hz) 미만이어야 함")
        w = 2.0 * math.pi * self.f0 * dt
        alpha = math.sin(w) / (2.0 * self.q)
        n = 1.0 / (1.0 + alpha)
        cw = math.cos(w)
        self.b = (n, -2.0 * n * cw, n)
        self.a = (-2.0 * n * cw, (1.0 - alpha) * n)

    def reset(self, state=None) -> None:
        if state is None:
            self._z1 = self._z2 = 0.0
        else:
            self._z1, self._z2 = float(state[0]), float(state[1])

    def step(self, u):
        # Direct Form II Transposed — 곱 5회, C++ 이식 그대로 대응 (실시간 친화)
        b0, b1, b2 = self.b
        a1, a2 = self.a
        y = b0 * u + self._z1
        self._z1 = b1 * u - a1 * y + self._z2
        self._z2 = b2 * u - a2 * y
        return y
