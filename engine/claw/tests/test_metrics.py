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
    """접지 t=0.03, 정지 t=0.09인 합성 신호 — **실제로 강하 중**이고 뱅크가 있다.

    처음 이 픽스처는 w=19.7이었는데 그 값에서 ḣ = +0.46, 즉 초당 0.46 m로
    **올라가는** 접지였다. 기댓값을 구현식으로 다시 평가해 만들었던 탓에 아무도
    못 잡았다 — 그래서 여기 값은 손으로 확인한 −1.0 근처로 두고, 아래 단정은
    구현을 베끼지 않은 독립 산출값을 쓴다.

    φ와 v를 0이 아닌 값으로 두는 것이 핵심이다: 근사식(u·sinθ − w·cosθ)은 그 둘이
    0일 때만 맞으므로, 여기서 0을 주면 φ·v 항 누락을 원리적으로 못 잡는다.
    """
    import numpy as np

    th = np.full(n, 0.25)  # θ = 14.32°
    phi = np.full(n, 0.17)  # φ = 9.74° — 측풍 접지(디크랩)
    u = np.full(n, 79.0)
    v = np.full(n, 5.0)  # 횡속도가 있어야 v·sinφ·cosθ 항이 드러난다
    w = np.full(n, 20.4)
    return {
        "u": u, "v": v, "w": w, "phi": phi, "theta": th,
        # V·theta를 표본마다 흔들어 인덱스를 실제로 고정한다 — 전부 상수면
        # k가 한 칸 어긋나도 단정이 통과해 버린다
        "V": 81.4 + np.arange(n) * 0.5,
        "pn": np.arange(n) * 100.0, "pe": np.zeros(n),
        "launch_gx": np.array([33.9] * 3 + [0.0] * (n - 3)),
        "on_rail": np.array([1.0] * 3 + [0.0] * (n - 3)),
        "wow": np.array([0, 0, 0] + [1] * (n - 3), dtype=bool),
    }


def test_climb_rate_is_the_exact_rotation_not_the_phi_zero_special_case():
    """φ·v 항이 빠진 근사식과 정확식이 갈리는 것을 직접 못박는다.

    근사 u·sinθ − w·cosθ는 φ=0·v=0에서만 맞는다. 측풍 접지에서 0.5 m/s 넘게
    틀리고, 접지 강하율의 판별 범위(1.0 대 4.6)를 생각하면 결론이 바뀐다.
    """
    from claw.pipeline.metrics import climb_rate

    sig = _landing_signals()
    got = climb_rate(sig, 3)
    u, v, w, phi, th = 79.0, 5.0, 20.4, 0.17, 0.25
    exact = (u * math.sin(th) - v * math.sin(phi) * math.cos(th)
             - w * math.cos(phi) * math.cos(th))
    assert got == pytest.approx(exact)
    naive = u * math.sin(th) - w * math.cos(th)
    assert abs(naive - exact) > 0.5, "이 픽스처가 근사식 오차를 드러내야 한다"
    # φ=0·v=0이면 둘이 같아진다 — 근사가 언제 맞는지도 함께 고정
    flat = {**sig, "phi": np.zeros(12), "v": np.zeros(12)}
    assert climb_rate(flat, 3) == pytest.approx(
        u * math.sin(th) - w * math.cos(th)
    )


def test_climb_rate_refuses_nonfinite_samples():
    """JSON 왕복본의 null은 _arr에서 NaN이 된다 — 수치인 척 흘려보내지 않는다."""
    from claw.pipeline.metrics import climb_rate

    sig = _landing_signals()
    assert climb_rate(sig, 3) is not None
    assert climb_rate({**sig, "v": [None] * 12}, 3) is None
    assert climb_rate({**sig, "phi": np.full(12, np.nan)}, 3) is None
    assert climb_rate({k2: v2 for k2, v2 in sig.items() if k2 != "w"}, 3) is None
    assert climb_rate(sig, 999) is None, "범위 밖 인덱스"


def test_landing_metrics_from_phase_times():
    from claw.pipeline.metrics import _landing_metrics

    n = 12
    t = np.arange(n) * 0.01
    meta = {"phases": {"launch_exit_t": 0.02, "touchdown_t": 0.03, "stop_t": 0.09}}
    out = _landing_metrics(t, _landing_signals(n), meta)
    # **독립 산출값이다** — 구현식을 다시 평가하지 않는다.
    #   79·sin0.25          = +19.5449
    #   −5·sin0.17·cos0.25  =  −0.8196
    #   −20.4·cos0.17·cos0.25 = −19.4809
    #   합 ḣ = −0.7556  →  크기 0.7556
    # (처음 여기 −1.0245를 적었다가 틀렸다. 구현식을 베꼈다면 그 오류가 드러나지
    #  않았을 것이고, 그래서 이 자리는 손계산 상수여야 한다.)
    assert out["td_sink_rate"] == pytest.approx(0.7556, abs=1e-3)
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
