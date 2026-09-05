"""pipeline.metrics 검증 — METRICS 선언(influence.py)과 계산의 짝 맞춤 + 합성 수치.

지표는 지금까지 선언(MetricDef)만 있고 계산이 없었다 — metric_values가 그
계산 짝이다. 여기서 지키는 것: ① 선언·계산 이중 정의가 드리프트하면 터진다
② 수치가 손계산과 일치한다 ③ JSON 왕복본(list·null)을 수용한다 ④ 활성 게이팅
(비활성 축의 cmd는 의미 없음) ⑤ 웨이포인트 부재는 0이 아니라 None.
"""

import math

import numpy as np
import pytest

from claw.pipeline.influence import METRICS
from claw.pipeline.metrics import metric_values


def _payload(n=4):
    """전 지표가 계산 가능한 최소 합성 런 — 값은 전부 '조용한' 기준선."""
    z = [0.0] * n
    signals = {
        "h": [1000.0] * n, "cmd_alt": [1000.0] * n, "alt_on": [1.0] * n,
        "V": [200.0] * n, "cmd_speed": [200.0] * n, "speed_on": [1.0] * n,
        "psi": z, "cmd_heading": z, "heading_on": [1.0] * n,
        "de": z, "da": z, "dr": z,
        "limiter_active": [False] * n,
        "pn": z, "pe": z,
    }
    envelope = {
        "worst_margin": 0.25,
        "flags": {"alpha": [False] * n, "altitude": [False] * n},
    }
    meta = {
        "dt_plant": 0.01,
        "limits": {"elevon_lo": -0.35, "elevon_hi": 0.35,
                   "rudder_lo": -0.2, "rudder_hi": 0.2, "rate_max": None},
        "waypoints": None,
    }
    t = [0.01 * k for k in range(n)]
    return t, signals, envelope, meta


def test_키_집합이_METRICS_선언과_일치한다():
    """선언(influence.METRICS)과 계산(metric_values)은 이중 정의다 — 한쪽에 지표를
    더하고 다른 쪽을 잊으면 여기서 터진다."""
    t, signals, envelope, meta = _payload()
    out = metric_values(t, signals, envelope, meta)
    assert set(out) == {m.key for m in METRICS}


def test_추종_RMS_손계산_일치():
    t, signals, envelope, meta = _payload()
    signals["h"] = [1000.0, 1002.0, 998.0, 1000.0]  # 오차 [0,2,-2,0] → RMS √2
    out = metric_values(t, signals, envelope, meta)
    assert out["alt_rms"] == pytest.approx(np.sqrt(2.0))
    assert out["spd_rms"] == pytest.approx(0.0)


def test_헤딩_RMS는_각도_랩을_따른다():
    """ψ=2π−0.1 vs 명령 0은 오차 0.1이지 6.18이 아니다 — 랩 없이 재면 북쪽 통과가
    거대 오차로 둔갑한다."""
    t, signals, envelope, meta = _payload()
    signals["psi"] = [2.0 * np.pi - 0.1] * 4
    out = metric_values(t, signals, envelope, meta)
    assert out["hdg_rms"] == pytest.approx(0.1, rel=1e-9)


def test_비활성_축은_게이팅된다():
    """축이 꺼진 스텝의 cmd·필터 노드는 의미가 없다(disabled_output=0) — 켜진
    구간만 재야 한다. 전 구간 꺼짐이면 값이 아니라 None."""
    t, signals, envelope, meta = _payload()
    signals["alt_on"] = [1.0, 1.0, 0.0, 0.0]
    signals["cmd_alt"] = [1000.0, 1000.0, 0.0, 0.0]  # off 구간의 cmd는 쓰레기
    out = metric_values(t, signals, envelope, meta)
    assert out["alt_rms"] == pytest.approx(0.0)
    signals["alt_on"] = [0.0] * 4
    assert metric_values(t, signals, envelope, meta)["alt_rms"] is None


def test_타면_포화율과_리미터_작동률():
    t, signals, envelope, meta = _payload()
    # 표본 1에서 elevon_l = de+da = 0.35 (한계) — 4표본 중 1 = 0.25
    signals["de"] = [0.0, 0.35, 0.0, 0.0]
    signals["limiter_active"] = [True, True, False, False]
    out = metric_values(t, signals, envelope, meta)
    assert out["surf_sat_frac"] == pytest.approx(0.25)
    assert out["limiter_frac"] == pytest.approx(0.5)


def test_엔벨로프_이탈은_표본별_OR_개수다():
    t, signals, envelope, meta = _payload()
    envelope["flags"] = {"alpha": [True, False, False, False],
                         "altitude": [True, True, False, False]}
    out = metric_values(t, signals, envelope, meta)
    assert out["envelope_flags"] == 2  # 표본 0·1 (중복은 한 번)
    assert out["worst_stall_margin"] == pytest.approx(0.25)


def test_경로오차는_폴리라인_최근접이고_부재는_None():
    t, signals, envelope, meta = _payload()
    signals["pn"] = [0.0, 50.0, 100.0, 100.0]
    signals["pe"] = [3.0, 4.0, 0.0, 0.0]
    out = metric_values(t, signals, envelope, meta)
    assert out["xtrack_rms"] is None  # 웨이포인트 없음 — 0이 아니라 판정 불가

    meta["waypoints"] = [[0.0, 0.0], [100.0, 0.0]]  # 저장 meta 동봉 경로
    out = metric_values(t, signals, envelope, meta)
    assert out["xtrack_rms"] == pytest.approx(np.sqrt((9.0 + 16.0) / 4.0))

    # 인자 waypoints가 meta보다 우선한다 (호출자가 명시하면 그것이 정본)
    out = metric_values(t, signals, envelope, meta, waypoints=[[0.0, 3.0], [100.0, 3.0]])
    assert out["xtrack_rms"] == pytest.approx(np.sqrt((0.0 + 1.0 + 9.0 + 9.0) / 4.0))


def test_xtrack_rms_ignores_the_altitude_column():
    """3열 웨이포인트(n, e, alt)에서 고도 열이 좌표로 섞이지 않는다.

    종전 reshape(-1, 2)는 원소 수가 짝수이기만 하면 예외 없이 엉뚱한 좌표쌍을
    만들었다 — 지표가 말없이 거짓이 되는 자리다. 같은 수평 경로면 고도를 붙이든
    말든 xtrack_rms가 **같아야** 한다.
    """
    from claw.pipeline.metrics import _xtrack_rms

    sig = {"pn": [0.0, 500.0, 1000.0], "pe": [0.0, 30.0, 0.0]}
    flat = _xtrack_rms(sig, [[0.0, 0.0], [1000.0, 0.0]])
    with_alt = _xtrack_rms(sig, [[0.0, 0.0, 500.0], [1000.0, 0.0, 1500.0]])
    assert flat == pytest.approx(with_alt)
    assert with_alt == pytest.approx(_rms_of([0.0, 30.0, 0.0]))


def _rms_of(vals):
    import numpy as np
    return float(np.sqrt(np.mean(np.square(np.asarray(vals, dtype=float)))))


# ---- 이착륙 지표 (01 §3.3.1) ----


def _landing_signals(n=12):
    """접지 t=0.03, 정지 t=0.09인 합성 신호.

    승강률은 **시뮬이 기록한 hdot 신호**다 — 지표는 그것을 읽을 뿐 u·v·w·φ·θ에서
    다시 유도하지 않는다. 그 유도식이 세 벌로 늘어났던 것이 문제였고(하나는 φ·v를
    빠뜨린 φ=0 특수해), 지금은 sim/simulator.py의 body_to_ned 한 곳에만 있다.
    """
    import numpy as np

    return {
        "hdot": np.full(n, -0.7556),  # 강하 중 (상승 +이므로 음수)
        # V·pn을 표본마다 흔들어 인덱스를 실제로 고정한다 — 전부 상수면 k가 한 칸
        # 어긋나도 단정이 통과해 버린다
        "V": 81.4 + np.arange(n) * 0.5,
        "pn": np.arange(n) * 100.0, "pe": np.zeros(n),
        "launch_gx": np.array([33.9] * 3 + [0.0] * (n - 3)),
        "on_rail": np.array([1.0] * 3 + [0.0] * (n - 3)),
        "wow": np.array([0, 0, 0] + [1] * (n - 3), dtype=bool),
    }


def test_climb_rate_reads_the_logged_signal_not_a_second_formula():
    """지표는 시뮬이 남긴 참값 승강률을 **읽는다** — 여기서 다시 유도하지 않는다.

    신호가 없으면(지면 도입 전 저장 결과) None이지 0이 아니다. 회전식 자체의
    정확성은 시뮬 쪽 성질이라 test_launch가 body_to_ned 대조로 못박는다.
    """
    from claw.pipeline.metrics import climb_rate

    sig = _landing_signals()
    assert climb_rate(sig, 3) == pytest.approx(-0.7556)
    assert climb_rate({k2: v2 for k2, v2 in sig.items() if k2 != "hdot"}, 3) is None
    assert climb_rate({**sig, "hdot": [None] * 12}, 3) is None
    assert climb_rate({**sig, "hdot": np.full(12, np.nan)}, 3) is None
    assert climb_rate(sig, 999) is None, "범위 밖 인덱스"


def test_touchdown_is_a_descent_in_this_fixture():
    """부호 규약을 따로 고정한다 — 지표가 크기라 그 안에서는 안 드러난다."""
    from claw.pipeline.metrics import climb_rate

    assert climb_rate(_landing_signals(), 3) < 0.0, "접지는 내려오면서 한다"


def test_landing_metrics_from_phase_times():
    from claw.pipeline.metrics import _landing_metrics

    n = 12
    t = np.arange(n) * 0.01
    meta = {"phases": {"launch_exit_t": 0.02, "touchdown_t": 0.03, "stop_t": 0.09}}
    out = _landing_metrics(t, _landing_signals(n), meta)
    assert out["td_sink_rate"] == pytest.approx(0.7556, abs=1e-4)
    assert out["td_sink_rate"] > 0.0, "지표는 **크기**다 (better='lower'가 참이려면)"
    assert out["td_speed"] == pytest.approx(81.4 + 3 * 0.5), "접지 표본의 V"
    assert out["rollout_dist"] == pytest.approx(600.0)  # 300 m → 900 m
    assert out["launch_gx"] == pytest.approx(33.9)


def test_touchdown_is_a_descent_in_this_fixture():
    """부호 규약을 따로 고정한다 — 지표가 크기라 그 안에서는 안 드러난다."""
    from claw.pipeline.metrics import climb_rate

    assert climb_rate(_landing_signals(), 3) < 0.0, "접지는 내려오면서 한다"


def test_landing_metrics_are_none_when_the_phase_never_happened():
    """0으로 채우면 착륙하지 않은 런이 '접지 강하율 0 = 완벽한 착륙'이 된다."""
    from claw.pipeline.metrics import _landing_metrics

    n = 12
    t = np.arange(n) * 0.01
    sig = _landing_signals(n)
    sig["launch_gx"] = np.zeros(n)
    sig["on_rail"] = np.zeros(n)
    sig["wow"] = np.zeros(n, dtype=bool)
    out = _landing_metrics(t, sig, {"phases": {
        "launch_exit_t": None, "touchdown_t": None, "stop_t": None}})
    assert out == {"td_sink_rate": None, "td_speed": None,
                   "rollout_dist": None, "launch_gx": None}
    # meta에 phases 자체가 없어도(구 결과 재생) 조용히 0을 만들지 않는다
    assert _landing_metrics(t, sig, {})["td_sink_rate"] is None


def test_launch_load_survives_a_run_cut_short_on_the_rail():
    """레일 위에서 절단된 런도 사출 하중을 낸다 — 하중 판정이 가장 급한 런이다.

    이탈 시각으로 관문을 걸면 이 런이 "발사 없음"으로 접혀 측정값이 버려진다.
    발사가 있었는가의 직접 근거는 on_rail이다.
    """
    from claw.pipeline.metrics import _landing_metrics

    n = 3
    sig = {k2: v2[:n] for k2, v2 in _landing_signals(12).items()}
    out = _landing_metrics(np.arange(n) * 0.01, sig,
                           {"phases": {"launch_exit_t": None,
                                       "touchdown_t": None, "stop_t": None}})
    assert out["launch_gx"] == pytest.approx(33.9)
    assert out["td_sink_rate"] is None, "접지는 하지 않았다"


def test_touchdown_without_stop_has_no_rollout():
    """접지했지만 아직 안 멈췄으면 미끄럼 거리는 없음 — 미래를 지어내지 않는다."""
    from claw.pipeline.metrics import _landing_metrics

    n = 12
    sig = _landing_signals(n)
    sig["on_rail"] = np.zeros(n)
    out = _landing_metrics(np.arange(n) * 0.01, sig,
                           {"phases": {"launch_exit_t": None,
                                       "touchdown_t": 0.03, "stop_t": None}})
    assert out["td_speed"] is not None
    assert out["rollout_dist"] is None
    assert out["launch_gx"] is None, "레일에 오른 적이 없으면 사출 하중도 없다"


def test_nan_samples_do_not_pass_as_metric_values():
    """NaN이 None 자리로 새면 '판정 불가'가 수치인 척 집계에 들어간다."""
    from claw.pipeline.metrics import _landing_metrics

    n = 12
    sig = _landing_signals(n)
    sig["V"] = np.full(n, np.nan)
    sig["pn"] = np.full(n, np.nan)
    out = _landing_metrics(np.arange(n) * 0.01, sig,
                           {"phases": {"launch_exit_t": 0.02,
                                       "touchdown_t": 0.03, "stop_t": 0.09}})
    assert out["td_speed"] is None
    assert out["rollout_dist"] is None
    assert out["td_sink_rate"] is not None, "온전한 신호는 그대로 나온다"


# ── 스텝 응답 특성 (step_metrics — A⑤·B급 지표의 계산부) ────────────────────


def _step_series(y_unit, dt=0.001, t_pre=1.0):
    """단위 스텝 응답 y(t) → (t, cmd, y) — 스텝 전 구간을 붙여 변화점 감지를 시험."""
    n0 = int(round(t_pre / dt))
    cmd = np.concatenate([np.zeros(n0), np.ones(len(y_unit))])
    y = np.concatenate([np.zeros(n0), np.asarray(y_unit, dtype=float)])
    return np.arange(cmd.size) * dt, cmd, y


def test_step_metrics_2차계_오버슈트는_닫힌형과_일치한다():
    from claw.pipeline.metrics import step_metrics

    z, wn, dt = 0.5, 2.0, 0.001
    t = np.arange(0.0, 12.0, dt)
    wd = wn * math.sqrt(1 - z * z)
    y = 1 - np.exp(-z * wn * t) / math.sqrt(1 - z * z) * np.sin(
        wd * t + math.acos(z))
    tt, cmd, resp = _step_series(y, dt=dt)
    m = step_metrics(tt, cmd, resp, None)
    assert abs(m["mp"] - math.exp(-math.pi * z / math.sqrt(1 - z * z))) < 5e-3
    assert 0.0 < m["tr"] < m["ts"] < math.inf  # 10→90이 정착보다 빠르다
    assert m["sse"] < 1e-3  # 잔차 없는 응답


def test_step_metrics_1차계는_오버슈트_0과_ln9_상승시간():
    from claw.pipeline.metrics import step_metrics

    a, dt = 1.0, 0.001
    t = np.arange(0.0, 15.0, dt)
    y = 1 - np.exp(-a * t)
    tt, cmd, resp = _step_series(y, dt=dt)
    m = step_metrics(tt, cmd, resp, None)
    assert m["mp"] == 0.0
    assert abs(m["tr"] - math.log(9.0) / a) < 5e-3  # t90−t10 = ln9/a
    # Ts(±2 %) = ln50/a
    assert abs(m["ts"] - math.log(50.0) / a) < 5e-3


def test_step_metrics_창_안에서_안_일어난_일은_inf다():
    """미도달·미정착은 None(못 쟀다)이 아니라 ∞(느리다의 극한)이다 — None이면
    판정이 na로 빠져 정착 실패가 조용히 넘어간다."""
    from claw.pipeline.metrics import step_metrics

    tt, cmd, resp = _step_series(np.zeros(3000))  # 전혀 안 움직이는 응답
    m = step_metrics(tt, cmd, resp, None)
    assert m["tr"] == math.inf and m["ts"] == math.inf
    assert m["mp"] == 0.0


def test_step_metrics_스텝이_없으면_전부_None():
    from claw.pipeline.metrics import step_metrics

    t = np.arange(0.0, 3.0, 0.01)
    flat = np.ones_like(t)
    m = step_metrics(t, flat, flat, None)
    assert m == {"tr": None, "ts": None, "mp": None, "sse": None}


def test_step_metrics_발산_창은_전부_inf():
    """NaN은 비교에서 False라 그대로 두면 발산이 「정착」으로 위장된다."""
    from claw.pipeline.metrics import step_metrics

    y = np.concatenate([np.linspace(0, 1, 500), np.full(500, np.nan)])
    tt, cmd, resp = _step_series(y)
    m = step_metrics(tt, cmd, resp, None)
    assert all(m[k] == math.inf for k in ("tr", "ts", "mp", "sse"))


def test_step_metrics_하강_스텝도_같은_축이다():
    """진행률은 스텝 방향으로 접힌다 — 하강 스텝의 오버슈트(아래로 지나침)가
    음수나 0으로 뭉개지면 안 된다."""
    from claw.pipeline.metrics import step_metrics

    dt = 0.001
    t = np.arange(0.0, 10.0, dt)
    z, wn = 0.5, 2.0
    wd = wn * math.sqrt(1 - z * z)
    yu = 1 - np.exp(-z * wn * t) / math.sqrt(1 - z * z) * np.sin(
        wd * t + math.acos(z))
    n0 = 1000
    cmd = np.concatenate([np.ones(n0), np.zeros(t.size)])  # 1 → 0 하강
    y = np.concatenate([np.ones(n0), 1.0 - yu])
    m = step_metrics(np.arange(cmd.size) * dt, cmd, y, None)
    assert abs(m["mp"] - math.exp(-math.pi * z / math.sqrt(1 - z * z))) < 5e-3


def test_step_metrics_헤딩은_랩을_넘는_스텝을_바르게_잰다():
    from claw.pipeline.metrics import step_metrics

    dt = 0.01
    # 3.0 rad → −3.0 rad: 랩 경유 실제 스텝은 +0.2832 rad (2π−6)
    h = 2.0 * math.pi - 6.0
    n0, n1 = 100, 400
    cmd = np.concatenate([np.full(n0, 3.0), np.full(n1, -3.0)])
    # 응답: 짧은 랩 방향으로 지수 수렴 (각도는 wrap 영역을 지난다)
    t1 = np.arange(n1) * dt
    y1 = 3.0 + h * (1 - np.exp(-3.0 * t1))
    y1 = np.mod(y1 + math.pi, 2 * math.pi) - math.pi
    y = np.concatenate([np.full(n0, 3.0), y1])
    m = step_metrics(np.arange(cmd.size) * dt, cmd, y, None, angular=True)
    assert m["mp"] is not None and m["mp"] < 0.05  # 지수 수렴 — 사실상 무초과
    assert m["ts"] < math.inf


def test_잔여_권한은_배분_신호와_예산으로_잰다():
    from claw.pipeline.metrics import _authority_metrics

    meta = {"limits": {"elevon_hi": 0.35}}
    sig = {"alloc_pitch_hi": [0.35, 0.20, 0.28], "alloc_roll_hi": [0.30, 0.25, 0.35]}
    out = _authority_metrics(sig, meta)
    assert abs(out["min_pitch_authority_frac"] - 0.20 / 0.35) < 1e-12
    assert abs(out["min_roll_authority_frac"] - 0.25 / 0.35) < 1e-12
    # 배분 미장착(신호 없음·NaN뿐)은 0이 아니라 None — "다 썼다"와 "계측 없다"는 다르다
    assert _authority_metrics({}, meta)["min_pitch_authority_frac"] is None
    assert _authority_metrics(
        {"alloc_pitch_hi": [float("nan")]}, meta)["min_pitch_authority_frac"] is None


def test_포화_최장_지속은_채널_최악의_연속_구간이다():
    from claw.pipeline.metrics import _sat_longest

    n = 100
    dt = 0.01
    meta = {"limits": {"elevon_lo": -0.35, "elevon_hi": 0.35,
                       "rudder_lo": -0.3, "rudder_hi": 0.3},
            "dt_plant": dt}
    de = np.zeros(n)
    de[10:30] = 0.35  # 좌·우 엘레본 모두 20표본 = 0.2 s 포화
    sig = {"de": de, "da": np.zeros(n), "dr": np.zeros(n)}
    assert abs(_sat_longest(sig, meta, np.arange(n) * dt) - 0.2) < 1e-9
