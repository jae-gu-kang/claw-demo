"""M5 지면 접촉 — 스키드 착륙장치·발사 레일 (01 §3.3.1 이륙·착륙 단계).

이 모듈이 엔진에 **지면**을 들여온다. 그 전까지 plant의 힘 합성은 공력+추진+중력
세 항뿐이었고(aircraft.fm), 기체는 h<0에서도 지면을 그대로 통과해 계속 날았다 —
sim.simulator의 min_altitude는 "지면 충돌 판정이 아니라 특이 상황 표시"라 플래그만
남길 뿐 기체를 받치지 않는다.

두 가지를 담는다:

- SkidGear   : 스키드 접촉점의 수직반력·마찰. **힘**이므로 aircraft.fm의 합성에 들어간다.
- LaunchRail : 발사 레일 위 운동. **구속**이므로 힘이 아니라 별도 적분 경로다 (아래 §레일).

**모멘트 기준점 이전 M += r×F가 여기서 처음 실제로 구현된다.** aero.py 머리말의
[TBD]는 *공력 DB 기준점*의 이전을 말하며, DB 축 규격이 확정되지 않아 여전히 미구현이다
— 여기서 해소되는 것은 **착륙장치 부분뿐**이다. 기어 접촉점 r_i는 기하로 정확히 아는
값이라 DB 규격과 무관하게 지금 쓸 수 있다. 절반만 된 상태임을 혼동하지 말 것.

§접촉 — 불연속이 아니라 뻣뻣한 연속력
    RK4는 한 스텝에 힘을 4번 평가한다(eom.rk4_step). h=0에서 끊기는 힘을 그대로 넣으면
    부단계가 지면 안팎을 오가며 적분 차수가 무너진다. 그래서 접촉을 스프링-댐퍼
    연속 근사로 둔다 — 침투 δ에 비례하는 반력이라 부단계마다 연속이다.
    강성은 "정지 침투량"으로 정한다: 무게 W를 δ_ref에서 받으려면 k_total = W/δ_ref.

§마찰 — 저속 부호 채터링 방지
    쿨롱 마찰 −μN·sign(v)는 v=0 근방에서 부호가 매 부단계 뒤집혀 적분을 깨뜨린다.
    v/(|v| + v_eps)로 정칙화한다. 대가로 **정지 마찰이 없다** — 경사면에 놓으면 아주
    느리게 미끄러진다. 평지 활주로에서 감속해 멈추는 용도에는 무해하고, 경사 지형이
    들어오면 재검토 대상 [TBD].
"""

import math

import numpy as np

from claw.common.attitude import euler_to_quat
from claw.common.constants import G0
from claw.common.frames import body_to_ned, ned_to_body

V_EPS_DEFAULT = 0.5  # [m/s] 마찰 방향 정칙화 속도 [기본값]


class SkidGear:
    """스키드 접촉점 집합 — 수직반력(스프링-댐퍼) + 미끄럼 마찰.

    contacts: 동체축 접촉점 위치 (n, 3) [m]. CG 기준, FRD (x 전방·y 우현·z 하방).
        좌·우 스키드를 각각 앞·뒤 2점으로 이산화하면 롤과 피치가 모두 나온다.
        좌우 2점만 두면 피치 자유도가 없어 접지 후 기수 내려앉음이 재현되지 않는다.
    k: 점당 접촉 강성 [N/m] — 총 강성은 k·n. δ_ref에서 무게를 받으려면 k = W/(n·δ_ref).
    c: 점당 접촉 감쇠 [N·s/m] — 임계감쇠 근처(ζ≈0.7)면 c ≈ 2ζ√(k·m/n).
    mu: 미끄럼 마찰계수 [-]. 바퀴가 아니라 스키드이므로 구름이 아닌 미끄럼 값.
    """

    def __init__(self, contacts, k, c, mu, v_eps=V_EPS_DEFAULT):
        r = np.asarray(contacts, dtype=float)
        if r.ndim != 2 or r.shape[1] != 3 or r.shape[0] < 1:
            raise ValueError(f"contacts는 (n,3) 이어야 함 (n≥1): {r.shape}")
        if not np.all(np.isfinite(r)):
            raise ValueError("contacts에 비유한값")
        if k <= 0:
            raise ValueError(f"접촉 강성은 양수여야 함: {k}")
        if c < 0:
            raise ValueError(f"접촉 감쇠는 음수 불가: {c}")
        if mu < 0:
            raise ValueError(f"마찰계수는 음수 불가: {mu}")
        if v_eps <= 0:
            raise ValueError(f"v_eps는 양수여야 함: {v_eps}")
        self.contacts = r
        self.k = float(k)
        self.c = float(c)
        self.mu = float(mu)
        self.v_eps = float(v_eps)

    @property
    def n_contacts(self) -> int:
        return int(self.contacts.shape[0])

    def _per_contact(self, pos_n, vel_b, q_nb, omega_b, elevation):
        """접촉점별 (침투 δ, 수직력 N, NED 힘) — forces와 contact_state의 공용 계산."""
        pos_n = np.asarray(pos_n, dtype=float)
        vel_b = np.asarray(vel_b, dtype=float)
        omega_b = np.asarray(omega_b, dtype=float)

        pen = np.zeros(self.n_contacts)
        normal = np.zeros(self.n_contacts)
        f_ned = np.zeros((self.n_contacts, 3))

        for i, r_b in enumerate(self.contacts):
            # 접촉점의 NED 위치·속도 (강체: v_point = v + ω×r)
            p_n = pos_n + body_to_ned(q_nb, r_b)
            v_n = body_to_ned(q_nb, vel_b + np.cross(omega_b, r_b))

            # NED z는 하방 +. 지면은 고도 elevation → 그 지점의 z = −elevation.
            # 침투 δ = (접촉점 z) − (지면 z) = p_n[2] + elevation, δ > 0 이면 파고든 것.
            delta = float(p_n[2]) + float(elevation)
            if delta <= 0.0:
                continue
            ddot = float(v_n[2])  # δ̇ — 가라앉는 중이면 +

            # 압축만 — 스키드는 지면을 끌어당기지 못한다. 되튈 때 감쇠항이 음수로
            # 끌어내리는 것도 여기서 잘린다.
            n_i = self.k * delta + self.c * ddot
            if n_i <= 0.0:
                continue

            # 마찰: 접촉점 수평 미끄럼 속도의 반대 방향. v/(|v|+v_eps) 정칙화.
            slip = np.array([v_n[0], v_n[1], 0.0])
            speed = float(np.linalg.norm(slip))
            f_fric = -self.mu * n_i * slip / (speed + self.v_eps)

            pen[i] = delta
            normal[i] = n_i
            f_ned[i] = f_fric
            f_ned[i, 2] = -n_i  # 수직반력은 NED 상방 = z 음수

        return pen, normal, f_ned

    def forces(self, pos_n, vel_b, q_nb, omega_b, elevation=0.0):
        """(NED 위치, 동체 속도, 자세, 각속도, 지면 고도) → (F_b, M_b).

        aero.forces·prop.forces와 같은 모양 — aircraft.fm이 네 번째 항으로 합성한다.
        접촉이 없으면 (0, 0)이라 자유비행에서는 아무 영향이 없다.
        """
        _pen, _n, f_ned = self._per_contact(pos_n, vel_b, q_nb, omega_b, elevation)
        force_b = np.zeros(3)
        moment_b = np.zeros(3)
        for i, r_b in enumerate(self.contacts):
            if not f_ned[i].any():
                continue
            f_b = ned_to_body(q_nb, f_ned[i])
            force_b += f_b
            moment_b += np.cross(r_b, f_b)  # ← M += r×F (착륙장치 부분)
        return force_b, moment_b

    def contact_state(self, pos_n, vel_b, q_nb, omega_b, elevation=0.0) -> dict:
        """접지 진단 — 스텝당 1회 기록용 (RK4 부단계에서는 부르지 않는다).

        wow      : 어느 접촉점이든 수직반력이 서 있으면 True (weight-on-skid)
        n_total  : 수직반력 합 [N]
        max_pen  : 최대 침투 [m] — 강성이 적절한지 보는 값
        """
        pen, normal, _f = self._per_contact(pos_n, vel_b, q_nb, omega_b, elevation)
        n_total = float(normal.sum())
        return {
            "wow": bool(n_total > 0.0),
            "n_total": n_total,
            "max_pen": float(pen.max()) if pen.size else 0.0,
        }

    def rest_penetration(self, weight) -> float:
        """모든 접촉점이 고르게 닿은 정지 상태의 침투량 [m] — δ = W/(n·k).

        지상 평형 초기해의 출발 추정값. 자세가 기울어 접촉이 고르지 않으면 실제 값과
        다르므로 평형 솔버의 시드로만 쓴다.
        """
        if weight <= 0:
            raise ValueError(f"무게는 양수여야 함: {weight}")
        return float(weight) / (self.n_contacts * self.k)


class LaunchRail:
    """발사 레일 — 레일 위 구속 운동 (01 §3.3.1 이륙).

    **레일 구간은 힘이 아니라 구속이다.** 기체는 레일에 물려 자세가 고정되고 위치는
    레일 축 스칼라 s 하나만 움직인다 — 6DOF 중 1자유도. 등가속 운동이라 해석해가
    닫힌 형태로 있으므로 RK4로 근사할 이유가 없다. 데모 기본값(레일 10 m·이탈 81.5 m/s)
    에서 사출은 0.245 s뿐이라 dt_plant 0.01이면 25스텝밖에 안 된다.

    accel은 **레일 축 순가속도**다 — 카타펄트 추력·중력의 레일 축 성분·항력이 이미
    합쳐진 값이며, 그 셋으로의 분해는 카타펄트 모델이 들어올 때 [TBD]. 그래서 이
    클래스가 내는 하중 지표(launch_gx)도 "기체가 겪는 레일 축 가속도"이지 카타펄트
    단독 하중이 아니다.

    azimuth  : 레일 방위 ψ [rad] (북 기준 시계방향, conventions.md)
    elev_deg : 레일 앙각 γ [rad] (상방 +)
    length   : 레일 길이 [m]
    origin_n : 레일 시작점 NED 위치 [m] — 기본은 원점(= 이륙점, conventions.md)
    """

    def __init__(self, length, elev_angle, azimuth=0.0, exit_speed=None, accel=None, origin_n=None):
        if length <= 0:
            raise ValueError(f"레일 길이는 양수여야 함: {length}")
        if not (-0.5 * math.pi < float(elev_angle) < 0.5 * math.pi):
            raise ValueError(f"레일 앙각은 ±90° 미만이어야 함: {elev_angle}")
        if (exit_speed is None) == (accel is None):
            # 둘 다 주면 어느 쪽이 이겼는지 화면이 말할 수 없고, 둘 다 없으면 운동이 없다.
            raise ValueError("exit_speed와 accel 중 정확히 하나를 지정해야 함")
        self.length = float(length)
        self.elev_angle = float(elev_angle)
        self.azimuth = float(azimuth)
        if exit_speed is not None:
            if exit_speed <= 0:
                raise ValueError(f"이탈 속도는 양수여야 함: {exit_speed}")
            self.exit_speed = float(exit_speed)
            self.accel = self.exit_speed**2 / (2.0 * self.length)
        else:
            if accel <= 0:
                raise ValueError(f"사출 가속도는 양수여야 함: {accel}")
            self.accel = float(accel)
            self.exit_speed = math.sqrt(2.0 * self.accel * self.length)
        self.origin_n = (
            np.zeros(3) if origin_n is None else np.asarray(origin_n, dtype=float).copy()
        )
        if self.origin_n.shape != (3,) or not np.all(np.isfinite(self.origin_n)):
            raise ValueError(f"origin_n은 유한한 (3,)이어야 함: {origin_n}")

    @property
    def exit_time(self) -> float:
        """정지에서 이탈까지 걸리는 시간 [s] — t = √(2L/a)."""
        return math.sqrt(2.0 * self.length / self.accel)

    @property
    def launch_gx(self) -> float:
        """레일 축 가속도 [g] — 사출 하중 지표. 판정 기준은 구조 한계 n_x_launch."""
        return self.accel / G0

    def direction(self):
        """레일 축 NED 단위벡터 — 앙각만큼 위를 보므로 z 성분이 음수다."""
        cg, sg = math.cos(self.elev_angle), math.sin(self.elev_angle)
        return np.array([cg * math.cos(self.azimuth), cg * math.sin(self.azimuth), -sg])

    def attitude(self):
        """레일 위 자세 쿼터니언 — φ=0, θ=레일 앙각, ψ=레일 방위로 물려 있다."""
        return euler_to_quat(0.0, self.elev_angle, self.azimuth)

    def state_at(self, s):
        """레일 축 거리 s [m] → (pos_n, vel_b, q_nb, omega_b).

        기체가 레일에 물려 있으므로 동체 x축이 곧 레일 축이다 → vel_b = (V, 0, 0).
        s는 [0, length]로 클램프하지 않는다 — 이탈 판정은 호출자(시뮬)가 한다.
        """
        if s < 0.0:
            raise ValueError(f"레일 축 거리는 음수 불가: {s}")
        speed = math.sqrt(2.0 * self.accel * float(s))
        pos_n = self.origin_n + self.direction() * float(s)
        return pos_n, np.array([speed, 0.0, 0.0]), self.attitude(), np.zeros(3)

    def advance(self, s, dt):
        """s에서 dt만큼 등가속 전진 → (s', V'). 해석해 그대로 (근사 아님)."""
        if dt < 0.0:
            raise ValueError(f"dt는 음수 불가: {dt}")
        v = math.sqrt(2.0 * self.accel * float(s))
        s_next = float(s) + v * dt + 0.5 * self.accel * dt * dt
        return s_next, v + self.accel * dt
