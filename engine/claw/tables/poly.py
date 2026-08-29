"""1D 구간별 다항 테이블 — 게인 스케줄의 다항 런타임 표현 (01 §3.4 다항 채택).

Table(격자+선형 보간)의 자매 표현이다: 같은 소비 계약(`axis_names` +
`interp(**좌표)` 덕 타이핑 — blocks/lookup.py·design/schedmap.py)을 지키면서,
값을 격자점이 아니라 **구간별 다항식 계수**로 갖는다. 튜닝된 게인 surface를
적은 수의 knot + 2~4차 계수로 나르는 것이 목적이다 (design/fit.py가 생산).

- 평가: 센터·스케일 정규화 u=(x−c)/h 영역 호너 — web polyfit.js evalFit과 같은
  식이라 계수가 그대로 왕복한다. C 짝은 codegen claw_polyeval1d (비트 일치 대상).
- 외삽 금지: x를 [knots[0], knots[-1]]로 클램프 — Table extrapolate='clip'과 같은
  의미. 다른 정책은 받지 않는다 (비행 중 예외 금지 원칙).
- v1은 1D 전용 — 다차원 다항은 [백로그], 그 자리는 Table 폴백 (design/fit.py).
"""

import numpy as np

from claw.tables.table import TableError


class PolyTable:
    """구간별 다항 1D 테이블. segments: [{x0, x1, degree, coeffs, c, h}] —
    coeffs는 u-영역 오름차수(폴리핏 규약), 구간은 인접·오름차순이어야 한다."""

    kind = "poly"
    extrapolate = "clip"  # 유일 정책 — GainSchedule의 clip 강제 검증과 정합

    def __init__(self, axis, segments, name=""):
        self.name = name
        self.axis_names = (str(axis),)
        segs = []
        prev_x1 = None
        for i, s in enumerate(segments):
            x0, x1 = float(s["x0"]), float(s["x1"])
            coeffs = tuple(float(v) for v in s["coeffs"])
            c, h = float(s["c"]), float(s["h"])
            if not x0 < x1:
                raise TableError(f"{name or 'poly'}: 구간 {i} 역전 x0={x0} ≥ x1={x1}")
            if prev_x1 is not None and x0 != prev_x1:
                raise TableError(
                    f"{name or 'poly'}: 구간 {i} 불연속 경계 {prev_x1} → {x0} — 인접 필수"
                )
            if not coeffs:
                raise TableError(f"{name or 'poly'}: 구간 {i} 계수 없음")
            if int(s.get("degree", len(coeffs) - 1)) != len(coeffs) - 1:
                raise TableError(f"{name or 'poly'}: 구간 {i} degree≠계수 수−1")
            if h <= 0:
                raise TableError(f"{name or 'poly'}: 구간 {i} 스케일 h는 양수: {h}")
            segs.append({"x0": x0, "x1": x1, "coeffs": coeffs, "c": c, "h": h,
                         "degree": len(coeffs) - 1})
            prev_x1 = x1
        if not segs:
            raise TableError(f"{name or 'poly'}: 구간이 없다")
        self.segments = tuple(segs)
        self.knots = np.array([s["x0"] for s in segs] + [segs[-1]["x1"]])

    def _coords(self, point):
        if set(point) != set(self.axis_names):
            raise TableError(
                f"축 인자 불일치: 필요 {list(self.axis_names)}, 받음 {sorted(point)}"
            )
        return np.asarray(point[self.axis_names[0]], dtype=float)

    def in_range(self, **point):
        v = self._coords(point)
        ok = (v >= self.knots[0]) & (v <= self.knots[-1])
        return bool(ok) if np.ndim(ok) == 0 else ok

    def _locate(self, x: float) -> tuple:
        """좌표 → (구간, u) — **클램프와 구간 선택의 유일한 구현**.

        이 네 줄이 탑재 C `claw_polyeval1d`(codegen/emit_c.py)와 비트 단위로 맞아야
        하는 부분이다. 평가와 기울기가 각자 복사본을 들고 있으면 C를 따라 규약을
        고칠 때 한쪽만 바뀌어도 테스트가 안 잡는다 — 한 곳에 둔다.
        """
        xc = min(max(x, float(self.knots[0])), float(self.knots[-1]))  # clip
        i = int(np.clip(np.searchsorted(self.knots, xc, side="right") - 1,
                        0, len(self.segments) - 1))
        s = self.segments[i]
        return s, (xc - s["c"]) / s["h"]

    def _eval_one(self, x: float) -> float:
        s, u = self._locate(x)
        v = 0.0
        for a in reversed(s["coeffs"]):  # u-영역 호너 (polyfit.js evalFit과 동일)
            v = v * u + a
        return v

    def interp(self, **point):
        v = self._coords(point)
        if np.ndim(v) == 0:
            return self._eval_one(float(v))
        return np.array([self._eval_one(float(x)) for x in np.ravel(v)]).reshape(v.shape)

    __call__ = interp

    def slope(self, x: float) -> float:
        """dp/dx — 경계 기울기 점프 보고용 (u-영역 도함수 호너 / h).

        구간 선택은 `_locate`와 공유한다 — 평가와 다른 구간을 고르면 joints 리포트가
        런타임이 쓰지 않는 분할을 설명하게 된다.
        """
        s, u = self._locate(float(x))
        v = 0.0
        for k in range(len(s["coeffs"]) - 1, 0, -1):
            v = v * u + k * s["coeffs"][k]
        return v / s["h"]

    def scaled(self, factor: float) -> "PolyTable":
        """곡선 전체에 배율 — 다항은 계수에 곱하면 된다 (p·s의 계수 = 계수·s).

        영향성 파이프라인(pipeline/influence.py gain_scale)이 게인 곡선을 흔드는
        경로다. Table은 data에 곱하지만 다항은 격자 값이 없으므로 여기서 처리한다.
        """
        f = float(factor)
        return PolyTable(
            self.axis_names[0],
            [{**s, "coeffs": [c * f for c in s["coeffs"]]} for s in self.segments],
            name=self.name,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "poly",
            "axis": self.axis_names[0],
            "name": self.name,
            "segments": [
                {"x0": s["x0"], "x1": s["x1"], "degree": s["degree"],
                 "coeffs": list(s["coeffs"]), "c": s["c"], "h": s["h"]}
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PolyTable":
        return cls(d["axis"], d["segments"], name=d.get("name", ""))
