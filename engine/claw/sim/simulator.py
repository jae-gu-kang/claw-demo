"""M11 멀티레이트 시뮬 프레임 + 조립 루트 (02 §6, 03 M11).

조립(composition root): plant(쿼터니언 경로 RigidBody+RK4) + nav + guidance +
fcl — 전부 03 §4 계약(VehicleState→NavOutput→GuidanceCommand→SurfaceCommand)
으로만 연결. 법칙은 NavOutput만 소비한다 (참값 차단 계약).

멀티레이트 [확정 02 §6]:
- 플랜트 적분: dt_plant 고정스텝 RK4 (힘·모멘트 부단계 재평가, 상태 의존)
- 제어: control_hz — dt_plant의 정수배 주기 검증, 명령은 틱 사이 ZOH
- 항법: nav 모델이 dt_plant 틱 기준으로 자체 갱신주기·지연 처리 (02 §3.1)
- 작동기 [기본값 01 §2.4]: 옵션 — 4엘레본+러더 2차계, 플랜트 주기 적분,
  트림 웜스타트. 미장착 시 명령 직결

엔벨로프 감시 [확정 02 §6.1]: 실속 마진(α_stall(mach)−α) 시계열·최악값·시각,
α/β/mach DB 유효범위 이탈 플래그·최초 발생 시각.

연료 소모: fuel_flow[kg/s, 스로틀 1 기준]·평균 스로틀 준정적 [기본값 0 —
분산 대상·소모 모델은 02 §6 몬테카를로 TBD와 함께 확정].
"""

import math

import numpy as np

from claw.common.contracts import NavOutput, SimResult, VehicleState
from claw.common.frames import body_to_ned, wind_angles
from claw.env import isa_atmosphere
from claw.env.constants import ISA_MIN_ALT, ISA_STRATO1_TOP_ALT
from claw.plant import OMEGA, POS, QUAT, VEL, RigidBody, SecondOrderActuator, pack

# 명령 사슬 계측 — 유도→AP→리미터→SCAS 각 단의 중간 신호. FCL 그래프가 매 제어
# 스텝에 이미 계산해 두는 값(law.py last_signals)을 꺼내 쓸 뿐, 새로 계산하지 않는다.
# 소비처: 구조도 재생 오버레이(배선마다 그 시각의 실제 값)와 진단(pipeline/diagnose —
# 오차 분해·기여항 분해·와인드업·리미터 귀속) — 이게 없으면 최종 타면과 피드백만
# 계측되어 명령 사슬 배선이 값 없이 남는다.
# 주의: 제어주기(n_ctrl)마다만 갱신되므로 사이 스텝은 직전 값을 유지한다 (de/da/dr 규약).
# 형상 의존 채널(law.py INSTRUMENT_NODES 참조)은 0이 아니라 NaN — 부재 집합은
# test_sim이 못박는다.
_CHAIN_SIGNALS = (
    "cmd_speed", "cmd_alt", "cmd_heading", "cmd_pitch", "cmd_hdot",  # 유도 → AP
    "speed_on", "alt_on", "heading_on",  # 축 활성 — 진단의 활성 구간 게이팅 근거
    "pitch_on", "hdot_on",  # 종방향 축 선택 (alt·pitch·hdot 배타)
    "alt_cmd_filt", "spd_cmd_filt", "hdg_cmd_filt",  # 명령필터 통과 (오차 분해)
    "theta_cmd", "phi_cmd",  # AP → α 리미터
    "ap_alt_pi", "ap_alt_damp", "ap_alt_raw",  # AP 고도축 기여항 (포화 전)
    "ap_spd_pi", "ap_hdg_pi",
    "ap_pitch_ff", "ap_thr_ff", "ap_theta_raw",  # 선회 FF·재클램프 전 θ
    "ap_vs_pi", "ap_theta_alt", "ap_theta_vs", "ap_theta_pitch", "ap_theta_src",
    "theta_lim",  # 리미터 → SCAS (보호가 물리면 theta_cmd와 갈라진다)
    "lim_cap",  # 리미터 θ 상한 — 귀속(감쇠 vs margin)의 근거
    "pitch", "roll", "yaw",  # SCAS → 믹서
    "pitch_pi", "pitch_damp", "pitch_raw",  # SCAS 축 기여항 (포화 전)
    "roll_pi", "roll_damp", "roll_raw",
    "yaw_pi", "yaw_damp", "yaw_raw", "yaw_wo",
    "i_pitch", "i_roll", "i_yaw", "i_alt", "i_spd", "i_hdg", "i_vs",  # 적분기 (와인드업)
)


class Simulator:
    def __init__(
        self,
        aircraft,
        fcl,
        guidance,
        nav_model=None,
        stall_table=None,
        db_ranges=None,
        dt_plant: float = 0.005,
        control_hz: float = 100.0,
        actuator_params=None,
        fuel_flow: float = 0.0,
        min_altitude: float | None = 0.0,
        ground_elev: float = 0.0,
        launch=None,
    ):
        if dt_plant <= 0 or control_hz <= 0:
            raise ValueError(f"dt_plant({dt_plant})·control_hz({control_hz})는 양수여야 함")
        ratio = 1.0 / (control_hz * dt_plant)
        if ratio < 1.0 - 1e-9:
            raise ValueError(
                f"플랜트 주기({dt_plant}s)가 제어 주기(1/{control_hz}s)보다 김 — "
                "플랜트가 제어보다 빠르거나 같아야 함"
            )
        n = round(ratio)
        if abs(ratio - n) > 1e-6:
            raise ValueError(f"제어 주기는 dt_plant의 정수배여야 함: 비율 {ratio:.4f}")
        if fuel_flow < 0:
            raise ValueError(f"fuel_flow는 음수 불가: {fuel_flow}")
        if min_altitude is not None and not math.isfinite(min_altitude):
            raise ValueError(f"min_altitude는 유한값이어야 함: {min_altitude}")
        bad_vars = set(db_ranges or {}) - {"alpha", "beta", "mach"}
        if bad_vars:
            raise ValueError(f"db_ranges 미지원 변수 {sorted(bad_vars)} (허용: alpha·beta·mach)")
        self.aircraft = aircraft
        self.fcl = fcl
        self.guidance = guidance
        self.nav_model = nav_model
        self.stall_table = stall_table
        self.db_ranges = dict(db_ranges) if db_ranges else {}
        # 기준면 여유 감시 [기본값 0 m = 해수면 MSL, 01 §2.5]. None이면 감시 끔.
        #
        # **의미가 지면 도입으로 갈린다.** 착륙장치가 없으면 예전 그대로다 — 지형·파고
        # 미모델이라 "지면 충돌 판정"이 아니라 특이 상황 표시이고, 시뮬은 중단하지 않고
        # 플래그만 남긴다(02 §6.1). 착륙장치가 달리면 접촉점이 지면을 파고드는 것은
        # 정상(스프링 침투)이고, 이 플래그가 잡는 것은 **동체 기준점(CG)이 지면 아래**로
        # 내려간 경우다 — 스키드가 0.55 m 아래에 있으므로 CG가 지면 밑이면 기체가
        # 통째로 잠긴 것이다. 활주로 표고가 0이 아니면 기준면도 표고여야 한다
        # (호출자가 ground_elev와 같은 값을 준다 — 여기서 자동으로 끌어오지 않는 것은
        # 감시를 끄거나 다른 기준면을 보고 싶은 경우를 막지 않기 위해서다).
        self.min_altitude = float(min_altitude) if min_altitude is not None else None
        if not math.isfinite(ground_elev):
            raise ValueError(f"ground_elev는 유한값이어야 함: {ground_elev}")
        # 지면 평면 표고 [m] — 착륙장치가 침투를 재는 기준. 지형은 미모델이라 평면 하나다.
        self.ground_elev = float(ground_elev)
        # 발사 레일 (plant.ground.LaunchRail | None). 레일 구간은 **힘이 아니라 구속**이라
        # RK4를 타지 않고 등가속 해석해로 전진한다 — run()의 레일 분기 참조.
        self.launch = launch
        if launch is not None and not hasattr(launch, "state_at"):
            raise ValueError("launch는 LaunchRail 계약(state_at·exit_time·length)이어야 함")
        # on_ground·airborne 조건은 착륙장치가 있어야 판정된다. 없으면 그 조건이
        # 영원히 판정 불가라 모드 체인이 조용히 그 자리에 멈춘다 — path 없이
        # path_done을 쓰는 것을 구성 시점에 거부하는 것과 같은 자리다(guidance.py).
        if getattr(guidance, "needs_ground", False) and aircraft.ground is None:
            raise ValueError(
                "on_ground·airborne 이탈 조건이 있으나 기체에 착륙장치가 없음 "
                "— Aircraft(ground=...)로 장착하거나 조건을 바꿔야 함"
            )
        if getattr(guidance, "needs_rail", False) and launch is None:
            raise ValueError(
                "off_rail 이탈 조건이 있으나 발사 레일이 없음 — launch=를 주거나 조건을 바꿔야 함"
            )
        self.dt_plant = dt_plant
        self.control_hz = control_hz
        self.n_ctrl = int(n)
        self.dt_ctrl = self.n_ctrl * dt_plant
        # 빈 dict = 기본 파라미터로 장착 (None만 미장착)
        self.actuator_params = (
            dict(actuator_params) if actuator_params is not None else None
        )
        if self.actuator_params is not None:
            reserved = {"pos_lo", "pos_hi", "initial"} & set(self.actuator_params)
            if reserved:
                raise ValueError(
                    f"actuator_params 예약 키 사용 불가: {sorted(reserved)} "
                    "(위치 한계는 믹서, 초기값은 트림 웜스타트가 결정)"
                )
            # 프로브 생성 — 파라미터 오류를 run()이 아닌 구성 시점에 검출
            SecondOrderActuator(
                pos_lo=-1.0, pos_hi=1.0, initial=0.0, **self.actuator_params
            )
        self.fuel_flow = fuel_flow

    def _make_actuators(self, de0):
        p = self.actuator_params
        mixer = self.fcl.mixer
        elev = []
        for _ in range(4):
            a = SecondOrderActuator(
                pos_lo=mixer.elevon_lo, pos_hi=mixer.elevon_hi, initial=de0, **p
            ).init(self.dt_plant)
            elev.append(a)
        rud = SecondOrderActuator(
            pos_lo=mixer.rudder_lo, pos_hi=mixer.rudder_hi, initial=0.0, **p
        ).init(self.dt_plant)
        return elev, rud

    def run(self, tr, t_end: float, fingerprint: str = "", on_progress=None) -> SimResult:
        """트림해에서 출발하는 폐루프 실행 → SimResult (계보 지문 포함).

        on_progress(done, total): 스텝 수 기준 ~1% 주기로 호출 (M13 서버 진행률
        경로). truthy 반환 = 협조적 취소 — ISA 이탈과 같은 절단 경로로 부분
        결과를 보존하고 meta["aborted"]="cancelled"로 표시한다. 완주 시 마지막
        호출은 done==total 보장. 콜백 예외는 전파되며 부분 결과가 소실된다 —
        취소는 반드시 truthy 반환으로.
        """
        if not tr.converged:
            raise ValueError(f"미수렴 트림해로는 시뮬 불가: {tr.case.name}")
        de0 = float(tr.control.elevon[0])
        thr0 = float(tr.control.throttle[0])
        fuel = float(tr.case.fuel)

        # 초기 상태는 **트림해의 상태**에서 온다. 수평비행 트림은 pos_n = [0,0,−case.alt]
        # 이라 종전(case.alt를 직접 쓰던 것)과 완전히 같고, 지상 평형 트림은 풀어낸
        # CG 높이(표고 + 0.50 m)를 담고 있어 그 값이 그대로 쓰인다 — case.alt를 쓰면
        # 활주로 표면에 CG를 놓아 기체가 반쯤 잠긴 채 출발한다.
        x = pack(tr.state.pos_n, tr.state.vel_b, tr.state.q_nb, tr.state.omega_b)
        on_rail = self.launch is not None
        if on_rail:
            # 발사 구성에서는 **레일 기하가 초기 상태를 정한다** — 레일이 기체를 잡고
            # 있으므로 평형해가 아니라 구속 상태다. 트림해는 질량·연료와 법칙 웜스타트의
            # 출처로만 남는다. 웜스타트 자세도 레일 앙각이어야 한다(수평이 아니다).
            x = pack(*self.launch.state_at(0.0))
        th0 = float(VehicleState(q_nb=x[QUAT]).euler()[1])
        self.fcl.init(self.dt_ctrl)
        self.fcl.reset(state={"theta": th0, "throttle": thr0, "de": de0})
        self.guidance.init(self.dt_ctrl)
        if self.nav_model is not None:
            self.nav_model.init(self.dt_plant)
        actuators = self._make_actuators(de0) if self.actuator_params is not None else None

        m0, _cg, J0 = self.aircraft.fuel_mass.at(fuel)
        rb = RigidBody(m0, J0)

        n_steps = int(round(t_end / self.dt_plant))
        progress_stride = max(1, n_steps // 100)
        sig = {k: np.empty(n_steps) for k in (
            "pn", "pe", "h", "u", "v", "w", "p", "q", "r", "phi", "theta", "psi",
            "V", "alpha", "beta", "mach", "fuel",
            "de", "da", "dr", "thr_l", "thr_r", "alpha_margin",
            "n_gear", "launch_gx",
            *_CHAIN_SIGNALS,
        )}
        sig["limiter_active"] = np.zeros(n_steps, dtype=bool)
        # 지면 접촉 — 착륙장치가 없으면 반력은 0이 아니라 **NaN**(미계측)이다.
        # 0으로 두면 "지면에 닿았는데 반력이 0"과 구분되지 않는다.
        sig["wow"] = np.zeros(n_steps, dtype=bool)
        sig["on_rail"] = np.zeros(n_steps, dtype=bool)
        modes = []
        stall_margin = np.full(n_steps, np.nan)
        flag_keys = list(self.db_ranges)
        if self.min_altitude is not None:
            flag_keys.append("altitude")  # db_ranges와 구분 — DB 유효범위가 아니라 기준면 여유
        flags = {k: np.zeros(n_steps, dtype=bool) for k in flag_keys}

        sc = None
        aborted = None
        n_done = n_steps
        launch_exit_t = None
        for k in range(n_steps):
            t = k * self.dt_plant
            pos, vel_b, q_nb, omega = x[POS], x[VEL], x[QUAT], x[OMEGA]
            truth = VehicleState(
                t=t, pos_n=pos.copy(), vel_b=vel_b.copy(),
                q_nb=q_nb.copy(), omega_b=omega.copy(), fuel=fuel,
            )
            if self.nav_model is not None:
                nav = self.nav_model.step(truth)
            else:
                nav = NavOutput(
                    t=t, pos_n=pos.copy(), vel_n=body_to_ned(q_nb, vel_b),
                    q_nb=q_nb.copy(), omega_b=omega.copy(),
                    t_meas=t, valid=True, fuel=fuel,
                )
            # 접지 여부는 유도의 이탈 조건(on_ground·airborne)이 쓰므로 **제어 틱보다
            # 먼저** 재야 한다. 레일 위에서는 레일이 받치므로 기어는 닿지 않는다.
            gs = (
                self.aircraft.ground.contact_state(
                    pos, vel_b, q_nb, omega, self.ground_elev
                )
                if self.aircraft.ground is not None
                else None
            )
            if k % self.n_ctrl == 0:
                cmd = self.guidance.step(
                    nav,
                    on_ground=None if gs is None else gs["wow"],
                    on_rail=on_rail if self.launch is not None else None,
                )
                sc = self.fcl.step(cmd, nav)

            if actuators is not None:
                elev_act, rud_act = actuators
                positions = [a.step(float(sc.elevon[i])) for i, a in enumerate(elev_act)]
                rud_pos = rud_act.step(float(sc.rudder))
            else:
                positions = sc.elevon
                rud_pos = float(sc.rudder)
            de = float(np.mean(positions))
            da = float((positions[0] - positions[2]) / 2.0)
            controls = {
                "de": de, "da": da, "dr": rud_pos,
                "throttle": (float(sc.throttle[0]), float(sc.throttle[1])),
            }

            # 로깅·엔벨로프 (스텝 전 상태 기준 — t와 정합)
            V, alpha, beta = wind_angles(vel_b)
            h = -float(pos[2])
            h_isa = min(max(h, ISA_MIN_ALT), ISA_STRATO1_TOP_ALT)
            mach = V / isa_atmosphere(h_isa).a
            eul = truth.euler()
            for name, val in (
                ("pn", pos[0]), ("pe", pos[1]), ("h", h),
                ("u", vel_b[0]), ("v", vel_b[1]), ("w", vel_b[2]),
                ("p", omega[0]), ("q", omega[1]), ("r", omega[2]),
                ("phi", eul[0]), ("theta", eul[1]), ("psi", eul[2]),
                ("V", V), ("alpha", alpha), ("beta", beta), ("mach", mach),
                ("fuel", fuel), ("de", de), ("da", da), ("dr", rud_pos),
                ("thr_l", controls["throttle"][0]), ("thr_r", controls["throttle"][1]),
            ):
                sig[name][k] = val
            sig["alpha_margin"][k] = (
                np.nan if self.fcl.alpha_margin is None else self.fcl.alpha_margin
            )
            sig["limiter_active"][k] = self.fcl.limiter_active
            # 지면 접촉 — 위(제어 틱 전)에서 이미 잰 값을 그대로 기록한다. 두 번 재면
            # 유도가 본 접지와 화면이 보는 접지가 갈릴 수 있다.
            if gs is not None:
                sig["wow"][k] = gs["wow"]
                sig["n_gear"][k] = gs["n_total"]
            else:
                sig["n_gear"][k] = np.nan  # 착륙장치 미장착 — 0이 아니라 미계측
            sig["on_rail"][k] = on_rail
            # 사출 하중은 레일 위에서만 존재한다 — 이탈 후 0이 아니라 NaN이면
            # "하중이 없다"와 "레일이 없다"가 섞인다. 레일 밖은 0이 맞다(가속 없음).
            sig["launch_gx"][k] = self.launch.launch_gx if on_rail else 0.0
            # 명령 사슬 계측 — 유도 명령은 cmd에서, 법칙 내부는 그래프 계측 창구에서.
            # 둘 다 제어주기(n_ctrl)마다만 갱신되므로 사이 스텝은 직전 값이 유지된다
            # (de/da/dr과 같은 규약 — 제로홀드가 아니라 실제로 그 값이 유지된 것).
            # 프로브가 없는 형상(리미터 미장착 등)은 0이 아니라 NaN — 계측되지 않은
            # 것과 값이 0인 것을 화면에서 구분해야 한다.
            law_sig = self.fcl.last_signals
            for name in _CHAIN_SIGNALS:
                if name.startswith("cmd_"):
                    sig[name][k] = getattr(cmd, name[4:])
                elif name.endswith("_on"):
                    # 축 활성 플래그 — 유도 명령의 것 그대로 (법칙 그래프 입력과 동일)
                    sig[name][k] = float(bool(getattr(cmd, name)))
                else:
                    sig[name][k] = law_sig.get(name, np.nan)
            modes.append(cmd.mode)
            if self.stall_table is not None:
                stall_margin[k] = float(self.stall_table.interp(mach=mach)) - alpha
            for var, (lo, hi) in self.db_ranges.items():
                val = {"alpha": alpha, "beta": beta, "mach": mach}[var]
                flags[var][k] = (val < lo) or (val > hi)
            if self.min_altitude is not None:
                flags["altitude"][k] = h < self.min_altitude

            # 발산 런 조기 종료 — ISA 범위 이탈 직전 절단해 부분 결과·엔벨로프를
            # 보존한다 (RK4 부단계에서 isa_atmosphere 예외로 전체 손실 방지)
            if not (ISA_MIN_ALT + 10.0 < h < ISA_STRATO1_TOP_ALT - 10.0):
                aborted = "alt_out_of_range"
                n_done = k + 1
                break

            # 진행률·협조적 취소 (M13) — 절단 경로 재사용으로 부분 결과 보존
            if (
                on_progress is not None
                and (k + 1) % progress_stride == 0
                and on_progress(k + 1, n_steps)
            ):
                aborted = "cancelled"
                n_done = k + 1
                break

            # 플랜트 적분 — 준정적 질량·관성 갱신 후 RK4 (ZOH 제어)
            m, _cg, J = self.aircraft.fuel_mass.at(fuel)
            rb.set_mass_inertia(m, J)

            def fm(xx):
                F, M, _m, _J = self.aircraft.fm(
                    xx[VEL], xx[OMEGA], xx[QUAT], -float(xx[POS][2]), controls, fuel,
                    pos_n=xx[POS], ground_elev=self.ground_elev,
                )
                return F, M

            t_next = t + self.dt_plant
            if on_rail:
                # **레일 구간은 적분하지 않는다.** 기체가 레일에 물려 자세·횡방향이
                # 구속된 1자유도 등가속 운동이라 해석해가 닫힌 형태로 있다. 데모
                # 사출은 0.245 s뿐이라 dt 0.01이면 25스텝인데, 그걸 RK4로 근사할
                # 이유가 없다. 레일이 주는 구속 반력은 fm에 들어가지 않는다 —
                # 들어갈 자리가 없어서가 아니라, 구속을 힘으로 흉내내면 매우 뻣뻣한
                # 스프링이 되어 같은 시간을 훨씬 잘게 쪼개야 하기 때문이다.
                rail = self.launch
                if t_next < rail.exit_time:
                    x = pack(*rail.state_at(0.5 * rail.accel * t_next * t_next))
                else:
                    # 이탈 시각이 스텝 경계에 떨어지지 않는다 — 이탈 상태에서 **남은
                    # 시간만** 자유비행으로 적분한다. 다음 스텝 경계까지 통째로
                    # 레일에 두면 최대 dt만큼 늦게 놓여 81.5 m/s에서 0.8 m가 밀린다.
                    x = pack(*rail.state_at(rail.length))
                    rem = t_next - rail.exit_time
                    if rem > 0.0:
                        x = rb.step(x, fm, rem)
                    on_rail = False
                    launch_exit_t = rail.exit_time
            else:
                x = rb.step(x, fm, self.dt_plant)
            if self.fuel_flow > 0.0:
                burn = self.fuel_flow * float(np.mean(sc.throttle)) * self.dt_plant
                fuel = max(fuel - burn, 0.0)

        # 완주 시 done==total 최종 콜백 보장 (스트라이드가 n_steps를 나누지
        # 못하는 경우 보충 — 반환값은 무의미하므로 무시)
        if aborted is None and on_progress is not None and n_steps % progress_stride != 0:
            on_progress(n_steps, n_steps)

        if n_done < n_steps:
            sig = {k2: v[:n_done] for k2, v in sig.items()}
            modes = modes[:n_done]
            stall_margin = stall_margin[:n_done]
            flags = {k2: v[:n_done] for k2, v in flags.items()}
        sig["mode"] = modes
        t_arr = np.arange(n_done) * self.dt_plant
        envelope = self._envelope(t_arr, stall_margin, flags, sig["h"])
        phases = self._phase_times(t_arr, sig, launch_exit_t)
        return SimResult(
            t=t_arr,
            signals=sig,
            envelope=envelope,
            params_fingerprint=fingerprint,
            meta={
                "control_hz": self.control_hz,
                "dt_plant": self.dt_plant,
                "t_end": t_end,
                "nav": type(self.nav_model).__name__ if self.nav_model else "ideal",
                "actuators": self.actuator_params is not None,
                "case": tr.case.name,
                "aborted": aborted,
                "limits": self._effector_limits(actuators),
                "clamps": self._command_clamps(),
                "phases": phases,
            },
        )

    # 접지 후 "정지"로 치는 속도 [m/s] — 정칙화 마찰은 v→0에서 점근이라 정확히 0에
    # 닿지 않는다(plant/ground.py §마찰). 0을 기다리면 영원히 안 오므로 문턱이 필요하다.
    STOP_SPEED = 0.5

    def _phase_times(self, t_arr, sig, launch_exit_t) -> dict:
        """비행 단계 시각 — 이탈·접지·정지. **없으면 None**이지 0이 아니다.

        0으로 채우면 "t=0에 접지했다"가 되어, 착륙하지 않은 런이 완벽한 착륙으로
        읽힌다(01 §4.2 판정 불가를 0으로 위장하지 않는다와 같은 자리). 소비자는
        None을 "그 일이 일어나지 않았다"로 읽으면 된다.
        """
        out = {"launch_exit_t": launch_exit_t, "touchdown_t": None, "stop_t": None}
        wow = sig["wow"]
        if len(t_arr) == 0 or self.aircraft.ground is None:
            return out
        # 접지 = 떠 있다가 닿은 첫 순간. 지상에서 출발한 런의 첫 샘플은 접지가 아니다
        airborne = ~wow
        if airborne.any():
            after = np.flatnonzero(wow[int(np.argmax(airborne)):])
            if after.size:
                i = int(np.argmax(airborne)) + int(after[0])
                out["touchdown_t"] = float(t_arr[i])
                # 정지 = 접지 이후 속도가 문턱 아래로 처음 내려간 순간 (접지 상태 유지)
                slow = np.flatnonzero((sig["V"][i:] < self.STOP_SPEED) & wow[i:])
                if slow.size:
                    out["stop_t"] = float(t_arr[i + int(slow[0])])
        return out

    def _effector_limits(self, actuators) -> dict:
        """이 런의 판정 기준선 — 타면 위치 한계와 작동기 rate 한계.

        신호가 아니라 **기준선**이다. 타각 듀티(analysis/duty.py)는 "얼마나
        움직였나"뿐 아니라 "한계에 얼마나 붙어 있었나"를 세는데, 그러려면 한계값이
        결과와 함께 다녀야 한다 — 저장된 결과만 보고도 포화 판정이 되도록.
        (없으면 소비자가 파라미터를 따로 들고 와 맞춰야 하고, 어긋나면 조용히
        틀린 포화율이 나온다.)

        미장착·미상은 0이 아니라 None — "한계가 0"과 "한계를 모른다"는 다르다.
        """
        mixer = getattr(self.fcl, "mixer", None)
        out = {}
        for name in ("elevon_lo", "elevon_hi", "rudder_lo", "rudder_hi"):
            v = getattr(mixer, name, None)
            out[name] = None if v is None else float(v)
        # 작동기 미장착이면 명령 직결 — rate 한계라는 것이 없다 (무제한이 아니라 부재)
        out["rate_max"] = float(actuators[0][0].rate_max) if actuators else None
        return out

    def _command_clamps(self) -> dict:
        """법칙 축 출력·적분기 클램프 기준선 — `_effector_limits`와 같은 이유로 동봉.

        진단(pipeline/diagnose)이 "적분기가 클램프에 주차했는가"(와인드업)·"AP 축
        명령이 한계에 붙었는가"를 저장된 결과만으로 판정하려면 클램프 값이 결과와
        함께 다녀야 한다. 적분기 클램프 = 축 출력 한계(PID 내부 안티와인드업,
        fcl/scas.py). 속도축 [0,1]·헤딩축 ±phi_max는 그래프 조립 상수다
        (fcl/graphs.py autopilot_nodes). 미상은 None — "한계가 없다"가 아니다.
        """
        scas = getattr(self.fcl, "scas", None)
        ap = getattr(self.fcl, "autopilot", None)
        out = {}
        scas_cfg = getattr(scas, "cfg", {}) or {}
        for axis in ("pitch", "roll", "yaw"):
            cfg = scas_cfg.get(axis)
            out[axis] = (
                None if cfg is None
                else {"lo": float(cfg["out_lo"]), "hi": float(cfg["out_hi"])}
            )
        cfg = getattr(ap, "cfg", None)
        if cfg is None:
            out["alt"] = out["spd"] = out["hdg"] = None
        else:
            out["alt"] = {"lo": float(cfg["theta_lo"]), "hi": float(cfg["theta_hi"])}
            out["spd"] = {"lo": 0.0, "hi": 1.0}
            out["hdg"] = {"lo": -float(cfg["phi_max"]), "hi": float(cfg["phi_max"])}
        return out

    def _envelope(self, t_arr, stall_margin, flags, h_arr) -> dict:
        """엔벨로프 요약 (02 §6.1) — 최악 실속 마진 + 최저 고도 + 이탈 플래그.

        stall_margin = α_stall(mach) − α (참값 기준, 보호마진 미차감) —
        signals["alpha_margin"](리미터 내부값: 항법 추정 α·마진 차감)과 구분.
        flags는 DB 유효범위(alpha·beta·mach)와 기준면 여유(altitude)를 함께 담는다
        — any_flag는 "이 런에 볼 것이 있었는가"의 단일 요약이다.
        """
        env = {"stall_margin": stall_margin, "flags": flags}
        if self.stall_table is not None and len(t_arr):
            i = int(np.nanargmin(stall_margin))
            env["worst_margin"] = float(stall_margin[i])
            env["worst_margin_t"] = float(t_arr[i])
        # 최저 고도는 감시 여부와 무관하게 보고 — 플래그가 안 떠도 여유가 얼마였는지
        if len(t_arr):
            j = int(np.argmin(h_arr))
            env["min_alt"] = float(h_arr[j])
            env["min_alt_t"] = float(t_arr[j])
        any_arr = None
        for arr in flags.values():
            any_arr = arr if any_arr is None else (any_arr | arr)
        env["any_flag"] = bool(np.any(any_arr)) if any_arr is not None else False
        env["first_flag_t"] = (
            float(t_arr[int(np.argmax(any_arr))]) if env["any_flag"] else None
        )
        return env
