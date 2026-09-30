"""Bounded design improvement using measured sensitivities and full confirmation."""

import itertools
import math

from claw.pipeline.prescribe import (IMPROVEMENT_HIGHER_METRICS, IMPROVEMENT_LOOPS,
                                    PERF_METRICS_DEFAULT, solve_joint)
from claw.pipeline.influence import param_universe
from claw.pipeline.diagnose import _AP_AXIS
from claw.pipeline.sweep import plan_shapes
from claw.pipeline.evaluate import evaluate


def linear_metrics(case):
    stages = case.get("stages") or {}
    damping = stages.get("damping") or {}
    loops = (stages.get("margins") or {}).get("loops") or {}
    values = {}
    for name in ("zeta_sp", "zeta_dr", "roll_lambda"):
        values[name] = (damping.get(name) or {}).get("value")
    for name in IMPROVEMENT_LOOPS:
        margins = (loops.get(name) or {}).get("margins") or {}
        values[f"gm.{name}"] = margins.get("gm_db")
        values[f"pm.{name}"] = margins.get("pm_deg")
    return values


def _goal_value(case, metric):
    if metric in IMPROVEMENT_HIGHER_METRICS:
        return linear_metrics(case).get(metric)
    return (case.get("metrics_raw") or {}).get(metric)


def goal_report(report, goals, expected_cases=None):
    rows = []
    cases = report.get("cases") or []
    for metric, limit in goals.items():
        for case in cases:
            value = _goal_value(case, metric)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
            valid = value is not None and (math.isfinite(value) or
                (metric in IMPROVEMENT_HIGHER_METRICS and value == math.inf))
            rows.append({"case": case["case"], "metric": metric, "target": limit,
                         "value": value if valid else None,
                         "met": valid and (value >= limit if metric in IMPROVEMENT_HIGHER_METRICS
                                            else value <= limit)})
    complete = expected_cases is None or sorted(c["case"] for c in cases) == sorted(expected_cases)
    met = (bool(cases) and complete and all(row["met"] for row in rows)
           and not report.get("aborted") and not any(c.get("aborted") for c in cases))
    return {"met": met, "rows": rows,
            "hard_pass": (report.get("aggregate") or {}).get("hard_fail") is False}


def recommended_goals(criteria):
    """Use explicitly configured response limits; never invent recommended values."""
    out = {}
    for suffix, limits in (("rms", criteria.response.rms_max),
                           ("ts", criteria.response.ts_max), ("mp", criteria.response.mp_max)):
        for axis, value in limits.items():
            if f"{axis}_{suffix}" in PERF_METRICS_DEFAULT:
                out[f"{axis}_{suffix}"] = float(value)
    return out


def margin_goals(criteria, report):
    """Keep unmeasurable active loops visible as unmet goals, never an implicit pass."""
    cases = report.get("cases") or []
    loops = {name for case in cases
             for name in ((case.get("stages") or {}).get("margins") or {}).get("loops", {})
             if name in IMPROVEMENT_LOOPS}
    if cases and not loops:
        loops = set(IMPROVEMENT_LOOPS)
    goals = {}
    for loop in IMPROVEMENT_LOOPS:
        if loop in loops:
            goals[f"gm.{loop}"] = float(criteria.margin.gm_good_db)
            goals[f"pm.{loop}"] = float(criteria.margin.pm_min_deg)
    for metric in ("zeta_sp", "zeta_dr"):
        if cases and any("damping" in (case.get("stages") or {}) for case in cases):
            goals[metric] = float(criteria.margin.zeta_good)
    if cases and any("damping" in (case.get("stages") or {}) for case in cases):
        goals["roll_lambda"] = float(criteria.targets.roll_lambda * criteria.margin.lam_good_frac)
    return goals


def hard_margin_goals(criteria, report):
    goals = margin_goals(criteria, report)
    return {key: (float(criteria.margin.gm_min_db) if key.startswith("gm.") else
                  float(criteria.margin.zeta_min) if key in ("zeta_sp", "zeta_dr") else value)
            for key, value in goals.items() if key != "roll_lambda"}


def enrich_sweep_linear(sweep, shape, plan, aircraft, trims, criteria, baseline,
                        *, on_progress=None):
    """Measure margins and damping for the same sweep shapes without another 6DOF run."""
    shapes = plan_shapes(shape, plan)
    specs = list(plan["runs"])
    by_label = {"base": {c["case"]: c for c in baseline.get("cases", [])}}
    for index, spec in enumerate(specs):
        if spec.label == "base":
            continue
        if on_progress and on_progress(index, len(specs)):
            sweep["aborted"] = "cancelled"
            return sweep
        measured = evaluate(aircraft, trims, shapes[spec.label], criteria, depth="linear",
            on_progress=(lambda done, total, _msg: on_progress(index + done / max(total, 1), len(specs)))
            if on_progress else None)
        if measured.get("aborted"):
            sweep["aborted"] = measured["aborted"]
            return sweep
        by_label[spec.label] = {c["case"]: c for c in measured.get("cases", [])}
    for row in sweep.get("rows", []):
        case = by_label.get(row["label"], {}).get(row["case"])
        if case:
            row["metrics"].update(linear_metrics(case))
    return sweep


def recommend_knobs(shape, report, goals, limit=8):
    refs = {r.id: r for r in param_universe(shape)}
    ranked = {}

    def add(key, reason):
        if key.startswith(("table.", "fcl/ScasAxis.")):
            gain = key.rsplit(".", 1)[-1] in ("kp", "ki", "k_rate", "k_yaw")
        elif key.startswith("fcl/Autopilot."):
            gain = key.rsplit(".", 1)[-1].startswith(("kp_", "ki_", "k_"))
        else:
            gain = False
        if key in refs and gain:
            ranked.setdefault(key, reason)

    misses = [row["metric"] for row in goal_report(report, goals)["rows"] if not row["met"]]
    target_metrics = list(dict.fromkeys(misses)) or list(goals)
    for metric in target_metrics:
        if metric in IMPROVEMENT_HIGHER_METRICS:
            if metric.startswith(("gm.", "pm.")):
                loop = metric.split(".", 1)[1]
                group = loop.split("_")[0]
            else:
                group = "pitch" if metric == "zeta_sp" else "yaw" if metric == "zeta_dr" else "roll"
            if group == "spd":
                for gain in ("kp", "ki"):
                    add(f"table.spd.{gain}" if f"table.spd.{gain}" in refs else _AP_AXIS["spd"][gain],
                        f"{metric} 목표에 연결된 속도 루프")
            else:
                for gain in ("kp", "ki", "k_rate"):
                    table = f"table.{group}.{gain}"
                    add(table if table in refs else f"fcl/ScasAxis.{group}.{gain}",
                        f"{metric} 목표에 연결된 {group} 루프")
    axes = list(dict.fromkeys(key.split("_")[0] for key in target_metrics
                              if key.split("_")[0] in _AP_AXIS))
    for axis in axes:
        for gain in ("kp", "ki"):
            table = f"table.{axis}.{gain}"
            add(table if table in refs else _AP_AXIS[axis][gain], f"{axis} 목표 응답을 조절하는 {gain} 게인")
    for case in report.get("cases", []):
        for prescription in (case.get("attribution") or {}).get("prescriptions", []):
            for key in prescription.get("knobs", []):
                add(key, f"{case['case']} 평가 소견의 원인 귀속")
    for axis in axes:
        inner = "pitch" if axis == "alt" else "roll" if axis == "hdg" else None
        if inner:
            table = f"table.{inner}.kp"
            add(table if table in refs else f"fcl/ScasAxis.{inner}.kp", f"{axis} 응답의 내부 {inner} 루프")
    chosen = list(ranked)[:limit]
    return [{"knob": key, "reason": ranked[key]} for key in chosen], list(ranked)[limit:]


def constrained_proposal(rows, knobs, criteria, *, goals, bounds, max_changed, objective):
    """Enumerate permitted subsets, then solve continuous changes within each subset."""
    if not 1 <= len(knobs) <= 8 or len(set(knobs)) != len(knobs):
        raise ValueError("조정 변수는 중복 없이 1~8개여야 합니다")
    if not 1 <= max_changed <= len(knobs):
        raise ValueError("최대 변경 개수는 조정 변수 수 이하여야 합니다")
    for row in rows:
        if row.get("label") != "base":
            continue
        for metric, limit in goals.items():
            value = (row.get("metrics") or {}).get(metric)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = math.nan
            if math.isnan(value) or (not math.isfinite(value) and
                (metric not in IMPROVEMENT_HIGHER_METRICS or value != math.inf)):
                return {"solvable": False, "spans": {},
                        "reason": f"{row['case']} {metric} 기준값이 없어 변화량을 계산할 수 없습니다"}
            if value == math.inf and metric in IMPROVEMENT_HIGHER_METRICS:
                continue
    candidates = []
    for size in range(1, max_changed + 1):
        for subset in itertools.combinations(knobs, size):
            allowed = set(subset)
            limits = {k: bounds[k] if k in allowed else (0., 0.) for k in knobs}
            result = solve_joint(rows, knobs, criteria, goal_limits=goals,
                                 knob_bounds=limits, objective=objective,
                                 span_bound=max(abs(v) for b in bounds.values() for v in b))
            if result.get("solvable"):
                spans = result["spans"]
                score = (result.get("objective_value") or {}).get("predicted", 0.)
                score += sum(v * v for v in spans.values())
                candidates.append((score, result))
        if candidates and objective == "min_change":
            break
    if not candidates:
        return {"solvable": False, "spans": {}, "reason": "변경 범위·개수 안에서 목표를 만족하는 예측해가 없습니다"}
    return min(candidates, key=lambda item: item[0])[1]
