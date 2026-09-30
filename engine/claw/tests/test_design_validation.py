"""검증점 생성(05 §11.6)과 결과 요약 격자(05 §11.8) — 이관 4단계.

합성 요구영역은 쇼케이스 기체(S1)의 모양이다: 마하 0.10~0.24 · 고도 200~3000 m · 연료 10~50 kg, 경계표 두 층(연료 10 kg: 200 m
M0.10~0.24 · 3000 m M0.11~0.24 / 50 kg: 200 m M0.11~0.24 · 3000 m M0.12~0.24), 절점 = 공통 마하 좌표 0.10~0.24(0.02 간격).
설계 줄은 200 m · 25 kg — 그 행의 요구 마하는 연료 층 사이 보간이라 M0.10375부터다.
"""

import pytest

from claw.common.contracts import TrimCase
from claw.design.points import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, PointSet, case_name
from claw.design.validation import (
    DEFAULT_VALIDATION,
    EXTRA_ROW,
    HEADLINE_TEXT,
    check_validation_config,
    column_of,
    row_key,
    summary_columns,
    summary_grid,
    validation_conditions,
    validation_plan,
)
from claw.opspace.region import ModelRange, Region

KNOTS = [0.1, 0.12, 0.14, 0.16, 0.18, 0.2, 0.22, 0.24]
ROW = (200.0, 25.0)


def _region(**over):
    kw = dict(mach=(0.1, 0.24), alt=(200.0, 3000.0), fuel=(10.0, 50.0),
              boundary=((10.0, ((200.0, 0.1, 0.24), (3000.0, 0.11, 0.24))),
                        (50.0, ((200.0, 0.11, 0.24), (3000.0, 0.12, 0.24)))),
              grid={"n_mach": 8, "alts": (200.0, 3000.0), "fuels": (10.0, 50.0)}, confirmed=True, source="profile")
    kw.update(over)
    return Region(**kw)


MODEL = ModelRange(mach=(0.05, 0.3), fuel=(0.0, 60.0))


def _pt(mach, alt=ROW[0], fuel=ROW[1], role=ROLE_DESIGN, trimmable=True, origin="coarse"):
    return OperatingPoint(case=TrimCase(name=case_name(mach, alt, fuel), mach=mach, alt=alt, fuel=fuel), role=role,
                          origin=origin, trimmable=trimmable)


def _s1_points():
    """설계 줄 — 행 하한 M0.10375 · 공통 좌표 0.12~0.24 · 세분화가 둔 절점 구간 중점 0.11·0.13(설계점)."""
    ms = [0.10375, 0.11, 0.12, 0.13, 0.14, 0.16, 0.18, 0.2, 0.22, 0.24]
    return PointSet(_pt(m, trimmable=(m != 0.24)) for m in ms)


# ── 설정 ──────────────────────────────────────────────────────────────────────────────


def test_config_defaults_and_normalisation():
    cfg = check_validation_config({})
    assert cfg == DEFAULT_VALIDATION and cfg["rule"] == "plan" and cfg["boundary"] is True
    got = check_validation_config({"conditions": [[3000, 50], [200, 25], [200, 25]],
                                   "extras": [{"mach": 0.15, "alt": 500, "fuel": 30, "source": " 영향성 탭 "}]})
    assert got["conditions"] == [[200.0, 25.0], [3000.0, 50.0]]  # 정렬·중복 제거
    assert got["extras"] == [{"mach": 0.15, "alt": 500.0, "fuel": 30.0, "source": "영향성 탭"}]


@pytest.mark.parametrize("bad, match", [
    ({"nope": 1}, "미정의 키"),
    ({"rule": "dense"}, "rule"),
    ({"mode": "some"}, "mode"),
    ({"boundary": 1}, "boundary"),
    ({"conditions": []}, "conditions"),
    ({"conditions": [[200.0]]}, "conditions"),
    ({"conditions": [[200.0, -1.0]]}, "연료"),
    ({"conditions": [[200.0, float("nan")]]}, "conditions"),
    ({"extras": [{"mach": 0.15, "alt": 0.0, "fuel": 1.0}]}, "네 칸"),
    ({"extras": [{"mach": 0.15, "alt": 0.0, "fuel": 1.0, "source": "  "}]}, "출처"),
    ({"extras": [{"mach": -0.1, "alt": 0.0, "fuel": 1.0, "source": "x"}]}, "마하"),
])
def test_config_rejects_bad_values(bad, match):
    with pytest.raises(ValueError, match=match):
        check_validation_config(bad)


# ── 검증조건 ──────────────────────────────────────────────────────────────────────────


def test_conditions_default_to_the_design_rows_and_user_rows_win():
    got = validation_conditions(DEFAULT_VALIDATION, design_rows=[(200.0, 25.0)])
    assert got == {"rows": [[200.0, 25.0]], "source": "design_rows", "mode": "full", "omitted": []}
    user = validation_conditions({**DEFAULT_VALIDATION, "conditions": [[1000, 20], [3000, 40]]},
                                 design_rows=[(200.0, 25.0)])
    assert user["rows"] == [[1000.0, 20.0], [3000.0, 40.0]] and user["source"] == "user"


def test_representative_keeps_ends_centre_and_prior_failures_and_lists_the_rest():
    """대표 조합 — 고도·연료 각각 {최소·중앙·최대} 곱 + 직전 검증의 실패 행. 생략한 행은 목록으로 남는다(05 §11.6)."""
    alts, fuels = [0.0, 1000.0, 2000.0, 3000.0, 4000.0], [10.0, 30.0, 50.0]
    rows = [[a, f] for a in alts for f in fuels]
    got = validation_conditions({**DEFAULT_VALIDATION, "conditions": rows, "mode": "representative"},
                                design_rows=(), prior_failure_rows=[(1000.0, 30.0)])
    kept = {tuple(r) for r in got["rows"]}
    assert kept == {(a, f) for a in (0.0, 2000.0, 4000.0) for f in fuels} | {(1000.0, 30.0)}
    assert len(got["omitted"]) == len(rows) - len(kept) and got["mode"] == "representative"
    assert not kept & {tuple(r) for r in got["omitted"]}


# ── 생성 절차 ─────────────────────────────────────────────────────────────────────────


def test_s1_plan_kinds_order_and_existing_points():
    """S1 모양: 내분점 7(구간마다 — 중점에 설계점이 있으면 ¼ 자리로), clip 없음(요구 끝 = 첫·끝 절점 밖이 아니다), 절점은
    설계점이 이미 있어 공짜, 경계점 = 행 끝 2(설계점) + 경계표 모서리 8(새 점). 순서가 곧 예산 순서다."""
    pts = _s1_points()
    plan = validation_plan(pts, KNOTS, _region(), MODEL, rows=[ROW])
    es = plan["entries"]
    kinds = [e["kind"] for e in es]
    # 1라운드 내분점 → (clip) → 절점 → 경계 — 종류가 섞이지 않고 그 순서로 온다
    order = ["midpoint", "knot", "boundary"]
    assert [k for i, k in enumerate(kinds) if i == 0 or kinds[i - 1] != k] == order
    mids = [e for e in es if e["kind"] == "midpoint"]
    # [0.10, 0.12] 중점 0.11은 설계점 → ¼ 0.105(행 하한 0.10375 안), [0.12,0.14] 중점 0.13 설계점 → 0.125, [0.22,0.24] → 0.23
    assert [e["mach"] for e in mids] == [0.105, 0.125, 0.15, 0.17, 0.19, 0.21, 0.23]
    assert plan["moved"] == 2 and plan["unplaceable"] == 0
    assert all(e["row"] == [200.0, 25.0] and not e["existing"] and e["pre_state"] == "not_run" for e in mids)
    assert mids[0]["origin"] == "midpoint:M0.1|M0.12"
    knots = [e for e in es if e["kind"] == "knot"]
    assert [e["mach"] for e in knots] == KNOTS[1:]  # 0.10은 행 하한 0.10375 밖
    assert all(e["existing"] for e in knots)
    bnd = [e for e in es if e["kind"] == "boundary"]
    assert all(e["row"] is None for e in bnd)
    row_ends = [e for e in bnd if e["origin"] == "boundary:row"]
    assert [(e["mach"], e["existing"]) for e in row_ends] == [(0.10375, True)]  # 상한 0.24는 절점 점으로 이미 계획됐다
    corners = {(e["alt"], e["fuel"], e["mach"]) for e in bnd if e["origin"] == "boundary:region"}
    assert corners == {(200.0, 10.0, 0.1), (200.0, 10.0, 0.24), (3000.0, 10.0, 0.11), (3000.0, 10.0, 0.24),
                       (200.0, 50.0, 0.11), (200.0, 50.0, 0.24), (3000.0, 50.0, 0.12), (3000.0, 50.0, 0.24)}
    assert len({e["name"] for e in es}) == len(es)  # 한 이름은 한 번만


def test_clip_points_cover_the_region_beyond_the_first_and_last_knot():
    """요구영역이 절점 밖으로 뻗으면 그 끝 구간(표가 끝값으로 버티는 자리)의 중점을 검증한다 — 05 §11.6 ③."""
    region = _region(boundary=None, mach=(0.08, 0.3))
    pts = PointSet(_pt(m) for m in (0.12, 0.2))
    plan = validation_plan(pts, [0.12, 0.2], region, MODEL, rows=[ROW], boundary=False)
    clip = [(e["mach"], e["origin"]) for e in plan["entries"] if e["kind"] == "clip"]
    assert clip == [(0.1, "clip:lo"), (0.25, "clip:hi")]
    kinds = [e["kind"] for e in plan["entries"]]
    assert kinds.index("clip") < kinds.index("knot")  # 예산 순서 — clip이 절점보다 먼저


def test_rows_outside_or_undefined_stay_in_the_plan_only():
    """요구영역 밖·요구 미정의·모델 부족은 계획에만 남는다 — 상태로 표시되고 점 집합에 넣을 대상이 아니다."""
    pts = _s1_points()
    extras = [{"mach": 0.2, "alt": 5000.0, "fuel": 25.0, "source": "user"},  # 고도 범위 밖
              {"mach": 0.2, "alt": 1000.0, "fuel": 30.0, "source": "user"}]  # 요구 안(보간)
    plan = validation_plan(pts, KNOTS, _region(), ModelRange(mach=(0.05, 0.3), fuel=(0.0, 20.0)),
                           rows=[ROW, (1000.0, 60.0)], extras=extras)
    by = {(e["alt"], e["fuel"], e["mach"]): e for e in plan["entries"]}
    assert by[(5000.0, 25.0, 0.2)]["pre_state"] == "out_of_region"
    assert by[(5000.0, 25.0, 0.2)]["origin"] == "extra:user"
    # 모델 연료 범위 0~20 kg — 25 kg 줄은 요구 안이지만 모델 밖
    assert by[(200.0, 25.0, 0.15)]["pre_state"] == "model_gap"
    # 60 kg는 경계표 층(10~50) 밖 — 연료 기본 범위 밖이라 요구영역 밖, 전 구간이 계획에 상태로 남는다
    und = [e for e in plan["entries"] if e["row"] == [1000.0, 60.0]]
    assert und and {e["pre_state"] for e in und} == {"out_of_region"}


def test_undefined_row_is_planned_over_every_interval_with_its_state():
    region = _region(boundary=((10.0, ((200.0, 0.1, 0.24), (1000.0, 0.11, 0.24))),
                               (50.0, ((200.0, 0.11, 0.24), (1000.0, 0.12, 0.24)))))
    plan = validation_plan(PointSet(), KNOTS, region, MODEL, rows=[(3000.0, 25.0)])
    es = [e for e in plan["entries"] if e["row"] == [3000.0, 25.0]]
    assert {e["pre_state"] for e in es} == {"undefined"}
    assert sum(e["kind"] == "midpoint" for e in es) == len(KNOTS) - 1


def test_without_a_region_the_row_range_is_the_adopted_design_range_and_there_are_no_boundary_points():
    pts = PointSet([_pt(0.12), _pt(0.16), _pt(0.2), _pt(0.24, trimmable=False)])
    plan = validation_plan(pts, [0.12, 0.16, 0.2, 0.24], None, None, rows=[ROW])
    kinds = {e["kind"] for e in plan["entries"]}
    assert kinds == {"midpoint", "knot"}
    assert max(e["mach"] for e in plan["entries"]) == 0.2  # 채택 안 한 0.24까지 늘리지 않는다(옛 규칙과 같은 범위)


def test_between_rows_keeps_the_v170_altitude_pair_midpoints():
    pts = PointSet([_pt(0.16, alt=200.0), _pt(0.16, alt=1000.0)])
    plan = validation_plan(pts, [0.12, 0.2], _region(boundary=None), MODEL, rows=[(200.0, 25.0), (1000.0, 25.0)],
                           boundary=False)
    btw = [e for e in plan["entries"] if e["kind"] == "between_rows"]
    assert [(e["mach"], e["alt"], e["row"]) for e in btw] == [(0.16, 600.0, None)]
    assert btw[0]["origin"].startswith("midpoint:")  # coverage 집계 키 그대로


def test_later_midpoint_rounds_come_after_boundary_and_extras():
    pts = PointSet([_pt(0.12), _pt(0.2)])
    plan = validation_plan(pts, [0.12, 0.2], _region(boundary=None), MODEL, rows=[ROW], n_between=3,
                           extras=[{"mach": 0.15, "alt": 500.0, "fuel": 30.0, "source": "s"}])
    kinds = [e["kind"] for e in plan["entries"]]
    assert kinds[0] == "midpoint" and kinds.index("extra") < len(kinds) - 2
    assert kinds[-2:] == ["midpoint", "midpoint"]
    assert [e["mach"] for e in plan["entries"] if e["kind"] == "midpoint"] == [0.16, 0.14, 0.18]


# ── 요약 격자 ─────────────────────────────────────────────────────────────────────────


def test_columns_alternate_clip_knot_segment():
    cols = summary_columns([0.1, 0.2, 0.3])
    assert [c["key"] for c in cols] == ["clip_lo", "knot1", "seg1-2", "knot2", "seg2-3", "knot3", "clip_hi"]
    assert [column_of(m, [0.1, 0.2, 0.3]) for m in (0.05, 0.1, 0.15, 0.3, 0.31)] == \
        ["clip_lo", "knot1", "seg1-2", "knot3", "clip_hi"]


def _judged(pts, cases, mach, statuses, *, alt=ROW[0], fuel=ROW[1], role=ROLE_VALIDATION, trim="computable",
            outside=False):
    p = _pt(mach, alt, fuel, role=role, trimmable=not outside)
    p.verdict = {"trim": {"status": trim, "reasons": []}}
    pts.add(p)
    loops = {} if trim != "computable" else {f"l{i}": {"status": s} for i, s in enumerate(statuses)}
    cases[p.name] = {"loops": loops, **({"outside_envelope": True} if outside else {})}
    return p.name


def _entry(mach, alt=ROW[0], fuel=ROW[1], kind="midpoint", row=ROW, pre="not_run"):
    return {"name": case_name(mach, alt, fuel), "mach": mach, "alt": alt, "fuel": fuel, "kind": kind,
            "row": None if row is None else list(row), "origin": kind, "pre_state": pre, "existing": False}


def test_summary_cells_keep_state_verdict_and_coverage_apart():
    pts, cases = PointSet(), {}
    _judged(pts, cases, 0.15, ["ok", "warn"])  # 합격·주의
    _judged(pts, cases, 0.17, ["ok", "fail"])  # 불합격
    _judged(pts, cases, 0.13, [], trim="constraint_hit")  # 트림 실패 — 판정 없음
    _judged(pts, cases, 0.11, ["ok"], outside=True)  # 계산은 됐으나 채택 안 함
    entries = [_entry(0.15), _entry(0.17), _entry(0.13), _entry(0.11),
               _entry(0.19),  # 요청했지만 점이 없다 — 미계산(예산)
               _entry(0.3, kind="boundary", row=None, pre="out_of_region"),
               _entry(0.12, alt=3000.0, fuel=50.0, kind="boundary", row=None)]
    g = summary_grid(entries, pts, cases, [0.1, 0.12, 0.14, 0.16, 0.18, 0.2], rows=[ROW, (1000.0, 30.0)])
    assert [r["key"] for r in g["rows"]] == [row_key(*ROW), row_key(1000.0, 30.0), EXTRA_ROW]
    assert g["rows"][-1]["label"] == "경계·추가"
    row = g["cells"][row_key(*ROW)]
    seg = row["seg3-4"]  # 0.15
    assert (seg["n"], seg["done"], seg["headline"]) == (1, 1, HEADLINE_TEXT["all_met"])  # 합격·주의도 충족이다
    assert seg["verdicts"]["caution"] == 1
    assert row["seg4-5"]["headline"] == "불합격" and row["seg4-5"]["verdicts"]["fail"] == 1
    c = row["seg2-3"]  # 0.13 제약 도달
    assert (c["n"], c["done"], c["headline_code"]) == (1, 0, "incomplete")
    assert c["states"] == {"constraint_hit": 1} and "제약 도달·미수렴 1" in c["text"]
    assert row["seg1-2"]["verdicts"]["excluded"] == 1 and row["seg1-2"]["headline_code"] == "excluded"
    assert row["seg5-6"]["states"] == {"not_run": 1}  # 결과에 없는 요청 점 = 미계산 — 사라지지 않는다
    extra = g["cells"][EXTRA_ROW]
    assert extra["clip_hi"]["n"] == 0 and extra["clip_hi"]["out_of_region"] == 1  # 분모에서 빼고 따로 센다
    assert extra["knot2"]["states"] == {"not_run": 1}
    t = g["totals"]
    assert (t["n"], t["done"], t["out_of_region"]) == (6, 3, 1)
    assert t["headline"] == "불합격"
    texts = [cell["text"] + cell["headline"] for by in g["cells"].values() for cell in by.values()]
    assert not any("구간 합격" in s for s in texts)  # 표본 통과를 구간 보장으로 쓰지 않는다


def test_headline_priority_is_fail_then_incomplete_then_all_met():
    pts, cases = PointSet(), {}
    _judged(pts, cases, 0.15, ["ok"])
    _judged(pts, cases, 0.151, ["fail"])
    g = summary_grid([_entry(0.15), _entry(0.151), _entry(0.152)], pts, cases, [0.1, 0.2])
    cell = g["cells"][row_key(*ROW)]["seg1-2"]
    assert cell["headline"] == "불합격" and cell["text"].startswith("불합격 1 · 완료 2/3")
    g2 = summary_grid([_entry(0.15), _entry(0.152)], pts, cases, [0.1, 0.2])
    assert g2["cells"][row_key(*ROW)]["seg1-2"]["headline"] == "미완료"
    g3 = summary_grid([_entry(0.15)], pts, cases, [0.1, 0.2])
    assert g3["cells"][row_key(*ROW)]["seg1-2"]["headline"] == "검사한 점 모두 충족"


def test_an_interval_only_partly_inside_the_row_range_gets_a_point_in_the_inside_part():
    """행 범위 [0.35, 0.9] · 절점 [0.2, 0.4] — 구간 중점 0.3은 행 밖이지만 0.35–0.4는 요구 안이다. 그 안쪽 부분의 중점에
    내분점을 둔다(리뷰 3 — 전에는 구간을 통째로 건너뛰어 0.35–0.4가 검증 없이 남았다)."""
    region = _region(mach=(0.35, 0.9), boundary=None)
    model = ModelRange(mach=(0.05, 1.5), fuel=(0.0, 60.0))
    plan = validation_plan(PointSet(), [0.2, 0.4, 0.6, 0.8], region, model, rows=[ROW], boundary=False)
    mids = [(e["mach"], e["origin"]) for e in plan["entries"] if e["kind"] == "midpoint"]
    assert mids == [(0.375, "midpoint:M0.35|M0.4"), (0.5, "midpoint:M0.4|M0.6"), (0.7, "midpoint:M0.6|M0.8")]
    assert plan["gaps"] == []
    # 안쪽 부분이 반올림 자릿수보다 좁으면 점을 두지 않고 공백으로 남긴다(조용히 빼지 않는다)
    narrow = _region(mach=(0.3999996, 0.9), boundary=None)
    plan2 = validation_plan(PointSet(), [0.2, 0.4, 0.6], narrow, model, rows=[ROW], boundary=False)
    assert [e["mach"] for e in plan2["entries"] if e["kind"] == "midpoint"] == [0.5]
    (gap,) = plan2["gaps"]
    assert gap["row"] == list(ROW) and gap["interval"] == [0.2, 0.4] and "좁" in gap["why"]


def test_measure_only_entries_do_not_count_in_the_grid():
    pts, cases = PointSet(), {}
    _judged(pts, cases, 0.15, ["ok"])
    alias = {**_entry(0.15, kind="reinforce"), "measure_only": True}
    gap = {**_entry(0.16, kind="reinforce"), "name": "gap:x", "measure_only": True, "gap": "좁다"}
    g = summary_grid([_entry(0.15), alias, gap], pts, cases, [0.1, 0.2])
    assert g["totals"]["n"] == 1


def test_prior_kind_has_a_label():
    from claw.design.validation import VALIDATION_KINDS

    assert VALIDATION_KINDS["prior"] == "이전 계획"
