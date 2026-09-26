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
    fit_quality,
    fit_slot,
    fit_slots,
    resample_to_table,
    select_axes,
)
from claw.tables import PolyTable

MACHS = np.round(np.arange(0.15, 0.951, 0.05), 4)
# 동압 역비 스케일 꼴의 **합성** 곡선. 상한 4는 임의 선택이지만 **knot 위치(M0.3)를
# 정하므로** 아래 knot 단정과 한 벌이다 — 2.0으로 바꾸면 joints가 [0.4, 0.45]가 되어
# 단정이 깨진다(실측). 데모 형상의 상한과는 무관하다: 상한 4·경계 M0.3이 우연히 롤과
# 같을 뿐이고, 진폭 -2.0은 pitch.kp의 설계값이라 어느 자리와도 짝이 아니다.
DP = np.minimum((0.6 / MACHS) ** 2, 4.0)


def _points_1d(machs, alt=1000.0, fuel=200.0):
    ps = PointSet()
    for m in machs:
        ps.add(OperatingPoint(
            case=TrimCase(name=case_name(m, alt, fuel), mach=float(m), alt=alt, fuel=fuel),
            role=ROLE_ANCHOR, origin="coarse",
        ))
    return ps


def test_dynamic_pressure_law_fit():
    """1/M²·상한 4 곡선 — 캡 경계(M0.3)를 knot로 찾고 소수 구간·저차로 tol 내 적합.

    **상한을 바꾸면 이 테스트가 깨진다.** 곡선이 꺾이는 자리가 곧 상한이 물리는
    자리라 knot 단정(M0.3)이 상한 4에 묶여 있다 — 상한 2.0에서는 joints가
    [0.4, 0.45]로 옮겨 가 아래 단정이 실패한다. 데모 형상을 따라가라는 뜻이 아니다
    (그쪽 상한은 축별이다): 바꿀 거면 곡선과 단정을 **함께** 바꾸라는 뜻이다.
    """
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


def test_fit_preserves_design_sign():
    """0 근처 값에 고차를 씌우면 곡선이 0을 가로질러 부호가 뒤집힌다.

    데모에서 실제로 겪었다 — roll.ki 설계 +0.1인데 적합 4차가 M0.4346에서
    −0.00022를 냈고, oriented_margins가 방향을 보정해 PM 116°로 보고했다
    (실제로는 양의 되먹임). 허용치는 슬롯 전체 스케일 기준이라 이걸 못 막는다.
    """
    ps = _points_1d(MACHS)
    # 0 근처에서 진동하는 양수 샘플 — 고차 적합이 0을 넘기 쉬운 형상
    vals = 0.002 + 0.0018 * np.sin(np.linspace(0, 3.2 * np.pi, len(MACHS)))
    samples = {case_name(m, 1000.0, 200.0): float(v) for m, v in zip(MACHS, vals)}
    out = fit_slot("roll.ki", samples, ps, tol_fit=0.02, max_degree=4)
    guard = (out.get("report") or out).get("sign_guard")
    assert guard is not None and guard["want"] == 1.0
    if out["kind"] == "poly":
        xs = np.linspace(0.15, 0.95, 401)
        v = out["table"].interp(mach=xs)
        assert np.all(v >= 0.0), f"부호가 뒤집혔다: min={v.min():.6g}"
    else:  # 어떤 차수로도 못 지키면 상수 폴백 — 그 값도 부호를 지킨다
        assert out["value"] > 0.0
        assert guard["fallback"] == "constant"


def test_sign_guard_lowers_degree_only_when_needed():
    """부호를 지키는 적합에는 손대지 않는다 — 필요할 때만 차수를 낮춘다."""
    ps = _points_1d(MACHS)
    samples = {case_name(m, 1000.0, 200.0): float(-2.0 * f) for m, f in zip(MACHS, DP)}
    out = fit_slot("pitch.kp", samples, ps, tol_fit=0.02, max_degree=4)
    assert out["kind"] == "poly"
    guard = out["report"]["sign_guard"]
    assert guard["want"] == -1.0
    assert guard["lowered"] is False, "멀쩡한 적합의 차수를 낮췄다"


def test_mixed_sign_samples_are_unconstrained():
    """샘플 자체가 부호를 넘나들면 제약할 부호가 없다 — 가드가 끼어들지 않는다."""
    ps = _points_1d(MACHS)
    samples = {case_name(m, 1000.0, 200.0): float(m - 0.5) for m in MACHS}
    out = fit_slot("pitch.ki", samples, ps, tol_fit=0.02, max_degree=4)
    guard = (out.get("report") or out)["sign_guard"]
    assert guard["want"] == 0.0
    assert guard["lowered"] is False


def test_fit_quality_normalizes_by_the_slots_own_scale():
    """fit_quality — 무차원 정규화 한 곳 (04 §10 지표부). 기체 무관이어야 한다.

    slope_jump_norm의 단위는 scale/axis_span("축 전폭에 걸쳐 스케일만큼 변하는
    기울기" = 1)이다 — 절대 기울기로 재면 게인 크기가 큰 자리가 항상 나쁘게 읽힌다.
    상수 자리는 None이다: "잴 것이 없다"를 0("완벽하다")으로 위장하지 않는다.
    """
    rep = {
        "kind": "poly",
        "segments": [{"x0": 0.2, "x1": 0.5}, {"x0": 0.5, "x1": 0.8}],
        "scale": 2.0,  # span 0.6 → 단위 기울기 2.0/0.6
        "joints": [{"x": 0.5, "value_jump": 0.0, "slope_jump": 10.0}],
        "cross_axis_residual": 0.5,
    }
    q = fit_quality(rep)
    assert q["slope_jump_norm_max"] == pytest.approx(10.0 / (2.0 / 0.6))
    assert q["cross_axis_frac"] == pytest.approx(0.25)
    # 관절 없는 1구간 — 꺾임이 없다 = 0 (None이 아니다: 실제로 재서 없는 것)
    q1 = fit_quality({"kind": "poly", "segments": [{"x0": 0.2, "x1": 0.8}],
                      "scale": 2.0, "joints": [], "cross_axis_residual": 0.0})
    assert q1["slope_jump_norm_max"] == 0.0 and q1["cross_axis_frac"] == 0.0
    # 상수 자리 — 관절도 축도 없다
    qc = fit_quality({"kind": "constant", "slot": "yaw.k_rate", "value": 0.4})
    assert qc["slope_jump_norm_max"] is None and qc["cross_axis_frac"] is None
    # 표 모드 — **같은 자**로 잰다 (span은 분할점 양끝, 단위는 scale/span).
    # 표현이 달라지면 문턱(fit_slope_jump_max)이 한쪽에만 걸리게 되고, 그러면
    # 「표는 품질을 안 본다」가 된다 — 1축 붕괴의 톱니가 드러나야 하는 자리다
    qt = fit_quality({
        "kind": "table", "slot": "pitch.kp", "breakpoints": [0.2, 0.5, 0.8],
        "scale": 2.0, "joints": [{"x": 0.5, "value_jump": 0.0, "slope_jump": 10.0}],
        "cross_axis_residual": 0.5,
    })
    assert qt["slope_jump_norm_max"] == pytest.approx(10.0 / (2.0 / 0.6))
    assert qt["cross_axis_frac"] == pytest.approx(0.25)


def test_table_mode_puts_the_tuned_values_at_the_breakpoints():
    """mode="table" — 적합 없이 튜닝값이 그대로 분할점 값이다 (사용자 확정 표현).

    다항은 샘플을 2% 안에서 지나가기만 하면 되는데, 표는 **그 점에서 정확히** 그
    값이어야 한다. 그것이 "급변을 뭉개지 않는다"의 내용이고, 이 단정이 깨지면
    표 모드가 이름만 표인 적합이 된다.
    """
    ps = _points_1d(MACHS)
    samples = {case_name(m, 1000.0, 200.0): float(0.4 * f) for m, f in zip(MACHS, DP)}
    out = fit_slot("pitch.k_rate", samples, ps, mode="table")
    assert out["kind"] == "table"
    tab = out["table"]
    assert tab.axis_names == ("mach",) and tab.extrapolate == "clip"
    assert list(tab.axes[0]) == pytest.approx(list(MACHS))
    for m, v in zip(MACHS, (0.4 * DP)):
        assert float(tab.interp(mach=float(m))) == pytest.approx(float(v))
    rep = out["report"]
    # 한 행(고도·연료 고정)뿐이니 접을 것이 없다 — 잔차 0, 교차축 0
    assert rep["max_residual"] == pytest.approx(0.0) and rep["cross_axis_residual"] == 0.0
    assert rep["n_breakpoints"] == len(MACHS)
    # 관절은 내부 분할점 전부 — 선형 보간은 분할점마다 기울기가 꺾인다
    assert len(rep["joints"]) == len(MACHS) - 2
    assert all(j["value_jump"] == 0.0 for j in rep["joints"]), "값은 구성적으로 연속"
    # 단조 곡선(1/M²·캡)이라 방향 반전이 없다 — 톱니 집계가 잡음을 세지 않는지
    assert rep["zigzag"] == 0


def test_table_mode_reports_what_the_one_axis_collapse_costs():
    """1축 붕괴의 대가를 0으로 위장하지 않는다 — 잔차·교차축·톱니로 보고.

    고도 두 행이 다른 값을 갖는데 지배 축이 mach면, 같은 mach의 두 샘플이 평균으로
    접힌다. 접은 대표값끼리 재면 잔차가 정의상 0이므로 **접기 전 표본 전부**에
    대해 재야 한다 (실측 동기: 예제 기체에서 축값마다 참여 행이 달라 표가 톱니였다).
    """
    ps = PointSet()
    machs = (0.3, 0.4, 0.5)
    for m in machs:
        for alt in (0.0, 4000.0):
            ps.add(OperatingPoint(
                case=TrimCase(name=case_name(m, alt, 200.0), mach=m, alt=alt, fuel=200.0),
                role=ROLE_ANCHOR, origin="coarse",
            ))
    # 고도가 값을 ±0.1 벌린다 — mach 방향 변동(0.2)이 더 커서 지배 축은 mach다
    samples = {case_name(m, alt, 200.0): 1.0 + 0.2 * i + (0.1 if alt else -0.1)
               for i, m in enumerate(machs) for alt in (0.0, 4000.0)}
    out = fit_slot("pitch.kp", samples, ps, mode="table")
    rep = out["report"]
    assert rep["axis"] == "mach" and rep["axes_detected"] == ("mach", "alt")
    assert list(out["table"].axes[0]) == pytest.approx(list(machs))
    # 평균으로 접혔으니 표는 두 행의 중간값이고, 잔차는 벌어진 폭의 절반이다
    assert list(out["table"].data) == pytest.approx([1.0, 1.2, 1.4])
    assert rep["max_residual"] == pytest.approx(0.1)
    assert rep["cross_axis_residual"] == pytest.approx(0.2)
    q = fit_quality(rep)
    assert q["cross_axis_frac"] == pytest.approx(0.2 / 1.4)


def test_table_mode_keeps_a_schedule_the_sign_guard_flattens():
    """다항이 상수로 굳히는 표본을 표는 스케줄로 지킨다 — 이 변경의 동기.

    부호 보호(_fit_preserving_sign)는 어느 차수로도 부호를 못 지키면 그 자리를
    상수로 굳힌다. 0에 닿는 계단형 표본이 그 경우다(예제 기체 roll.k_rate 실측:
    표본이 −0.131~0.0이고 1차까지 내려도 0을 넘어 상수가 됐다). 표는 표본값을
    그대로 놓으므로 부호를 넘길 곡선이 없다.
    """
    ps = _points_1d(MACHS)
    ys = [-0.12 if m < 0.35 else (-0.02 if m < 0.7 else 0.0) for m in MACHS]
    samples = {case_name(m, 1000.0, 200.0): float(y) for m, y in zip(MACHS, ys)}

    poly = fit_slot("roll.k_rate", samples, ps)
    assert poly["kind"] == "constant", "다항이 부호를 못 지켜 상수로 굳는 표본이어야 한다"
    assert poly["sign_guard"]["fallback"] == "constant"

    tab = fit_slot("roll.k_rate", samples, ps, mode="table")
    assert tab["kind"] == "table", "표는 같은 표본에서 스케줄을 지킨다"
    assert all(v <= 0.0 for v in tab["table"].data), "표본 부호를 그대로 쓴다"
    assert tab["report"]["sign_guard"]["want"] == -1.0
    # 계단이 두 번 꺾이므로 관절 기울기 점프가 실제로 잡힌다 (뭉개지 않은 대가의 표시)
    assert max(abs(j["slope_jump"]) for j in tab["report"]["joints"]) > 0.0


def test_table_mode_needs_two_breakpoints_on_the_dominant_axis():
    """지배 축 분할점이 한 점이면 표를 못 세운다 — 상수로 굳히고 **사유를 남긴다**."""
    ps = PointSet()
    for alt in (0.0, 2000.0, 4000.0):
        ps.add(OperatingPoint(
            case=TrimCase(name=case_name(0.4, alt, 200.0), mach=0.4, alt=alt, fuel=200.0),
            role=ROLE_ANCHOR, origin="coarse",
        ))
    # 변동이 전부 alt에서 오지만 mach는 한 점 — 지배 축은 alt이므로 표가 선다
    by_alt = {case_name(0.4, alt, 200.0): 1.0 + 0.5 * i
              for i, alt in enumerate((0.0, 2000.0, 4000.0))}
    out = fit_slot("pitch.kp", by_alt, ps, mode="table")
    assert out["kind"] == "table" and out["report"]["axis"] == "alt"

    # 축이 하나뿐인데 그 축의 값이 한 점 — 표를 세울 수 없다
    ps1 = PointSet()
    for fuel in (200.0, 300.0):
        ps1.add(OperatingPoint(
            case=TrimCase(name=case_name(0.4, 0.0, fuel), mach=0.4, alt=0.0, fuel=fuel),
            role=ROLE_ANCHOR, origin="coarse",
        ))
    one = fit_slot("pitch.kp", {case_name(0.4, 0.0, 200.0): 1.0,
                                case_name(0.4, 0.0, 300.0): 2.0}, ps1, mode="table")
    assert one["kind"] == "table" and one["report"]["axis"] == "fuel"


def test_fit_slot_rejects_an_unknown_mode():
    ps = _points_1d(MACHS)
    samples = {case_name(m, 1000.0, 200.0): float(0.4 * f) for m, f in zip(MACHS, DP)}
    with pytest.raises(ValueError, match="mode"):
        fit_slot("pitch.kp", samples, ps, mode="spline")


def test_fit_slots_table_mode_keeps_the_constant_decision():
    """표/다항 전환은 **표현**만 바꾼다 — 실질 무변동 축 탈락(상수 판정)은 그대로."""
    ps = _points_1d(MACHS)
    samples = {
        "pitch.kp": {case_name(m, 1000.0, 200.0): float(-2.0 * f)
                     for m, f in zip(MACHS, DP)},
        "yaw.k_rate": {case_name(m, 1000.0, 200.0): 0.8 for m in MACHS},
    }
    out = fit_slots(samples, ps, mode="table")
    assert set(out["tables"]) == {"pitch.kp"}
    assert not isinstance(out["tables"]["pitch.kp"], PolyTable)
    assert out["constants"] == {"yaw.k_rate": pytest.approx(0.8)}
    assert out["reports"]["pitch.kp"]["kind"] == "table"
    assert out["reports"]["yaw.k_rate"]["kind"] == "constant"
