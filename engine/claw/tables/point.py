"""1점 표 — 표준 템플릿에서 스케줄하지 않은 게인 자리를 **값으로** 두는 표 (v1.12, 07 §6).

분석 그래프는 스케줄하지 않은 자리를 파라미터 상수로 두고, 스케줄한 자리는 룩업으로 둔다 — 그래서 어느 자리를 스케줄하는지가
탑재 C의 **구조**를 바꿨다. 표준 템플릿은 카탈로그의 모든 자리를 룩업으로 두고, 스케줄하지 않은 자리는 이 1점 표를 물린다.
그러면 자리 선택이 구조가 아니라 이미지 안의 표 길이(n = 1)가 된다.

**비트 동일:** `interp`는 질의점과 무관하게 값 하나를 그대로 돌려주고, C `claw_lookup1d`도 n < 2면 `val[0]`을 그대로
돌려준다 — 분석 그래프의 상수 곱 `kp * e`와 표준 그래프의 룩업 곱 `sched_kp_y * e`가 같은 비트다(flight 패리티가 증명).

소비 계약은 `Table`과 같다(`axis_names`·`axes`·`data`·`extrapolate`·`interp`) — `LookupBlock`은 덕 타이핑이라 그대로
받는다. `Table`은 축 크기 2 이상을 요구하므로(보간 구간이 있어야 한다) 따로 둔다.
"""

import math

import numpy as np

from claw.tables.table import TableError


class PointTable:
    """값 하나짜리 1D 표. at은 격자점 자리(이미지 목록에 보일 뿐 조회에 쓰이지 않는다)."""

    kind = "point"
    extrapolate = "clip"

    def __init__(self, axis, value, name="", at=0.0):
        value, at = float(value), float(at)
        if not (math.isfinite(value) and math.isfinite(at)):
            raise TableError(f"{name or 'point'}: 1점 표의 값·격자점은 유한해야 한다 ({value}, {at})")
        self.name = name
        self.axis_names = (str(axis),)
        self.axes = (np.array([at]),)
        self.data = np.array([value])

    def _coords(self, point):
        if set(point) != set(self.axis_names):
            raise TableError(f"축 인자 불일치: 필요 {list(self.axis_names)}, 받음 {sorted(point)}")
        return np.asarray(point[self.axis_names[0]], dtype=float)

    def in_range(self, **point):
        """값이 하나라 어느 질의점이든 같은 답이다 — 범위 밖이라는 개념이 없다."""
        v = self._coords(point)
        return True if np.ndim(v) == 0 else np.ones(np.shape(v), dtype=bool)

    def interp(self, **point):
        v = self._coords(point)
        return float(self.data[0]) if np.ndim(v) == 0 else np.full(np.shape(v), float(self.data[0]))

    __call__ = interp
