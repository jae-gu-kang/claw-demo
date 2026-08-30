"""M17 orchestrator 검증 — 전자동 종결, gated 일시정지·승인·재개, 왕복, 취소."""

import pytest

from claw.design import AutoDesignConfig, DesignSession
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
    c = AutoDesignConfig(alts=(1000.0,))
    assert AutoDesignConfig.from_dict(c.to_dict()) == c


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

    s, v = _seed_failing_session()
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

    monkeypatch.setattr(O, "midpoint_validation_points", lambda pts: [])
    monkeypatch.setattr(O, "scheduled_margin_map", lambda *a, **k: {
        "aborted": None, "failures": [],
        "cases": {v: {"role": "validation", "loops": {"pitch_att": {
            "kind": "margin", "pm_deg": 52.0, "gm_db": 9.0, "status": "ok"}}}},
    })
    s._stage_verify(None, "fp", lambda *a: None)
    assert s.stage == "CLASSIFY"
    assert s.actions[0]["effect"]["after"]["status"] == "ok"
    assert s.actions[0]["effect"]["changed"] is True
