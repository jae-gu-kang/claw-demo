"""스칼라 보간(ScalarTable)은 Table.interp와 비트 단위로 같고, 점 하나 질의에서 훨씬 빠르다 (02 §5.6)."""

import math
import time

import numpy as np
import pytest

from claw.tables.scalar import ScalarTable
from claw.tables.table import Table, TableError


def _table(rs, ndim, extrapolate):
    axes = {}
    for d in range(ndim):
        n = rs.randint(2, 7)
        axes[f"x{d}"] = np.cumsum(rs.uniform(0.05, 1.0, n)) + rs.uniform(-2, 2)
    data = rs.normal(size=tuple(len(a) for a in axes.values()))
    return Table(axes, data, name="t", extrapolate=extrapolate)


@pytest.mark.parametrize("extrapolate", ["clip", "linear"])
@pytest.mark.parametrize("ndim", [1, 2, 3, 4])
def test_scalar_matches_table_bit_for_bit(ndim, extrapolate):
    rs = np.random.RandomState(100 + ndim)
    for _ in range(5):
        t = _table(rs, ndim, extrapolate)
        s = ScalarTable(t)
        for _ in range(200):
            # 범위 안·경계 위·밖을 섞는다 — 칸 찾기와 clip·외삽의 갈래를 전부 탄다
            pt = {}
            for nm, ax in zip(t.axis_names, t.axes):
                pick = rs.randint(4)
                pt[nm] = (float(rs.choice(ax)) if pick == 0 else
                          float(ax[0] - rs.uniform(0, 1)) if pick == 1 else
                          float(ax[-1] + rs.uniform(0, 1)) if pick == 2 else
                          float(rs.uniform(ax[0], ax[-1])))
            want = t.interp(**pt)
            got = s.at(pt)
            assert got == want or (math.isnan(got) and math.isnan(want)), (pt, got, want)
            assert math.copysign(1.0, got) == math.copysign(1.0, want)


def test_error_policy_and_missing_axis_raise_like_table():
    t = Table({"mach": [0.1, 0.5]}, [1.0, 2.0], name="cl", extrapolate="error")
    s = ScalarTable(t)
    assert s.at({"mach": 0.3}) == t.interp(mach=0.3)
    with pytest.raises(TableError):
        s.at({"mach": 0.6})
    with pytest.raises(TableError):
        s.at({"alpha": 0.1})


def test_scalar_is_much_faster_than_table_for_single_points():
    """속도 예산 — 비율로 잰다(기계마다 절대 시간이 다르다). 공력 항은 스텝마다 수십 번 불린다."""
    rs = np.random.RandomState(7)
    axes = {"alpha": np.linspace(-0.3, 0.6, 19), "beta": np.linspace(-0.3, 0.3, 7), "mach": np.linspace(0.1, 0.9, 9)}
    t = Table(axes, rs.normal(size=(19, 7, 9)))
    s = ScalarTable(t)
    pts = [{"alpha": float(rs.uniform(-0.3, 0.6)), "beta": float(rs.uniform(-0.3, 0.3)),
            "mach": float(rs.uniform(0.1, 0.9))} for _ in range(400)]
    t0 = time.perf_counter()
    for p in pts:
        t.interp(**p)
    slow = time.perf_counter() - t0
    t0 = time.perf_counter()
    for p in pts:
        s.at(p)
    fast = time.perf_counter() - t0
    assert fast * 4 < slow, f"스칼라 보간 {fast / len(pts) * 1e6:.1f} µs vs Table {slow / len(pts) * 1e6:.1f} µs"
