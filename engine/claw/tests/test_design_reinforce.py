"""보강 — 보강 지표 d · 허용치·예산·합격 기준 분리 · 잴 수 없는 구간 (05 §11.7 — 이관 4단계).

실험 코드(experiments/grid_system/gridsys.py)의 규칙을 제품 모듈로 옮긴 것을 합성 마진 결과로 본다: 척도는 튜닝 목표와
독립이고, d는 절점 끝점 사이 선형 보간에서 벗어난 양을 척도로 나눈 값이며, 잴 수 없는 구간은 버리지 않고 목록에 남는다.
"""

import pytest

from claw.common.contracts import TrimCase
from claw.design.criteria import MarginCriteria
from claw.design.points import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, PointSet, case_name
from claw.design.reinforce import (
    D_METRIC,
    DEFAULT_REINFORCE,
    PM_D_SCALE_PROVISIONAL,
    REINFORCE_STATUS_TEXT,
    ROLL_LAMBDA_D_SCALE_PROVISIONAL,
    check_reinforce_config,
    d_distribution,
    d_scale_sources,
    d_scales,
    reinforce_candidates,
    reinforce_points,
    reinforce_status,
    segment_d,
)
from claw.design.tune import TuneTargets

ROW = (200.0, 25.0)
SCALES = {"pitch_rate": 0.2}


def _name(m, row=ROW):
    return case_name(m, *row)


def _case(zeta=None, status="ok", **metrics):
    return {"loops": {"pitch_rate": {"zeta": zeta, "status": status, **metrics}}}


def _mid(m, row=ROW, **kw):
    return {"name": _name(m, row), "mach": m, "alt": row[0], "fuel": row[1], "kind": "midpoint",
            "row": list(row), "origin": "midpoint", "pre_state": "not_run", "existing": False, **kw}


# ── 척도 ──────────────────────────────────────────────────────────────────────────────


def test_scales_come_from_the_criteria_not_from_the_tuning_targets():
    """ζ는 권장선 − 합격선(0.5 − 0.3), PM·λ는 독립 잠정 상수 — 튜닝 목표를 바꿔도 그대로다(04 §1 세 층 분리)."""
    s = d_scales(MarginCriteria())
    assert s == {"pitch_rate": pytest.approx(0.2), "yaw_rate": pytest.approx(0.2),
                 "roll_rate": ROLL_LAMBDA_D_SCALE_PROVISIONAL, "pitch_att": PM_D_SCALE_PROVISIONAL,
                 "roll_att": PM_D_SCALE_PROVISIONAL}
    assert (PM_D_SCALE_PROVISIONAL, ROLL_LAMBDA_D_SCALE_PROVISIONAL) == (5.0, 3.6)
    assert d_scales(MarginCriteria(zeta_good=0.6))["pitch_rate"] == pytest.approx(0.3)
    # 튜닝 목표는 인자에 없다 — 목표 쪽 값을 바꿔도 척도를 움직일 길이 없다
    assert TuneTargets(roll_lambda=20.0) and d_scales(MarginCriteria())["roll_rate"] == 3.6
    src = d_scale_sources(MarginCriteria())
    assert set(src) == set(D_METRIC) and "0.5" in src["pitch_rate"] and "잠정" in src["pitch_att"]
    assert "3.6" in src["roll_rate"]


def test_config_defaults_and_rejections():
    assert check_reinforce_config({}) == DEFAULT_REINFORCE
    assert DEFAULT_REINFORCE == {"tol": None, "max_points": 24, "max_depth": 3, "max_time_s": None}
    assert check_reinforce_config({"tol": 0.5, "max_time_s": 30})["tol"] == 0.5
    for bad in ({"tol": 0}, {"tol": -1.0}, {"tol": float("inf")}, {"max_points": -1}, {"max_points": 1.5},
                {"max_depth": 0}, {"max_depth": 9}, {"max_time_s": 0}, {"what": 1}, {"max_points": True}):
        with pytest.raises(ValueError):
            check_reinforce_config(bad)


# ── 보강 지표 d ───────────────────────────────────────────────────────────────────────


def test_segment_d_measures_the_departure_from_the_straight_line_between_knot_ends():
    cases = {_name(0.1): _case(0.4), _name(0.2): _case(0.6), _name(0.125): _case(0.6)}
    got = segment_d([_mid(0.125)], cases, [0.1, 0.2], SCALES)
    (r,) = got["d"]
    # lerp at t=¼ = 0.45 · |0.6 − 0.45| / 0.2 = 0.75
    assert r["d"] == pytest.approx(0.75) and r["t"] == pytest.approx(0.25)
    assert (r["row"], r["interval"], r["slot"], r["point"], r["depth"]) == ([200.0, 25.0], [0.1, 0.2], "pitch_rate",
                                                                            _name(0.125), 0)
    assert got["unmeasured"] == [] and got["verdict_change"] == 0


def test_an_interval_that_cannot_be_measured_is_listed_never_dropped():
    """양끝·중간 중 하나라도 계산 불가면 d를 잴 수 없다 — 「잴 수 없는 구간」으로 남는다(05 §11.7)."""
    cases = {_name(0.1): {"loops": {}}, _name(0.2): _case(0.6), _name(0.15): _case(0.5),
             _name(0.25): _case(0.5), _name(0.3): _case(None)}
    entries = [_mid(0.15), _mid(0.25), _mid(0.35)]
    got = segment_d(entries, cases, [0.1, 0.2, 0.3, 0.4], SCALES)
    assert got["d"] == []
    why = {tuple(u["interval"]): u["why"] for u in got["unmeasured"]}
    assert "트림" in why[(0.1, 0.2)]  # 끝점 트림 미수렴
    assert "지표" in why[(0.2, 0.3)]  # 끝점 ζ 없음(비유한)
    assert "미계산" in why[(0.3, 0.4)]  # 중간·끝 결과가 없다


def test_the_end_outside_the_row_range_is_named_with_its_plan_state():
    cases = {_name(0.15): _case(0.5), _name(0.2): _case(0.5)}
    knot = {**_mid(0.1), "kind": "knot", "pre_state": "out_of_region"}
    got = segment_d([_mid(0.15), knot], cases, [0.1, 0.2], SCALES)
    (u,) = got["unmeasured"]
    assert "요구영역 밖" in u["why"]
    # 절점이 행 범위 밖이라 계획에 점조차 없으면 그렇게 말한다(쇼케이스 200 m 줄 — 행 하한 M0.10375가 첫 절점 0.10보다 안쪽)
    (u,) = segment_d([_mid(0.15)], cases, [0.1, 0.2], SCALES)["unmeasured"]
    assert "계획에 없다" in u["why"]


def test_a_verdict_change_between_neighbours_is_counted():
    cases = {_name(0.1): _case(0.4, "ok"), _name(0.2): _case(0.2, "fail"), _name(0.15): _case(0.3, "warn")}
    got = segment_d([_mid(0.15)], cases, [0.1, 0.2], SCALES)
    assert got["verdict_change"] == 1
    assert got["verdict_change_intervals"] == [{"row": [200.0, 25.0], "interval": [0.1, 0.2]}]


def test_distribution_is_per_slot():
    dres = {"d": [{"slot": "pitch_rate", "d": x} for x in (0.1, 0.2, 0.3, 0.4)] + [{"slot": "roll_att", "d": 1.0}]}
    dist = d_distribution(dres)
    assert dist["pitch_rate"]["n"] == 4 and dist["pitch_rate"]["max"] == pytest.approx(0.4)
    assert dist["pitch_rate"]["p50"] == pytest.approx(0.25) and dist["roll_att"]["p90"] == pytest.approx(1.0)


# ── 이분 ──────────────────────────────────────────────────────────────────────────────


def _dres(*rows):
    return {"d": [{"row": [200.0, 25.0], "interval": [a, b], "slot": "pitch_rate", "d": d, "t": 0.5, "point": _name(p),
                   "mach": p, "depth": depth} for a, b, p, d, depth in rows], "unmeasured": []}


def test_worst_interval_is_split_at_its_interior_point_first():
    pts = PointSet()
    dres = _dres((0.1, 0.2, 0.125, 0.4, 0), (0.2, 0.3, 0.25, 0.9, 0), (0.3, 0.4, 0.35, 0.05, 0))
    got = reinforce_candidates(dres, tol=0.3, max_points_left=10, max_depth=3, points=pts)
    # 최악(0.9) 먼저 — [0.2, 0.25]·[0.25, 0.3]의 중점, 그다음 0.4 구간 — [0.1, 0.125]·[0.125, 0.2]
    assert [e["mach"] for e in got] == [0.225, 0.275, 0.1125, 0.1625]
    assert got[0]["origin"] == "reinforce:pitch_rate:0.2|0.25" and got[0]["interval"] == [0.2, 0.25]
    assert got[0]["parent"] == [0.2, 0.3] and got[0]["depth"] == 1 and got[0]["kind"] == "reinforce"
    ops = reinforce_points(dres, tol=0.3, max_points_left=2, max_depth=3, points=pts)
    assert [p.case.mach for p in ops] == [0.225, 0.275]  # 예산 — 두 점이 한 이분이다
    assert all(isinstance(p, OperatingPoint) and p.role == ROLE_VALIDATION for p in ops)


def test_depth_budget_and_already_split_intervals_stop_the_bisection():
    dres = _dres((0.2, 0.3, 0.25, 0.9, 3))
    assert reinforce_candidates(dres, tol=0.3, max_points_left=10, max_depth=3, points=PointSet()) == []
    # 이미 쪼갠 구간 — 계획에 그 부모의 보강 항목이 있다
    child = {"kind": "reinforce", "row": [200.0, 25.0], "parent": [0.2, 0.3], "name": _name(0.225)}
    assert reinforce_candidates(_dres((0.2, 0.3, 0.25, 0.9, 0)), tol=0.3, max_points_left=10, max_depth=3,
                                points=PointSet(), entries=[child]) == []
    assert reinforce_candidates(_dres((0.2, 0.3, 0.25, 0.9, 0)), tol=0.3, max_points_left=1, max_depth=3,
                                points=PointSet()) == []


def test_status_keeps_tolerance_budget_and_unmeasured_apart():
    """허용치 미설정은 d 분포만 · 남은 구간이 있으면 「보강 종료 · 추가 검증 필요」(합격·불가로 바꾸지 않는다) · 잴 수 없는
    구간이 있으면 「보강 완료」가 아니다."""
    dres = _dres((0.1, 0.2, 0.15, 0.4, 0), (0.2, 0.3, 0.25, 0.1, 0))
    assert reinforce_status(dres, [], tol=None)["status"] == "tol_unset"
    assert REINFORCE_STATUS_TEXT["tol_unset"] == "허용치 미설정 — d 분포만"
    b = reinforce_status(dres, [], tol=0.3)
    assert b["status"] == "budget" and b["max_d_remaining"] == pytest.approx(0.4)
    assert b["remaining"] == [{"row": [200.0, 25.0], "interval": [0.1, 0.2], "d": 0.4, "slot": "pitch_rate"}]
    assert b["label"].startswith("보강 종료 · 추가 검증 필요") and "0.4" in b["label"]
    # 쪼갠 구간은 남은 구간이 아니다 — 그 자식 구간이 대신 잰다
    child = {"kind": "reinforce", "row": [200.0, 25.0], "parent": [0.1, 0.2]}
    assert reinforce_status(dres, [child], tol=0.3)["status"] == "done"
    assert reinforce_status(dres, [child], tol=0.3)["label"] == "보강 완료"
    un = {**dres, "unmeasured": [{"row": [200.0, 25.0], "interval": [0.3, 0.4], "why": "x"}]}
    assert reinforce_status(un, [child], tol=0.3)["label"] == "보강 종료 · 잴 수 없는 구간 있음"


def test_a_child_midpoint_that_is_already_a_point_is_measured_there_for_free():
    """이분한 조각의 중점이 이미 점이면(설계점 등) 건너뛰지 않는다 — 그 점을 공짜 항목(existing)으로 실어 d를 거기서 잰다.
    건너뛰면 형제 조각만 부모를 「쪼갠」 것으로 만들어, 빠진 조각에는 d도 남은 구간도 잴 수 없는 구간도 없이 「보강
    완료」가 거짓으로 뜬다(리뷰 MUST 1)."""
    pts = PointSet([OperatingPoint(case=TrimCase(name=_name(0.225), mach=0.225, alt=200.0, fuel=25.0), role=ROLE_DESIGN)])
    got = reinforce_candidates(_dres((0.2, 0.3, 0.25, 0.9, 0)), tol=0.3, max_points_left=1, max_depth=3, points=pts)
    # 새 점은 0.275 하나라 예산 1에 든다 — 0.225는 공짜
    assert [(e["mach"], e["existing"]) for e in got] == [(0.225, True), (0.275, False)]
    assert all(e["parent"] == [0.2, 0.3] and not e.get("gap") for e in got)
    assert [p.case.mach for p in reinforce_points(_dres((0.2, 0.3, 0.25, 0.9, 0)), tol=0.3, max_points_left=1,
                                                  max_depth=3, points=pts)] == [0.275]
    # 공짜 조각도 d를 잰다 — 양끝(0.2 · 0.25)과 중점(0.225) 결과가 있으면 그 조각의 d가 나온다
    child = {**got[0], "added": False}
    cases = {_name(0.2): _case(0.4), _name(0.25): _case(0.6), _name(0.225): _case(0.5)}
    (r,) = segment_d([child], cases, [0.2, 0.3], SCALES)["d"]
    assert r["interval"] == [0.2, 0.25] and r["d"] == pytest.approx(0.0)
    # 두 조각 중점이 모두 이미 점이어도 부모는 쪼갠 것이다 — 남은 구간(예산)으로 잘못 남지 않는다
    both = PointSet([OperatingPoint(case=TrimCase(name=_name(m), mach=m, alt=200.0, fuel=25.0), role=ROLE_DESIGN)
                     for m in (0.225, 0.275)])
    got2 = reinforce_candidates(_dres((0.2, 0.3, 0.25, 0.9, 0)), tol=0.3, max_points_left=0, max_depth=3, points=both)
    assert [e["existing"] for e in got2] == [True, True]
    assert reinforce_status(_dres((0.2, 0.3, 0.25, 0.9, 0)), got2, tol=0.3)["remaining"] == []


def test_a_child_midpoint_already_planned_is_an_alias_not_a_second_count():
    """조각 중점이 이미 계획 항목(다른 종류)이면 이름이 겹친다 — 보강 항목은 재기만 하는 항목(measure_only)이라 요청 수에
    두 번 세지 않는다."""
    pts = PointSet([OperatingPoint(case=TrimCase(name=_name(0.225), mach=0.225, alt=200.0, fuel=25.0),
                                   role=ROLE_VALIDATION)])
    got = reinforce_candidates(_dres((0.2, 0.3, 0.25, 0.9, 0)), tol=0.3, max_points_left=4, max_depth=3, points=pts,
                               entries=[_mid(0.225)])
    assert got[0]["existing"] and got[0]["measure_only"] and not got[1].get("measure_only")


def test_a_piece_too_narrow_for_a_midpoint_is_left_as_unmeasured_with_its_reason():
    """조각이 반올림 자릿수보다 좁아 중점을 둘 수 없으면 조용히 빼지 않는다 — 잴 수 없는 구간으로 남고 보강 완료가 아니다."""
    a, b, p = 0.2, 0.2000008, 0.2000004  # 폭 0.4e-6 — 반올림 6자리 중점이 조각 밖
    got = reinforce_candidates(_dres((a, b, p, 0.9, 0)), tol=0.3, max_points_left=10, max_depth=3, points=PointSet())
    assert len(got) == 2 and all(e["gap"] and e["measure_only"] for e in got)
    assert reinforce_points(_dres((a, b, p, 0.9, 0)), tol=0.3, max_points_left=10, max_depth=3,
                            points=PointSet()) == []
    un = segment_d(got, {}, [a, b], SCALES)["unmeasured"]
    assert len(un) == 2 and all("좁" in u["why"] for u in un)
    dres = {**_dres((a, b, p, 0.9, 0)), "unmeasured": un}
    st = reinforce_status(dres, got, tol=0.3)
    assert st["remaining"] == [] and st["status"] == "unmeasured"  # 예산 탓이 아니다 — 잴 수 없음
