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


def test_setup_derives_from_document_and_targets_each_state(built):
    draft, region, model, bps, alts, fuels = rx.setup(built)
    tg = built.doc["mission_template"]["trim_grid"]
    assert draft.confirmed is False and draft.mach == (tg["mach"]["from"], tg["mach"]["to"])
    # 절점 4개는 초안 마하 범위 안, 설계점과 무관
    assert len(bps) == 4 and draft.mach[0] <= bps[0] < bps[-1] <= draft.mach[1] + 1e-9
    # 요구영역 상한이 DB 밖까지 — 모델 부족이 생길 자리가 있다
    assert region.mach[1] > model.mach[1]
    assert not model.covers(g.Condition(region.mach[1], alts[0], fuels[0]))
    # 경계표는 가운데 고도까지만 — 가장 높은 검증 고도는 요구 미정의
    assert region.classify(g.Condition(bps[1], alts[-1], fuels[0])) == g.UNDEFINED
    assert region.classify(g.Condition(bps[1], alts[0], fuels[0])) is None


def test_jsonable_flattens_conditions():
    r = {"name": "n", "cond": g.Condition(0.2, 100.0, 10.0), "row": (100.0, 10.0), "state": g.NOT_RUN}
    (x,) = rx.jsonable([r])
    assert x["cond"] == {"mach": 0.2, "alt": 100.0, "fuel": 10.0} and x["row"] == [100.0, 10.0]
