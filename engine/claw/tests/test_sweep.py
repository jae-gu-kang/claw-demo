"""pipeline.sweep 검증 — 3단: 처방 부분공간 한정 폐루프 스윕 + 쌍별 비가산성.

스윕 계획(sweep_plan)·표준 기동(probe_mission)·비가산성(nonadditivity)은 순수
함수로 검증하고, 실제 6DOF 실행(run_sweep)은 초소형 1케이스로만 통합 확인한다
(케이스·런 수가 늘수록 비용은 곱이다 — 그게 처방 부분공간 한정이 필요한 이유).
"""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.pipeline.influence import Shape
from claw.pipeline.sweep import (
    nonadditivity,
    probe_mission,
    run_sweep,
    sweep_plan,
)
from claw.plant import make_demo_aircraft
from claw.trim import trim_level


@pytest.fixture(scope="module")
def design_trim():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    return ac, tr


def test_표준_진단_기동은_설계_스캔_기동의_정본화다(design_trim):
    """수치(고도 +100 m·속도 +10 m/s·헤딩 0.5 rad)는 autopilot.py 설계 스캔
    기동에서 왔다 — 다른 수치로 재면 설계 성능 문구와 비교가 안 된다."""
    _, tr = design_trim
    modes, t_end = probe_mission(tr)
    assert [m.name for m in modes] == ["settle", "alt_step", "spd_step", "hdg_step"]
    V0 = float(np.linalg.norm(tr.state.vel_b))
    assert modes[1].alt == pytest.approx(1000.0 + 100.0)
    assert modes[2].speed == pytest.approx(V0 + 10.0)
    assert modes[3].heading == pytest.approx(0.5)
    assert modes[3].next is None  # 종단 모드
    assert t_end > 0
    # 체인이 끊기지 않는다
    names = {m.name for m in modes}
    assert all(m.next in names for m in modes[:-1])


def test_sweep_plan은_기준런과_스팬과_쌍_3점을_만든다():
    plan = sweep_plan(
        Shape(), ["table.pitch.kp"],
        pairs=[("table.pitch.kp", "table.pitch.k_rate")],
    )
    labels = {r.label: r for r in plan["runs"]}
    assert "base" in labels and labels["base"].overrides == {}
    # 배율 1.0 기준 ±10·20% 4점
    for s, v in ((-0.2, 0.8), (-0.1, 0.9), (0.1, 1.1), (0.2, 1.2)):
        lab = f"table.pitch.kp@{s:+g}"
        assert labels[lab].overrides == {"table.pitch.kp": pytest.approx(v)}
    # 쌍 3점: A@+0.1은 단독 스윕과 중복 — 재실행하지 않는다 (라벨 공유)
    pair = plan["pairs"][0]
    assert pair["a"] == "table.pitch.kp@+0.1"
    assert pair["b"] == "table.pitch.k_rate@+0.1"
    assert pair["ab"] in labels
    assert labels[pair["ab"]].overrides == {
        "table.pitch.kp": pytest.approx(1.1),
        "table.pitch.k_rate": pytest.approx(1.1),
    }
    assert len(plan["runs"]) == 1 + 4 + 1 + 1  # base + 단독 4 + B단독 + AB


def test_sweep_plan_기준값_0은_절대_스텝으로():
    """상대 스팬은 0에서 성립하지 않는다 (probe_value와 같은 이유) — zero_step
    절대 스텝을 쓴다. 0을 0으로 곱해 '스윕했는데 아무 일 없음'을 만들지 않는다."""
    plan = sweep_plan(Shape(), ["fcl/Autopilot.ki_hdg"], span=(0.1, 0.2))
    labels = {r.label: r for r in plan["runs"]}
    vals = sorted(r.overrides["fcl/Autopilot.ki_hdg"]
                  for r in labels.values() if r.overrides)
    assert vals == [pytest.approx(0.001), pytest.approx(0.002)]


def test_sweep_plan_unknown_knob은_거부():
    with pytest.raises(ValueError):
        sweep_plan(Shape(), ["없는.자리"])


def test_비가산성은_델타의_합과_동시_델타의_차다():
    m0 = {"alt_rms": 10.0, "spd_rms": 1.0, "worst_stall_margin": None}
    mA = {"alt_rms": 8.0, "spd_rms": 1.5, "worst_stall_margin": 0.2}
    mB = {"alt_rms": 9.0, "spd_rms": 1.0, "worst_stall_margin": None}
    mAB = {"alt_rms": 6.0, "spd_rms": 1.6, "worst_stall_margin": None}
    out = nonadditivity(m0, mA, mB, mAB)
    # dA=-2, dB=-1, dAB=-4 → 비가산 -1 (동시에 더 좋아짐 = 상호작용 존재)
    assert out["alt_rms"] == pytest.approx(-1.0)
    assert out["spd_rms"] == pytest.approx(0.1)
    assert out["worst_stall_margin"] is None  # 판정 불가는 0이 아니라 None


def test_run_sweep_초소형_통합(design_trim):
    """1케이스 × (base + 1런) — 행마다 지표·형상 지문이 실리고, 기준런이 부수
    산출물로 나온다 (규칙 4 국소성의 입력)."""
    ac, tr = design_trim
    plan = sweep_plan(Shape(), ["table.pitch.kp"], span=(0.1,))
    out = run_sweep(ac, [tr], Shape(), plan, t_settle=2.0, t_step=4.0)
    assert out["aborted"] is None
    rows = out["rows"]
    assert [r["label"] for r in rows] == ["base", "table.pitch.kp@+0.1"]
    for r in rows:
        assert r["case"] == "design"
        assert r["metrics"]["alt_rms"] is not None
        assert r["fingerprint"]
    assert rows[0]["fingerprint"] != rows[1]["fingerprint"]  # 지문이 계보
