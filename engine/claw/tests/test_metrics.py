"""pipeline.metrics 검증 — METRICS 선언(influence.py)과 계산의 짝 맞춤 + 합성 수치.

지표 8개는 지금까지 선언(MetricDef)만 있고 계산이 없었다 — metric_values가 그
계산 짝이다. 여기서 지키는 것: ① 선언·계산 이중 정의가 드리프트하면 터진다
② 수치가 손계산과 일치한다 ③ JSON 왕복본(list·null)을 수용한다 ④ 활성 게이팅
(비활성 축의 cmd는 의미 없음) ⑤ 웨이포인트 부재는 0이 아니라 None.
"""

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
