"""M17 classify 검증 — 4-verdict 분기·evidence 수치·supersede (합성 시나리오)."""

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    ROLE_VALIDATION,
    LinearModelSet,
    MarginCriteria,
    OperatingPoint,
    PointSet,
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
    assert "지연 제거" in bn["note"]


def test_structural_limit_reports_no_relief_when_nothing_helps():
    """완화해도 통과 못 하는 경우 — 프로브가 "해결된다"고 위장하지 않는다.

    합격선을 도달 불가능하게(PM ≥ 179°) 두어 지연·작동기와 무관하게 미달을 만든다.
    긍정 분기만 테스트하면 `resolves`를 무조건 True로 만드는 실수를 못 잡는다 —
    그러면 화면이 "지연만 빼면 된다"고 잘못 안내하고, 실제로는 상위 설계를 헛짚는다.
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
    assert "플랜트" in bn["note"]


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


def test_valley_on_anchor_prescribes_refit_not_promotion():
    """이미 breakpoint 이상인 점의 보간 괴리 — 승격은 래칫 위반이라 세션을 죽인다.

    anchor는 breakpoint 역할을 겸하므로(서열) 그 점의 괴리는 격자가 성긴 게 아니라
    적합이 못 맞춘 것이다 → 재적합 처방이어야 한다.
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
    assert out["verdict"] == "gain_interp_valley"
    assert out["action"]["type"] == "refit_at", "anchor에 승격 처방을 내면 래칫이 터진다"
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
