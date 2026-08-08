"""오토파일럿 — 속도/고도/헤딩 PI + 1차 명령필터 + 선회 피드포워드 (01 §3.2).

전 축이 ScasAxis(PI+레이트 피드백+클램프+스텝 게인 덮어쓰기)를 재사용한다:
    속도: thr   = PI(V_ref − V)                     ∈ [0, 1]
    고도: θ_cmd = PI(h_ref − h) + k_hdot·ḣ          ∈ [theta_lo, theta_hi]
    헤딩: φ_cmd = P(wrap(ψ_ref − ψ))                ∈ [−phi_max, phi_max]
    선회 FF (01 §3.3.1 델타윙 고도손실 보상):
        θ_cmd += k_pitch_turn·(1/cosφ_cmd − 1),  thr += k_thr_turn·(1/cos²φ_cmd − 1)

명령필터 [기본값]: 1차, 활성 시작 시 현재 측정으로 시드(캡처 거동) — 급명령에
의한 타면 포화·과도 하중 방지. 비활성 축의 필터는 측정을 추적(reset_to)해
활성화 순간 현재값부터 램프한다. 축 비활성 시 오차 0 입력 → 적분기 유지
(트림 홀드), 헤딩 off는 φ_cmd = 0 (수평 유지).

기본 게인은 설계점 M0.6 h1000 fuel200 비선형 폐루프(SCAS 포함) 스캔으로 선정한
데모 설계값 [기본값] — 고도 +100 m 오버슈트 8.3%, 속도 +10 m/s 3.7%, 헤딩 0.5 rad
오버슈트 없음·고도 강하 1.1 m. 실기체 게인은 파라미터 계층(02 §5.5)에서 관리.
"""

import math

import numpy as np

from claw.blocks.base import Block
from claw.common.attitude import quat_to_euler, wrap_pi
from claw.fcl.scas import ScasAxis
from claw.params.param import ParamDef


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


class Autopilot(Block):
    NAME = "Autopilot"
    PARAM_DEFS = (
        ParamDef("kp_spd", 0.15, "s/m", "속도 비례 게인"),
        ParamDef("ki_spd", 0.03, "1/m", "속도 적분 게인"),
        ParamDef("tau_spd", 2.0, "s", "속도 명령필터 시정수", lo=0.0),
        ParamDef("kp_alt", 0.004, "rad/m", "고도 비례 게인"),
        ParamDef("ki_alt", 0.0004, "rad/(m·s)", "고도 적분 게인"),
        ParamDef("k_hdot", -0.008, "rad·s/m", "승강률 댐핑 게인"),
        ParamDef("tau_alt", 5.0, "s", "고도 명령필터 시정수", lo=0.0),
        ParamDef("kp_hdg", 4.0, "-", "헤딩 비례 게인"),
        ParamDef("ki_hdg", 0.0, "1/s", "헤딩 적분 게인"),
        ParamDef("tau_hdg", 1.0, "s", "헤딩 명령필터 시정수", lo=0.0),
        ParamDef("theta_lo", -0.3, "rad", "피치 명령 하한"),
        ParamDef("theta_hi", 0.3, "rad", "피치 명령 상한"),
        ParamDef("phi_max", 0.7, "rad", "뱅크 명령 한계", lo=0.0),
        ParamDef("k_pitch_turn", 0.05, "rad", "선회 피치 FF 계수 (1/cosφ−1 배)"),
        ParamDef("k_thr_turn", 0.0, "-", "선회 스로틀 FF 계수 (1/cos²φ−1 배)"),
    )

    def __init__(
        self,
        kp_spd: float = 0.15,
        ki_spd: float = 0.03,
        tau_spd: float = 2.0,
        kp_alt: float = 0.004,
        ki_alt: float = 0.0004,
        k_hdot: float = -0.008,
        tau_alt: float = 5.0,
        kp_hdg: float = 4.0,
        ki_hdg: float = 0.0,
        tau_hdg: float = 1.0,
        theta_lo: float = -0.3,
        theta_hi: float = 0.3,
        phi_max: float = 0.7,
        k_pitch_turn: float = 0.05,
        k_thr_turn: float = 0.0,
    ):
        if theta_lo > theta_hi:
            raise ValueError(f"theta_lo({theta_lo}) > theta_hi({theta_hi})")
        if phi_max < 0:
            raise ValueError(f"phi_max는 음수 불가: {phi_max}")
        self.theta_lo, self.theta_hi, self.phi_max = theta_lo, theta_hi, phi_max
        self.k_pitch_turn, self.k_thr_turn = k_pitch_turn, k_thr_turn
        self._spd = ScasAxis(kp=kp_spd, ki=ki_spd, out_lo=0.0, out_hi=1.0)
        self._alt = ScasAxis(kp=kp_alt, ki=ki_alt, k_rate=k_hdot, out_lo=theta_lo, out_hi=theta_hi)
        self._hdg = ScasAxis(kp=kp_hdg, ki=ki_hdg, out_lo=-phi_max, out_hi=phi_max)
        self._fv = CommandFilter(tau_spd)
        self._fh = CommandFilter(tau_alt)
        self._fpsi = CommandFilter(tau_hdg, angle=True)

    def _discretize(self, dt: float) -> None:
        for child in (self._spd, self._alt, self._hdg, self._fv, self._fh, self._fpsi):
            child.init(dt)

    def reset(self, state=None) -> None:
        """state={"throttle": thr0, "theta": θ0} — 트림 웜스타트 (캡처 시 범프리스)."""
        for child in (self._spd, self._alt, self._hdg, self._fv, self._fh, self._fpsi):
            child.reset()
        if state:
            if "throttle" in state:
                self._spd.reset(float(state["throttle"]))
            if "theta" in state:
                self._alt.reset(float(state["theta"]))

    def step(self, cmd, nav, gains=None):
        """(GuidanceCommand, NavOutput) → (θ_cmd, φ_cmd, thr 집합 0~1).

        gains={"speed": {...}, "alt": {...}, "heading": {...}} 스텝별 덮어쓰기
        — 게인 스케줄(01 §3.4) 주입 경로. 차동추력 배분은 믹서 소관.
        """
        V = float(np.linalg.norm(nav.vel_n))  # 바람 0 가정: 대기속도 = 관성속도
        h, hdot = -float(nav.pos_n[2]), -float(nav.vel_n[2])
        _phi, _theta, psi = quat_to_euler(nav.q_nb)
        g = gains or {}

        if cmd.heading_on:
            psi_ref = self._fpsi.step(cmd.heading, psi)
            phi_cmd = self._hdg.step(float(wrap_pi(psi_ref - psi)), 0.0, **g.get("heading", {}))
        else:
            self._fpsi.reset_to(psi)
            phi_cmd = 0.0

        if cmd.alt_on:
            h_ref = self._fh.step(cmd.alt, h)
            theta_cmd = self._alt.step(h_ref - h, hdot, **g.get("alt", {}))
        else:
            self._fh.reset_to(h)
            theta_cmd = self._alt.step(0.0, 0.0)  # 적분기 유지 = 트림 θ 홀드
        theta_cmd = theta_cmd + self.k_pitch_turn * (1.0 / math.cos(phi_cmd) - 1.0)
        theta_cmd = min(max(theta_cmd, self.theta_lo), self.theta_hi)

        if cmd.speed_on:
            v_ref = self._fv.step(cmd.speed, V)
            thr = self._spd.step(v_ref - V, 0.0, **g.get("speed", {}))
        else:
            self._fv.reset_to(V)
            thr = self._spd.step(0.0, 0.0)  # 적분기 유지 = 트림 스로틀 홀드
        thr = thr + self.k_thr_turn * (1.0 / math.cos(phi_cmd) ** 2 - 1.0)
        return theta_cmd, phi_cmd, min(max(thr, 0.0), 1.0)
