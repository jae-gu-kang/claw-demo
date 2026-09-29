"""pipeline.prescribe 성능 목적(objective="performance") 검증 — 04 §7.3 복수 게인 성능 최적화.

전부 합성 스윕 행(6DOF 없음). 핵심 규약: ① min_change는 종전 값 그대로 + 정보 키만
늘어난다 ② performance는 하드 문턱을 **전부** 지키며 lower-is-better 지표를 기울기
방향으로 민다 ③ 선형 모델은 경계로 달리므로 평활항이 없으면 bound_active가 그 사실을
말한다 ④ None·inf·비단조는 목적에서 빼되 사유를 남긴다 ⑤ 개선 방향이 없으면 0 변화.
"""

import math

import pytest

from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.prescribe import (
    CHANGED_TOL,
    PERF_METRICS_DEFAULT,
    perf_compare,
    solve_joint,
)

K = "table.pitch.kp"
K2 = "table.spd.kp"

# 하드 지표가 전부 여유 있게 통과하는 기본 바탕
_OK = {"alt_rms": 5.0, "spd_rms": 1.0, "hdg_rms": 0.05,
       "surf_sat_frac": 0.0, "worst_stall_margin": 0.2,
       "de_dyn_reserve_min_frac": 0.5}


def _rows(case, knob, base, by_span, with_base=True):
    rows = []
    if with_base:
        rows.append({"case": case, "label": "base", "role": "base", "overrides": {},
                     "aborted": False, "metrics": dict(base)})
    for s, delta in sorted(by_span.items()):
        m = dict(base)
        m.update(delta)
        rows.append({"case": case, "label": f"{knob}@{s:+g}", "role": "single",
                     "overrides": {knob: 1.0 + s}, "aborted": False, "metrics": m})
    return rows


def _lin(base, slopes, spans=(-0.2, -0.1, 0.1, 0.2)):
    """지표별 선형 기울기 {metric: slope} → 스팬별 덮어쓰기."""
    return {s: {m: base[m] + sl * s for m, sl in slopes.items()} for s in spans}


def test_min_change는_종전_그대로에_정보_키만_는다():
    base = dict(_OK, alt_rms=12.0)
    rows = _rows("A", K, base, _lin(base, {"alt_rms": -10.0}))
    out = solve_joint(rows, [K], GainEvalCriteria())
    assert out["objective"] == "min_change"
    assert out["solvable"] is True
    assert abs(out["spans"][K] - 0.2) < 1e-3  # 12−10x ≤ 10
    assert out["changed_knobs"] == [K] and out["changed_count"] == 1
    assert "perf_metrics" not in out  # 성능 키는 성능 목적에만


def test_min_change_이미_통과면_바뀐_게인_0개():
    rows = _rows("A", K, _OK, _lin(_OK, {"alt_rms": -10.0}))
    out = solve_joint(rows, [K], GainEvalCriteria())
    assert out["changed_knobs"] == [] and out["changed_count"] == 0


def test_성능은_기울기_방향으로_밀되_묶인_하드_제약을_지킨다():
    """kp↑는 alt_ts를 줄이지만 포화율을 올린다 — 포화 한계가 멈춘다."""
    crit = GainEvalCriteria()
    lim = float(crit.actuator.sat_frac_max)
    base = dict(_OK, alt_ts=10.0, surf_sat_frac=lim - 0.01)
    # 포화율 기울기 0.1/스팬 → x ≤ 0.1 에서 묶인다 (경계 0.2 보다 안쪽)
    rows = _rows("A", K, base, _lin(base, {"alt_ts": -20.0, "surf_sat_frac": 0.1}))
    out = solve_joint(rows, [K], crit, objective="performance", smooth_weight=0.0)
    assert out["objective"] == "performance"
    assert out["solvable"] is True, out
    x = out["spans"][K]
    assert abs(x - 0.1) < 1e-4
    assert out["predicted"]["A"]["surf_sat_frac"] <= lim + 1e-9
    pp = out["perf_predicted"]["A"]["alt_ts"]
    assert pp["base"] == 10.0 and pp["predicted"] < 10.0 and pp["delta_frac"] < 0
    ov = out["objective_value"]
    assert ov["predicted"] < ov["base"] and ov["smoothing"] == 0.0
    assert out["bound_active"] == []  # 제약이 멈췄지 신뢰영역이 아니다
    assert out["changed_knobs"] == [K]


def test_성능은_metrics_좁히기를_무시하고_하드_전부를_지킨다():
    crit = GainEvalCriteria()
    lim = float(crit.actuator.sat_frac_max)
    base = dict(_OK, alt_ts=10.0, surf_sat_frac=lim - 0.01)
    rows = _rows("A", K, base, _lin(base, {"alt_ts": -20.0, "surf_sat_frac": 0.1}))
    out = solve_joint(rows, [K], crit, objective="performance", smooth_weight=0.0,
                      metrics=["alt_rms"])  # 좁혀도 포화 제약은 남는다
    assert abs(out["spans"][K] - 0.1) < 1e-4


def test_평활항이_크면_안쪽_작으면_경계():
    base = dict(_OK, alt_ts=10.0)
    rows = _rows("A", K, base, _lin(base, {"alt_ts": -20.0}))
    small = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                        smooth_weight=0.0)
    assert small["bound_active"] == [K]
    assert abs(small["spans"][K] - 0.2) < 1e-6
    big = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts"], smooth_weight=100.0)
    xb = big["spans"][K]
    # 지표 하나(Σw=1): J = (10−20x)/10 + 100·(x/0.2)² 해석해
    # dJ/dx = −2 + 100·2x/0.04 = 0 → x = 0.0004 (기본 아홉 지표면 평탄한 RMS 셋이 Σw에 들어 1/4로 준다)
    assert 0.0 < xb < 0.2 - 1e-3
    assert abs(xb - 0.0004) < 1e-5
    assert big["bound_active"] == []
    assert big["objective_value"]["smoothing"] > 0.0


def test_가중치가_축을_가른다():
    """kp는 alt_ts를 줄이고 spd_ts를 늘린다 — 가중이 방향을 정한다."""
    base = dict(_OK, alt_ts=10.0, spd_ts=10.0)
    rows = _rows("A", K, base, _lin(base, {"alt_ts": -20.0, "spd_ts": 10.0}))
    a = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                    smooth_weight=0.0)
    assert a["spans"][K] > 0.19
    b = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                    smooth_weight=0.0, perf_weights={"spd_ts": 5.0})
    assert b["spans"][K] < -0.19
    assert b["perf_weights"]["spd_ts"] == 5.0 and b["perf_weights"]["alt_ts"] == 1.0


def test_None_inf_비단조는_사유와_함께_목적에서_빠진다():
    base = dict(_OK, alt_ts=10.0, spd_ts=float("inf"), hdg_ts=None, alt_mp=0.1)
    rows = (_rows("A", K, base, {-0.1: {"alt_ts": 12.0, "alt_mp": 0.12},
                                 0.1: {"alt_ts": 8.0, "alt_mp": 0.12},
                                 0.2: {"alt_ts": 6.0, "alt_mp": 0.08}}))
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance")
    ex = {(e["metric"], e["case"]): e["reason"] for e in out["perf_excluded"]}
    assert "미정착" in ex[("spd_ts", "A")]
    assert "판정 불가" in ex[("hdg_ts", "A")]
    assert "비단조" in ex[("alt_mp", None)]
    assert "alt_mp" not in out["perf_predicted"]["A"]
    assert "alt_ts" in out["perf_predicted"]["A"]
    assert out["solvable"] is True


def test_직렬화된_inf_문자열도_미정착이다():
    base = dict(_OK, alt_ts="inf")
    rows = _rows("A", K, base, {0.1: {"alt_ts": "inf"}})
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts"])
    assert out["solvable"] is False
    assert "하나도" in out["reason"]
    assert "미정착" in out["perf_excluded"][0]["reason"]


def test_인자_검증():
    rows = _rows("A", K, dict(_OK, alt_ts=10.0), {0.1: {"alt_ts": 9.0}})
    c = GainEvalCriteria()
    with pytest.raises(ValueError, match="perf_weights"):
        solve_joint(rows, [K], c, objective="performance", perf_weights={"없는": 1.0})
    with pytest.raises(ValueError, match="higher"):
        solve_joint(rows, [K], c, objective="performance",
                    perf_metrics=["worst_stall_margin"])
    with pytest.raises(ValueError):
        solve_joint(rows, [K], c, objective="performance", perf_metrics=["없는지표"])
    with pytest.raises(ValueError, match="objective"):
        solve_joint(rows, [K], c, objective="best")


def test_개선_방향이_없으면_0_변화():
    """kp가 alt_ts를 안 움직이는 자리(평탄, 기울기 0) — 목적이 줄 방향이 없으니 0 변화."""
    base = dict(_OK, alt_ts=10.0)
    rows = _rows("A", K, base, {-0.1: {"alt_ts": 10.0}, 0.1: {"alt_ts": 10.0}})
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      smooth_weight=0.0)
    assert out["solvable"] is True
    assert out["spans"] == {K: 0.0}
    assert out["changed_count"] == 0
    assert "더 낫게 하는 방향" in out["reason"]


def test_두_게인_중_하나만_바뀌면_changed_count_1():
    base = dict(_OK, alt_ts=10.0)
    rows = (_rows("A", K, base, _lin(base, {"alt_ts": -20.0}))
            + _rows("A", K2, base, {-0.1: {}, 0.1: {}}, with_base=False))
    out = solve_joint(rows, [K, K2], GainEvalCriteria(), objective="performance")
    assert out["changed_knobs"] == [K] and out["changed_count"] == 1
    assert abs(out["spans"][K2]) <= CHANGED_TOL


def test_기본_성능_지표는_전부_lower다():
    from claw.pipeline.influence import METRICS
    better = {m.key: m.better for m in METRICS}
    assert all(better[k] == "lower" for k in PERF_METRICS_DEFAULT)


def test_perf_compare는_inf_문자열을_다룬다():
    out = perf_compare({"alt_ts": 10.0, "spd_ts": "inf", "hdg_ts": None, "alt_mp": 0.2},
                       {"alt_ts": 8.0, "spd_ts": 12.0, "hdg_ts": 3.0, "alt_mp": "inf"},
                       perf_metrics=("alt_ts", "spd_ts", "hdg_ts", "alt_mp"))
    assert out["alt_ts"]["base"] == 10.0 and out["alt_ts"]["new"] == 8.0
    assert abs(out["alt_ts"]["delta_frac"] + 0.2) < 1e-12
    assert out["spd_ts"]["base"] is None and out["spd_ts"]["base_state"] == "inf"
    assert out["spd_ts"]["delta_frac"] is None
    assert out["hdg_ts"]["base_state"] == "none"
    assert out["alt_mp"]["new_state"] == "inf" and out["alt_mp"]["delta_frac"] is None
    assert math.isfinite(out["alt_ts"]["delta_frac"])


# ---------- 탐색 경계는 스윕이 실제로 재어 본 자리까지 (리뷰 MUST 1) ----------

def _probe_rows(top):
    """alt_ts 14/12/10/8 @ −0.2..+0.1 — +0.2 표본은 top(덮어쓰기)이 정한다."""
    base = dict(_OK, alt_ts=10.0)
    rows = _rows("A", K, base, {-0.2: {"alt_ts": 14.0}, -0.1: {"alt_ts": 12.0},
                                0.1: {"alt_ts": 8.0}, 0.2: top.get("delta", {})})
    if top.get("aborted"):
        rows[-1]["aborted"] = True
    return rows


def test_경계_표본이_미정착이면_탐색을_그_안쪽_표본으로_줄인다():
    rows = _probe_rows({"delta": {"alt_ts": float("inf")}})
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts"], smooth_weight=0.0)
    assert out["solvable"] is True, out
    assert out["spans"][K] <= 0.1 + 1e-9
    assert abs(out["spans"][K] - 0.1) < 1e-6  # 선형 목적은 줄인 경계까지 간다
    bl = out["bound_limits"][K]
    assert bl["lo"] == -0.2 and bl["hi"] == 0.1
    assert "+20 %" in bl["reason"] and "미정착" in bl["reason"] and "+10 %" in bl["reason"]
    assert any(r.startswith(K) and "미정착" in r for r in out["bound_reasons"])
    assert out["bound_active"] == [K]  # 실제 경계(+10 %)에 닿았다


def test_경계_표본이_발산으로_잘렸으면_같은_규칙():
    rows = _probe_rows({"delta": {"alt_ts": 6.0}, "aborted": True})
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts"], smooth_weight=0.0)
    assert abs(out["spans"][K] - 0.1) < 1e-6
    bl = out["bound_limits"][K]
    assert bl["hi"] == 0.1 and "발산" in bl["reason"] and "+20 %" in bl["reason"]


def test_표본이_10퍼센트뿐이면_탐색도_10퍼센트():
    base = dict(_OK, alt_ts=10.0)
    rows = _rows("A", K, base, _lin(base, {"alt_ts": -20.0}, spans=(-0.1, 0.1)))
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      smooth_weight=0.0)
    bl = out["bound_limits"][K]
    assert bl["lo"] == -0.1 and bl["hi"] == 0.1
    assert "외삽" in bl["reason"]
    assert abs(out["spans"][K] - 0.1) < 1e-6
    assert out["bound_active"] == [K]
    assert out["span_bound"] == 0.2  # 사용자 한계는 그대로 에코한다 — 줄인 것은 bound_limits


def test_한쪽_표본이_없으면_그쪽_경계는_0():
    base = dict(_OK, alt_ts=10.0)
    rows = _rows("A", K, base, {0.1: {"alt_ts": 12.0}, 0.2: {"alt_ts": 14.0}})
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      smooth_weight=0.0)
    bl = out["bound_limits"][K]
    assert bl["lo"] == 0.0 and bl["hi"] == 0.2
    assert "표본이 없다" in bl["reason"]
    assert out["spans"][K] == 0.0  # 줄이는 쪽(−)이 막혔다
    assert out["bound_active"] == [K]  # 목적은 −로 가고 싶었는데 경계 0이 멈췄다


def test_경계는_전_케이스가_유효해야_한다():
    base = dict(_OK, alt_ts=10.0)
    rows = (_rows("A", K, base, _lin(base, {"alt_ts": -20.0}))
            + _rows("B", K, base, {-0.2: {"alt_ts": 14.0}, -0.1: {"alt_ts": 12.0},
                                   0.1: {"alt_ts": 8.0}}))  # B는 +0.2 행이 없다
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts"], smooth_weight=0.0)
    bl = out["bound_limits"][K]
    assert bl["hi"] == 0.1 and "B" in bl["reason"]


def test_min_change는_표본_경계를_쓰지_않는다():
    """최소 수정은 종전 그대로 ±span_bound — 경계 축소는 성능 목적에만."""
    base = dict(_OK, alt_rms=12.0)
    rows = _rows("A", K, base, _lin(base, {"alt_rms": -10.0}, spans=(-0.1, 0.1)))
    out = solve_joint(rows, [K], GainEvalCriteria())
    assert abs(out["spans"][K] - 0.2) < 1e-3
    assert "bound_limits" not in out


def test_하드_지표가_비단조면_경고하고_최소_표본까지만_간다():
    crit = GainEvalCriteria()
    base = dict(_OK, alt_ts=10.0, surf_sat_frac=0.0)
    rows = _rows("A", K, base, {
        -0.2: {"alt_ts": 14.0, "surf_sat_frac": 0.02},
        -0.1: {"alt_ts": 12.0, "surf_sat_frac": 0.01},
        0.1: {"alt_ts": 8.0, "surf_sat_frac": 0.01},
        0.2: {"alt_ts": 6.0, "surf_sat_frac": 0.04}})
    out = solve_joint(rows, [K], crit, objective="performance",
                      perf_metrics=["alt_ts"], smooth_weight=0.0)
    assert out["hard_unmodelled"] == [{"knob": K, "metric": "surf_sat_frac"}]
    bl = out["bound_limits"][K]
    assert bl["lo"] == -0.1 and bl["hi"] == 0.1
    assert "surf_sat_frac" in bl["reason"]
    assert abs(out["spans"][K] - 0.1) < 1e-6


# ---------- 평활항 정규화 · 수치 실패 · 기준 위반 · 다중 케이스 ----------

def test_평활항은_가중_합과_지표_수에_무관하다():
    """목적을 Σw로 정규화한다 — 같은 정규화 기울기면 가중·지표 수가 달라도 같은 해."""
    base = dict(_OK, alt_ts=10.0, spd_ts=10.0)
    rows = _rows("A", K, base, _lin(base, {"alt_ts": -20.0, "spd_ts": -20.0}))
    one = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts"], smooth_weight=100.0)
    two = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts", "spd_ts"],
                      perf_weights={"alt_ts": 2.0, "spd_ts": 2.0}, smooth_weight=100.0)
    assert abs(one["spans"][K] - 0.0004) < 1e-7
    assert abs(two["spans"][K] - one["spans"][K]) < 1e-9
    # 보고도 같은 자 — 정규화된 목적값(기준 1.0, 평활항 = sw·(x/span_bound)²)
    for o in (one, two):
        ov = o["objective_value"]
        assert abs(ov["base"] - 1.0) < 1e-12
        x = o["spans"][K]
        assert abs(ov["predicted"] - (1.0 - 2.0 * x)) < 1e-9
        assert abs(ov["smoothing"] - 100.0 * (x / 0.2) ** 2) < 1e-12


def test_가중이_전부_0이면_거절():
    rows = _rows("A", K, dict(_OK, alt_ts=10.0), {0.1: {"alt_ts": 9.0}})
    with pytest.raises(ValueError, match="전부 0"):
        solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                    perf_metrics=["alt_ts"], perf_weights={"alt_ts": 0.0})


def test_기준이_하드를_지키는데_최적화가_위반해를_내면_0_변화(monkeypatch):
    from types import SimpleNamespace

    import claw.pipeline.prescribe as pr

    crit = GainEvalCriteria()
    lim = float(crit.actuator.sat_frac_max)
    base = dict(_OK, alt_ts=10.0, surf_sat_frac=lim - 0.01)
    rows = _rows("A", K, base, _lin(base, {"alt_ts": -20.0, "surf_sat_frac": 0.1}))
    # 수치 실패 흉내 — 포화 한계를 넘는 x(0.2)를 성공 아님으로 돌려준다
    monkeypatch.setattr(pr, "minimize", lambda *a, **k: SimpleNamespace(
        x=pr.np.array([0.2]), success=False, message="Iteration limit reached"))
    out = pr.solve_joint(rows, [K], crit, objective="performance", smooth_weight=0.0)
    assert out["spans"] == {K: 0.0}
    assert out["solvable"] is True and out["violated"] == []
    assert "0 변화" in out["reason"] and "Iteration limit" in out["reason"]
    assert out["changed_count"] == 0


def test_기준이_하드_위반이면_성능을_잃더라도_제약이_요구한_변화를_낸다():
    """alt_rms 12 > 10 — kp↑가 고치지만 alt_ts를 늘린다. 0으로 되돌리지 않는다."""
    base = dict(_OK, alt_rms=12.0, alt_ts=10.0)
    rows = _rows("A", K, base, _lin(base, {"alt_rms": -10.0, "alt_ts": 20.0}))
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts"], smooth_weight=0.0)
    assert out["solvable"] is True, out
    assert abs(out["spans"][K] - 0.2) < 1e-6  # 12−10x ≤ 10 의 최소 x
    ov = out["objective_value"]
    assert ov["predicted"] > ov["base"]  # 성능 손해를 감수한 답 — 유지된다
    assert out["reason"] is None
    assert out["predicted"]["A"]["alt_rms"] <= 10.0 + 1e-9


def test_다중_케이스는_항_가중_평균이다():
    """A: alt_ts(기울기 −2/스팬, 정규화) + alt_mp(바닥 아래 → 0.5), B: alt_ts만.
    J = Σ w·v/scale / Σw — 케이스마다 항 수가 달라도 같은 자."""
    base_a = dict(_OK, alt_ts=10.0, alt_mp=0.005)
    base_b = dict(_OK, alt_ts=10.0, alt_mp=None)
    rows = (_rows("A", K, base_a, _lin(base_a, {"alt_ts": -20.0, "alt_mp": 0.0}))
            + _rows("B", K, base_b, _lin(base_b, {"alt_ts": -10.0})))
    out = solve_joint(rows, [K], GainEvalCriteria(), objective="performance",
                      perf_metrics=["alt_ts", "alt_mp"], perf_weights={"alt_mp": 3.0},
                      smooth_weight=0.0)
    assert abs(out["spans"][K] - 0.2) < 1e-6
    ov = out["objective_value"]
    assert abs(ov["base"] - (1.0 + 3.0 * 0.5 + 1.0) / 5.0) < 1e-12
    assert abs(ov["predicted"] - (0.6 + 1.5 + 0.8) / 5.0) < 1e-9
    assert abs(out["perf_predicted"]["A"]["alt_ts"]["predicted"] - 6.0) < 1e-6
    assert abs(out["perf_predicted"]["B"]["alt_ts"]["predicted"] - 8.0) < 1e-6
    assert ("alt_mp", "B") in {(e["metric"], e["case"]) for e in out["perf_excluded"]}


# ---------- 최소 수정 고정 — 성능 목적 도입 전(HEAD dfba11a) 알고리즘의 저장값 ----------

def _pin_rows():
    out = []
    for case, b_alt, b_spd in (("A", 11.2, 1.0), ("B", 9.5, 2.2)):
        base = dict(_OK, alt_rms=b_alt, spd_rms=b_spd)
        out.append({"case": case, "label": "base", "role": "base", "overrides": {},
                    "aborted": False, "metrics": dict(base)})
        for knob, sa, ss in ((K, -9.0, 0.7), (K2, 1.5, -3.0)):
            for s in (-0.2, -0.1, 0.1, 0.2):
                m = dict(base, alt_rms=b_alt + sa * s + 0.3 * s * s,
                         spd_rms=b_spd + ss * s - 0.2 * s * s,
                         surf_sat_frac=0.01 * abs(s) if knob == K else 0.0)
                out.append({"case": case, "label": f"{knob}@{s:+g}", "role": "single",
                            "overrides": {knob: 1 + s}, "aborted": False, "metrics": m})
    return out


def test_min_change는_도입_전_알고리즘과_같은_값이다():
    """기댓값은 `git show dfba11a:engine/claw/pipeline/prescribe.py`의 solve_joint가 같은 행에서 낸 값."""
    out = solve_joint(_pin_rows(), [K, K2], GainEvalCriteria())
    assert out["solvable"] is True and out["reason"] is None
    assert abs(out["spans"][K] - 0.15028901734104055) < 1e-12
    assert abs(out["spans"][K2] - 0.10173410404624286) < 1e-12
    assert abs(out["predicted"]["A"]["alt_rms"] - 9.999999999999998) < 1e-12
    assert abs(out["predicted"]["B"]["spd_rms"] - 2.0) < 1e-12
    narrowed = solve_joint(_pin_rows(), [K, K2], GainEvalCriteria(), metrics=["alt_rms"])
    assert abs(narrowed["spans"][K] - 0.1297297297265828) < 1e-12
    assert abs(narrowed["spans"][K2] - (-0.021621621640502922)) < 1e-12
