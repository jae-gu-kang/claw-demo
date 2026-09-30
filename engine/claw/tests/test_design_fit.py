"""M17 fit 검증 — 동압 법칙 적합(캡 knot·차수 에스컬레이션·C0), 축 선택, 재샘플."""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_DESIGN,
    OperatingPoint,
    PointSet,
    case_name,
    fit_gain_surface,
    fit_quality,
    fit_slot,
    fit_slots,
    resample_to_table,
    select_axes,
    table_on_knots,
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
            role=ROLE_DESIGN, origin="coarse",
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
                role=ROLE_DESIGN, origin="coarse",
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
            role=ROLE_DESIGN, origin="coarse",
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
            role=ROLE_DESIGN, origin="coarse",
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


def _points_2d(machs, alts, fuel=200.0):
    ps = PointSet()
    for a in alts:
        for m in machs:
            ps.add(OperatingPoint(
                case=TrimCase(name=case_name(m, a, fuel), mach=float(m), alt=float(a), fuel=fuel),
                role=ROLE_DESIGN, origin="coarse",
            ))
    return ps


def test_sched_axis_restriction_keeps_the_table_on_mach_and_reports_the_rest():
    """스케줄 축 제한 — 고도 변동이 지배적이어도 마하 표로 적합하고, 뺀 축은 보고에 남는다.

    기체 문서(law.gain_tables)와 게인 탭은 마하 1축 표만 받는다. 제한 없이 지배 축을 고르면
    고도 표가 나와 apply-gains가 422로 거부했다(실측: 고도 2개 설정에서 pitch.kp가 alt 표).
    """
    machs, alts = (0.3, 0.4, 0.5, 0.6), (500.0, 3000.0)
    ps = _points_2d(machs, alts)
    # 마하로 조금, 고도로 크게 변하는 합성 게인 — 제한이 없으면 지배 축은 alt다
    samples = {case_name(m, a, 200.0): -1.0 - 1.0 * m - 0.0004 * a for a in alts for m in machs}
    free = fit_slot("pitch.kp", samples, ps)
    assert free["kind"] == "poly" and free["table"].axis_names == ("alt",)  # 종전 동작 그대로
    assert "axes_excluded" not in free["report"]

    out = fit_slot("pitch.kp", samples, ps, axes=("mach",))
    assert out["kind"] == "poly" and out["table"].axis_names == ("mach",)
    rep = out["report"]
    assert rep["axis"] == "mach"
    assert rep["axes_detected"] == ("mach", "alt")  # 변동 축은 전부 적는다
    assert rep["axes_excluded"] == ("alt",)
    # 같은 마하의 고도별 샘플은 평균으로 접힌다 — 뭉갠 고도 기여가 cross_axis_residual로 나온다
    assert rep["cross_axis_residual"] == pytest.approx(0.0004 * 2500.0)
    for m in machs:
        mean = np.mean([samples[case_name(m, a, 200.0)] for a in alts])
        assert out["table"].interp(mach=m) == pytest.approx(mean, abs=0.02 * rep["scale"])


def test_sched_axis_restriction_folds_an_off_axis_only_slot_to_a_constant_with_a_note():
    """변동이 제한 밖 축에만 있으면 상수로 접되, 조용히 뭉개지 않는다 — 잔차·뺀 축·사유."""
    machs, alts = (0.3, 0.4, 0.5), (500.0, 3000.0)
    ps = _points_2d(machs, alts)
    samples = {case_name(m, a, 200.0): 0.5 + 0.0002 * a for a in alts for m in machs}
    out = fit_slot("yaw.k_rate", samples, ps, axes=("mach",))
    assert out["kind"] == "constant"
    assert out["axes_excluded"] == ("alt",) and out["note"]
    assert out["max_residual"] == pytest.approx(0.0002 * 2500.0 / 2)
    # 제한 안에 변동이 없고 밖에도 없으면 종전 상수 그대로 — 보고 칸이 늘지 않는다
    flat = {case_name(m, a, 200.0): 0.5 for a in alts for m in machs}
    assert fit_slot("yaw.k_rate", flat, ps, axes=("mach",)) == fit_slot("yaw.k_rate", flat, ps)


def test_fit_slots_passes_the_restriction_and_rejects_unknown_axes():
    machs, alts = (0.3, 0.4, 0.5, 0.6), (500.0, 3000.0)
    ps = _points_2d(machs, alts)
    samples = {"pitch.kp": {case_name(m, a, 200.0): -1.0 - 1.0 * m - 0.0004 * a
                            for a in alts for m in machs}}
    out = fit_slots(samples, ps, axes=("mach",))
    assert out["tables"]["pitch.kp"].axis_names == ("mach",)
    for bad in ((), ("speed",), ("mach", "qbar")):
        with pytest.raises(ValueError):
            fit_slots(samples, ps, axes=bad)


def test_sched_axis_restriction_is_orthogonal_to_the_table_mode():
    """제한(어느 축으로 펴는가)과 표현(편 것을 어떻게 싣는가)은 직교한다 — 표 모드에서도 마하 표·같은 보고.

    v1.47 표 모드가 기본이 된 뒤에도 문서가 받는 모양(마하 1축)은 그대로다. 표 모드는 뺀 축의 기여를
    평균으로 접어 분할점에 싣고, 그 대가를 잔차·교차축·fit_quality로 낸다 — axes_detected는 다항과 같은
    뜻(변동 축 전부)이고 뺀 축은 axes_excluded다.
    """
    machs, alts = (0.3, 0.4, 0.5, 0.6), (500.0, 3000.0)
    ps = _points_2d(machs, alts)
    samples = {case_name(m, a, 200.0): -1.0 - 1.0 * m - 0.0004 * a for a in alts for m in machs}
    free = fit_slot("pitch.kp", samples, ps, mode="table")
    assert free["kind"] == "table" and free["table"].axis_names == ("alt",)  # v1.47 지배 축 그대로
    assert "axes_excluded" not in free["report"]

    out = fit_slot("pitch.kp", samples, ps, mode="table", axes=("mach",))
    assert out["kind"] == "table" and not isinstance(out["table"], PolyTable)
    assert out["table"].axis_names == ("mach",)
    rep = out["report"]
    assert rep["axis"] == "mach" and rep["axes_detected"] == ("mach", "alt")
    assert rep["axes_excluded"] == ("alt",)
    # 분할점 값 = 같은 마하의 고도별 샘플 평균 (적합 없음), 잔차 = 벌어진 폭의 절반
    for m, v in zip(machs, out["table"].data):
        assert v == pytest.approx(np.mean([samples[case_name(m, a, 200.0)] for a in alts]))
    assert rep["cross_axis_residual"] == pytest.approx(0.0004 * 2500.0)
    assert rep["max_residual"] == pytest.approx(0.0004 * 2500.0 / 2)
    assert fit_quality(rep)["cross_axis_frac"] == pytest.approx(1.0 / rep["scale"])

    # 제한 밖에만 변동 → 표현과 무관하게 같은 상수(사유 포함)
    off = {case_name(m, a, 200.0): 0.5 + 0.0002 * a for a in alts for m in machs}
    assert fit_slot("yaw.k_rate", off, ps, mode="table", axes=("mach",)) == \
        fit_slot("yaw.k_rate", off, ps, mode="poly", axes=("mach",))
    out2 = fit_slots({"pitch.kp": samples}, ps, mode="table", axes=("mach",))
    assert out2["tables"]["pitch.kp"].axis_names == ("mach",)
    assert out2["reports"]["pitch.kp"]["axes_excluded"] == ("alt",)


def _failed_zero_samples():
    """쇼케이스 기체 표 모드 실측의 모양 — 롤 댐퍼 표본이 음수로 매끄럽다가 튜닝 실패 한 점만 자리값 0."""
    machs = (0.100, 0.1039, 0.1077, 0.1116, 0.1154)
    ps = _points_1d(machs)
    names = [case_name(m, 1000.0, 200.0) for m in machs]
    k_rate = dict(zip(names, (-0.52, -0.50, 0.0, -0.46, -0.44)))
    kp = dict(zip(names, (2.15, 2.07, 0.32, 1.93, 1.86)))  # 0 댐퍼 위에서 튜닝된 자세 게인
    bad = names[2]
    exclude = {"roll.k_rate": {bad: {"loop": "roll_rate", "reason": "sign_mismatch", "basis": "own"}},
               "roll.kp": {bad: {"loop": "roll_rate", "reason": "sign_mismatch", "basis": "rate_loop"}}}
    return ps, machs, names, {"roll.k_rate": k_rate, "roll.kp": kp}, exclude


@pytest.mark.parametrize("mode", ["table", "poly"])
def test_failed_tuning_samples_are_excluded_from_the_fit(mode):
    """튜닝이 성립하지 않은 표본은 적합에 들어가지 않는다 — 표에 자리값 0이 박히지 않는다.

    실패한 튜닝은 "그 점의 게인이 0"이 아니라 "게인을 못 찾았다"다. 표 모드는 표본을 그대로 분할점에
    놓으므로 종전에는 roll.k_rate가 그 점에서 정확히 0이었고(부호가 섞인 표), 그 위에서 튜닝된 roll.kp가
    이웃의 1/6로 튀었다. 뺀 점의 게인은 이웃 보간이 되고, 뺀 사실은 값·사유와 함께 보고에 남는다."""
    ps, machs, names, samples, exclude = _failed_zero_samples()
    out = fit_slots(samples, ps, mode=mode, exclude=exclude)
    for slot, want in (("roll.k_rate", -0.48), ("roll.kp", 2.0)):
        tab = out["tables"][slot]
        got = tab.interp(mach=machs[2])
        assert got == pytest.approx(want, rel=0.02), f"{slot}: 실패 표본이 적합에 들어갔다 ({got})"
        rep = out["reports"][slot]
        assert [r["point"] for r in rep["excluded_samples"]] == [names[2]]
        row = rep["excluded_samples"][0]
        assert row["value"] == samples[slot][names[2]]
        assert row["reason"] == "sign_mismatch" and row["loop"] == "roll_rate"
        assert "exclusion_withheld" not in rep
    assert out["reports"]["roll.k_rate"]["excluded_samples"][0]["basis"] == "own"
    assert out["reports"]["roll.kp"]["excluded_samples"][0]["basis"] == "rate_loop"
    if mode == "table":
        # 분할점에서 빠진다 — 표가 담은 것은 튜닝이 성립한 표본뿐이다
        assert list(out["tables"]["roll.k_rate"].axes[0]) == [machs[i] for i in (0, 1, 3, 4)]
        assert np.all(out["tables"]["roll.k_rate"].data < 0.0)
    # 제외 목록이 없는 자리·exclude 생략은 종전과 같다
    plain = fit_slots(samples, ps, mode=mode)
    assert "excluded_samples" not in plain["reports"]["roll.k_rate"]
    assert plain["tables"]["roll.k_rate"].interp(mach=machs[2]) != pytest.approx(-0.48, rel=0.02)


def test_exclusion_is_withheld_when_fewer_than_two_samples_would_remain():
    """표본이 2개 미만으로 남으면 빼지 않는다(표가 안 선다) — 대신 보류 사실을 보고한다."""
    ps, machs, names, samples, _ = _failed_zero_samples()
    reason = {"loop": "roll_rate", "reason": "no_stable_gain", "basis": "own"}
    exclude = {"roll.k_rate": {n: reason for n in names[:4]}}  # 5개 중 4개 실패 → 1개만 남는다
    out = fit_slots({"roll.k_rate": samples["roll.k_rate"]}, ps, mode="table", exclude=exclude)
    rep = out["reports"]["roll.k_rate"]
    assert "excluded_samples" not in rep
    held = rep["exclusion_withheld"]
    assert held["kept_would_be"] == 1 and held["min_kept"] == 2
    assert [r["point"] for r in held["samples"]] == sorted(names[:4])
    assert len(out["tables"]["roll.k_rate"].axes[0]) == 5  # 보류 — 표본 전부로 섰다
    # 딱 2개가 남으면 뺀다
    exclude2 = {"roll.k_rate": {n: reason for n in names[:3]}}
    rep2 = fit_slots({"roll.k_rate": samples["roll.k_rate"]}, ps, mode="table",
                     exclude=exclude2)["reports"]["roll.k_rate"]
    assert len(rep2["excluded_samples"]) == 3 and "exclusion_withheld" not in rep2


# ── 절점 위 표 (이관 3단계 — 설계점과 절점 분리, 05 §11.5) ─────────────────────────────────


def test_table_on_knots_equals_the_legacy_table_when_samples_sit_on_the_knots():
    """표본이 전부 절점 위에 있으면 최소제곱 해가 곧 절점별 평균이다 — 종전 표 모드(같은 마하 평균)와 같은 표.

    구간 선형 기저에서 절점 k_i의 기저는 이웃 절점 위에서 0이라, 표본이 절점 위에만 있으면 식이 절점마다 갈라진다.
    옛 세션을 표본 규칙(samples)으로 재개하면 같은 표가 나오는 근거다."""
    ps = PointSet()
    machs = (0.3, 0.4, 0.5)
    for m in machs:
        for alt in (0.0, 4000.0):
            ps.add(OperatingPoint(case=TrimCase(name=case_name(m, alt, 200.0), mach=m, alt=alt, fuel=200.0),
                                  role=ROLE_DESIGN, origin="coarse"))
    samples = {case_name(m, alt, 200.0): 1.0 + 0.2 * i + (0.1 if alt else -0.1)
               for i, m in enumerate(machs) for alt in (0.0, 4000.0)}
    legacy = fit_slot("pitch.kp", samples, ps, mode="table")
    on = fit_slot("pitch.kp", samples, ps, mode="table", knots=list(machs))
    assert list(on["table"].axes[0]) == pytest.approx(list(legacy["table"].axes[0]))
    assert list(on["table"].data) == pytest.approx(list(legacy["table"].data), abs=1e-12)
    for key in ("max_residual", "cross_axis_residual", "zigzag", "adjacent_jump_frac", "n_breakpoints"):
        assert on["report"][key] == pytest.approx(legacy["report"][key]), key
    assert on["report"]["knots"] == list(machs) and on["report"]["unsupported_knots"] == []


def test_table_on_knots_fits_many_samples_on_few_knots():
    """설계점이 많아도 표의 분할점은 절점 수 그대로다 — 값은 표본 전부의 최소제곱(구간 선형)."""
    xs = np.linspace(0.1, 0.3, 21)
    ys = 2.0 - 3.0 * xs  # 선형 — 어느 절점 배치로도 정확히 나타난다
    out = table_on_knots(xs, ys, [0.1, 0.2, 0.3])
    assert out["breakpoints"] == [0.1, 0.2, 0.3] and out["n_breakpoints"] == 3
    assert out["values"] == pytest.approx([1.7, 1.4, 1.1])
    assert out["sample_residual"] == pytest.approx(0.0, abs=1e-12)
    # 곡선이면 잔차가 남고 0으로 위장하지 않는다
    curved = table_on_knots(xs, ys + 5.0 * (xs - 0.2) ** 2, [0.1, 0.2, 0.3])
    assert curved["sample_residual"] > 1e-4 and curved["n_breakpoints"] == 3


def test_unsupported_knot_is_dropped_and_reported():
    """표본이 기저 범위(이웃 절점 사이)에 하나도 없는 절점은 값을 정할 수 없다 — 그 표에서 빼고 보고한다.

    쇼케이스 실측이 이 모양이다: 요구영역 공통 좌표는 M0.24까지지만 M0.22 위는 날 수 없어 설계점이 없다. 뺀 절점 너머는
    끝 절점 값으로 clip된다(탑재 형식과 같은 끝단 처리)."""
    xs = np.array([0.10375, 0.11, 0.13, 0.15, 0.18, 0.19, 0.22])
    ys = 1.0 + xs
    out = table_on_knots(xs, ys, [0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22, 0.24])
    assert out["unsupported_knots"] == [0.24]
    assert out["breakpoints"] == [0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22]
    assert out["values"] == pytest.approx([1.10, 1.12, 1.14, 1.16, 1.18, 1.20, 1.22], abs=1e-9)
    # 가운데 빈 절점 — 이웃 절점 사이(열린 구간)에 표본이 없으면 뺀다. 이웃 절점 위의 표본은 그 절점 기저에 0이다
    mid = table_on_knots(np.array([0.1, 0.12, 0.2]), np.array([1.0, 1.1, 1.4]), [0.1, 0.12, 0.14, 0.16, 0.2])
    assert mid["unsupported_knots"] == [0.14, 0.16]
    assert mid["breakpoints"] == [0.1, 0.12, 0.2]


def test_table_on_knots_sign_guard_clips_to_the_samples_sign():
    """최소제곱은 표본 사이에서 부호를 넘길 수 있다(0 근처 표본 + 급변) — 표본 부호로 되돌리고 보고한다.

    되돌리는 값은 0이 아니라 표본 중 가장 작은 크기다 — 0은 그 자리 루프를 끄는 값이다(적합 제외 규칙이 빼는 자리값)."""
    xs = np.array([0.1, 0.12, 0.139, 0.141, 0.16])
    ys = np.array([-0.5, -0.4, -0.3, -0.001, -0.0005])
    out = table_on_knots(xs, ys, [0.1, 0.14, 0.16])
    guard = out["sign_guard"]
    assert guard["want"] == -1.0
    assert all(v < 0.0 for v in out["values"]), out["values"]
    assert guard["clipped"], "이 표본은 부호를 넘기는 해를 내야 시험이 된다"
    assert all(c["to"] == pytest.approx(-0.0005) for c in guard["clipped"])


def test_fit_slots_passes_knots_per_slot_and_poly_mode_ignores_them():
    ps = _points_1d(MACHS)
    samples = {"pitch.kp": {case_name(m, 1000.0, 200.0): float(-2.0 * f) for m, f in zip(MACHS, DP)},
               "pitch.ki": {case_name(m, 1000.0, 200.0): float(-0.3 * f) for m, f in zip(MACHS, DP)}}
    out = fit_slots(samples, ps, mode="table", knots_by_slot={"pitch.kp": [0.15, 0.55, 0.95]})
    assert list(out["tables"]["pitch.kp"].axes[0]) == pytest.approx([0.15, 0.55, 0.95])
    assert len(out["tables"]["pitch.ki"].axes[0]) == len(MACHS), "절점 없는 자리는 옛 표(표본 마하마다)"
    poly = fit_slots(samples, ps, mode="poly", knots_by_slot={"pitch.kp": [0.15, 0.55, 0.95]})
    assert isinstance(poly["tables"]["pitch.kp"], PolyTable) and "knots" not in poly["reports"]["pitch.kp"]


@pytest.mark.parametrize("xs, ys, knots, dropped", [
    # 끝 절점 — 이웃 절점을 살짝 넘은 표본 하나만 닿는다(가중 0.02). 종전 해는 4.10(표본 범위 1.0~1.25 밖)
    ([0.1, 0.12, 0.14, 0.16, 0.18, 0.2, 0.2012], [1.0, 1.05, 1.1, 1.12, 1.15, 1.2, 1.25], [0.1, 0.14, 0.2, 0.26], [0.26]),
    # 같은 모양에 이웃 절점 위 표본이 흩어졌다 — 종전 해 12.3
    ([0.1, 0.14, 0.2, 0.2, 0.2019], [1.0, 1.1, 1.2, 1.3, 1.6], [0.1, 0.14, 0.2, 0.26], [0.26]),
    # 가운데 절점 — 양 끝 절점 바로 옆 표본만 닿는다(가중 0.002). 종전 해 358
    ([0.5, 0.5, 0.5005, 1.0, 0.9995], [1.0, 1.1, 2.3, 2.0, 2.0], [0.5, 0.75, 1.0], [0.75]),
])
def test_barely_supported_knot_is_dropped_not_extrapolated(xs, ys, knots, dropped):
    """절점에서 먼 표본 하나(작은 기저 가중)만 닿는 절점은 값이 v_이웃 + (y − v_이웃)/t로 폭주한다(리뷰 실측 1.763→31.2,
    가운데 2501). 가중 0.5(절점에서 반 구간) 이상 표본이 있어야 받쳐진 절점으로 보고 아니면 뺀다 — 값은 표본 범위에 남는다."""
    out = table_on_knots(np.array(xs), np.array(ys), knots)
    assert out["unsupported_knots"] == dropped
    lo, hi = min(ys), max(ys)
    span = hi - lo
    assert all(lo - 0.05 * span <= v <= hi + 0.05 * span for v in out["values"]), out["values"]
    why = {d["knot"]: d for d in out["unsupported_detail"]}
    assert why[dropped[0]]["reason"] == "far" and why[dropped[0]]["weight"] < 0.5


def test_unsupported_detail_tells_empty_from_far():
    """사유를 가른다 — 기저 범위에 표본이 아예 없음(none) · 있으나 절점에서 멀다(far, 가중 < 0.5)."""
    out = table_on_knots(np.array([0.1, 0.12, 0.2, 0.2]), np.array([1.0, 1.1, 1.4, 1.4]), [0.1, 0.12, 0.14, 0.2, 0.3])
    by = {d["knot"]: d["reason"] for d in out["unsupported_detail"]}
    assert by == {0.14: "none", 0.3: "none"}
    assert "표본 없음" in out["unsupported_detail"][0]["text"]


def test_support_filter_is_stable():
    """거른 결과는 고정점이다 — 남은 절점으로 다시 풀면 더 빠지는 절점이 없고 값도 같다.

    절점을 빼면 이웃 기저가 넓어지므로 거르기를 안정될 때까지 되풀이한다. (가중 0.5 문턱에서는 뺀 절점이 이웃을
    살리는 일은 없다 — 이웃과 사이 표본은 둘 중 하나에 0.5 이상이다. 되풀이는 끝 절점 clip·표본 없는 구간이 겹칠 때의
    안전판이다)"""
    xs = np.array([0.1, 0.12, 0.13, 0.2, 0.33, 0.4])
    ys = np.array([1.0, 1.1, 1.15, 1.3, 1.5, 1.6])
    out = table_on_knots(xs, ys, [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5])
    assert out["unsupported_knots"] == [0.25, 0.3, 0.5]  # 0.3은 0.33(가중 0.4)만 닿는다
    again = table_on_knots(xs, ys, out["breakpoints"])
    assert again["unsupported_knots"] == [] and again["values"] == pytest.approx(out["values"])


def test_underdetermined_knots_pick_the_straight_interpolant_scale_free():
    """식이 모자라는 경로(가중 0.5 표본 하나가 두 절점을 함께 정한다) — 2차 차분 정칙화로 곧은 보간을 고르고,
    그 해는 게인 크기와 무관하다(y를 스케일로 나눈 뒤 고정 무차원 가중치 — 종전에는 가중치가 |y|에 비례했다)."""
    xs = np.array([0.1, 0.15, 0.3])
    ys = np.array([1.0, 1.5, 3.0])
    knots = [0.1, 0.2, 0.3]
    out = table_on_knots(xs, ys, knots)
    assert out["underdetermined"] is False  # 표본 3·절점 3 — 풀린다(대조)
    # 0.1·0.2를 표본 0.15(가중 0.5·0.5) 하나가 정한다 + 끝 0.3 — 절점 3에 독립 식 2
    xs2 = np.array([0.15, 0.3])
    ys2 = np.array([1.5, 3.0])
    a = table_on_knots(xs2, ys2, knots)
    assert a["underdetermined"] is True
    assert a["values"] == pytest.approx([1.0, 2.0, 3.0], abs=1e-3), "곧은 보간(선형)을 골라야 한다"
    b = table_on_knots(xs2, 1e4 * ys2, knots)
    assert np.array(b["values"]) / 1e4 == pytest.approx(a["values"], rel=1e-9), "해가 게인 크기에 따라 달라졌다"


def test_table_on_knots_sign_guard_floor_is_local_and_zero_is_a_violation():
    """되돌림 값은 **그 절점 기저 범위 안** 같은 부호 표본의 최소 크기다 — 전역 최소는 먼 자리의 작은 게인을 끌고 온다.
    정확히 0도 위반이다(0은 그 자리 루프를 끄는 값)."""
    from claw.design import fit as F

    # 부호 보호 시험의 모양(0.16 절점이 +로 넘어간다)에 먼 자리(M0.05) 아주 작은 표본 -0.0001을 더한다 — 전역 최소로
    # 되돌리면 -0.0001, 그 절점 기저 범위(0.14, 0.16] 안 최소는 -0.0005
    xs = np.array([0.05, 0.1, 0.12, 0.139, 0.141, 0.16])
    ys = np.array([-0.0001, -0.5, -0.4, -0.3, -0.001, -0.0005])
    out = F.table_on_knots(xs, ys, [0.05, 0.1, 0.14, 0.16])
    assert all(v < 0.0 for v in out["values"])
    assert out["sign_guard"]["clipped"] == [{"knot": 0.16, "from": pytest.approx(0.0073, abs=1e-4),
                                             "to": pytest.approx(-0.0005)}]

    # 정확히 0 — lstsq가 0을 내는 모양은 만들기 어려워 해 자리를 직접 겨냥한다
    orig = np.linalg.lstsq
    try:
        np.linalg.lstsq = lambda A, b, rcond=None: (np.array([-1.0, 0.0, -1.0]), None, None, None)
        z = F.table_on_knots(np.array([0.1, 0.2, 0.3]), np.array([-1.0, -0.5, -1.0]), [0.1, 0.2, 0.3])
    finally:
        np.linalg.lstsq = orig
    assert [c["knot"] for c in z["sign_guard"]["clipped"]] == [0.2]
    assert z["values"][1] == pytest.approx(-0.5)
