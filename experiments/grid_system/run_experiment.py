"""격자 체계 첫 실험 실행기 (05 §11.10) — 예제·쇼케이스 기체에서 확인 항목 + 부산물(d 분포).

실행: 워크트리 루트에서 `python experiments/grid_system/run_experiment.py`
산출: experiments/grid_system/out/<기체>.json (UI 프로토타입이 같은 형식을 읽는다) + 표준출력 요약.
"""

import json
import math
import pathlib
import statistics
import subprocess
import sys
import time
import warnings

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "engine"), str(HERE)]
warnings.filterwarnings("ignore")

import claw  # noqa: E402

assert str(ROOT / "engine") in claw.__file__, f"워크트리 엔진이 아니다: {claw.__file__}"

import gridsys as g  # noqa: E402

OUT = HERE / "out"


def setup(built):
    """기체마다 같은 규칙으로 실험 조건을 만든다 — 값은 기체 문서에서.

    **실험 영역**의 마하를 기존 게인 스케줄 범위(law.schedule.mach_grid 양끝)에 맞춘다 — 점 밀집의 원인
    (절점을 좁은 범위에서 뽑은 설정)을 확인하려는 실험 설정이다. 요구 운용영역의 정의가 아니다: 요구
    영역은 성능을 확보해야 할 범위이고, 게인 스케줄은 그것을 지원하도록 설계하는 쪽이라 관계가 반대다.
    이 범위 전체가 모든 고도·연료에서 비행 가능하다는 뜻도 아니다. 절점 5개를 그 범위 양끝까지 고르게
    둔다. 고도·연료는 trim_grid 초안에서, 경계표는 가운데 고도까지만 정의해 그 위를 요구 미정의로
    남긴다. 모델 부족은 실제 기체 데이터와 구분한 합성 시험 데이터(synthetic_limited_model)가 맡는다.
    """
    draft = g.region_draft_from_trim_grid(built.doc["mission_template"]["trim_grid"])
    fuel_max = built.aircraft().fuel_mass.fuel_max
    mg = built.doc["law"]["schedule"]["mach_grid"]
    m_lo, m_hi = float(mg[0]), float(mg[-1])
    a_lo, a_hi = draft.alt
    a_mid = float(round((a_lo + a_hi) / 2.0))
    f_lo, f_hi = 0.2 * fuel_max, fuel_max
    region = g.Region(
        mach=(m_lo, m_hi), alt=(a_lo, a_hi), fuel=(f_lo, f_hi),
        boundary={f_lo: [(a_lo, m_lo, m_hi), (a_mid, m_lo * 1.1, m_hi)],
                  f_hi: [(a_lo, m_lo * 1.1, m_hi), (a_mid, m_lo * 1.2, m_hi)]},
        source="experiment:schedule_range")
    model = g.ModelRange(mach=built.db_ranges()["mach"], fuel=(0.0, fuel_max))
    bps = tuple(round(m_lo + (m_hi - m_lo) * k / 4.0, 6) for k in range(5))  # 절점 5개
    return draft, region, model, bps, (a_lo, a_mid, a_hi), (f_lo, 0.5 * fuel_max, f_hi)


def synthetic_limited_model(region, model):
    """**합성 시험 데이터** — 요구영역은 그대로 두고 제공 모델의 마하 범위만 요구영역 안쪽 80 %까지로
    줄인다. 모델 부족 상태를 종단 간(생성 → 상태 → 요약)으로 확인하려는 것이고, 실제 기체 데이터가 아니다."""
    hi = region.mach[0] + 0.8 * (region.mach[1] - region.mach[0])
    return g.ModelRange(mach=(model.mach[0], hi), fuel=model.fuel, source="synthetic:model_mach_limited_80pct")


def design_rows(alts, fuels):
    """설계점 행 — 이 실험에서는 검증 조합과 다르게 둬 **따로 지정할 수 있음**을 보인다. 반드시 달라야 하는
    것은 아니다 — 실제 검증에는 설계점도 포함할 수 있고, 같은 조건은 트림을 한 번만 계산한다."""
    return tuple(alts[:-1]), (fuels[0], fuels[-1])


def trim_points(ev, region, model, design_points, recs) -> list:
    """트림 시도점 = 트림을 시도한 조건 전부(설계점 ∪ 검증점, 성공·실패 모두). 같은 조건은 저장소 키가
    같아 한 번만 계산된다 — 개수는 **고유 조건 수**이고, 계산 시도 횟수는 저장소가 따로 센다.

    검증점은 이미 평가한 레코드의 상태를 쓰고, 설계점은 여기서 상태를 판정한다(트림 저장소 재사용)."""
    trimmed = (g.COMPUTABLE, g.CALC_FAILED, g.CONSTRAINT_HIT, g.INFEASIBLE)  # 트림을 실제로 시도한 상태만
    out: dict = {}
    for d in design_points:
        st, _, why = ev.state(d.cond, region, model)
        if st in trimmed:
            out[d.cond.name] = {"name": d.cond.name, "cond": d.cond, "state": st, "reasons": why,
                                "used_by": ["design"]}
    for r in recs:
        if r["state"] not in trimmed:
            continue
        t = out.setdefault(r["name"], {"name": r["name"], "cond": r["cond"], "state": r["state"],
                                       "reasons": r["reasons"], "used_by": []})
        if "validation" not in t["used_by"]:
            t["used_by"].append("validation")
    return list(out.values())


# 보강 비교용 잠정 예산·허용치 — 허용치는 05 §11.7 [TBD]라 **두 규칙에 똑같이** 쓰는 비교 전용 값이다
REINFORCE_TOL = 0.25
REINFORCE_MAX_POINTS = 24
REINFORCE_MAX_DEPTH = 3


def d_scales_legacy_target_based(crit) -> dict:
    """**이전 규칙(v1.59, 폐기)** — 척도를 튜닝 목표에서 끌어왔다. 변경 전후 비교에만 쓴다 (05 §11.7 v1.60)."""
    m, t = crit.margin, crit.targets
    return {"pitch_rate": t.zeta_sp - m.zeta_min, "yaw_rate": t.zeta_dr - m.zeta_min,
            "roll_rate": t.roll_lambda * (m.lam_good_frac - m.lam_min_frac),
            "pitch_att": t.pm_deg - m.pm_min_deg, "roll_att": t.pm_deg - m.pm_min_deg}


def compare_reinforce(before, after) -> dict:
    """두 보강 결과 비교 — 추가점(개수·한쪽에만 있는 점) · 보강 순서(처음 갈린 위치) · 종료 상태."""
    nb = [a["cond"].name for a in before["added"]]
    na = [a["cond"].name for a in after["added"]]
    first = next((i for i, (x, y) in enumerate(zip(nb, na)) if x != y), None)
    if first is None and len(nb) != len(na):
        first = min(len(nb), len(na))
    return {
        "added": {"before": len(nb), "after": len(na), "only_before": [n for n in nb if n not in set(na)],
                  "only_after": [n for n in na if n not in set(nb)]},
        "first_order_difference": first,
        "status": {"before": before["status"], "after": after["status"]},
        "remaining": {"before": len(before["remaining"]), "after": len(after["remaining"])},
    }


def make_measure(ev, region, model, schedule):
    tables = schedule.tables()

    def measure(c):
        st, rec, _ = ev.state(c, region, model)
        return ev.judge(c, rec, schedule, tables)[1] if st == g.COMPUTABLE else None

    return measure


def run_reinforce(ev, region, model, schedule, rows, union, scales, tol=None, max_points=None):
    measure = make_measure(ev, region, model, schedule)
    return g.reinforce(measure, rows, union, scales, tol=REINFORCE_TOL if tol is None else tol,
                       max_points=REINFORCE_MAX_POINTS if max_points is None else max_points,
                       max_depth=REINFORCE_MAX_DEPTH)


def reinforce_json(r) -> dict:
    return {**r, "added": [{**a, "cond": {"mach": a["cond"].mach, "alt": a["cond"].alt, "fuel": a["cond"].fuel},
                             "name": a["cond"].name} for a in r["added"]]}


def run_case(built, store, region, model, schedule, spec):
    ev = g.Evaluator(built, store)
    val = g.generate_validation(region, schedule, spec)
    return ev, val, g.evaluate(ev, region, model, schedule, val["points"])


def _finite(x):
    """비유한값(inf·nan)은 null — 브라우저 JSON.parse가 Infinity/NaN을 못 읽고, 0으로 바꾸면 판정 불가가 숫자로 둔갑한다."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    return x


def dump(obj) -> str:
    return json.dumps(_finite(json.loads(json.dumps(obj, default=str))), ensure_ascii=False, indent=1,
                      allow_nan=False)


def base_refine(built, *, n_mach=9, budget=REINFORCE_MAX_POINTS, common_axis=False) -> dict:
    """기본 모델 격자 + 역할별 선택 + 보강 (05 §11.11) — 재사용·추가 트림·보강 사유를 잰다.

    1) 기본 격자(행별 등간격)를 먼저 트림하고 품질 관문(인접 플랜트 거리)을 거친다. 2) 역할별 선택 —
    절점은 기본 격자 마하에서 한 칸 건너, 설계점은 기본 격자의 계산 완료 점. 3) 검증점을 만들어 평가 —
    기본 격자에서 재사용된 점과 새로 트림한 점을 센다. 4) 보강 — 지표 비선형(d > 허용치) · 판정 변화 ·
    트림 실패 경계, 사유를 점마다 남긴다. 예산은 사유별로 같은 값(budget)을 실행 전에 준다.
    """
    from claw.design.orchestrator import AutoDesignConfig

    _, region, model, _, alts, fuels = setup(built)
    names = tuple(built.doc["law"]["schedule"]["scheduled"])
    store = g.TrimStore()
    ev = g.Evaluator(built, store)
    base_alts = tuple(alts[:-1])  # 가장 높은 고도는 이 실험의 요구 미정의 행
    base = g.base_grid(region, alts=base_alts, fuels=fuels, n_mach=n_mach, common_axis=common_axis)
    by_row: dict = {}
    for b in base:
        st, rec, why = ev.state(b["cond"], region, model)
        b.update(state=st, rec=rec, reasons=why, row=(b["cond"].alt, b["cond"].fuel))
        by_row.setdefault(b["row"], []).append(b)
    base_trims, base_keys = store.attempts, set(store._d)
    quality = g.quality_warnings(ev, by_row, tol_plant=AutoDesignConfig().refine_tol)

    # 역할별 선택 — 절점은 기준 행(가장 낮은 고도·가운데 연료)의 기본 격자 마하에서 한 칸 건너
    ref = sorted(p["cond"].mach for p in by_row[(base_alts[0], fuels[1])])
    bps = tuple(ref[::2]) if len(ref[::2]) >= 2 else tuple(ref)
    sch = g.sample_schedule(built, {"A": g.BreakpointSet("A", "mach", bps)}, {n: "A" for n in names})
    design = [b for b in base if b["state"] == g.COMPUTABLE]

    spec = g.ValidationSpec(alts=base_alts, fuels=fuels)
    val = g.generate_validation(region, sch, spec)
    a0, h0 = store.attempts, store.reused
    recs = g.evaluate(ev, region, model, sch, val["points"])
    role_new, role_hits = store.attempts - a0, store.reused - h0

    # 보강
    a1 = store.attempts
    rows_v = [(float(a), float(f)) for f in fuels for a in base_alts]
    re_ = run_reinforce(ev, region, model, sch, rows_v, sch.union_coords(), g.d_scales(ev.criteria), max_points=budget)
    added = [{"cond": x["cond"], "row": x["row"], "reason": g.R_NONLINEAR_METRIC, "slot": x["slot"]}
             for x in re_["added"]]
    extra = g.verdict_change_points(recs, max_points=budget) + g.trim_boundary_points(recs, max_points=budget)
    for p in extra:
        ev.state(p["cond"], region, model)
    added += [{"cond": p["cond"], "row": p["row"], "reason": p["reason"]} for p in extra]
    refine_new = store.attempts - a1

    new_keys = set(store._d) - base_keys
    new_fail = sum(1 for k in new_keys if ev.state(g.Condition(*_cond_of(store._d[k]["tr"])), region, model)[0]
                   != g.COMPUTABLE)
    reasons: dict = {}
    for a in added:
        reasons[a["reason"]] = reasons.get(a["reason"], 0) + 1
    tried = role_new + role_hits
    metrics = {
        "base_points": len(base), "base_trims": base_trims,
        "quality_dense_pairs": len(quality["dense"]), "quality_anomalies": len(quality["anomaly"]),
        "quality_unjudged_rows": len(quality["unjudged_rows"]),
        "breakpoints": len(bps), "design_points": len(design), "validation_points": len(recs),
        "role_new_trims": role_new, "role_reused": role_hits,
        "base_reuse_ratio": role_hits / tried if tried else 0.0,
        "refine_new_trims": refine_new, "additional_trims": role_new + refine_new,
        "additional_trim_failures": new_fail, "interpolation": g.interpolation_share(recs, sch.union_coords()),
        "refinement_reasons": reasons, "reinforce_status": re_["status"],
        "reinforce_unmeasured": len(re_["unmeasured"]),
        "unique_conditions": store.unique_conditions, "attempts": store.attempts,
    }
    return {"metrics": metrics, "bps": bps, "quality": quality,
            "added": [{"mach": a["cond"].mach, "alt": a["cond"].alt, "fuel": a["cond"].fuel,
                       "reason": a["reason"], **({"slot": a["slot"]} if "slot" in a else {})} for a in added],
            "base": [{"mach": b["cond"].mach, "alt": b["cond"].alt, "fuel": b["cond"].fuel, "state": b["state"]}
                     for b in base]}


def _cond_of(tr):
    c = tr.case
    return c.mach, c.alt, c.fuel


def jsonable(recs):
    out = []
    for r in recs:
        x = {k: v for k, v in r.items() if k != "cond"}
        x["cond"] = {"mach": r["cond"].mach, "alt": r["cond"].alt, "fuel": r["cond"].fuel}
        x["row"] = list(r["row"]) if r["row"] is not None else None
        out.append(x)
    return out


def experiment(name, built):
    t0 = time.time()
    draft, region, model, bps, alts, fuels = setup(built)
    names = tuple(built.doc["law"]["schedule"]["scheduled"])
    checks = {}

    # ① 설계점·절점 분리 — 설계점 수를 바꿔도 절점은 그대로이고, 설계점의 절점 구간 연결은 저장 없이
    # 절점에서 계산된다. 표 값이 설계점과 무관한 것은 샘플 표라 구성상 참이다(튜닝 연결은 이관 과제)
    bset = {"A": g.BreakpointSet("A", "mach", bps)}
    d_alts, d_fuels = design_rows(alts, fuels)
    few = g.auto_design_points(region, n_mach=3, alts=d_alts, fuels=d_fuels)
    dps = g.auto_design_points(region, n_mach=7, alts=d_alts, fuels=d_fuels)
    sch1 = g.sample_schedule(built, bset, {n: "A" for n in names})
    links = g.design_links(dps, bps)
    moved_links = g.design_links(dps, (bps[0], bps[-1]))
    checks["separation"] = {
        "design_points": [len(few), len(dps)], "breakpoints": len(bps), "links": links,
        "links_two_breakpoints": moved_links,
        "note": "표 값의 설계점 무관성은 샘플 표라 구성상 참 — 확인 대상은 절점 불변·연결 파생",
        "ok": all(tuple(t.axes[0]) == bps for t in sch1.tables().values())
        and sum(links.values()) == sum(moved_links.values()) == len(dps),
    }

    # ② 표별 절점 — roll.k_rate만 독립 절점(가운데 두 절점을 다르게)으로 분리
    b_coords = (bps[0], round((bps[0] + bps[1]) / 2, 6), round((bps[2] + bps[3]) / 2, 6), bps[3])
    bset2 = {**bset, "B": g.BreakpointSet("B", "mach", b_coords)}
    sch2 = g.sample_schedule(built, bset2, {n: ("B" if n == "roll.k_rate" else "A") for n in names})
    union = sch2.union_coords()
    checks["per_table"] = {
        "union": union, "independent": [k for k, v in sch2.sharing().items() if v == "independent"],
        "ok": set(union) == set(bps) | set(b_coords) and sch2.sharing()["roll.k_rate"] == "independent",
    }

    # ③ 검증조건 생성 — 중간 마하 × 별도 지정한 고도·연료 조합
    store = g.TrimStore()
    spec = g.ValidationSpec(alts=alts, fuels=fuels, n_between=1)
    ev, val, recs = run_case(built, store, region, model, sch2, spec)
    mids = [p for p in val["points"] if p.kind == "midpoint"]
    want_rows = {(float(a), float(f)) for f in fuels for a in alts}
    checks["validation_rows"] = {
        "rows": len(want_rows), "midpoints": len(mids), "intervals": len(union) - 1,
        "ok": {p.row for p in mids} == want_rows and len(mids) == (len(union) - 1) * len(want_rows),
    }

    tps = trim_points(ev, region, model, dps, recs)
    trim_counts = {"unique_conditions": store.unique_conditions, "attempts": store.attempts, "reused": store.reused}

    # ⑦ 모델 부족 종단 간 — 합성 시험 데이터(요구영역 그대로, 모델 마하 범위만 줄임). 실제 기체와 구분
    syn = synthetic_limited_model(region, model)
    ev_syn = g.Evaluator(built, g.TrimStore())
    val_syn = g.generate_validation(region, sch2, spec)
    recs_syn = g.evaluate(ev_syn, region, syn, sch2, val_syn["points"])
    gap = [r for r in recs_syn if r["state"] == g.MODEL_GAP]
    trimmed_names = {k[1] for k in ev_syn.store._d}
    summ_syn = g.summarize(recs_syn, union)
    checks["model_gap_e2e"] = {
        "data": syn.source, "model_mach": syn.mach, "region_mach": region.mach,
        "model_gap": len(gap), "gap_trimmed": sum(r["name"] in trimmed_names for r in gap),
        "candidates": [len(recs), len(recs_syn)],
        "ok": bool(gap) and not any(r["name"] in trimmed_names for r in gap) and len(recs_syn) == len(recs)
        and sum(c["n"] for c in summ_syn["cells"].values()) + summ_syn["out_of_region"] == len(recs_syn),
    }

    # ④ 누락 방지 — 상태 합 = 후보 수, 요약 분모 + 영역 밖 = 후보 수
    by_state = {}
    for r in recs:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    summ = g.summarize(recs, union)
    in_cells = sum(c["n"] for c in summ["cells"].values())
    checks["no_omission"] = {
        "candidates": len(recs), "by_state": {g.STATE_LABEL[k]: v for k, v in by_state.items()},
        "summary_denominator": in_cells, "out_of_region": summ["out_of_region"],
        "ok": sum(by_state.values()) == len(recs) and in_cells + summ["out_of_region"] == len(recs),
    }

    # ⑤ 스케줄 게인 사용 — 계산 완료 점마다 게인 = 자기 표 평가값 (비트 일치)
    tabs2 = sch2.tables()
    done = [r for r in recs if r["state"] == g.COMPUTABLE]
    mism = [r["name"] for r in done for n, t in tabs2.items() if r["gains"][n] != t.interp(mach=r["cond"].mach)]
    checks["scheduled_gains"] = {"checked": len(done), "mismatch": mism, "ok": bool(done) and not mism}

    # ⑥ 계산 재사용 — 절점 하나를 옮겨 다시 돌리면 새 좌표만 트림한다
    moved = list(bps)
    moved[1] = round(moved[1] + (moved[2] - moved[1]) * 0.25, 6)
    sch3 = g.sample_schedule(built, {"A": g.BreakpointSet("A", "mach", tuple(moved)), "B": bset2["B"]},
                             sch2.refs)
    known = {k[1] for k in store._d}
    before, reused_before = store.computed, store.reused
    _, _, recs3 = run_case(built, store, region, model, sch3, g.ValidationSpec(alts=alts, fuels=fuels))
    need = {r["name"] for r in recs3
            if region.classify(r["cond"]) is None and model.covers(r["cond"]) and r["name"] not in known}
    checks["reuse"] = {
        "trims_first_run": before, "new_trims_second_run": store.computed - before,
        "expected_new": len(need), "reused_second_run": store.reused - reused_before,
        "ok": store.computed - before == len(need) and store.reused > reused_before,
    }

    # 보강 — 새 규칙(튜닝 목표 독립 척도)과 이전 규칙을 같은 설정·같은 잠정 허용치로 (05 §11.7 v1.60)
    rows_v = [(float(a), float(f)) for f in fuels for a in alts]
    re_new = run_reinforce(ev, region, model, sch2, rows_v, union, g.d_scales(ev.criteria))
    re_old = run_reinforce(ev, region, model, sch2, rows_v, union, d_scales_legacy_target_based(ev.criteria))
    reinforce_cmp = compare_reinforce(re_old, re_new)
    # 허용치 민감도 — 허용치는 [TBD]라, 규칙 차이가 어느 허용치부터 드러나는지 본다
    tol_sweep = {}
    for tol in (0.25, 0.1, 0.05):
        a = run_reinforce(ev, region, model, sch2, rows_v, union, d_scales_legacy_target_based(ev.criteria), tol)
        b = run_reinforce(ev, region, model, sch2, rows_v, union, g.d_scales(ev.criteria), tol)
        cnt = lambda r: {s: sum(x["slot"] == s for x in r["added"]) for s in sorted({x["slot"] for x in r["added"]})}  # noqa: E731
        # 처음 구간(절점 합집합의 인접쌍) 중 허용치를 넘는 것 — 자리별. 예산에 가려 순서에 안 드러난 차이를 본다
        over = lambda sc: {sl: sum(1 for x in g.d_values(recs, union, sc) if x["slot"] == sl and x["d"] > tol)  # noqa: E731
                           for sl in sorted(sc)}
        tol_sweep[str(tol)] = {**compare_reinforce(a, b), "slots_before": cnt(a), "slots_after": cnt(b),
                               "initial_over_before": over(d_scales_legacy_target_based(ev.criteria)),
                               "initial_over_after": over(g.d_scales(ev.criteria))}

    # 구간 세분화 — 기체·게인 표·고도·연료·척도를 고정하고 같은 구간을 1·2·4등분(재튜닝 없음). 점 간격만의
    # 효과를 분리한다 — 절점 배치를 바꾼 전후 비교는 범위·위치·검사 조건까지 함께 바뀌어 간격 효과로 못 읽는다
    subdiv = g.subdivision_d(make_measure(ev, region, model, sch2), rows_v, union, g.d_scales(ev.criteria),
                             levels=(1, 2, 4))

    # 부산물 — 보강 지표 d 분포 (허용치 보정 자료, 05 §11.7)
    ds = g.d_values(recs, union, g.d_scales(ev.criteria))
    d_stats = {}
    for slot in sorted({d["slot"] for d in ds}):
        v = sorted(d["d"] for d in ds if d["slot"] == slot)
        d_stats[slot] = {"n": len(v), "median": statistics.median(v), "p90": v[int(0.9 * (len(v) - 1))],
                         "max": v[-1]}

    return {
        "aircraft": name, "fingerprint": built.fingerprint, "plant_fingerprint": built.plant_fingerprint,
        "criteria_source": built.criteria_source,
        "pass_lines": {"pm_deg": ev.criteria.margin.pm_min_deg, "gm_db": ev.criteria.margin.gm_min_db},
        "code": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True).stdout.strip(),
        "region": {"mach": region.mach, "alt": region.alt, "fuel": region.fuel,
                   "boundary": {str(k): v for k, v in (region.boundary or {}).items()}, "source": region.source,
                   "draft": {"mach": draft.mach, "alt": draft.alt, "fuel": draft.fuel,
                             "confirmed": draft.confirmed}},
        "model": {"mach": model.mach, "fuel": model.fuel},
        "design_points": [{"mach": d.cond.mach, "alt": d.cond.alt, "fuel": d.cond.fuel, "origin": d.origin}
                          for d in dps],
        "schedule": {"bp_sets": {k: {"axis": v.axis, "coords": v.coords} for k, v in sch2.bp_sets.items()},
                     "refs": sch2.refs, "sharing": sch2.sharing(), "values": sch2.values},
        "validation": {"alts": alts, "fuels": fuels, "mode": spec.mode, "omitted": val["omitted"],
                       "union": union},
        "records": jsonable(recs),
        "trim_points": jsonable([{**t, "row": None} for t in tps]),
        "summary": {"columns": summ["columns"], "out_of_region": summ["out_of_region"],
                    "cells": [{"row": list(k[0]) if isinstance(k[0], tuple) else k[0], "col": k[1], **c}
                              for k, c in summ["cells"].items()]},
        "d": d_stats, "checks": checks, "trim_counts": trim_counts, "subdivision_d": subdiv,
        "d_scales": {k: {"value": v, "source": g.d_scale_sources(ev.criteria)[k]}
                     for k, v in g.d_scales(ev.criteria).items()},
        "d_scales_legacy": d_scales_legacy_target_based(ev.criteria),
        "reinforce": {"rule_v1_60": reinforce_json(re_new), "legacy_v1_59": reinforce_json(re_old),
                      "comparison": reinforce_cmp, "tol_sweep": tol_sweep}, "elapsed_s": round(time.time() - t0, 1),
    }


def main():
    from claw.profile.build import build_profile
    from claw.profile.document import load_example, load_showcase

    OUT.mkdir(exist_ok=True)
    all_ok = True
    for name, loader in (("example", load_example), ("showcase", load_showcase)):
        built = build_profile(loader())
        res = experiment(name, built)
        br = base_refine(built)
        (OUT / f"{name}_base_refine.json").write_text(dump(br))
        brc = base_refine(built, common_axis=True)
        (OUT / f"{name}_base_refine_common_axis.json").write_text(dump(brc))
        (OUT / f"{name}.json").write_text(dump(res))
        print(f"\n== {name} ({res['elapsed_s']} s, code {res['code']}) ==")
        for k, v in res["checks"].items():
            all_ok &= v["ok"]
            print(f"  [{'OK' if v['ok'] else 'NG'}] {k}: "
                  + json.dumps({kk: vv for kk, vv in v.items() if kk != "ok"}, ensure_ascii=False, default=str))
        for tag, x in (("행별 축", br), ("공통 축", brc)):
            mm = x["metrics"]
            print(f"  기본 격자 + 보강 [{tag}]: 기본 {mm['base_points']} · 재사용률 {mm['base_reuse_ratio']:.2f} "
                  f"(역할 새 트림 {mm['role_new_trims']} / 재사용 {mm['role_reused']}) · 보강 새 트림 {mm['refine_new_trims']} "
                  f"· 추가 트림 {mm['additional_trims']}(실패 {mm['additional_trim_failures']}) · 설계점 {mm['design_points']} "
                  f"· 검증점 {mm['validation_points']} · 보간 {mm['interpolation']} · 사유 {mm['refinement_reasons']} "
                  f"· 조밀화 {mm['quality_dense_pairs']}/이상 {mm['quality_anomalies']} · 보강 {mm['reinforce_status']}")
        print("  트림 시도점:", json.dumps(res["trim_counts"], ensure_ascii=False))
        print("  구간 세분화 d(최대, 1·2·4등분):", json.dumps({k: {kk: round(vv, 3) for kk, vv in v.items()}
                                                          for k, v in res["subdivision_d"].items()}))
        rc = res["reinforce"]["comparison"]
        print("  보강 비교(이전 → 새):", json.dumps({"추가점": [rc["added"]["before"], rc["added"]["after"]],
              "처음 갈린 순서": rc["first_order_difference"], "종료": [rc["status"]["before"], rc["status"]["after"]],
              "남은 구간": [rc["remaining"]["before"], rc["remaining"]["after"]]}, ensure_ascii=False))
        for tol, v in res["reinforce"]["tol_sweep"].items():
            print(f"   tol {tol}: 추가점 {v['added']['before']}→{v['added']['after']} · 처음 갈린 순서 "
                  f"{v['first_order_difference']} · 종료 {v['status']['before']}→{v['status']['after']} · "
                  f"자리별 {v['slots_before']}→{v['slots_after']}")
            print(f"      처음 구간 중 허용치 초과(자리별): {v['initial_over_before']} → {v['initial_over_after']}")
        print("  d:", json.dumps({k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in res["d"].items()},
                                 ensure_ascii=False))
    print("\n전체:", "통과" if all_ok else "실패 있음")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
