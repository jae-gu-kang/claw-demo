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
# 소비처: 구조도 재생 오버레이(배선마다 그 시각의 실제 값) — 이게 없으면 최종
# 타면과 피드백만 계측되어 명령 사슬 배선이 값 없이 남는다.
# 주의: 제어주기(n_ctrl)마다만 갱신되므로 사이 스텝은 직전 값을 유지한다 (de/da/dr 규약).
_CHAIN_SIGNALS = (
    "cmd_speed", "cmd_alt", "cmd_heading",  # 유도 → AP
    "theta_cmd", "phi_cmd",  # AP → α 리미터
    "theta_lim",  # 리미터 → SCAS (보호가 물리면 theta_cmd와 갈라진다)
    "pitch", "roll", "yaw",  # SCAS → 믹서
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
        # 기준면 여유 감시 [기본값 0 m = 해수면 MSL, 01 §2.5]. 지형·파고는 미모델이라
        # 이건 "지면 충돌 판정"이 아니라 특이 상황 표시 — 시뮬은 중단하지 않고 플래그만
        # 남긴다(엔벨로프 감시 항상 장착, 02 §6.1). None이면 감시 끔.
        self.min_altitude = float(min_altitude) if min_altitude is not None else None
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
        th0 = tr.state.euler()[1]
        de0 = float(tr.control.elevon[0])
        thr0 = float(tr.control.throttle[0])
        fuel = float(tr.case.fuel)

        x = pack(
            np.array([0.0, 0.0, -tr.case.alt]),
            tr.state.vel_b,
            tr.state.q_nb,
            np.zeros(3),
        )
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
            *_CHAIN_SIGNALS,
        )}
        sig["limiter_active"] = np.zeros(n_steps, dtype=bool)
        modes = []
        stall_margin = np.full(n_steps, np.nan)
        flag_keys = list(self.db_ranges)
        if self.min_altitude is not None:
            flag_keys.append("altitude")  # db_ranges와 구분 — DB 유효범위가 아니라 기준면 여유
        flags = {k: np.zeros(n_steps, dtype=bool) for k in flag_keys}

        sc = None
        aborted = None
        n_done = n_steps
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
            if k % self.n_ctrl == 0:
                cmd = self.guidance.step(nav)
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
            # 명령 사슬 계측 — 유도 명령은 cmd에서, 법칙 내부는 그래프 계측 창구에서.
            # 둘 다 제어주기(n_ctrl)마다만 갱신되므로 사이 스텝은 직전 값이 유지된다
            # (de/da/dr과 같은 규약 — 제로홀드가 아니라 실제로 그 값이 유지된 것).
            # 프로브가 없는 형상(리미터 미장착 등)은 0이 아니라 NaN — 계측되지 않은
            # 것과 값이 0인 것을 화면에서 구분해야 한다.
            law_sig = self.fcl.last_signals
            for name in _CHAIN_SIGNALS:
                if name.startswith("cmd_"):
                    sig[name][k] = getattr(cmd, name[4:])
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
                    xx[VEL], xx[OMEGA], xx[QUAT], -float(xx[POS][2]), controls, fuel
                )
                return F, M

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
            },
        )

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
