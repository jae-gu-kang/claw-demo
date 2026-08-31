"""웨이포인트 경로추종 — LOS [기본값], 레지스트리 교체 가능 컴포넌트 (03 M8).

LOS: 현 위치→활성 웨이포인트 방위각을 헤딩 명령으로. 도달 반경 진입 시 다음
웨이포인트로 전환(반경 내 연쇄 스킵 허용), 소진 시 done=True + 마지막 헤딩
유지. L1·벡터필드 등 대안은 같은 step(nav)->(heading, alt, done) 계약으로 등록
[TBD 01 §3.3 — 경로추종 알고리즘 선정].

웨이포인트는 NED 수평면 (n, e)[m] 열이고, **고도를 함께 주면 세로 프로파일도
경로가 낸다** (n, e, alt)[m]. 종전에는 고도가 모드 테이블 전담이었으나(M8 분업:
경로는 헤딩만), 구간마다 고도를 다르게 주려면 구간 수만큼 모드를 적어야 했다 —
사용자 요청으로 경로가 고도 명령도 내도록 확장했다(01 §3.3).

**모드 테이블은 여전히 출처를 고르는 쪽이다**: heading과 똑같이 `alt="path"`인
모드에서만 이 값이 쓰인다(guidance.py). 새 우선순위 규칙을 만들지 않고 기존
선택 규약을 그대로 한 축 더 쓰는 것이라, "경로와 모드 중 누가 이기나"라는 물음이
생기지 않는다.

고도 명령은 **구간 선형 보간**이다 — 활성 구간의 시작 고도에서 목표 고도까지
남은 수평거리 비율로 잇되, 램프는 **도달 반경 경계**에서 끝난다(전환이 그 자리에서
일어나므로 명령이 연속이고, 도착할 때 이미 목표 고도다 — _leg_alt 참조).
활성 웨이포인트의 고도를 곧바로 명령하면(계단) 화면의 세로 프로파일(거리-고도
꺾은선)과 실제 명령이 다른 것을 그리게 된다. 첫 구간의 시작 고도는 **첫 스텝의
기체 고도**다: 출발점은 웨이포인트가 아니므로 계획에 없고, 기체가 실제로 있는
곳에서 시작해야 첫 구간이 계단이 되지 않는다.
"""

import math

from claw.blocks.base import Block
from claw.params.param import ParamDef


class LosPath(Block):
    NAME = "LOS"
    PARAM_DEFS = (ParamDef("accept_radius", 200.0, "m", "웨이포인트 도달 반경", lo=1e-9),)

    def __init__(self, waypoints=(), accept_radius: float = 200.0):
        if accept_radius <= 0:
            raise ValueError(f"accept_radius는 양수여야 함: {accept_radius}")
        self.accept_radius = accept_radius
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
        while self._idx < len(self._wps):
            wn, we = self._wps[self._idx]
            dn, de = wn - n, we - e
            rem = math.hypot(dn, de)
            if rem <= self.accept_radius:
                self._from = (wn, we, self._alts[self._idx] if self._has_alt else None)
                self._idx += 1
                continue
            self._last_hdg = math.atan2(de, dn)
            if self._has_alt:
                self._last_alt = self._leg_alt(rem)
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

    def _leg_alt(self, rem: float) -> float:
        """활성 구간의 선형 고도 — 시작 고도에서 목표까지 남은 거리 비율로.

        **램프는 도달 반경 경계에서 끝난다** (웨이포인트 중심이 아니라). 전환은
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
        denom = seg - self.accept_radius
        frac = (
            1.0 if denom <= 0.0
            else min(1.0, max(0.0, 1.0 - (rem - self.accept_radius) / denom))
        )
        return fa + (wa - fa) * frac
