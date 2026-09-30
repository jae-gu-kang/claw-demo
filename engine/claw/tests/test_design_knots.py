"""표별 절점 집합(design/knots.py) — 초기 규칙, 공유·분리, 단조 성장·상한, 기록 왕복 (05 §11.5 · 이관 3단계)."""

import json

import pytest

from claw.common.contracts import TrimCase
from claw.design import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, PointSet, case_name
from claw.design.knots import (
    DEFAULT_KNOTS,
    KnotSet,
    add_knot,
    check_knots_config,
    initial_knot_sets,
    knot_record,
    union_knots,
)

SLOTS = ["pitch.kp", "pitch.ki", "roll.kp"]


def _points(machs, alt=200.0, fuel=25.0, role=ROLE_DESIGN, trimmable=True):
    ps = PointSet()
    for m in machs:
        pt = OperatingPoint(case=TrimCase(name=case_name(m, alt, fuel), mach=m, alt=alt, fuel=fuel), role=role)
        pt.trimmable = trimmable
        ps.add(pt)
    return ps


def test_base_axis_rule_takes_the_region_common_mach_axis_and_all_tables_share_it():
    """기본 규칙 base_axis — 요구영역 기본 격자의 공통 마하 좌표(n_mach)가 절점이고, 표는 전부 한 집합을 참조한다.

    설계점 수와 무관하다: 설계점이 36개여도 절점은 공통 좌표 그대로다(REFINE이 넣은 점은 표본이지 절점이 아니다)."""
    rg = {"axis": [0.10, 0.12, 0.14, 0.16]}
    pts = _points([0.10375 + 0.002 * i for i in range(30)])
    sets, tables = initial_knot_sets(dict(DEFAULT_KNOTS), region_grid=rg, points=pts, slots=SLOTS)
    assert list(sets) == ["common"]
    ks = sets["common"]
    assert (ks.axis, ks.coords, ks.source) == ("mach", [0.10, 0.12, 0.14, 0.16], "base_axis")
    assert tables == {s: "common" for s in SLOTS}
    assert union_knots(sets, tables) == [0.10, 0.12, 0.14, 0.16]


def test_initial_rules_without_region_and_user_and_samples():
    """요구영역이 없으면 설계 마하 범위의 균등 절점(LEGACY_N_MACH개). uniform·user·samples는 그 규칙대로."""
    from claw.design.orchestrator import LEGACY_N_MACH

    pts = _points([0.2, 0.25, 0.3, 0.45, 0.6])
    # 검증점·채택 안 한 설계점은 범위에 들지 않는다 — 튜닝 표본이 나오는 점만 본다
    pts.add(OperatingPoint(case=TrimCase(name=case_name(0.9, 200.0, 25.0), mach=0.9, alt=200.0, fuel=25.0),
                           role=ROLE_VALIDATION))
    bad = OperatingPoint(case=TrimCase(name=case_name(0.1, 200.0, 25.0), mach=0.1, alt=200.0, fuel=25.0),
                         role=ROLE_DESIGN)
    bad.trimmable = False
    pts.add(bad)
    sets, _ = initial_knot_sets(dict(DEFAULT_KNOTS), region_grid=None, points=pts, slots=SLOTS)
    ks = sets["common"]
    assert ks.source == f"uniform:{LEGACY_N_MACH}" and len(ks.coords) == LEGACY_N_MACH
    assert ks.coords[0] == pytest.approx(0.2) and ks.coords[-1] == pytest.approx(0.6)

    sets, _ = initial_knot_sets({**DEFAULT_KNOTS, "rule": "uniform", "n": 3}, region_grid={"axis": [0.0, 1.0]},
                                points=pts, slots=SLOTS)
    assert sets["common"].coords == pytest.approx([0.2, 0.4, 0.6]) and sets["common"].source == "uniform:3"

    sets, _ = initial_knot_sets({**DEFAULT_KNOTS, "rule": "user", "coords": [0.15, 0.3, 0.5]}, region_grid=None,
                                points=pts, slots=SLOTS)
    assert (sets["common"].coords, sets["common"].source) == ([0.15, 0.3, 0.5], "user")

    # samples = 옛 규칙(튜닝한 마하마다 절점) — 옛 세션 재개가 이 규칙으로 같은 표를 낸다
    sets, _ = initial_knot_sets({**DEFAULT_KNOTS, "rule": "samples"}, region_grid=None, points=pts, slots=SLOTS)
    assert (sets["common"].coords, sets["common"].source) == ([0.2, 0.25, 0.3, 0.45, 0.6], "samples")


def test_knots_config_is_validated():
    check_knots_config(dict(DEFAULT_KNOTS))
    for bad, match in (({"rule": "grid"}, "rule"),
                       ({"rule": "user", "coords": [0.3, 0.2]}, "증가"),
                       ({"rule": "user", "coords": None}, "coords"),
                       ({"rule": "uniform", "n": 1}, "n"),
                       ({"max_per_table": 1}, "max_per_table"),
                       ({"extra": 1}, "미정의")):
        with pytest.raises(ValueError, match=match):
            check_knots_config({**DEFAULT_KNOTS, **bad})


def test_add_knot_splits_only_the_named_tables_and_grows_monotonically():
    """절점 추가는 이름 댄 표만 분리해 자기 집합을 갖게 한다(독립 — 05 §11.5). 이름 안 댄 표는 공유 집합 그대로다."""
    sets = {"common": KnotSet(name="common", axis="mach", coords=[0.1, 0.2, 0.3], source="base_axis")}
    tables = {s: "common" for s in SLOTS}
    out = add_knot(sets, tables, ["pitch.kp", "pitch.ki"], 0.15, reason="gain_interp_valley",
                   point="M0.15_h200_f25", iter_n=1, max_per_table=16)
    assert out == {"added": True, "split": ["pitch.ki", "pitch.kp"], "skipped": None}
    assert tables["roll.kp"] == "common" and sets["common"].coords == [0.1, 0.2, 0.3]
    new = tables["pitch.kp"]
    assert tables["pitch.ki"] == new and new != "common"
    assert sets[new].coords == [0.1, 0.15, 0.2, 0.3] and sets[new].source == "split:common"
    assert sets[new].history[-1] == {"op": "add", "mach": 0.15, "reason": "gain_interp_valley",
                                     "point": "M0.15_h200_f25", "iter": 1}
    # 같은 두 표에 다시 넣으면 이제 그 둘만 쓰는 집합이라 제자리에 더한다(더 쪼개지 않는다)
    out = add_knot(sets, tables, ["pitch.kp", "pitch.ki"], 0.25, reason="r", point="p", iter_n=2, max_per_table=16)
    assert out["split"] == [] and sets[new].coords == [0.1, 0.15, 0.2, 0.25, 0.3]
    # 이미 있는 좌표 — 아무것도 안 바뀐다(skipped 사유)
    out = add_knot(sets, tables, ["roll.kp"], 0.2, reason="r", point="p", iter_n=2, max_per_table=16)
    assert out["added"] is False and "이미" in out["skipped"]
    assert tables["roll.kp"] == "common"


def test_add_knot_respects_the_cap():
    sets = {"common": KnotSet(name="common", axis="mach", coords=[0.1, 0.2, 0.3], source="user")}
    tables = {"pitch.kp": "common"}
    out = add_knot(sets, tables, ["pitch.kp"], 0.25, reason="r", point="p", iter_n=0, max_per_table=3)
    assert out["added"] is False and "상한" in out["skipped"]
    assert sets["common"].coords == [0.1, 0.2, 0.3]


def test_knot_record_round_trips_and_says_shared_or_independent():
    sets = {"common": KnotSet(name="common", axis="mach", coords=[0.1, 0.2, 0.3], source="base_axis")}
    tables = {s: "common" for s in SLOTS}
    add_knot(sets, tables, ["roll.kp"], 0.25, reason="r", point="p", iter_n=1, max_per_table=16)
    fits = {"pitch.kp": {"kind": "table", "n_breakpoints": 3, "unsupported_knots": []},
            "pitch.ki": {"kind": "table", "n_breakpoints": 2, "unsupported_knots": [0.3], "breakpoints": [0.1, 0.2],
                         "unsupported_detail": [{"knot": 0.3, "reason": "none"}]},
            "roll.kp": {"kind": "table", "n_breakpoints": 3, "unsupported_knots": [0.2], "breakpoints": [0.1, 0.25, 0.3],
                        "unsupported_detail": [{"knot": 0.2, "reason": "far"}]}}
    rec = knot_record(sets, tables, fits)
    json.dumps(rec)  # 저장·반출(provenance.knots)되는 모양이다
    assert rec["tables"]["pitch.kp"] == {"set": "common", "shared": True, "unsupported": [],
                                         "unsupported_detail": [], "n": 3}
    assert rec["tables"]["pitch.ki"]["unsupported"] == [0.3]
    # 끝 바깥(범위 밖 — clip)과 안쪽에서 뺀 절점(이웃 직선으로 메움)을 가른다
    assert rec["tables"]["pitch.ki"]["unsupported_detail"] == [{"knot": 0.3, "reason": "none", "edge": True}]
    assert rec["tables"]["roll.kp"]["unsupported_detail"] == [{"knot": 0.2, "reason": "far", "edge": False}]
    assert rec["tables"]["roll.kp"]["shared"] is False
    assert rec["sets"]["common"]["coords"] == [0.1, 0.2, 0.3]
    # 왕복 — 기록의 집합에서 같은 집합이 다시 선다
    back = {n: KnotSet.from_dict({"name": n, **d}) for n, d in rec["sets"].items()}
    assert {n: k.to_dict() for n, k in back.items()} == {n: k.to_dict() for n, k in sets.items()}
    assert union_knots(sets, tables) == [0.1, 0.2, 0.25, 0.3]
    assert union_knots(sets, tables, ["pitch.kp"]) == [0.1, 0.2, 0.3]
