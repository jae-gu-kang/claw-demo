"""pipeline.prescribe 단계화 처방(v1.93, 04 §7.3) — 하드·목표 두 층, 「못 맞춤」 보고, 게인 수별 복수 안.

합성 스윕 행으로 순수 계산을 핀한다(6DOF 없음). 결함 #21의 모양을 그대로 세운다: 하드 지표(동적 여유)는
고칠 수 있는데 주의 지표(alt_rms)가 기준 설계에서 이미 한계 밖이다 — 종전 solve_joint는 둘 다 하드 제약으로
넣어 불가능(→ x≈0)이 됐고, 단계화 풀이는 하드를 풀고 alt_rms의 「못 맞춤」을 사유·최선값과 함께 말한다.
"""

import pytest

from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.prescribe import (
    MAX_FULL_POOL,
    TIER_LABEL,
    TIER_RANK,
    _plan_key,
    enumerate_plans,
    solve_joint,
    solve_tiered,
)

DYN, ALT = "de_dyn_reserve_min_frac", "alt_rms"
K1, K2, K3 = "table.pitch.kp", "fcl/Autopilot.kp_alt", "fcl/Autopilot.k_hdot"
SLOPES = {K1: {DYN: 0.3, ALT: 2.0},   # 동적 여유를 올리지만 alt_rms를 나쁘게
          K2: {DYN: 0.0, ALT: -5.0},  # alt_rms만 줄인다
          K3: {DYN: 0.2, ALT: 0.0}}   # 동적 여유만 올린다


def _rows(slopes=SLOPES, base=None, cases=(("A", 0.0), ("B", 0.5))):
    """선형 합성 스윕 — base + 설계변수마다 ±10·20 % 단독 런. 케이스 B는 alt_rms가 0.5 높다."""
    base = base or {DYN: 0.02, ALT: 12.0}
    rows = []
    for case, off in cases:
        b = dict(base, **{ALT: base[ALT] + off})
        rows.append({"case": case, "label": "base", "role": "base", "overrides": {},
                     "aborted": False, "metrics": b})
        for k, sl in slopes.items():
            for s in (-0.2, -0.1, 0.1, 0.2):
                rows.append({"case": case, "label": f"{k}@{s:+g}", "role": "single",
                             "overrides": {k: 1.0 + s}, "aborted": False,
                             "metrics": {m: b[m] + sl.get(m, 0.0) * s for m in b}})
    return rows


CRIT = GainEvalCriteria()
TIERS = {"hard_metrics": [DYN], "goal_metrics": [ALT]}


def test_목표_지표가_기준에서_한계_밖이면_하드는_풀리고_목표는_못_맞춤():
    out = solve_tiered(_rows(), [K1, K2, K3], CRIT, **TIERS)
    f = out["feasibility"]
    assert f["hard"]["solvable"] is True and f["hard"]["violated"] == []
    assert f["goal"]["solvable"] is False
    assert f["mode"] == "nonregress"
    assert f["limits"] == {DYN: {"limit": 0.05, "above_is_bad": False, "tier": "hard"},
                           ALT: {"limit": 10.0, "above_is_bad": True, "tier": "goal"}}
    viol = f["goal"]["violated"]
    assert {(v["metric"], v["case"]) for v in viol} == {(ALT, "A"), (ALT, "B")}
    # 최선값 = alt_rms만 최소화한 상자 꼭짓점 — 12 + min(±0.4) + min(±1.0) = 10.6 (B는 11.1) — 기준보다 낫다
    by = {v["case"]: v for v in viol}
    assert by["A"]["best_reachable"] == pytest.approx(10.6)
    assert by["B"]["best_reachable"] == pytest.approx(11.1)
    assert all(v["best_reachable"] < v["base"] for v in viol)
    # 사유 — 가장 모자란 케이스의 최선값과 탐색 범위
    assert f["reason"] == "alt_rms는 탐색 범위(±20 %) 안 어떤 조합으로도 10 아래로 못 내려간다(최선 11.1 @B)"
    # 조합 해 자체는 하드를 만족하고 alt_rms는 퇴행하지 않는다(퇴행 금지 층)
    assert out["solvable"] is True and out["tier"] == "nonregress"
    assert f["goal"]["nonregress_solvable"] is True
    for case, b in (("A", 12.0), ("B", 12.5)):
        assert out["predicted"][case][DYN] >= 0.05 - 1e-9
        assert out["predicted"][case][ALT] <= b + 1e-9
    assert {u["case"] for u in out["unmet"]} == {"A", "B"}


def test_종전_solve_joint는_같은_입력에서_불가능을_그대로_낸다():
    """하위 호환 — solve_joint(min_change, metrics=…)의 서명·동작은 그대로다(성능 목적 등 다른 호출자)."""
    out = solve_joint(_rows(), [K1, K2, K3], CRIT, metrics=[ALT, DYN])
    assert out["solvable"] is False
    assert any(v["metric"] == ALT for v in out["violated"])
    assert "feasibility" not in out and "tier" not in out
    assert out["objective"] == "min_change"
    assert out["changed_count"] == len(out["changed_knobs"])


def test_목표까지_맞출_수_있으면_goal_층_최소_변화():
    rows = _rows(base={DYN: 0.02, ALT: 10.5}, cases=(("A", 0.0),))
    out = solve_tiered(rows, [K1, K2, K3], CRIT, **TIERS)
    f = out["feasibility"]
    assert f["hard"]["solvable"] and f["goal"]["solvable"] is True
    assert f["reason"] is None and f["mode"] == "goal"
    assert out["tier"] == "goal" and out["unmet"] == []
    assert out["predicted"]["A"][ALT] <= 10.0 + 1e-9


def test_하드부터_못_맞추면_못_맞춤은_그대로_말하고_경계_안을_확인_런에_올린다():
    """선형 모델은 길잡이, 판정자는 확인 런 — feasibility는 정직하게 「못 맞춤」, 안은 경계 해 하나(hard_boundary)."""
    weak = {K3: {DYN: 0.05, ALT: 0.0}}  # +20 %여도 0.02+0.01 = 0.03 < 0.05
    res = enumerate_plans(_rows(slopes=weak), [K3], CRIT, **TIERS)
    f = res["feasibility"]
    assert f["hard"]["solvable"] is False
    assert f["goal"]["solvable"] is None  # 하드가 먼저다 — 목표 판정을 지어내지 않는다
    hv = f["hard"]["violated"]
    assert hv and hv[0]["best_reachable"] == pytest.approx(0.03)
    assert "0.05 위로 못 올라간다" in f["reason"]
    assert res["joint"]["solvable"] is False and res["joint"]["reason"] == f["reason"]
    (p,) = res["plans"]
    assert p["tier"] == "hard_boundary" and TIER_RANK["hard_boundary"] == 3
    assert p["solvable"] is False
    assert TIER_LABEL["hard_boundary"] == "모델 예측 미달 — 확인 런으로 판정"
    # 경계 해 = best_reachable이 나온 꼭짓점(+20 %)
    assert p["knobs"] == [K3] and p["spans"][K3] == pytest.approx(0.2, abs=1e-6)
    assert p["predicted"]["A"][DYN] == pytest.approx(0.03, abs=1e-6)
    assert {(u["metric"], u["case"]) for u in p["hard_unmet"]} == {(DYN, "A"), (DYN, "B")}
    assert res["candidates"] == [p]


def test_경계_해는_부족분에_영향_없는_게인을_움직이지_않는다():
    weak = {K3: {DYN: 0.05, ALT: 0.0}, K2: {DYN: 0.0, ALT: -5.0}}
    (p,) = enumerate_plans(_rows(slopes=weak), [K3, K2], CRIT, **TIERS)["plans"]
    assert p["knobs"] == [K3]


def test_게인_수별_복수_안_순위와_결정성():
    res = enumerate_plans(_rows(), [K1, K2, K3], CRIT, **TIERS)
    assert res["n_subsets"] == 7 and res["pruned"] == []
    plans = res["plans"]
    # 게인 수마다 최선 1안 — 바뀐 게인 수가 겹치지 않는다
    ks = [p["cost"]["n_changed"] for p in plans]
    assert sorted(ks) == [1, 2, 3]
    assert [_plan_key(p) for p in plans] == sorted(_plan_key(p) for p in plans)
    # 1-게인 안은 k_hdot 단독 — K1 단독은 alt_rms를 퇴행시키고 K2 단독은 하드를 못 푼다
    one = next(p for p in plans if p["cost"]["n_changed"] == 1)
    assert one["knobs"] == [K3] and one["spans"][K3] == pytest.approx(0.15, abs=1e-4)
    assert one["score"] == pytest.approx(0.0, abs=1e-9)
    # 개선량이 큰 안(alt_rms를 줄이는 K2를 쓴 안)이 앞선다
    assert K2 in plans[0]["knobs"] and plans[0]["score"] < 0
    for p in plans:
        assert p["tier"] == "nonregress" and p["solvable"] is True
        assert p["cost"]["max_pct"] == pytest.approx(max(abs(v) for v in p["spans"].values()) * 100)
        for case, b in (("A", 12.0), ("B", 12.5)):
            assert p["predicted"][case][DYN] >= 0.05 - 1e-9
            assert p["predicted"][case][ALT] <= b + 1e-9
    # 후보 전부도 순위순이고 바뀐 게인 집합이 겹치지 않는다
    keys = [tuple(p["knobs"]) for p in res["candidates"]]
    assert len(keys) == len(set(keys))
    assert [_plan_key(p) for p in res["candidates"]] == sorted(_plan_key(p) for p in res["candidates"])
    # 결정적 — 같은 입력이면 같은 순서·같은 값, 풀 순서를 뒤집어도 같은 안 집합
    again = enumerate_plans(_rows(), [K1, K2, K3], CRIT, **TIERS)
    assert [(p["knobs"], p["spans"]) for p in again["plans"]] == [(p["knobs"], p["spans"]) for p in plans]
    rev = enumerate_plans(_rows(), [K3, K2, K1], CRIT, **TIERS)
    assert {tuple(sorted(p["knobs"])) for p in rev["plans"]} == {tuple(sorted(p["knobs"])) for p in plans}


def test_K가_부분집합_크기를_자른다():
    res = enumerate_plans(_rows(), [K1, K2, K3], CRIT, K=1, **TIERS)
    assert res["n_subsets"] == 3
    assert [p["knobs"] for p in res["plans"]] == [[K3]]


def test_퇴행_금지로도_안_풀리면_하드_층으로_떨어지고_퇴행을_든다():
    only = {K1: SLOPES[K1]}  # 동적 여유를 고치려면 alt_rms가 반드시 나빠진다
    res = enumerate_plans(_rows(slopes=only), [K1], CRIT, **TIERS)
    f = res["feasibility"]
    assert f["hard"]["solvable"] and f["goal"]["solvable"] is False
    assert f["goal"]["nonregress_solvable"] is False
    (p,) = res["plans"]
    assert p["tier"] == "hard" and TIER_RANK["hard"] == 2
    assert {r["case"] for r in p["regressed"]} == {"A", "B"}
    assert p["spans"][K1] == pytest.approx(0.1, abs=1e-4)


def test_풀이_크면_민감도로_가지친다():
    slopes = dict(SLOPES)
    for i in range(MAX_FULL_POOL - 3):
        slopes[f"table.k{i}"] = {DYN: 0.01 * (i + 1), ALT: 0.0}
    slopes["table.dead1"] = {DYN: 0.0, ALT: 0.0}
    slopes["table.dead2"] = {DYN: 0.0, ALT: 0.0}
    knobs = list(slopes)
    assert len(knobs) == MAX_FULL_POOL + 2
    res = enumerate_plans(_rows(slopes=slopes), knobs, CRIT, K=2, **TIERS)
    assert [e["knob"] for e in res["pruned"]] == ["table.dead1", "table.dead2"]
    assert all(e["reason"] for e in res["pruned"])
    assert res["n_subsets"] == MAX_FULL_POOL + MAX_FULL_POOL * (MAX_FULL_POOL - 1) // 2
    assert all("dead" not in k for p in res["candidates"] for k in p["knobs"])


def test_hard_metrics_None이면_목표가_아닌_하드_지표_전부():
    out = solve_tiered(_rows(), [K1, K2, K3], CRIT, goal_metrics=[ALT])
    assert DYN in out["feasibility"]["hard"]["metrics"]
    assert ALT not in out["feasibility"]["hard"]["metrics"]
    assert out["feasibility"]["goal"]["metrics"] == [ALT]


def test_기준_런이_없으면_사유():
    rows = [r for r in _rows() if r["label"] != "base"]
    out = solve_tiered(rows, [K1], CRIT, **TIERS)
    assert out["solvable"] is False and out["feasibility"] is None
    res = enumerate_plans(rows, [K1], CRIT, **TIERS)
    assert res["plans"] == [] and res["feasibility"] is None


def test_승계_없이_부르면_하드_게이트_지표가_하드_추종_RMS가_목표():
    """evaluate는 RMS로 Fail을 내지 않는다 — 기본 하드 층은 하드 게이트 지표, 나머지 기준 지표는 목표 층."""
    out = solve_tiered(_rows(), [K1, K2, K3], CRIT)
    f = out["feasibility"]
    assert DYN in f["hard"]["metrics"] and ALT not in f["hard"]["metrics"]
    assert ALT in f["goal"]["metrics"]
    assert f["hard"]["solvable"] is True and f["goal"]["solvable"] is False
