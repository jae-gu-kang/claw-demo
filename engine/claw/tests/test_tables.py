"""M3 tables 검증 — nD 다중선형 보간 정확도·외삽 정책·유효범위 질의 (Phase 1 완료 기준).

핵심 근거: 다중선형 보간은 각 변수 차수 <= 1인 다항식을 셀 내에서 **정확히** 재현한다
— scipy 없이도 엄밀한 정확도 검증이 가능하다.
"""

import numpy as np
import pytest

from claw.blocks import LookupBlock
from claw.tables import Table, TableError


def _f(x, y, z):
    """다중선형 함수 (각 변수 차수 1) — 보간이 정확 재현해야 하는 대상."""
    return 2.0 + 3.0 * x - y + 0.5 * x * y - 0.1 * y * z + 0.02 * x * y * z + 0.7 * z


def make_3d():
    x = np.array([0.0, 0.5, 1.2, 2.0])
    y = np.array([-1.0, 0.0, 2.0])
    z = np.array([10.0, 20.0])
    xx, yy, zz = np.meshgrid(x, y, z, indexing="ij")
    return Table({"x": x, "y": y, "z": z}, _f(xx, yy, zz))


# ---- 정확도 ----


def test_grid_points_reproduced():
    t = make_3d()
    assert t.interp(x=0.5, y=2.0, z=10.0) == pytest.approx(_f(0.5, 2.0, 10.0), abs=1e-12)
    t1 = Table({"x": np.array([0.0, 1.0, 3.0])}, np.array([1.0, 5.0, -2.0]))
    assert t1.interp(x=3.0) == pytest.approx(-2.0, abs=1e-15)


def test_multilinear_function_exact():
    t = make_3d()
    for x, y, z in [(0.3, 1.1, 13.7), (0.9, -0.4, 19.9), (1.7, 0.0, 10.0), (0.0, -1.0, 15.0)]:
        assert t.interp(x=x, y=y, z=z) == pytest.approx(_f(x, y, z), abs=1e-9)


def test_1d_midpoint_and_2d_bilinear_hand_calc():
    t1 = Table({"x": np.array([0.0, 1.0])}, np.array([2.0, 6.0]))
    assert t1.interp(x=0.25) == pytest.approx(3.0)
    t2 = Table(
        {"a": np.array([0.0, 1.0]), "b": np.array([0.0, 1.0])},
        np.array([[1.0, 2.0], [3.0, 4.0]]),
    )
    assert t2.interp(a=0.5, b=0.5) == pytest.approx(2.5)  # 네 꼭짓점 평균


def test_vectorized_matches_scalar_and_broadcast():
    t = make_3d()
    xs = np.array([0.3, 0.9, 1.7])
    vec = t.interp(x=xs, y=1.0, z=15.0)
    assert vec.shape == (3,)
    for xi, vi in zip(xs, vec):
        assert vi == pytest.approx(t.interp(x=xi, y=1.0, z=15.0), abs=1e-12)


# ---- 외삽 정책 ----


def test_extrapolate_clip_default():
    t1 = Table({"x": np.array([0.0, 1.0])}, np.array([2.0, 6.0]))
    assert t1.interp(x=-5.0) == pytest.approx(2.0)  # 경계값 고정 (01 §3.4 외삽 금지)
    assert t1.interp(x=99.0) == pytest.approx(6.0)


def test_extrapolate_linear():
    t1 = Table({"x": np.array([0.0, 1.0])}, np.array([0.0, 2.0]), extrapolate="linear")
    assert t1.interp(x=2.0) == pytest.approx(4.0)  # 경계 셀 기울기 연장
    assert t1.interp(x=-1.0) == pytest.approx(-2.0)


def test_extrapolate_error():
    t1 = Table({"x": np.array([0.0, 1.0])}, np.array([0.0, 2.0]), extrapolate="error")
    assert t1.interp(x=0.5) == pytest.approx(1.0)
    with pytest.raises(TableError):
        t1.interp(x=1.5)


def test_in_range_boundary_inclusive():
    t = make_3d()
    assert t.in_range(x=0.0, y=-1.0, z=20.0)  # 경계 포함
    assert not t.in_range(x=2.1, y=0.0, z=15.0)
    assert not t.in_range(x=1.0, y=0.0, z=9.9)


def test_slice_matches_interp():
    t = make_3d()
    xs, ys = t.slice("x", y=1.0, z=15.0)
    assert np.array_equal(xs, np.array([0.0, 0.5, 1.2, 2.0]))
    for xi, yi in zip(xs, ys):
        assert yi == pytest.approx(t.interp(x=xi, y=1.0, z=15.0), abs=1e-12)


# ---- 입력 검증 ----


def test_table_errors():
    with pytest.raises(TableError):
        Table({"x": np.array([1.0, 0.0])}, np.array([0.0, 1.0]))  # 내림차순 축
    with pytest.raises(TableError):
        Table({"x": np.array([0.0, 1.0])}, np.array([0.0, 1.0, 2.0]))  # 형상 불일치
    with pytest.raises(TableError):
        Table({"x": np.array([0.0])}, np.array([1.0]))  # 크기 1 축
    with pytest.raises(TableError):
        Table({"x": np.array([0.0, 1.0])}, np.array([0.0, 1.0]), extrapolate="hold")
    t = make_3d()
    with pytest.raises(TableError):
        t.interp(x=0.5, y=0.0)  # 축 인자 누락
    with pytest.raises(TableError):
        t.interp(x=0.5, y=0.0, z=15.0, w=1.0)  # 미정의 축


# ---- LookupBlock: 게인 스케줄 소비 형태 ----


def test_lookup_block_1d_gain_schedule():
    """마하수 → 게인 테이블 조회 (M7 fcl의 게인 스케줄 시나리오)."""
    gains = Table({"mach": np.array([0.3, 0.6, 0.9])}, np.array([2.0, 1.5, 1.0]))
    lb = LookupBlock(gains).init(0.01)
    assert lb.step(0.45) == pytest.approx(1.75)
    assert lb.step(1.2) == pytest.approx(1.0)  # 외삽 clip — 스케줄 경계 고정


def test_lookup_block_nd_sequence_input():
    t2 = Table(
        {"a": np.array([0.0, 1.0]), "b": np.array([0.0, 1.0])},
        np.array([[1.0, 2.0], [3.0, 4.0]]),
    )
    lb = LookupBlock(t2, axis_order=("b", "a")).init(0.01)
    assert lb.step((0.5, 0.5)) == pytest.approx(2.5)
    with pytest.raises(ValueError):
        LookupBlock(t2, axis_order=("a", "c"))  # 축 이름 불일치
