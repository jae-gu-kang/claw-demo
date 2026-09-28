"""실험 실행기의 조건 구성 — 값이 기체 문서에서 오고, 확인 항목이 겨냥하는 상태가 실제로 생기는가."""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "experiments" / "grid_system")]

import gridsys as g  # noqa: E402
import run_experiment as rx  # noqa: E402


@pytest.fixture(scope="module", params=["example", "showcase"])
def built(request):
    from claw.profile.build import build_profile
    from claw.profile.document import load_example, load_showcase

    return build_profile({"example": load_example, "showcase": load_showcase}[request.param]())


def test_setup_spreads_breakpoints_over_the_schedule_range(built):
    draft, region, model, bps, alts, fuels = rx.setup(built)
    tg = built.doc["mission_template"]["trim_grid"]
    mg = built.doc["law"]["schedule"]["mach_grid"]
    assert draft.confirmed is False and draft.mach == (tg["mach"]["from"], tg["mach"]["to"])
    # 요구영역 마하 = 기체 스케줄이 덮는 범위, 절점 5개가 그 범위 양끝까지 고르게 — 좁은 띠에 몰리지 않는다
    assert region.mach == (mg[0], mg[-1])
    assert len(bps) == 5 and bps[0] == pytest.approx(mg[0]) and bps[-1] == pytest.approx(mg[-1])
    gaps = [b - a for a, b in zip(bps, bps[1:])]
    assert max(gaps) == pytest.approx(min(gaps), rel=1e-4)
    # 경계표는 가운데 고도까지만 — 가장 높은 검증 고도는 요구 미정의
    assert region.classify(g.Condition(bps[2], alts[-1], fuels[0])) == g.UNDEFINED
    assert region.classify(g.Condition(bps[2], alts[0], fuels[0])) is None


def test_design_rows_differ_from_validation_rows(built):
    _, region, _, _, alts, fuels = rx.setup(built)
    d_alts, d_fuels = rx.design_rows(alts, fuels)
    assert set(d_alts) < set(alts) and set(d_fuels) < set(fuels)  # 설계점과 검증 조합은 독립


def test_trim_points_are_union_of_design_and_validation_and_shared_once(built):
    _, region, model, bps, alts, fuels = rx.setup(built)
    ev = g.Evaluator(built, g.TrimStore())
    c1, c2 = g.Condition(bps[2], alts[0], fuels[0]), g.Condition(bps[1], alts[0], fuels[0])
    dps = [g.DesignPoint(c1, "user")]
    recs = [{"cond": c1, "name": c1.name, "state": g.COMPUTABLE, "reasons": []},
            {"cond": c2, "name": c2.name, "state": g.COMPUTABLE, "reasons": []}]
    tps = rx.trim_points(ev, region, model, dps, recs)
    by = {t["name"]: t for t in tps}
    assert set(by) == {c1.name, c2.name}
    assert by[c1.name]["used_by"] == ["design", "validation"] and by[c2.name]["used_by"] == ["validation"]
    assert ev.store.computed == 1  # 설계점 트림 한 번 — 검증점 레코드는 새로 트림하지 않는다
    # 트림을 돌리지 않은 조건(요구영역 밖·요구 미정의·모델 부족)은 트림점이 아니다
    c3 = g.Condition(bps[2], alts[-1], fuels[0])  # 요구 미정의
    tps = rx.trim_points(ev, region, model, dps, recs + [{"cond": c3, "name": c3.name, "state": g.UNDEFINED,
                                                          "reasons": []}])
    assert c3.name not in {t["name"] for t in tps}


def test_jsonable_flattens_conditions():
    r = {"name": "n", "cond": g.Condition(0.2, 100.0, 10.0), "row": (100.0, 10.0), "state": g.NOT_RUN}
    (x,) = rx.jsonable([r])
    assert x["cond"] == {"mach": 0.2, "alt": 100.0, "fuel": 10.0} and x["row"] == [100.0, 10.0]


def test_dump_writes_non_finite_as_null_so_browsers_can_parse():
    import json
    import math

    text = rx.dump({"a": math.inf, "b": [math.nan, 1.0], "c": {"d": -math.inf}})
    assert json.loads(text) == {"a": None, "b": [None, 1.0], "c": {"d": None}}
    assert "Infinity" not in text and "NaN" not in text


def test_legacy_scales_follow_targets_and_differ_from_rule(built):
    # 이전 규칙(비교 전용)은 튜닝 목표에 매인다 — 새 규칙과 ζ 자리에서 갈린다
    crit = built.eval_criteria
    old, new = rx.d_scales_legacy_target_based(crit), g.d_scales(crit)
    assert old["pitch_rate"] == pytest.approx(crit.targets.zeta_sp - crit.margin.zeta_min)
    assert old["pitch_rate"] != new["pitch_rate"]


def test_compare_reinforce_reports_points_order_and_status():
    c = lambda m: g.Condition(m, 0.0, 10.0)  # noqa: E731
    old = {"status": g.REINFORCE_DONE, "added": [{"cond": c(0.1), "row": (0.0, 10.0), "interval": (0.0, 0.2)},
                                                  {"cond": c(0.3), "row": (0.0, 10.0), "interval": (0.2, 0.4)}],
           "remaining": []}
    new = {"status": g.REINFORCE_BUDGET, "added": [{"cond": c(0.3), "row": (0.0, 10.0), "interval": (0.2, 0.4)},
                                                    {"cond": c(0.5), "row": (0.0, 10.0), "interval": (0.4, 0.6)}],
           "remaining": [{"row": (0.0, 10.0), "interval": (0.0, 0.2), "d": 0.4}]}
    cmp = rx.compare_reinforce(old, new)
    assert cmp["added"] == {"before": 2, "after": 2, "only_before": [c(0.1).name], "only_after": [c(0.5).name]}
    assert cmp["first_order_difference"] == 0
    assert cmp["status"] == {"before": g.REINFORCE_DONE, "after": g.REINFORCE_BUDGET}


def test_synthetic_model_limit_keeps_region_and_is_labelled(built):
    _, region, model, *_ = rx.setup(built)
    syn = rx.synthetic_limited_model(region, model)
    assert syn.source.startswith("synthetic:")  # 실제 기체 데이터와 구분
    assert syn.mach[1] < region.mach[1]  # 요구영역은 그대로, 모델 범위만 줄인다
    assert not syn.covers(g.Condition(region.mach[1], region.alt[0], region.fuel[0]))


def test_trim_attempt_points_include_constraint_hits(built):
    _, region, model, bps, alts, fuels = rx.setup(built)
    ev = g.Evaluator(built, g.TrimStore())
    c = g.Condition(bps[1], alts[0], fuels[0])
    recs = [{"cond": c, "name": c.name, "state": g.CONSTRAINT_HIT, "reasons": ["alpha_search_bound"]}]
    assert [t["name"] for t in rx.trim_points(ev, region, model, [], recs)] == [c.name]


def test_base_refine_metrics_are_consistent(built):
    out = rx.base_refine(built, n_mach=5, budget=4)
    m = out["metrics"]
    assert m["base_trims"] > 0 and 0.0 <= m["base_reuse_ratio"] <= 1.0
    # 추가 트림 = 역할 요청으로 새로 푼 점 + 보강으로 새로 푼 점, 그중 실패 수는 그 이하
    assert m["additional_trims"] == m["role_new_trims"] + m["refine_new_trims"]
    assert 0 <= m["additional_trim_failures"] <= m["additional_trims"]
    # 보강 사유 합 = 추가점 수, 사유 코드는 정의된 것만
    assert sum(m["refinement_reasons"].values()) == len(out["added"])
    assert set(m["refinement_reasons"]) <= {g.R_NONLINEAR_METRIC, g.R_VERDICT_CHANGE, g.R_TRIM_FAILURE_BOUNDARY}
    assert set(m["interpolation"]) == {"breakpoint", "interpolated", "clip"}
    assert m["design_points"] <= m["base_points"]  # 설계점은 기본 격자에서 고른다
    # 검증점마다 트림 출처 — 기본 격자 재사용 / 새 트림 / 트림 없음. 개수가 지표와 맞는다
    v = out["validation"]
    assert len(v) == m["validation_points"]
    assert {x["trim_origin"] for x in v} <= {"base", "new", "none"}
    assert sum(x["trim_origin"] == "base" for x in v) == m["role_reused"]
    assert sum(x["trim_origin"] == "new" for x in v) == m["role_new_trims"]


def test_common_axis_base_grid_is_reused_more_than_per_row(built):
    own = rx.base_refine(built, n_mach=7, budget=4)["metrics"]
    com = rx.base_refine(built, n_mach=7, budget=4, common_axis=True)["metrics"]
    assert com["base_reuse_ratio"] > own["base_reuse_ratio"]
    assert com["role_reused"] / (com["role_reused"] + com["role_new_trims"]) == pytest.approx(com["base_reuse_ratio"])


def test_base_refine_budget_reaches_reinforce(built):
    m = rx.base_refine(built, n_mach=5, budget=4)["metrics"]
    assert m["refinement_reasons"].get(g.R_NONLINEAR_METRIC, 0) <= 4
