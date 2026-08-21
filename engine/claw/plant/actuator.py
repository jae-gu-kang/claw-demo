"""2차계 작동기 [기본값 가정값 시작, 01 §2.4] — 위치·속도 제한 포함 (구현 문서 §3 모듈 4).

ẍ = ωn²(u − x) − 2ζωn·ẋ 를 스텝 내 ZOH 입력으로 RK4 적분한 뒤
① 속도 클램프(±rate_max) ② 스텝당 위치 변화 클램프(±rate_max·dt)
③ 위치 클램프(한계 도달 시 밀어붙이는 방향 속도 0) 순으로 제한 적용 —
②가 있어야 스텝당 이동량이 rate 한계를 엄밀히 넘지 않는다.
Block 프로토콜 준수. 레지스트리 카테고리 "actuator"로 등록 (plant/__init__).

기본값 세트는 데모 기체 가정값 wn 30 rad/s·ζ 0.7·rate 10 rad/s [기본값 01 §7].
rate_max만은 무제한이 아니라 이 가정값을 기본으로 둔다 — 미지정 시 무제한
작동기가 되면 해석이 조용히 낙관적이 되고(01 §4.2 경고), M11 폐루프 스터디가
rate 3 rad/s에서 리밋사이클을 실증해 "≥ 10 rad/s" 요구 사양을 도출한 근거가
결과에 반영되지 않는다. 위치 한계(pos_lo·pos_hi)는 믹서 타면 한계가, 초기값은
트림 웜스타트가 결정하므로 그쪽은 무제한 기본값이 맞다.
"""

from claw.blocks.base import UNBOUNDED, Block
from claw.params.param import ParamDef


class SecondOrderActuator(Block):
    NAME = "SecondOrderActuator"
    PARAM_DEFS = (
        ParamDef("wn", 30.0, "rad/s", "고유진동수", lo=1e-9),
        ParamDef("zeta", 0.7, "-", "감쇠비", lo=1e-9),
        ParamDef("pos_lo", -UNBOUNDED, "rad", "위치 하한"),
        ParamDef("pos_hi", UNBOUNDED, "rad", "위치 상한"),
        # lo는 1e-9 유지 — "≥ 10"은 실기체 선정 요구 사양이지 파라미터 제약이 아니다
        # (rate 3 rad/s 리밋사이클 재현 같은 민감도 스터디를 막으면 안 됨)
        ParamDef("rate_max", 10.0, "rad/s", "속도 한계(크기) — 요구사양 ≥ 10 (01 v0.13)", lo=1e-9),
        ParamDef("initial", 0.0, "rad", "초기 위치"),
    )

    def __init__(
        self,
        wn: float = 30.0,
        zeta: float = 0.7,
        pos_lo: float = -UNBOUNDED,
        pos_hi: float = UNBOUNDED,
        rate_max: float = 10.0,
        initial: float = 0.0,
    ):
        if wn <= 0 or zeta <= 0:
            raise ValueError(f"wn, zeta는 양수여야 함: wn={wn}, zeta={zeta}")
        if pos_lo > pos_hi:
            raise ValueError(f"pos_lo({pos_lo}) > pos_hi({pos_hi})")
        if rate_max <= 0:
            raise ValueError(f"rate_max는 양수여야 함: {rate_max}")
        self.wn, self.zeta = wn, zeta
        self.pos_lo, self.pos_hi, self.rate_max = pos_lo, pos_hi, rate_max
        self.initial = initial

    def reset(self, state=None) -> None:
        """state=(위치, 속도) 웜스타트 — 위치·속도 한계로 클램프해 수용."""
        if state is None:
            self._x = min(max(self.initial, self.pos_lo), self.pos_hi)
            self._v = 0.0
        else:
            self._x = min(max(float(state[0]), self.pos_lo), self.pos_hi)
            self._v = min(max(float(state[1]), -self.rate_max), self.rate_max)

    def step(self, u):
        dt, wn, zeta = self.dt, self.wn, self.zeta
        x0, v0 = self._x, self._v

        def f(x_, v_):
            return v_, wn * wn * (u - x_) - 2.0 * zeta * wn * v_

        k1x, k1v = f(x0, v0)
        k2x, k2v = f(x0 + 0.5 * dt * k1x, v0 + 0.5 * dt * k1v)
        k3x, k3v = f(x0 + 0.5 * dt * k2x, v0 + 0.5 * dt * k2v)
        k4x, k4v = f(x0 + dt * k3x, v0 + dt * k3v)
        x = x0 + (dt / 6.0) * (k1x + 2.0 * k2x + 2.0 * k3x + k4x)
        v = v0 + (dt / 6.0) * (k1v + 2.0 * k2v + 2.0 * k3v + k4v)

        v = min(max(v, -self.rate_max), self.rate_max)
        dx = min(max(x - x0, -self.rate_max * dt), self.rate_max * dt)
        x = x0 + dx
        if x >= self.pos_hi:
            x, v = self.pos_hi, min(v, 0.0)
        elif x <= self.pos_lo:
            x, v = self.pos_lo, max(v, 0.0)
        self._x, self._v = x, v
        return x
