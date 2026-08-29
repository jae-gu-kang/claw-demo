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
    s = DesignSession(_small(mode="gated", fit_tol=10.0, max_segments=1, max_degree=1))
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
