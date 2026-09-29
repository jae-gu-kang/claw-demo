"""공통 운용공간 (05 §11) — 요구 운용영역 · 조건 상태 · 기본 모델 격자."""

import copy
import dataclasses

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.opspace import (
    CALC_FAILED, COMPUTABLE, CONSTRAINT_HIT, INFEASIBLE, MODEL_GAP, NOT_RUN, OUT_OF_REGION, UNDEFINED,
    ModelRange, Region, base_grid, model_range_of, pre_state, region_of, trim_assessment, trim_state,
)
from claw.opspace.states import _alpha_upper
from claw.profile import ProfileError, build_profile, validate_document
# 엔진 테스트의 load_example은 구 합성 기체(conftest)다 — 요구영역·트림 수치는 출하 예제(200 kg급)에서 쟀다
from claw.profile.document import load_shipped_example as load_example
from claw.trim import trim_level


def region(boundary=None, *, mach=(0.1, 0.3), alt=(0.0, 3000.0), fuel=(0.0, 50.0), grid=None):
    b = None if boundary is None else tuple((f, tuple(sorted(rows))) for f, rows in sorted(boundary.items()))
    return Region(mach=mach, alt=alt, fuel=fuel, boundary=b,
                  grid=grid or {"n_mach": 5, "alts": (0.0, 3000.0), "fuels": (25.0,)},
                  confirmed=True, source="profile")


WIDE_MODEL = ModelRange(mach=(0.0, 0.9), fuel=(0.0, 50.0))


@pytest.fixture(scope="module")
def example():
    return build_profile(load_example())


# ── 요구 운용영역 (05 §11.2) ─────────────────────────────────────────────────
def test_base_range_classifies_out_of_region():
    r = region()
    assert r.classify(0.2, 1000.0, 25.0) is None
    assert r.classify(0.35, 1000.0, 25.0) == OUT_OF_REGION
    assert r.classify(0.2, 4000.0, 25.0) == OUT_OF_REGION


def test_boundary_table_interpolates_and_leaves_gaps_undefined():
    r = region({10.0: [(0.0, 0.10, 0.30), (2000.0, 0.14, 0.26)],
                40.0: [(0.0, 0.12, 0.30), (2000.0, 0.16, 0.26)]})
    lo, hi = r.mach_bounds(1000.0, 25.0)  # 층 사이·행 사이 선형 보간
    assert lo == pytest.approx(0.13) and hi == pytest.approx(0.28)
    assert r.mach_bounds(2500.0, 25.0) is None  # 행이 안 덮는 고도 — 가까운 행으로 늘리지 않는다
    assert r.classify(0.2, 2500.0, 25.0) == UNDEFINED
    assert r.mach_bounds(1000.0, 45.0) is None  # 층 밖의 연료
    assert r.classify(0.11, 1000.0, 25.0) == OUT_OF_REGION  # 행 하한 아래


def test_fuel_exactly_on_a_layer_uses_that_layer_only():
    # 층 40은 1000 m까지만 — 층 10 값 그대로의 연료가 이웃 층을 요구하면 2000 m가 미정의로 둔갑한다
    r = region({10.0: [(0.0, 0.10, 0.30), (2000.0, 0.14, 0.26)], 40.0: [(0.0, 0.12, 0.30), (1000.0, 0.14, 0.28)]})
    assert r.mach_bounds(2000.0, 10.0) == pytest.approx((0.14, 0.26))
    assert r.mach_bounds(2000.0, 25.0) is None


def test_trim_grid_gives_an_unconfirmed_draft_and_the_section_wins():
    doc = validate_document(load_example())
    draft = region_of({**doc, "operating_region": None})
    assert draft.confirmed is False and draft.source == "draft:trim_grid"
    g = doc["mission_template"]["trim_grid"]
    assert draft.mach == (g["mach"]["from"], g["mach"]["to"])
    assert draft.grid["alts"] == tuple(g["alt"]) and draft.grid["n_mach"] == 5  # 0.14~0.22 / 0.02
    confirmed = region_of(doc)
    assert confirmed.confirmed is True and confirmed.source == "profile" and confirmed.boundary
    assert region_of({**doc, "operating_region": None, "mission_template": None}) is None


def test_model_range_is_separate_and_never_shrinks_the_region(example):
    m = model_range_of(example)
    assert m.mach == tuple(example.db_ranges()["mach"]) and m.fuel == (0.0, 50.0)
    r = region(mach=(0.1, 1.2))
    assert r.classify(1.1, 1000.0, 25.0) is None  # 요구영역 안
    assert pre_state(r, m, 1.1, 1000.0, 25.0) == MODEL_GAP  # 모델 밖 — 상태로 남는다
    assert pre_state(r, m, 0.2, 1000.0, 25.0) == NOT_RUN


# ── 스키마 (operating_region 절) ─────────────────────────────────────────────
def _with_region(**over):
    doc = load_example()
    r = copy.deepcopy(doc["operating_region"])
    r.update(over)
    return {**doc, "operating_region": r}


@pytest.mark.parametrize("over, path", [
    ({"mach": [0.3, 0.1]}, "/operating_region/mach/1"),
    ({"mach": [0.0, 0.3]}, "/operating_region/mach/0"),
    ({"boundary": [{"fuel": 10.0, "rows": [[100.0, 0.2, 0.15]]}]}, "/operating_region/boundary/0/rows/0/2"),
    ({"boundary": [{"fuel": 10.0, "rows": [[100.0, 0.05, 0.2]]}]}, "/operating_region/boundary/0/rows/0/1"),
    ({"boundary": [{"fuel": 99.0, "rows": [[100.0, 0.1, 0.2]]}]}, "/operating_region/boundary/0/fuel"),
    ({"boundary": []}, "/operating_region/boundary"),
    ({"base_grid": {"n_mach": 1, "alts": [100.0], "fuels": [25.0]}}, "/operating_region/base_grid/n_mach"),
    ({"base_grid": {"n_mach": 5, "alts": [9000.0], "fuels": [25.0]}}, "/operating_region/base_grid/alts/0"),
    ({"base_grid": {"n_mach": 5, "alts": [100.0, 100.0], "fuels": [25.0]}}, "/operating_region/base_grid/alts"),
    ({"base_grid": {"n_mach": 40, "alts": [100.0, 1000.0, 2000.0], "fuels": [10.0, 25.0]}},
     "/operating_region/base_grid"),  # (40 + 2) × 3 × 2 = 252 > 200
    ({"boundary": [{"fuel": 10.0, "rows": [[100.0, 0.1, 0.2]]}, {"fuel": 10.0, "rows": [[100.0, 0.1, 0.2]]}]},
     "/operating_region/boundary/1/fuel"),
    ({"boundary": [{"fuel": 10.0, "rows": [[100.0, 0.1, 0.2], [100.0, 0.1, 0.25]]}]},
     "/operating_region/boundary/0/rows/1/0"),
])
def test_schema_rejects_malformed_region_with_path(over, path):
    with pytest.raises(ProfileError) as e:
        validate_document(_with_region(**over))
    assert path in str(e.value)


def test_schema_accepts_region_beyond_model_range():
    # 요구가 모델(연료 만재 50 kg)보다 넓어도 거부하지 않는다 — 넘친 부분은 모델 부족 상태다
    doc = _with_region(fuel=[0.0, 80.0], base_grid={"n_mach": 5, "alts": [100.0], "fuels": [70.0]})
    assert validate_document(doc)["operating_region"]["fuel"] == [0.0, 80.0]


def test_variant_cannot_override_the_region():
    doc = load_example()
    doc = {**doc, "variants": [{"id": "v", "name": "v", "patch": {"/operating_region/mach": [0.1, 0.2]}}]}
    with pytest.raises(ProfileError) as e:
        validate_document(doc)
    assert "요구 운용영역" in str(e.value)


# ── 기본 모델 격자 (05 §11.11) ───────────────────────────────────────────────
def test_base_grid_uses_common_mach_axis_plus_row_endpoints():
    r = region({25.0: [(0.0, 0.13, 0.30), (3000.0, 0.17, 0.26)]},
               grid={"n_mach": 5, "alts": (0.0, 3000.0), "fuels": (25.0,)})
    out = base_grid(r, WIDE_MODEL)
    assert out["axis"] == [0.1, 0.15, 0.2, 0.25, 0.3]
    by_alt = {}
    for p in out["points"]:
        by_alt.setdefault(p["alt"], []).append(p["mach"])
    assert sorted(by_alt[0.0]) == [0.13, 0.15, 0.2, 0.25, 0.3]  # 공통 좌표 + 행 하한 끝점
    assert sorted(by_alt[3000.0]) == [0.17, 0.2, 0.25, 0.26]
    # 공통 좌표라 행이 달라도 같은 마하를 공유한다 — 절점·검증점이 재사용한다
    assert {0.2, 0.25} <= set(by_alt[0.0]) & set(by_alt[3000.0])


def test_base_grid_rows_are_serpentine_for_adjacent_trim_seeds():
    out = base_grid(region(grid={"n_mach": 3, "alts": (0.0, 1000.0, 2000.0), "fuels": (25.0,)}), WIDE_MODEL)
    rows = [[p["mach"] for p in out["points"] if p["alt"] == a] for a in (0.0, 1000.0, 2000.0)]
    assert rows[0] == sorted(rows[0]) and rows[1] == sorted(rows[1], reverse=True) and rows[2] == sorted(rows[2])


def test_base_grid_keeps_undefined_rows_and_model_gap_points():
    r = region({25.0: [(0.0, 0.1, 0.5), (1000.0, 0.1, 0.5)]}, mach=(0.1, 0.5),
               grid={"n_mach": 5, "alts": (0.0, 2000.0), "fuels": (25.0,)})
    out = base_grid(r, ModelRange(mach=(0.0, 0.4), fuel=(0.0, 50.0)))
    undefined = [row for row in out["rows"] if row["state"] == UNDEFINED]
    assert [(row["alt"], row["n"]) for row in undefined] == [(2000.0, 0)]  # 행은 사라지지 않는다
    assert {p["state"] for p in out["points"] if p["mach"] > 0.4} == {MODEL_GAP}  # 지우지 않고 상태로
    assert {p["state"] for p in out["points"] if p["mach"] <= 0.4} == {NOT_RUN}


def test_base_grid_names_are_exact_values():
    out = base_grid(region(mach=(0.1, 0.3), grid={"n_mach": 3, "alts": (1000.0,), "fuels": (25.0,)}), WIDE_MODEL)
    assert [p["name"] for p in out["points"]] == ["M0.1_h1000_f25", "M0.2_h1000_f25", "M0.3_h1000_f25"]


def test_example_region_is_not_rectangular(example):
    out = base_grid(region_of(example.doc), model_range_of(example))
    lows = {row["alt"]: row["bounds"][0] for row in out["rows"]}
    assert lows[100.0] < lows[3000.0]  # 경계표 — 고도가 오르면 요구 하한이 오른다


# ── 조건 상태 (05 §11.3) ─────────────────────────────────────────────────────
def _trim(built, mach, alt, fuel):
    return trim_level(built.aircraft(), TrimCase(name="t", mach=mach, alt=alt, fuel=fuel))


def test_converged_trim_with_margin_is_computable(example):
    assert trim_state(_trim(example, 0.18, 1000.0, 25.0), example, WIDE_MODEL) == (COMPUTABLE, [])


def test_unconverged_trim_pinned_at_throttle_limit_is_infeasible_only_with_evidence(example):
    # 스로틀 100 %에 붙은 미수렴 — 그것만으로가 아니라, 최대 추력에서 수직력·피치 모멘트 평형을 다시 풀어 찾은 해
    # 전부에서 비행경로 가속도가 허용치를 넘게 음수라는 근거로 불가다. 근거 수치가 결과에 실린다
    tr = _trim(example, 0.5, 100.0, 25.0)
    assert tr.converged is False
    a = trim_assessment(tr, example, WIDE_MODEL)
    assert a["state"] == INFEASIBLE and a["reasons"] == ["thrust_deficit", "throttle_high"]
    ev = a["evidence"]
    assert ev["channel"] == "throttle_high" and ev["fixed"] == {"throttle": 1.0} and ev["equation"] == "vdot"
    assert ev["solutions"] and all(s["below_stall"] and s["vdot"] < -ev["tol"] for s in ev["solutions"])
    assert all(abs(s["ndot"]) < ev["tol"] and abs(s["qdot"]) < ev["tol"] for s in ev["solutions"])
    assert a["margin"]["status"] == "unevaluated"


# ── 여유 판정은 상태와 따로 (05 §11.3) — 검토 회귀 3종 ──────────────────────────
@pytest.fixture(scope="module")
def eoir():
    return build_profile(load_example(), "eoir")


def test_converged_trim_past_the_throttle_line_is_computable_with_margin_short(eoir):
    # EO/IR형 M0.28 2000 m·25 kg — 수렴한 평형(스로틀 95.1 %)이다. 판정선 95 %를 넘었을 뿐 날 수 있는 조건이다
    tr = _trim(eoir, 0.28, 2000.0, 25.0)
    assert tr.converged and float(tr.control.throttle[0]) > 0.95
    a = trim_assessment(tr, eoir, WIDE_MODEL)
    assert a["state"] == COMPUTABLE and a["reasons"] == []
    assert a["margin"] == {"status": "short", "reasons": ["throttle_high"]}
    assert trim_state(tr, eoir, WIDE_MODEL) == (COMPUTABLE, [])


def test_marginal_thrust_deficit_is_confirmed_by_the_balance_check(eoir):
    # EO/IR형 M0.28 3000 m·37.5 kg — 스로틀 100 %·미수렴. 최대 추력 평형 해의 V̇가 −0.0066 m/s²로 작지만 허용치를 넘는다
    tr = _trim(eoir, 0.28, 3000.0, 37.5)
    assert not tr.converged
    a = trim_assessment(tr, eoir, WIDE_MODEL)
    assert a["state"] == INFEASIBLE and a["reasons"][0] == "thrust_deficit"
    assert all(s["vdot"] < -1e-3 for s in a["evidence"]["solutions"])


def test_limit_without_a_balance_is_constraint_hit_not_infeasible(example, monkeypatch):
    # 평형을 풀 받음각 범위에 해가 없다 — 한계에 붙었다는 사실만 남는다: 원인 미확인
    tr = _trim(example, 0.5, 100.0, 25.0)
    monkeypatch.setattr(example, "db_ranges", lambda: {"alpha": (0.30, 0.31)})
    a = trim_assessment(tr, example, WIDE_MODEL)
    assert a["state"] == CONSTRAINT_HIT
    assert a["reasons"] == ["throttle_high", "not_converged", "balance_not_found"]
    assert a["evidence"]["solutions"] == []


def test_limit_with_spare_thrust_at_full_throttle_is_a_solver_failure(example):
    # 추력이 남는 조건(M0.18)의 해를 스로틀 100 %·미수렴으로 꾸민다 — 한계 안쪽에 트림이 있으니 다시 풀 대상이다
    tr = _trim(example, 0.18, 1000.0, 25.0)
    pinned = dataclasses.replace(tr, converged=False,
                                 control=dataclasses.replace(tr.control, throttle=np.array([1.0, 1.0])))
    a = trim_assessment(pinned, example, WIDE_MODEL)
    assert a["state"] == CALC_FAILED and "trim_inside_limit" in a["reasons"]
    assert any(s["vdot"] > 0.0 for s in a["evidence"]["solutions"])


@pytest.mark.parametrize("bound", [0, 1])
def test_elevon_stop_with_a_trim_inside_the_travel_is_a_solver_failure(example, bound):
    # 수렴한 해(δe −0.048)를 엘레본 끝(±0.35)·미수렴으로 꾸민다 — q̇가 남아도 엘레본을 안쪽으로 되돌리면 상쇄되는 방향이다.
    # 부호를 안 보고 |q̇|만 보면 양 끝 모두 「피치 모멘트 부족」이 된다(리뷰가 잡은 결함)
    tr = _trim(example, 0.18, 1000.0, 25.0)
    lim = example.trim_bounds["de"][bound]
    pinned = dataclasses.replace(tr, converged=False, control=dataclasses.replace(tr.control, elevon=np.full(4, lim)))
    a = trim_assessment(pinned, example, WIDE_MODEL)
    assert a["state"] == CALC_FAILED and "trim_inside_limit" in a["reasons"], a["reasons"]
    assert a["evidence"]["equation"] == "qdot" and a["evidence"]["solutions"]


def test_elevon_too_short_to_trim_is_pitch_moment_short():
    # 엘레본 음의 한계를 −0.01로 좁힌 기체 — 트림에 필요한 δe(약 −0.048)가 한계 밖이라 엘레본 하한에 붙는다.
    # 한계 고정 평형에서 q̇를 없애려면 더 음으로 가야 한다 — 불가 방향이므로 물리적 불가다
    doc = load_example()
    doc["surfaces"]["elevon"] = [-0.01, 0.35]
    doc["law"]["alloc"] = None  # 좁힌 한계로는 도출 표가 낡는다 — 이 시험은 트림만 본다
    built = build_profile(doc)
    tr = _trim(built, 0.18, 1000.0, 25.0)
    assert not tr.converged and float(tr.control.elevon[0]) == pytest.approx(-0.01)
    a = trim_assessment(tr, built, WIDE_MODEL)
    assert a["state"] == INFEASIBLE and a["reasons"] == ["pitch_moment_short", "de_low"], a["reasons"]


def test_throttle_evidence_balances_the_path_normal_axis(example):
    # 추력 부족 해는 V̇ ≠ 0이다 — 기체축 ẇ = 0으로 풀면 경로 수직 가속도가 −tanα·V̇로 남는다. 경로축 짝(V̇ · 경로 수직)으로 푼다
    a = trim_assessment(_trim(example, 0.5, 100.0, 25.0), example, WIDE_MODEL)
    assert all(abs(s["ndot"]) < a["evidence"]["tol"] for s in a["evidence"]["solutions"])


def test_limit_evidence_outside_the_stall_axis_does_not_claim_infeasible(example, monkeypatch):
    # 실속표 축 밖의 마하 — 찾은 평형이 실속 아래인지 근거가 없다: 불가를 주장하지 않는다
    from claw.tables import Table

    monkeypatch.setattr(example, "stall_table", lambda: Table({"mach": (0.6, 0.9)}, (0.30, 0.27), name="alpha_stall",
                                                               extrapolate="clip"))
    a = trim_assessment(_trim(example, 0.5, 100.0, 25.0), example, WIDE_MODEL)
    assert a["state"] == CONSTRAINT_HIT and "stall_basis_missing" in a["reasons"]
    assert all(s["below_stall"] is None for s in a["evidence"]["solutions"])


def test_limit_evidence_solver_error_degrades_to_a_reason(example, monkeypatch):
    import scipy.optimize

    def boom(*a, **k):
        raise ValueError("수치 실패")

    monkeypatch.setattr(scipy.optimize, "least_squares", boom)
    a = trim_assessment(_trim(example, 0.5, 100.0, 25.0), example, WIDE_MODEL)
    assert a["state"] == CONSTRAINT_HIT and a["reasons"][-1] == "balance_error"


def test_two_limits_at_once_do_not_claim_a_cause(example):
    tr = _trim(example, 0.18, 1000.0, 25.0)
    hi = example.trim_bounds["de"][1]
    pinned = dataclasses.replace(tr, converged=False, control=dataclasses.replace(
        tr.control, throttle=np.array([1.0, 1.0]), elevon=np.full(4, hi)))
    a = trim_assessment(pinned, example, WIDE_MODEL)
    assert a["state"] == CONSTRAINT_HIT and a["reasons"] == ["throttle_high", "de_high", "not_converged",
                                                             "balance_not_found"]


def test_converged_trim_past_stall_stays_computable(example):
    # 수치 평형이 있다는 사실과 운용 제한 위반은 따로다 — 실속 경계 위반은 조건 판정의 제한 항목이 말한다
    # (test_opspace_verdict.py)
    tr = _trim(example, 0.18, 1000.0, 25.0)
    reserve = copy.deepcopy(tr.reserve)
    reserve["alpha"]["stall_reserve"] = -0.01
    a = trim_assessment(dataclasses.replace(tr, reserve=reserve), example, WIDE_MODEL)
    assert a["state"] == COMPUTABLE and a["reasons"] == []


def test_margin_is_met_for_a_comfortable_trim(example):
    a = trim_assessment(_trim(example, 0.18, 1000.0, 25.0), example, WIDE_MODEL)
    assert a["margin"] == {"status": "met", "reasons": []} and a["evidence"] is None


def test_alpha_search_bound_without_stall_basis_is_constraint_hit(example):
    tr = _trim(example, 0.0612, 100.0, 10.0)
    assert tr.converged is False
    st, why = trim_state(tr, example, WIDE_MODEL)
    assert st == CONSTRAINT_HIT and "alpha_search_bound" in why and "stall_basis_missing" in why


def test_alpha_upper_uses_known_stall_speed_and_n_reach(example):
    case = TrimCase(name="t", mach=0.05, alt=100.0, fuel=25.0)
    key = (100.0, 25.0, 0.9)
    assert _alpha_upper(case, example, WIDE_MODEL, {key: (0.12, "stall")})[0] == INFEASIBLE
    st, why = _alpha_upper(case, example, WIDE_MODEL, {key: (0.9, "n_reach")})
    assert st == INFEASIBLE and "1g_unreachable" in why
    st, why = _alpha_upper(TrimCase(name="t", mach=0.2, alt=100.0, fuel=25.0), example, WIDE_MODEL,
                           {key: (0.12, "stall")})
    assert st == CONSTRAINT_HIT and "above_V_S" in why


def test_calc_failed_is_the_residual_state_for_unpinned_failure(example):
    # 수렴 해를 미수렴으로 표시한 것 — 포화도 받음각 탐색 한계도 아닌 자리에서 멈춘 해
    tr_failed = dataclasses.replace(_trim(example, 0.18, 1000.0, 25.0), converged=False)
    assert trim_state(tr_failed, example, WIDE_MODEL) == (CALC_FAILED, ["not_converged"])


def test_base_grid_sorts_and_dedupes_rows_so_names_stay_unique():
    out = base_grid(region(grid={"n_mach": 3, "alts": (1000.0, 0.0, 1000.0), "fuels": (25.0,)}), WIDE_MODEL)
    names = [p["name"] for p in out["points"]]
    assert len(names) == len(set(names))
    assert [row["alt"] for row in out["rows"]] == [0.0, 1000.0]


def test_serpentine_continues_across_fuel_layers():
    out = base_grid(region(grid={"n_mach": 3, "alts": (0.0, 1000.0), "fuels": (10.0, 25.0)}), WIDE_MODEL)
    rows = [[p["mach"] for p in out["points"] if (p["fuel"], p["alt"]) == k]
            for k in ((10.0, 0.0), (10.0, 1000.0), (25.0, 0.0), (25.0, 1000.0))]
    # 층이 바뀌어도 방향은 번갈아 — 층 경계에서 끝 점끼리 이어진다
    assert [r == sorted(r) for r in rows] == [True, False, True, False]


def test_out_of_region_row_carries_no_requirement_band():
    out = base_grid(region(grid={"n_mach": 3, "alts": (0.0, 5000.0), "fuels": (25.0,)}), WIDE_MODEL)
    row = next(r for r in out["rows"] if r["alt"] == 5000.0)
    assert row == {"alt": 5000.0, "fuel": 25.0, "bounds": None, "n": 0, "state": OUT_OF_REGION}


def test_alpha_lower_bound_is_constraint_hit_without_stall_reasoning(example):
    # 받음각 탐색 하한에 붙은 해 — 양력이 남는 쪽이라 실속 논리를 쓰지 않는다
    tr = _trim(example, 0.18, 1000.0, 25.0)
    a_lo = example.trim_bounds["alpha"][0]
    import math
    v = float(tr.state.vel_b[0])
    import numpy as np
    state = dataclasses.replace(tr.state, vel_b=np.array([v, 0.0, v * math.tan(a_lo)]))
    st, why = trim_state(dataclasses.replace(tr, converged=False, state=state), example, WIDE_MODEL)
    assert st == CONSTRAINT_HIT and why == ["alpha_search_lower", "not_converged"]


def test_alpha_upper_without_scan_basis_never_claims_infeasible(example):
    # 모델 마하 상한 위의 케이스(손으로 더함) — 스캔이 그 마하를 보지 않았다: 1g 도달 불가로 둔갑하지 않는다
    case = TrimCase(name="t", mach=0.95, alt=100.0, fuel=25.0)
    st, why = _alpha_upper(case, example, ModelRange(mach=(0.0, 0.9), fuel=(0.0, 50.0)), {})
    assert st == CONSTRAINT_HIT and "stall_basis_missing" in why
    st, why = _alpha_upper(TrimCase(name="t", mach=0.03, alt=100.0, fuel=25.0), example,
                           ModelRange(mach=(0.0, 0.01), fuel=(0.0, 50.0)), {})
    assert st == CONSTRAINT_HIT and "stall_basis_missing" in why


def test_stall_computation_error_keeps_the_trim_instead_of_failing(example, monkeypatch):
    import claw.analysis.envelope as envelope

    def boom(*a, **k):
        raise ValueError("수치 실패")

    monkeypatch.setattr(envelope, "stall_mach_lo", boom)
    st, why = _alpha_upper(TrimCase(name="t", mach=0.2, alt=100.0, fuel=25.0), example, WIDE_MODEL, {})
    assert st == CONSTRAINT_HIT and "stall_basis_error" in why
