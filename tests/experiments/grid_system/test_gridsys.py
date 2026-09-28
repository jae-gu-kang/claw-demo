"""격자 체계 첫 실험(05 §11.10) 최소 구현의 테스트 — 순수 로직 + 예제 기체 소규모 통합.

실행: 워크트리 루트에서 `python -m pytest tests/experiments` (엔진은 워크트리 engine/을 sys.path 앞에).
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "experiments" / "grid_system")]

import gridsys as g  # noqa: E402


def cond(m, a=1000.0, f=25.0):
    return g.Condition(m, a, f)


# ── 조건 식별 ────────────────────────────────────────────────────────────────
def test_condition_name_keeps_full_precision():
    # 반올림 이름은 정밀 격자에서 겹친다 — 0.135와 0.1349999는 다른 이름이어야 한다
    assert cond(0.135).name != cond(0.1349999).name
    assert g.Condition(0.2, 0.0, 10.0, config="gear_down").name.endswith("gear_down")


# ── 운용영역 ─────────────────────────────────────────────────────────────────
def test_region_base_range_out_of_region():
    r = g.Region(mach=(0.1, 0.3), alt=(0.0, 3000.0), fuel=(10.0, 50.0))
    assert r.classify(cond(0.2)) is None
    assert r.classify(cond(0.35)) == g.OUT_OF_REGION
    assert r.classify(cond(0.2, a=4000.0)) == g.OUT_OF_REGION


def test_boundary_table_interpolates_and_leaves_gaps_undefined():
    # 연료 층 둘, 고도 행 둘 — 행·층 사이 선형 보간
    bt = {10.0: [(0.0, 0.10, 0.30), (2000.0, 0.14, 0.34)],
          50.0: [(0.0, 0.12, 0.30), (2000.0, 0.16, 0.34)]}
    r = g.Region(mach=(0.0, 1.0), alt=(0.0, 3000.0), fuel=(0.0, 50.0), boundary=bt)
    lo, hi = r.mach_bounds(1000.0, 30.0)
    assert lo == pytest.approx(0.13) and hi == pytest.approx(0.32)
    # 기본 범위 안이지만 표가 덮지 않는 고도·연료는 요구 미정의 — 가까운 행으로 늘리지 않는다
    assert r.classify(cond(0.2, a=2500.0, f=30.0)) == g.UNDEFINED
    assert r.classify(cond(0.2, a=1000.0, f=5.0)) == g.UNDEFINED
    assert r.classify(cond(0.11, a=1000.0, f=30.0)) == g.OUT_OF_REGION


def test_trim_grid_gives_unconfirmed_draft():
    tg = {"mach": {"from": 0.14, "to": 0.22, "step": 0.02}, "alt": [100.0, 3000.0], "fuel": [25.0]}
    r = g.region_draft_from_trim_grid(tg)
    assert (r.mach, r.alt, r.fuel) == ((0.14, 0.22), (100.0, 3000.0), (25.0, 25.0))
    assert r.confirmed is False and r.source == "draft:trim_grid"


# ── 설계점과 절점의 분리 ──────────────────────────────────────────────────────
def test_design_points_do_not_create_breakpoints():
    r = g.Region(mach=(0.1, 0.3), alt=(0.0, 3000.0), fuel=(10.0, 50.0))
    dps = g.auto_design_points(r, n_mach=7, alts=(0.0, 1500.0, 3000.0), fuels=(10.0, 50.0))
    assert len(dps) == 42 and all(d.origin == "auto:grid" for d in dps)
    bs = g.BreakpointSet("M", "mach", (0.1, 0.2, 0.3))
    sch = g.Schedule({"M": bs}, {"pitch.kp": "M"}, {"pitch.kp": [1.0, 2.0, 3.0]})
    assert sch.union_coords() == (0.1, 0.2, 0.3)  # 설계점 42개와 무관


def test_breakpoint_set_must_increase():
    with pytest.raises(ValueError):
        g.BreakpointSet("bad", "mach", (0.2, 0.1))


def test_per_table_breakpoints_sharing_and_union():
    a = g.BreakpointSet("A", "mach", (0.1, 0.2, 0.3))
    b = g.BreakpointSet("B", "mach", (0.1, 0.25, 0.3))
    sch = g.Schedule({"A": a, "B": b}, {"pitch.kp": "A", "pitch.ki": "A", "roll.k_rate": "B"},
                     {"pitch.kp": [1, 2, 3], "pitch.ki": [1, 2, 3], "roll.k_rate": [3, 2, 1]})
    assert sch.sharing() == {"pitch.kp": "shared", "pitch.ki": "shared", "roll.k_rate": "independent"}
    assert sch.union_coords() == (0.1, 0.2, 0.25, 0.3)
    assert sch.union_coords(["pitch.kp"]) == (0.1, 0.2, 0.3)
    t = sch.tables()
    # 각 게인은 자기 절점으로 평가 — B 표의 0.25에서는 꺾이지 않고 A 표는 0.2에서 꺾인다
    assert t["roll.k_rate"].interp(mach=0.25) == pytest.approx(2.0)
    assert t["pitch.kp"].interp(mach=0.25) == pytest.approx(2.5)
    assert t["pitch.kp"].interp(mach=0.5) == pytest.approx(3.0)  # 끝단 clip


# ── 검증점 생성 ──────────────────────────────────────────────────────────────
def test_validation_machs_midpoints_and_clip():
    ms = g.validation_machs((0.1, 0.2, 0.3), (0.05, 0.4), n_between=1)
    kinds = {k: sorted(round(m, 6) for m, kk in ms if kk == k) for k in ("breakpoint", "midpoint", "clip")}
    assert kinds == {"breakpoint": [0.1, 0.2, 0.3], "midpoint": [0.15, 0.25], "clip": [0.075, 0.35]}
    # 요구영역이 절점 안쪽이면 clip 없음
    assert not [m for m, k in g.validation_machs((0.1, 0.3), (0.1, 0.3)) if k == "clip"]


def test_validation_rows_are_independent_of_design_points():
    r = g.Region(mach=(0.1, 0.3), alt=(0.0, 5000.0), fuel=(10.0, 40.0))
    sch = g.Schedule({"M": g.BreakpointSet("M", "mach", (0.1, 0.2, 0.3))}, {"pitch.kp": "M"},
                     {"pitch.kp": [1, 2, 3]})
    spec = g.ValidationSpec(alts=(1000.0, 3000.0, 5000.0), fuels=(10.0, 25.0, 40.0))
    out = g.generate_validation(r, sch, spec)
    mids = [p for p in out["points"] if p.kind == "midpoint"]
    assert {p.row for p in mids} == {(a, f) for a in spec.alts for f in spec.fuels}
    assert {round(p.cond.mach, 6) for p in mids} == {0.15, 0.25}
    assert out["omitted"] == []
    assert any(p.kind == "boundary" for p in out["points"])


def test_representative_mode_reports_omitted_rows():
    r = g.Region(mach=(0.1, 0.3), alt=(0.0, 5000.0), fuel=(10.0, 40.0))
    sch = g.Schedule({"M": g.BreakpointSet("M", "mach", (0.1, 0.3))}, {"pitch.kp": "M"}, {"pitch.kp": [1, 2]})
    spec = g.ValidationSpec(alts=(0.0, 1000.0, 3000.0, 5000.0), fuels=(10.0, 25.0, 40.0), mode="representative")
    out = g.generate_validation(r, sch, spec)
    # 경계·중앙만 남기고 나머지 내부 조합은 생략하되 생략 목록에 남긴다
    assert (3000.0, 10.0) in out["omitted"] and (1000.0, 25.0) not in out["omitted"]
    assert (0.0, 10.0) not in out["omitted"] and (5000.0, 40.0) not in out["omitted"]


# ── 요약 ─────────────────────────────────────────────────────────────────────
def test_columns_alternate_clip_breakpoint_interval():
    assert g.columns((0.1, 0.2, 0.3)) == ["clip<", "bp1", "iv1-2", "bp2", "iv2-3", "bp3", "clip>"]
    assert g.column_of(0.2, (0.1, 0.2, 0.3)) == "bp2"
    assert g.column_of(0.25, (0.1, 0.2, 0.3)) == "iv2-3"
    assert g.column_of(0.05, (0.1, 0.2, 0.3)) == "clip<"


def _rec(m, state, verdict=None, row=(1000.0, 25.0), kind="midpoint"):
    return {"name": cond(m).name, "cond": cond(m), "kind": kind, "row": row, "state": state,
            "reasons": [], "verdict": verdict}


def test_summary_keeps_uncomputed_points_in_denominator():
    union = (0.1, 0.2)
    recs = [_rec(0.15, g.COMPUTABLE, g.GOOD), _rec(0.16, g.CALC_FAILED), _rec(0.17, g.NOT_RUN),
            _rec(0.18, g.MODEL_GAP), _rec(0.12, g.OUT_OF_REGION)]
    s = g.summarize(recs, union)
    cell = s["cells"][((1000.0, 25.0), "iv1-2")]
    assert (cell["n"], cell["done"]) == (4, 1)  # 요구영역 밖만 분모에서 빠진다
    assert s["out_of_region"] == 1
    assert cell["headline"] == "미완료"
    assert "완료 1/4" in cell["text"] and "미계산 1" in cell["text"] and "계산 실패 1" in cell["text"]


def test_headline_never_claims_interval_pass():
    s = g.summarize([_rec(0.15, g.COMPUTABLE, g.GOOD), _rec(0.16, g.COMPUTABLE, g.CAUTION)], (0.1, 0.2))
    assert s["cells"][((1000.0, 25.0), "iv1-2")]["headline"] == "검사한 점 모두 충족"
    s = g.summarize([_rec(0.15, g.COMPUTABLE, g.FAIL), _rec(0.16, g.NOT_RUN)], (0.1, 0.2))
    assert s["cells"][((1000.0, 25.0), "iv1-2")]["headline"] == "불합격"


def test_boundary_and_extra_points_go_to_their_own_row():
    s = g.summarize([_rec(0.15, g.COMPUTABLE, g.GOOD, row=None, kind="boundary")], (0.1, 0.2))
    assert (g.EXTRA_ROW, "iv1-2") in s["cells"]


def test_d_value_is_deviation_from_linear_interpolation():
    def r(m, kind, metric):
        x = _rec(m, g.COMPUTABLE, g.GOOD, kind=kind)
        x["slots"] = {"pitch_rate": {"metric": metric}}
        return x

    recs = [r(0.1, "breakpoint", 0.6), r(0.2, "breakpoint", 0.8), r(0.15, "midpoint", 0.5)]
    d = g.d_values(recs, (0.1, 0.2), {"pitch_rate": 0.4})
    assert d == [{"interval": "iv1-2", "row": (1000.0, 25.0), "slot": "pitch_rate", "d": pytest.approx(0.5)}]


# ── 예제 기체 소규모 통합: 트림 재사용 · 상태 · 스케줄 게인 ───────────────────
@pytest.fixture(scope="module")
def example():
    import claw
    from claw.profile.build import build_profile
    from claw.profile.document import load_example

    assert str(ROOT / "engine") in claw.__file__  # 공유 체크아웃의 옛 엔진이 잡히지 않게
    return build_profile(load_example())


def test_store_reuses_same_key_and_states_are_separated(example):
    store = g.TrimStore()
    ev = g.Evaluator(example, store)
    region = g.Region(mach=(0.14, 1.0), alt=(0.0, 3000.0), fuel=(0.0, 50.0))
    model = g.ModelRange(mach=example.db_ranges()["mach"], fuel=(0.0, 50.0))
    c = cond(0.18, a=1000.0, f=25.0)
    st1, _, _ = ev.state(c, region, model)
    st2, _, _ = ev.state(c, region, model)
    assert (store.computed, store.reused) == (1, 1)
    assert st1 == st2
    # 모델 범위 밖(DB 마하 상한 위)은 트림을 돌리지 않고 모델 부족
    st, rec, _ = ev.state(cond(0.95), region, model)
    assert st == g.MODEL_GAP and rec is None and store.computed == 1


def test_judge_uses_evaluated_schedule_gains(example):
    ev = g.Evaluator(example, g.TrimStore())
    region = g.Region(mach=(0.14, 0.3), alt=(0.0, 3000.0), fuel=(0.0, 50.0))
    model = g.ModelRange(mach=example.db_ranges()["mach"], fuel=(0.0, 50.0))
    bs = {"M": g.BreakpointSet("M", "mach", (0.16, 0.2, 0.24))}
    sch = g.sample_schedule(example, bs, {n: "M" for n in example.doc["law"]["schedule"]["scheduled"]})
    c = cond(0.18, a=1000.0, f=25.0)
    st, rec, _ = ev.state(c, region, model)
    assert st == g.COMPUTABLE
    verdict, slots, gains = ev.judge(c, rec, sch)
    tabs = sch.tables()
    for name, t in tabs.items():
        assert gains[name] == t.interp(mach=0.18)  # 비트 일치 — 실제 표 평가값
    assert verdict in (g.FAIL, g.CAUTION, g.GOOD, g.NA) and set(slots) >= {"pitch_rate", "roll_att"}


def test_unconverged_trim_pinned_at_control_limit_is_infeasible_not_calc_failure(example):
    # 추력 한계 밖: 스로틀이 100 %에 붙은 채 감속 잔차가 남아 미수렴 — 계산 실패가 아니라 물리적 불가다
    ev = g.Evaluator(example, g.TrimStore())
    region = g.Region(mach=(0.1, 1.0), alt=(0.0, 3000.0), fuel=(0.0, 50.0))
    model = g.ModelRange(mach=example.db_ranges()["mach"], fuel=(0.0, 50.0))
    st, rec, why = ev.state(cond(0.5, a=100.0), region, model)
    assert rec["tr"].converged is False
    assert st == g.INFEASIBLE and "throttle_high" in why
