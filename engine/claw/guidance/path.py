"""웨이포인트 경로추종 — LOS [기본값], 레지스트리 교체 가능 컴포넌트 (03 M8).

LOS: 현 위치→활성 웨이포인트 방위각을 헤딩 명령으로. 도달 반경 진입 시 다음
웨이포인트로 전환(반경 내 연쇄 스킵 허용), 소진 시 done=True + 마지막 헤딩
유지. L1·벡터필드 등 대안은 같은 step(nav)->(heading, done) 계약으로 등록
[TBD 01 §3.3 — 경로추종 알고리즘 선정].

웨이포인트는 NED 수평면 (n, e)[m] 열 — 고도·속도는 모드 테이블 소관 (M8
분업: 경로는 헤딩만). 레지스트리 생성 시엔 set_waypoints()로 데이터 주입.
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
        wps = tuple((float(n), float(e)) for n, e in waypoints)
        self._wps = wps
        self.reset()

    def reset(self, state=None) -> None:
        self._idx = 0
        self._last_hdg = None  # 헤딩 미계산 상태 — 소진 시 현재 침로로 시드

    def step(self, nav):
        """NavOutput → (heading_cmd [rad], done). done 후엔 마지막 헤딩 유지.

        헤딩을 한 번도 계산하기 전에 소진되면(빈 리스트, 반경 내 시작 등)
        정북(0)이 아니라 현재 침로를 명령한다 — 조용한 급선회 방지.
        """
        n, e = float(nav.pos_n[0]), float(nav.pos_n[1])
        while self._idx < len(self._wps):
            wn, we = self._wps[self._idx]
            dn, de = wn - n, we - e
            if math.hypot(dn, de) <= self.accept_radius:
                self._idx += 1
                continue
            self._last_hdg = math.atan2(de, dn)
            return self._last_hdg, False
        if self._last_hdg is None:
            self._last_hdg = math.atan2(float(nav.vel_n[1]), float(nav.vel_n[0]))
        return self._last_hdg, True
