"""nD 다중선형 보간 테이블 — numpy 자체 구현 (scipy 미도입, 의존성 최소화 원칙).

공력 DB(Mach·α·β·타면각·고도 5축, 01 §2.3)와 게인 스케줄 테이블(Mach·고도·연료,
01 §3.4)의 공용 보간 엔진. 외삽 정책:
- "clip"  : 경계값 고정 (기본 — 게인 스케줄 외삽 금지, 01 §3.4)
- "linear": 경계 셀 기울기로 연장
- "error" : 범위 밖 질의 시 TableError (조용한 외삽 금지)
in_range()는 엔벨로프 감시 플래그(구현 문서 §6.1)의 근거, slice()는 DB 뷰어(§5.2)용.
"""

import itertools

import numpy as np

_POLICIES = ("clip", "linear", "error")


class TableError(ValueError):
    """테이블 정의·질의 오류."""


class Table:
    def __init__(self, axes, data, name="", extrapolate="clip"):
        if extrapolate not in _POLICIES:
            raise TableError(f"외삽 정책은 {_POLICIES} 중 하나: {extrapolate!r}")
        self.name = name
        self.extrapolate = extrapolate
        self.axis_names = tuple(axes)
        self.axes = tuple(np.asarray(v, dtype=float) for v in axes.values())
        for nm, ax in zip(self.axis_names, self.axes):
            if ax.ndim != 1 or ax.size < 2:
                raise TableError(f"축 {nm}: 1차원·크기 2 이상 필요 (shape={ax.shape})")
            if not np.all(np.diff(ax) > 0):
                raise TableError(f"축 {nm}: 순증가(오름차순) 필요")
        self.data = np.asarray(data, dtype=float)
        expected = tuple(ax.size for ax in self.axes)
        if self.data.shape != expected:
            raise TableError(f"데이터 형상 {self.data.shape} != 축 크기 {expected}")

    def _coords(self, point):
        if set(point) != set(self.axis_names):
            raise TableError(
                f"축 인자 불일치: 필요 {list(self.axis_names)}, 받음 {sorted(point)}"
            )
        return [np.asarray(point[nm], dtype=float) for nm in self.axis_names]

    def in_range(self, **point):
        """전 축이 유효범위 내인지 — 엔벨로프 플래그의 근거. 경계 포함."""
        ok = np.bool_(True)
        for ax, v in zip(self.axes, self._coords(point)):
            ok = ok & (v >= ax[0]) & (v <= ax[-1])
        return bool(ok) if np.ndim(ok) == 0 else ok

    def interp(self, **point):
        """축이름=좌표 질의. 스칼라 → float, 배열(브로드캐스트) → ndarray."""
        vals = self._coords(point)
        if self.extrapolate == "error" and not np.all(self.in_range(**point)):
            raise TableError(f"{self.name or 'table'}: 유효범위 밖 질의 (extrapolate='error')")
        vals = np.broadcast_arrays(*vals)
        idxs, ts = [], []
        for ax, v in zip(self.axes, vals):
            i = np.clip(np.searchsorted(ax, v, side="right") - 1, 0, ax.size - 2)
            t = (v - ax[i]) / (ax[i + 1] - ax[i])
            if self.extrapolate == "clip":
                t = np.clip(t, 0.0, 1.0)
            idxs.append(i)
            ts.append(t)
        out = np.zeros(np.shape(vals[0]))
        # 2^d 꼭짓점 가중합 — 질의점 배열에 대해 완전 벡터화 (5축 DB 기준 32 꼭짓점)
        for corner in itertools.product((0, 1), repeat=len(self.axes)):
            w = np.ones(np.shape(vals[0]))
            for t, b in zip(ts, corner):
                w = w * (t if b else 1.0 - t)
            idx = tuple(i + b for i, b in zip(idxs, corner))
            out = out + w * self.data[idx]
        return float(out) if np.ndim(out) == 0 else out

    __call__ = interp

    def slice(self, along, **fixed):
        """한 축을 따라 곡선 추출 (나머지 축 고정) — DB 뷰어의 CL–α 곡선 등."""
        if along not in self.axis_names:
            raise TableError(f"미정의 축: {along}")
        others = [nm for nm in self.axis_names if nm != along]
        if set(fixed) != set(others):
            raise TableError(f"고정 축 인자 불일치: 필요 {others}, 받음 {sorted(fixed)}")
        x = self.axes[self.axis_names.index(along)].copy()
        pts = {along: x}
        for nm in others:
            pts[nm] = np.full(x.shape, float(fixed[nm]))
        return x, self.interp(**pts)
