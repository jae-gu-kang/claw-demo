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

    요구영역 마하 = 기체 게인 스케줄이 덮는 범위(law.schedule.mach_grid 양끝) — 설계자가 게인을 정의한
    범위이자 이 기체가 실제로 쓰는 속도대다. 절점 5개를 그 범위 양끝까지 고르게 둔다(종전 설정은 절점을
    trim_grid의 좁은 범위에서 뽑고 요구영역만 DB 밖까지 늘려, 점이 좁은 띠에 몰렸다). 고도·연료는
    trim_grid 초안에서, 경계표는 가운데 고도까지만 정의해 그 위를 요구 미정의로 남긴다. 모델 부족은
    요구영역을 비행 불가 속도까지 늘려야 생기므로 여기서 만들지 않고 단위 테스트가 확인한다.
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
        source="user(experiment)")
    model = g.ModelRange(mach=built.db_ranges()["mach"], fuel=(0.0, fuel_max))
    bps = tuple(round(m_lo + (m_hi - m_lo) * k / 4.0, 6) for k in range(5))  # 절점 5개
    return draft, region, model, bps, (a_lo, a_mid, a_hi), (f_lo, 0.5 * fuel_max, f_hi)


def design_rows(alts, fuels):
    """설계점 행 — 검증 조합과 일부러 다르게(가운데 연료·가장 높은 고도를 뺀다). 두 집합이 독립이라는 것을 보인다."""
    return tuple(alts[:-1]), (fuels[0], fuels[-1])


def trim_points(ev, region, model, design_points, recs) -> list:
    """트림점 = 트림이 필요한 조건 전부(설계점 ∪ 검증점). 같은 조건은 저장소 키가 같아 한 번만 계산된다.

    검증점은 이미 평가한 레코드의 상태를 쓰고, 설계점은 여기서 상태를 판정한다(트림 저장소 재사용)."""
    trimmed = (g.COMPUTABLE, g.CALC_FAILED, g.INFEASIBLE)  # 트림을 실제로 돌린 상태만 — 나머지는 트림점이 아니다
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
        "d": d_stats, "checks": checks, "elapsed_s": round(time.time() - t0, 1),
    }


def main():
    from claw.profile.build import build_profile
    from claw.profile.document import load_example, load_showcase

    OUT.mkdir(exist_ok=True)
    all_ok = True
    for name, loader in (("example", load_example), ("showcase", load_showcase)):
        res = experiment(name, build_profile(loader()))
        (OUT / f"{name}.json").write_text(dump(res))
        print(f"\n== {name} ({res['elapsed_s']} s, code {res['code']}) ==")
        for k, v in res["checks"].items():
            all_ok &= v["ok"]
            print(f"  [{'OK' if v['ok'] else 'NG'}] {k}: "
                  + json.dumps({kk: vv for kk, vv in v.items() if kk != "ok"}, ensure_ascii=False, default=str))
        print("  d:", json.dumps({k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in res["d"].items()},
                                 ensure_ascii=False))
    print("\n전체:", "통과" if all_ok else "실패 있음")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
