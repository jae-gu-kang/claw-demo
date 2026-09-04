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
        "ap_spd_pi": np.full(N, 0.5), "ap_hdg_pi": z.copy(),
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
        "control_hz": 1.0 / DT,  # 실제 sim meta에는 항상 있다 — 규칙 3의 ZOH 보정이 쓴다
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


def _saturating_run(control_hz):
    """스로틀을 실제로 포화시키는 런 — 규칙 3의 시그니처 ②가 밟히는 유일한 형상.

    합성 페이로드로는 ②를 재현할 수 없다(적분기 동결 + 출력 포화가 동시에, 실제
    제어 틱 간격으로 일어나야 한다). `control_hz`는 스윕 노브라 이 함수를 여러
    주기로 부른다.
    """
    import numpy as np

    from claw.common.contracts import TrimCase
    from claw.fcl import make_demo_fcl
    from claw.guidance import Guidance, ModeSpec
    from claw.plant import make_demo_aircraft, make_demo_db_ranges, make_demo_stall_table
    from claw.sim import Simulator
    from claw.trim import trim_level

    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("d", mach=0.4, alt=1000.0, fuel=200.0))
    assert tr.converged
    v0 = float(np.linalg.norm(tr.state.vel_b))
    # 큰 속도 스텝 + 상승 — 프로펠러 여유추력으로는 못 내는 명령이라 스로틀이 포화한다
    modes = [ModeSpec(name="fast", speed=v0 + 30.0, alt=1400.0, heading=0.0,
                      exit_when=("time_ge", 1e9))]
    res = Simulator(aircraft=ac, fcl=make_demo_fcl(), guidance=Guidance(modes),
                    stall_table=make_demo_stall_table(), db_ranges=make_demo_db_ranges(),
                    dt_plant=0.01, control_hz=control_hz).run(tr, t_end=60.0)
    out = diagnose_run(
        {"t": list(res.t), "envelope": res.envelope,
         "signals": {k: list(np.asarray(v)) for k, v in res.signals.items()},
         "meta": res.meta},
        Shape(),
    )
    return res, out


def test_windup_rule_sees_conditional_integration_in_a_real_run():
    """규칙 3이 **실제 런**에서 살아 있는지 — 신호 주입이 아니라.

    다른 와인드업 테스트들은 `i_alt`를 직접 채워 규칙을 부른다. 그러면 시그니처가
    낡아도 통과한다: PID가 조건부 적분으로 바뀌면서 적분기는 클램프까지 못 가고
    그 **직전에서 얼어붙는데**, 종전 규칙은 "클램프에 주차"만 봤다. 실측으로는
    i_spd가 0.51~0.77에 머물러(클램프 0/1) 주차 판정이 0%였다 — 규칙이 조용히
    죽은 상태였고 주입 테스트는 그걸 못 봤다.

    여기서는 스로틀을 실제로 포화시키는 런을 돌려 규칙이 경고를 내는지 본다.
    """
    res, out = _saturating_run(100.0)
    i_spd = np.asarray(res.signals["i_spd"])
    assert np.mean(np.asarray(res.signals["thr_l"]) >= 0.999) > 0.5, "포화를 안 밟았다"
    # 적분기는 클램프(0/1) 근처에 가지 않는다 — 종전 시그니처가 못 잡던 이유
    assert 0.05 < i_spd.min() and i_spd.max() < 0.95
    wind = [f for f in out["findings"] if f["rule"] == "windup" and f["axis"] == "spd"]
    assert wind, "실제 포화 런에서 와인드업 규칙이 아무것도 안 냈다 — 시그니처가 낡았다"
    sev = wind[0]["severity"]
    assert sev == "warn", f"경고가 아니라 {sev}"


def test_와인드업_판정량은_제어주기에_안_매인다():
    """규칙 3이 재는 것은 **물리 시간**이지 제어 틱 수가 아니다.

    계측 신호는 제어 틱마다만 갱신되므로(ZOH) 틱 사이를 "동결"로 읽으면 오탐이
    난다. 그래서 틱만 판정하는데, **틱 표본 하나로만 세면** 이번엔 판정량이
    제어주기에 매인다: 같은 물리 사건이 100 Hz에서 frac 0.853·최장 51 s,
    20 Hz에서 frac 0.171·최장 0.01 s로 읽혔다. 후자가 더 나쁘다 — 51초 연속
    막힘이 "무시해도 되는 것"으로 화면에 나간다. 그래서 틱 판정을 그 틱이
    대표하는 ZOH 구간 전체로 펼친다.

    control_hz는 스윕 노브라(pipeline/influence.py) 이 왜곡은 실제로 밟힌다.
    """
    ev = {}
    for hz in (100.0, 20.0):
        _, out = _saturating_run(hz)
        w = [f for f in out["findings"] if f["rule"] == "windup" and f["axis"] == "spd"]
        assert w and w[0]["severity"] == "warn", f"control_hz={hz}에서 경고가 안 났다"
        ev[hz] = w[0]["evidence"]
    a, b = ev[100.0], ev[20.0]
    # 같은 사건이므로 세 지표가 전부 같은 크기여야 한다 (틱 수가 5배 다르다)
    assert abs(a["parked_frac"] - b["parked_frac"]) < 0.05, (
        f"막힘 비율이 제어주기에 매였다: {a['parked_frac']:.3f} vs {b['parked_frac']:.3f}")
    assert abs(a["longest"] - b["longest"]) < 1.0, (
        f"최장 지속이 제어주기에 매였다: {a['longest']:.2g} s vs {b['longest']:.2g} s")
    assert a["longest"] > 10.0 and b["longest"] > 10.0, "연속 막힘이 한 칸으로 쪼개졌다"
    assert a["events"] == b["events"] == 1


def test_ki가_0인_축은_와인드업으로_잡지_않는다():
    """요축은 설계상 ki = 0인 댐퍼다(fcl/demo.py DEMO_YAW). 적분기가 구조적으로
    안 움직이므로 "동결 + 출력 포화"가 **항상** 참이 되어 100% 오탐이 나고,
    처방은 이미 0인 게인을 줄이라고 말한다 — 진단이 낼 수 있는 최악의 종류다.

    실측 런으로는 이 가지가 안 열린다(β가 작아 yaw_pi가 한계에 안 붙는다).
    그래서 여기서 직접 만든다: 출력은 한계에 붙고 적분기는 상수.
    """
    p = _payload()
    s = p["signals"]
    s["yaw_pi"][:] = 0.35  # 출력이 상한에 붙어 있다
    s["i_yaw"][:] = 0.1  # 적분기는 상수 — ki = 0의 서명 (클램프 ±0.35 근처도 아니다)
    out = diagnose_run(p, Shape())
    wind = [f for f in out["findings"] if f["rule"] == "windup" and f["axis"] == "yaw"]
    assert not wind, f"ki=0 축에 와인드업 오탐: {wind}"
    # 그리고 살아 있는 적분기라면 같은 형상에서 반드시 잡아야 한다 (가드가 공허하지 않다)
    s["i_yaw"][:] = np.linspace(0.1, 0.1002, N)  # 미세하지만 움직인다 → 적분기 있음
    s["i_yaw"][40:] = 0.1002  # 그 뒤 동결 — 출력은 계속 포화 (80%)
    out2 = diagnose_run(p, Shape())
    wind2 = [f for f in out2["findings"] if f["rule"] == "windup" and f["axis"] == "yaw"]
    assert wind2 and wind2[0]["severity"] == "warn", "살아 있는 적분기의 동결을 놓쳤다"


def test_규칙3이_판정을_접을_때는_조용히_넘기지_않는다():
    """②(조건부 적분 시그니처)를 못 볼 때마다 **경고가 남아야** 한다.

    세 경로가 있고 셋 다 이유가 다르다: control_hz 미상(ZOH 보정 불가) · 적분기가
    런 내내 정지(ki=0인지 전 구간 막힘인지 신호로 구분 불가) · 런이 제어 틱보다 짧음.
    조용히 ①만 낸 값은 조건부 적분에서 죽은 시그니처라 **근거 없는 0%**가 된다 —
    이 모듈의 규약이 "판정 불가를 0으로 위장하지 않는다"이다.
    """
    # ㉠ control_hz 미상 — 구버전 결과. **①은 그대로 내고 ②만 접는다**가 계약이므로
    # ②로만 잡히는 형상(출력 포화 중 적분기 동결, 클램프 주차는 없음)을 넣어 갈린다
    def _frozen_while_saturated():
        q = _payload()
        q["signals"]["ap_alt_pi"][:] = 0.3  # 출력이 클램프(±0.3) 상한에 붙어 있다
        i = np.linspace(0.0, 0.2, N)
        i[40:] = i[39]  # 살아 있다가 동결 — 클램프 0.3에는 안 닿는다(②의 형상)
        q["signals"]["i_alt"] = i
        return q

    p = _frozen_while_saturated()
    p["meta"].pop("control_hz")
    out = diagnose_run(p, Shape())
    assert any("control_hz 미상" in w for w in out["warnings"]), out["warnings"]
    assert not [f for f in out["findings"] if f["rule"] == "windup"], "②를 접었어야 한다"
    # 대조군 — 같은 신호에 control_hz만 있으면 잡힌다 (위 단정이 공허하지 않다)
    got = [f for f in diagnose_run(_frozen_while_saturated(), Shape())["findings"]
           if f["rule"] == "windup"]
    assert got and got[0]["axis"] == "alt", f"②가 이 형상을 못 본다: {got}"

    # ㉡ 적분기 정지 — 출력은 한계에 붙어 있는데 적분기가 상수 (ki=0의 서명)
    p = _payload()
    p["signals"]["yaw_pi"][:] = 0.35
    p["signals"]["i_yaw"][:] = 0.1
    out = diagnose_run(p, Shape())
    assert any("적분기가 런 내내 정지" in w and "yaw" in w for w in out["warnings"]), out["warnings"]
    wu = [w for w in out["warnings"] if "와인드업" in w]
    assert len(wu) == 1, f"포화도 안 한 축까지 경고했다: {wu}"

    # ㉢ 런이 제어 틱보다 짧다 — step > N. 적분기가 **살아 있어야** 이 가지에 닿는다
    p = _payload()
    p["signals"]["ap_alt_pi"][:] = 0.3  # 출력 포화 (클램프 ±0.3)
    p["signals"]["i_alt"][:] = np.linspace(0.0, 0.2, N)  # 적분기는 살아 있다
    p["meta"]["control_hz"] = 1.0 / (DT * (N + 10))
    out = diagnose_run(p, Shape())
    assert any("제어주기보다 짧다" in w for w in out["warnings"]), out["warnings"]
