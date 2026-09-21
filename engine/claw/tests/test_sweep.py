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
    PROBE_DH,
    PROBE_DPSI,
    PROBE_DV,
    nonadditivity,
    probe_mission,
    run_sweep,
    sweep_plan,
)
from claw.plant import make_demo_aircraft
from claw.trim import trim_level
from claw.profile import example_profile


@pytest.fixture(scope="module")
def design_trim():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    return ac, tr


def test_표준_진단_기동의_스텝은_계측으로_정해진다(design_trim):
    """스텝은 **제어권한 안**이어야 한다 (v0.72).

    종전 수치(고도 +100 m·속도 +10 m/s·헤딩 0.5 rad)는 autopilot.py 설계 스캔
    기동에서 왔고 "다른 수치로 재면 설계 성능 문구와 비교가 안 된다"가 이 테스트의
    근거였다. 그 비교는 **이미 깨져 있었다** — fcl/demo.py 머리말이 적어 둔 대로
    프로펠러 추력 모델 이후 그 설계점(M0.6 h1000 f200)은 엔벨로프 밖이고(스로틀
    95.04 % > SAT_FRAC 0.95), 계측하면 스로틀이 전 구간의 93.6 %를 최대치에 붙어
    +10 m/s를 60초에 2.5 m/s밖에 못 따라간다. 그 상태의 추종 RMS는 제어 품질이
    아니라 물리 한계를 재는 값이다.

    그래서 스텝을 줄여 오차가 제어 품질을 재게 했다(sweep.PROBE_* 주석에 계측표).
    능력을 넘었다는 사실은 지우지 않는다 — CHECKS의 「추력 여유」가 계속 fail로
    보고한다. **축 겹침은 이 변경으로 안 고쳐진다**: 고도 정착은 70.4 → 71.0 s로
    그대로이고, 그것은 스텝 크기가 아니라 상승 능력이 정한다(t_step [TBD]).
    """
    _, tr = design_trim
    modes, t_end = probe_mission(tr)
    assert [m.name for m in modes] == ["settle", "alt_step", "spd_step", "hdg_step"]
    V0 = float(np.linalg.norm(tr.state.vel_b))
    assert modes[1].alt == pytest.approx(1000.0 + PROBE_DH)
    assert modes[2].speed == pytest.approx(V0 + PROBE_DV)
    assert modes[3].heading == pytest.approx(PROBE_DPSI)
    # 스텝은 상수에서 오고, 그 상수는 계측으로 정해졌다 — 값이 다시 커지면
    # 이 단언이 아니라 sweep.PROBE_* 주석의 계측표를 다시 돌려야 한다
    assert (PROBE_DH, PROBE_DV, PROBE_DPSI) == (30.0, 3.0, 0.3)
    assert modes[3].next is None  # 종단 모드
    assert t_end > 0
    # 체인이 끊기지 않는다
    names = {m.name for m in modes}
    assert all(m.next in names for m in modes[:-1])


def test_sweep_plan은_기준런과_스팬과_쌍_3점을_만든다():
    plan = sweep_plan(
        Shape(profile=example_profile()), ["table.pitch.kp"],
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


def test_sweep_plan_빈_knobs는_기준런_하나다():
    """knobs·pairs가 비면 계획은 base 런 1개 — 전 케이스 base 스캔(3단 A,
    /influence/scan)이 run_sweep을 그대로 재사용하는 계약이다."""
    plan = sweep_plan(Shape(profile=example_profile()), [], ())
    assert [r.label for r in plan["runs"]] == ["base"]
    assert plan["runs"][0].overrides == {}
    assert plan["pairs"] == [] and plan["notes"] == []


def test_sweep_plan_기준값_0은_절대_스텝으로():
    """상대 스팬은 0에서 성립하지 않는다 (probe_value와 같은 이유) — zero_step
    절대 스텝을 쓴다. 0을 0으로 곱해 '스윕했는데 아무 일 없음'을 만들지 않는다."""
    plan = sweep_plan(Shape(profile=example_profile()), ["fcl/Autopilot.ki_hdg"], span=(0.1, 0.2))
    labels = {r.label: r for r in plan["runs"]}
    vals = sorted(r.overrides["fcl/Autopilot.ki_hdg"]
                  for r in labels.values() if r.overrides)
    assert vals == [pytest.approx(0.001), pytest.approx(0.002)]


def test_sweep_plan_unknown_knob은_거부():
    with pytest.raises(ValueError):
        sweep_plan(Shape(profile=example_profile()), ["없는.자리"])


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
    plan = sweep_plan(Shape(profile=example_profile()), ["table.pitch.kp"], span=(0.1,))
    out = run_sweep(ac, [tr], Shape(profile=example_profile()), plan, t_settle=2.0, t_step=4.0)
    assert out["aborted"] is None
    rows = out["rows"]
    assert [r["label"] for r in rows] == ["base", "table.pitch.kp@+0.1"]
    for r in rows:
        assert r["case"] == "design"
        assert r["metrics"]["alt_rms"] is not None
        assert r["fingerprint"]
    assert rows[0]["fingerprint"] != rows[1]["fingerprint"]  # 지문이 계보


# ── 스케줄 가로지르기 시나리오 (v1.41 — 04 §5.5 mission_profile) ─────────────


def _cases(machs=(0.3, 0.5, 0.7), alts=(1000.0,), fuel=200.0):
    return [TrimCase(name=f"M{m}/h{a}", mach=m, alt=a, fuel=fuel)
            for m in machs for a in alts]


def test_crossing_scenario_derives_everything_from_tables_and_grid():
    """시나리오 좌표는 전부 표·격자에서 나온다 — 특정 기체 전제 금지.

    breakpoint는 Table.axes ∪ PolyTable.knots, 범위는 케이스 격자로 클립,
    쌍은 범위 중앙 최근접 인접쌍, 시작·목표는 b1−½Δ·b2+½Δ(클립)다.
    """
    from claw.pipeline.sweep import schedule_crossing_scenario
    from claw.tables import Table

    tables = {"pitch.kp": Table({"mach": [0.2, 0.4, 0.6, 0.8]},
                                [-8.0, -6.0, -4.0, -2.0], name="pitch.kp")}
    sc = schedule_crossing_scenario(tables, _cases())
    assert sc["mach"]["pair"] == (0.4, 0.6)  # 격자 범위 [0.3, 0.7]의 중앙 최근접 쌍
    assert sc["mach"]["start"] == pytest.approx(0.3)  # 0.4−0.1이나 범위 하한 클립
    assert sc["mach"]["target"] == pytest.approx(0.7)
    assert sc["alt"] is None and sc["start"]["alt"] == 1000.0
    assert sc["start"]["fuel"] == 200.0

    # breakpoint가 격자 범위 안에 2개 미만이면 None — 호출자가 na + 사유로 낸다
    narrow = [TrimCase(name="n", mach=0.45, alt=1000.0, fuel=200.0)]
    assert schedule_crossing_scenario(tables, narrow) is None
    assert schedule_crossing_scenario({}, _cases()) is None

    # fuel 축 스케줄 — 시나리오는 없고 사유가 남는다 (연료는 명령이 아니라 소모 상태)
    tables["yaw.k_rate"] = Table({"fuel": [0.0, 400.0]}, [0.4, 0.5], name="yaw.k_rate")
    sc2 = schedule_crossing_scenario(tables, _cases())
    assert any("fuel" in n for n in sc2["notes"])


def test_crossing_mission_chains_state_based_exits(design_trim):
    """페이즈 exit는 상태 기반(speed_ge·alt_ge)이고 문턱은 breakpoint 너머다 —
    시간이 아니라 **넘은 것이 확인된 뒤에만** 다음 페이즈로 간다."""
    from claw.env import isa_atmosphere
    from claw.pipeline.sweep import schedule_crossing_mission

    _ac, tr = design_trim
    sc = {"mach": {"pair": (0.55, 0.65), "start": 0.5, "target": 0.7},
          "alt": {"pair": (1000.0, 3000.0), "start": 0.0, "target": 4000.0},
          "start": {"mach": 0.5, "alt": 0.0, "fuel": 200.0}, "notes": []}
    modes, t_end = schedule_crossing_mission(tr, sc, t_settle=5.0, t_step=30.0)
    assert [m.name for m in modes] == ["settle", "accel", "climb", "hold"]
    kind, v = modes[1].exit_when
    assert kind == "speed_ge"
    sos = isa_atmosphere(float(tr.case.alt)).a
    assert v == pytest.approx((0.65 + 0.025) * sos)  # b2 + ¼Δ — 명령 목표(0.7)보다 안쪽
    assert modes[1].speed == pytest.approx(0.7 * sos)
    assert modes[2].exit_when == ("alt_ge", 3500.0)  # 3000 + ¼(2000)
    assert modes[2].alt == 4000.0
    assert t_end == pytest.approx(5.0 + (8.0 * 2 + 1.0) * 30.0)  # 천장 [기본값]
    _, t2 = schedule_crossing_mission(tr, sc, t_settle=5.0, t_step=30.0, t_mission=90.0)
    assert t2 == 90.0  # t_mission이 천장을 덮는다


def test_crossing_exit_stays_strictly_inside_a_clipped_target(design_trim):
    """격자 상한이 목표를 b2+¼Δ 안쪽으로 깎아도 exit < 명령 목표 — 같아지면 점근
    접근으로 영영 발화하지 않아 후속 페이즈가 못 선다 (리뷰 지적)."""
    from claw.env import isa_atmosphere
    from claw.pipeline.sweep import schedule_crossing_mission

    _ac, tr = design_trim
    sos = isa_atmosphere(float(tr.case.alt)).a
    # target 0.66 < b2+¼Δ(0.675) — 종전 식이면 exit == target이 되던 기하
    sc = {"mach": {"pair": (0.55, 0.65), "start": 0.5, "target": 0.66}, "alt": None,
          "start": {"mach": 0.5, "alt": float(tr.case.alt), "fuel": 200.0}, "notes": []}
    modes, _ = schedule_crossing_mission(tr, sc, t_settle=5.0, t_step=30.0)
    _, v_exit = modes[1].exit_when
    assert v_exit == pytest.approx((0.65 + 0.005) * sos)  # b2 + ½(target−b2)
    assert v_exit < modes[1].speed  # 명령 목표보다 엄격히 안쪽

    # 레그 없는 시나리오는 미션을 만들지 않는다 — 공개 함수 가드
    with pytest.raises(ValueError, match="레그가 없는"):
        schedule_crossing_mission(tr, {"mach": None, "alt": None,
                                       "start": sc["start"], "notes": []})


def test_crossing_scenario_multi_axis_tables_and_headroom_preference():
    """다축 테이블의 축 격자점도 breakpoint다 + 여유 없는 쌍은 뒤로 (리뷰 반영).

    ① 2축(mach×alt) 스케줄만 장착돼도 "미장착"으로 오독하지 않는다.
    ② b2가 격자 상한인 쌍은 target==b2라 exit가 영영 발화 못 하므로, 여유 있는
    쌍이 존재하면 중앙 최근접이라도 양보한다.
    """
    from claw.pipeline.sweep import schedule_crossing_scenario
    from claw.tables import Table

    # ① 다축 테이블 — mach 축 격자점이 잡힌다
    multi = {"pitch.kp": Table({"mach": [0.3, 0.5, 0.7], "alt": [0.0, 5000.0]},
                               [[-8, -7], [-6, -5], [-4, -3]], name="pitch.kp")}
    sc = schedule_crossing_scenario(multi, _cases(machs=(0.3, 0.7)))
    assert sc is not None and sc["mach"]["pair"] == (0.3, 0.5)

    # ② (0.4, 0.7)이 중앙 최근접이지만 b2==상한 — (0.2, 0.4)가 대신 뽑힌다
    t = {"pitch.kp": Table({"mach": [0.2, 0.4, 0.7]}, [-8.0, -6.0, -4.0],
                           name="pitch.kp")}
    sc2 = schedule_crossing_scenario(t, _cases(machs=(0.2, 0.7)))
    assert sc2["mach"]["pair"] == (0.2, 0.4)
    assert sc2["mach"]["target"] > sc2["mach"]["pair"][1]  # 여유가 실제로 있다


def test_crossing_scenario_drops_a_leg_with_no_headroom_alternative():
    """breakpoint가 범위 안에 딱 둘뿐이고 그 상한이 격자 상한과 겹치면(양보할 대안이
    없는 최소 스케줄) 그 축은 레그를 안 낸다 — target==b2를 강행하면 exit 문턱이
    명령 목표와 같아져 점근 접근으로 영영 발화 못 한다(리뷰 지적, ②의 "양보"가 대안이
    없을 때는 못 구하는 자리).
    """
    from claw.pipeline.sweep import schedule_crossing_scenario
    from claw.tables import Table

    # mach: breakpoint 딱 둘, 케이스 격자 상하한과 정확히 겹친다 — 양보할 대안이 없다
    two_bp = {"pitch.kp": Table({"mach": [0.4, 0.6]}, [-6.0, -4.0], name="pitch.kp")}
    sc = schedule_crossing_scenario(two_bp, _cases(machs=(0.4, 0.6)))
    assert sc is None, "가로지를 축이(마하 하나뿐인데 그마저 여유 없음) 없으면 전체가 None"

    # alt 축에 여유 있는 스케줄을 더하면 — mach 레그만 빠지고 alt 레그는 그대로 선다
    two_bp["roll.k_rate"] = Table({"alt": [500.0, 1500.0, 3000.0]},
                                  [-0.2, -0.3, -0.4], name="roll.k_rate")
    sc2 = schedule_crossing_scenario(two_bp, _cases(machs=(0.4, 0.6), alts=(500.0, 3000.0)))
    assert sc2 is not None
    assert sc2["mach"] is None, "마하는 여유가 없어 레그가 없어야 한다"
    assert sc2["alt"] is not None and sc2["alt"]["target"] > sc2["alt"]["pair"][1]


def test_crossing_mission_skips_the_accel_phase_when_mach_has_no_headroom(design_trim):
    """마하 레그가 없으면(위 테스트) accel 페이즈 자체가 없다 — climb이 바로 settle
    뒤에 서므로, 여유 없는 축이 뒤 페이즈(고도 가로지르기)를 막지 않는다(리뷰 지적:
    exit_short_of만 손보면 문턱이 명령 목표를 넘어서 버려 같은 증상이 형태만 바뀐다)."""
    from claw.pipeline.sweep import schedule_crossing_mission

    _ac, tr = design_trim
    sc = {"mach": None,
          "alt": {"pair": (1000.0, 3000.0), "start": 500.0, "target": 4000.0},
          "start": {"mach": 0.5, "alt": 500.0, "fuel": 200.0}, "notes": []}
    modes, _ = schedule_crossing_mission(tr, sc, t_settle=5.0, t_step=30.0)
    assert [m.name for m in modes] == ["settle", "climb", "hold"]
    kind, v = modes[1].exit_when
    assert kind == "alt_ge" and v == pytest.approx(3500.0)  # b2 + ¼Δ
    assert v < modes[1].alt  # 명령 목표(4000)보다 엄격히 안쪽 — 도달 가능하다
