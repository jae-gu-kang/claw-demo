"""웨이포인트 경로추종 — LOS [기본값], 레지스트리 교체 가능 컴포넌트 (03 M8).

LOS: 현 위치→활성 웨이포인트 방위각을 헤딩 명령으로. 도달 반경 진입 시 다음
웨이포인트로 전환(반경 내 연쇄 스킵 허용), 소진 시 done=True + 마지막 헤딩
유지. L1·벡터필드 등 대안은 같은 step(nav)->(heading, alt, done) 계약으로 등록
[TBD 01 §3.3 — 경로추종 알고리즘 선정].

웨이포인트는 NED 수평면 (n, e)[m] 열이고, **고도를 함께 주면 세로 프로파일도
경로가 낸다** (n, e, alt)[m]. 종전에는 고도가 모드 테이블 전담이었으나(M8 분업:
경로는 헤딩만), 구간마다 고도를 다르게 주려면 구간 수만큼 모드를 적어야 했다 —
사용자 요청으로 경로가 고도 명령도 내도록 확장했다(01 §3.3).

**순수추적은 선회 반경보다 급한 꺾임을 못 난다** — 엔진에는 그것을 다루는 장치가
둘 있다. 셋째(제출 전 기하 판정)는 화면 몫이라 여기 없다 —
01 §3.3 「LOS의 기하 한계」가 셋의 자리를 함께 적는다.

§선회 예상 전환 (fly-by) — `bank_max`
    도달 반경만으로 전환하면 기체는 꺾임점을 **지나친 뒤** 되돌아온다. 실기
    오토파일럿처럼 꺾임 **앞에서** 미리 전환한다: 선회 반경 R = V²/(g·tan φ_max)
    에서 예상 거리 L = R·tan(Δψ/2)이고, 유효 포획 반경은 max(도달 반경, L)이다.
    `bank_max`가 0(기본)이면 **선회 능력을 모른다는 뜻이라 예상 전환을 하지
    않는다** — 없는 값을 지어내지 않는 자리다. 서버 `_build`가 오토파일럿의
    실제 `phi_max`를 그대로 넘겨 실행 경로에서는 늘 켜진다(02 §5.5 — 웹·서버가
    기본값을 재기술하는 것이 아니라 **두 실값을 잇는다**).

§궤도 고착 탈출 — 안전망
    그래도 못 잡는 배치가 있다(도달 반경 < 선회 반경인데 꺾임이 급한 경우).
    순수추적은 목표를 중심으로 **반경 R의 원을 돌며 영영 수렴하지 않는다** —
    실측: 88 m/s·φ_max 0.7(R≈938 m)에서 1 km 간격 직각 웨이포인트를 주면 400 s
    동안 5.4바퀴를 돌고 `path_done`이 오지 않아 미션이 끝나지 않았다. 활성
    웨이포인트의 **방위각 누적 변화**가 한 바퀴(2π)에 닿으면 그 점을 순수추적으로는
    잡을 수 없다고 판정하고 다음으로 넘긴다. 2π는 건강한 미션에서 절대 나오지
    않는 값이라 안전망이 정상 비행을 건드리지 않는다.

    **넘긴 사실은 조용히 묻지 않는다** — `escapes`에 웨이포인트 인덱스(0 기준)가
    쌓이고 시뮬 결과 `meta["path_escapes"]`로 실려 화면이 "이 점은 못 잡고
    넘어갔다"를 말한다. 미션이 끝나는 것과 계획대로 난 것은 다르다.

**모드 테이블은 여전히 출처를 고르는 쪽이다**: heading과 똑같이 `alt="path"`인
모드에서만 이 값이 쓰인다(guidance.py). 새 우선순위 규칙을 만들지 않고 기존
선택 규약을 그대로 한 축 더 쓰는 것이라, "경로와 모드 중 누가 이기나"라는 물음이
생기지 않는다.

고도 명령은 **구간 선형 보간**이다 — 활성 구간의 시작 고도에서 목표 고도까지
남은 수평거리 비율로 잇되, 램프는 **유효 포획 반경 경계**에서 끝난다(전환이 그
자리에서 일어나므로 명령이 연속이고, 도착할 때 이미 목표 고도다 — _leg_alt 참조).
예상 전환이 켜지면 그 경계가 도달 반경보다 바깥이므로 램프도 함께 앞당겨진다.
활성 웨이포인트의 고도를 곧바로 명령하면(계단) 화면의 세로 프로파일(거리-고도
꺾은선)과 실제 명령이 다른 것을 그리게 된다. 첫 구간의 시작 고도는 **첫 스텝의
기체 고도**다: 출발점은 웨이포인트가 아니므로 계획에 없고, 기체가 실제로 있는
곳에서 시작해야 첫 구간이 계단이 되지 않는다.
"""

import math

from claw.blocks.base import Block
from claw.common.constants import G0
from claw.params.param import ParamDef

# 궤도 고착 판정 — 활성 웨이포인트 방위각을 **한 바퀴** 쓸면 순수추적으로는 못 잡는다.
# 한 바퀴보다 작게 잡으면 정상 선회가 걸린다(급한 꺾임 하나가 π를 넘길 수 있다).
_ORBIT_SWEEP = 2.0 * math.pi
# 예상 전환에 쓰는 선회각 상한 — tan(Δψ/2)가 Δψ→π에서 발산한다. 아래 구간 길이
# 상한이 실제로는 먼저 걸리지만, 유한하지 않은 중간값을 만들지 않는다.
_TURN_MAX = 0.9 * math.pi
# 이보다 작은 꺾임은 예상 전환할 것이 없다 (직진 구간의 수치 잡음)
_TURN_EPS = 1e-6


def _wrap_pi(a: float) -> float:
    """(-π, π] 래핑 — 이 모듈은 numpy를 안 쓴다(common.attitude.wrap_pi의 스칼라 짝)."""
    return math.remainder(a, 2.0 * math.pi)


class LosPath(Block):
    NAME = "LOS"
    PARAM_DEFS = (
        ParamDef("accept_radius", 200.0, "m", "웨이포인트 도달 반경", lo=1e-9),
        # 0 = 선회 능력 미지 → 예상 전환 없음. hi는 Autopilot phi_max와 같은 상한이다
        # (같은 물리량이라 한쪽만 넓으면 넘겨받을 수 없는 값이 생긴다).
        ParamDef("bank_max", 0.0, "rad", "선회 예상 전환용 뱅크 한계 (0=예상 전환 끔)",
                 lo=0.0, hi=1.5),
    )

    def __init__(self, waypoints=(), accept_radius: float = 200.0,
                 bank_max: float = 0.0):
        if accept_radius <= 0:
            raise ValueError(f"accept_radius는 양수여야 함: {accept_radius}")
        if not 0.0 <= bank_max <= 1.5:  # ParamDef hi와 일치 (Autopilot phi_max와 같은 축)
            raise ValueError(f"bank_max는 [0, 1.5] 필요 (ParamDef hi): {bank_max}")
        self.accept_radius = accept_radius
        self.bank_max = float(bank_max)
        self.set_waypoints(waypoints)

    def set_waypoints(self, waypoints) -> None:
        """(n, e) 또는 (n, e, alt) 열 — 고도는 **전부 있거나 전부 없거나**.

        섞인 목록을 받아 없는 쪽을 0이나 이웃 값으로 메우면, 화면의 세로
        프로파일이 사용자가 넣지 않은 고도를 넣은 것처럼 그린다. 판정 불가를
        정상으로 위장하지 않는 것과 같은 자리라 구성 시점에 거부한다.
        """
        rows = [tuple(w) for w in waypoints]
        for i, w in enumerate(rows):
            if len(w) not in (2, 3):
                raise ValueError(f"웨이포인트 {i}: (n, e) 또는 (n, e, alt) 필요 — {w!r}")
        with_alt = [len(w) == 3 for w in rows]
        if any(with_alt) and not all(with_alt):
            missing = [i for i, ok in enumerate(with_alt) if not ok]
            raise ValueError(
                "웨이포인트 고도는 전부 있거나 전부 없어야 함 — "
                f"고도 없는 항목 {missing}"
            )
        self._has_alt = bool(rows) and all(with_alt)
        self._wps = tuple((float(w[0]), float(w[1])) for w in rows)
        self._alts = tuple(float(w[2]) for w in rows) if self._has_alt else ()
        self.reset()

    @property
    def has_alt(self) -> bool:
        """세로 프로파일을 낼 수 있는가 — guidance가 alt="path" 구성 검증에 쓴다."""
        return self._has_alt

    def reset(self, state=None) -> None:
        self._idx = 0
        self._last_hdg = None  # 헤딩 미계산 상태 — 소진 시 현재 침로로 시드
        self._last_alt = None  # 고도 명령 미계산 상태 — 소진 시 마지막 값 유지
        # 활성 구간의 시작점 — 첫 구간은 (첫 스텝의 기체 위치·고도)로 채워진다
        self._from = None
        # 궤도 고착 판정 상태 — 웨이포인트를 넘길 때마다 새로 센다
        self._sweep = 0.0
        self._brg_prev = None
        # 순수추적으로 못 잡고 넘긴 웨이포인트 인덱스(0 기준). 런마다 새로 쌓인다 —
        # reset이 지우지 않으면 **직전 런의 사고가 이번 결과 meta에 실린다**
        self.escapes = ()

    def step(self, nav):
        """NavOutput → (heading_cmd [rad], alt_cmd [m] | None, done).

        done 후엔 마지막 헤딩 유지 + 고도는 **마지막 웨이포인트 고도로 정착**
        (소진은 그 웨이포인트 반경 진입이므로 램프의 끝점이 곧 계획의 종단이다).
        헤딩을 한 번도 계산하기 전에
        소진되면(빈 리스트, 반경 내 시작 등) 정북(0)이 아니라 현재 침로를
        명령한다 — 조용한 급선회 방지. alt_cmd는 고도 없는 웨이포인트 열에서
        항상 None이다(없는 명령을 0으로 위장하지 않는다).
        """
        n, e = float(nav.pos_n[0]), float(nav.pos_n[1])
        if self._from is None:
            # 출발점은 웨이포인트가 아니다 — 기체가 실제로 있는 자리가 첫 구간의 시작
            self._from = (n, e, -float(nav.pos_n[2]))
        v_h = math.hypot(float(nav.vel_n[0]), float(nav.vel_n[1]))
        while self._idx < len(self._wps):
            wn, we = self._wps[self._idx]
            dn, de = wn - n, we - e
            rem = math.hypot(dn, de)
            brg = math.atan2(de, dn)
            r_cap = self._capture_radius(v_h)
            if rem <= r_cap:
                self._advance()
                continue
            # 방위각 누적은 **활성 웨이포인트마다** 센다 — `_advance`가 리셋하므로
            # 이 while이 여러 점을 건너뛰어도 다음 점은 새 시드에서 시작한다
            if self._orbited(brg):
                self._advance(escaped=True)
                continue
            self._last_hdg = brg
            if self._has_alt:
                self._last_alt = self._leg_alt(rem, r_cap)
            return self._last_hdg, self._last_alt, False
        if self._last_hdg is None:
            self._last_hdg = math.atan2(float(nav.vel_n[1]), float(nav.vel_n[0]))
        if self._has_alt:
            # 소진 = 마지막 웨이포인트 반경 진입 — **그 고도로 정착**한다.
            # 헤딩처럼 "마지막 명령 유지"로 두면 램프 중간값에 얼어붙어 계획보다
            # 높거나 낮게 수평비행한다(실측: 800→400 구간에서 600에 멈춤).
            # 램프의 끝점이 곧 이 값이므로 정착이 곧 계획의 종단이다
            self._last_alt = self._alts[-1]
        return self._last_hdg, self._last_alt, True

    def _advance(self, escaped: bool = False) -> None:
        """활성 웨이포인트를 마감하고 다음으로 — 포획이든 궤도 탈출이든 같은 자리다.

        `escaped`여도 `_from`은 **그 웨이포인트**로 둔다. 기체가 거기 닿지 않은 것은
        맞지만 다음 구간의 고도 램프가 기대는 것은 실제 궤적이 아니라 **계획 기하**라,
        여기서 기체 위치를 쓰면 못 잡은 점을 지나온 척 램프를 다시 긋게 된다 —
        계획과 실제가 갈렸다는 사실 자체는 `escapes`가 들고 있다.
        """
        if escaped:
            self.escapes = (*self.escapes, self._idx)
        wn, we = self._wps[self._idx]
        self._from = (wn, we, self._alts[self._idx] if self._has_alt else None)
        self._idx += 1
        self._sweep = 0.0
        self._brg_prev = None

    def _orbited(self, brg: float) -> bool:
        """활성 웨이포인트 방위각이 한 바퀴를 쓸었는가 — 누적하며 판정한다.

        누적은 래핑한 **증분의 합**이다. 절대 방위각의 차로 재면 ±π 경계에서 한
        바퀴가 0으로 접혀 영영 안 걸린다.
        """
        if self._brg_prev is not None:
            self._sweep += _wrap_pi(brg - self._brg_prev)
        self._brg_prev = brg
        return abs(self._sweep) >= _ORBIT_SWEEP

    def _capture_radius(self, v_h: float) -> float:
        """유효 포획 반경 — max(도달 반경, 선회 예상 거리).

        도달 반경이 바닥인 이유: 예상 거리는 꺾임이 완만하면 0에 가까워지는데,
        그때 사용자가 지정한 도달 반경까지 무시하면 **설정이 조용히 꺼진다**.
        """
        return max(self.accept_radius, self._lead(v_h))

    def _lead(self, v_h: float) -> float:
        """선회 예상 거리 L = R·tan(Δψ/2) — 꺾임 앞에서 미리 트는 fly-by 거리.

        **0을 내는 자리가 넷이다.** ① `bank_max`가 0 — 선회 능력을 모른다 ②
        마지막 웨이포인트 — 다음 구간이 없으니 꺾임이 없다(fly-over가 맞다)
        ③ 속도가 0이거나 비유한 — R을 못 잰다 ④ 꺾임각이 0 — 틀 것이 없다.
        어느 쪽도 "예상 전환이 꺼진 것"이지 오류가 아니므로 조용히 도달 반경으로
        돌아간다.

        상한이 둘이다. 선회각은 `_TURN_MAX`에서 자른다(tan이 π에서 발산).
        거리는 **양쪽 구간의 절반**에서 자른다 — 예상 거리가 구간 절반을 넘으면
        앞뒤 전환이 서로를 삼켜 웨이포인트 하나가 통째로 사라진다. 잘렸다는 것은
        그 꺾임이 이 속도에서 계획대로는 못 나는 각이라는 뜻이고, 그 판정은
        화면이 제출 전에 따로 낸다(`web/js/lib/wpcheck.js`).
        """
        if self.bank_max <= 0.0 or self._idx + 1 >= len(self._wps):
            return 0.0
        if not math.isfinite(v_h) or v_h <= 0.0:
            return 0.0
        wn, we = self._wps[self._idx]
        nn, ne = self._wps[self._idx + 1]
        fn, fe = self._from[0], self._from[1]
        leg_in = math.hypot(wn - fn, we - fe)
        leg_out = math.hypot(nn - wn, ne - we)
        if leg_in <= 0.0 or leg_out <= 0.0:
            return 0.0
        turn = abs(_wrap_pi(math.atan2(ne - we, nn - wn) - math.atan2(we - fe, wn - fn)))
        if turn < _TURN_EPS:
            return 0.0
        radius = v_h * v_h / (G0 * math.tan(self.bank_max))
        lead = radius * math.tan(min(turn, _TURN_MAX) / 2.0)
        return min(lead, 0.5 * leg_in, 0.5 * leg_out)

    def begin_alt_leg(self, nav) -> None:
        """고도 축이 경로를 잡는 **그 순간**부터 활성 구간의 램프를 다시 잇는다.

        `_from`은 첫 step에서 한 번 박히는데, 지상 출발이 생긴 뒤로 그 자리는
        **발사대 위(h≈1.2 m)**다. 고도 축은 한참 뒤 순항에서야 경로를 잡으므로,
        램프를 발사대에서부터 재면 기체가 이미 올라온 고도와 무관한 값을 명령한다
        — 실측: WP (10000, 0, 300)·도달반경 300에서 상승 이탈 250 m인 기체에
        62.8 m를 명령한다(187 m 낙차). 그대로 두면 고도 루프가 급강하를 지시한다.

        축을 잡는 순간 "여기서부터 목표까지"로 다시 그으면 명령이 연속이고,
        실제 VNAV가 모드 진입 시 경로를 다시 계산하는 것과 같은 규약이다.
        축을 껐다 켜면 그때마다 다시 긋는다 — 재진입은 곧 재계획이다.

        헤딩에는 대응물이 없다: LOS 방위는 매 스텝 현재 위치에서 다시 재므로
        시작점을 기억하지 않는다. 고도만 **구간 시작점을 들고 있는** 축이다.

        **연속인 것은 값이지 기울기가 아니다.** 여기서 다시 그으면 seg = rem이 되므로,
        도달 반경 **바로 바깥**에서 축을 잡으면 유효 램프(seg − r)가 0에 수렴해 남은
        고도차를 몇 스텝 만에 밀어낸다 — 실측: rem 305 m·r 300·목표 800 m·현재 250 m
        에서 진입 명령은 250.0으로 연속이지만 이후 10 ms마다 346.8 → 443.6 → … → 734.0
        으로 550 m를 60 ms에 훑는다. 종전(발사대 기준)에는 그 자리에서 frac ≈ 1이라
        **곧바로 800을 명령**했으므로(실측 799.26부터 시작) 나빠진 것은 아니다.
        다만 AP 명령필터가 흡수하는 것은 **진입 스텝의 낡은 한 표본**이지 이쪽이
        아니다 — 여기서는 60 ms 뒤부터 목표 고도가 계속 서 있으므로 필터는 흡수가
        아니라 추종한다. 같은 필터의 두 다른 거동이라 한 문장으로 묶지 않는다.
        구간 길이에 하한을 두는 것은 "계획에 없는 램프를 지어내는" 쪽이라 하지 않는다
        — 반경 코앞에서 세로 축을 켜는 미션이 애초에 성립하지 않는다는 사실을
        화면이 보게 두는 편이 낫다 (리뷰 지적) [TBD — 그 구성을 구성 시점에 경고할 것].
        """
        if not self._has_alt:
            return  # 고도 없는 열 — 잡을 램프가 없다 (구성 시점에 이미 거부된다)
        self._from = (
            float(nav.pos_n[0]), float(nav.pos_n[1]), -float(nav.pos_n[2]),
        )

    def _leg_alt(self, rem: float, r_cap: float) -> float:
        """활성 구간의 선형 고도 — 시작 고도에서 목표까지 남은 거리 비율로.

        **램프는 유효 포획 반경 경계에서 끝난다** (웨이포인트 중심이 아니라).
        `r_cap`은 도달 반경이거나 그보다 큰 선회 예상 거리다 — 전환이 실제로
        일어나는 그 자리를 램프의 끝으로 삼아야 "도착할 때 이미 목표 고도"가
        예상 전환에서도 성립한다. 전환은
        반경 진입 순간에 일어나므로 중심 기준으로 이으면 램프가 목표에 닿기 전에
        끊기고, 다음 구간이 시작 고도를 wa로 잡는 순간 Δalt·r/seg 만큼 튄다 —
        구간 500 m·반경 200 m·Δ500 m에서 201 m 점프였다(리뷰 실측). 경계 기준이면
        전환 시점의 명령이 양쪽에서 같아 연속이고, 도착할 때 이미 목표 고도다.
        화면의 거리-고도 꺾은선도 이 모양을 그린다 — 웹 planProfile이 도달 반경을
        받아 마루 점을 하나 더 찍는다. 반경을 안 넘기면 중심끼리 곧게 이어져
        구간 내내 최대 Δalt·r/seg 만큼 어긋난다(그 폴백을 lib이 명기한다).

        비율은 [0, 1]로 자른다: 기체가 구간 밖(지나쳤거나 크게 벗어남)에 있으면
        rem이 구간 길이를 넘어 **계획에 없는 고도**로 외삽된다. 구간이 반경보다
        짧으면(denom ≤ 0) 이을 구간이 없으므로 곧바로 목표 고도다.

        _from의 고도는 항상 실수다 — 첫 스텝(89행)이거나, 고도 있는 웨이포인트를
        지나온 경우(95행, _has_alt가 참일 때만 이 함수가 불린다)뿐이다.
        """
        fn, fe, fa = self._from
        wn, we = self._wps[self._idx]
        wa = self._alts[self._idx]
        seg = math.hypot(wn - fn, we - fe)
        denom = seg - r_cap
        frac = (
            1.0 if denom <= 0.0
            else min(1.0, max(0.0, 1.0 - (rem - r_cap) / denom))
        )
        return fa + (wa - fa) * frac
