"""항법 등가 오차 모델 (구현 문서 §3.1) — EKF 미구현 [확정].

항법 출력 = 참값(6DOF) + 오차(백색잡음 + 1차 마르코프 바이어스) + 지연, 갱신주기 반영:
    측정 = truth + bias(1차 마르코프, 위치축) + 백색잡음 (위치/속도/자세/각속도)
    자세 오차는 소각 오차 쿼터니언 δq를 동체측에 곱해 반영 (단위 노름 유지)
    갱신주기(update_hz)마다 새 측정 생성, 사이에는 홀드 (멀티레이트 전제, 01 §2.5)
    지연(delay_s)만큼 릴리스를 늦춤 — t_meas는 측정 시각, t는 출력 시각

**위치·속도 오차는 수평(N·E)과 수직(D)을 분리한다.** GNSS는 수신기 아래쪽
위성이 없어 수직 기하가 나쁘고(VDOP > HDOP), 기압고도 보정도 별도 드리프트원을
갖는다. 등방(3축 동일) 가정은 수직 채널을 실제보다 후하게 모사해 저고도 임무의
고도 마진을 낙관적으로 보이게 한다 — 오토파일럿 고도 루프가 nav.pos_n[2]와
nav.vel_n[2]를 직접 소비하므로(fcl.autopilot) 그 오차가 곧 고도 오차다.

초기값은 GPS/INS 일반 수준 자리표시자 [기본값] — 항법팀 자료 확보 시 대체 [TBD].
수직 기본값은 수평 × 1.5 (VDOP/HDOP 통상비)로 둔 파생 자리표시자이며, 실측
자료가 아니다. 난수는 seed 고정 결정적 (몬테카를로 재현성).
"""

import math
from collections import deque

import numpy as np

from claw.common.attitude import quat_multiply, quat_normalize
from claw.common.contracts import NavOutput
from claw.params.param import ParamDef


# RTK 고정해 등급 파라미터 [기본값] — NavErrorModel.rtk_fixed()가 쓰는 값.
# 수직을 수평의 1.5배로 두는 관계는 기본값과 같다(VDOP/HDOP 통상비). 자세·각속도·
# 지연·갱신주기는 손대지 않는다 — RTK가 개선하는 것은 측위이지 자세가 아니다.
# 수치는 RTK 고정해 일반 수준 자리표시자이며 실측 자료가 아니다 [TBD].
RTK_FIXED = {
    "pos_std_h": 0.02,
    "pos_std_v": 0.03,
    "vel_std_h": 0.02,
    "vel_std_v": 0.03,
    "bias_std_h": 0.01,
    "bias_std_v": 0.015,
}


class NavErrorModel:
    NAME = "ErrorModel"
    PARAM_DEFS = (
        ParamDef("pos_std_h", 3.0, "m", "수평 위치 백색잡음 표준편차", lo=0.0),
        ParamDef("pos_std_v", 4.5, "m", "수직 위치 백색잡음 표준편차(수평보다 큼)", lo=0.0),
        ParamDef("vel_std_h", 0.3, "m/s", "수평 속도 백색잡음 표준편차", lo=0.0),
        ParamDef("vel_std_v", 0.45, "m/s", "수직 속도 백색잡음 표준편차(수평보다 큼)", lo=0.0),
        ParamDef("att_std", 0.002, "rad", "롤·피치 백색잡음 표준편차", lo=0.0),
        ParamDef("psi_std", 0.005, "rad", "방위 백색잡음 표준편차(롤·피치보다 큼)", lo=0.0),
        ParamDef("rate_std", 0.001, "rad/s", "각속도 백색잡음 표준편차", lo=0.0),
        ParamDef("bias_std_h", 1.0, "m", "수평 위치 마르코프 바이어스 정상 표준편차", lo=0.0),
        ParamDef("bias_std_v", 1.5, "m", "수직 위치 마르코프 바이어스 정상 표준편차", lo=0.0),
        ParamDef("bias_tau", 60.0, "s", "바이어스 상관시간", lo=1e-9),
        ParamDef("delay_s", 0.03, "s", "항법 출력 지연", lo=0.0),
        ParamDef("update_hz", 100.0, "Hz", "항법해 갱신주기", lo=1e-9),
        ParamDef("seed", 0, "-", "난수 시드", lo=0),
    )

    def __init__(
        self,
        pos_std_h: float = 3.0,
        pos_std_v: float = 4.5,
        vel_std_h: float = 0.3,
        vel_std_v: float = 0.45,
        att_std: float = 0.002,
        psi_std: float = 0.005,
        rate_std: float = 0.001,
        bias_std_h: float = 1.0,
        bias_std_v: float = 1.5,
        bias_tau: float = 60.0,
        delay_s: float = 0.03,
        update_hz: float = 100.0,
        seed: int = 0,
    ):
        if min(pos_std_h, pos_std_v, vel_std_h, vel_std_v, att_std, psi_std,
               rate_std, bias_std_h, bias_std_v, delay_s) < 0:
            raise ValueError("오차 표준편차·지연은 음수 불가")
        if bias_tau <= 0 or update_hz <= 0:
            raise ValueError(f"bias_tau({bias_tau})·update_hz({update_hz})는 양수여야 함")
        self.pos_std_h, self.pos_std_v = pos_std_h, pos_std_v
        self.vel_std_h, self.vel_std_v = vel_std_h, vel_std_v
        self.att_std, self.psi_std, self.rate_std = att_std, psi_std, rate_std
        self.bias_std_h, self.bias_std_v = bias_std_h, bias_std_v
        self.bias_tau = bias_tau
        # NED 축별 σ — 수평 2축(N·E) + 수직 1축(D). 갱신마다 재구성하지 않도록 선계산
        self._sigma_pos = np.array([pos_std_h, pos_std_h, pos_std_v])
        self._sigma_vel = np.array([vel_std_h, vel_std_h, vel_std_v])
        self._sigma_bias = np.array([bias_std_h, bias_std_h, bias_std_v])
        self.delay_s, self.update_hz, self.seed = delay_s, update_hz, int(seed)

    @classmethod
    def rtk_fixed(cls, **overrides) -> "NavErrorModel":
        """RTK 고정해 등급 항법 [기본값] — 위치·속도 오차만 낮춘다.

        **왜 필요한가 — 접지 지점의 반복성이다.** 처음에는 "기본 항법의 수직 오차가
        플레어 개시 고도보다 커서 플레어가 잡음에 묻힌다"로 적었는데, 5시드 실측이
        그것을 뒤집었다: 접지 강하율은 기본 −0.72 m/s·RTK −0.89 m/s로 오히려 기본
        쪽이 살짝 부드럽고 산포도 σ 0.07로 같다. 강하율은 vel_std_v(0.45 m/s)가
        지배하고, 플레어 개시 고도가 20 m라 4.5 m짜리 위치 잡음이 그 자릿수를
        흔들지 못하기 때문이다.

        갈리는 것은 **어디에 내리는가**다. 플레어 개시가 고도 조건이므로 고도 오차가
        곧 개시 시점 오차이고, 접근 속도 88 m/s가 그것을 접지 지점으로 증폭한다:

            기본 GNSS   접지 지점 폭 874 m (σ 344 m)
            RTK 고정해  접지 지점 폭  92 m (σ  33 m)

        활주로가 1,500 m인데 ±437 m가 흔들리면 활주로에 못 내린다.
        (문서 01 §2.5의 RALT [TBD]도 같은 문제를 다른 수단으로 푸는 자리다.)

        자세·각속도 오차는 **그대로 둔다**: RTK가 개선하는 것은 반송파 위상 기반
        측위이지 자세가 아니다(2안테나 자세 결정은 별개 장비 [TBD]). 낮춰 두면
        착륙 성능이 실제보다 좋게 나온다.

        **가정 — fix 상실은 미모델이다 [TBD].** 실제 RTK는 기준국 보정 링크가 끊기거나
        가시위성이 줄면 float·단독으로 강등되고 오차가 수십 배로 뛴다. 이 모델에는
        그 상태 전이가 없으므로 **fix 유지가 전제**다. 접지 지점 정확도가 통째로 이
        전제에 걸려 있으니 화면·문서에 함께 적는다 (조용한 전제 금지). 강등되면
        위 표의 "기본 GNSS" 쪽으로 되돌아간다 — 착륙 자체는 하되 지점이 흩어진다.
        """
        return cls(**{**RTK_FIXED, **overrides})

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
        self._q_bias = self._sigma_bias * math.sqrt(1.0 - self._p_bias**2)

    def _measure(self, state):
        rng = self._rng
        self._bias = self._p_bias * self._bias + self._q_bias * rng.standard_normal(3)
        pos = state.pos_n + self._bias + self._sigma_pos * rng.standard_normal(3)
        vel = state.vel_n() + self._sigma_vel * rng.standard_normal(3)
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
