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

from claw.codegen.ir_exec import GraphRunner
from claw.common.attitude import quat_to_euler
from claw.common.contracts import SurfaceCommand
from claw.env import isa_atmosphere
from claw.env.constants import ISA_MIN_ALT, ISA_STRATO1_TOP_ALT
from claw.fcl.airdata import airdata_from_nav
from claw.fcl.graphs import fcl_graph

_SCAS_GROUPS = ("pitch", "roll", "yaw")
_AP_GROUPS = ("speed", "alt", "heading")
# 스케줄 덮어쓰기 허용 키 — 전 그룹이 ScasAxis.step(kp·ki·k_rate)로만 소비
_GAIN_KEYS = ("kp", "ki", "k_rate")

# 계측 프로브 — 논리 이름 → 그래프 노드 id (fcl/graphs.py 조립이 붙이는 접두사_이름).
# 명령 사슬 중간값은 그래프 **출력이 아니다** — 출력은 생성 C의 인터페이스라 여기에
# 계측을 섞으면 탑재 코드가 달라진다. 그래서 러너의 계측 창구(last_env)에서 꺼낸다.
# 노드 id는 그래프 조립 규약에 매여 있어 이름이 바뀌면 값이 조용히 사라진다 —
# test_fcl_law가 데모 형상에서 프로브가 전부 해석되는지 핀한다.
INSTRUMENT_NODES = {
    "theta_cmd": "ap_theta_out",  # AP 피치 명령 (선회 FF·포화 후) → α 리미터
    "phi_cmd": "ap_hdg_sat",  # AP 롤 명령 (헤딩축 출력) → SCAS
    "theta_lim": "lim_theta_lim",  # 리미터 통과 θ — 보호가 물리면 theta_cmd와 갈라진다
    "pitch": "scas_pitch_sat",  # SCAS 축 출력 → 믹서
    "roll": "scas_roll_sat",
    "yaw": "scas_yaw_sat",
}


class FlightControlLaw:
    def __init__(self, scas, autopilot, mixer, schedule=None, alpha_limiter=None):
        self.scas = scas
        self.autopilot = autopilot
        self.mixer = mixer
        self.schedule = schedule
        self.alpha_limiter = alpha_limiter
        if schedule is not None:
            # 그룹·키 오타는 분배 필터/스텝 kwargs에서 '조용히' 또는 '실행 시점에'
            # 터진다 — 여기(조립 시점)서 시끄럽게 (리뷰: 키도 검증)
            known = set(_SCAS_GROUPS) | set(_AP_GROUPS)
            for name in schedule.tables:
                group, _, key = name.partition(".")
                if group not in known:
                    raise ValueError(
                        f"미정의 게인 그룹 {group!r} ({name!r}) — 허용: {sorted(known)}"
                    )
                if key not in _GAIN_KEYS:
                    raise ValueError(
                        f"미정의 게인 키 {name!r} — 허용 키: {list(_GAIN_KEYS)}"
                    )
        self.alpha_margin = None
        self.limiter_active = False
        self.last_signals = {}  # 직전 스텝 그래프 출력 (계측 전용 — 법칙 경로 미사용)

    def init(self, dt: float) -> "FlightControlLaw":
        """전 법칙을 **하나의 평탄한 그래프**로 조립한다 (fcl/graphs.py fcl_graph).

        자식 컴포넌트는 여기서 파라미터 보유자다 — 상태는 이 러너 한 곳에만 둔다.
        자식마다 러너를 또 만들면 웜스타트를 어디에 넣었는지에 따라 결과가 달라진다.
        """
        self.dt = dt
        lim = self.alpha_limiter
        self._runner = GraphRunner(
            fcl_graph(
                autopilot=self.autopilot.cfg,
                scas_axes=self.scas.cfg,
                mixer=self.mixer.cfg,
                stall_table=lim.stall_table if lim is not None else None,
                alpha_margin=lim.margin if lim is not None else 0.05,
                gain_tables=self.schedule.tables if self.schedule is not None else None,
                filter_tau=self.schedule.filter_tau if self.schedule is not None else 0.5,
            ),
            dt,
        )
        if self.schedule is not None:
            # 스케줄은 단독 조회 경로로도 쓰인다(편집한 테이블이 반영됐는지 확인 등).
            # 그 러너의 상태는 법칙 실행과 **무관하다** — 법칙은 위 그래프 하나로만 돈다
            self.schedule.init(dt)
        self.reset()
        return self

    @property
    def runner(self):
        """조립된 그래프 실행기 — 탑재 C 생성(`codegen.emit_c`)이 이 그래프를 읽는다.

        생성기가 조립을 따로 재현하면 정본이 둘이 된다(02 §5.5). 산출물 생성
        (`flight/generate.py`)과 서버의 탑재 C 응답이 모두 이 경로를 쓴다.
        """
        return self._runner

    def reset(self, state=None) -> None:
        """state={"theta": θ0, "throttle": thr0, "de": de0} — 트림 웜스타트.

        SCAS 피치 적분기=de0, AP 고도 적분기=θ0·속도 적분기=thr0. 홀드 명령도
        웜스타트 값으로 재구성 (첫 유효 항법 이전의 출력).
        """
        st = state or {}
        de0 = float(st.get("de", 0.0))
        thr0 = float(st.get("throttle", 0.0))
        hold = self.mixer.step(de0, 0.0, 0.0, thr0)  # 믹서는 무상태 — 같은 그래프다
        self._runner.reset(
            states={
                "scas_pitch_pid": de0,
                "ap_alt_pid": float(st.get("theta", 0.0)),
                "ap_spd_pid": thr0,
            },
            hold={
                "elevon_l": float(hold.elevon[0]), "elevon_r": float(hold.elevon[2]),
                "rudder": float(hold.rudder),
                "throttle_l": float(hold.throttle[0]),
                "throttle_r": float(hold.throttle[1]),
            },
        )
        self.alpha_margin = None
        self.limiter_active = False
        self.last_signals = {}  # 직전 스텝 그래프 출력 (계측 전용 — 법칙 경로 미사용)

    def step(self, cmd, nav) -> SurfaceCommand:
        """법칙 구조는 fcl/graphs.py가 정본 — 여기서는 원시 항법 상태를 그래프가
        받는 공학량으로 바꾸고(실기에선 항법·ADC 몫) 결과를 계약으로 포장한다."""
        V, alpha, beta = airdata_from_nav(nav)
        phi, theta, psi = quat_to_euler(nav.q_nb)
        h = -float(nav.pos_n[2])
        h_isa = min(max(h, ISA_MIN_ALT), ISA_STRATO1_TOP_ALT)
        p, q, r = nav.omega_b
        o = self._runner.step(
            nav_valid=float(bool(nav.valid)),
            theta=float(theta), phi=float(phi), psi=float(psi),
            p=float(p), q=float(q), r=float(r),
            V=float(V), alpha=float(alpha), beta=float(beta),
            h=h, hdot=-float(nav.vel_n[2]), mach=float(V / isa_atmosphere(h_isa).a),
            cmd_speed=float(cmd.speed), cmd_alt=float(cmd.alt),
            cmd_heading=float(cmd.heading),
            speed_on=float(bool(cmd.speed_on)), alt_on=float(bool(cmd.alt_on)),
            heading_on=float(bool(cmd.heading_on)),
        )
        # 항법 무효 스텝은 아무것도 실행되지 않았다 — 로깅 속성도 직전 값을 유지한다
        if nav.valid:
            env = self._runner.last_env
            # 명령 사슬 중간값을 논리 이름으로 공개 — 소비처는 관측자뿐(Simulator
            # 로깅·구조도 재생 오버레이). 법칙 경로는 읽지 않는다: 읽는 순간
            # "그래프가 구조의 정본"이라는 계약이 깨진다.
            self.last_signals = {
                name: float(env[nid])
                for name, nid in INSTRUMENT_NODES.items() if nid in env
            }
            if "alpha_margin" in o:
                self.alpha_margin = o["alpha_margin"]
                self.limiter_active = bool(o["limiter_active"])
        return SurfaceCommand(
            elevon=np.array([o["elevon_l"], o["elevon_l"], o["elevon_r"], o["elevon_r"]]),
            rudder=o["rudder"],
            throttle=np.array([o["throttle_l"], o["throttle_r"]]),
        )
