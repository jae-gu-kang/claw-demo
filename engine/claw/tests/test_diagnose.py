"""pipeline.diagnose 검증 — "어떤 손잡이를 만질 것인가"의 귀속 규칙별 판정.

합성 신호로 각 규칙의 처방을 못박는다: 같은 추종 미달이라도 필터 병목이면 tau,
루프 미달이면 kp/ki가 나와야 하고(규칙 1), 포화를 PI항이 주도하면 kp/ki 감소가
나와야 하며(규칙 2), 스케줄이 덮는 자리는 table.* 배율로 자동 승격돼야 한다
(교차 규칙 — 1단 overridden/inert가 진단에 기여하는 자리).
"""

import numpy as np

from claw.pipeline.diagnose import (
    RMS_THRESH,
    diagnose_grid,
    diagnose_run,
)
from claw.pipeline.influence import Shape, param_universe

N = 200
DT = 0.01


def _payload():
    """전 규칙이 '조용한' 기준선 런 — 각 테스트가 결함을 주입해 쓴다."""
    z = np.zeros(N)
    signals = {
        "cmd_alt": np.full(N, 1000.0), "alt_cmd_filt": np.full(N, 1000.0),
        "h": np.full(N, 1000.0), "alt_on": np.ones(N),
        "cmd_speed": np.full(N, 200.0), "spd_cmd_filt": np.full(N, 200.0),
        "V": np.full(N, 200.0), "speed_on": np.ones(N),
        "cmd_heading": z.copy(), "hdg_cmd_filt": z.copy(),
        "psi": z.copy(), "heading_on": np.ones(N),
        "pitch_pi": z.copy(), "pitch_damp": z.copy(), "pitch_raw": z.copy(),
        "roll_pi": z.copy(), "roll_damp": z.copy(), "roll_raw": z.copy(),
        "yaw_pi": z.copy(), "yaw_damp": z.copy(), "yaw_raw": z.copy(),
        "pitch": z.copy(), "roll": z.copy(), "yaw": z.copy(),
        "ap_alt_pi": z.copy(), "ap_alt_damp": z.copy(), "ap_alt_raw": z.copy(),
        "ap_pitch_ff": z.copy(), "ap_theta_raw": z.copy(),
        "theta_cmd": z.copy(), "theta_lim": z.copy(), "lim_cap": np.full(N, 0.3),
        "i_pitch": z.copy(), "i_roll": z.copy(), "i_yaw": z.copy(),
        "i_alt": z.copy(), "i_spd": np.full(N, 0.5), "i_hdg": z.copy(),
        "limiter_active": np.zeros(N, dtype=bool),
        "alpha_margin": np.full(N, 0.2),
        "de": z.copy(), "da": z.copy(), "dr": z.copy(),
        "pn": z.copy(), "pe": z.copy(),
    }
    envelope = {"worst_margin": 0.25, "flags": {"alpha": np.zeros(N, dtype=bool)}}
    meta = {
        "dt_plant": DT,
        "limits": {"elevon_lo": -0.35, "elevon_hi": 0.35,
                   "rudder_lo": -0.2, "rudder_hi": 0.2, "rate_max": None},
        "clamps": {
            "pitch": {"lo": -0.35, "hi": 0.35}, "roll": {"lo": -0.35, "hi": 0.35},
            "yaw": {"lo": -0.35, "hi": 0.35}, "alt": {"lo": -0.3, "hi": 0.3},
            "spd": {"lo": 0.0, "hi": 1.0}, "hdg": {"lo": -0.7, "hi": 0.7},
        },
        "waypoints": None,
    }
    return {"t": np.arange(N) * DT, "signals": signals,
            "envelope": envelope, "meta": meta}


def _pres(out, knob_class=None, rule=None):
    ps = out["prescriptions"]
    if knob_class is not None:
        ps = [p for p in ps if p["knob_class"] == knob_class]
    if rule is not None:
        ps = [p for p in ps if out["findings"][p["findings"][0]]["rule"] == rule]
    return ps


def test_조용한_기준선은_처방이_없다():
    out = diagnose_run(_payload(), Shape())
    assert out["prescriptions"] == []
    assert out["metrics"]["alt_rms"] == 0.0


def test_규칙1_필터_병목이면_tau_처방():
    """오차의 대부분이 (원본 명령 − 필터 명령)이면 게인을 올려도 소용없다 —
    tau 감소가 나와야 한다."""
    p = _payload()
    s = p["signals"]
    s["cmd_alt"] = np.full(N, 1100.0)
    s["alt_cmd_filt"] = np.linspace(1000.0, 1080.0, N)  # 필터가 명령을 못 따라감
    s["h"] = s["alt_cmd_filt"] - 1.0  # 루프는 필터 명령을 잘 추종 (오차 1 m)
    out = diagnose_run(p, Shape())
    ps = _pres(out, knob_class="filter")
    assert len(ps) == 1
    assert ps[0]["knobs"] == ["fcl/Autopilot.tau_alt"]
    assert ps[0]["direction"] == "decrease"
    f = out["findings"][ps[0]["findings"][0]]
    assert f["rule"] == "error_split" and f["axis"] == "alt"
    assert f["evidence"]["rms_filter"] > f["evidence"]["rms_loop"]


def test_규칙1_루프_미달이면_kp_ki_처방():
    """필터는 명령을 다 냈는데 응답이 못 따라가면 루프 게인 문제다."""
    p = _payload()
    s = p["signals"]
    s["cmd_alt"] = np.full(N, 1100.0)
    s["alt_cmd_filt"] = np.full(N, 1100.0)  # 필터는 즉시 통과
    s["h"] = np.full(N, 1100.0 - 3.0 * RMS_THRESH["alt"])  # 정상상태 미달
    out = diagnose_run(p, Shape())
    ps = _pres(out, knob_class="loop_gain", rule="error_split")
    assert len(ps) == 1
    assert ps[0]["knobs"] == ["fcl/Autopilot.kp_alt", "fcl/Autopilot.ki_alt"]
    assert ps[0]["direction"] == "increase"
    assert "surf_sat_frac" in ps[0]["recheck"]  # kp↑ 커플링 — 포화 재확인


def test_규칙2_포화를_PI항이_주도하면_감소_처방과_스케줄_승격():
    """포화 틱에서 |PI| ≫ |damp|면 kp/ki 감소 — 그리고 데모 형상은 pitch.kp/ki가
    스케줄에 덮이므로(1단 overridden) table.pitch.* 배율로 승격돼야 한다.
    승격 없이 fcl/ScasAxis.pitch.kp를 처방하면 "편집해도 아무 일 없는" 자리다."""
    p = _payload()
    s = p["signals"]
    sat = slice(0, 24)  # 24/200 = 12% > SAT_FRAC_WARN
    s["pitch_raw"][sat] = 0.6
    s["pitch"][sat] = 0.35  # 클램프에 물림
    s["pitch_pi"][sat] = 0.55  # PI 지배
    s["pitch_damp"][sat] = 0.05
    out = diagnose_run(p, Shape())
    ps = _pres(out, rule="sat_attrib")
    assert len(ps) == 1
    assert ps[0]["knobs"] == ["table.pitch.kp", "table.pitch.ki"]  # 승격됨
    assert ps[0]["direction"] == "decrease"
    assert ps[0]["knob_class"] == "loop_gain"
    f = out["findings"][ps[0]["findings"][0]]
    assert f["evidence"]["mean_pi"] > f["evidence"]["mean_damp"]
    assert any("승격" in n for n in ps[0]["notes"])


def test_규칙2_damp_지배면_k_rate_처방():
    p = _payload()
    s = p["signals"]
    sat = slice(0, 24)
    s["pitch_raw"][sat] = 0.6
    s["pitch"][sat] = 0.35
    s["pitch_pi"][sat] = 0.05
    s["pitch_damp"][sat] = 0.55  # 레이트항 지배
    out = diagnose_run(p, Shape())
    ps = _pres(out, rule="sat_attrib")
    assert len(ps) == 1
    assert ps[0]["knobs"] == ["table.pitch.k_rate"]  # 스케줄 자리라 역시 승격 (inert)
    assert ps[0]["knob_class"] == "rate_gain" and ps[0]["direction"] == "decrease"


def test_규칙3_적분기_클램프_주차는_와인드업_처방():
    """내부 클램프형 PID는 적분기가 '계속 자라는' 게 아니라 클램프에 주차한다 —
    그 지속이 시그니처다. ki 감소 + 클램프 완화가 동시 수정 후보."""
    p = _payload()
    s = p["signals"]
    s["i_alt"][:40] = 0.3  # theta_hi에 주차 (40/200 = 20%)
    out = diagnose_run(p, Shape())
    ps = _pres(out, rule="windup")
    assert len(ps) == 1
    assert ps[0]["knobs"] == ["fcl/Autopilot.ki_alt"]
    assert ps[0]["direction"] == "decrease"
    assert set(ps[0]["joint_with"]) >= {"fcl/Autopilot.theta_lo", "fcl/Autopilot.theta_hi"}


def test_규칙5_리미터_작동_중_침투는_감쇠_처방():
    """리미터가 자주 물리는데 α 마진까지 뚫리면 피치 응답이 경계를 넘는 것 —
    감쇠(k_rate) 문제다. pitch.k_rate는 스케줄 자리라 승격된다."""
    p = _payload()
    s = p["signals"]
    s["limiter_active"][:20] = True
    s["alpha_margin"][:20] = -0.01  # 보호 경계 침투
    out = diagnose_run(p, Shape())
    ps = _pres(out, rule="limiter")
    assert len(ps) == 1
    assert ps[0]["knobs"] == ["table.pitch.k_rate"]
    assert ps[0]["direction"] == "increase"
    assert "worst_stall_margin" in ps[0]["recheck"]


def test_규칙5_침투_없는_지속_작동은_margin_처방():
    p = _payload()
    s = p["signals"]
    s["limiter_active"][:20] = True  # 침투 없음 (alpha_margin 0.2 유지)
    out = diagnose_run(p, Shape())
    ps = _pres(out, rule="limiter")
    assert len(ps) == 1
    assert ps[0]["knobs"] == ["fcl/AlphaLimiter.margin"]
    assert ps[0]["knob_class"] == "limiter" and ps[0]["direction"] == "decrease"


def test_처방_knob은_전부_실재하는_파라미터다():
    """knob id가 param_universe에 없는 자리를 처방하면 스윕이 시작조차 못 한다 —
    id 철자 드리프트를 여기서 잡는다 (여러 결함 동시 주입)."""
    p = _payload()
    s = p["signals"]
    s["cmd_alt"] = np.full(N, 1100.0)
    s["alt_cmd_filt"] = np.linspace(1000.0, 1080.0, N)
    s["h"] = s["alt_cmd_filt"] - 1.0
    s["pitch_raw"][:24] = 0.6
    s["pitch"][:24] = 0.35
    s["pitch_pi"][:24] = 0.55
    s["i_alt"][:40] = 0.3
    s["limiter_active"][:20] = True
    shape = Shape()
    out = diagnose_run(p, shape)
    assert out["prescriptions"], "결함을 주입했는데 처방이 없다"
    ids = {r.id for r in param_universe(shape)}
    for pres in out["prescriptions"]:
        for knob in pres["knobs"]:
            assert knob in ids, f"실재하지 않는 knob: {knob}"


def test_규칙4_국소성_판정():
    """결함이 격자 일부에 몰리면 스케줄(테이블 형상), 전반이면 게인 수준 문제다."""
    def case(m, bad):
        return {"case": {"mach": m, "alt": 1000.0, "fuel": 200.0},
                "metrics": {"alt_rms": 30.0 if bad else 2.0}}

    local = diagnose_grid([case(0.2 + 0.1 * i, i == 0) for i in range(9)])
    assert local["metrics"]["alt_rms"]["verdict"] == "local"
    assert local["metrics"]["alt_rms"]["knob_class"] == "schedule"
    assert len(local["metrics"]["alt_rms"]["bad_cases"]) == 1

    global_ = diagnose_grid([case(0.2 + 0.1 * i, i < 8) for i in range(9)])
    assert global_["metrics"]["alt_rms"]["verdict"] == "global"
    assert global_["metrics"]["alt_rms"]["knob_class"] == "loop_gain"


def test_규칙4_잘린_런은_판정에서_빠진다():
    """발산으로 중단된 런의 지표는 잘린 구간만의 값 — 문턱 안으로 보여도 근거가
    아니다. 세면 판정 불가가 '정상'으로 위장된다."""
    def case(m, *, rms, aborted=False):
        return {"case": {"mach": m, "alt": 1000.0, "fuel": 200.0},
                "metrics": {"alt_rms": rms}, "aborted": aborted}

    # 정상 2 + 결함 2 + 잘린 4. 잰 것만 세면 2/4 = 0.5 > 1/3 → 전역(게인 수준),
    # 잘린 4건까지 세면 2/8 = 0.25 ≤ 1/3 → 국소(스케줄 셀)로 뒤집힌다
    out = diagnose_grid([
        case(0.3, rms=2.0), case(0.4, rms=2.0),
        case(0.5, rms=30.0), case(0.6, rms=30.0),
        *(case(0.7 + 0.1 * i, rms=2.0, aborted=True) for i in range(4)),
    ])
    g = out["metrics"]["alt_rms"]
    assert g["n_cases"] == 4 and g["n_bad"] == 2
    assert g["bad_frac"] == 0.5  # 2/4 — 이진수로 정확한 값이라 근사 비교가 필요 없다
    assert g["verdict"] == "global" and g["knob_class"] == "loop_gain"

    # 전부 잘리면 잰 케이스가 없다 — 지표 자체가 판정에서 빠진다 (ok가 아니다)
    assert diagnose_grid([case(0.4, rms=2.0, aborted=True)])["metrics"] == {}
