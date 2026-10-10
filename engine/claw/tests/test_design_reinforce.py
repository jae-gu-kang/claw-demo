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
    DEFAULT_TOL,
    INTERVAL_STATUS,
    PM_D_SCALE_PROVISIONAL,
    REINFORCE_STATUS_TEXT,
    ROLL_LAMBDA_D_SCALE_PROVISIONAL,
    check_reinforce_config,
    d_distribution,
    d_scale_sources,
    d_scales,
    reinforce_candidates,
    reinforce_intervals,
    reinforce_points,
    reinforce_status,
    segment_d,
    split_reasons,
    tol_for,
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
    # [기본값 2026-10-10] 허용치 0.10(척도의 10 % — 단일 값) 기본 켬 · 이웃 판정 다름도 쪼갬 · 합격선 근접은 예약(None)
    assert DEFAULT_REINFORCE == {"tol": 0.10, "max_points": 24, "max_depth": 3, "max_time_s": None,
                                 "on_verdict_change": True, "near_line_frac": None}
    assert DEFAULT_TOL == 0.10 and INTERVAL_STATUS == ("split", "remaining", "unmeasured", "ok")
    assert check_reinforce_config({"tol": 0.5, "max_time_s": 30})["tol"] == 0.5
    assert check_reinforce_config({"tol": None})["tol"] is None  # 명시로 끈다 — d 분포만
    for bad in ({"tol": 0}, {"tol": -1.0}, {"tol": float("inf")}, {"max_points": -1}, {"max_points": 1.5},
                {"max_depth": 0}, {"max_depth": 9}, {"max_time_s": 0}, {"what": 1}, {"max_points": True},
                {"tol": {}}, {"tol": {"bogus": 0.1}}, {"tol": {"roll_rate": float("nan")}}, {"tol": {"roll_rate": 0}},
                {"tol": {"roll_rate": True}}, {"tol": "0.1"}, {"on_verdict_change": 1}, {"on_verdict_change": None},
                {"near_line_frac": 0}, {"near_line_frac": 1.5}, {"near_line_frac": float("nan")},
                {"near_line_frac": True}):
        with pytest.raises(ValueError):
            check_reinforce_config(bad)
    assert check_reinforce_config({"near_line_frac": 0.2})["near_line_frac"] == 0.2  # 예약 — 받기만 한다


def test_per_slot_tolerance_is_accepted_and_filled_with_the_single_default():
    """자리별 허용치 {slot: 값} — 아는 자리만, 빠진 자리는 단일 기본값(자리별 기본값은 없다)으로 채운 정규형이 된다."""
    got = check_reinforce_config({"tol": {"roll_rate": 0.2, "pitch_rate": 0.05}})["tol"]
    assert got == {"pitch_rate": 0.05, "yaw_rate": 0.1, "roll_rate": 0.2, "pitch_att": 0.1, "roll_att": 0.1}
    assert list(got) == list(D_METRIC)
    assert tol_for(got, "roll_rate") == 0.2 and tol_for(0.3, "roll_rate") == 0.3 and tol_for(None, "roll_rate") is None
    assert tol_for({"roll_rate": 0.2}, "pitch_att") == DEFAULT_TOL  # 정규형이 아닌 dict도 빠진 자리는 기본값


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
    assert b["remaining"] == [{"row": [200.0, 25.0], "interval": [0.1, 0.2], "d": 0.4, "slot": "pitch_rate", "tol": 0.3,
                               "reasons": ["d"]}]
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


# ── 허용치 규칙 · 판정 다름 · 구간별 기록 (⑤ 보강 허용치 — 2026-10-10) ─────────────────────


def _rec(a, b, p, slot, d, depth=0, row=ROW):
    return {"row": list(row), "interval": [a, b], "slot": slot, "d": d, "t": 0.5, "point": _name(p, row), "mach": p,
            "depth": depth}


def test_per_slot_tolerance_compares_each_slot_with_its_own_value():
    """구간 A: pitch 0.4(허용치 0.5 안) · roll 0.15(허용치 0.1 넘음) → 쪼갠다(roll 자리). 구간 B: pitch 0.45 · roll 0.05 → 둘 다
    안이라 쪼개지 않는다. 같은 d를 단일 허용치 0.3으로 보면 B(0.45)가 먼저다 — 비교와 순서가 자리별 값을 따른다."""
    dres = {"d": [_rec(0.1, 0.2, 0.15, "pitch_rate", 0.4), _rec(0.1, 0.2, 0.15, "roll_rate", 0.15),
                  _rec(0.2, 0.3, 0.25, "pitch_rate", 0.45), _rec(0.2, 0.3, 0.25, "roll_rate", 0.05)], "unmeasured": []}
    tol = {"pitch_rate": 0.5, "roll_rate": 0.1}
    got = reinforce_candidates(dres, tol=tol, max_points_left=10, max_depth=3, points=PointSet())
    assert [e["mach"] for e in got] == [0.125, 0.175]
    assert got[0]["origin"] == "reinforce:roll_rate:0.1|0.15" and got[0]["slot"] == "roll_rate"
    assert got[0]["d_trigger"] == 0.15 and got[0]["reasons"] == ["d"]
    single = reinforce_candidates(dres, tol=0.3, max_points_left=10, max_depth=3, points=PointSet())
    assert [e["mach"] for e in single] == [0.225, 0.275, 0.125, 0.175]
    st = reinforce_status(dres, [], tol=tol)
    assert st["status"] == "budget" and st["remaining"] == [
        {"row": [200.0, 25.0], "interval": [0.1, 0.2], "d": 0.15, "slot": "roll_rate", "tol": 0.1, "reasons": ["d"]}]
    assert "허용치 0.1" in st["label"]


def _flip_cases(m_a, m_mid, m_b, verdicts=("ok", "warn", "warn"), zetas=(0.4, 0.4, 0.4)):
    return {_name(m): _case(z, v) for m, z, v in zip((m_a, m_mid, m_b), zetas, verdicts)}


def test_a_verdict_change_forces_a_split_whatever_d_is():
    """양끝·중간 판정이 갈리면 d가 0이어도 쪼갠다(on_verdict_change — 기본 켬). 끄면 d만 사유이고, 허용치를 끄면(None)
    판정 다름도 쪼개지 않는다(보강 끔)."""
    dres = segment_d([_mid(0.15)], _flip_cases(0.1, 0.15, 0.2), [0.1, 0.2], SCALES)
    assert dres["d"][0]["d"] == pytest.approx(0.0) and dres["verdict_change"] == 1
    assert dres["intervals"] == [{"row": [200.0, 25.0], "interval": [0.1, 0.2], "point": _name(0.15), "mach": 0.15,
                                  "depth": 0, "points": [_name(0.1), _name(0.15), _name(0.2)],
                                  "verdicts": {"a": "ok", "mid": "warn", "b": "warn"}}]
    got = reinforce_candidates(dres, tol=0.1, max_points_left=10, max_depth=3, points=PointSet(), on_verdict_change=True)
    assert [e["mach"] for e in got] == [0.125, 0.175]
    assert all(e["reasons"] == ["verdict_change"] and e["origin"].startswith("reinforce:verdict_change:") for e in got)
    assert got[0]["slot"] == "pitch_rate" and got[0]["d_trigger"] == pytest.approx(0.0)  # 최악 자리는 적되 사유는 판정
    assert reinforce_candidates(dres, tol=0.1, max_points_left=10, max_depth=3, points=PointSet(),
                                on_verdict_change=False) == []
    assert reinforce_candidates(dres, tol=None, max_points_left=10, max_depth=3, points=PointSet(),
                                on_verdict_change=True) == []
    # d도 넘으면 사유 둘 — d 초과 구간이 판정 다름만인 구간보다 먼저다
    both = {**dres, "d": [{**dres["d"][0], "d": 0.5}]}
    (e, _) = reinforce_candidates(both, tol=0.1, max_points_left=10, max_depth=3, points=PointSet(),
                                  on_verdict_change=True)
    assert e["reasons"] == ["d", "verdict_change"] and e["origin"].startswith("reinforce:pitch_rate:")
    assert split_reasons([{**e, "added": True}]) == {"d": 1, "verdict_change": 1}
    assert split_reasons([{"kind": "reinforce", "row": [200.0, 25.0], "parent": [0.1, 0.2]}]) == {"d": 1, "verdict_change": 0}


def test_termination_a_localized_verdict_change_is_not_left_but_an_exceeding_d_is():
    """판정 다름만인 구간이 깊이 max_depth에 닿으면 판정이 바뀌는 자리를 그 폭까지 좁힌 것이다 — 남은 구간이 아니고(ok ·
    보강 완료) 더 쪼개지도 않는다. d 초과 구간은 깊이에 닿아도 남은 구간(예산 종료)이다. 판정 다름만인 구간이 추가점
    예산에 막히면 남은 구간이다."""
    ch = {**_mid(0.15), "kind": "reinforce", "interval": [0.1, 0.2], "parent": [0.1, 0.3], "depth": 3}
    dres = segment_d([ch], _flip_cases(0.1, 0.15, 0.2), [0.1, 0.3], SCALES)
    kw = dict(tol=0.1, on_verdict_change=True, max_depth=3)
    assert reinforce_candidates(dres, max_points_left=10, points=PointSet(), **{**kw, "max_depth": 3}) == []
    (iv,) = reinforce_intervals(dres, [ch], **kw)
    assert iv["status"] == "ok" and iv["verdict_change"] and iv["reasons"] == ["verdict_change"] and iv["depth"] == 3
    assert reinforce_status(dres, [ch], **kw)["status"] == "done"
    # 같은 구간이 d도 넘으면 깊이에 막힌 남은 구간
    over = {**dres, "d": [{**dres["d"][0], "d": 0.5}]}
    st = reinforce_status(over, [ch], **kw)
    assert st["status"] == "budget" and st["remaining"][0]["reasons"] == ["d", "verdict_change"]
    assert "최대 d 0.5 > 허용치 0.1" in st["label"] and "이웃 판정 다름 1" in st["label"]
    # 깊이 0의 판정 다름 — 추가점이 없어 못 쪼갰으면 남은 구간이다(사유는 판정 다름뿐 — 「최대 d > 허용치」라 적지 않는다)
    top = segment_d([_mid(0.15)], _flip_cases(0.1, 0.15, 0.2), [0.1, 0.2], SCALES)
    assert reinforce_candidates(top, max_points_left=1, points=PointSet(), **kw) == []
    st = reinforce_status(top, [], **kw)
    assert st["status"] == "budget" and st["remaining"][0]["reasons"] == ["verdict_change"]
    assert "최대 d" not in st["label"] and st["label"].endswith("이웃 판정 다름 1")
    assert reinforce_status(top, [], tol=0.1, on_verdict_change=False, max_depth=3)["status"] == "done"


def test_the_three_end_states_done_budget_unmeasured():
    """쪼갤 사유가 없고 잴 수 없는 구간도 없으면 보강 완료 · 사유가 남으면 예산 종료 · 사유는 없는데 잴 수 없는 구간이
    있으면 잴 수 없음 — 셋은 섞이지 않는다(남은 구간이 잴 수 없는 구간보다 먼저 말해진다)."""
    ok = {"d": [_rec(0.1, 0.2, 0.15, "pitch_rate", 0.05)], "unmeasured": []}
    un = {**ok, "unmeasured": [{"row": [200.0, 25.0], "interval": [0.2, 0.3], "point": None, "why": "x"}]}
    over = {**un, "d": [_rec(0.1, 0.2, 0.15, "pitch_rate", 0.5)]}
    got = [reinforce_status(x, [], tol=0.1, on_verdict_change=True, max_depth=3)["status"] for x in (ok, un, over)]
    assert got == ["done", "unmeasured", "budget"]
    assert [REINFORCE_STATUS_TEXT[k] for k in ("done", "unmeasured")] == ["보강 완료", "보강 종료 · 잴 수 없는 구간 있음"]


def test_intervals_payload_has_the_contract_shape_and_every_status():
    """reinforcement.intervals(⑥의 입력) — 구간마다 row · interval · depth · slot(최악) · d · tol · exceeds ·
    verdict_change · verdicts{a, mid, b} · points · status(split|remaining|unmeasured|ok) · reasons · why."""
    knots = [0.1, 0.2, 0.3, 0.4, 0.5]
    cases = {_name(0.1): _case(0.4), _name(0.2): _case(0.4), _name(0.3): _case(0.4), _name(0.4): _case(0.4),
             _name(0.15): _case(0.6), _name(0.125): _case(0.5), _name(0.175): _case(0.5),
             _name(0.25): _case(0.4), _name(0.35): _case(0.9)}
    entries = [_mid(0.15), _mid(0.25), _mid(0.35), _mid(0.45)]
    # [0.1, 0.2]는 쪼갰다 — 두 조각의 보강점(깊이 1)이 잰다
    kids = [{**_mid(m), "kind": "reinforce", "interval": iv, "parent": [0.1, 0.2], "depth": 1, "reasons": ["d"]}
            for m, iv in ((0.125, [0.1, 0.15]), (0.175, [0.15, 0.2]))]
    plan = entries + kids
    dres = segment_d(plan, cases, knots, SCALES)
    ivs = reinforce_intervals(dres, plan, tol=0.1, on_verdict_change=True, max_depth=3)
    by = {tuple(i["interval"]): i for i in ivs}
    assert {k: i["status"] for k, i in by.items()} == {
        (0.1, 0.15): "ok", (0.1, 0.2): "split", (0.15, 0.2): "ok", (0.2, 0.3): "ok", (0.3, 0.4): "remaining",
        (0.4, 0.5): "unmeasured"}
    assert {i["status"] for i in ivs} == set(INTERVAL_STATUS)
    for i in ivs:
        assert set(i) == {"row", "interval", "depth", "slot", "d", "tol", "exceeds", "verdict_change", "verdicts",
                          "points", "status", "reasons", "why"}
    r = by[(0.3, 0.4)]
    assert r["exceeds"] and r["d"] == pytest.approx(2.5) and r["tol"] == 0.1 and r["slot"] == "pitch_rate"
    assert r["points"] == [_name(0.3), _name(0.35), _name(0.4)] and r["reasons"] == ["d"] and r["why"] is None
    assert r["verdicts"] == {"a": "ok", "mid": "ok", "b": "ok"} and r["verdict_change"] is False
    s_ = by[(0.1, 0.2)]
    assert s_["exceeds"] and s_["depth"] == 0
    u = by[(0.4, 0.5)]
    assert u["d"] is None and u["slot"] is None and u["verdicts"] is None and "미계산" in u["why"] and not u["exceeds"]
    k = by[(0.1, 0.15)]
    assert k["depth"] == 1 and not k["exceeds"] and k["reasons"] == []
    # 허용치를 끄면 사유가 없다 — 사실(d·판정 다름)은 그대로 적는다
    off = {tuple(i["interval"]): i for i in reinforce_intervals(dres, plan, tol=None)}
    assert off[(0.3, 0.4)]["status"] == "ok" and off[(0.3, 0.4)]["tol"] is None and not off[(0.3, 0.4)]["exceeds"]
    assert off[(0.3, 0.4)]["d"] == pytest.approx(2.5)


# S1(쇼케이스 200 m·25 kg 한 줄) 실측 — 자리별 최대 d(2026-10-10 v1.81 S1 설계 경로 실행, 파일 쓰지 않음). 다섯 구간 · 판정 다름
# 0 · 잴 수 없는 구간 2(행 하한 M0.10375가 첫 절점 안쪽 · M0.23 전 스로틀 위)
S1_MAX_D = {"pitch_rate": 0.0082, "yaw_rate": 0.0094, "roll_rate": 0.0372, "pitch_att": 0.0269, "roll_att": 0.0244}


def test_s1_like_fixture_triggers_nothing_at_005_010_020():
    """S1 꼴(최대 d 0.037)에서는 허용치 0.05·0.10·0.20 어느 것도 구간을 쪼개지 않는다 — 추가점 0, 상태는 잴 수 없는 구간
    둘 때문에 unmeasured(쇼케이스의 tol_unset → unmeasured가 이것이다)."""
    ivs = [(0.12, 0.14), (0.14, 0.16), (0.16, 0.18), (0.18, 0.20), (0.20, 0.22)]
    dres = {"d": [_rec(a, b, (a + b) / 2, slot, d * (0.5 + 0.1 * i)) for i, (a, b) in enumerate(ivs)
                  for slot, d in S1_MAX_D.items()],
            "unmeasured": [{"row": [200.0, 25.0], "interval": [0.1, 0.12], "point": None, "why": "계획에 없다"},
                           {"row": [200.0, 25.0], "interval": [0.22, 0.24], "point": None, "why": "트림 미수렴"}],
            "verdict_change": 0, "verdict_change_intervals": [], "intervals": []}
    assert max(r["d"] for r in dres["d"]) == pytest.approx(0.0372 * 0.9)
    counts = []
    for tol in (0.05, 0.10, 0.20):
        got = reinforce_candidates(dres, tol=tol, max_points_left=24, max_depth=3, points=PointSet(),
                                   on_verdict_change=True)
        counts.append(len(got))
        st = reinforce_status(dres, [], tol=tol, on_verdict_change=True, max_depth=3)
        assert (st["status"], st["remaining"], st["unmeasured"]) == ("unmeasured", [], 2), tol
    assert counts == [0, 0, 0]
