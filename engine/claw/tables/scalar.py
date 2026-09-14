"""스칼라 질의 전용 다중선형 보간 — 공력 항처럼 **점 하나씩** 부르는 자리를 위한 Table의 짝 (02 §5.6).

`Table.interp`는 질의점 배열에 대해 벡터화돼 있어 점 하나를 부를 때도 numpy 배열을 만들고 2^d 꼭짓점을
돈다 — 3축 표에서 한 번에 수십 µs다. 공력 항은 시뮬 한 스텝에 계수 여섯 개 × 항 수만큼 불리므로 그대로
쓰면 시뮬이 몇십 배 느려진다. 여기서는 축·데이터를 파이썬 리스트로 한 번 풀어 두고 같은 식을 스칼라로 돈다.

**Table.interp와 산술이 같다** — 같은 칸 찾기(searchsorted side="right" ↔ bisect_right), 같은 t 식과
clip, 같은 꼭짓점 순서(itertools.product), 같은 곱·합 순서(1.0에서 곱해 가고 0.0에서 더해 간다). 그래서
결과가 비트 단위로 같고, test_tables_scalar.py가 그것을 무작위 표로 대조한다. 검증(축 순증가·형상)은
Table 생성자가 하므로 여기서는 Table을 받아 만든다.
"""

import bisect
import itertools

from claw.tables.table import Table, TableError


class ScalarTable:
    __slots__ = ("name", "axis_names", "extrapolate", "_axes", "_data", "_strides", "_corners")

    def __init__(self, table: Table):
        self.name = table.name
        self.axis_names = table.axis_names
        self.extrapolate = table.extrapolate
        self._axes = tuple(ax.tolist() for ax in table.axes)
        self._data = table.data.ravel(order="C").tolist()
        strides, s = [], 1
        for size in reversed(table.data.shape):
            strides.append(s)
            s *= size
        self._strides = tuple(reversed(strides))
        self._corners = tuple(itertools.product((0, 1), repeat=len(self._axes)))

    def at_values(self, values) -> float:
        """축 순서(axis_names)대로 좌표 → 값."""
        idx, ts = [], []
        for ax, v in zip(self._axes, values):
            v = float(v)
            if self.extrapolate == "error" and not (ax[0] <= v <= ax[-1]):
                raise TableError(f"{self.name or 'table'}: 유효범위 밖 질의 (extrapolate='error')")
            i = bisect.bisect_right(ax, v) - 1
            n2 = len(ax) - 2
            i = 0 if i < 0 else (n2 if i > n2 else i)
            t = (v - ax[i]) / (ax[i + 1] - ax[i])
            if self.extrapolate == "clip":
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            idx.append(i)
            ts.append(t)
        out = 0.0
        strides, data = self._strides, self._data
        for corner in self._corners:
            w = 1.0
            flat = 0
            for d, b in enumerate(corner):
                t = ts[d]
                w = w * (t if b else 1.0 - t)
                flat += (idx[d] + b) * strides[d]
            out = out + w * data[flat]
        return out

    def at(self, point) -> float:
        """축이름 → 좌표 mapping 질의 (Table.interp(**point)의 스칼라판)."""
        missing = [nm for nm in self.axis_names if nm not in point]
        if missing:
            raise TableError(f"{self.name or 'table'}: 축 인자 누락 {missing}")
        return self.at_values([point[nm] for nm in self.axis_names])
