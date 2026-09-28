"""M17 orchestrator 검증 — 전자동 종결, gated 일시정지·승인·재개, 왕복, 취소."""

import numpy as np
import pytest

from claw.design import AutoDesignConfig, DesignSession, TuneTargets
from claw.fcl.demo import demo_design_gains
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_stall_table,
    make_demo_structural_limits,
)


@pytest.fixture(scope="module")
def env():
    return (
        make_demo_aircraft(),
        make_demo_stall_table(),
        make_demo_structural_limits(),
        make_demo_db_ranges(),
        demo_design_gains(),
    )


def _small(**over):
    base = dict(n_mach=3, alts=(1000.0,), fuels=(200.0,), budget_points=24,
                budget_iters=3, mode="auto")
    base.update(over)
    return AutoDesignConfig(**base)


def test_auto_mode_reaches_terminal(env):
    """전자동 — 예산 내에서 converged/escalated/budget_exhausted 중 하나로 끝난다."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small())
    report = s.run(ac, stall, limits, db, design, fingerprint="fp")
    assert s.stage == "DONE"
    assert report["status"] in ("converged", "escalated", "budget_exhausted")
    # "실패 0"이 통과인지 미검증인지 — 판정 수가 갈라 준다 (vacuous pass 배제)
    assert report["judged"] > 0, "판정이 한 건도 없는데 종결됐다"
    assert report["points"]["anchor"] >= 3
    assert s.sched_tables or s.sched_constants  # 게인 산출물이 존재
    assert s.margin_out["cases"]  # 스케줄 인지 검증이 돌았다
    # 에스컬레이션은 자동 적용된 적이 없어야 한다 — applied 표식 금지
    assert all(not a.get("applied") for a in s.escalations)


def test_gated_pauses_then_resumes(env):
    """gated 기본 — 처방이 나오면 awaiting_approval로 멈추고, 승인 후 이어 돈다.

    일부러 조악한 적합(1구간·1차·허용치 무한)으로 보간 괴리를 만들어 실패를 유도한다.
    """
    ac, stall, limits, db, design = env
    s = DesignSession(_small(mode="gated", fit_tol=0.99, max_segments=1, max_degree=1))
    report = s.run(ac, stall, limits, db, design, fingerprint="fp")
    if report["status"] in ("converged", "escalated"):
        pytest.skip("조악한 적합으로도 실패가 없다 — gated 경로는 왕복 테스트가 덮는다")
    assert report["status"] == "awaiting_approval"
    cards = s.proposed_actions()
    assert cards, "일시정지인데 처방 카드가 없다"
    assert all("evidence" in a and "verdict" in a for a in cards)
    approvable = [a["id"] for a in cards if a["action"]["type"] != "escalate"]
    out = s.apply_actions(approvable)
    assert out["next_stage"] in ("REFINE", "TUNE")
    assert s.iter_n == 1
    report2 = s.run(ac, stall, limits, db, design, fingerprint="fp")
    assert report2["status"] in (
        "converged", "escalated", "budget_exhausted", "awaiting_approval"
    )


def test_roundtrip_preserves_session(env):
    ac, stall, limits, db, design = env
    s = DesignSession(_small())
    s.run(ac, stall, limits, db, design, fingerprint="fp")
    d = s.to_dict()
    s2 = DesignSession.from_dict(d)
    assert s2.to_dict() == d  # 완전 왕복
    assert s2.report() == s.report()


def test_cancel_preserves_and_resumes(env):
    ac, stall, limits, db, design = env
    s = DesignSession(_small())
    calls = []

    def cancel_early(done, total, message):
        calls.append(message)
        return len(calls) >= 2

    report = s.run(ac, stall, limits, db, design, fingerprint="fp",
                   on_progress=cancel_early)
    assert report["status"] == "cancelled"
    # 왕복 후 재개 — 처음부터가 아니라 남은 스테이지부터
    s2 = DesignSession.from_dict(s.to_dict())
    report2 = s2.run(ac, stall, limits, db, design, fingerprint="fp")
    assert report2["status"] in (
        "converged", "escalated", "budget_exhausted", "awaiting_approval"
    )


def test_config_validation():
    with pytest.raises(ValueError, match="mode"):
        AutoDesignConfig(mode="yolo")
    with pytest.raises(ValueError, match="budget_iters"):
        AutoDesignConfig(budget_iters=99)
    for bad in (0, 5):
        with pytest.raises(ValueError, match="n_validation_between"):
            AutoDesignConfig(n_validation_between=bad)
    with pytest.raises(ValueError, match="fit_mode"):
        AutoDesignConfig(fit_mode="spline")
    c = AutoDesignConfig(alts=(1000.0,), n_validation_between=2)
    assert AutoDesignConfig.from_dict(c.to_dict()) == c
    # 필드가 생기기 전 저장물(왕복 dict에 키 없음) — 기본값 1로 재개된다
    legacy = {k: v for k, v in c.to_dict().items() if k != "n_validation_between"}
    assert AutoDesignConfig.from_dict(legacy).n_validation_between == 1
    # 표현 기본값은 표다 (사용자 확정) — 옛 저장물도 그 기본으로 재개된다.
    # 다항으로 돈 옛 세션의 결과는 저장물 자체에 sched_tables가 실려 있어 영향받지
    # 않고, 재개(run 이어달리기)는 이 기본으로 FIT부터 다시 돈다
    assert AutoDesignConfig().fit_mode == "table"
    legacy2 = {k: v for k, v in c.to_dict().items() if k != "fit_mode"}
    assert AutoDesignConfig.from_dict(legacy2).fit_mode == "table"


def test_targets_must_meet_criteria():
    """튜닝 목표가 판정선보다 낮으면 제출 시점에 막는다 — 성공점이 warn/fail로 찍힌다.

    기본값끼리 이미 정합이라는 첫 단정이 핵심이다: 종전에는 gm_good_db 10 dB >
    targets.gm_db 8 dB로 어긋나 있어 튜닝 성공점이 구조적으로 warn이었다.
    """
    from claw.design import MarginCriteria, TuneTargets

    AutoDesignConfig()  # 출하 기본값은 정합이어야 한다
    with pytest.raises(ValueError, match="gm_db"):
        AutoDesignConfig(targets=TuneTargets(gm_db=7.0))
    with pytest.raises(ValueError, match="pm_deg"):
        AutoDesignConfig(criteria=MarginCriteria(pm_min_deg=60.0))
    with pytest.raises(ValueError, match="zeta_dr"):
        AutoDesignConfig(targets=TuneTargets(zeta_dr=0.4))
    # 금지가 아니라 **정합 요구**다 — 판정선을 올리면서 목표도 함께 올리면 통과한다
    AutoDesignConfig(criteria=MarginCriteria(gm_good_db=12.0),
                     targets=TuneTargets(gm_db=12.0))


def test_add_validation_inserts_flanking_midpoints(env):
    """simple_deficit 처방 — 검증점 좌우 이웃과의 중점 2개를 넣는다 (예산 내)."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small())
    for mach, role in ((0.3, ROLE_ANCHOR), (0.4, ROLE_VALIDATION), (0.5, ROLE_ANCHOR)):
        s.points.add(OperatingPoint(
            case=TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach,
                          alt=1000.0, fuel=200.0),
            role=role, origin="test",
        ))
    target = case_name(0.4, 1000.0, 200.0)
    s.actions = [{"id": "a1", "verdict": "simple_deficit", "case": target, "loop": "pitch_att",
                  "action": {"type": "add_validation", "point": target}}]
    s.apply_actions(["a1"])

    added = sorted(p.case.mach for p in s.points.by_role(ROLE_VALIDATION)
                   if p.origin.startswith("add_validation"))
    assert added == pytest.approx([0.35, 0.45])
    assert s.stage == "TUNE"  # 앵커 승격이 아니므로 리파인으로 돌아가지 않는다


def test_add_validation_respects_point_budget(env):
    """예산이 꽉 차 있으면 검증점을 더 넣지 않는다 (종료 보장의 한 겹)."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small(budget_points=4))
    for mach, role in ((0.3, ROLE_ANCHOR), (0.4, ROLE_VALIDATION),
                       (0.5, ROLE_ANCHOR), (0.6, ROLE_ANCHOR)):
        s.points.add(OperatingPoint(
            case=TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach,
                          alt=1000.0, fuel=200.0),
            role=role, origin="test",
        ))
    target = case_name(0.4, 1000.0, 200.0)
    s.actions = [{"id": "a1", "verdict": "simple_deficit", "case": target, "loop": "pitch_att",
                  "action": {"type": "add_validation", "point": target}}]
    s.apply_actions(["a1"])
    assert len(s.points) == 4  # 상한에서 멈춘다


def test_ratchet_violation_is_skipped_not_fatal(env):
    """상위 역할 점에 승격 처방이 오더라도 세션을 죽이지 않는다 (안전망).

    분류기가 그런 처방을 내지 않도록 막아 두었지만(classify refit_at), 여기서
    ValueError가 나면 run()이 못 잡아 트림·튜닝 전량이 저장 없이 사라진다.
    """
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, OperatingPoint, case_name

    s = DesignSession(_small())
    name = case_name(0.5, 1000.0, 200.0)
    s.points.add(OperatingPoint(
        case=TrimCase(name=name, mach=0.5, alt=1000.0, fuel=200.0),
        role=ROLE_ANCHOR, origin="test",
    ))
    s.actions = [{"id": "a1", "verdict": "gain_interp_valley", "case": name, "loop": "pitch_att",
                  "action": {"type": "promote", "to": "breakpoint", "point": name,
                             "gains": {"pitch.kp": -1.8}}}]
    out = s.apply_actions(["a1"])  # 터지면 안 된다
    assert out["applied"] == ["a1"]
    assert s.points.get(name).role == ROLE_ANCHOR  # 강등되지 않는다
    assert s.actions[0]["skipped"]
    assert s.promoted_gains["pitch.kp"][name] == pytest.approx(-1.8)


def test_escalation_never_marked_applied(env):
    """승인 목록에 에스컬레이션이 섞여도 반영도 표식도 없다 (보고 전용 계약)."""
    s = DesignSession(_small())
    esc = {"id": "e1", "verdict": "structural_limit", "case": "X", "loop": "pitch_att",
           "action": {"type": "escalate", "point": "X"}}
    s.actions = [esc]
    s.escalations = [esc]  # _stage_classify와 같은 참조 공유 상황
    out = s.apply_actions(["e1"])
    assert out["applied"] == []
    assert "applied" not in esc, "거부한 처방에 반영 표식이 붙었다"
    assert "applied" not in s.escalations[0]


def test_promoted_gains_never_override_fresh_tuning(env):
    """승격 때 굳은 게인이 나중 TUNE 결과를 덮으면 그 점은 영원히 재분류된다."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, OperatingPoint, case_name

    s = DesignSession(_small())
    name = case_name(0.5, 1000.0, 200.0)
    s.points.add(OperatingPoint(
        case=TrimCase(name=name, mach=0.5, alt=1000.0, fuel=200.0),
        role=ROLE_ANCHOR, origin="test",
    ))
    s.gain_samples = {"pitch.kp": {name: -2.4}}   # 최신 튜닝 결과
    s.promoted_gains = {"pitch.kp": {name: -1.8}}  # 이전 이터에서 굳은 값
    captured = {}
    s.fits = {}

    import claw.design.orchestrator as orch
    real_fit_slots = orch.fit_slots
    try:
        orch.fit_slots = lambda samples, points, **kw: (
            captured.update(samples) or {"tables": {}, "constants": {}, "reports": {}}
        )
        s._stage_fit(lambda *a: None)
    finally:
        orch.fit_slots = real_fit_slots
    assert captured["pitch.kp"][name] == pytest.approx(-2.4), "낡은 승격 게인이 최신 튜닝을 덮었다"


def test_nothing_verified_is_not_converged(env):
    """판정이 한 건도 없으면 '통과'가 아니다 — vacuous pass 금지."""
    s = DesignSession(_small())
    s.margin_out = {"cases": {"A": {"role": "anchor", "note": "미수렴 트림", "loops": {}}},
                    "failures": []}
    assert s.judged_count() == 0
    s._stage_classify(None, lambda *a: None)
    assert s.status == "nothing_verified"
    assert s.stage == "DONE"
    # 판정이 하나라도 있으면 정상 수렴
    s2 = DesignSession(_small())
    s2.margin_out = {"cases": {"A": {"role": "anchor",
                                     "loops": {"pitch_att": {"status": "ok"}}}},
                     "failures": []}
    s2._stage_classify(None, lambda *a: None)
    assert s2.status == "converged"


def test_gated_pause_is_deterministic(env):
    """gated 일시정지·승인·재개를 실패 유도에 기대지 않고 고정한다.

    실패를 만들어 내는 테스트는 데모 모델이 조금만 바뀌면 skip으로 조용히 no-op이
    된다 — 처방을 직접 세워 상태 전이만 검사한다.
    """
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small(mode="gated"))
    for mach, role in ((0.3, ROLE_ANCHOR), (0.4, ROLE_VALIDATION), (0.5, ROLE_ANCHOR)):
        s.points.add(OperatingPoint(
            case=TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach,
                          alt=1000.0, fuel=200.0),
            role=role, origin="test",
        ))
    v = case_name(0.4, 1000.0, 200.0)
    s.margin_out = {
        "cases": {v: {"role": "validation",
                      "loops": {"pitch_att": {"kind": "margin", "pm_deg": 40.0,
                                              "gm_db": 7.0, "status": "fail"}}}},
        "failures": [{"case": v, "loop": "pitch_att", "severity": 40.0}],
    }
    # 분류기를 태우지 않고 처방을 직접 세운다 (전이만 본다)
    s.actions = [{"id": "a1", "verdict": "simple_deficit", "case": v, "loop": "pitch_att",
                  "action": {"type": "add_validation", "point": v}}]
    applicable = [a for a in s.actions if a["action"]["type"] != "escalate"]
    assert applicable
    s.status = "awaiting_approval"
    assert s.proposed_actions() == s.actions

    out = s.apply_actions(["a1"])
    assert out["next_stage"] == "TUNE"
    assert s.status == "running" and s.iter_n == 1
    added = [p for p in s.points.by_role(ROLE_VALIDATION)
             if p.origin.startswith("add_validation")]
    assert len(added) == 2


def test_classify_gets_the_hand_design_not_the_fitted_one(monkeypatch):
    """오케스트레이터는 분류기에 **손설계 정본**을 함께 넘긴다.

    분류기의 tune_point은 design에서 부호와 탐색 브래킷만 읽는다. 오케스트레이터가
    넘기던 design_eff는 `{**손설계, **적합 상수}`라, 적합이 어떤 자리를 0으로 접으면
    그 자리를 아예 안 켠 채로 "자유 게인 최적"을 내놓는다 — "게인으로 될 일인가"의
    오판이다. 보간 게인 비교(scheduled_gains)는 그대로 design_eff를 써야 하므로
    **둘 다** 넘어가야 한다.

    분류기 자체는 대역한다 — 여기서 볼 것은 배선이다.
    """
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, ROLE_VALIDATION, OperatingPoint, case_name
    from claw.design import orchestrator as O

    s = DesignSession(_small())
    s.design = {"pitch.kp": -2.0, "roll.k_rate": -0.2}
    s.sched_constants = {"roll.k_rate": 0.0}  # 적합이 이 자리를 0으로 접었다
    for mach, role in ((0.3, ROLE_ANCHOR), (0.4, ROLE_VALIDATION)):
        s.points.add(OperatingPoint(
            case=TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach,
                          alt=1000.0, fuel=200.0), role=role, origin="test"))
    v = case_name(0.4, 1000.0, 200.0)
    s.margin_out = {"cases": {v: {"role": "validation", "loops": {}}},
                    "failures": [{"case": v, "loop": "pitch_att", "severity": 1.0}]}

    seen = {}

    def fake_classify(aircraft, points, lms, trims, tables, design, margin_out, **kw):
        seen["design"] = design
        seen["design_base"] = kw.get("design_base")
        return []

    monkeypatch.setattr(O, "classify_failures", fake_classify)
    s._stage_classify(None, lambda *a: None)

    assert seen["design_base"] == s.design, "손설계 정본이 안 넘어갔다"
    assert seen["design"]["roll.k_rate"] == 0.0, "보간 비교 기준은 실효 설계값이어야 한다"
    assert seen["design_base"]["roll.k_rate"] == -0.2


def _seed_failing_session(mode="auto", **cfg):
    """실패 하나가 걸린 세션 — 처방 효과 채점만 보기 위한 최소 상태."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small(mode=mode, **cfg))
    for mach, role in ((0.3, ROLE_ANCHOR), (0.4, ROLE_VALIDATION), (0.5, ROLE_ANCHOR)):
        s.points.add(OperatingPoint(
            case=TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach,
                          alt=1000.0, fuel=200.0), role=role, origin="test"))
    v = case_name(0.4, 1000.0, 200.0)
    s.margin_out = {"cases": {v: {"role": "validation", "loops": {
        "pitch_att": {"kind": "margin", "pm_deg": 40.0, "gm_db": 7.0,
                      "status": "fail"}}}}, "failures": []}
    s.actions = [{"id": "a1", "verdict": "simple_deficit", "case": v,
                  "loop": "pitch_att", "action": {"type": "add_validation", "point": v}}]
    return s, v


def _set_margin(s, v, pm, status):
    s.margin_out["cases"][v]["loops"]["pitch_att"] = {
        "kind": "margin", "pm_deg": pm, "gm_db": 7.0, "status": status}


def test_applied_action_is_scored_against_the_next_verification():
    """"반영됨"과 "고쳐짐"은 다르다 — 다음 판정으로 채점한다.

    처방을 내고 applied만 찍으면 무효 처방이 예산을 태우는 것을 아무도 모른다.
    실제로 앵커에 대한 게인 주입 처방이 구조적으로 무효인 채 이터를 소모했다.
    """
    s, v = _seed_failing_session()
    s.apply_actions(["a1"])
    a = s.actions[0]
    assert a["applied"] is True
    assert a["effect"]["before"]["status"] == "fail"
    assert "after" not in a["effect"], "아직 재검증 전인데 채점했다"

    _set_margin(s, v, 52.0, "ok")  # 다음 VERIFY에서 좋아졌다
    s._score_applied_actions()
    assert a["effect"]["after"]["status"] == "ok"
    assert a["effect"]["changed"] is True
    assert s.report()["ineffective_actions"] == 0


def test_ineffective_action_is_sealed_after_two_tries():
    """두 번 반영해도 판정이 안 움직이면 그 처방을 봉인한다 — 같은 카드 재발행 금지.

    봉인이 없으면 무효 처방이 예산 소진까지 같은 순환을 돈다 (fit 잔차가 tol_gain을
    넘는 앵커에서 실제로 도달 가능한 경로였다).
    """
    s, v = _seed_failing_session()
    for _ in range(2):
        s.actions = [{"id": "a1", "verdict": "simple_deficit", "case": v,
                      "loop": "pitch_att",
                      "action": {"type": "add_validation", "point": v}}]
        s.apply_actions(["a1"])
        _set_margin(s, v, 40.0, "fail")  # 아무것도 안 바뀜
        s._score_applied_actions()

    assert s.report()["ineffective_actions"] == 2
    assert s.sealed_keys() == {f"{v}|pitch_att|simple_deficit"}
    # 봉인된 처방은 다음 CLASSIFY에서 적용 대상에서 빠진다 (분류기는 대역)
    from claw.design import orchestrator as O

    s.margin_out["failures"] = [{"case": v, "loop": "pitch_att", "severity": 1.0}]
    monkey = [{"id": "a1", "verdict": "simple_deficit", "case": v, "loop": "pitch_att",
               "action": {"type": "add_validation", "point": v}, "evidence": {}}]
    orig = O.classify_failures
    try:
        O.classify_failures = lambda *a, **k: [dict(x) for x in monkey]
        s._stage_classify(None, lambda *a: None)
    finally:
        O.classify_failures = orig
    assert s.actions[0]["sealed"], "봉인 표식이 안 붙었다"
    assert s.status == "escalated", "적용할 처방이 없으면 순환을 멈춰야 한다"


def test_effect_unknown_is_not_counted_as_ineffective():
    """볼 수 없는 것을 무효로 세면 멀쩡한 처방이 봉인된다."""
    s, v = _seed_failing_session()
    s.apply_actions(["a1"])
    s.margin_out["cases"] = {}  # 그 점이 판정에서 사라졌다 (재트림 실패 등)
    s._score_applied_actions()
    assert s.actions[0]["effect"]["changed"] is True
    assert s.sealed_keys() == set()


def test_tighten_fit_moves_the_fit_parameters_and_ratchets():
    """앵커 처방(tighten_fit)은 샘플이 아니라 **적합**을 바꾼다 — 단조 래칫, 상한 있음."""
    from claw.design.orchestrator import _FIT_TIGHTEN_MAX

    # 다항 전용 처방이다 — 기본(표) 모드에는 조일 적합이 없어 건너뛴다(아래 별 테스트)
    s, v = _seed_failing_session(fit_mode="poly")
    base = s._fit_params()
    for i in range(_FIT_TIGHTEN_MAX + 2):
        s.actions = [{"id": f"t{i}", "verdict": "fit_residual", "case": v,
                      "loop": "pitch_att",
                      "action": {"type": "tighten_fit", "point": v, "slots": []}}]
        s.apply_actions([f"t{i}"])
    assert s.fit_tighten == _FIT_TIGHTEN_MAX, "상한을 넘어 조여진다 — 래칫이 안 멈춘다"
    tight = s._fit_params()
    assert tight["tol_fit"] < base["tol_fit"]
    assert tight["max_segments"] > base["max_segments"]
    assert s.actions[0].get("skipped"), "상한 도달 뒤에도 반영했다고 기록한다"


def test_refit_gains_beat_promoted_gains():
    """같은 점에 승격 게인이 먼저 들어가 있어도 새 재적합 값이 이겨야 한다.

    한 겹 setdefault이던 동안, 처음 들어간 승격 값이 계속 이겨 이터를 넘긴 새
    처방이 아무것도 안 바꿨다 — 반영은 되는데 결과가 그대로인 순환.
    """
    s, v = _seed_failing_session()
    s.promoted_gains = {"pitch.kp": {v: -1.0}}
    s.actions = [{"id": "r1", "verdict": "gain_interp_valley", "case": v,
                  "loop": "pitch_att",
                  "action": {"type": "refit_at", "point": v, "gains": {"pitch.kp": -2.5}}}]
    s.apply_actions(["r1"])
    assert s.refit_gains == {"pitch.kp": {v: -2.5}}

    captured = {}
    from claw.design import orchestrator as O
    orig = O.fit_slots
    try:
        O.fit_slots = lambda samples, points, **kw: (
            captured.update(samples=samples) or
            {"tables": {}, "constants": {}, "reports": {}})
        s._stage_fit(lambda *a: None)
    finally:
        O.fit_slots = orig
    assert captured["samples"]["pitch.kp"][v] == -2.5, "승격 게인이 재적합 값을 덮었다"


def test_verify_stage_scores_the_applied_actions(monkeypatch):
    """채점은 VERIFY가 부른다 — 함수만 있고 배선이 없으면 아무것도 채점되지 않는다.

    직접 호출하는 테스트만 있으면 이 호출을 지워도 스위트가 통과한다.
    """
    from claw.design import orchestrator as O

    s, v = _seed_failing_session()
    s.apply_actions(["a1"])
    assert "after" not in s.actions[0]["effect"]

    monkeypatch.setattr(O, "midpoint_validation_points", lambda pts, **kw: [])
    monkeypatch.setattr(O, "scheduled_margin_map", lambda *a, **k: {
        "aborted": None, "failures": [],
        "cases": {v: {"role": "validation", "loops": {"pitch_att": {
            "kind": "margin", "pm_deg": 52.0, "gm_db": 9.0, "status": "ok"}}}},
    })
    s._stage_verify(None, "fp", lambda *a: None)
    assert s.stage == "CLASSIFY"
    assert s.actions[0]["effect"]["after"]["status"] == "ok"
    assert s.actions[0]["effect"]["changed"] is True


def test_effect_notices_a_severity_move_without_a_status_change():
    """판정어가 그대로여도 부족 비율이 움직였으면 처방이 **들은** 것이다.

    fail → fail이라도 PM 40° → 44°면 그 처방은 효과가 있었다. 이 가지가 무너지면
    실제로 개선되고 있는 처방까지 2회 만에 봉인되어, 봉인 장치가 반대로 작동한다.
    (통합 실행에서 같은 status에 severity만 움직이는 쌍이 실제로 발생한다.)
    """
    s, v = _seed_failing_session()
    s.apply_actions(["a1"])
    _set_margin(s, v, 44.0, "fail")  # 여전히 fail인데 부족이 절반 이하로 줄었다
    s._score_applied_actions()
    eff = s.actions[0]["effect"]
    assert eff["before"]["status"] == eff["after"]["status"] == "fail"
    assert eff["changed"] is True, "판정어만 보고 '안 바뀌었다'고 했다"
    assert s.sealed_keys() == set()

    # 반대로 정말 그대로면 무효로 센다 (이 테스트가 항진이 아님을 보인다)
    s2, v2 = _seed_failing_session()
    s2.apply_actions(["a1"])
    _set_margin(s2, v2, 40.0, "fail")
    s2._score_applied_actions()
    assert s2.actions[0]["effect"]["changed"] is False


def test_tighten_fit_at_the_cap_is_still_scored_and_sealable():
    """조이기 상한에 닿은 처방도 **applied로 세야** 봉인될 수 있다.

    상한에서 그냥 건너뛰면 effect 레코드가 안 생겨 채점 대상에서 빠지고, 그러면
    `ineffective` 카운터가 영원히 0이라 봉인되지 않는다. 그런데 CLASSIFY는 그 카드를
    계속 applicable로 세므로, 아무것도 안 바꾸는 이터를 예산 소진까지 반복한다 —
    이 커밋이 막으려던 바로 그 순환이 봉인이 안 보이는 형태로 하나 더 생긴다.
    """
    from claw.design.orchestrator import _FIT_TIGHTEN_MAX

    s, v = _seed_failing_session(fit_mode="poly")
    for i in range(_FIT_TIGHTEN_MAX + 2):
        s.actions = [{"id": f"t{i}", "verdict": "fit_residual", "case": v,
                      "loop": "pitch_att",
                      "action": {"type": "tighten_fit", "point": v, "slots": []}}]
        s.apply_actions([f"t{i}"])
        _set_margin(s, v, 40.0, "fail")  # 상한 뒤로는 아무것도 안 바뀐다
        s._score_applied_actions()

    assert s.fit_tighten == _FIT_TIGHTEN_MAX
    over = s.actions[0]
    assert over.get("skipped"), "상한 도달 사유가 안 남았다"
    assert over.get("applied") is True, "상한에서 건너뛰면 채점도 봉인도 안 된다"
    assert s.sealed_keys() == {f"{v}|pitch_att|fit_residual"}


def test_refine_leaves_room_for_interpolation_checks(env):
    """REFINE이 점 예산을 앵커로 다 태우면 **보간 구간 검증이 이름만 남는다**.

    VERIFY의 중점 검증점은 남은 예산으로만 들어간다. 종전에는 REFINE에 예산 전부를
    줘서, 큰 격자(예산 60)에서 요구 60개 중 0개, 기본 테스트 설정(예산 24)에서도
    21개 중 2개만 들어갔다 — 판정된 자리가 전부 자기 게인이 직접 튜닝된 앵커였고,
    "스케줄 인지 검증"은 breakpoint 사이를 한 번도 보지 않은 채 converged를 냈다.
    """
    ac, stall, limits, db, design = env
    s = DesignSession(_small())
    s.run(ac, stall, limits, db, design, fingerprint="fp")
    mids = [p for p in s.points if str(p.origin).startswith("midpoint:")]
    assert mids, "보간 구간 검증점이 하나도 없다 — 예약이 듣지 않았다"
    assert s.coverage()["validation_points"] == len(mids)
    # 예약분만큼은 REFINE이 못 쓴다
    assert s.refine_report["budget"] < s.config.budget_points


def test_coverage_counts_the_point_set_not_a_stage_counter():
    """검증점 수는 **점집합 실물**로 센다 — 스테이지 카운터는 마지막 패스만 남는다.

    이터레이션이 돌면 VERIFY도 여러 번 돈다. 실측: 1차에서 15개를 넣고 2차에서
    예산 소진으로 0개를 넣었는데, 카운터로 세면 보고가 0으로 나왔다 — 실제로는
    15개 구간을 봤는데 "하나도 안 봤다"고 말하게 된다.
    """
    from claw.common.contracts import TrimCase
    from claw.design import (
        ROLE_ANCHOR, ROLE_BREAKPOINT, ROLE_VALIDATION, OperatingPoint, case_name,
    )

    s = DesignSession(_small())
    for mach, origin, role in ((0.3, "coarse", ROLE_ANCHOR),
                               (0.4, "midpoint:a|b", ROLE_VALIDATION),
                               (0.5, "midpoint:b|c", ROLE_BREAKPOINT),  # 승격된 검증점
                               (0.6, "coarse", ROLE_ANCHOR)):
        s.points.add(OperatingPoint(
            case=TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach,
                          alt=1000.0, fuel=200.0), role=role, origin=origin))
    s.validation_wanted, s.validation_added = 9, 0  # 마지막 패스는 아무것도 못 넣었다
    cov = s.coverage()
    assert cov["validation_points"] == 2, "승격된 검증점이 안 세어졌다 — 그 구간은 봤다"
    assert cov["validation_missing"] == 9


def test_coverage_gaps_say_what_the_run_did_not_look_at(env):
    """"수렴"이 무엇을 안 보고 난 수렴인지 문장으로 남는다."""
    s = DesignSession(_small())
    s.validation_wanted, s.validation_added = 21, 0
    s.refine_report = {"max_d_remaining": 0.54, "aborted": "budget_points"}
    s.margin_out = {"cases": {"x": {"loops": {}}}, "failures": []}
    gaps = s.coverage_gaps()
    assert len(gaps) == 3
    assert "한 개도 없다" in gaps[0] and "21개" in gaps[0]
    assert "0.54" in gaps[1] and "0.25" in gaps[1]
    assert "트림 미수렴 점 1개" in gaps[2]
    # 공백이 없으면 아무 말도 안 한다 (경고를 남발하면 아무도 안 읽는다)
    clean = DesignSession(_small())
    clean.margin_out = {"cases": {}, "failures": []}
    assert clean.coverage_gaps() == []


def test_ledger_gathers_what_has_no_prescription_card():
    """미달 원장은 **처방이 안 나오는 미달**까지 모은다 — 그게 대부분이다.

    종전 화면은 처방 카드가 붙은 실패만 보여 줬다. 그런데 자동 튜닝이 설계 목표를
    못 채운 자리(합격선은 넘겨 실패가 아니다), 판정 불가, 엔벨로프 경계, 튜닝을
    건너뛴 점, 트림 미수렴, 반영했는데 안 바뀐 처방은 카드가 없다 — 어디에도
    안 나왔다. 정렬은 측정 불가가 맨 앞, 그 뒤 부족 비율 내림차순이다.
    """
    s, v = _seed_failing_session()
    s.margin_out["cases"].update({
        "M0.9_h0_f200": {"role": "anchor", "loops": {}},  # 트림 미수렴
        "M0.2_h0_f40": {"role": "anchor", "outside_envelope": True, "loops": {
            "roll_att": {"kind": "margin", "pm_deg": 20.0, "gm_db": 3.0,
                         "status": "fail"}}},
        "M0.5_h0_f200": {"role": "anchor", "loops": {
            "pitch_att": {"kind": "margin", "pm_deg": float("nan"),
                          "gm_db": float("nan"), "status": "na"}}},
    })
    s.tune_meta = {
        "skipped": ["M0.9_h0_f200"],
        "slots": {"M0.3_h0_f200": {
            "pitch_rate": {"status": "infeasible", "reason": "capped",
                           "target": 0.7, "achieved": 0.63},
            "roll_att": {"status": "ok", "reason": "ok"}}},
    }
    s.apply_actions(["a1"])
    _set_margin(s, v, 40.0, "fail")
    s._score_applied_actions()

    led = s.shortfall_ledger()
    kinds = {r["kind"] for r in led}
    assert kinds == {"verify", "unjudged", "outside_envelope", "not_trimmed",
                     "skipped", "tune", "ineffective"}, kinds
    # 측정 불가가 맨 앞 (criteria.severity와 같은 규약)
    assert led[0]["severity"] is None
    sev = [r["severity"] for r in led if r["severity"] is not None]
    assert sev == sorted(sev, reverse=True), "부족 비율 내림차순이 아니다"
    # 튜닝 미달 행은 요구·달성·사유를 들고 온다
    tune_row = next(r for r in led if r["kind"] == "tune")
    assert tune_row["reason"] == "capped" and tune_row["target"] == 0.7
    assert "작동기" in tune_row["note"], "사유를 사람이 읽는 문장으로 안 냈다"
    # 목표를 맞춘 자리는 원장에 안 든다 (원장이 전 자리 목록이 되면 못 읽는다)
    assert not any(r["loop"] == "roll_att" and r["kind"] == "tune" for r in led)
    # 무효 처방이 그 사실과 함께 실린다
    ineff = next(r for r in led if r["kind"] == "ineffective")
    assert ineff["action"]["changed"] is False and ineff["action"]["applied"] is True
    assert s.report()["ledger_size"] == len(led)


def test_effect_survives_a_serialization_round_trip():
    """카드의 효과 기록이 **JSON 왕복** 뒤에도 채워진다.

    프로세스 안에서는 `actions[].effect`와 `applied_log[].effect`가 같은 dict를
    참조해서 한 번 쓰면 둘 다 갱신된다. 그런데 그 성질은 왕복에서 소리 없이
    사라진다 — gated 승인은 매번 store를 거치고(load → from_dict → apply → save),
    취소 후 재개 경로에서는 저장된 카드가 `before`만 가진 채 영영 `after`를 못 받는다.
    동일 객체에 기대지 않고 id로 찾아 넣는지 잰다.
    """
    import json

    s, v = _seed_failing_session()
    s.apply_actions(["a1"])
    # **JSON을 실제로 거친다** — to_dict()만으로는 파이썬 dict 참조가 그대로 살아
    # 있어 이 테스트가 판별력을 잃는다. 서버의 저장 경로가 하는 일 그대로다
    s2 = DesignSession.from_dict(json.loads(json.dumps(s.to_dict())))
    assert s2.actions[0]["effect"] is not s2.applied_log[0]["effect"], (
        "왕복인데 공유가 살아 있다 — 이 테스트가 재려는 상황이 아니다")

    s2.margin_out["cases"][v]["loops"]["pitch_att"] = {
        "kind": "margin", "pm_deg": 52.0, "gm_db": 9.0, "status": "ok"}
    s2._score_applied_actions()
    assert s2.applied_log[0]["effect"]["changed"] is True
    assert s2.actions[0]["effect"].get("changed") is True, (
        "왕복 뒤 카드가 효과를 못 받았다 — 화면은 반영만 보고 결과는 못 본다")


def test_bandwidth_floor_is_one_predicate():
    """대역폭 하한 판정이 한 자리에만 있다 — 세 곳에 적히면 서로 다른 물리량을 댄다.

    백오프는 설계 목표 교차(wc), 구제는 마무리 뒤의 실측 이득교차(wcp)를 같은 문턱에
    댄다. 게인이 바뀌었으니 후자가 맞지만, 식이 흩어져 있으면 한쪽만 고쳐도 아무도
    모른다. wc0이 0이거나 wc가 비유한이면 통과가 아니다.
    """
    from claw.design.tune import _bandwidth_ok

    tg = TuneTargets()  # wc_att_ok_frac = 0.2
    assert _bandwidth_ok(2.0, 10.0, tg) is True   # 0.20 — 경계 포함
    assert _bandwidth_ok(1.99, 10.0, tg) is False
    assert _bandwidth_ok(float("nan"), 10.0, tg) is False, "못 잰 교차가 통과가 됐다"
    assert _bandwidth_ok(5.0, 0.0, tg) is False, "분모가 없으면 비율이 없다"



def test_session_trim_round_trip_keeps_the_trim_reserve():
    """세션 저장·재개가 트림 여유 수치를 잃지 않는다 — 잃으면 재개 뒤 모든 트림이 「미계산」으로 읽힌다(리뷰)."""
    from claw.common.contracts import TrimCase
    from claw.design.orchestrator import _trim_from_dict, _trim_to_dict
    from claw.profile import example_profile
    from claw.trim import trim_level

    tr = trim_level(example_profile().aircraft(), TrimCase("rt", mach=0.45, alt=1000.0, fuel=200.0))
    back = _trim_from_dict(_trim_to_dict(tr))
    assert back.reserve == tr.reserve and back.reserve["de"]["frac"] > 0.0
    legacy = {k: v for k, v in _trim_to_dict(tr).items() if k != "reserve"}
    assert _trim_from_dict(legacy).reserve == {}


_STATUS_RANK_OF = {"ok": 0, "warn": 1, "fail": 2}


def test_reverify_resampled_judges_the_adopted_tables(env):
    """반출 표 재검증 — 채택되는 재양자화 표로 판정을 다시 받는다 (05 §5.1).

    세션이 검증한 것은 다항인데 웹 「채택」·apply-gains가 주입하는 것은
    resample_to_table의 근사 표다. 기본 허용치 재양자화는 판정을 **합격선 너머로**
    움직이면 안 되고(움직이면 허용치가 판정 마진보다 크다는 뜻), 게인을 크게 왜곡한
    표는 악화를 잡아내야 한다 — 델타가 0만 내는 기계는 재검증이 아니라 장식이다.

    판정은 하나도 안 움직인다 — 그리고 그 무변화가 **설계로** 선다. 요 댐퍼는 정상 상태(롤까지
    닫힌 최종 조성)에서 설계 목표 ζ_dr에 처음 닿는 크기로 튜닝되고(tune._retune_with_later_closed),
    그 목표(TuneTargets.zeta_dr 0.6)가 판정 목표선 zeta_good 0.5 위에 있다. 이 격자의 다항 검증 요
    ζ는 전부 목표 ±0.01 안(실측 0.5949~0.6089 — 목표선 위 0.095 이상)이라 재양자화(ζ 변화 ≤ 0.0043)가
    판정을 옮길 수 없다. 이력: 목표가 목표선과 같던 때(0.5)는 요 ζ가 목표선 ±0.01(0.4966~0.5060,
    warn 10)에 앉아 재양자화가 5점을 warn → ok로 옮겼다 — 좋아진 것이 아니라 목표선 위의 동전
    던지기였다. 그 전(요 2차 패스를 탐색 조성에서 못 닿은 자리에만)에는 변화 0이었지만 그 여유는
    설계가 아니라 과감쇠(ζ 0.55~0.74)였고, 요 표가 M0.2353 0.822 → M0.2519 1.262로 뛰어 다항이 그
    뜀을 뭉갠 검증점 M0.2270이 진짜 목표 미달(ζ 0.472 warn)이었다.
    """
    from claw.design.fit import resample_to_table
    from claw.tables import PolyTable, Table

    ac, stall, limits, db, design = env
    # 재양자화가 끼는 것은 **다항 모드**다 — 표 모드는 반출 표가 검증한 표 그 자체라
    # 재검증이 생략된다(그 경로는 test_table_mode_adopts_the_table_it_verified)
    s = DesignSession(_small(fit_mode="poly"))
    s.run(ac, stall, limits, db, design, fingerprint="fp")

    def export_tables(scale=1.0):
        out = {}
        for slot, t in s.sched_tables.items():
            rt = resample_to_table(t) if isinstance(t, PolyTable) else t
            out[slot] = Table({rt.axis_names[0]: rt.axes[0]}, rt.data * scale,
                              name=rt.name, extrapolate=rt.extrapolate)
        return out

    # 기본 허용치 재양자화 — 합격선 너머 판정 무변화 (트림·점 재사용이라 전 판정 자리가 대조된다)
    out = s.reverify_resampled(ac, export_tables())
    assert out["n_judged"] > 0 and out["failures"] == []
    assert out["n_judged"] == s.judged_count() and out["dropped"] == 0
    zg, zt = s.config.criteria.zeta_good, s.config.targets.zeta_dr
    yaw_z = [e["loops"]["yaw_rate"]["zeta"] for e in s.margin_out["cases"].values()
             if "yaw_rate" in e.get("loops", {})]
    # 요 댐퍼가 정상 상태 목표에 앉아 있고(과감쇠로 되돌아가면 깨진다), 그 목표가 목표선 위에 재양자화 변화(≤ 0.0043)의
    # 20배 넘는 여유를 둔다(목표를 목표선과 같게 되돌리면 깨진다)
    assert yaw_z and all(abs(z - zt) < 0.01 for z in yaw_z), sorted(yaw_z)
    assert min(yaw_z) - zg > 0.09, (min(yaw_z), zg)
    assert out["changed"] == [] and out["better"] == 0 and out["worse"] == 0, out["changed"]

    # 왜곡 표(게인 반감) — 악화를 잡아낸다. 실측: 데모 소격자에서 worse 69/판정 115
    bad = s.reverify_resampled(ac, export_tables(scale=0.5))
    assert bad["worse"] > 0 and bad["worse"] > 10 * bad["better"]
    # 좋아지는 자리는 **GM 목표선 아래 warn → ok**뿐이다 — 게인을 반으로 줄이면 이득여유가 6 dB 커진다. 레이트 루프 마진
    # 가드가 피치 댐퍼를 여유 목표에서 묶은 뒤로 이 격자의 M0.434581 피치 자세가 GM 목표선 아래(warn)라, 반감 표에서 ok가
    # 된다(실측 worse 69 · better 1 / 판정 115). 합격선 너머(fail → 무엇) 개선은 재검증이 장식이라는 뜻이다
    assert all(c["from"] == "warn" and c["to"] == "ok" for c in bad["changed"]
               if _STATUS_RANK_OF[c["to"]] < _STATUS_RANK_OF[c["from"]]), bad["changed"]
    assert all(c["from"] == "ok" or c["from"] == "warn" for c in bad["changed"])

    # 재료가 없으면 n_judged 0 + 사유 — 조용한 통과 위장 금지
    assert s.reverify_resampled(ac, {})["n_judged"] == 0
    fresh = DesignSession(_small())
    empty = fresh.reverify_resampled(ac, export_tables())
    assert empty["n_judged"] == 0 and "검증 결과가 없다" in empty["note"]


def test_yaw_target_headroom_absorbs_the_altitude_interleave_of_a_mach_table():
    """요 감쇠 목표의 여유 — 1축 마하 표가 두 설계 고도를 한 축에 번갈아 놓아도 요 판정이 warn으로 떨어지지 않는다.

    튜너는 앵커마다 목표에 처음 닿는 크기를 고르지만, 1축 표는 같은 마하 근처의 두 고도 값을 한 축에 섞는다 — 한
    고도의 앵커가 다른 고도의 분할점 값을 받는 자리에서 요 ζ가 목표 아래로 내려간다(제품 예제 500·1500 m 소격자:
    최저 목표의 97 %). 목표가 판정 목표선과 같으면(종전 0.5 = zeta_good) 그 표현 손실이 곧 warn이다 — 실측 요 판정
    58건 중 20건 warn. 목표를 목표선 위에 두면(TuneTargets.zeta_dr — 잰 표현 손실 최대 16.4 %를 덮는 0.6) 0건이다.
    둘 다 수렴·실패 0이라, 목표만이 판정을 가른다."""
    from claw.design import MarginCriteria, design_inputs
    from claw.profile import build_profile
    from claw.profile.document import load_shipped_example

    inp = design_inputs(build_profile(load_shipped_example()))

    def yaw_verdicts(targets):
        s = DesignSession(AutoDesignConfig(n_mach=5, alts=(500.0, 1500.0), fuels=(25.0,), budget_points=60,
                                           budget_iters=1, targets=targets))
        s.run(inp["aircraft"], inp["stall_table"], inp["limits"], inp["db_ranges"], inp["design"],
              rate_filters=inp["rate_filters"], actuator=inp["actuator"], fingerprint="")
        assert s.status == "converged" and s.report()["failures"] == 0
        assert s.sched_tables["yaw.k_rate"].axis_names == ("mach",), "1축 마하 표가 아니면 이 검사의 전제가 아니다"
        return [(m["zeta"], m["status"]) for e in s.margin_out["cases"].values()
                for loop, m in e.get("loops", {}).items() if loop == "yaw_rate"]

    crit = MarginCriteria()
    at_goal = yaw_verdicts(TuneTargets(zeta_dr=crit.zeta_good))
    assert sum(st == "warn" for _, st in at_goal) == 20 and len(at_goal) == 58
    assert min(z for z, _ in at_goal) == pytest.approx(0.4872, abs=1e-3)
    default = yaw_verdicts(TuneTargets())
    assert TuneTargets().zeta_dr > crit.zeta_good
    assert [st for _, st in default] == ["ok"] * 58, sorted(default)[:5]
    assert min(z for z, _ in default) == pytest.approx(0.5846, abs=1e-3)


def test_table_mode_adopts_the_table_it_verified(env):
    """기본(표) 모드 — FIT이 Table을 내고, 반출 표가 검증받은 그 표다.

    다항 모드에서는 세션이 검증한 것(다항)과 채택되는 것(재양자화 표)이 달라 재검증이
    필요했다(05 §5.1). 표 모드에는 그 간극이 없다 — 같은 점·같은 트림·같은 기준으로
    다시 돌리면 정의상 같은 결과라 계산을 생략하고 **세션 검증을 인용한다**. 인용을
    n_judged 0으로 내면 "아무것도 안 봤다"로 읽히므로 실제 판정 수를 낸다.
    """
    from claw.tables import PolyTable, Table

    ac, stall, limits, db, design = env
    s = DesignSession(_small())
    assert s.config.fit_mode == "table"
    s.run(ac, stall, limits, db, design, fingerprint="fp")
    assert s.sched_tables, "표 모드에서 스케줄 자리가 하나도 안 섰다"
    assert all(isinstance(t, Table) and not isinstance(t, PolyTable)
               for t in s.sched_tables.values())
    assert s.report()["fit_mode"] == "table"
    for rep in s.fits.values():
        assert rep["kind"] in ("table", "constant")

    # 반출 표 = 검증한 표 (서버는 값만 같은 새 객체를 넘긴다 — 값 동일성으로 짚는다)
    copies = {slot: Table({t.axis_names[0]: t.axes[0]}, t.data, name=t.name,
                          extrapolate=t.extrapolate)
              for slot, t in s.sched_tables.items()}
    rv = s.reverify_resampled(ac, copies)
    assert rv.get("identical") is True
    assert rv["n_judged"] == s.judged_count() > 0
    assert rv["worse"] == 0 and rv["better"] == 0 and rv["changed"] == []
    assert "동일" in rv["note"]

    # 값이 다른 표는 생략하지 않는다 — 생략 조건이 "표 모드"가 아니라 "같은 표"다
    moved = {slot: Table({t.axis_names[0]: t.axes[0]}, t.data * 0.5, name=t.name,
                         extrapolate=t.extrapolate)
             for slot, t in s.sched_tables.items()}
    rv2 = s.reverify_resampled(ac, moved)
    assert not rv2.get("identical") and rv2["worse"] > 0


def test_failures_are_counted_by_point_role():
    """"실패 N"만으로는 앵커 실패와 점 사이 실패가 섞인다 — 역할별로 센다.

    표 모드에서 앵커의 실효 게인은 그 점의 튜닝값인 경우가 많아 통과가 "튜닝 성립"에
    가깝다. 스케줄이 성립하는지를 말하는 것은 검증점 판정이므로 두 수가 갈려야 한다.
    """
    from claw.design import ROLE_ANCHOR, ROLE_VALIDATION, case_name

    s, v = _seed_failing_session()
    a = case_name(0.3, 1000.0, 200.0)
    assert s.points.get(v).role == ROLE_VALIDATION
    assert s.points.get(a).role == ROLE_ANCHOR
    s.margin_out["failures"] = [
        {"case": v, "loop": "pitch_att", "status": "fail"},
        {"case": a, "loop": "pitch_att", "status": "fail"},
        {"case": a, "loop": "roll_att", "status": "fail"},
        # 점 집합에 없는 케이스(옛 저장물·격자 변경) — 0으로 위장하지 않고 미상으로 센다
        {"case": "M9.9_h0_f0", "loop": "pitch_att", "status": "fail"},
    ]
    assert s.failures_by_role() == {ROLE_VALIDATION: 1, ROLE_ANCHOR: 2, "unknown": 1}
    rep = s.report()
    assert rep["failures"] == 4 and rep["failures_by_role"] == s.failures_by_role()
    # 실패가 없으면 빈 dict — "앵커 0"을 적어 넣지 않는다
    s.margin_out["failures"] = []
    assert s.report()["failures_by_role"] == {}


def test_tighten_fit_is_skipped_in_table_mode():
    """표 모드에는 조일 적합이 없다 — 사유를 달아 건너뛰고, 그래도 채점·봉인된다.

    남은 어긋남은 1축 붕괴(같은 축값의 다른 축 샘플 평균) 탓이라 조이기로는 안 풀린다.
    상한 분기와 같은 규약으로 applied로 세야 채점 대상에 들어가고, 안 듣는 처방이
    예산을 태우기 전에 봉인된다.
    """
    s, v = _seed_failing_session()  # 기본 = 표 모드
    for i in range(3):
        s.actions = [{"id": f"t{i}", "verdict": "fit_residual", "case": v,
                      "loop": "pitch_att",
                      "action": {"type": "tighten_fit", "point": v, "slots": []}}]
        s.apply_actions([f"t{i}"])
        _set_margin(s, v, 40.0, "fail")
        s._score_applied_actions()
    assert s.fit_tighten == 0, "표 모드에서 적합 조이기 래칫이 움직였다"
    assert s._fit_params()["mode"] == "table"
    skipped = s.actions[0].get("skipped")
    assert skipped and "표 모드" in skipped
    assert s.actions[0].get("applied") is True
    assert s.sealed_keys() == {f"{v}|pitch_att|fit_residual"}


def test_validation_density_reaches_the_verify_stage(env):
    """n_validation_between이 VERIFY까지 배선됐는지 — 밀도 2가 실제로 검증점을 늘린다.

    예산이 넉넉한 조건에서 같은 격자로 1·2를 돌려 midpoint 검증점 수를 대조한다.
    배선이 끊기면(스테이지가 기본값 호출) 이 대조가 같아져 잡아낸다.
    """
    ac, stall, limits, db, design = env
    counts = {}
    for n in (1, 2):
        s = DesignSession(_small(budget_points=40, n_validation_between=n))
        s.run(ac, stall, limits, db, design, fingerprint="fp")
        counts[n] = s.coverage()["validation_points"]
    assert counts[2] > counts[1] > 0


def test_fit_quality_judgement_warns_ledgers_and_reports():
    """적합 품질 판정 — 문턱 0 = 끔(na·보고만), 켜면 warn + 원장 행 + report 카운트.

    verdict·자동 처방은 없다(04 §10 [TBD] 유지 — tighten_fit이 관절을 보탤 수 있어
    처방 방향 미확정). warn의 severity는 문턱 대비 초과 비율이라 엔진 severity 축에
    끼어 정렬된다.
    """
    poly_rep = {
        "kind": "poly", "slot": "pitch.kp",
        "segments": [{"x0": 0.2, "x1": 0.5}, {"x0": 0.5, "x1": 0.8}],
        "scale": 2.0,
        "joints": [{"x": 0.5, "value_jump": 0.0, "slope_jump": 10.0}],  # norm 3.0
        "cross_axis_residual": 0.0,
    }
    const_rep = {"kind": "constant", "slot": "yaw.k_rate", "value": 0.4}

    # 문턱 끔(기본값) — 지표는 붙되 판정은 na, 원장·카운트 0
    s = DesignSession(_small())
    s.fits = {"pitch.kp": dict(poly_rep), "yaw.k_rate": dict(const_rep)}
    s._judge_fit_quality()
    assert s.fits["pitch.kp"]["quality"]["status"] == "na"
    assert "문턱 미설정" in s.fits["pitch.kp"]["quality"]["note"]
    assert s.fits["yaw.k_rate"]["quality"]["status"] == "na"
    assert not [r for r in s.shortfall_ledger() if r["kind"] == "fit_quality"]

    # 문턱 켬 — norm 3.0 > 1.5 → warn, severity = 초과 비율 1.0
    s2 = DesignSession(_small(fit_slope_jump_max=1.5))
    s2.fits = {"pitch.kp": dict(poly_rep), "yaw.k_rate": dict(const_rep)}
    s2._judge_fit_quality()
    q = s2.fits["pitch.kp"]["quality"]
    assert q["status"] == "warn" and q["slope_jump_norm_max"] == pytest.approx(3.0)
    assert s2.fits["yaw.k_rate"]["quality"]["status"] == "na"  # 상수는 판정 대상이 아니다
    rows = [r for r in s2.shortfall_ledger() if r["kind"] == "fit_quality"]
    assert len(rows) == 1 and rows[0]["loop"] == "pitch.kp"
    assert rows[0]["severity"] == pytest.approx(3.0 / 1.5 - 1.0)
    assert s2.report()["fit_quality_warns"] == 1

    # 넉넉한 문턱 — ok (켰다는 사실이 na와 구별돼야 한다)
    s3 = DesignSession(_small(fit_slope_jump_max=10.0))
    s3.fits = {"pitch.kp": dict(poly_rep)}
    s3._judge_fit_quality()
    assert s3.fits["pitch.kp"]["quality"]["status"] == "ok"

    with pytest.raises(ValueError, match="fit_slope_jump_max"):
        _small(fit_slope_jump_max=-0.1)


def test_fit_quality_flows_through_a_real_run(env):
    """실행 통합 — 기본값(끔)으로 돌아도 전 자리에 지표·status가 붙고 warns는 0이다."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small())
    s.run(ac, stall, limits, db, design, fingerprint="fp")
    assert s.fits, "적합 보고가 비어 있다"
    for slot, rep in s.fits.items():
        assert rep["quality"]["status"] in ("na", "ok", "warn"), slot
    assert s.report()["fit_quality_warns"] == 0
    # 왕복 후에도 품질이 남는다 (fits 직렬화 경유)
    s2 = DesignSession.from_dict(s.to_dict())
    assert s2.report()["fit_quality_warns"] == 0
    assert all("quality" in rep for rep in s2.fits.values())


# ── 스케줄 적합 축 (마하 표 — 기체 문서가 받는 모양) ──


def test_sched_axes_config_defaults_to_mach_and_round_trips():
    """기본은 마하만이다 — 산출 표가 가는 곳(기체 문서 law.gain_tables·게인 탭)이 마하 1축 표만 받는다."""
    from claw.design.orchestrator import DEFAULT_SCHED_AXES

    c = AutoDesignConfig()
    assert c.sched_axes == DEFAULT_SCHED_AXES == ("mach",)
    assert c.to_dict()["sched_axes"] == ["mach"]  # JSON 모양 — 서버 /design/defaults가 그대로 낸다
    wide = AutoDesignConfig(sched_axes=["mach", "alt"])
    assert wide.sched_axes == ("mach", "alt")
    assert AutoDesignConfig.from_dict(wide.to_dict()) == wide
    # 필드가 생기기 전 저장물 — 재개하면 마하 제한으로 이어 돈다
    legacy = {k: v for k, v in c.to_dict().items() if k != "sched_axes"}
    assert AutoDesignConfig.from_dict(legacy).sched_axes == ("mach",)
    for bad in ((), ("speed",), ("mach", "mach"), "mach"):
        with pytest.raises(ValueError, match="sched_axes"):
            AutoDesignConfig(sched_axes=bad)


def _two_alt_fit_session(**cfg):
    """고도 변동이 지배적인 게인 샘플이 걸린 세션 — FIT 한 판만 보기 위한 최소 상태."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, OperatingPoint, case_name

    s = DesignSession(_small(**cfg))
    machs, alts = (0.3, 0.4, 0.5, 0.6), (1000.0, 5000.0)
    for a in alts:
        for m in machs:
            s.points.add(OperatingPoint(
                case=TrimCase(name=case_name(m, a, 200.0), mach=m, alt=a, fuel=200.0),
                role=ROLE_ANCHOR, origin="test"))
    s.gain_samples = {"pitch.kp": {case_name(m, a, 200.0): -1.0 - 1.0 * m - 0.0004 * a
                                   for a in alts for m in machs}}
    return s


def test_fit_stage_schedules_on_mach_even_when_altitude_dominates():
    """FIT이 config.sched_axes 안에서만 축을 고른다 — 종전에는 고도 표가 나와 apply-gains가 422였다."""
    s = _two_alt_fit_session()
    s._stage_fit(lambda *a: None)
    assert s.sched_tables["pitch.kp"].axis_names == ("mach",)
    assert s.fits["pitch.kp"]["axes_excluded"] == ("alt",)  # 뺀 축은 보고에 남는다
    # 축을 넓히면(API 전용) 종전처럼 지배 축 — 이 설정의 결과는 문서에 반영할 수 없다
    wide = _two_alt_fit_session(sched_axes=("mach", "alt", "fuel"))
    wide._stage_fit(lambda *a: None)
    assert wide.sched_tables["pitch.kp"].axis_names == ("alt",)


def test_multi_altitude_run_exports_only_mach_tables(env):
    """고도 둘로 실제로 돌려도 반출 표는 전부 마하 표다 (재검증도 그 표로 한다)."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(alts=(1000.0, 5000.0), budget_iters=1))
    s.run(ac, stall, limits, db, design, fingerprint="fp")
    assert s.sched_tables, "스케줄 표가 없다 — 전제가 바뀌었다"
    assert {t.axis_names for t in s.sched_tables.values()} == {("mach",)}


# ── 작동기 (기체 문서 → 설계·검증·분류) ──


def test_actuator_comes_from_the_aircraft_unless_the_config_names_one():
    """config가 없음이면 기체 작동기, 수치면 config가 이긴다 — 칸마다 따로, 출처를 말한다."""
    from claw.design.orchestrator import ACTUATOR_FALLBACK

    s = DesignSession(_small())
    assert s.config.actuator_wn is None and s.config.actuator_zeta is None
    fb = s.actuator_used()
    assert (fb["wn"], fb["zeta"]) == (ACTUATOR_FALLBACK["wn"], ACTUATOR_FALLBACK["zeta"])
    assert fb["source"] == {"wn": "default", "zeta": "default"}  # 폴백을 기체 값인 척하지 않는다

    s.actuator = {"wn": 18.0, "zeta": 0.5}
    kw = s._act_kw()
    assert (kw["actuator_wn"], kw["actuator_zeta"]) == (18.0, 0.5)
    assert s.actuator_used()["source"] == {"wn": "profile", "zeta": "profile"}

    s2 = DesignSession(_small(actuator_wn=25.0))
    s2.actuator = {"wn": 18.0, "zeta": 0.5}
    used = s2.actuator_used()
    assert (used["wn"], used["zeta"]) == (25.0, 0.5)
    assert used["source"] == {"wn": "config", "zeta": "profile"}
    assert s2.report()["actuator"] == used  # 판정 조성의 일부로 보고에 실린다

    for bad in (0.0, -3.0):
        with pytest.raises(ValueError, match="actuator_wn"):
            AutoDesignConfig(actuator_wn=bad)
    # 필드 뜻이 바뀌기 전 저장물은 30·0.7을 **명시**로 들고 있다 — 재개해도 그 값 그대로
    old = {**AutoDesignConfig().to_dict(), "actuator_wn": 30.0, "actuator_zeta": 0.7}
    s3 = DesignSession(AutoDesignConfig.from_dict(old))
    s3.actuator = {"wn": 18.0, "zeta": 0.5}
    assert s3.actuator_used()["source"] == {"wn": "config", "zeta": "config"}


def test_a_session_saved_before_the_actuator_fields_still_loads():
    """필드가 생기기 전 저장물(세션 actuator·config sched_axes 없음, config 작동기 30·0.7 명시) —
    재개 라우트의 from_dict가 KeyError로 409를 내지 않고, 저장 당시의 작동기를 그대로 이어 쓴다."""
    d = DesignSession(_small(mode="gated")).to_dict()
    d.pop("actuator")
    d["config"].pop("sched_axes")
    d["config"].update(actuator_wn=30.0, actuator_zeta=0.7)
    s = DesignSession.from_dict(d)
    assert s.actuator == {} and s.config.sched_axes == ("mach",)
    s.actuator = {"wn": 18.0, "zeta": 0.5}  # 재개 호출이 기체 작동기를 넘겨도
    used = s.actuator_used()
    assert (used["wn"], used["zeta"]) == (30.0, 0.7)  # 저장 당시 명시값이 이긴다
    assert used["source"] == {"wn": "config", "zeta": "config"}


def test_run_hands_the_aircraft_actuator_to_tune_and_verify(env, monkeypatch):
    """run(actuator=…)가 튜닝·검증까지 실제로 도달한다 — 종전에는 config의 30·0.7이 늘 이겼다."""
    from claw.design import orchestrator as O

    ac, stall, limits, db, design = env
    seen = {"tune": [], "verify": []}
    real_tune, real_map = O.tune_points, O.scheduled_margin_map

    def spy_tune(*a, **kw):
        seen["tune"].append((kw["actuator_wn"], kw["actuator_zeta"]))
        return real_tune(*a, **kw)

    def spy_map(*a, **kw):
        seen["verify"].append((kw["actuator_wn"], kw["actuator_zeta"]))
        return real_map(*a, **kw)

    monkeypatch.setattr(O, "tune_points", spy_tune)
    monkeypatch.setattr(O, "scheduled_margin_map", spy_map)
    s = DesignSession(_small(budget_iters=1))
    s.run(ac, stall, limits, db, design, actuator={"wn": 18.0, "zeta": 0.5}, fingerprint="fp")
    assert seen["tune"] and set(seen["tune"]) == {(18.0, 0.5)}
    assert seen["verify"] and set(seen["verify"]) == {(18.0, 0.5)}
    # 왕복 뒤 재개 호출이 작동기를 안 줘도(None = 안 바꾼다) 저장된 기체 값을 이어 간다
    s2 = DesignSession.from_dict(s.to_dict())
    assert s2.actuator == {"wn": 18.0, "zeta": 0.5}
    assert s2.to_dict() == s.to_dict()


def test_design_inputs_reads_the_actuator_from_the_document():
    """서버·생성 스크립트가 쓰는 한 경로 — 기체 문서의 작동기 wn·zeta가 그대로 실린다."""
    from claw.design import design_inputs
    from claw.profile import build_profile, load_example

    doc = load_example()
    doc["actuator"]["params"].update(wn=18.0, zeta=0.55)
    inp = design_inputs(build_profile(doc))
    assert inp["actuator"] == {"wn": 18.0, "zeta": 0.55}
    assert set(inp) == {"aircraft", "stall_table", "limits", "db_ranges", "design",
                        "rate_filters", "actuator"}


# ── CLASSIFY 진행 보고·협조적 취소 ──


def _classify_ready_session():
    s, v = _seed_failing_session(mode="gated")
    s.margin_out["failures"] = [{"case": v, "loop": "pitch_att", "severity": 40.0}]
    s.stage, s.status = "CLASSIFY", "running"
    return s, v


def test_classify_reports_progress_and_cancel_resumes_at_classify(monkeypatch):
    """CLASSIFY도 실패마다 진행을 보고하고, 그 콜백으로 취소가 먹는다 — 재개는 CLASSIFY부터.

    종전에는 분류가 끝날 때까지 콜백이 없어(실측 실패 56개 ≈ 25 s, 325개 ≈ 100 s) 진행 막대가
    직전 VERIFY 메시지에 멈춰 있었고 [중단]도 분류가 끝나야 먹었다.
    """
    from claw.design import orchestrator as O

    calls = []

    def fake_classify(*a, on_progress=None, **kw):
        for i in range(3):
            calls.append(i)
            if on_progress is not None and on_progress(i + 1, 3, f"classify p{i} pitch_att"):
                return []
        return [{"id": "a9", "case": "x", "loop": "pitch_att", "verdict": "simple_deficit",
                 "action": {"type": "add_validation", "point": "x"}}]

    monkeypatch.setattr(O, "classify_failures", fake_classify)
    s, _ = _classify_ready_session()
    before = list(s.actions)
    msgs = []

    def cancel_in_classify(done, total, message):
        msgs.append(message)
        return message.startswith("[CLASSIFY] classify p1")

    report = s.run(None, None, None, None, {}, on_progress=cancel_in_classify)
    assert report["status"] == "cancelled" and s.stage == "CLASSIFY"
    assert calls == [0, 1], "취소 뒤에도 분류를 계속했다"
    assert s.actions == before, "취소된 분류가 처방 목록을 바꿨다"
    assert msgs[:2] == ["[CLASSIFY] classify p0 pitch_att", "[CLASSIFY] classify p1 pitch_att"]

    # 왕복 후 재개 — CLASSIFY를 처음부터 다시 돌아 승인 대기로 간다
    s2 = DesignSession.from_dict(s.to_dict())
    calls.clear()
    report2 = s2.run(None, None, None, None, {}, on_progress=lambda *a: False)
    assert calls == [0, 1, 2]
    assert report2["status"] == "awaiting_approval"
    assert [a["id"] for a in s2.proposed_actions()] == ["a9"]


@pytest.mark.parametrize("fit_mode", ["table", "poly"])
def test_sched_axes_restriction_holds_in_both_fit_modes(fit_mode):
    """v1.47 표현 전환(fit_mode)과 스케줄 축 제한(sched_axes)은 직교한다 — 어느 표현이든 FIT은 마하 표."""
    from claw.tables import PolyTable

    s = _two_alt_fit_session(fit_mode=fit_mode)
    assert s._fit_params()["mode"] == fit_mode and s._fit_params()["axes"] == ("mach",)
    s._stage_fit(lambda *a: None)
    tab = s.sched_tables["pitch.kp"]
    assert tab.axis_names == ("mach",)
    assert isinstance(tab, PolyTable) == (fit_mode == "poly")
    rep = s.fits["pitch.kp"]
    assert rep["kind"] == fit_mode
    assert rep["axes_detected"] == ("mach", "alt") and rep["axes_excluded"] == ("alt",)
    # 표 모드는 반출 표가 곧 검증한 표다 — 제한이 그 성질을 깨지 않는다(값이 같은 새 객체도 동일로 본다)
    if fit_mode == "table":
        from claw.design.orchestrator import _same_tables
        from claw.tables import Table

        copy_ = {k: Table({t.axis_names[0]: t.axes[0]}, t.data, name=t.name, extrapolate=t.extrapolate)
                 for k, t in s.sched_tables.items()}
        assert _same_tables(s.sched_tables, copy_)


def _failed_roll_damper_session(**cfg):
    """튜닝이 한 점에서 롤 댐퍼를 못 찾은 세션 — FIT 한 판만 보기 위한 최소 상태 (쇼케이스 표 모드 실측의 모양).

    그 점의 roll.k_rate 표본은 자리값 0, roll.kp·ki는 0 댐퍼 위에서 튜닝된 값이다."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_ANCHOR, OperatingPoint, case_name

    s = DesignSession(_small(**cfg))
    machs = (0.100, 0.1039, 0.1077, 0.1116, 0.1154)
    names = [case_name(m, 0.0, 25.0) for m in machs]
    for m, n in zip(machs, names):
        s.points.add(OperatingPoint(case=TrimCase(name=n, mach=m, alt=0.0, fuel=25.0),
                                    role=ROLE_ANCHOR, origin="test"))
    bad = names[2]
    s.gain_samples = {
        "roll.k_rate": dict(zip(names, (-0.52, -0.50, 0.0, -0.46, -0.44))),
        "roll.kp": dict(zip(names, (2.15, 2.07, 0.32, 1.93, 1.86))),
        "roll.ki": dict(zip(names, (0.95, 0.91, 0.035, 0.83, 0.80))),
        "pitch.kp": dict(zip(names, (-1.25, -1.24, -1.21, -1.20, -1.19))),
    }
    ok = {"status": "ok", "reason": "ok"}
    s.tune_meta = {"skipped": [], "status": {}, "notes": {}, "slots": {
        n: {"pitch_rate": dict(ok), "yaw_rate": dict(ok), "pitch_att": dict(ok), "roll_att": dict(ok),
            "roll_rate": ({"status": "infeasible", "reason": "sign_mismatch"} if n == bad else dict(ok))}
        for n in names}}
    return s, machs, names, bad


def test_fit_excludes_samples_whose_tuning_failed_and_reports_them():
    """튜닝이 성립하지 않은 표본(tune.SLOT_DESIGN_FAILED)과 그 위에서 튜닝된 같은 축 자세 게인은 적합에서 빠진다.

    사용자 합의 규칙 — 실패한 데이터는 표에 넣지 않는다. 종전 표 모드는 그 점의 자리값을 분할점에 그대로
    놓아 롤 댐퍼가 한 점에서 정확히 0이었고(VERIFY는 통과했다 — 롤 대역폭 판정이 실패 기준이 아니다),
    그 위의 roll.ki가 이웃의 1/26이었다. 뺀 점의 게인은 이웃 보간이고, 보고에 값·사유가 남는다."""
    s, machs, names, bad = _failed_roll_damper_session()
    s._stage_fit(lambda *a: None)
    rk = s.sched_tables["roll.k_rate"]
    assert np.all(rk.data < 0.0), "실패 표본(자리값 0)이 롤 댐퍼 표에 들어갔다"
    assert rk.interp(mach=machs[2]) == pytest.approx(-0.48, rel=0.02)
    assert s.sched_tables["roll.ki"].interp(mach=machs[2]) == pytest.approx(0.87, rel=0.02)
    # 튜닝이 성립한 자리(피치)는 그 점 표본을 그대로 쓴다 — 점 단위가 아니라 자리 단위 제외다
    assert s.sched_tables["pitch.kp"].interp(mach=machs[2]) == pytest.approx(-1.21)
    rep = s.report()
    rows = {(r["slot"], r["point"]): r for r in rep["excluded_samples"]}
    assert set(rows) == {("roll.k_rate", bad), ("roll.kp", bad), ("roll.ki", bad)}
    assert rows[("roll.k_rate", bad)]["basis"] == "own"
    assert rows[("roll.kp", bad)]["basis"] == "rate_loop" and rows[("roll.kp", bad)]["value"] == 0.32
    assert all(r["reason"] == "sign_mismatch" and r["loop"] == "roll_rate" for r in rows.values())
    assert rep["exclusion_withheld"] == []
    # 원장의 튜닝 미달 행이 "이 점의 표 값은 튜닝값이 아니라 이웃 보간"을 들고 온다
    row = next(r for r in s.shortfall_ledger()
               if r["kind"] == "tune" and r["point"] == bad and r["loop"] == "roll_rate")
    assert row["fit_excluded"] == ["roll.k_rate", "roll.ki", "roll.kp"]
    # 화면이 이미 그리는 공백 목록에도 한 줄 — "수렴"이 튜닝값이 아닌 점을 품고 있다는 사실
    assert any("적합에서 뺐다" in g and "점 1곳" in g for g in rep["coverage_gaps"])
    # 저장·재개 왕복에서도 같은 보고
    assert DesignSession.from_dict(s.to_dict()).report()["excluded_samples"] == rep["excluded_samples"]


def test_withheld_exclusion_is_a_coverage_gap():
    """표본이 2개 미만으로 남아 제외를 보류한 자리는 보고의 공백이다 — 표가 실패 표본을 담는다는 사실이 보여야 한다."""
    s, machs, names, bad = _failed_roll_damper_session()
    for n in names[:4]:  # 5점 중 4점에서 롤 댐퍼 실패 → 1점만 남는다
        s.tune_meta["slots"][n]["roll_rate"] = {"status": "infeasible", "reason": "no_stable_gain"}
    s._stage_fit(lambda *a: None)
    rep = s.report()
    assert rep["exclusion_withheld"] == ["roll.k_rate", "roll.ki", "roll.kp"]
    assert not [r for r in rep["excluded_samples"] if r["slot"].startswith("roll.")]
    gaps = [g for g in rep["coverage_gaps"] if "제외를 보류" in g]
    assert len(gaps) == 3 and gaps[0].startswith("roll.k_rate:")


def test_fit_exclusion_map_follows_the_axis_and_keeps_working_dampers():
    """제외 대상 — 자기 실패는 그 자리, 레이트 실패는 **뒤에 닫히는** 같은 축 자리까지. 목표 미달·캡은 빼지 않는다.

    요 댐퍼 실패는 횡축이라 롤 댐퍼(요 = 0인 프리픽스에서 찾은 값)와 roll_att(roll.kp·ki)를 끌고 가고 피치는
    건드리지 않는다. 자세 자리가 스스로도 실패했으면 그 사유가 남는다. target_unreached·capped는 작동하는 댐퍼를
    낸 것이라 표본이다. 규칙은 tune.failed_gain_slots 한 곳이다."""
    s = DesignSession(_small())
    s.tune_meta = {"slots": {
        "P1": {"yaw_rate": {"reason": "no_stable_gain"}, "roll_rate": {"reason": "ok"},
               "pitch_rate": {"reason": "capped"}, "pitch_att": {"reason": "ok"},
               "roll_att": {"reason": "margin_floor"}},
        "P2": {"pitch_rate": {"reason": "sign_mismatch"}, "yaw_rate": {"reason": "target_unreached"},
               "roll_rate": {"reason": "ok"}, "pitch_att": {"reason": "rescued"},
               "roll_att": {"reason": "ok"}},
    }}
    ex = s._fit_exclusions()
    assert set(ex) == {"yaw.k_rate", "roll.k_rate", "roll.kp", "roll.ki", "pitch.k_rate", "pitch.kp", "pitch.ki"}
    assert ex["yaw.k_rate"] == {"P1": {"loop": "yaw_rate", "reason": "no_stable_gain", "basis": "own"}}
    # 롤 댐퍼 자체는 P1에서 성립(ok)했지만 요가 꺼진(0) 프리픽스에서 찾은 값이다 — 출하 조성의 답이 아니다
    assert ex["roll.k_rate"] == {"P1": {"loop": "yaw_rate", "reason": "no_stable_gain", "basis": "rate_loop"}}
    assert ex["roll.kp"] == {"P1": {"loop": "roll_att", "reason": "margin_floor", "basis": "own"}}
    assert ex["pitch.kp"] == ex["pitch.ki"] == {
        "P2": {"loop": "pitch_rate", "reason": "sign_mismatch", "basis": "rate_loop"}}
    # P2의 요는 target_unreached(작동하는 댐퍼)라 롤 댐퍼를 끌고 가지 않는다
    assert "P2" not in ex["roll.k_rate"]
    assert "P2" not in ex.get("yaw.k_rate", {}) and "P1" not in ex["pitch.k_rate"]
