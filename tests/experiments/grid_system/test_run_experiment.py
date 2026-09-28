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
