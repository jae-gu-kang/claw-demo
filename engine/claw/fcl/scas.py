"""SCAS — 자세 안정화 (피치/롤/요), PI + 각속도 피드백 (01 §3.1).

축 공통 구조 ScasAxis:
    u = clip( PI(자세오차) + k_rate·rate' , out_lo, out_hi )
    rate' = washout(rate)  (washout_tau > 0일 때 — 요축: 지속 선회의 정상 r을
            제거해 선회 유지를 방해하지 않는 댐퍼, 01 §3.1)
게인 부호는 설계값(게인 테이블)이 보유한다 — 코드는 공력 모멘트 부호를 가정하지
않는다 (conventions.md: 부호는 공력 DB가 정의). 게인 스케줄은 step() 인자
덮어쓰기로 주입 (PID와 동일 패턴 — M7 상위 조립이 테이블 조회값을 스텝마다 전달).

안티와인드업: 적분기는 PID 내부 클램프(out_lo/out_hi). rate 항은 클램프 밖에서
더해지므로 축 출력은 최종 clip으로 한 번 더 제한한다.

3축 조립 Scas: (θ·φ 명령, NavOutput) → 믹싱 전 축 명령 (de, da, dr).
요축 오차 입력은 −β (사이드슬립 억제 — 자세 명령이 아닌 선회조화).
"""

from claw.blocks.base import UNBOUNDED, Block
from claw.blocks.controllers import PID
from claw.blocks.filters import Washout
from claw.common.attitude import quat_to_euler, wrap_pi
from claw.fcl.airdata import airdata_from_nav
from claw.params.param import ParamDef


class ScasAxis(Block):
    NAME = "ScasAxis"
    PARAM_DEFS = (
        ParamDef("kp", 0.0, "-", "자세오차 비례 게인"),
        ParamDef("ki", 0.0, "1/s", "자세오차 적분 게인"),
        ParamDef("k_rate", 0.0, "s", "각속도 피드백 게인"),
        ParamDef("washout_tau", 0.0, "s", "rate 워시아웃 시정수 (0=미사용)", lo=0.0),
        ParamDef("out_lo", -UNBOUNDED, "rad", "출력 하한"),
        ParamDef("out_hi", UNBOUNDED, "rad", "출력 상한"),
    )

    def __init__(
        self,
        kp: float = 0.0,
        ki: float = 0.0,
        k_rate: float = 0.0,
        washout_tau: float = 0.0,
        out_lo: float = -UNBOUNDED,
        out_hi: float = UNBOUNDED,
    ):
        if out_lo > out_hi:
            raise ValueError(f"out_lo({out_lo}) > out_hi({out_hi})")
        if washout_tau < 0:
            raise ValueError(f"washout_tau는 음수 불가: {washout_tau}")
        # kp·ki의 정본은 내부 PID(step에서 None 전달 시 PID 값 사용) — 생성 후
        # 게인 변경은 스텝 인자 덮어쓰기(게인 스케줄 경로)로만 한다
        self.kp, self.ki, self.k_rate = kp, ki, k_rate
        self.washout_tau = washout_tau
        self.out_lo, self.out_hi = out_lo, out_hi
        self._pid = PID(kp, ki, 0.0, out_lo, out_hi)
        self._wo = Washout(washout_tau) if washout_tau > 0 else None

    def _discretize(self, dt: float) -> None:
        self._pid.init(dt)
        if self._wo is not None:
            self._wo.init(dt)

    def reset(self, state=None, rate=None) -> None:
        """state=적분기 웜스타트, rate=현재 각속도로 워시아웃 시드 (범프리스 전환 계약).

        정상 선회(r≠0) 중 SCAS 재관여 시 rate를 주면 워시아웃 출력이 0에서
        시작해 k_rate·r 킥이 발생하지 않는다.
        """
        self._pid.reset(state)
        if self._wo is not None:
            self._wo.reset(rate)

    def step(self, att_err, rate, kp=None, ki=None, k_rate=None):
        r = self._wo.step(rate) if self._wo is not None else rate
        kr = self.k_rate if k_rate is None else k_rate
        y = self._pid.step(att_err, kp=kp, ki=ki) + kr * r
        return min(max(y, self.out_lo), self.out_hi)


class Scas:
    """3축 SCAS 조립 — step(θ_cmd, φ_cmd, nav) → (de, da, dr) 믹싱 전 축 명령.

    피치: θ 오차 + q 피드백 / 롤: φ 오차 + p 피드백 /
    요: −β 오차 + washout(r) 피드백 (β는 NavOutput에서 추정, airdata.py).
    gains 인자: {"pitch": {kp,ki,k_rate}, "roll": …, "yaw": …} 스텝별 덮어쓰기
    — 게인 스케줄(01 §3.4) 주입 경로.
    """

    def __init__(self, pitch: ScasAxis, roll: ScasAxis, yaw: ScasAxis):
        self.pitch, self.roll, self.yaw = pitch, roll, yaw

    def init(self, dt: float) -> "Scas":
        self.dt = dt
        for ax in (self.pitch, self.roll, self.yaw):
            ax.init(dt)
        return self

    def reset(self) -> None:
        for ax in (self.pitch, self.roll, self.yaw):
            ax.reset()

    def step(self, theta_cmd, phi_cmd, nav, gains=None):
        # nav.valid 처리는 상위 조립(FlightControlLaw)의 소관 — 여기서는 항상 계산
        phi, theta, _psi = quat_to_euler(nav.q_nb)
        p, q, r = nav.omega_b
        _V, _alpha, beta = airdata_from_nav(nav)
        g = gains or {}
        de = self.pitch.step(theta_cmd - theta, q, **g.get("pitch", {}))
        # 롤 오차는 ±π 경계(배면 통과)에서 2π 점프하지 않도록 wrap (θ는 구조상 |θ|≤π/2)
        da = self.roll.step(wrap_pi(phi_cmd - phi), p, **g.get("roll", {}))
        dr = self.yaw.step(-beta, r, **g.get("yaw", {}))
        return de, da, dr
