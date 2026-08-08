"""항법 등가 오차 모델 (구현 문서 §3.1) — EKF 미구현 [확정].

항법 출력 = 참값(6DOF) + 오차(백색잡음 + 1차 마르코프 바이어스) + 지연, 갱신주기 반영:
    측정 = truth + bias(1차 마르코프, 위치축) + 백색잡음 (위치/속도/자세/각속도)
    자세 오차는 소각 오차 쿼터니언 δq를 동체측에 곱해 반영 (단위 노름 유지)
    갱신주기(update_hz)마다 새 측정 생성, 사이에는 홀드 (멀티레이트 전제, 01 §2.5)
    지연(delay_s)만큼 릴리스를 늦춤 — t_meas는 측정 시각, t는 출력 시각
초기값은 GPS/INS 일반 수준 자리표시자 [기본값] — 항법팀 자료 확보 시 대체 [TBD].
난수는 seed 고정 결정적 (몬테카를로 재현성).
"""

import math
from collections import deque

import numpy as np

from claw.common.attitude import quat_multiply, quat_normalize
from claw.common.contracts import NavOutput
from claw.params.param import ParamDef


class NavErrorModel:
    NAME = "ErrorModel"
    PARAM_DEFS = (
        ParamDef("pos_std", 3.0, "m", "위치 백색잡음 표준편차", lo=0.0),
        ParamDef("vel_std", 0.3, "m/s", "속도 백색잡음 표준편차", lo=0.0),
        ParamDef("att_std", 0.002, "rad", "롤·피치 백색잡음 표준편차", lo=0.0),
        ParamDef("psi_std", 0.005, "rad", "방위 백색잡음 표준편차(롤·피치보다 큼)", lo=0.0),
        ParamDef("rate_std", 0.001, "rad/s", "각속도 백색잡음 표준편차", lo=0.0),
        ParamDef("bias_std", 1.0, "m", "위치 마르코프 바이어스 정상 표준편차", lo=0.0),
        ParamDef("bias_tau", 60.0, "s", "바이어스 상관시간", lo=1e-9),
        ParamDef("delay_s", 0.03, "s", "항법 출력 지연", lo=0.0),
        ParamDef("update_hz", 100.0, "Hz", "항법해 갱신주기", lo=1e-9),
        ParamDef("seed", 0, "-", "난수 시드", lo=0),
    )

    def __init__(
        self,
        pos_std: float = 3.0,
        vel_std: float = 0.3,
        att_std: float = 0.002,
        psi_std: float = 0.005,
        rate_std: float = 0.001,
        bias_std: float = 1.0,
        bias_tau: float = 60.0,
        delay_s: float = 0.03,
        update_hz: float = 100.0,
        seed: int = 0,
    ):
        if min(pos_std, vel_std, att_std, psi_std, rate_std, bias_std, delay_s) < 0:
            raise ValueError("오차 표준편차·지연은 음수 불가")
        if bias_tau <= 0 or update_hz <= 0:
            raise ValueError(f"bias_tau({bias_tau})·update_hz({update_hz})는 양수여야 함")
        self.pos_std, self.vel_std = pos_std, vel_std
        self.att_std, self.psi_std, self.rate_std = att_std, psi_std, rate_std
        self.bias_std, self.bias_tau = bias_std, bias_tau
        self.delay_s, self.update_hz, self.seed = delay_s, update_hz, int(seed)

    def init(self, dt: float) -> "NavErrorModel":
        """틱 주기 dt[s] (제어/시뮬 주기)로 초기화. 체이닝을 위해 self 반환."""
        if dt <= 0:
            raise ValueError(f"dt는 양수여야 함: {dt}")
        self.dt = dt
        ratio = 1.0 / (self.update_hz * dt)
        if ratio < 1.0 - 1e-9:
            self._n_up = 1  # 항법이 틱보다 빠름 → 틱 주기가 상한 (틱마다 새 측정)
        else:
            n = round(ratio)
            if abs(ratio - n) > 1e-6:
                raise ValueError(
                    f"항법 갱신주기는 틱 주기의 정수배여야 함: 1/(update_hz·dt) = {ratio:.4f}"
                )
            self._n_up = n
        self.reset()
        return self

    def reset(self, state=None) -> None:
        self._rng = np.random.default_rng(self.seed)
        self._bias = np.zeros(3)
        self._pending = deque()
        self._last = None
        self._tick = 0
        t_up = self._n_up * self.dt
        self._p_bias = math.exp(-t_up / self.bias_tau)
        self._q_bias = self.bias_std * math.sqrt(1.0 - self._p_bias**2)

    def _measure(self, state):
        rng = self._rng
        self._bias = self._p_bias * self._bias + self._q_bias * rng.standard_normal(3)
        pos = state.pos_n + self._bias + self.pos_std * rng.standard_normal(3)
        vel = state.vel_n() + self.vel_std * rng.standard_normal(3)
        eps = np.array([self.att_std, self.att_std, self.psi_std]) * rng.standard_normal(3)
        dq = quat_normalize(np.array([1.0, 0.5 * eps[0], 0.5 * eps[1], 0.5 * eps[2]]))
        q = quat_normalize(quat_multiply(state.q_nb, dq))
        omega = state.omega_b + self.rate_std * rng.standard_normal(3)
        return NavOutput(
            t=state.t, pos_n=pos, vel_n=vel, q_nb=q, omega_b=omega,
            t_meas=state.t, valid=True, fuel=state.fuel,  # 연료 게이지 참값 통과
        )

    def step(self, state):
        """플랜트 참값(VehicleState) → NavOutput. 매 틱 호출 (state.t 단조 증가 전제)."""
        if self._tick % self._n_up == 0:
            self._pending.append(self._measure(state))
        self._tick += 1
        while self._pending and self._pending[0].t_meas <= state.t - self.delay_s + 1e-12:
            self._last = self._pending.popleft()
        if self._last is None:
            return NavOutput(t=state.t, valid=False)
        m = self._last  # 배열 복사 릴리스 — 소비자 훼손이 보관 측정치를 오염시키지 않도록
        return NavOutput(
            t=state.t,
            pos_n=m.pos_n.copy(),
            vel_n=m.vel_n.copy(),
            q_nb=m.q_nb.copy(),
            omega_b=m.omega_b.copy(),
            t_meas=m.t_meas,
            valid=m.valid,
            fuel=m.fuel,
        )
