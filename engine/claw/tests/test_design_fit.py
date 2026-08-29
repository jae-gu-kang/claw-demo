"""M17 fit 검증 — 동압 법칙 적합(캡 knot·차수 에스컬레이션·C0), 축 선택, 재샘플."""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    OperatingPoint,
    PointSet,
    case_name,
    fit_gain_surface,
    fit_slot,
    fit_slots,
    resample_to_table,
    select_axes,
)
from claw.tables import PolyTable

MACHS = np.round(np.arange(0.15, 0.951, 0.05), 4)
DP = np.minimum((0.6 / MACHS) ** 2, 4.0)  # 데모 동압 역비 스케일 (상한 4)


def _points_1d(machs, alt=1000.0, fuel=200.0):
    ps = PointSet()
    for m in machs:
        ps.add(OperatingPoint(
            case=TrimCase(name=case_name(m, alt, fuel), mach=float(m), alt=alt, fuel=fuel),
            role=ROLE_ANCHOR, origin="coarse",
        ))
    return ps


def test_dynamic_pressure_law_fit():
    """1/M²·상한 4 곡선 — 캡 경계(M0.3)를 knot로 찾고 소수 구간·저차로 tol 내 적합."""
    out = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02, max_degree=4, max_segments=4)
    assert out["n_segments"] <= 3
    assert out["max_residual"] <= 0.02 * out["scale"]
    assert any(j["x"] == pytest.approx(0.3, abs=0.051) for j in out["joints"])
    # C0 구성 보장 — 경계 값 점프는 0 (기울기 점프는 정량 보고만)
    for j in out["joints"]:
        assert j["value_jump"] == pytest.approx(0.0, abs=1e-12)


def test_linear_data_stays_single_linear_segment():
    ys = 1.0 + 0.1 * MACHS
    out = fit_gain_surface(MACHS, ys, tol_fit=0.02)
    assert out["n_segments"] == 1
    assert out["max_degree_used"] == 1


def test_polytable_eval_clip_roundtrip():
    out = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02)
    poly = PolyTable("mach", out["segments"], name="pitch.kp")
    # 격자점 재현 (tol 내)
    for x, y in zip(MACHS, -2.0 * DP):
        assert poly.interp(mach=float(x)) == pytest.approx(y, abs=0.02 * out["scale"])
    # 외삽 clip — 범위 밖은 경계값 고정
    assert poly.interp(mach=0.05) == poly.interp(mach=0.15)
    assert poly.interp(mach=1.5) == poly.interp(mach=0.95)
    assert not poly.in_range(mach=0.05) and poly.in_range(mach=0.5)
    # 직렬화 왕복 후 평가 비트 일치
    poly2 = PolyTable.from_dict(poly.to_dict())
    for x in (0.15, 0.3, 0.31, 0.62, 0.95):
        assert poly2.interp(mach=x) == poly.interp(mach=x)


def test_resample_to_table():
    out = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02)
    poly = PolyTable("mach", out["segments"], name="pitch.kp")
    tab = resample_to_table(poly, tol_interp=0.01)
    scale = float(np.max(np.abs(-2.0 * DP)))
    xs = np.linspace(0.15, 0.95, 401)
    err = np.abs(tab.interp(mach=xs) - poly.interp(mach=xs))
    assert float(np.max(err)) <= 0.011 * scale
    assert tab.extrapolate == "clip"


def test_select_axes():
    ps = _points_1d(MACHS)
    varying = {case_name(m, 1000.0, 200.0): float(-2.0 * f) for m, f in zip(MACHS, DP)}
    flat = {case_name(m, 1000.0, 200.0): 0.5 for m in MACHS}
    assert select_axes(varying, ps) == ("mach",)
    assert select_axes(flat, ps) == ()


def test_fit_slot_constant_and_poly():
    ps = _points_1d(MACHS)
    flat = {case_name(m, 1000.0, 200.0): 0.5 for m in MACHS}
    out = fit_slot("yaw.k_rate", flat, ps)
    assert out["kind"] == "constant" and out["value"] == pytest.approx(0.5)
    varying = {case_name(m, 1000.0, 200.0): float(0.4 * f) for m, f in zip(MACHS, DP)}
    out2 = fit_slot("pitch.k_rate", varying, ps)
    assert out2["kind"] == "poly"
    assert out2["table"].axis_names == ("mach",)
    assert out2["report"]["max_residual"] <= 0.02 * out2["report"]["scale"]


def test_fit_slots_shapes():
    ps = _points_1d(MACHS)
    samples = {
        "pitch.kp": {case_name(m, 1000.0, 200.0): float(-2.0 * f)
                     for m, f in zip(MACHS, DP)},
        "yaw.k_rate": {case_name(m, 1000.0, 200.0): 0.8 for m in MACHS},
    }
    out = fit_slots(samples, ps)
    assert set(out["tables"]) == {"pitch.kp"}
    assert out["constants"] == {"yaw.k_rate": pytest.approx(0.8)}
    assert set(out["reports"]) == {"pitch.kp", "yaw.k_rate"}


def test_greedy_does_not_abandon_splittable_segments():
    """잔차 1위 구간을 못 쪼갠다고 전체 세분화를 포기하면 안 된다.

    격자점 2개짜리 구간(pin 제약으로 흔하다)이 최악이면 종전 코드는 아직 쪼갤 수
    있는 구간을 남긴 채 루프를 끝냈다 — 허용치의 수천 배로 끝나는 적합이 나왔고,
    그 나쁜 적합이 곧 분류기의 보간 괴리 오탐으로 이어진다.
    """
    # 끝에 2점짜리 급변을 두고 앞쪽에 넉넉한 곡선을 둔다
    xs = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    ys = np.array([0.0, 9.0, 1.0, 8.0, 2.0, 7.0, 3.0, 40.0])
    out = fit_gain_surface(xs, ys, tol_fit=0.001, max_degree=2, max_segments=6)
    assert out["n_segments"] >= 3, "쪼갤 수 있는 구간이 남았는데 2구간에서 멈췄다"


def test_greedy_terminates_when_nothing_splittable():
    """전 구간이 2점이면 더 쪼갤 자리가 없으므로 조용히 종료한다 (무한 루프 금지)."""
    xs = np.array([0.0, 1.0])
    ys = np.array([0.0, 5.0])
    out = fit_gain_surface(xs, ys, tol_fit=1e-12, max_degree=1, max_segments=4)
    assert out["n_segments"] == 1
