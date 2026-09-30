"""M17 orchestrator 검증 — 전자동 종결, gated 일시정지·승인·재개, 왕복, 취소."""

import copy
import functools

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.design import AutoDesignConfig, DesignSession, TuneTargets
from claw.design.knots import union_knots
from claw.design.points import ROLE_DESIGN, OperatingPoint, case_name
from claw.fcl.demo import demo_design_gains
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_stall_table,
    make_demo_structural_limits,
)
from claw.opspace.verdict import VerdictContext
from claw.profile import example_profile


@pytest.fixture(scope="module")
def env():
    return (
        make_demo_aircraft(),
        make_demo_stall_table(),
        make_demo_structural_limits(),
        make_demo_db_ranges(),
        demo_design_gains(),
    )


@functools.lru_cache(maxsize=None)
def _vctx():
    """예제 기체의 조건 판정 문맥 — 트림 탭과 같은 생성자(from_profile)."""
    return VerdictContext.from_profile(example_profile())


def _small(**over):
    base = dict(n_mach=3, alts=(1000.0,), fuels=(200.0,), budget_points=24,
                budget_iters=3, mode="auto")
    base.update(over)
    return AutoDesignConfig(**base)


def test_auto_mode_reaches_terminal(env):
    """전자동 — 예산 내에서 converged/escalated/budget_exhausted 중 하나로 끝난다."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small())
    report = s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    assert s.stage == "DONE"
    assert report["status"] in ("converged", "escalated", "budget_exhausted")
    # "실패 0"이 통과인지 미검증인지 — 판정 수가 갈라 준다 (vacuous pass 배제)
    assert report["judged"] > 0, "판정이 한 건도 없는데 종결됐다"
    assert report["points"]["design"] >= 3 and set(report["points"]) == {"design", "validation"}
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
    report = s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
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
    report2 = s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    assert report2["status"] in (
        "converged", "escalated", "budget_exhausted", "awaiting_approval"
    )


def test_roundtrip_preserves_session(env):
    ac, stall, limits, db, design = env
    s = DesignSession(_small())
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
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

    report = s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp",
                   on_progress=cancel_early)
    assert report["status"] == "cancelled"
    # 왕복 후 재개 — 처음부터가 아니라 남은 스테이지부터
    s2 = DesignSession.from_dict(s.to_dict())
    report2 = s2.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
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
    """튜닝 목표가 합격선보다 느슨하면 제출 시점에 막고, 권장선보다만 느슨하면 경고로 남긴다.

    기본값끼리 이미 정합이라는 첫 단정이 핵심이다: 종전에는 gm_good_db 10 dB >
    targets.gm_db 8 dB로 어긋나 있어 튜닝 성공점이 구조적으로 warn이었다.
    권장선 충돌은 기준 통합 ⑤ S5부터 거절이 아니라 경고다(사용자 승인 동작 변경) —
    합격은 지키는 설정이라 모순이 아니고, 대신 report가 그 사실을 말해야 한다.
    """
    from claw.design import MarginCriteria, TuneTargets

    assert AutoDesignConfig().target_warnings() == []  # 출하 기본값은 정합이어야 한다
    # 권장선(gm_good_db 8·zeta_good 0.5)보다만 느슨 → 만들어지고 경고가 붙는다
    cfg = AutoDesignConfig(targets=TuneTargets(gm_db=7.0))
    (w,) = cfg.target_warnings()
    assert "gm_db 7" in w and "gm_good_db 8" in w and "권장선" in w
    cfg2 = AutoDesignConfig(targets=TuneTargets(zeta_dr=0.4))
    (w2,) = cfg2.target_warnings()
    assert "zeta_dr 0.4" in w2 and "zeta_good" in w2
    # 경고는 저장 필드가 아니라 criteria·targets에서 다시 계산된다 — 왕복해도 그대로
    assert AutoDesignConfig.from_dict(cfg.to_dict()).target_warnings() == [w]
    assert "target_warnings" not in cfg.to_dict()
    # report가 싣는다 — 화면·저장물이 warn의 원인이 설정임을 알 수 있어야 한다
    assert DesignSession(cfg).report()["target_warnings"] == [w]
    assert DesignSession(AutoDesignConfig()).report()["target_warnings"] == []
    # 합격선보다 느슨하면 여전히 거절이다 (서버 422)
    with pytest.raises(ValueError, match="gm_db"):
        AutoDesignConfig(targets=TuneTargets(gm_db=5.0))  # < gm_min_db 6
    with pytest.raises(ValueError, match="pm_deg"):
        AutoDesignConfig(criteria=MarginCriteria(pm_min_deg=60.0))
    # 금지가 아니라 **정합 요구**다 — 판정선을 올리면서 목표도 함께 올리면 경고도 없다
    assert AutoDesignConfig(criteria=MarginCriteria(gm_good_db=12.0),
                            targets=TuneTargets(gm_db=12.0)).target_warnings() == []


def test_add_validation_inserts_flanking_midpoints(env):
    """simple_deficit 처방 — 검증점 좌우 이웃과의 중점 2개를 넣는다 (예산 내)."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small())
    for mach, role in ((0.3, ROLE_DESIGN), (0.4, ROLE_VALIDATION), (0.5, ROLE_DESIGN)):
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
    assert s.stage == "TUNE"  # 플랜트 편입이 아니므로 리파인으로 돌아가지 않는다


def test_add_validation_respects_point_budget(env):
    """예산이 꽉 차 있으면 검증점을 더 넣지 않는다 (종료 보장의 한 겹)."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small(budget_points=4))
    for mach, role in ((0.3, ROLE_DESIGN), (0.4, ROLE_VALIDATION),
                       (0.5, ROLE_DESIGN), (0.6, ROLE_DESIGN)):
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


def test_promote_on_a_design_point_is_skipped_not_fatal(env):
    """설계점에 편입 처방이 오더라도 세션을 죽이지 않는다 (안전망).

    분류기는 설계점에 편입을 내지 않지만, 옛 세션의 대기 카드(breakpoint 승격 — 게인 동봉)는 올 수 있다. 여기서
    ValueError가 나면 run()이 못 잡아 트림·튜닝 전량이 저장 없이 사라진다. 옛 카드의 게인은 옛 규약대로 기록한다.
    """
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_DESIGN, OperatingPoint, case_name

    s = DesignSession(_small())
    name = case_name(0.5, 1000.0, 200.0)
    s.points.add(OperatingPoint(
        case=TrimCase(name=name, mach=0.5, alt=1000.0, fuel=200.0),
        role=ROLE_DESIGN, origin="test",
    ))
    s.actions = [{"id": "a1", "verdict": "gain_interp_valley", "case": name, "loop": "pitch_att",
                  "action": {"type": "promote", "to": "breakpoint", "point": name,
                             "gains": {"pitch.kp": -1.8}}}]
    out = s.apply_actions(["a1"])  # 터지면 안 된다
    assert out["applied"] == ["a1"]
    assert s.points.get(name).role == ROLE_DESIGN
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
    from claw.design import ROLE_DESIGN, OperatingPoint, case_name

    s = DesignSession(_small())
    name = case_name(0.5, 1000.0, 200.0)
    s.points.add(OperatingPoint(
        case=TrimCase(name=name, mach=0.5, alt=1000.0, fuel=200.0),
        role=ROLE_DESIGN, origin="test",
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
    s.margin_out = {"cases": {"A": {"role": "design", "note": "미수렴 트림", "loops": {}}},
                    "failures": []}
    assert s.judged_count() == 0
    s._stage_classify(None, lambda *a: None)
    assert s.status == "nothing_verified"
    assert s.stage == "DONE"
    # 판정이 하나라도 있으면 정상 수렴
    s2 = DesignSession(_small())
    s2.margin_out = {"cases": {"A": {"role": "design",
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
    from claw.design import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small(mode="gated"))
    for mach, role in ((0.3, ROLE_DESIGN), (0.4, ROLE_VALIDATION), (0.5, ROLE_DESIGN)):
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
    from claw.design import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, case_name
    from claw.design import orchestrator as O

    s = DesignSession(_small())
    s.design = {"pitch.kp": -2.0, "roll.k_rate": -0.2}
    s.sched_constants = {"roll.k_rate": 0.0}  # 적합이 이 자리를 0으로 접었다
    for mach, role in ((0.3, ROLE_DESIGN), (0.4, ROLE_VALIDATION)):
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
    from claw.design import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small(mode=mode, **cfg))
    for mach, role in ((0.3, ROLE_DESIGN), (0.4, ROLE_VALIDATION), (0.5, ROLE_DESIGN)):
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
    """설계점 처방(tighten_fit — 다항 모드)은 샘플이 아니라 **적합**을 바꾼다 — 단조 래칫, 상한 있음."""
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

    monkeypatch.setattr(O, "validation_points", lambda pts, knots, **kw: [])
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
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    mids = [p for p in s.points if str(p.origin).startswith("midpoint:")]
    cov = s.coverage()
    # 절점 구간 중점이 이미 설계점이어도(보강의 이분 중점 — 흔하다) 다음 빈 내분점으로 옮겨 표본 밖 검증점을 둔다 —
    # 설계점 판정은 적합 잔차라 검증으로 세지 않는다(리뷰 정정)
    assert mids, "보간 구간을 하나도 안 봤다 — 예약이 듣지 않았다"
    assert "validation_at_design_points" not in cov
    assert cov["validation_points"] == len(mids)
    assert cov["validation_missing"] == 0
    # 예약분만큼은 REFINE이 못 쓴다
    assert s.refine_report["budget"] < s.config.budget_points


def test_coverage_counts_the_point_set_not_a_stage_counter():
    """검증점 수는 **점집합 실물**로 센다 — 스테이지 카운터는 마지막 패스만 남는다.

    이터레이션이 돌면 VERIFY도 여러 번 돈다. 실측: 1차에서 15개를 넣고 2차에서
    예산 소진으로 0개를 넣었는데, 카운터로 세면 보고가 0으로 나왔다 — 실제로는
    15개 구간을 봤는데 "하나도 안 봤다"고 말하게 된다.
    """
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_DESIGN, ROLE_VALIDATION, OperatingPoint, case_name

    s = DesignSession(_small())
    for mach, origin, role in ((0.3, "coarse", ROLE_DESIGN),
                               (0.4, "midpoint:a|b", ROLE_VALIDATION),
                               (0.5, "midpoint:b|c", ROLE_VALIDATION),
                               (0.6, "coarse", ROLE_DESIGN)):
        s.points.add(OperatingPoint(
            case=TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach,
                          alt=1000.0, fuel=200.0), role=role, origin=origin))
    s.points.promote(case_name(0.5, 1000.0, 200.0), reason="plant_variation")  # 편입된 검증점 — 출처는 promoted:
    s.validation_wanted, s.validation_added = 9, 0  # 마지막 패스는 아무것도 못 넣었다
    cov = s.coverage()
    assert cov["validation_points"] == 2, "편입된 검증점이 안 세어졌다 — 그 구간은 봤다"
    assert cov["validation_missing"] == 9


def test_coverage_never_counts_a_design_point_as_a_validation():
    """설계점과 겹친 내분점은 검증 수에 들지 않는다 — 옮긴 수(midpoints_at_design_points)는 정보로만 낸다.

    종전(이관 3단계 초안)은 절점 구간 중점에 선 설계점을 「검증」으로 세었다(validation_at_design) — 트림·판정 안 된 보강
    점과, 편입된 검증점(중점 출처 이력으로 이미 센다)까지 두 번. 설계점은 그 자신이 적합 표본이라 거기 판정은 보간이
    아니라 적합 잔차다."""
    from claw.common.contracts import TrimCase
    from claw.design import ROLE_DESIGN, OperatingPoint, case_name

    s = DesignSession(_small())
    for mach in (0.3, 0.4, 0.5):
        s.points.add(OperatingPoint(case=TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach, alt=1000.0,
                                                  fuel=200.0), role=ROLE_DESIGN, origin="coarse"))
    from claw.design.knots import KnotSet

    s.knot_sets = {"common": KnotSet(name="common", coords=[0.3, 0.5], source="user")}
    s.table_knots = {"pitch.kp": "common"}
    from claw.design.schedmap import validation_candidates

    cand = validation_candidates(s.points.designable(), [0.3, 0.5])
    s.validation_moved, s.validation_unplaceable = cand["moved"], cand["unplaceable"]
    s.validation_wanted, s.validation_added = 1, 0
    cov = s.coverage()
    assert cov["validation_points"] == 0 and cov["midpoints_at_design_points"] == 1
    gaps = " ".join(s.coverage_gaps())
    assert "한 개도 없다" in gaps, "설계점 겹침을 검증으로 세어 공백을 숨겼다"


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
        "M0.9_h0_f200": {"role": "design", "loops": {}},  # 트림 미수렴
        "M0.2_h0_f40": {"role": "design", "outside_envelope": True, "loops": {
            "roll_att": {"kind": "margin", "pm_deg": 20.0, "gm_db": 3.0,
                         "status": "fail"}}},
        "M0.5_h0_f200": {"role": "design", "loops": {
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
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")

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
    # 설계 줄(1000 m)의 점만 — 이관 4단계부터 검증점에 요구영역 경계점(100·3000 m 행 끝)이 들어오는데, 그 고도는 요 댐퍼를
    # 튜닝한 줄이 아니라 ζ가 목표에서 떨어져 있다(실측 0.539~0.540 — 여전히 목표선 0.5 위). 이 검사는 튜닝한 줄의 설계 여유다
    yaw_z = [e["loops"]["yaw_rate"]["zeta"] for n, e in s.margin_out["cases"].items()
             if "yaw_rate" in e.get("loops", {}) and s.points.get(n).case.alt == 1000.0]
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
    60건 중 30건 warn(이관 3단계 — 표가 설계점마다가 아니라 공통 마하 절점 5개 위 최소제곱이라 표가 튜닝값을 지나지
    않는다. 설계점과 겹친 구간 중점 6곳의 검증점을 ¼·¾로 옮긴 뒤 29 → 30. 종전 표본 마하마다 분할점일 때 15건, 이관
    2단계 전 coarse_grid 58건 중 20건). 목표를 목표선 위에 두면
    (TuneTargets.zeta_dr — 잰 표현 손실 최대 16.4 %를 덮는 0.6) 0건이다.
    둘 다 수렴·실패 0이라, 목표만이 판정을 가른다."""
    from claw.design import MarginCriteria, design_inputs
    from claw.profile import build_profile
    from claw.profile.document import load_shipped_example

    inp = design_inputs(build_profile(load_shipped_example()))

    def yaw_verdicts(targets):
        s = DesignSession(AutoDesignConfig(n_mach=5, alts=(500.0, 1500.0), fuels=(25.0,), budget_points=60,
                                           budget_iters=1, targets=targets))
        s.run(inp["aircraft"], inp["stall_table"], inp["limits"], inp["db_ranges"], inp["design"],
              verdict_ctx=inp["verdict_ctx"], rate_filters=inp["rate_filters"], actuator=inp["actuator"],
              fingerprint="")
        assert s.status == "converged" and s.report()["failures"] == 0
        assert s.sched_tables["yaw.k_rate"].axis_names == ("mach",), "1축 마하 표가 아니면 이 검사의 전제가 아니다"
        return [(m["zeta"], m["status"]) for e in s.margin_out["cases"].values()
                for loop, m in e.get("loops", {}).items() if loop == "yaw_rate"]

    crit = MarginCriteria()
    at_goal = yaw_verdicts(TuneTargets(zeta_dr=crit.zeta_good))
    assert sum(st == "warn" for _, st in at_goal) == 30 and len(at_goal) == 60
    assert min(z for z, _ in at_goal) == pytest.approx(0.4828, abs=1e-3)
    default = yaw_verdicts(TuneTargets())
    assert TuneTargets().zeta_dr > crit.zeta_good
    assert [st for _, st in default] == ["ok"] * 60, sorted(default)[:5]
    assert min(z for z, _ in default) == pytest.approx(0.5791, abs=1e-3)  # 절점 위 표(이관 3단계) — 종전 0.5844


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
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
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
    """"실패 N"만으로는 설계점 실패와 점 사이 실패가 섞인다 — 역할별로 센다.

    설계점 실패는 절점 부족(표가 표본을 못 지나감 — add_knot), 검증점 실패는 표본 사이 보간이라 처방이 갈린다.
    """
    from claw.design import ROLE_DESIGN, ROLE_VALIDATION, case_name

    s, v = _seed_failing_session()
    a = case_name(0.3, 1000.0, 200.0)
    assert s.points.get(v).role == ROLE_VALIDATION
    assert s.points.get(a).role == ROLE_DESIGN
    s.margin_out["failures"] = [
        {"case": v, "loop": "pitch_att", "status": "fail"},
        {"case": a, "loop": "pitch_att", "status": "fail"},
        {"case": a, "loop": "roll_att", "status": "fail"},
        # 점 집합에 없는 케이스(옛 저장물·격자 변경) — 0으로 위장하지 않고 미상으로 센다
        {"case": "M9.9_h0_f0", "loop": "pitch_att", "status": "fail"},
    ]
    assert s.failures_by_role() == {ROLE_VALIDATION: 1, ROLE_DESIGN: 2, "unknown": 1}
    rep = s.report()
    assert rep["failures"] == 4 and rep["failures_by_role"] == s.failures_by_role()
    # 실패가 없으면 빈 dict — "설계점 0"을 적어 넣지 않는다
    s.margin_out["failures"] = []
    assert s.report()["failures_by_role"] == {}


def test_tighten_fit_is_skipped_in_table_mode():
    """표 모드에는 조일 적합이 없다 — 사유를 달아 건너뛰고, 그래도 채점·봉인된다.

    분류기는 표 모드에 이 카드를 더는 내지 않는다(설계점 괴리 → add_knot). 옛 세션의 대기 카드만 여기 온다.
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
        # 예산 60 — 요구영역 격자(M0.3~0.55)에서는 REFINE이 좁은 구간을 더 채워 40이면 밀도 2의 검증점이 예산에 막혔다(이관 2단계)
        s = DesignSession(_small(budget_points=60, n_validation_between=n))
        s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
        cov = s.coverage()
        counts[n] = cov["validation_points"]
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
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
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
    from claw.design import ROLE_DESIGN, OperatingPoint, case_name

    s = DesignSession(_small(**cfg))
    machs, alts = (0.3, 0.4, 0.5, 0.6), (1000.0, 5000.0)
    for a in alts:
        for m in machs:
            s.points.add(OperatingPoint(
                case=TrimCase(name=case_name(m, a, 200.0), mach=m, alt=a, fuel=200.0),
                role=ROLE_DESIGN, origin="test"))
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
    # 두 고도 모두 요구영역(초안 100~3000 m) 안이어야 한다 — 5000 m는 요구영역 밖 행이라 점이 없다(이관 2단계)
    s = DesignSession(_small(alts=(1000.0, 3000.0), budget_iters=1))
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    assert s.sched_tables, "스케줄 표가 없다 — 전제가 바뀌었다"
    assert {p.case.alt for p in s.points if p.origin == "coarse"} == {1000.0, 3000.0}
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
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), actuator={"wn": 18.0, "zeta": 0.5}, fingerprint="fp")
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
                        "rate_filters", "actuator", "verdict_ctx"}
    # 조건 판정 문맥은 트림 탭과 같은 생성자에서 — 같은 조건에 같은 채택·제외 사유 (이관 8단계)
    from claw.opspace.verdict import VerdictContext
    want, got = VerdictContext.from_profile(build_profile(doc)), inp["verdict_ctx"]
    for f in ("db_ranges", "q_max", "mach_no", "limiter_margin", "fuel_max"):
        assert getattr(got, f) == getattr(want, f), f  # trim_bounds는 표 객체라 값 비교가 없다


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

    report = s.run(None, None, None, None, {}, verdict_ctx=None, on_progress=cancel_in_classify)
    assert report["status"] == "cancelled" and s.stage == "CLASSIFY"
    assert calls == [0, 1], "취소 뒤에도 분류를 계속했다"
    assert s.actions == before, "취소된 분류가 처방 목록을 바꿨다"
    assert msgs[:2] == ["[CLASSIFY] classify p0 pitch_att", "[CLASSIFY] classify p1 pitch_att"]

    # 왕복 후 재개 — CLASSIFY를 처음부터 다시 돌아 승인 대기로 간다
    s2 = DesignSession.from_dict(s.to_dict())
    calls.clear()
    report2 = s2.run(None, None, None, None, {}, verdict_ctx=None, on_progress=lambda *a: False)
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
    from claw.design import ROLE_DESIGN, OperatingPoint, case_name

    s = DesignSession(_small(**cfg))
    machs = (0.100, 0.1039, 0.1077, 0.1116, 0.1154)
    names = [case_name(m, 0.0, 25.0) for m in machs]
    for m, n in zip(machs, names):
        s.points.add(OperatingPoint(case=TrimCase(name=n, mach=m, alt=0.0, fuel=25.0),
                                    role=ROLE_DESIGN, origin="test"))
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


# ── 이관 2단계 — COARSE는 요구영역의 기본 격자, 커버리지는 요구영역 기준 (05 §11.13) ──────────────────────────────


def _region_ctx(**over):
    """예제 판정 문맥의 요구영역만 바꾼 것 — 기본값은 확정 영역(초안 대신)."""
    import dataclasses

    ctx = _vctx()
    region = dataclasses.replace(ctx.region, confirmed=True, source="profile", **over)
    return dataclasses.replace(ctx, region=region, cache={})


def test_coarse_uses_the_region_base_grid_and_reports_a_draft_as_unconfirmed(env):
    """구 합성 기체는 operating_region이 없어 trim_grid 초안(M0.3~0.55 · 100/1000/3000 m · 200 kg)이 요구영역이다 — 쓰되
    미확정이라 완료라 하지 않는다. 격자는 초안의 기본 격자에서 나온다(옛 coarse_grid는 실속 하한 × 1.1 ~ M_NO 0.75)."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small())  # n_mach 3 · 1000 m · 200 kg — 설정이 영역의 격자 명세를 덮는다
    report = s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    coarse = [p for p in s.points if p.origin == "coarse"]
    assert [p.case.mach for p in coarse] == [0.3, 0.425, 0.55]  # 요구 마하 전 구간 — 물리로 깎지 않는다
    assert report["coarse_source"] == "region_base_grid"
    rc = report["region_coverage"]
    assert (rc["source"], rc["confirmed"], rc["complete"]) == ("draft:trim_grid", False, False)
    assert any("미확정" in r for r in rc["reasons"])
    assert rc["points"] >= 3 and sum(rc["by_category"].values()) == rc["points"]
    assert s.region_grid["selection"]["rule"] == "all"


def test_model_gap_points_stay_in_the_session_untrimmed_and_the_region_is_not_complete(env):
    """모델 부족 점(DB 마하 0.9 밖)은 버리지 않고 목록에 남는다 — 트림·튜닝·검증은 하지 않고, 요구영역은 완료가 아니다."""
    ac, stall, limits, db, design = env
    ctx = _region_ctx(mach=(0.5, 0.95), alt=(1000.0, 1000.0))
    s = DesignSession(_small(n_mach=4, budget_iters=1))
    report = s.run(ac, stall, limits, db, design, verdict_ctx=ctx, fingerprint="fp")
    gap = next(p for p in s.points if p.case.mach == 0.95)
    assert gap.trimmable is False and gap.verdict["exclusion"] == {"category": "model", "reasons": ["model_gap"]}
    assert gap.name not in s.trims and gap.name not in s.margin_out["cases"]
    assert gap.name not in report["skipped"]  # 튜닝 「건너뜀」(트림 미수렴·경계)과 다르다 — 요구영역 커버리지가 센다
    assert report["coverage"]["pre_trim_excluded"] == 1
    assert any("트림 전에 제외" in g for g in report["coverage_gaps"])
    rc = report["region_coverage"]
    assert rc["confirmed"] is True and rc["by_category"]["model"] == 1 and rc["complete"] is False
    assert any("채택하지 못한 요구 조건" in r for r in rc["reasons"])
    s2 = DesignSession.from_dict(s.to_dict())
    assert s2.to_dict() == s.to_dict() and s2.report()["region_coverage"] == rc


def test_without_a_region_the_legacy_grid_runs_and_says_the_requirement_is_undefined(env):
    import dataclasses

    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1))
    report = s.run(ac, stall, limits, db, design, verdict_ctx=dataclasses.replace(_vctx(), region=None, cache={}),
                   fingerprint="fp")
    assert report["coarse_source"] == "coarse_grid" and s.region_grid is None
    assert max(p.case.mach for p in s.points if p.origin == "coarse") == pytest.approx(0.75)  # 옛 규칙 — M_NO까지
    rc = report["region_coverage"]
    assert (rc["source"], rc["complete"], rc["points"]) == (None, False, 0)
    assert rc["reasons"][0].startswith("요구영역 미정의")


def test_coarse_picks_representative_points_within_its_budget(env):
    """기본 격자가 COARSE 몫(점 예산의 절반)을 넘으면 행 끝점을 남기고 공통 좌표를 솎는다 — 뺀 점은 커버리지가 센다."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(n_mach=11, alts=(100.0, 3000.0), budget_points=20, budget_iters=1))
    s.run(ac, stall, limits, db, design, verdict_ctx=_region_ctx(), fingerprint="fp")
    sel = s.region_grid["selection"]
    assert sel["rule"] == "thinned" and sel["budget"] == 10 and sel["selected"] <= 10
    coarse = [p for p in s.points if p.origin == "coarse"]
    for alt in (100.0, 3000.0):
        row = sorted(p.case.mach for p in coarse if p.case.alt == alt)
        assert (row[0], row[-1]) == (0.3, 0.55)
    rc = s.report()["region_coverage"]
    # 뺀 점 중 보강·검증점으로 나중에 세션에 들어온 것(같은 좌표)은 더는 미선택이 아니다. 설정이 명세를 덮었으므로
    # 요구(분모)는 영역 자신의 명세(6점 마하 · 3고도)다 — 덮은 격자에만 있는 좌표는 미선택으로 세지 않는다
    req = {p["name"] for p in s.region_grid["requirement"]["points"]}
    assert rc["by_category"]["unselected"] == sum(n not in s.points and n in req for n in sel["dropped"]) > 0
    assert rc["by_category"]["omitted"] > 0 and rc["complete"] is False


def _coverage_session(**state):
    """region_coverage를 상태만으로 재는 세션 — 확정 영역 한 행 M0.3·0.4·0.5, 0.4는 고르지 않았다."""
    s = DesignSession(_small())
    s.region_grid = {"source": "profile", "confirmed": True, "axis": [0.3, 0.4, 0.5], "selection": {},
                     "rows": [{"alt": 1000.0, "fuel": 200.0, "bounds": [0.3, 0.5], "n": 3, "state": "not_run"}],
                     "points": [{"name": case_name(m, 1000.0, 200.0), "mach": m, "alt": 1000.0, "fuel": 200.0,
                                 "state": "not_run", "selected": m != 0.4} for m in (0.3, 0.4, 0.5)]}
    s.coarse_source = "region_base_grid"
    for m in (0.3, 0.5):
        pt = OperatingPoint(case=TrimCase(name=case_name(m, 1000.0, 200.0), mach=m, alt=1000.0, fuel=200.0),
                            role=ROLE_DESIGN, origin="coarse")
        pt.verdict = {"region": {"status": "in", "confirmed": True}, "adopted": True, "exclusion": None,
                      "trim": {"status": "computable", "reasons": []}}
        pt.trimmable = True
        s.points.add(pt)
    s.margin_out = {"cases": {p.name: {"loops": {"pitch_rate": {"status": "ok"}}} for p in s.points}}
    s.status = "converged"
    for k, v in state.items():
        setattr(s, k, v)
    return s


def test_region_is_complete_only_when_every_required_condition_is_adopted_and_verified():
    rc = _coverage_session().region_coverage()
    assert rc["complete"] is True and rc["reasons"] == []
    assert rc["by_category"] == {"adopted": 2, "trim": 0, "model": 0, "limits": 0, "region": 0, "unselected": 1, "omitted": 0,
                                 "not_run": 0}
    # 설계가 끝나지 않았으면
    assert _coverage_session(status="budget_exhausted").region_coverage()["complete"] is False
    # 채택점 하나가 검증 판정을 못 받았으면 — 그 점도, 그 사이의 고르지 않은 점도 덮이지 않는다
    s = _coverage_session()
    s.margin_out["cases"][case_name(0.5, 1000.0, 200.0)]["outside_envelope"] = True
    rc = s.region_coverage()
    assert rc["complete"] is False and any("덮지 못한 요구 조건 2점" in r for r in rc["reasons"])
    # 한 점이 채택되지 않았으면(부분 성공) — 나머지가 다 통과해도 요구영역 완료가 아니다
    s = _coverage_session()
    pt = s.points.get(case_name(0.5, 1000.0, 200.0))
    pt.trimmable, pt.verdict = False, {**pt.verdict, "adopted": False,
                                       "exclusion": {"category": "limits", "reasons": ["q_max"]}}
    rc = s.region_coverage()
    assert rc["complete"] is False and rc["by_category"]["limits"] == 1
    # 경계표가 덮지 않는 행이 있으면
    s = _coverage_session()
    s.region_grid["rows"].append({"alt": 3000.0, "fuel": 200.0, "bounds": None, "n": 0, "state": "undefined"})
    assert s.region_coverage()["rows_undefined"] == [{"alt": 3000.0, "fuel": 200.0, "state": "undefined"}]
    assert s.region_coverage()["complete"] is False


def test_a_config_grid_override_does_not_shrink_the_requirement(env):
    """설정의 고도 목록(1000 m 하나)이 요구영역 명세(100/1000/3000 m)를 덮어도 요구는 줄지 않는다 — 분모는 영역 자신의
    기본 격자 명세다. 설정이 뺀 요구 행의 점은 「덮지 못함」이고 완료가 아니다(리뷰 재현: 이전엔 complete True)."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1))
    report = s.run(ac, stall, limits, db, design, verdict_ctx=_region_ctx(), fingerprint="fp")
    rc = report["region_coverage"]
    assert rc["complete"] is False
    assert any(r.startswith("격자 명세를 설정이 덮음 — 요구 행 2개 미포함") for r in rc["reasons"]), rc["reasons"]
    assert rc["by_category"]["omitted"] > 0 and sum(rc["by_category"].values()) == rc["points"]
    # COARSE가 실제로 쓴 명세와 요구 명세를 세션에 남긴다(직렬화 왕복)
    assert s.region_grid["spec"] == {"n_mach": 3, "alts": [1000.0], "fuels": [200.0]}
    assert s.region_grid["requirement_spec"] == {"n_mach": 6, "alts": [100.0, 1000.0, 3000.0], "fuels": [200.0]}
    s2 = DesignSession.from_dict(s.to_dict())
    assert s2.report()["region_coverage"] == rc


def test_without_an_override_the_requirement_is_the_coarse_base_grid():
    """덮지 않으면(요구 기록 없음 — 옛 기록 포함) 기본 격자가 곧 요구다 — 설정 덮음 사유가 서지 않는다."""
    rc = _coverage_session().region_coverage()
    assert rc["by_category"]["omitted"] == 0 and not any("설정이 덮음" in r for r in rc["reasons"])


def test_preflight_rejects_a_coarse_budget_below_the_row_ends_before_the_job():
    """COARSE 몫(4)이 행 끝점 6점(3고도 × 2)보다 작으면 제출 전 검사가 ValueError — 서버가 202 전에 422로 낸다."""
    import dataclasses

    s = DesignSession(_small(alts=(100.0, 1000.0, 3000.0), budget_points=4))
    with pytest.raises(ValueError, match="예산"):
        s.preflight(_region_ctx())
    assert DesignSession(_small()).preflight(_region_ctx())["floor"] == 2
    # 옛 경로(요구영역 없음)는 coarse_grid의 점 수 곱과 같은 검사
    with pytest.raises(ValueError, match="초과"):
        DesignSession(_small(n_mach=5, alts=(100.0, 1000.0, 3000.0), budget_points=12)).preflight(
            dataclasses.replace(_vctx(), region=None, cache={}))
    # 재개(COARSE 뒤)는 이미 격자가 있다 — 재지 않는다
    s.stage = "TUNE"
    assert s.preflight(_region_ctx()) is None


def test_a_session_without_a_base_grid_record_is_unknown_not_undefined():
    """이관 2단계 전 세션(기본 격자 기록 없음·coarse_source None)은 기체에 요구영역이 있을 수 있다 — 「미정의」가 아니라 「모름」."""
    s = DesignSession(_small())
    rc = s.region_coverage()
    assert rc["source"] is None and rc["complete"] is False
    assert rc["reasons"][0].startswith("요구영역 커버리지 모름")


# ── 설계점과 절점 분리 (이관 3단계 — 05 §11.5) ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def ran(env):
    """한 번 끝까지 돈 작은 세션(표 모드·요구영역 격자) — 절점 기록·왕복·옛 세션 재개가 같은 실행을 본다."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1))
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    return s


def test_knots_come_from_the_region_axis_not_from_the_design_points(env, ran):
    """절점 수는 설계점 수와 무관하다 — REFINE이 설계점을 더해도 표의 분할점은 요구영역 공통 마하 좌표다.

    종전 표 모드는 튜닝한 마하마다 분할점이라 설계점이 곧 절점이었다(쇼케이스 36점). 보강을 끈 실행(refine_tol 큼)과
    같은 절점을 쓰는지로 본다."""
    ac, stall, limits, db, design = env
    flat = DesignSession(_small(budget_iters=1, refine_tol=50.0))
    flat.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    n_ran = len(ran.points.by_role("design"))
    n_flat = len(flat.points.by_role("design"))
    assert n_ran > n_flat, "보강이 설계점을 더해야 시험이 된다"
    axis = ran.region_grid["axis"]
    assert ran.knot_sets["common"].coords == flat.knot_sets["common"].coords == axis
    assert ran.knot_sets["common"].source == "base_axis"
    for s in (ran, flat):
        for slot, t in s.sched_tables.items():
            assert set(np.round(t.axes[0], 9)) <= set(np.round(axis, 9)), slot
    rep = ran.report()
    assert rep["knots"]["shared"] is True
    assert rep["knots"]["tables"] == {slot: len(t.axes[0]) for slot, t in ran.sched_tables.items()}


def test_session_round_trip_keeps_the_knot_sets(ran):
    d = ran.to_dict()
    assert d["knot_sets"]["common"]["coords"] == ran.knot_sets["common"].coords
    assert d["config"]["knots"]["rule"] == "base_axis"
    s2 = DesignSession.from_dict(d)
    assert s2.to_dict() == d
    assert s2.knot_record() == ran.knot_record()
    assert s2.report()["knots"] == ran.report()["knots"]


def test_old_session_resumes_with_the_samples_rule_and_the_same_tables(ran):
    """절점 기록이 없는 옛 세션 — 표의 마하 축이 곧 절점이었으므로 그 합집합을 samples 집합으로 세운다.

    「옛 표」는 **이관 3단계 전 경로 그대로**(fit_slots knots_by_slot=None — 튜닝한 마하마다 평균) 짓는다 — 새 samples
    규칙으로 지으면 같은 코드끼리 비교하는 셈이다. 적합 제외 표본도 하나 넣는다: 한 마하의 pitch 표본이 전부 빠지면 옛
    표에는 그 마하가 없지만 합집합 절점에는 (다른 자리 표 때문에) 있다 — 그 절점은 받치는 표본이 없어 그 표에서만 빠져야
    같은 표가 나온다. 옛 설정에 knots가 없으면 규칙도 samples로 읽는다 — 새 기본값(base_axis)으로 읽으면 재개한 세션의
    표 형상이 조용히 바뀐다."""
    import copy

    from claw.design.fit import fit_slots
    from claw.design.knots import COMMON
    from claw.design.tune import REASON_NO_STABLE_GAIN

    legacy = DesignSession(_small(budget_iters=1))
    for key in ("points", "trims", "gain_samples", "region_grid", "coarse_source"):
        setattr(legacy, key, copy.deepcopy(getattr(ran, key)))
    legacy.lms = ran.lms
    legacy.tune_meta = copy.deepcopy(ran.tune_meta)
    # 표본이 한 점뿐인 안쪽 마하를 골라 그 점의 피치 레이트 튜닝을 실패로 — pitch.k_rate(own)·pitch.kp/ki(rate_loop)가 빠진다
    by_mach: dict = {}
    for n in legacy.gain_samples["pitch.kp"]:
        by_mach.setdefault(round(legacy.points.get(n).case.mach, 9), []).append(n)
    inner = sorted(by_mach)[1:-1]
    m_x = next(m for m in inner if len(by_mach[m]) == 1)
    victim = by_mach[m_x][0]
    legacy.tune_meta.setdefault("slots", {}).setdefault(victim, {})["pitch_rate"] = {"reason": REASON_NO_STABLE_GAIN}
    old_fit = fit_slots(legacy.gain_samples, legacy.points, exclude=legacy._fit_exclusions(), knots_by_slot=None,
                        **legacy._fit_params())
    assert victim in {r["point"] for r in old_fit["reports"]["pitch.kp"]["excluded_samples"]}, "제외가 걸려야 시험이 된다"
    assert not np.any(np.isclose(old_fit["tables"]["pitch.kp"].axes[0], m_x)), "옛 표에 제외 마하가 없어야 한다"
    legacy.sched_tables, legacy.sched_constants, legacy.fits = (old_fit["tables"], old_fit["constants"],
                                                                old_fit["reports"])
    legacy.stage = "FIT"
    d = legacy.to_dict()
    for k in ("knot_sets", "table_knots"):
        d.pop(k)
    d["config"].pop("knots")
    old = DesignSession.from_dict(d)
    assert old.config.knots["rule"] == "samples"
    assert old.knot_sets[COMMON].source == "samples"
    assert any(np.isclose(old.knot_sets[COMMON].coords, m_x)), "다른 자리 표가 그 마하를 절점 합집합에 넣는다"
    before = {slot: (list(t.axes[0]), list(t.data)) for slot, t in old.sched_tables.items()}
    old._stage_fit(lambda *a: None)
    for slot, t in old.sched_tables.items():
        assert list(t.axes[0]) == pytest.approx(before[slot][0]), slot
        assert list(t.data) == pytest.approx(before[slot][1], abs=1e-12), slot
    assert m_x in old.fits["pitch.kp"]["unsupported_knots"] or any(
        np.isclose(old.fits["pitch.kp"]["unsupported_knots"], m_x))


def test_add_knot_action_promotes_and_splits_only_the_named_tables(env, ran):
    """add_knot 반영 — 검증점이면 설계점으로 편입(다음 스테이지 TUNE — 튜닝해야 표본이 선다), 이름 댄 표만 새 절점.

    같은 점의 다른 자리 카드가 또 오면 편입은 건너뛰되(applied로 센다) 절점은 그 자리 표에 더한다."""
    import copy

    from claw.common.contracts import TrimCase
    from claw.design import OperatingPoint
    from claw.opspace.verdict import condition_verdict
    from claw.trim import trim_level

    s = DesignSession.from_dict(copy.deepcopy(ran.to_dict()))
    # 절점 구간 0.3 자리의 검증점(보강의 이분 좌표와 겹치지 않는 비율) — 트림·판정을 실어 둔다(편입 뒤 TUNE이 이 트림으로 튜닝한다)
    k = s.knot_sets["common"].coords
    row = next(p for p in s.points if p.role == "design").case
    mach = round(k[0] + 0.3 * (k[1] - k[0]), 6)
    case = TrimCase(name=case_name(mach, row.alt, row.fuel), mach=mach, alt=row.alt, fuel=row.fuel)
    tr = trim_level(env[0], case, fingerprint="fp")
    s.trims[case.name] = tr
    v = OperatingPoint(case=case, role="validation", origin="test")
    v.verdict = condition_verdict(tr, _vctx())
    v.trimmable = v.verdict["adopted"]
    assert v.trimmable
    s.points.add(v)
    s.actions = [
        {"id": "k1", "verdict": "gain_interp_valley", "case": v.name, "loop": "pitch_att",
         "action": {"type": "add_knot", "point": v.name, "mach": mach, "slots": ["pitch.kp", "pitch.ki"],
                    "promote": True}},
        {"id": "k2", "verdict": "gain_interp_valley", "case": v.name, "loop": "roll_att",
         "action": {"type": "add_knot", "point": v.name, "mach": mach, "slots": ["roll.kp", "roll.ki"],
                    "promote": True}},
    ]
    out = s.apply_actions(["k1", "k2"])
    assert out == {"applied": ["k1", "k2"], "next_stage": "TUNE"}
    assert s.points.get(v.name).role == "design" and s.points.get(v.name).origin == "promoted:gain_interp_valley"
    # 둘째 카드는 편입이 이미 됐지만 절점은 더했다 — 건너뜀이 아니다(한 일이 있는 카드). 편입 불필요는 참고로 남는다
    assert "skipped" not in s.actions[1] and s.actions[1]["knot"]["added"] is True
    assert s.actions[1]["notes"][0].startswith("이미 design")
    assert s.table_knots["pitch.kp"] == s.table_knots["pitch.ki"] == "pitch.ki+pitch.kp"
    assert s.table_knots["roll.kp"] == "roll.ki+roll.kp"
    assert s.table_knots["yaw.k_rate"] == "common" and mach not in s.knot_sets["common"].coords
    assert mach in s.knot_sets["pitch.ki+pitch.kp"].coords
    assert s.actions[0]["knot"]["split"] == ["pitch.ki", "pitch.kp"]
    # 표본이 생기기 전(TUNE 전) FIT은 그 절점을 표본 없는 절점으로 뺄 수 있다 — 튜닝 뒤에는 편입점이 표본이다
    s.run(*env[:4], env[4], verdict_ctx=_vctx(), fingerprint="fp")
    assert v.name in s.gain_samples["pitch.kp"]
    kp = s.sched_tables["pitch.kp"]
    assert np.any(np.isclose(kp.axes[0], mach)), "편입점 마하 절점이 표에 서야 한다"
    assert s.knot_record()["tables"]["pitch.kp"]["shared"] is True  # 두 표가 새 집합을 함께 쓴다
    assert s.knot_record()["tables"]["yaw.k_rate"]["set"] == "common"


# ── 검증점 생성 · 요약 격자 · 보강 (이관 4단계 — 05 §11.6~11.8) ─────────────────────────────


def _session_digest(s) -> str:
    """점(이름·역할·출처) · 자리별 판정 · 표 값 · 상태 · 판정 수의 지문 — 규칙이 같으면 비트 단위로 같다."""
    import hashlib
    import json

    pts = sorted((p.name, p.role, p.origin) for p in s.points)
    cases = {n: {lp: m.get("status") for lp, m in e.get("loops", {}).items()} for n, e in sorted(s.margin_out["cases"].items())}
    tabs = {k: [list(map(float, t.axes[0])), [float(x) for x in t.data.ravel()]] for k, t in sorted(s.sched_tables.items())}
    blob = json.dumps([pts, cases, tabs, s.status, s.judged_count()], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def test_validation_config_defaults_to_the_plan_and_an_old_session_reads_the_midpoint_rule():
    cfg = AutoDesignConfig()
    assert cfg.validation == {"rule": "plan", "conditions": None, "mode": "full", "boundary": True, "extras": []}
    assert cfg.reinforce == {"tol": None, "max_points": 24, "max_depth": 3, "max_time_s": None}
    d = cfg.to_dict()
    assert AutoDesignConfig.from_dict(d).validation == cfg.validation
    old = {k: v for k, v in d.items() if k not in ("validation", "reinforce")}
    back = AutoDesignConfig.from_dict(old)
    assert back.validation["rule"] == "midpoint" and back.reinforce == cfg.reinforce
    with pytest.raises(ValueError, match="validation"):
        AutoDesignConfig(validation={"rule": "dense"})
    with pytest.raises(ValueError, match="reinforce"):
        AutoDesignConfig(reinforce={"tol": -1.0})


def test_midpoint_rule_is_the_v170_verification_bit_for_bit(env):
    """rule "midpoint"는 v1.70 VERIFY 그대로다 — 같은 설정의 v1.70(ce8052e) 실행에서 잰 지문(점·판정·표·상태)을 고정한다.
    옛 세션 재개가 같은 검증점과 같은 판정을 내는 근거다."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1, validation={"rule": "midpoint"}))
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    assert _session_digest(s) == "05d0ba34b8632f4a"
    rep = s.report()
    assert rep["summary_grid"] is None and rep["reinforcement"] is None
    assert rep["validation"]["rule"] == "midpoint" and rep["validation"]["requested"] == 2
    assert rep["coverage"]["validation_requested"] is None and rep["coverage"]["reinforce_status"] is None


@pytest.fixture(scope="module")
def planned(env):
    """rule "plan"(기본)으로 한 번 돈 작은 세션 — 요구영역 초안(M0.3~0.55 · 100/1000/3000 m · 200 kg), 설계 줄 1000 m."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1))
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    return s


def test_plan_puts_boundary_points_in_and_reports_a_summary_grid(planned):
    s = planned
    kinds = {e["kind"] for e in s.validation_plan}
    assert {"midpoint", "knot", "boundary"} <= kinds
    added = [e for e in s.validation_plan if e["added"]]
    assert {e["kind"] for e in added} >= {"midpoint", "boundary"}
    for e in added:
        assert s.points.get(e["name"]).role == "validation" and s.points.get(e["name"]).origin == e["origin"]
    # 절점 자리 설계점은 판정을 겸한다 — 새 점을 만들지 않는다
    assert all(e["existing"] and not e["added"] for e in s.validation_plan if e["kind"] == "knot")
    rep = s.report()
    v = rep["validation"]
    assert v["rule"] == "plan" and v["source"] == "design_rows" and v["conditions"] == [[1000.0, 200.0]]
    assert v["requested"] == len(s.validation_plan) - v["out_of_region"]
    assert v["by_kind"]["boundary"]["requested"] >= 4
    g = rep["summary_grid"]
    assert g["totals"]["n"] == v["requested"] and g["totals"]["done"] == v["done"]
    assert [r["key"] for r in g["rows"]] == ["h1000_f200", "extra"]
    assert g["cells"]["extra"], "경계점이 「경계·추가」 행에 모인다"
    r = rep["reinforcement"]
    assert r["status"] == "tol_unset" and r["label"] == "허용치 미설정 — d 분포만" and r["added"] == []
    assert r["d"] and set(r["distribution"]) <= {"pitch_rate", "yaw_rate", "roll_rate", "pitch_att", "roll_att"}
    assert r["scales"]["pitch_att"] == 5.0 and "잠정" in r["scale_sources"]["pitch_att"]
    cov = rep["coverage"]
    assert cov["validation_requested"] == v["requested"] and cov["reinforce_status"] == "tol_unset"
    assert cov["validation_points"] == sum(1 for p in s.points if str(p.origin).startswith("midpoint:"))
    assert not any("허용치 미설정" in gap or "d 분포" in gap for gap in rep["coverage_gaps"])  # 공백이 아니다


def test_plan_session_round_trip_keeps_the_plan_and_the_report(planned):
    d = planned.to_dict()
    assert d["validation_plan"] and d["validation_meta"]["mode"] == "full" and d["reinforce_state"]["status"] == "tol_unset"
    s2 = DesignSession.from_dict(d)
    assert s2.to_dict() == d
    a, b = planned.report(), s2.report()
    for key in ("validation", "summary_grid", "reinforcement", "coverage", "coverage_gaps"):
        assert a[key] == b[key], key
    # 옛 세션(계획 칸 없음)은 빈 계획으로 읽힌다
    old = {k: v for k, v in d.items() if k not in ("validation_plan", "validation_meta", "reinforce_state")}
    s3 = DesignSession.from_dict(old)
    assert (s3.validation_plan, s3.validation_meta, s3.reinforce_state) == ([], {}, {})


def test_reinforce_bisects_within_the_point_budget(env):
    """허용치를 주면 최악 구간부터 이분한다 — 추가점 예산 4(두 번의 이분)에서 멈추고 남은 구간이 있으면 「보강 종료 · 추가
    검증 필요」다(합격·불가로 바꾸지 않는다). 새 점은 판정까지 받는다."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1, budget_points=40, reinforce={"tol": 1e-6, "max_points": 4}))
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    added = s.reinforce_state["added"]
    assert 0 < len(added) <= 4 and len(added) % 2 == 0
    for name in added:
        assert name in s.margin_out["cases"]
        e = next(x for x in s.validation_plan if x["name"] == name)
        assert e["kind"] == "reinforce" and e["origin"].startswith("reinforce:") and e["depth"] == 1
    rep = s.report()["reinforcement"]
    assert rep["status"] == "budget" and rep["label"].startswith("보강 종료 · 추가 검증 필요")
    assert rep["remaining"] and rep["max_d_remaining"] > 1e-6
    assert any("보강 예산" in g for g in s.report()["coverage_gaps"])


def test_reinforce_time_budget_is_checked_before_each_round(env):
    """시간 예산은 실행 전에 받는다 — 시계가 이미 넘었으면 한 점도 더하지 않고 남은 구간을 보고한다(시계는 주입)."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1, reinforce={"tol": 1e-6, "max_time_s": 1.0}))
    ticks = iter(range(0, 10_000, 100))
    s._clock = lambda: float(next(ticks))
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    assert s.reinforce_state["added"] == [] and s.reinforce_state["status"] == "budget"


def test_plan_gaps_name_omitted_rows_unrun_points_and_unmeasured_intervals(planned):
    s = DesignSession.from_dict(copy.deepcopy(planned.to_dict()))  # 픽스처 공유 — 사본을 고친다
    s.validation_meta["omitted"] = [[3000.0, 200.0]]
    victim = next(e for e in s.validation_plan if e["added"] and e["kind"] == "boundary")
    s.margin_out["cases"].pop(victim["name"])  # 결과에 없는 요청 점 = 미계산
    gaps = " ".join(s.coverage_gaps())
    assert "1개 행을 생략" in gaps and "3000 m·200 kg" in gaps
    assert "계산하지 못했다" in gaps
    cov = s.coverage()
    assert cov["validation_not_run"] == 1 and cov["validation_omitted_rows"] == 1
    if cov["d_unmeasured"]:
        assert "잴 수 없는 구간" in gaps


def test_without_a_region_the_plan_uses_the_adopted_range_and_says_so(env):
    import dataclasses

    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1))
    s.run(ac, stall, limits, db, design, verdict_ctx=dataclasses.replace(_vctx(), region=None, cache={}),
          fingerprint="fp")
    assert s.validation_plan and {e["kind"] for e in s.validation_plan} <= {"midpoint", "knot", "between_rows"}
    assert "요구영역 미정의" in s.report()["validation"]["note"]


def test_a_boundary_point_failure_goes_to_classify_and_the_action_names_its_plan_origin(planned):
    """계획한 점(경계·clip·절점·추가·검증조건·보강) 어디서든 실패는 CLASSIFY로 간다 — 요구영역 안 실패는 실제 실패다(부모
    결정). 처방 근거가 그 점의 계획 종류·출처를 적어, 사용자가 「경계점 실패」임을 처방 카드에서 읽는다. 이 작은 세션은
    요구영역 경계 모서리 M0.3 · 3000 m의 롤 레이트가 실패한다."""
    s = planned
    boundary = {e["name"] for e in s.validation_plan if e["kind"] == "boundary"}
    acts = [a for a in s.actions if a["case"] in boundary]
    assert acts, [a["id"] for a in s.actions]
    pp = acts[0]["evidence"]["plan_point"]
    assert pp["kind"] == "boundary" and pp["origin"] == "boundary:region" and pp["label"] == "요구영역 경계"
    note = s.report()["validation"]["classify_note"]
    assert "CLASSIFY" in note and "승인" in note


def test_validation_report_says_what_requested_counts(planned):
    """requested = 새로 넣은 검증점(added) + 판정을 겸한 기존 설계점(existing) + 못 돈 점(not_run) + 계획에만 남은 점."""
    v = planned.report()["validation"]
    assert v["rule"] == "plan"
    assert v["existing"] == sum(1 for e in planned.validation_plan if e["kind"] == "knot")  # 절점 자리 설계점 셋
    assert v["requested"] == v["added"] + v["existing"] + v["not_run"]


def test_report_uses_the_knots_the_plan_was_made_with_and_says_when_they_changed(planned):
    """add_knot 뒤 다음 VERIFY 전(취소·승인 대기)에 보고하면 지금 합집합은 계획 당시와 다르다 — 격자·d는 계획 당시 절점
    기준이고 그렇다고 적는다(리뷰 4)."""
    from claw.design.knots import add_knot

    s = DesignSession.from_dict(copy.deepcopy(planned.to_dict()))  # 픽스처 공유 — 사본을 고친다
    before = s.report()
    plan_knots = s.validation_meta["plan_knots"]
    assert plan_knots == union_knots(s.knot_sets, s.table_knots) and before["validation"]["knots_note"] is None
    slot = sorted(s.table_knots)[0]
    add_knot(s.knot_sets, s.table_knots, [slot], (plan_knots[0] + plan_knots[1]) / 2.0, reason="t", point="p",
             iter_n=1, max_per_table=20)
    after = s.report()
    assert after["summary_grid"]["columns"] == before["summary_grid"]["columns"]
    assert after["reinforcement"]["d"] == before["reinforcement"]["d"]
    note = after["validation"]["knots_note"]
    assert note and "절점이 바뀐 뒤 검증 전" in note
    assert note in after["summary_grid"]["notes"] and any(note in g for g in after["coverage_gaps"])


def test_validation_points_left_out_of_a_new_plan_stay_in_the_grid_as_prior(planned):
    """앞선 VERIFY가 넣은 검증점이 새 계획에 없어도 점 집합에 남아 판정받고 CLASSIFY로 간다 — 요약 격자의 「경계·추가」 행에
    「이전 계획」으로 보인다(리뷰 5). 검증조건을 다른 행으로 바꿔 다시 계획해 본다."""
    s = DesignSession.from_dict(copy.deepcopy(planned.to_dict()))  # 픽스처 공유 — 사본을 고친다
    old = {e["name"] for e in s.validation_plan if e["kind"] == "midpoint"}
    s.config.validation["conditions"] = [[100.0, 200.0]]
    s._add_planned_validation(s.points.designable(), union_knots(s.knot_sets, s.table_knots))
    prior = [e for e in s.validation_plan if e["kind"] == "prior"]
    assert old and old <= {e["name"] for e in prior}
    assert all(e["row"] is None and e["existing"] and not e["added"] for e in prior)
    g = s.summary_grid()
    assert sum(c["n"] for c in g["cells"]["extra"].values()) >= len(prior)
    assert s.report()["validation"]["by_kind"]["prior"]["requested"] == len(prior)


def test_failures_outside_the_plan_are_named_under_the_grid(planned):
    """실패가 계획 밖 점(설계점 적합 잔차 등)에만 있으면 격자는 모두 충족으로 보일 수 있다 — 격자 주석이 그 수를 말한다."""
    s = DesignSession.from_dict(copy.deepcopy(planned.to_dict()))  # 픽스처 공유 — 사본을 고친다
    failing = {f["case"] for f in s.margin_out["failures"]}
    s.validation_plan = [e for e in s.validation_plan if e["name"] not in failing]
    g = s.summary_grid()
    assert g["unplanned_failures"] == len(failing)
    assert any("계획 밖" in n for n in g["notes"])
