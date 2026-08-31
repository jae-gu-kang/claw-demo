"""선형 필터 블록 — Lag, LowPass, Washout, LeadLag(ZOH-정확), Notch(Tustin+프리워핑),
CommandFilter(명령 램프).

1차 블록은 스텝 불변(ZOH-정확) 이산화: p = e^(-dt/tau). ZOH 입력 가정에서 표본점
출력이 연속 해석해와 기계정밀도로 일치 — 해석해 대조 완료 기준을 허용오차 없이
만족하고 Simulink(연속 블록 + ZOH 입력) 회귀 대조에도 유리하다.
노치는 RBJ biquad(=Tustin+프리워핑과 동치)로 중심주파수가 정확히 f0에 유지된다.

샘플 규약: step(u_k)의 반환은 t_k = k·dt 시점 출력 (내부 lag 상태는 호출 후 갱신,
직달항 없는 Lag는 현재 입력에 무의존 — 연속계와 동일한 인과성).
"""

import math
from collections import deque

from claw.blocks.base import Block
from claw.common.attitude import wrap_pi
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


class MovingAverage(Block):
    """이동평균 — 최근 n 샘플의 산술평균 (초기 버퍼는 0으로 채움)."""

    NAME = "MovingAverage"
    PARAM_DEFS = (ParamDef("n", 5, "-", "윈도우 길이(샘플수)", lo=1, hi=100000),)

    def __init__(self, n: int = 5):
        if int(n) != n or n < 1:
            raise ValueError(f"n은 1 이상의 정수여야 함: {n}")
        self.n = int(n)

    def reset(self, state=None) -> None:
        if state is None:
            self._buf = deque([0.0] * self.n, maxlen=self.n)
            return
        buf = [float(v) for v in state]  # deque(maxlen)은 초과분을 조용히 버리므로 길이 검사 먼저
        if len(buf) != self.n:
            raise ValueError(f"웜스타트 버퍼 길이 불일치: {len(buf)} != {self.n}")
        self._buf = deque(buf, maxlen=self.n)

    def step(self, u):
        self._buf.append(u)
        return sum(self._buf) / self.n


class IIRFilter(Block):
    """일반 이산 필터 y = (b0 + b1·z⁻¹ + …)/(1 + a1·z⁻¹ + …) — FIR/IIR/Discrete Filter 포괄.

    이산 계수 (b, a)를 직접 지정 — 연속 설계의 이산화가 아니라 계수 자체가 규격인
    경우(비행SW 이식 필터 등)를 위한 블록. FIR은 a=(1,)인 특수 사례. a[0]으로 정규화.
    Direct Form II Transposed 임의 차수 — Notch와 동일한 구조로 C++ 이식 대응.
    """

    NAME = "IIRFilter"

    def __init__(self, b=(1.0,), a=(1.0,)):
        b, a = tuple(float(v) for v in b), tuple(float(v) for v in a)
        if not b or not a:
            raise ValueError("b, a는 비어 있을 수 없음")
        if a[0] == 0.0:
            raise ValueError("a[0]은 0일 수 없음 (정규화 기준 계수)")
        norder = max(len(b), len(a)) - 1
        self.b = tuple(v / a[0] for v in b) + (0.0,) * (norder + 1 - len(b))
        self.a = tuple(v / a[0] for v in a) + (0.0,) * (norder + 1 - len(a))
        self.norder = norder

    def reset(self, state=None) -> None:
        if state is None:
            self._z = [0.0] * self.norder
            return
        z = [float(v) for v in state]
        if len(z) != self.norder:
            raise ValueError(f"웜스타트 상태 길이 불일치: {len(z)} != {self.norder}")
        self._z = z

    def step(self, u):
        if self.norder == 0:
            return self.b[0] * u
        y = self.b[0] * u + self._z[0]
        for i in range(self.norder - 1):
            self._z[i] = self.b[i + 1] * u + self._z[i + 1] - self.a[i + 1] * y
        self._z[self.norder - 1] = self.b[self.norder] * u - self.a[self.norder] * y
        return y


class CommandFilter(Block):
    """1차 명령필터 — step(cmd, current): 미시드 상태면 current에서 시작.

    angle=True면 wrap 보간(최단 경로)으로 ±π 경계를 안전하게 통과한다.
    tau=0은 필터 통과(즉시 명령).
    """

    NAME = "CommandFilter"
    PARAM_DEFS = (
        ParamDef("tau", 1.0, "s", "시정수 (0=통과)", lo=0.0),
        ParamDef("angle", False, "-", "각도(wrap) 모드"),
    )

    def __init__(self, tau: float = 1.0, angle: bool = False):
        if tau < 0:
            raise ValueError(f"tau는 음수 불가: {tau}")
        self.tau = tau
        self.angle = angle

    def _discretize(self, dt: float) -> None:
        self._p = math.exp(-dt / self.tau) if self.tau > 0 else 0.0

    def reset(self, state=None) -> None:
        """state=필터 상태 웜스타트. None이면 미시드 — 첫 step의 current로 시드."""
        self._x = None if state is None else float(state)

    def reset_to(self, value) -> None:
        """현재 측정으로 재시드 — 비활성 축 추적용."""
        self._x = float(value)

    def step(self, cmd, current):
        if self._x is None:
            self._x = float(current)
        d = wrap_pi(cmd - self._x) if self.angle else (cmd - self._x)
        self._x = self._x + (1.0 - self._p) * float(d)
        if self.angle:
            self._x = float(wrap_pi(self._x))
        return self._x


# 레이트 피드백 경로에 놓을 수 있는 필터의 **정본 목록** — 해석(analysis.margins)과
# 향후 법칙 그래프(fcl.graphs)가 같은 표를 읽는다. 목록이 두 곳에 적히면 그 순간
# 어긋난다 (codegen/blockspec.py 머리말과 같은 원칙).
#
# "none"은 값이 None이다 — 자리는 있는데 필터가 없는 상태를 이름으로 표현한다
# (washout_tau == 0으로 부재를 표현하던 기존 관용과 달리, 종류가 여럿이면
# 부재도 하나의 선택지여야 한다).
RATE_FILTERS = {
    "none": None,
    "washout": Washout,
    "lowpass": LowPass,
    "notch": Notch,
}


def rate_filter_tau(spec) -> float:
    """1차 레이트 필터 스펙 → 시정수 [s] — 해석 두 경로가 공유하는 환산의 정본.

    파라미터 이름·단위는 각 블록 PARAM_DEFS 그대로다: washout `tau`[s],
    lowpass `fc`[Hz]. fc → tau 환산은 LowPass가 Lag에 넘기는 것과 **같은 식**이고
    (아래 클래스 정의), 그것을 마진(analysis.margins)과 레이트 지표(design.closure)가
    각자 적으면 한쪽만 고쳐진 날 두 해석이 다른 필터를 보게 된다.

    1차가 아닌 종류(notch)는 시정수로 기술되지 않으므로 거부한다.
    """
    kind = spec["kind"]
    if kind == "washout":
        tau = float(spec["tau"])
    elif kind == "lowpass":
        fc = float(spec["fc"])
        # 나눗셈 **전에** 본다 — 0/음수/nan을 그대로 넣으면 ZeroDivisionError나
        # 조용한 inf 시정수가 되어, 이 모듈이 잘못된 입력에 내기로 한 ValueError
        # 계약(같은 파일 다른 블록들의 생성자 검증과 같은 규약)이 깨진다
        if not fc > 0.0:
            raise ValueError(f"저역통과 fc는 양수여야 함 [Hz]: {fc}")
        tau = 1.0 / (2.0 * math.pi * fc)
    else:
        raise ValueError(f"1차 필터가 아니라 시정수가 없다: {kind!r}")
    if not tau > 0.0:
        raise ValueError(f"필터 시정수는 양수여야 함: {kind} {spec}")
    return tau
