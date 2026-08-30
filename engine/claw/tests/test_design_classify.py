"""M17 classify 검증 — 4-verdict 분기·evidence 수치·완화 임계값·supersede (합성 시나리오)."""

import math

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    ROLE_VALIDATION,
    LinearModelSet,
    MarginCriteria,
    OperatingPoint,
    PointSet,
    TuneTargets,
    case_name,
    tune_point,
)
from claw.design.classify import classify_failures, classify_margin_deficit
from claw.fcl.demo import demo_design_gains
from claw.plant import make_demo_aircraft
from claw.tables import Table
from claw.trim import trim_level

ACT = dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2)


def _setup(machs, v_mach, alt=1000.0, fuel=200.0):
    ac = make_demo_aircraft()
    points, trims = PointSet(), {}
    for m in machs:
        case = TrimCase(name=case_name(m, alt, fuel), mach=m, alt=alt, fuel=fuel)
        tr = trim_level(ac, case, fingerprint="fp")
        assert tr.converged
        trims[case.name] = tr
        role = ROLE_VALIDATION if v_mach is not None and m == v_mach else ROLE_ANCHOR
        pt = OperatingPoint(case=case, role=role, origin="test")
        pt.trimmable = True
        points.add(pt)
    return ac, points, LinearModelSet(), trims


def _fail_cases(v, lo, hi, loop="pitch_att"):
    """합성 마진맵 케이스 — v만 fail, 이웃은 ok."""
    entry = {"kind": "margin", "pm_deg": 42.0, "gm_db": 7.0, "status": "fail"}
    ok = {"kind": "margin", "pm_deg": 60.0, "gm_db": 10.0, "status": "ok"}
    return {
        v: {"role": "validation", "loops": {loop: entry}},
        lo: {"role": "anchor", "loops": {loop: dict(ok)}},
        hi: {"role": "anchor", "loops": {loop: dict(ok)}},
    }


def test_structural_limit_with_excess_delay():
    """과대 지연 — 자유 게인으로도 미달 → escalate (보고 전용) + 병목 수치."""
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, {}, design, _fail_cases(v, lo, hi),
        criteria=MarginCriteria(),
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.6, pade_order=2,
    )
    assert out["verdict"] == "structural_limit"
    assert out["action"]["type"] == "escalate"
    bn = out["evidence"]["bottleneck"]
    assert "delay_phase_deg_at_wc" in bn
    # 완화 프로브가 병목을 **지목**한다 — 지연 0.6 s가 원인이므로 지연 제거만 통과해야
    # 하고, 작동기 대역폭을 3배로 올려도 그 지연은 그대로라 통과하지 못한다.
    # 둘 다 통과한다고 나오면 프로브가 인과를 분리하지 못하는 것이다
    by_change = {p["change"]: p for p in bn["relief"]}
    assert set(by_change) == {"delay_s", "actuator_wn"}
    assert by_change["delay_s"]["resolves"] is True
    assert by_change["delay_s"]["from"] == 0.6 and by_change["delay_s"]["to"] == 0.0
    assert by_change["actuator_wn"]["resolves"] is False
    assert bn["resolved_by"] == ["지연 제거"]
    # 결론 문장은 "지연 제거"가 아니라 **얼마까지 줄이면 되는지**를 말한다
    assert "지연 ≤" in bn["note"] and " s면 통과" in bn["note"]
    assert set(bn["thresholds"]) == {"max_delay_s"}, "통과한 축에만 임계값이 붙는다"
    assert "threshold" not in by_change["actuator_wn"], "미달 축에 임계값을 지어내면 안 된다"


def test_structural_limit_reports_no_relief_when_nothing_helps():
    """완화해도 통과 못 하는 경우 — 프로브가 "해결된다"고 위장하지 않는다.

    합격선을 도달 불가능하게(PM ≥ 179°) 두어 지연·작동기와 무관하게 미달을 만든다.
    긍정 분기만 테스트하면 `resolves`를 무조건 True로 만드는 실수를 못 잡는다 —
    그러면 화면이 "지연만 빼면 된다"고 잘못 안내하고, 실제로는 상위 설계를 헛짚는다.

    **임계값도 없어야 한다.** 이분은 [현재값, 완화값] 브래킷의 양 끝이 각각 미달·통과로
    실측됐다는 전제 위에서만 뜻을 갖는다 — 완화값이 미달인데도 숫자를 내면 그건 실측이
    아니라 이분의 마지막 좌표일 뿐이고, 결론 문장이 없는 예산을 있다고 말하게 된다.
    """
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, {}, demo_design_gains(),
        _fail_cases(v, lo, hi), criteria=MarginCriteria(pm_min_deg=179.0), **ACT,
    )
    assert out["verdict"] == "structural_limit"
    bn = out["evidence"]["bottleneck"]
    assert [p["resolves"] for p in bn["relief"]] == [False, False]
    assert bn["resolved_by"] == []
    assert bn["thresholds"] == {}
    assert all("threshold" not in p for p in bn["relief"])
    assert "플랜트" in bn["note"]
    assert "면 통과" not in bn["note"], "통하는 완화가 없는데 임계값 문장을 낸다"


def test_design_target_miss_alone_is_not_a_structural_limit():
    """**설계 목표**에만 못 미치는 자리를 에스컬레이션으로 보내면 안 된다 — 자가 둘이었다.

    자리 status는 TuneTargets(설계 목표 ζ_dr 0.5) 기준이고 judged는 MarginCriteria
    (합격선 ζ 0.30) 기준인데, 종전 게이트가 그 둘을 OR로 묶었다. 두 선의 간격은
    히스테리시스로 **일부러** 둔 것이라, 게이트가 그걸 결함으로 읽으면 합격선을 여유
    있게 넘는 자리가 적용 버튼 없는 escalate로 간다 — 원래 나왔어야 할 실행 가능한
    처방(승격·재적합)이 사라진다. 한 카드 안에서 evidence의 judged=="ok"와 verdict가
    서로를 부정하는 것도 그 증상이다.

    재현: 데모 M0.6/h1000 yaw_rate에 ζ_dr 목표 0.95(플랜트가 못 내는 값)를 준다.
    달성 0.923 — 합격선 0.30의 3배인데 사유는 target_unreached다.
    """
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    cases = _fail_cases(v, lo, hi, loop="yaw_rate")
    cases[v]["loops"]["yaw_rate"] = {"kind": "damping", "zeta": 0.2, "status": "fail"}
    out = classify_margin_deficit(
        ac, v, "yaw_rate", points, lms, trims, {}, demo_design_gains(), cases,
        criteria=MarginCriteria(), targets=TuneTargets(zeta_dr=0.95), **ACT,
    )
    tuned = out["evidence"]["tuned"]
    assert tuned["reason"] == "target_unreached", "이 테스트가 겨냥한 상황이 아니다"
    assert tuned["judged"] == "ok" and tuned["achieved"]["zeta_dr"] > 0.9
    assert out["verdict"] != "structural_limit", (
        f"합격선의 3배를 내는 자리가 {out['verdict']}로 갔다 — 게이트가 설계 목표선을 결함으로 읽는다")
    assert out["action"]["type"] != "escalate"
    assert "bottleneck" not in out["evidence"], "구조 한계가 아닌데 완화 프로브를 돌렸다"


def test_structural_gate_keeps_both_of_its_halves():
    """게이트를 합격선 축으로 옮겨도 **잡아야 할 둘은 그대로** 잡는다 — 술어 헬퍼로 직접 잰다.

    (a) 판정이 fail — 자유 게인 최적조차 합격선에 못 미친다.
    (b) 사유가 "쓸 수 있는 게인 자체가 안 나온" 축(no_stable_gain·degenerate·
        margin_floor·bandwidth_collapse) — 지연 0.6 s의 pitch_att가 그 경우다. PM 86°/
        GM 10 dB라 마진 판정만 보면 ok지만 교차가 목표의 0.08배로 무너져 있다. 판정
        하나로만 게이트를 만들면 이 자리를 통과시킨다.
    (c) 그 목록에 없는 사유(target_unreached·capped)는 구조 한계가 아니다.

    게이트·프로브·이분이 모두 이 함수 하나를 부르므로, 여기서 셋을 한 번에 고정한다.
    """
    from claw.design.classify import _slot_passes, _tuned_judgement

    ac, _points, lms, trims = _setup((0.6,), v_mach=None)
    lm = lms.get(ac, trims[case_name(0.6, 1000.0, 200.0)])
    design = demo_design_gains()

    fail_judged = tune_point(lm, design, **ACT)
    assert not _slot_passes(fail_judged, "pitch_att", MarginCriteria(pm_min_deg=179.0))

    collapsed = tune_point(lm, design, **{**ACT, "delay_s": 0.6})
    assert collapsed["slots"]["pitch_att"]["reason"] == "bandwidth_collapse"
    assert _tuned_judgement(collapsed, "pitch_att", MarginCriteria()) == "ok"
    assert not _slot_passes(collapsed, "pitch_att", MarginCriteria()), (
        "대역폭이 무너진 자리를 마진 판정만 보고 통과시킨다")

    unreached = tune_point(lm, design, targets=TuneTargets(zeta_dr=0.95), **ACT)
    assert unreached["slots"]["yaw_rate"]["reason"] == "target_unreached"
    assert _slot_passes(unreached, "yaw_rate", MarginCriteria())


def test_plant_variation_promotes_to_anchor():
    """플랜트 급변(tol_plant 낮춤) — validation → anchor 승격, valley 동시 성립 시 병기."""
    ac, points, lms, trims = _setup((0.25, 0.35, 0.45), v_mach=0.35)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.35, 0.25, 0.45))
    design = demo_design_gains()
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, {}, design, _fail_cases(v, lo, hi),
        criteria=MarginCriteria(), tol_plant=0.05, **ACT,
    )
    assert out["verdict"] == "plant_variation"
    assert out["action"]["type"] == "promote" and out["action"]["to"] == ROLE_ANCHOR
    assert out["evidence"]["plant"]["d_total"] > 0.05


def test_gain_interp_valley_promotes_to_breakpoint():
    """이웃 통과 + 보간 게인 괴리 큼 (plant 분기는 tol 완화로 배제) → breakpoint 승격."""
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    opt = tune_point(lms.get(ac, trims[v]), design, **ACT)["gains"]
    # 보간 게인을 최적의 3배로 — 괴리 200% > tol_gain 10%
    tables = {
        "pitch.kp": Table({"mach": (0.55, 0.65)},
                          (opt["pitch.kp"] * 3.0,) * 2, extrapolate="clip"),
    }
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, tables, design,
        _fail_cases(v, lo, hi), criteria=MarginCriteria(), tol_plant=99.0, **ACT,
    )
    assert out["verdict"] == "gain_interp_valley"
    act = out["action"]
    assert act["type"] == "promote" and act["to"] == "breakpoint"
    assert act["gains"]["pitch.kp"] == pytest.approx(opt["pitch.kp"])
    assert out["evidence"]["interp_gap"]["max"] > 0.10


def test_simple_deficit_adds_validation():
    """괴리 작고 플랜트 완만 — 검증점 추가 처방."""
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    opt = tune_point(lms.get(ac, trims[v]), design, **ACT)["gains"]
    tables = {
        "pitch.kp": Table({"mach": (0.55, 0.65)}, (opt["pitch.kp"],) * 2,
                          extrapolate="clip"),
        "pitch.ki": Table({"mach": (0.55, 0.65)}, (opt["pitch.ki"],) * 2,
                          extrapolate="clip"),
    }
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, tables, design,
        _fail_cases(v, lo, hi), criteria=MarginCriteria(), tol_plant=99.0, **ACT,
    )
    assert out["verdict"] == "simple_deficit"
    assert out["action"]["type"] == "add_validation"


def test_classify_failures_supersede():
    """같은 점의 다중 실패 — 승격 처방 중 상위 하나만 유효, 나머지는 supersede."""
    ac, points, lms, trims = _setup((0.25, 0.35, 0.45), v_mach=0.35)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.35, 0.25, 0.45))
    cases = _fail_cases(v, lo, hi)
    cases[v]["loops"]["pitch_rate"] = {"kind": "damping", "zeta": 0.2, "status": "fail"}
    margin_out = {
        "cases": cases,
        "failures": [
            {"case": v, "loop": "pitch_att", "severity": 42.0},
            {"case": v, "loop": "pitch_rate", "severity": 18.0},
        ],
    }
    actions = classify_failures(
        ac, points, lms, trims, {}, demo_design_gains(), margin_out,
        criteria=MarginCriteria(), tol_plant=0.05, **ACT,
    )
    assert len(actions) == 2
    promotes = [a for a in actions if a["action"]["type"] == "promote"]
    assert promotes, "승격 처방이 없다"
    superseded = [a for a in actions if "superseded_by" in a]
    assert len(promotes) - len(superseded) <= 1  # 같은 점 유효 승격은 1개
    assert all(a["id"].count(":") == 2 for a in actions)


def test_valley_on_anchor_is_a_fit_failure_not_a_sample_failure():
    """앵커의 보간 괴리는 **적합 실패**다 — 게인 주입 처방은 구조적으로 무효다.

    승격은 래칫 위반이라 세션을 죽이므로 낼 수 없다. 그렇다고 "그 점의 최적 게인을
    적합 샘플에 고정"하는 것도 답이 아니다: 앵커는 TUNE이 매 이터레이션 자유 게인
    최적을 넣는 자리라 **이미 그 값이 샘플**이고, 병합에서 튜닝 샘플이 이긴다
    (orchestrator._stage_fit setdefault). 종전에는 그런 처방을 refit_at으로 내고
    applied로 기록해 이터 예산만 태웠다 — 반영해도 다음 판정이 그대로였다.

    남은 손잡이는 적합 자체다 (허용치·구간 수).
    """
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=None)  # 전부 anchor
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    opt = tune_point(lms.get(ac, trims[v]), design, **ACT)["gains"]
    tables = {
        "pitch.kp": Table({"mach": (0.55, 0.65)},
                          (opt["pitch.kp"] * 3.0,) * 2, extrapolate="clip"),
    }
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, tables, design,
        _fail_cases(v, lo, hi), criteria=MarginCriteria(), tol_plant=99.0, **ACT,
    )
    assert out["verdict"] == "fit_residual"
    act = out["action"]
    assert act["type"] == "tighten_fit", "anchor에 승격·게인 주입 처방을 내면 안 된다"
    assert act["slots"] == ["pitch.kp", "pitch.ki"]
    assert "gains" not in act, "앵커의 샘플은 이미 최적 — 주입할 값이 없다"


def test_valley_on_breakpoint_still_injects_the_optimum():
    """breakpoint는 TUNE이 안 도는 자리라 최적 게인 주입이 **실제로** 값을 바꾼다.

    앵커와 갈라 두지 않으면 둘 중 하나는 틀린 처방을 받는다.
    """
    from claw.design import ROLE_BREAKPOINT

    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    points.promote(v, ROLE_BREAKPOINT, reason="test")
    design = demo_design_gains()
    opt = tune_point(lms.get(ac, trims[v]), design, **ACT)["gains"]
    tables = {
        "pitch.kp": Table({"mach": (0.55, 0.65)},
                          (opt["pitch.kp"] * 3.0,) * 2, extrapolate="clip"),
    }
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, tables, design,
        _fail_cases(v, lo, hi), criteria=MarginCriteria(), tol_plant=99.0, **ACT,
    )
    assert out["verdict"] == "gain_interp_valley"
    assert out["action"]["type"] == "refit_at"
    assert out["action"]["gains"]["pitch.kp"] == pytest.approx(opt["pitch.kp"])


def test_sign_flip_gets_its_own_verdict_not_promotion():
    """부호 뒤집힘은 격자 문제가 아니다 — 승격을 처방하면 재개해도 그대로다.

    실제로 겪었다: plant_variation으로 분류돼 앵커 승격을 반영했는데 다항이 다시
    0을 가로질러 실패가 유지됐다.
    """
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    cases = _fail_cases(v, lo, hi)
    # 검증이 부호 뒤집힘을 표시한 상태 (schedmap._apply_sign_check가 하는 일)
    cases[v]["loops"]["pitch_att"].update({
        "sign_flip": ["pitch.ki"],
        "gains": {"kp": -2.0, "ki": +0.5},  # ki가 설계(-0.5)와 반대
    })
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, {}, design, cases,
        criteria=MarginCriteria(), tol_plant=0.001, **ACT,  # plant도 걸리게 낮춘다
    )
    assert out["verdict"] == "gain_sign_flip", "부호 뒤집힘이 다른 원인으로 분류됐다"
    assert out["action"]["type"] == "refit_at"
    assert out["evidence"]["sign_flip"]["slots"] == ["pitch.ki"]


def test_failing_sibling_axis_does_not_escalate_this_slot():
    """한 축이 안 되는 점에서 **다른 축의 고칠 수 있는 실패**가 에스컬레이션으로 둔갑하면 안 된다.

    분류는 (점, 자리) 단위인데 구조 한계 판정이 **점 단위** status를 봤다. 그래서
    피치가 대역폭 붕괴로 infeasible인 점에서는, 자유 게인으로 멀쩡히 통과하는 롤의
    실패까지 structural_limit → escalate(적용 버튼 없음)가 됐다 — 원래 나왔어야 할
    breakpoint 승격(실행 가능한 처방)이 사라진다.

    지연 0.6 s에서 이 점의 자리별 상태: pitch_att infeasible / roll_att ok.
    """
    act = {**ACT, "delay_s": 0.6}
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    out_t = tune_point(lms.get(ac, trims[v]), design, **act)
    assert out_t["status"] == "infeasible", "점 단위로는 실패인 상황이어야 한다"
    assert out_t["slots"]["pitch_att"]["status"] == "infeasible"
    assert out_t["slots"]["roll_att"]["status"] == "ok", "롤은 멀쩡해야 이 테스트가 성립한다"

    opt = out_t["gains"]
    tables = {  # 보간 게인을 최적의 3배로 — 괴리 200% > tol_gain 10%
        "roll.kp": Table({"mach": (0.55, 0.65)}, (opt["roll.kp"] * 3.0,) * 2,
                         extrapolate="clip"),
    }
    out = classify_margin_deficit(
        ac, v, "roll_att", points, lms, trims, tables, design,
        _fail_cases(v, lo, hi, loop="roll_att"),
        criteria=MarginCriteria(), tol_plant=99.0, **act,
    )
    assert out["verdict"] == "gain_interp_valley", (
        f"롤 실패가 {out['verdict']}로 갔다 — 점 단위 status가 자리 판정을 오염시킨다")
    assert out["action"]["type"] == "promote"
    # 근거에도 자리 단위 상태가 남아야 한다 (점 단위는 참고로만)
    assert out["evidence"]["tuned"]["status"] == "ok"
    assert out["evidence"]["tuned"]["point_status"] == "infeasible"


def test_relief_probe_resolves_is_slot_scoped(monkeypatch):
    """완화 프로브의 "해소" 판정도 자리 단위다.

    점 단위로 재면, 이 자리를 실제로 고친 완화도 **다른 축이 못 따라오면** "여전히
    미달"로 보고된다. 그러면 화면의 결론 문장("무엇을 바꾸면 통과하는가")이 거짓이
    되고, 사용자는 통하는 예산 변경을 통하지 않는 것으로 읽는다.

    바뀐 것은 판정식 하나이므로 튜너를 대역해 그 식만 잰다.
    """
    from claw.design import classify as C

    def fake_tune_point(lm, design, *, targets=None, **kw):
        # 완화 후: 이 자리는 통과, 그런데 점 전체는 다른 축 때문에 여전히 실패
        return {
            "gains": {}, "notes": [],
            "achieved": {"roll_att": {"pm_deg": 70.0, "gm_db": 12.0}},
            "slots": {"roll_att": {"status": "ok", "reason": "ok", "target": 50.0},
                      "pitch_att": {"status": "infeasible", "reason": "margin_floor"}},
            "status": "infeasible",
        }

    monkeypatch.setattr(C, "tune_point", fake_tune_point)
    probes = C._relief_probes(
        None, {}, "roll_att", targets=None, criteria=MarginCriteria(),
        act_kw=dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2),
    )
    assert [p["label"] for p in probes] == ["지연 제거", "작동기 대역폭 ×3"]
    assert all(p["resolves"] for p in probes), (
        "이 자리를 고친 완화가 다른 축 때문에 '미달'로 보고됐다")
    assert all(p["status"] == "ok" for p in probes)


def test_relief_threshold_is_measured_not_the_probe_value():
    """"×3이면 통과"가 아니라 **최소 몇이면 통과**인지를 낸다 — 그 수치가 곧 요구 사양이다.

    docs -01 §7 백로그의 "작동기 대역폭 요구 사양 미도출"이 묻는 것은 배수가 아니라
    rad/s 값이다. 프로브는 그 답을 눈앞에 두고도 불리언만 남기고 있었다.

    이 테스트가 가르는 것은 "임계값이 실측인가"다. 이분이 낸 min_actuator_wn을 **다시
    돌려** 통과를 확인하고, 브래킷의 반대쪽 끝(한 걸음 아래)에서는 통과하지 않음을
    확인한다. 폭이 초기 브래킷의 1/256임도 같이 고정한다 — 이분을 지우고 완화값(×3)을
    그대로 내면 "그 값에서 통과"는 여전히 참이지만 폭과 "완화값보다 작다"가 무너진다.

    시나리오: 작동기 18 rad/s(데모 30보다 짠 예산)에서 M0.6/h1000 pitch_att는 대역폭
    붕괴로 구조 한계다. 두 축이 모두 통과하므로 전/후 달성값도 여기서 함께 잰다.
    """
    from claw.design.classify import _slot_passes

    act = {**ACT, "actuator_wn": 18.0}
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    design = demo_design_gains()
    out = classify_margin_deficit(
        ac, v, "pitch_att", points, lms, trims, {}, design, _fail_cases(v, lo, hi),
        criteria=MarginCriteria(), **act,
    )
    assert out["verdict"] == "structural_limit"
    bn = out["evidence"]["bottleneck"]
    probe = next(p for p in bn["relief"] if p["change"] == "actuator_wn")
    assert probe["resolves"] is True, "이 시나리오는 작동기 완화가 통해야 성립한다"
    th = probe["threshold"]
    assert th["name"] == "min_actuator_wn" and th["unit"] == "rad/s"
    assert th["direction"] == ">=" and th["current"] == 18.0
    assert bn["thresholds"]["min_actuator_wn"] == th["value"]

    # 1) 배수가 아니라 경계다 — ×3(54)보다 한참 아래에서 이미 통과한다
    assert 18.0 < th["value"] < th["probe_value"]
    # 2) 폭 = 초기 브래킷 ÷ 2^8. 이분을 지우면 여기서 걸린다
    passed, failed = th["bracket"]
    assert passed == th["value"]
    assert abs(failed - passed) == pytest.approx((54.0 - 18.0) / 2**8)

    # 3) **실측 확인** — 그 값이면 통과하고, 한 걸음 아래면 통과하지 않는다.
    #    술어는 게이트와 같은 함수라 "이분이 찾은 경계 = 구조 한계 경계"다
    lm = lms.get(ac, trims[v])
    crit = MarginCriteria()
    assert _slot_passes(tune_point(lm, design, **{**act, "actuator_wn": passed}),
                        "pitch_att", crit)
    assert not _slot_passes(tune_point(lm, design, **{**act, "actuator_wn": failed}),
                            "pitch_att", crit), (
        "한 걸음 아래에서도 통과한다 — 낸 값이 경계가 아니다")

    # 4) 완화 전/후 달성값 — 프로브가 이미 치른 계산이다. 대역폭 붕괴가 원인이므로
    #    후에는 교차가 크게 회복돼 있어야 한다
    ach = probe["achieved"]
    assert set(ach["before"]) == {"pm_deg", "gm_db", "wc_att", "wc0"}
    assert set(ach["after"]) == set(ach["before"])
    assert ach["after"]["wc_att"] > ach["before"]["wc_att"]
    assert bn["note"].startswith("자유 게인으로도 기준 미달 — ")
    assert f"작동기 대역폭 ≥ {th['value']:.3g} rad/s면 통과 (현재 18)" in bn["note"]


def test_relief_probe_carries_the_achieved_numbers_it_already_paid_for(monkeypatch):
    """프로브가 계산해 놓고 버리던 달성 수치를 전/후로 싣는다 — 자리 종류에 맞는 키로.

    종전 프로브는 tune_point을 통째로 한 번 더 돌리고 out["achieved"]를 버렸다.
    "지연을 빼면 λ 4.2 → 9.0"이 매번 계산되고 폐기된 것이다. 화면이 전후를 비교하려면
    양쪽이 **같은 키**여야 하므로 자리 종류별로 골라 담는다 — 롤은 λ와 목표에 더해
    발산 여부·참여도까지다 (그 둘이 없으면 λ 수치만으로는 판정을 재현할 수 없다).

    바뀐 것은 담는 규칙 하나이므로 튜너를 대역해 그 규칙만 잰다.
    """
    from claw.design import classify as C

    def make(lam):
        return {
            "gains": {}, "notes": [],
            "achieved": {"roll_rate": {"kind": "bandwidth", "roll_lambda": lam,
                                       "target": 12.0, "wc": 8.0, "capped": None,
                                       "reason": "ok", "unstable": False,
                                       "participation": 0.9}},
            "slots": {"roll_rate": {"status": "ok", "reason": "ok", "target": 12.0}},
            "status": "ok",
        }

    monkeypatch.setattr(C, "tune_point", lambda *a, **kw: make(9.0))
    probes = C._relief_probes(
        None, {}, "roll_rate", targets=None, criteria=MarginCriteria(),
        act_kw=dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2),
        base_out=make(4.2),
    )
    keys = {"roll_lambda", "target", "unstable", "participation"}
    for p in probes:
        assert set(p["achieved"]["before"]) == keys
        assert p["achieved"]["before"]["roll_lambda"] == 4.2
        assert p["achieved"]["after"]["roll_lambda"] == 9.0
        assert p["achieved"]["after"]["participation"] == 0.9
    # 완화 전 결과가 없으면 지어내지 않는다 (None) — 후만 낸다
    bare = C._relief_probes(
        None, {}, "roll_rate", targets=None, criteria=MarginCriteria(),
        act_kw=dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2),
    )
    assert all(p["achieved"]["before"] is None for p in bare)


def test_gate_and_relief_probe_read_one_predicate(monkeypatch):
    """구조 한계 술어는 **한 함수에만** 있다 — 게이트도 프로브도 그것을 부른다.

    같은 식이 두 곳에 손으로 적혀 있으면 한쪽만 바뀐 날 프로브가 거짓 안도를 준다
    ("지연만 빼면 통과"라고 말하는데 게이트는 여전히 미달로 본다). 술어를 대역해
    두 자리가 **함께** 뒤집히는지를 본다 — 어느 한쪽이라도 제 식을 갖고 있으면
    여기서 갈라진다.
    """
    from claw.design import classify as C

    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    kw = dict(criteria=MarginCriteria(), tol_plant=99.0)

    # 술어가 "미달"이라 하면 멀쩡한 점도 구조 한계다 — 게이트가 이 함수를 읽는다는 증거
    monkeypatch.setattr(C, "_slot_passes", lambda *a, **k: False)
    out = classify_margin_deficit(ac, v, "pitch_att", points, lms, trims, {},
                                  demo_design_gains(), _fail_cases(v, lo, hi),
                                  **kw, **ACT)
    assert out["verdict"] == "structural_limit"
    bn = out["evidence"]["bottleneck"]
    # 프로브도 같은 함수를 읽는다 — 제 식을 갖고 있으면 여기서 통과로 나온다
    assert [p["resolves"] for p in bn["relief"]] == [False, False]
    assert bn["thresholds"] == {}

    # 반대로 "통과"라 하면 진짜 구조 한계(지연 0.6 s)도 아래 분기로 흐른다
    monkeypatch.setattr(C, "_slot_passes", lambda *a, **k: True)
    out = classify_margin_deficit(ac, v, "pitch_att", points, lms, trims, {},
                                  demo_design_gains(), _fail_cases(v, lo, hi),
                                  **kw, **{**ACT, "delay_s": 0.6})
    assert out["verdict"] != "structural_limit"
    assert "bottleneck" not in out["evidence"]


def test_nan_crossover_does_not_leak_into_the_bottleneck_numbers(monkeypatch):
    """교차가 없어 wcp가 nan인 자리에서도 병목 수치 둘이 nan으로 새지 않는다.

    `entry.get("wcp") or entry.get("wc") or 0.0`은 폴백처럼 보이지만 **nan은 파이썬에서
    truthy**라 그대로 통과한다. 그러면 wc_over_actuator와 delay_phase_deg_at_wc가 **둘
    다** nan이 되어, "지연이 병목인가 작동기가 병목인가"에 답할 수치 두 개가 화면에서
    동시에 사라진다 — 하필 그 판단이 필요한 카드에서.

    튜너는 대역한다: 여기서 재는 것은 evidence의 수치 두 개뿐이고, 실기동을 돌리면
    이분까지 따라와 초 단위로 느려진다.
    """
    from claw.design import classify as C

    def fake_tune_point(lm, design, *, targets=None, **kw):
        # 어느 완화로도 안 되는 자리 — 프로브가 이분까지 가지 않는다
        return {
            "gains": {}, "notes": [],
            "achieved": {"pitch_att": {"pm_deg": 20.0, "gm_db": 3.0, "wc_att": 0.1,
                                       "wc0": 3.0, "reason": "margin_floor"}},
            "slots": {"pitch_att": {"status": "infeasible", "reason": "margin_floor"}},
            "status": "infeasible",
        }

    monkeypatch.setattr(C, "tune_point", fake_tune_point)
    ac, points, lms, trims = _setup((0.55, 0.6, 0.65), v_mach=0.6)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.6, 0.55, 0.65))
    cases = _fail_cases(v, lo, hi)
    cases[v]["loops"]["pitch_att"]["wcp"] = float("nan")
    out = classify_margin_deficit(ac, v, "pitch_att", points, lms, trims, {},
                                  demo_design_gains(), cases,
                                  criteria=MarginCriteria(), **ACT)
    bn = out["evidence"]["bottleneck"]
    assert math.isfinite(bn["wc_over_actuator"]) and math.isfinite(
        bn["delay_phase_deg_at_wc"]), "nan이 폴백을 통과해 병목 수치를 지웠다"

    # wcp만 nan이고 wc가 살아 있으면 **그쪽을 쓴다** — 폴백 순서까지 고정한다
    cases[v]["loops"]["pitch_att"]["wc"] = 2.5
    out = classify_margin_deficit(ac, v, "pitch_att", points, lms, trims, {},
                                  demo_design_gains(), cases,
                                  criteria=MarginCriteria(), **ACT)
    bn = out["evidence"]["bottleneck"]
    assert bn["wc_over_actuator"] == pytest.approx(2.5 / 30.0)
    assert bn["delay_phase_deg_at_wc"] == pytest.approx(math.degrees(2.5 * 0.035))


def test_free_gain_optimum_uses_the_hand_design_bracket():
    """자유 게인 최적은 **손설계 정본**에서 부호·브래킷을 잡아야 한다.

    tune_point은 design에서 그 둘만 읽는다. 오케스트레이터가 분류기에 넘기던 것은
    `{**손설계, **적합 상수}`라, 적합이 접은 값이 곧 탐색의 출발점이 됐다.

    브래킷 **크기** 차이는 이제 확장(_first_reach_bisect, 최대 256배)이 흡수한다 —
    같은 최적을 찾아낸다. 남은 노출은 **0**이다: 설계값 0인 자리는 방향 정보가 없어
    튜너가 통째로 건너뛰고(REASON_ZERO_DESIGN) 0.0을 "자유 게인 최적"이라 낸다.
    4×0 = 0이라 확장으로도 못 산다. 적합이 부호 가드 폴백으로 상수를 내거나 스케줄
    자리가 비면 실제로 0이 온다.
    """
    from claw.design.tune import REASON_ZERO_DESIGN

    ac, points, lms, trims = _setup((0.25, 0.3, 0.35), v_mach=0.3)
    v, lo, hi = (case_name(m, 1000.0, 200.0) for m in (0.3, 0.25, 0.35))
    design = demo_design_gains()
    ref = tune_point(lms.get(ac, trims[v]), design, **ACT)  # 손설계 정본의 정답
    assert ref["slots"]["roll_rate"]["status"] == "ok"

    zeroed = {**design, "roll.k_rate": 0.0}  # 적합이 이 자리를 0으로 접은 상황
    kw = dict(criteria=MarginCriteria(), tol_plant=99.0, **ACT)
    cases = _fail_cases(v, lo, hi, loop="roll_att")
    out = classify_margin_deficit(ac, v, "roll_att", points, lms, trims, {}, zeroed,
                                  cases, design_base=design, **kw)
    got = out["evidence"]["tuned"]["achieved"]
    assert got["pm_deg"] == pytest.approx(ref["achieved"]["roll_att"]["pm_deg"]), (
        "분류기의 자유 게인 최적이 TUNE과 다르다 — 탐색이 적합 상수에 끌려갔다")

    # design_base 없이 부르면 종전 동작 — 롤 댐퍼가 아예 안 켜진 채로 "최적"을 낸다.
    # 이 단정이 무너지면 두 경로가 같아진 것이므로 이 테스트가 판별력을 잃은 것이다
    stale = classify_margin_deficit(ac, v, "roll_att", points, lms, trims, {}, zeroed,
                                    cases, **kw)
    assert stale["evidence"]["tuned"]["reason"] != REASON_ZERO_DESIGN  # 자세 자리는 살아 있고
    assert stale["evidence"]["tuned"]["achieved"]["pm_deg"] != pytest.approx(
        got["pm_deg"], rel=1e-6), "브래킷 차이가 결과를 안 바꾼다 — 판별력 없는 테스트"
