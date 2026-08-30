"""마진 부족 원인 분류기 — 4-verdict, 판정마다 수치 evidence 동반 (diagnose.py Finding 관례).

마진이 부족할 때 "breakpoint만 추가"가 아니라 **원인별로 다른 처방**을 낸다
(사용자 요구의 핵심). 실패 검증점 v·자리에 대해 순서대로:

1. structural_limit — v에서 튜너(tune_point — 자유 게인 국소 최적)를 돌려도
   infeasible이거나 최적 게인의 판정이 fail → 게인·breakpoint로는 불가.
   action=escalate (**보고 전용** — 필터·작동기 대역폭·지연 예산 등 상위 설계
   변경은 어느 모드에서도 자동 적용하지 않는다). evidence로 교차 주파수 vs
   작동기 대역폭 비·지연 위상 기여에 더해 **완화 프로브**(_relief_probes —
   지연·작동기 대역폭을 하나씩 풀어 재튜닝)를 동봉한다: 자동 적용은 안 해도
   "무엇을 바꾸면 통과하는가"까지는 기계가 답해야 사람이 판단할 수 있다.
2. plant_variation — v를 낀 인접 앵커 간 model_distance.d_total > tol_plant
   (refine tol과 **같은 상수** — 기준 이원화 금지) → 트림 격자가 플랜트 변화를
   못 담는 것. action=promote v→anchor (검증 시 트림·선형화는 이미 완료 — 역할
   승격 후 TUNE부터 재실행). valley도 동시 성립하면 anchor가 상위 집합 처방이라
   이쪽을 택하고 note로 병기.
3. gain_interp_valley — 최적 게인은 통과 ∧ 보간 게인과의 괴리 > tol_gain ∧ 이웃
   breakpoint 자체는 통과 → 보간이 범인. action=promote v→breakpoint (최적
   게인을 그 점의 값으로) + FIT 국소 재실행.
4. simple_deficit — 나머지. 미달 폭이 히스테리시스 밴드 내면 좁은 골 가능성 —
   action=add_validation (v 좌우 중점 2개). 지속·확대되면 다음 이터레이션에서
   1~3으로 자연 재분류된다.
"""

import math

from claw.design.linmodels import model_distance
from claw.design.points import ROLE_ANCHOR, ROLE_BREAKPOINT, ROLE_RANK
from claw.design.schedmap import scheduled_gains
from claw.design.tune import TuneTargets, tune_point

VERDICTS = ("simple_deficit", "plant_variation", "gain_interp_valley", "structural_limit",
            "gain_sign_flip")

# 자리(루프) → 관련 게인 슬롯 — valley 괴리·breakpoint 승격 값의 대상
LOOP_SLOTS = {
    "pitch_att": ("pitch.kp", "pitch.ki"),
    "pitch_rate": ("pitch.k_rate",),
    "roll_att": ("roll.kp", "roll.ki"),
    "roll_rate": ("roll.k_rate",),
    "yaw_rate": ("yaw.k_rate",),
}
_EPS = 1e-12
# 구조 한계 완화 프로브의 작동기 대역폭 배수. 데모 30 rad/s → 90 rad/s로, docs -01 §7
# 백로그가 적어 둔 소멸 경계(wn ≥ 50 rad/s)를 넘는 값이라 "대역폭이 병목인가"에 답한다.
_RELIEF_ACT_FACTOR = 3.0


def _relief_probes(lm, design, loop_name, *, targets, criteria, act_kw) -> list:
    """지연·작동기 대역폭을 하나씩만 완화해 재튜닝 — 병목 지목의 실측 근거.

    structural_limit는 "게인으로는 안 된다"까지만 말한다. 그다음 질문인 "그럼 무엇을
    바꾸나"는 상위 설계 결정이라 자동 적용하지 않지만, **판단 재료는 기계가 낼 수
    있다**. 종전 evidence는 ωc/작동기 비와 지연 위상 두 수치뿐이었는데 그 둘은 같이
    커지므로(둘 다 ωc에 비례) 어느 쪽이 병목인지 화면에서 읽어낼 수 없었다.
    프로브는 한 번에 하나씩만 바꿔 돌려 인과를 분리한다.

    비용은 구조 한계로 판정된 (점, 자리)당 튜닝 2회 추가다 — 그 판정 자체가 이미
    자유 게인 튜닝 1회를 돌린 뒤이고, 구조 한계는 드물어 전체 실행에는 거의 영향이 없다.
    """
    act_wn = float(act_kw.get("actuator_wn") or 0.0)
    delay = float(act_kw.get("delay_s") or 0.0)
    plan = []
    if delay > 0.0:  # 이미 0이면 "지연을 빼 보라"가 답이 될 수 없다
        plan.append(("delay_s", 0.0, "지연 제거"))
    if act_wn > 0.0:
        plan.append(("actuator_wn", act_wn * _RELIEF_ACT_FACTOR,
                     f"작동기 대역폭 ×{_RELIEF_ACT_FACTOR:g}"))
    probes = []
    for key, to_value, label in plan:
        kw = dict(act_kw)
        kw[key] = to_value
        out = tune_point(lm, design, targets=targets, **kw)
        judged = _tuned_judgement(out, loop_name, criteria)
        probes.append({
            "change": key, "label": label, "from": act_kw.get(key), "to": to_value,
            "status": out["status"], "judged": judged,
            # 구조 한계 판정 조건(infeasible ∨ fail)이 더 이상 성립하지 않으면 해소다 —
            # 판정과 같은 식을 부정해 쓴다 (두 곳이 갈리면 프로브가 거짓 안도를 준다)
            "resolves": out["status"] != "infeasible" and judged != "fail",
        })
    return probes


def _tuned_judgement(tune_out, loop_name, criteria) -> str:
    """v에서의 자유 게인 최적 결과 판정 — 자리 종류에 맞는 자로 잰다."""
    ach = tune_out["achieved"].get(loop_name)
    if ach is None:
        return "na"
    if loop_name.endswith("_att"):
        if "pm_deg" not in ach:
            return "na"
        return criteria.judge(ach)
    key = "zeta_sp" if loop_name == "pitch_rate" else "zeta_dr"
    if key not in ach:
        return "na"
    return criteria.judge_damping(ach[key])


def classify_margin_deficit(
    aircraft, v_name, loop_name, points, lms, trims, tables, design, margin_cases, *,
    criteria, targets=None, tol_plant=0.25, tol_gain=0.10,
    hysteresis_pm=5.0, hysteresis_zeta=0.10,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
) -> dict:
    """실패 (검증점, 자리) 하나의 원인 분류 — {"verdict", "action", "evidence"}."""
    targets = targets if targets is not None else TuneTargets()
    tr = trims[v_name]
    lm = lms.get(aircraft, tr)
    entry = margin_cases[v_name]["loops"][loop_name]
    evidence: dict = {"current": {k: entry.get(k) for k in
                                  ("pm_deg", "gm_db", "zeta", "wc_att", "status")}}

    # 0) 부호 뒤집힘 — 원인이 이미 확정된 경우다. 격자도 보간 valley도 아니고
    #    **적합이 설계 부호를 넘긴 것**이라, 앵커를 늘려도 다항이 다시 0을 가로지른다
    #    (실제로 겪었다: roll.ki 승격 처방을 반영해도 실패가 그대로였다).
    #    적합 단계의 부호 가드(fit._fit_preserving_sign)가 먼저 막지만, 상수 폴백까지
    #    실패했거나 API로 직접 주입된 다항이면 여기로 온다
    if entry.get("sign_flip"):
        tune_out = tune_point(
            lm, design, targets=targets,
            actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
            delay_s=delay_s, pade_order=pade_order,
        )
        slots = LOOP_SLOTS.get(loop_name, ())
        evidence["sign_flip"] = {
            "slots": entry["sign_flip"],
            "effective": {s: eff for s, eff in (entry.get("gains") or {}).items()},
            "design": {s: design.get(s) for s in slots},
        }
        return {
            "verdict": "gain_sign_flip",
            "action": {
                "type": "refit_at", "point": v_name,
                "gains": {s: tune_out["gains"][s] for s in slots if s in tune_out["gains"]},
                "note": "부호를 지키도록 그 점을 고정해 재적합 — 승격으로는 해결되지 않는다",
            },
            "evidence": evidence,
        }

    # 1) 자유 게인 국소 최적 — structural_limit 판별의 근거
    tune_out = tune_point(
        lm, design, targets=targets,
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )
    tuned_status = _tuned_judgement(tune_out, loop_name, criteria)
    evidence["tuned"] = {
        "status": tune_out["status"], "judged": tuned_status,
        "achieved": tune_out["achieved"].get(loop_name), "notes": tune_out["notes"],
    }
    if tune_out["status"] == "infeasible" or tuned_status == "fail":
        wcp = (entry.get("wcp") or entry.get("wc") or 0.0)
        relief = _relief_probes(
            lm, design, loop_name, targets=targets, criteria=criteria,
            act_kw=dict(actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
                        delay_s=delay_s, pade_order=pade_order),
        )
        resolved = [p["label"] for p in relief if p["resolves"]]
        evidence["bottleneck"] = {
            "wc_over_actuator": (wcp / actuator_wn) if actuator_wn else None,
            "delay_phase_deg_at_wc": math.degrees(wcp * delay_s),
            "relief": relief,
            "resolved_by": resolved,
            "note": "자유 게인으로도 기준 미달 — " + (
                f"{' / '.join(resolved)} 시 통과: 병목은 게인이 아니라 이 예산이다"
                if resolved else
                "지연·작동기 대역폭을 완화해도 통과하지 못한다 — 플랜트·루프 구조 자체를 검토"
            ),
        }
        return {
            "verdict": "structural_limit",
            "action": {"type": "escalate", "point": v_name, "loop": loop_name},
            "evidence": evidence,
        }

    # 관련 슬롯의 보간 게인 vs 최적 게인 괴리 (valley 판별 재료)
    g_interp = scheduled_gains(tables, design, trims[v_name].case)
    slots = LOOP_SLOTS.get(loop_name, ())
    gaps = {}
    for slot in slots:
        go = tune_out["gains"].get(slot)
        if go is None:
            continue
        gaps[slot] = abs(g_interp[slot] - go) / max(abs(go), _EPS)
    max_gap = max(gaps.values(), default=0.0)
    evidence["interp_gap"] = {"per_slot": gaps, "max": max_gap, "tol": tol_gain}

    # 2) plant 급변 — v를 낀 인접 앵커의 플랜트 거리
    flank_a = points.flanking(v_name, ROLE_ANCHOR)
    if flank_a is not None:
        lo, hi, axis = flank_a
        tr_lo, tr_hi = trims.get(lo), trims.get(hi)
        if tr_lo is not None and tr_hi is not None and tr_lo.converged and tr_hi.converged:
            d = model_distance(lms.get(aircraft, tr_lo), lms.get(aircraft, tr_hi),
                               tr_lo, tr_hi)
            evidence["plant"] = {"pair": (lo, hi), "axis": axis,
                                 "d_total": d["d_total"], "tol": tol_plant,
                                 "detail": {k: d[k] for k in ("d_trim", "d_mode", "d_ctrl")}}
            if d["d_total"] > tol_plant:
                note = None
                if max_gap > tol_gain:
                    note = "valley도 동시 성립 — anchor 승격이 상위 집합 처방이라 이쪽을 택한다"
                return {
                    "verdict": "plant_variation",
                    "action": {"type": "promote", "to": ROLE_ANCHOR, "point": v_name,
                               "note": note},
                    "evidence": evidence,
                }

    # 3) 보간 valley — 최적은 통과 + 괴리 큼 + 이웃 breakpoint는 통과
    flank_b = points.flanking(v_name, ROLE_BREAKPOINT)
    if max_gap > tol_gain and flank_b is not None:
        lo, hi, axis = flank_b
        neighbor_ok = all(
            margin_cases.get(n, {}).get("loops", {}).get(loop_name, {}).get("status")
            not in ("fail",)
            for n in (lo, hi)
        )
        evidence["neighbors"] = {"pair": (lo, hi), "axis": axis, "pass": neighbor_ok}
        if neighbor_ok:
            opt_gains = {s: tune_out["gains"][s] for s in slots if s in tune_out["gains"]}
            # v가 **이미** breakpoint 이상이면 승격할 자리가 없다 — 역할은 단방향
            # 래칫이라 요청하면 터진다(세션 전량 소실). anchor는 breakpoint 역할을
            # 겸하므로(points.at_least 서열) 그 점에서 보간 괴리가 크다는 것은
            # 격자가 성긴 게 아니라 **적합이 그 점을 못 맞춘 것**이다 — 처방은
            # 승격이 아니라 그 점의 최적 게인을 적합 샘플에 고정해 재적합하는 것
            if ROLE_RANK[points.get(v_name).role] >= ROLE_RANK[ROLE_BREAKPOINT]:
                return {
                    "verdict": "gain_interp_valley",
                    "action": {"type": "refit_at", "point": v_name, "gains": opt_gains,
                               "note": "이미 breakpoint 이상 — 승격 대신 재적합"},
                    "evidence": evidence,
                }
            return {
                "verdict": "gain_interp_valley",
                "action": {"type": "promote", "to": ROLE_BREAKPOINT, "point": v_name,
                           "gains": opt_gains},
                "evidence": evidence,
            }

    # 4) 나머지 — 검증점 추가 (히스테리시스 밴드 밖이면 note로 확대 경고)
    deficit_note = None
    if entry.get("kind") == "margin" and entry.get("pm_deg") is not None:
        d = criteria.deficit(entry)
        if d["pm_deg"] > hysteresis_pm:
            deficit_note = f"PM 부족 {d['pm_deg']:.1f}°가 히스테리시스({hysteresis_pm}°) 초과 — 지속 시 재분류 예상"
    elif entry.get("zeta") is not None:
        if criteria.zeta_min - entry["zeta"] > hysteresis_zeta:
            deficit_note = "ζ 부족이 히스테리시스 초과 — 지속 시 재분류 예상"
    return {
        "verdict": "simple_deficit",
        "action": {"type": "add_validation", "point": v_name, "note": deficit_note},
        "evidence": evidence,
    }


def classify_failures(
    aircraft, points, lms, trims, tables, design, margin_out, *,
    criteria, targets=None, tol_plant=0.25, tol_gain=0.10,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
) -> list:
    """마진맵 결과의 fail 목록 전체 분류 — 처방 카드 목록 (심각 순, id 부여).

    같은 점의 여러 자리 실패는 각각 분류하되, 같은 점에 상위 승격이 이미 나왔으면
    하위 처방은 중복이라 supersede로 표시한다 (같은 점을 두 번 승격할 수 없다 —
    points.promote 래칫).
    """
    kw = dict(
        criteria=criteria, targets=targets, tol_plant=tol_plant, tol_gain=tol_gain,
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )
    actions = []
    promoted: dict = {}  # point → 최고 승격 역할
    rank = {ROLE_BREAKPOINT: 1, ROLE_ANCHOR: 2}
    for f in margin_out["failures"]:
        out = classify_margin_deficit(
            aircraft, f["case"], f["loop"], points, lms, trims, tables, design,
            margin_out["cases"], **kw,
        )
        act = out["action"]
        item = {
            "id": f"{out['verdict']}:{f['case']}:{f['loop']}",
            "case": f["case"], "loop": f["loop"],
            "verdict": out["verdict"], "action": act, "evidence": out["evidence"],
            "severity": f.get("severity"),
        }
        if act["type"] == "promote":
            prev = promoted.get(f["case"])
            if prev is not None and rank[prev] >= rank[act["to"]]:
                item["superseded_by"] = f"{f['case']}→{prev}"
            else:
                promoted[f["case"]] = act["to"]
        actions.append(item)
    return actions
