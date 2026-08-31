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

from claw.blocks.base import Block
from claw.blocks.filters import CommandFilter
from claw.codegen.ir_exec import GraphRunner
from claw.common.attitude import quat_to_euler
from claw.fcl.airdata import airdata_from_nav
from claw.fcl.graphs import AP_PARAM, AP_PORTS, autopilot_graph
from claw.params.param import ParamDef

# CommandFilter는 원시 블록(M2)으로 옮겼다 — codegen이 fcl을 거치지 않고 쓰려면
# 계층이 아래여야 한다(03 §1). 기존 import 경로는 유지한다.
__all__ = ["Autopilot", "CommandFilter"]


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
        ParamDef("kp_vs", 0.08, "rad·s/m", "승강률 비례 게인"),
        ParamDef("ki_vs", 0.02, "rad/m", "승강률 적분 게인"),
        ParamDef("tau_vs", 2.0, "s", "승강률 명령필터 시정수", lo=0.0),
        ParamDef("theta_lo", -0.3, "rad", "피치 명령 하한"),
        ParamDef("theta_hi", 0.3, "rad", "피치 명령 상한"),
        ParamDef("phi_max", 0.7, "rad", "뱅크 명령 한계 (π/2 미만 — 선회 FF 부호 보전)", lo=0.0, hi=1.5),
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
        # 승강률 축 [기본값] — 오차 [m/s] → θ [rad]. **착륙 실측으로 정했다**:
        # 접근 −4.8 m/s에서 플레어 개시 고도를 바꿔 가며 접지 강하율을 재면
        #   개시 5 m·kp 0.02 → 접지 −4.58 m/s (플레어가 0.9 s뿐이라 못 세운다)
        #   개시 20 m·kp 0.08 → 접지 −1.00 m/s, 실속 마진 0.071 rad ← 채택
        #   개시 35 m·kp 0.12 → 접지 −0.72 m/s, 그러나 마진 0.043으로 얇아진다
        # 더 부드러운 접지는 더 오래 기수를 들고 있어야 하므로 실속 여유와 맞바꾼다.
        kp_vs: float = 0.08,
        ki_vs: float = 0.02,
        tau_vs: float = 2.0,
        theta_lo: float = -0.3,
        theta_hi: float = 0.3,
        phi_max: float = 0.7,
        k_pitch_turn: float = 0.05,
        k_thr_turn: float = 0.0,
    ):
        if theta_lo > theta_hi:
            raise ValueError(f"theta_lo({theta_lo}) > theta_hi({theta_hi})")
        if not 0.0 <= phi_max <= 1.5:  # ParamDef hi와 일치 (π/2 미만 — 선회 FF 부호 보전)
            # π/2 이상이면 1/cosφ 선회 FF 부호가 반전 — 설계 스캔 실수 방지 가드
            raise ValueError(f"phi_max는 [0, 1.5] 필요 (ParamDef hi): {phi_max}")
        self.theta_lo, self.theta_hi, self.phi_max = theta_lo, theta_hi, phi_max
        self.k_pitch_turn, self.k_thr_turn = k_pitch_turn, k_thr_turn
        # 구조는 fcl/graphs.py autopilot_nodes가 정본 — 여기는 파라미터만 보유한다
        self.cfg = {
            "kp_spd": kp_spd, "ki_spd": ki_spd, "tau_spd": tau_spd,
            "kp_alt": kp_alt, "ki_alt": ki_alt, "k_hdot": k_hdot, "tau_alt": tau_alt,
            "kp_hdg": kp_hdg, "ki_hdg": ki_hdg, "tau_hdg": tau_hdg,
            "kp_vs": kp_vs, "ki_vs": ki_vs, "tau_vs": tau_vs,
            "theta_lo": theta_lo, "theta_hi": theta_hi, "phi_max": phi_max,
            "k_pitch_turn": k_pitch_turn, "k_thr_turn": k_thr_turn,
        }

    def _discretize(self, dt: float) -> None:
        # 단독 실행은 게인을 포트로 — step(gains=…)이 임의 조합을 덮어쓸 수 있다
        self._runner = GraphRunner(autopilot_graph(ports=True, **self.cfg), dt)

    def reset(self, state=None) -> None:
        """state={"throttle": thr0, "theta": θ0} — 트림 웜스타트 (캡처 시 범프리스)."""
        st = state or {}
        warm = {}
        if "throttle" in st:
            warm["spd_pid"] = float(st["throttle"])
        if "theta" in st:
            warm["alt_pid"] = float(st["theta"])
        self._runner.reset(warm)

    def step(self, cmd, nav, gains=None):
        """(GuidanceCommand, NavOutput) → (θ_cmd, φ_cmd, thr 집합 0~1).

        gains={"speed": {...}, "alt": {...}, "heading": {...}} 스텝별 덮어쓰기
        — 게인 스케줄(01 §3.4) 주입 경로. 차동추력 배분은 믹서 소관.
        """
        # 대기속도는 airdata_from_nav 하나만 쓴다 — 예전엔 여기서 norm(nav.vel_n)로
        # 따로 구했는데(수학적으로는 같다) 반올림이 달라 법칙 안에 대기속도가 두 벌
        # 있었다(실측 2.8e-14). 바람 모델이 들어오면 고칠 곳도 airdata 한 곳이어야 한다
        V = float(airdata_from_nav(nav)[0])
        _phi, _theta, psi = quat_to_euler(nav.q_nb)
        g = gains or {}
        ports = {
            f"g_{grp}_{key}": g.get(grp, {}).get(key, self.cfg[AP_PARAM[(grp, key)]])
            for grp, keys in AP_PORTS.items()
            for key in keys
        }
        o = self._runner.step(
            psi=float(psi), h=-float(nav.pos_n[2]), hdot=-float(nav.vel_n[2]), V=V,
            cmd_heading=float(cmd.heading), cmd_alt=float(cmd.alt),
            cmd_speed=float(cmd.speed),
            cmd_pitch=float(cmd.pitch), cmd_hdot=float(cmd.hdot),
            heading_on=float(bool(cmd.heading_on)), alt_on=float(bool(cmd.alt_on)),
            speed_on=float(bool(cmd.speed_on)), pitch_on=float(bool(cmd.pitch_on)),
            hdot_on=float(bool(cmd.hdot_on)), **ports,
        )
        return o["theta_cmd"], o["phi_cmd"], o["throttle"]
