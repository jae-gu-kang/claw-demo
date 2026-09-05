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

from claw.codegen.blockspec import get_state
from claw.codegen.ir_exec import GraphRunner
from claw.common.attitude import quat_to_euler
from claw.common.contracts import SurfaceCommand
from claw.env import isa_atmosphere
from claw.env.constants import ISA_MIN_ALT, ISA_STRATO1_TOP_ALT
from claw.fcl.airdata import airdata_from_nav
from claw.fcl.graphs import SCHEDULABLE, fcl_graph


# 계측 프로브 — 논리 이름 → 그래프 노드 id (fcl/graphs.py 조립이 붙이는 접두사_이름).
# 명령 사슬 중간값은 그래프 **출력이 아니다** — 출력은 생성 C의 인터페이스라 여기에
# 계측을 섞으면 탑재 코드가 달라진다. 그래서 러너의 계측 창구(last_env)에서 꺼낸다.
# 노드 id는 그래프 조립 규약에 매여 있어 이름이 바뀌면 값이 조용히 사라진다 —
# test_fcl_law가 전장착 형상에서 프로브가 전부 해석되는지 핀한다.
#
# 형상 의존 프로브: 옵션 경로가 꺼진 형상에서는 노드 자체가 조립되지 않아
# (죽은 항을 탑재 코드에 내지 않는다) `if nid in env` 가드로 생략된다 —
# 리미터 미장착의 theta_lim·lim_cap, k_pitch_turn=0의 ap_pitch_ff·ap_theta_raw,
# k_thr_turn=0의 ap_thr_ff, rate 경로 없는 축의 *_damp·*_raw가 그렇다.
INSTRUMENT_NODES = {
    "theta_cmd": "ap_theta_out",  # AP 피치 명령 (선회 FF·포화 후) → α 리미터
    "phi_cmd": "ap_hdg_sat",  # AP 롤 명령 (헤딩축 출력) → SCAS
    "theta_lim": "lim_theta_lim",  # 리미터 통과 θ — 보호가 물리면 theta_cmd와 갈라진다
    "pitch": "scas_pitch_sat",  # SCAS 축 출력 → 믹서
    "roll": "scas_roll_sat",
    "yaw": "scas_yaw_sat",
    # ── 명령필터 통과 명령 (오차 분해: 원본−필터 vs 필터−응답, 진단 규칙 1) ──
    "alt_cmd_filt": "ap_fh",
    "spd_cmd_filt": "ap_fv",
    "hdg_cmd_filt": "ap_fpsi",
    # ── 기여항 분해 (포화 틱에서 어느 게인 그룹이 주도했나, 진단 규칙 2) ──
    "ap_alt_pi": "ap_alt_pid",  # AP 고도축 PI항 (클램프 내)
    "ap_alt_damp": "ap_alt_damp",  # 승강률 댐핑항 k_hdot·ḣ
    "ap_alt_raw": "ap_alt_sum",  # 고도축 포화 전 합 (pi + damp)
    "ap_spd_pi": "ap_spd_pid",
    "ap_hdg_pi": "ap_hdg_pid",
    "ap_pitch_ff": "ap_ff_p",  # 선회 피치 FF항 (k_pitch_turn≠0일 때만 존재)
    "ap_thr_ff": "ap_ff_t",  # 선회 스로틀 FF항 (k_thr_turn≠0일 때만 존재)
    "ap_theta_raw": "ap_theta_ff",  # FF 합산 후·재클램프 전 θ
    # ── 종방향 축 선택 (01 §3.3.1 이륙·착륙) ──
    # 셋 중 무엇이 θ를 냈는지는 화면이 말해야 한다 — 조용한 출처 전환은 "왜 이렇게
    # 날았나"를 설명할 수 없게 만든다. 세 갈래의 값을 모두 계측한다.
    "ap_vs_pi": "ap_vs_pid",  # 승강률축 PI (클램프 내)
    "ap_theta_alt": "ap_alt_sat",  # 고도축이 냈을 θ
    "ap_theta_vs": "ap_vs_sat",  # 승강률축이 냈을 θ
    "ap_theta_pitch": "ap_pitch_sat",  # 피치 직접 지령(축 한계로 자른 값)
    "ap_theta_src": "ap_theta_src",  # 실제로 고른 값
    "pitch_pi": "scas_pitch_pid",
    "pitch_damp": "scas_pitch_damp",
    "pitch_raw": "scas_pitch_sum",  # 포화 전 합 — |raw−sat|>0이 곧 축 포화 틱
    "roll_pi": "scas_roll_pid",
    "roll_damp": "scas_roll_damp",
    "roll_raw": "scas_roll_sum",
    "yaw_pi": "scas_yaw_pid",
    "yaw_damp": "scas_yaw_damp",
    "yaw_raw": "scas_yaw_sum",
    "yaw_wo": "scas_yaw_wo",  # 워시아웃 통과 r — 지속 선회의 정상 r 제거 확인
    # ── 리미터 (귀속: 감쇠 문제 vs margin 문제, 진단 규칙 5) ──
    "lim_cap": "lim_cap",  # θ 상한 = θ + (α_max − α) — theta_cmd−cap 지속이 margin 문제 신호
    # ── 엘레본 제어권한 배분 (평가 A⑦ 잔여 권한 — fcl/graphs.py 예산 노드) ──
    # 배분 미장착 형상(alloc_trim_table=None)은 노드 자체가 조립되지 않으므로
    # `if nid in env` 가드가 자동 생략한다 — 선택 경로 계측의 기존 관례(ap_ff_* 등).
    # lo는 −hi라 계측하지 않는다(같은 수를 두 번 싣지 않는다).
    "alloc_roll_hi": "scas_alloc_roll_hi",  # 롤 동적 한계 = B − R
    "alloc_pitch_hi": "scas_alloc_pitch_hi",  # 피치 잔여 권한 = B − |δa_eff|
    "alloc_resv": "scas_alloc_resv",  # 선회 하중 예약 R
}

# 계측 상태 — 논리 이름 → (노드 id, 논리 필드). 상태는 그래프 노드 출력이 아니라
# 인스턴스 속성이라 last_env에 없다 — blockspec.get_state(set_state의 read 대칭)로
# 꺼낸다. 적분기가 클램프에 주차하는가(안티와인드업 진단, 규칙 3)의 유일한 근거.
INSTRUMENT_STATES = {
    "i_vs": ("ap_vs_pid", "i"),
    "i_pitch": ("scas_pitch_pid", "i"),
    "i_roll": ("scas_roll_pid", "i"),
    "i_yaw": ("scas_yaw_pid", "i"),
    "i_alt": ("ap_alt_pid", "i"),
    "i_spd": ("ap_spd_pid", "i"),
    "i_hdg": ("ap_hdg_pid", "i"),
}


class FlightControlLaw:
    def __init__(self, scas, autopilot, mixer, schedule=None, alpha_limiter=None,
                 alloc_trim_table=None, alloc_resv_frac=0.7):
        self.scas = scas
        # 엘레본 제어권한 배분 계수 [rad/하중] — 0이면 배분 없음 (fcl/graphs.py)
        self.alloc_trim_table = alloc_trim_table
        self.alloc_resv_frac = float(alloc_resv_frac)
        self.autopilot = autopilot
        self.mixer = mixer
        self.schedule = schedule
        self.alpha_limiter = alpha_limiter
        if schedule is not None:
            # 그룹·키 오타는 분배 필터/스텝 kwargs에서 '조용히' 또는 '실행 시점에'
            # 터진다 — 여기(조립 시점)서 시끄럽게 (리뷰: 키도 검증).
            # 허용 자리는 fcl/graphs.py SCHEDULABLE이 정본이다 — 속도·헤딩 축의
            # k_rate처럼 **구조상 불가능한** 자리도 그래서 여기서 함께 걸린다
            for name in schedule.tables:
                group, _, key = name.partition(".")
                if group not in SCHEDULABLE:
                    raise ValueError(
                        f"미정의 게인 그룹 {group!r} ({name!r}) — 허용: {sorted(SCHEDULABLE)}"
                    )
                if key not in SCHEDULABLE[group]:
                    raise ValueError(
                        f"스케줄 불가 게인 {name!r} — {group} 축 허용 키: "
                        f"{list(SCHEDULABLE[group])}"
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
                alloc_trim_table=self.alloc_trim_table,
                alloc_resv_frac=self.alloc_resv_frac,
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
            cmd_pitch=float(cmd.pitch), cmd_hdot=float(cmd.hdot),
            speed_on=float(bool(cmd.speed_on)), alt_on=float(bool(cmd.alt_on)),
            heading_on=float(bool(cmd.heading_on)),
            pitch_on=float(bool(cmd.pitch_on)), hdot_on=float(bool(cmd.hdot_on)),
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
            # 적분기 상태 합류 — 노드가 아니라 인스턴스 속성이라 env에 없다.
            # 스텝 후 값(_i 갱신 완료)이다. 노드 부재 형상은 프로브와 같은 규약으로 생략
            for name, (nid, field) in INSTRUMENT_STATES.items():
                inst = self._runner.instances.get(nid)
                if inst is not None:
                    self.last_signals[name] = get_state(inst, field)
            if "alpha_margin" in o:
                self.alpha_margin = o["alpha_margin"]
                self.limiter_active = bool(o["limiter_active"])
        return SurfaceCommand(
            elevon=np.array([o["elevon_l"], o["elevon_l"], o["elevon_r"], o["elevon_r"]]),
            rudder=o["rudder"],
            throttle=np.array([o["throttle_l"], o["throttle_r"]]),
        )
