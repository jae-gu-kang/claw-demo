import pytest

from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.influence import Shape
from claw.profile import example_profile
from claw.pipeline.improve import (constrained_proposal, goal_report, margin_goals,
                                   recommend_knobs, recommended_goals)


def test_goal_report_requires_measurement_and_hard_pass():
    report = {"cases": [{"case": "A", "metrics_raw": {"alt_ts": 4}}],
              "aggregate": {"hard_fail": False}}
    assert goal_report(report, {"alt_ts": 5})["met"]
    assert not goal_report(report, {"alt_ts": 3})["met"]
    assert not goal_report(report, {"spd_ts": 5})["met"]
    assert not goal_report({"cases": []}, {})["met"]
    assert not goal_report({**report, "aborted": True}, {"alt_ts": 5})["met"]
    assert not goal_report(report, {"alt_ts": 5}, ["A", "B"])["met"]
    assert goal_report(report, {"alt_ts": 5}, ["A"])["met"]


def test_minimum_number_and_bounded_change():
    knobs = ["table.alt.kp", "table.alt.ki"]
    base = {"alt_rms": 5, "spd_rms": 1, "hdg_rms": .05, "surf_sat_frac": 0,
            "worst_stall_margin": .2, "de_dyn_reserve_min_frac": .5, "alt_ts": 10}
    rows = [{"case": "A", "label": "base", "role": "base", "overrides": {}, "metrics": base}]
    for k in knobs:
        for s in [-.2, -.1, .1, .2]:
            rows.append({"case": "A", "label": f"{k}@{s}", "role": "single", "overrides": {k: 1 + s},
                         "metrics": {**base, "alt_ts": 10 - 10 * s}})
    kw = dict(goals={"alt_ts": 7}, bounds={k: (-.2, .2) for k in knobs}, objective="min_change")
    assert not constrained_proposal(rows, knobs, GainEvalCriteria(), max_changed=1, **kw)["solvable"]
    answer = constrained_proposal(rows, knobs, GainEvalCriteria(), max_changed=2, **kw)
    assert answer["solvable"]
    assert answer["changed_count"] == 2
    assert all(abs(v) <= .2 for v in answer["spans"].values())
    kw["goals"] = {"alt_ts": 9}
    answer = constrained_proposal(rows, knobs, GainEvalCriteria(), max_changed=2, **kw)
    assert answer["changed_count"] == 1


def test_configured_limits_are_not_invented():
    goals = recommended_goals(GainEvalCriteria())
    assert goals["alt_rms"] == 10
    assert "alt_ts" not in goals


def test_margin_goals_use_measured_loops_and_higher_is_better():
    criteria = GainEvalCriteria()
    report = {"cases": [{"case": "A", "stages": {
        "margins": {"loops": {"pitch_att": {"margins": {"gm_db": 7, "pm_deg": 50}}}},
        "damping": {"zeta_sp": {"value": .4}}}}], "aggregate": {"hard_fail": False}}
    goals = margin_goals(criteria, report)
    assert goals["gm.pitch_att"] == criteria.margin.gm_good_db
    assert goals["zeta_sp"] == criteria.margin.zeta_good
    assert "gm.roll_att" not in goals
    judged = goal_report(report, goals, ["A"])
    assert not judged["met"]
    assert next(r for r in judged["rows"] if r["metric"] == "gm.pitch_att")["met"] is False
    assert next(r for r in judged["rows"] if r["metric"] == "pm.pitch_att")["met"] is True
    missing = {"cases": [{"case": "A", "stages": {"margins": {"status": "na"}}}],
               "aggregate": {"hard_fail": False}}
    unavailable = margin_goals(criteria, missing)
    assert "gm.pitch_att" in unavailable
    assert not goal_report(missing, unavailable, ["A"])["met"]


def test_failed_margin_selects_its_loop_gains():
    report = {"cases": [{"case": "A", "stages": {"margins": {"loops": {
        "pitch_att": {"margins": {"gm_db": 5}}}}},
        "attribution": {"prescriptions": [{"knobs": ["fcl/Autopilot.tau_alt"]}]}}]}
    picks, _omitted = recommend_knobs(Shape(profile=example_profile()), report,
                                      {"gm.pitch_att": 8})
    assert any("pitch" in item["knob"] for item in picks)
    assert all("목표" in item["reason"] for item in picks)
    assert not any("tau" in item["knob"] for item in picks)


def test_margin_goal_solves_in_upward_direction():
    knob = "table.pitch.kp"
    base = {"alt_rms": 5, "spd_rms": 1, "hdg_rms": .05, "surf_sat_frac": 0,
            "worst_stall_margin": .2, "de_dyn_reserve_min_frac": .5,
            "gm.pitch_att": 5}
    rows = [{"case": "A", "label": "base", "role": "base", "overrides": {}, "metrics": base}]
    for s in (-.2, -.1, .1, .2):
        rows.append({"case": "A", "label": f"{knob}@{s}", "role": "single",
                     "overrides": {knob: 1 + s},
                     "metrics": {**base, "gm.pitch_att": 5 + 20 * s}})
    found = constrained_proposal(rows, [knob], GainEvalCriteria(),
        goals={"gm.pitch_att": 8}, bounds={knob: (-.2, .2)},
        max_changed=1, objective="min_change")
    assert found["solvable"]
    assert found["spans"][knob] == pytest.approx(.15, abs=.002)
    rows[0]["metrics"].pop("gm.pitch_att")
    missing = constrained_proposal(rows, [knob], GainEvalCriteria(),
        goals={"gm.pitch_att": 8}, bounds={knob: (-.2, .2)},
        max_changed=1, objective="min_change")
    assert not missing["solvable"]
    assert "기준값이 없어" in missing["reason"]


def test_sweep_linear_measurement_is_joined_by_case_and_run(monkeypatch):
    from claw.pipeline import improve
    from types import SimpleNamespace
    runs = [SimpleNamespace(label="base"), SimpleNamespace(label="pitch@+0.1")]
    monkeypatch.setattr(improve, "plan_shapes", lambda *args: {"pitch@+0.1": object()})
    monkeypatch.setattr(improve, "evaluate", lambda *args, **kwargs: {"cases": [{
        "case": "A", "stages": {"margins": {"loops": {
            "pitch_att": {"margins": {"gm_db": 9, "pm_deg": 55}}}}}}]})
    baseline = {"cases": [{"case": "A", "stages": {"margins": {"loops": {
        "pitch_att": {"margins": {"gm_db": 7, "pm_deg": 50}}}}}}]}
    sweep = {"rows": [{"case": "A", "label": label, "metrics": {"alt_rms": 5}}
                      for label in ("base", "pitch@+0.1")]}
    improve.enrich_sweep_linear(sweep, None, {"runs": runs}, None, [], GainEvalCriteria(), baseline)
    assert [row["metrics"]["gm.pitch_att"] for row in sweep["rows"]] == [7, 9]
