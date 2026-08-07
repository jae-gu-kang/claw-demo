"""제어기 블록 — PID (게인 스케줄 가능, 클램프 안티와인드업) (구현 문서 §2.2).

병렬형 y = kp·e + I + kd·(e - e_prev)/dt. 적분은 Integrator 기본과 동일한
forward Euler(출력 계산 후 I ← clip(I + dt·ki·e)) — 상수 오차 e에서
y_k = kp·e + ki·e·k·dt 의 정확 수열.

게인 스케줄: step(e, kp=, ki=, kd=) 덮어쓰기 — M7 fcl이 게인 테이블(M3) 조회값을
스텝마다 주입하는 방식으로 "게인 스케줄 가능 PID" 요구를 충족한다.
미분항은 비필터링 — 필터 필요 시 Lag와 조합 (미분 필터 tau_d는 백로그).
"""

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
