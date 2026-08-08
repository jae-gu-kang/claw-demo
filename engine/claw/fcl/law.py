"""M7 최상위 조립 — step(GuidanceCommand, NavOutput) → SurfaceCommand.

흐름 (01 §3 고정 아키텍처):
    게인 스케줄(옵션) → 오토파일럿 → α 리미터(옵션) → SCAS → 믹서

- nav.valid=False → 마지막 유효 SurfaceCommand 유지 [기본값]. 첫 유효 이전엔
  reset() 웜스타트로 구성한 홀드 명령 (트림 타면·스로틀)
- 멀티레이트: 항법 갱신이 제어주기보다 느려도 매 제어 틱 호출 — 측정 홀드는
  nav 모듈(02 §3.1) 소관, 법칙은 항상 최신 NavOutput만 소비
- 스케줄 mach는 항법 고도의 ISA 음속으로 산출 — M4 env 소비 (L3→L1 계층 규칙 내,
  03 M7 의존 M0~M4)
- 로깅 속성(스텝 후 갱신): alpha_margin(실속 마진 α_max−α, 리미터 없으면 None),
  limiter_active — 엔벨로프 감시(02 §6.1)가 소비
"""

import numpy as np

from claw.common.contracts import SurfaceCommand
from claw.env import isa_atmosphere
from claw.fcl.airdata import airdata_from_nav

_SCAS_GROUPS = ("pitch", "roll", "yaw")
_AP_GROUPS = ("speed", "alt", "heading")
_H_VALID = (-5000.0, 20000.0)  # ISA 유효범위 (env.constants) — mach 산출용 클램프


class FlightControlLaw:
    def __init__(self, scas, autopilot, mixer, schedule=None, alpha_limiter=None):
        self.scas = scas
        self.autopilot = autopilot
        self.mixer = mixer
        self.schedule = schedule
        self.alpha_limiter = alpha_limiter
        self.alpha_margin = None
        self.limiter_active = False

    def init(self, dt: float) -> "FlightControlLaw":
        self.dt = dt
        self.scas.init(dt)
        self.autopilot.init(dt)
        self.mixer.init(dt)
        if self.schedule is not None:
            self.schedule.init(dt)
        self.reset()
        return self

    def reset(self, state=None) -> None:
        """state={"theta": θ0, "throttle": thr0, "de": de0} — 트림 웜스타트.

        SCAS 피치 적분기=de0, AP 고도 적분기=θ0·속도 적분기=thr0. 홀드 명령도
        웜스타트 값으로 재구성 (첫 유효 항법 이전의 출력).
        """
        st = state or {}
        de0 = float(st.get("de", 0.0))
        thr0 = float(st.get("throttle", 0.0))
        self.scas.reset()
        self.scas.pitch.reset(de0)
        self.autopilot.reset(state=st)
        if self.schedule is not None:
            self.schedule.reset()
        self.alpha_margin = None
        self.limiter_active = False
        self._hold = self.mixer.step(de0, 0.0, 0.0, thr0)

    def _hold_copy(self) -> SurfaceCommand:
        h = self._hold
        return SurfaceCommand(
            elevon=h.elevon.copy(), rudder=h.rudder, throttle=h.throttle.copy()
        )

    def step(self, cmd, nav) -> SurfaceCommand:
        if not nav.valid:
            return self._hold_copy()

        V, _alpha, _beta = airdata_from_nav(nav)
        h = -float(nav.pos_n[2])
        h_isa = min(max(h, _H_VALID[0]), _H_VALID[1])
        mach = V / isa_atmosphere(h_isa).a

        gains = None
        if self.schedule is not None:
            gains = self.schedule.step(mach, h, nav.fuel)

        ap_gains = {k: gains[k] for k in _AP_GROUPS if k in gains} if gains else None
        theta_cmd, phi_cmd, thr = self.autopilot.step(cmd, nav, gains=ap_gains)

        if self.alpha_limiter is not None:
            theta_cmd, self.limiter_active, self.alpha_margin = self.alpha_limiter.step(
                theta_cmd, nav, mach
            )

        scas_gains = {k: gains[k] for k in _SCAS_GROUPS if k in gains} if gains else None
        de, da, dr = self.scas.step(theta_cmd, phi_cmd, nav, gains=scas_gains)

        sc = self.mixer.step(de, da, dr, thr)
        self._hold = sc
        return SurfaceCommand(
            elevon=sc.elevon.copy(), rudder=sc.rudder, throttle=sc.throttle.copy()
        )
