"""제어기 블록 — PID (게인 스케줄 가능, 클램프 안티와인드업), StateSpace, TransferFunction (구현 문서 §2.2).

병렬형 y = kp·e + I + kd·(e - e_prev)/dt. 적분은 Integrator 기본과 동일한
forward Euler(출력 계산 후 I ← clip(I + dt·ki·e)) — 상수 오차 e에서
y_k = kp·e + ki·e·k·dt 의 정확 수열.

게인 스케줄: step(e, kp=, ki=, kd=) 덮어쓰기 — M7 fcl이 게인 테이블(M3) 조회값을
스텝마다 주입하는 방식으로 "게인 스케줄 가능 PID" 요구를 충족한다.
미분항은 비필터링 — 필터 필요 시 Lag와 조합 (미분 필터 tau_d는 백로그).
"""

import numpy as np

from claw.blocks.base import UNBOUNDED, Block
from claw.params.param import ParamDef


class PID(Block):
    NAME = "PID"
    PARAM_DEFS = (
        ParamDef("kp", 1.0, "-", "비례 게인"),
        ParamDef("ki", 0.0, "-", "적분 게인"),
        ParamDef("kd", 0.0, "-", "미분 게인"),
        ParamDef("out_lo", -UNBOUNDED, "-", "출력 하한(안티와인드업 클램프)"),
        ParamDef("out_hi", UNBOUNDED, "-", "출력 상한(안티와인드업 클램프)"),
    )

    def __init__(
        self,
        kp: float = 1.0,
        ki: float = 0.0,
        kd: float = 0.0,
        out_lo: float = -UNBOUNDED,
        out_hi: float = UNBOUNDED,
    ):
        if out_lo > out_hi:
            raise ValueError(f"out_lo({out_lo}) > out_hi({out_hi})")
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_lo, self.out_hi = out_lo, out_hi

    def reset(self, state=None) -> None:
        """state는 적분기 웜스타트 값 (범프리스 전환 계약)."""
        self._i = 0.0 if state is None else float(state)
        self._e_prev = 0.0

    def step(self, e, kp=None, ki=None, kd=None):
        kp = self.kp if kp is None else kp
        ki = self.ki if ki is None else ki
        kd = self.kd if kd is None else kd
        d = (e - self._e_prev) / self.dt
        y = min(max(kp * e + self._i + kd * d, self.out_lo), self.out_hi)
        self._i = min(max(self._i + self.dt * ki * e, self.out_lo), self.out_hi)
        self._e_prev = e
        return y


class StateSpace(Block):
    """연속시간 상태공간 (A, B, C, D) — init(dt)에서 ZOH 이산화 (scipy는 이산화 시점에만
    사용, 매 스텝은 numpy 행렬곱만 — 실시간 친화).

    샘플 규약은 filters와 동일: y[k] = C·x[k] + D·u[k] — 직달항(D)이 없으면 현재
    입력에 무의존이라 Lag·Integrator(forward)와 표본점에서 기계정밀도로 일치한다.
    스칼라 입출력(SISO)이면 step은 float를 주고받는다.
    """

    NAME = "StateSpace"

    def __init__(self, A, B, C, D=None):
        self.A = np.atleast_2d(np.asarray(A, dtype=float))
        self.B = np.atleast_2d(np.asarray(B, dtype=float))
        self.C = np.atleast_2d(np.asarray(C, dtype=float))
        n = self.A.shape[0]
        if self.A.shape != (n, n):
            raise ValueError(f"A는 정방행렬이어야 함: {self.A.shape}")
        if self.B.shape[0] != n or self.C.shape[1] != n:
            raise ValueError(f"B({self.B.shape})·C({self.C.shape})가 A({self.A.shape})와 불일치")
        p, m = self.C.shape[0], self.B.shape[1]
        self.D = (
            np.zeros((p, m)) if D is None else np.atleast_2d(np.asarray(D, dtype=float))
        )
        if self.D.shape != (p, m):
            raise ValueError(f"D 형상 {self.D.shape} != ({p}, {m})")
        self._siso = p == 1 and m == 1

    def _discretize(self, dt: float) -> None:
        from scipy.signal import cont2discrete

        Ad, Bd, _, _, _ = cont2discrete((self.A, self.B, self.C, self.D), dt, method="zoh")
        self.Ad, self.Bd = Ad, Bd

    def reset(self, state=None) -> None:
        n = self.A.shape[0]
        if state is None:
            self.x = np.zeros(n)
            return
        x = np.asarray(state, dtype=float).ravel()
        if x.size != n:
            raise ValueError(f"웜스타트 상태 길이 불일치: {x.size} != {n}")
        self.x = x

    def step(self, u):
        u = np.atleast_1d(np.asarray(u, dtype=float))
        y = self.C @ self.x + self.D @ u
        self.x = self.Ad @ self.x + self.Bd @ u
        return float(y[0]) if self._siso else y


class TransferFunction(StateSpace):
    """연속시간 전달함수 num(s)/den(s) — 상태공간 실현 후 StateSpace와 동일하게 ZOH 이산화.

    프로퍼(deg num ≤ deg den)만 허용. 예: TransferFunction([1], [tau, 1])은 Lag(tau)와
    표본점에서 기계정밀도로 일치한다.
    """

    NAME = "TransferFunction"

    def __init__(self, num, den):
        from scipy.signal import tf2ss

        num = [float(v) for v in num]
        den = [float(v) for v in den]
        if len(num) > len(den):
            raise ValueError(f"비프로퍼 전달함수: deg num({len(num) - 1}) > deg den({len(den) - 1})")
        A, B, C, D = tf2ss(num, den)
        super().__init__(A, B, C, D)
        self.num, self.den = num, den
