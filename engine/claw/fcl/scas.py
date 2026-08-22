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
from claw.codegen.ir_exec import GraphRunner
from claw.common.attitude import quat_to_euler
from claw.fcl.airdata import airdata_from_nav
from claw.fcl.graphs import _SCHEDULABLE, scas3_graph, scas_axis_graph
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
        # 게인의 정본은 이 인스턴스이고, 스텝 인자 덮어쓰기(게인 스케줄 경로)가
        # 있으면 그 값이 우선한다. **구조**는 fcl/graphs.py scas_axis_nodes가 정본
        self.kp, self.ki, self.k_rate = kp, ki, k_rate
        self.washout_tau = washout_tau
        self.out_lo, self.out_hi = out_lo, out_hi
        self.cfg = {
            "kp": kp, "ki": ki, "k_rate": k_rate,
            "washout_tau": washout_tau, "out_lo": out_lo, "out_hi": out_hi,
        }

    def _discretize(self, dt: float) -> None:
        # 단독 실행은 게인 셋을 모두 포트로 — step()이 임의 조합을 덮어쓸 수 있다
        self._runner = GraphRunner(
            scas_axis_graph("scas_axis", scheduled=_SCHEDULABLE, **self.cfg), dt
        )

    def reset(self, state=None, rate=None) -> None:
        """state=적분기 웜스타트, rate=현재 각속도로 워시아웃 시드 (범프리스 전환 계약).

        정상 선회(r≠0) 중 SCAS 재관여 시 rate를 주면 워시아웃 출력이 0에서
        시작해 k_rate·r 킥이 발생하지 않는다.
        """
        states = {"pid": state}
        if self.washout_tau > 0:
            states["wo"] = rate
        self._runner.reset(states)

    def step(self, att_err, rate, kp=None, ki=None, k_rate=None):
        return self._runner.step(
            att_err=att_err, rate=rate,
            kp=self.kp if kp is None else kp,
            ki=self.ki if ki is None else ki,
            k_rate=self.k_rate if k_rate is None else k_rate,
        )


class Scas:
    """3축 SCAS 조립 — step(θ_cmd, φ_cmd, nav) → (de, da, dr) 믹싱 전 축 명령.

    피치: θ 오차 + q 피드백 / 롤: φ 오차 + p 피드백 /
    요: −β 오차 + washout(r) 피드백 (β는 NavOutput에서 추정, airdata.py).
    gains 인자: {"pitch": {kp,ki,k_rate}, "roll": …, "yaw": …} 스텝별 덮어쓰기
    — 게인 스케줄(01 §3.4) 주입 경로.
    """

    def __init__(self, pitch: ScasAxis, roll: ScasAxis, yaw: ScasAxis):
        self.pitch, self.roll, self.yaw = pitch, roll, yaw
        self.cfg = {"pitch": pitch.cfg, "roll": roll.cfg, "yaw": yaw.cfg}

    def init(self, dt: float) -> "Scas":
        # 축 인스턴스는 여기서 **파라미터 보유자**다 — 상태는 이 조립의 러너 한 곳에만
        # 둔다. 축마다 러너를 또 만들면 웜스타트를 어디에 넣었는지에 따라 결과가
        # 달라진다 (실제로 겪었다: 트림 웜스타트가 축 러너로 가서 사라졌다)
        self.dt = dt
        self._runner = GraphRunner(scas3_graph(ports=True, **self.cfg), dt)
        self.reset()
        return self

    def reset(self, states=None) -> None:
        """states={"pitch": 적분기 웜스타트, …} — 트림 웜스타트 주입 경로."""
        self._runner.reset({f"{g}_pid": v for g, v in (states or {}).items()})

    def step(self, theta_cmd, phi_cmd, nav, gains=None):
        """구조는 fcl/graphs.py scas3_nodes가 정본 — 여기서는 항법 상태에서
        공학량(θ·φ·β·p·q·r)을 뽑아 넘긴다. nav.valid 처리는 상위 조립 소관."""
        phi, theta, _psi = quat_to_euler(nav.q_nb)
        p, q, r = nav.omega_b
        _V, _alpha, beta = airdata_from_nav(nav)
        g = gains or {}
        ports = {
            f"g_{grp}_{key}": g.get(grp, {}).get(key, ax.cfg[key])
            for grp, ax in (("pitch", self.pitch), ("roll", self.roll), ("yaw", self.yaw))
            for key in _SCHEDULABLE
        }
        o = self._runner.step(
            theta_cmd=theta_cmd, phi_cmd=phi_cmd,
            theta=float(theta), phi=float(phi), beta=float(beta),
            p=float(p), q=float(q), r=float(r), **ports,
        )
        return o["de"], o["da"], o["dr"]
