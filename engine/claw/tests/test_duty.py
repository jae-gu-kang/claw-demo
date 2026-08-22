"""타면 사용 통계(duty) 검증 — 시간 가중 집계·포화 판정·복원 항등.

여기서 지키는 것:
① **시간 보존** — 히스토그램·밀도의 합이 총 시간과 같다 (표본이 조용히 사라지면
   "덜 쓴 것"처럼 보인다). ② **손계산 일치** — 구형파·클리핑 신호의 빈별 시간과
   포화 구간 수·최장 구간이 해석해와 정확히 같다. ③ **복원 항등 가드** — de/da로
   물리 타면을 복원하는 전제(믹서 1:1 고정 믹싱)가 깨지면 여기서 먼저 터진다.
④ **미상은 0이 아니다** — 한계를 모르면 포화율 0이 아니라 None.
"""

import numpy as np
import pytest

from claw.analysis.duty import (
    CHANNELS,
    density2d,
    duty_report,
    exceedance,
    rate_saturation,
    rate_series,
    reversals,
    run_stats,
    saturation,
    surface_positions,
    time_histogram,
)
from claw.common.contracts import TrimCase
from claw.fcl import make_demo_fcl
from claw.fcl.mixer import Mixer
from claw.guidance import Guidance, ModeSpec
from claw.plant import make_demo_aircraft, make_demo_stall_table
from claw.sim import Simulator
from claw.trim import trim_level


@pytest.fixture(scope="module")
def trim_design():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    return ac, tr


def make_sim(ac, tr, *, actuator_params=None, dt_plant=0.01, control_hz=100.0):
    V0 = float(np.linalg.norm(tr.state.vel_b))
    # 고도 명령을 트림에서 띄워 타면이 실제로 움직이게 한다 (정지 신호는 듀티가 없다)
    modes = [ModeSpec(name="climb", speed=V0, alt=tr.case.alt + 40.0, heading=0.0,
                      exit_when=("time_ge", 1e9))]
    return Simulator(
        aircraft=ac, fcl=make_demo_fcl(), guidance=Guidance(modes),
        stall_table=make_demo_stall_table(), dt_plant=dt_plant,
        control_hz=control_hz, actuator_params=actuator_params,
    )


# ── 복원 항등 (드리프트 가드) ────────────────────────────────────────────────

def test_surface_positions_matches_mixer():
    """de/da → 좌·우 엘레본 복원이 Mixer 출력과 정확히 일치.

    이 항등이 깨지면(믹싱 비율이 1:1을 벗어나면) 듀티 그림 전체가 조용히
    거짓말을 한다 — 그래서 여기서 Mixer와 직접 대조한다.
    """
    m = Mixer()
    sc = m.step(de=0.10, da=0.05, dr=0.02, thr=0.5)
    pos = np.asarray(sc.elevon, dtype=float)
    # 좌 쌍·우 쌍이 각각 같은 값이어야 두 값이 4면을 대표한다 (1:1 고정 믹싱 전제)
    assert pos[0] == pytest.approx(pos[1])
    assert pos[2] == pytest.approx(pos[3])

    de = float(np.mean(pos))
    da = float((pos[0] - pos[2]) / 2.0)
    out = surface_positions({"de": [de], "da": [da], "dr": [float(sc.rudder)]})
    assert out["elevon_l"][0] == pytest.approx(pos[0])
    assert out["elevon_r"][0] == pytest.approx(pos[2])
    assert out["rudder"][0] == pytest.approx(float(sc.rudder))


def test_surface_positions_requires_signals():
    with pytest.raises(KeyError, match="da"):
        surface_positions({"de": [0.0], "dr": [0.0]})


def test_surface_positions_accepts_json_roundtrip():
    """JSON 왕복본(리스트 + NaN→null)도 그대로 수용 — 서버가 저장본을 넘긴다."""
    out = surface_positions({"de": [0.1, None], "da": [0.05, 0.0], "dr": [0.0, 0.0]})
    assert out["elevon_l"][0] == pytest.approx(0.15)
    assert np.isnan(out["elevon_l"][1])


# ── 시간 가중 히스토그램 ─────────────────────────────────────────────────────

def test_time_histogram_square_wave_exact():
    """구형파 60/40 표본 × dt 0.1 → 빈별 6.0 s / 4.0 s (해석해와 정확히 일치)."""
    x = np.concatenate([np.full(60, 0.10), np.full(40, 0.20)])
    edges = np.array([0.0, 0.15, 0.30])
    h = time_histogram(x, edges, dt=0.1)
    assert h["time"] == pytest.approx([6.0, 4.0])
    assert h["frac"] == pytest.approx([0.6, 0.4])
    assert h["time"].sum() == pytest.approx(10.0)


def test_time_histogram_preserves_total_time():
    rng = np.random.default_rng(3)
    x = rng.normal(0.0, 0.1, 500)
    h = time_histogram(x, np.linspace(-0.5, 0.5, 33), dt=0.02)
    assert h["time"].sum() == pytest.approx(500 * 0.02)


def test_time_histogram_clips_out_of_range_and_reports_it():
    """범위 밖 표본은 버리지 않고 clip — 대신 그 시간을 따로 적어 위장을 막는다."""
    x = np.array([-1.0, 0.0, 0.0, 1.0])
    h = time_histogram(x, np.array([-0.5, 0.0, 0.5]), dt=0.25)
    assert h["time"].sum() == pytest.approx(1.0)  # 시간이 사라지지 않는다
    assert h["out_of_range"] == pytest.approx(0.5)  # 두 표본이 밖에 있었다


def test_time_histogram_ignores_nan():
    h = time_histogram([0.1, np.nan, 0.1], np.array([0.0, 0.2]), dt=1.0)
    assert h["time"] == pytest.approx([2.0])


# ── 누적 초과 ────────────────────────────────────────────────────────────────

def test_exceedance_levels_and_percentiles():
    x = np.array([0.1, 0.1, 0.1, 0.3, 0.3])
    ex = exceedance(x, dt=1.0, n_levels=4)
    assert ex["level"] == pytest.approx([0.0, 0.1, 0.2, 0.3])
    assert ex["time"] == pytest.approx([5.0, 5.0, 2.0, 2.0])
    assert ex["p50"] == pytest.approx(0.1)
    assert ex["p99"] == pytest.approx(0.3, abs=0.01)


def test_exceedance_is_monotone_decreasing():
    rng = np.random.default_rng(11)
    ex = exceedance(rng.normal(0, 0.1, 400), dt=0.01, n_levels=32)
    assert np.all(np.diff(ex["time"]) <= 1e-12)
    assert ex["time"][0] == pytest.approx(4.0)  # level 0 = 전체 시간


def test_exceedance_uses_magnitude_not_sign():
    """음의 타각도 |δ|로 센다 — 부호로 나누면 하방 타각이 0으로 보인다."""
    ex = exceedance([-0.3, -0.3], dt=1.0, n_levels=2)
    assert ex["time"][-1] == pytest.approx(2.0)


# ── 타율 ─────────────────────────────────────────────────────────────────────

def test_rate_series_decimates_and_uses_midpoints():
    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    xmid, xdot = rate_series(x, dt=0.1, decimate=2)
    assert xdot == pytest.approx([10.0, 10.0])  # (2-0)/0.2
    assert xmid == pytest.approx([1.0, 3.0])  # 중점 정렬
    assert xdot.size == xmid.size


def test_rate_series_too_short_is_empty_not_error():
    xmid, xdot = rate_series([0.3], dt=0.1)
    assert xmid.size == 0 and xdot.size == 0


def test_reversals_counts_sign_changes_above_deadband():
    xdot = np.array([1.0, 1.0, -1.0, -1.0, 1.0])
    r = reversals(xdot, dt_rate=1.0, deadband=0.1)
    assert r["count"] == 2
    assert r["per_min"] == pytest.approx(2.0 / (5.0 / 60.0))
    assert r["deadband"] == pytest.approx(0.1)  # 해석 가능하도록 echo


def test_reversals_deadband_suppresses_noise():
    """정지 근처 잡음은 반전이 아니다 — 불감대가 없으면 숫자가 무의미해진다."""
    xdot = np.array([1e-4, -1e-4, 1e-4, -1e-4, 1e-4])
    assert reversals(xdot, dt_rate=1.0, deadband=0.01)["count"] == 0


# ── 포화 집계 ────────────────────────────────────────────────────────────────

def test_run_stats_hand_calculation():
    """[F F T T T F F T F] · dt 0.1 → 시간 0.4 · 구간 2회 · 최장 0.3 · 최초 0.2."""
    m = np.array([False, False, True, True, True, False, False, True, False])
    t = np.arange(m.size) * 0.1
    s = run_stats(m, dt=0.1, times=t)
    assert s["time"] == pytest.approx(0.4)
    assert s["events"] == 2
    assert s["longest"] == pytest.approx(0.3)
    assert s["first_t"] == pytest.approx(0.2)
    assert s["frac"] == pytest.approx(4 / 9)


def test_run_stats_counts_leading_run_as_event():
    """처음부터 물려 있으면 상승엣지가 없다 — 그래도 1회로 센다."""
    s = run_stats(np.array([True, True, False]), dt=1.0)
    assert s["events"] == 1 and s["longest"] == pytest.approx(2.0)
    assert s["first_t"] == pytest.approx(0.0)


def test_run_stats_empty_mask():
    s = run_stats(np.zeros(5, dtype=bool), dt=0.1)
    assert s["time"] == 0.0 and s["events"] == 0 and s["first_t"] is None


def test_saturation_detects_both_ends():
    x = np.array([-0.35, 0.0, 0.35, 0.35, 0.0])
    s = saturation(x, dt=0.1, lo=-0.35, hi=0.35)
    assert s["time"] == pytest.approx(0.3)
    assert s["events"] == 2  # 하한 1회 + 상한 1회
    assert s["longest"] == pytest.approx(0.2)


def test_saturation_unknown_limits_is_none_not_zero():
    """한계를 모르는 것과 '한계에 0초 붙어 있었다'는 다른 사실이다."""
    assert saturation(np.zeros(5), dt=0.1, lo=None, hi=None) is None


def test_rate_saturation_unknown_rate_max_is_none():
    assert rate_saturation(np.zeros(5), dt_rate=0.1, rate_max=None) is None


def test_rate_saturation_boundary_is_inclusive():
    """작동기는 rate_max에 정확히 클램프한다 — 등호가 포화로 세어져야 한다."""
    s = rate_saturation(np.array([10.0, -10.0, 1.0]), dt_rate=0.1, rate_max=10.0)
    assert s["time"] == pytest.approx(0.2)


# ── 밀도 ─────────────────────────────────────────────────────────────────────

def test_density2d_preserves_total_time():
    rng = np.random.default_rng(5)
    x = rng.normal(0, 0.1, 300)
    v = rng.normal(0, 1.0, 300)
    d = density2d(x, v, np.linspace(-0.35, 0.35, 17), np.linspace(-10, 10, 13), 0.02)
    assert d["time"].sum() == pytest.approx(300 * 0.02)
    assert d["time"].shape == (16, 12)


# ── 리포트 (폐루프 런) ───────────────────────────────────────────────────────

def test_duty_report_closed_loop_with_actuators(trim_design):
    ac, tr = trim_design
    res = make_sim(ac, tr, actuator_params={}).run(tr, t_end=8.0)
    rep = duty_report(res.t, res.signals, res.meta)

    assert [c["key"] for c in rep["channels"]] == [k for k, _, _ in CHANNELS]
    assert rep["t_total"] == pytest.approx(8.0)
    assert rep["actuators"] is True
    assert rep["rate_is_command_slew"] is False
    assert rep["rate_dt"] == pytest.approx(res.meta["dt_plant"])
    assert not rep["warnings"]

    for ch in rep["channels"]:
        assert ch["hist"]["time"].sum() == pytest.approx(rep["t_total"])
        assert ch["density"]["time"].sum() == pytest.approx(
            rep["t_total"] - rep["rate_dt"])  # 차분이라 한 표본 적다
        # 한계가 결과 meta에서 실려 오므로 포화 판정이 선다
        assert ch["pos_lo"] is not None and ch["pos_hi"] is not None
        assert ch["rate_max"] == pytest.approx(10.0)
        assert ch["pos_sat"] is not None and ch["rate_sat"] is not None
        assert 0.0 <= ch["stats"]["usage"] <= 1.0


def test_duty_report_elevons_split_and_track_de(trim_design):
    """엘레본 좌·우가 실제로 로그된 de를 사이에 두고 갈라진다 (복원이 살아 있다)."""
    ac, tr = trim_design
    res = make_sim(ac, tr, actuator_params={}).run(tr, t_end=6.0)
    s = surface_positions(res.signals)
    de = np.asarray(res.signals["de"], dtype=float)
    assert np.allclose(0.5 * (s["elevon_l"] + s["elevon_r"]), de)


def test_duty_report_mode_split_sums_to_total(trim_design):
    """모드별 체류 시간의 합 = 총 시간 — 어느 구간이 작동기를 먹는지 나눠 본다."""
    ac, tr = trim_design
    V0 = float(np.linalg.norm(tr.state.vel_b))
    modes = [
        # 전환 시각을 체류 시간으로 고정 — 고도 캡처에 의존하면 상승 성능이
        # 바뀔 때 이 테스트가 모드 분해와 무관한 이유로 깨진다
        ModeSpec(name="climb", speed=V0, alt=tr.case.alt + 30.0, heading=0.0,
                 exit_when=("time_ge", 5.0), next="hold"),
        ModeSpec(name="hold", speed=V0, alt=tr.case.alt + 30.0, heading=0.0,
                 exit_when=("time_ge", 1e9)),
    ]
    sim = Simulator(
        aircraft=ac, fcl=make_demo_fcl(), guidance=Guidance(modes),
        stall_table=make_demo_stall_table(), dt_plant=0.01, control_hz=100.0,
        actuator_params={},
    )
    res = sim.run(tr, t_end=20.0)
    rep = duty_report(res.t, res.signals, res.meta)
    assert set(rep["modes"]) == {"climb", "hold"}
    assert sum(rep["mode_time"].values()) == pytest.approx(rep["t_total"])
    for ch in rep["channels"]:
        per_mode = sum(m["hist"]["time"].sum() for m in ch["by_mode"].values())
        assert per_mode == pytest.approx(rep["t_total"])


def test_duty_report_without_actuators_flags_command_slew(trim_design):
    """작동기 미장착 = 명령 ZOH — 제어주기 기준으로 솎아 계산하고 그 사실을 알린다."""
    ac, tr = trim_design
    res = make_sim(ac, tr, actuator_params=None, dt_plant=0.005).run(tr, t_end=4.0)
    rep = duty_report(res.t, res.signals, res.meta)
    assert rep["rate_is_command_slew"] is True
    assert rep["rate_dt"] == pytest.approx(0.01)  # 제어 100 Hz — 2배 솎임
    assert any("작동기 미장착" in w for w in rep["warnings"])
    for ch in rep["channels"]:
        assert ch["rate_max"] is None
        assert ch["rate_sat"] is None  # rate 한계가 없으므로 판정하지 않는다
        assert ch["pos_sat"] is not None  # 위치 한계는 믹서가 주므로 판정한다


def test_duty_report_survives_result_without_limits(trim_design):
    """구 결과(meta에 limits 없음)도 산출은 되고, 포화만 판정 불가로 남는다."""
    ac, tr = trim_design
    res = make_sim(ac, tr, actuator_params={}).run(tr, t_end=4.0)
    meta = {k: v for k, v in res.meta.items() if k != "limits"}
    rep = duty_report(res.t, res.signals, meta)
    for ch in rep["channels"]:
        assert ch["pos_sat"] is None and ch["rate_sat"] is None
        assert ch["stats"]["usage"] is None
        assert ch["hist"]["time"].sum() == pytest.approx(rep["t_total"])


def test_duty_report_histogram_spans_full_authority(trim_design):
    """한계를 알면 빈 경계는 데이터 범위가 아니라 **한계 전 구간** —

    남긴 조종권이 빈 칸으로 보여야 여유가 읽힌다. 데이터 범위로 잡으면 어떤
    런이든 양끝이 차 보여 '다 썼다'로 오독된다.
    """
    ac, tr = trim_design
    res = make_sim(ac, tr, actuator_params={}).run(tr, t_end=4.0)
    rep = duty_report(res.t, res.signals, res.meta, bins=16)
    ch = rep["channels"][0]
    assert ch["hist"]["edges"][0] == pytest.approx(ch["pos_lo"])
    assert ch["hist"]["edges"][-1] == pytest.approx(ch["pos_hi"])
    assert len(ch["hist"]["edges"]) == 17
    assert np.count_nonzero(ch["hist"]["time"]) < 16  # 실제로 안 쓴 구간이 있다


def test_duty_report_accepts_json_roundtrip_payload(trim_design):
    """서버는 저장된 JSON 본문을 넘긴다 — 리스트·null이 섞여도 같은 결과."""
    ac, tr = trim_design
    res = make_sim(ac, tr, actuator_params={}).run(tr, t_end=4.0)
    payload_sig = {
        k: (list(v) if not isinstance(v, np.ndarray) else v.tolist())
        for k, v in res.signals.items()
    }
    rep = duty_report(list(res.t), payload_sig, dict(res.meta))
    ref = duty_report(res.t, res.signals, res.meta)
    assert rep["channels"][0]["stats"]["max_abs"] == pytest.approx(
        ref["channels"][0]["stats"]["max_abs"])
