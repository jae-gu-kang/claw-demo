"""설계 지표 계산 — `influence.METRICS` 선언의 계산 짝 (진단·3단 스윕의 공용 입력).

METRICS는 지금까지 "이 지표가 무엇을 읽는가"의 선언이었고 계산이 없었다 —
`metric_values`가 그 짝이다. 선언과 계산은 이중 정의이므로 키 집합 일치를
test_metrics가 핀한다 (한쪽에 지표를 더하고 다른 쪽을 잊으면 터진다).

입력은 SimResult의 (t, signals, envelope, meta) 그대로이며 **JSON 왕복본을
수용**한다(list·null — `duty_report`와 같은 계약: 저장된 원본을 쥔 서버가 부른다).
전 해상도 입력 전제도 duty와 같다 — stride 다운샘플본으로 재면 짧은 포화·이탈이
사라져 조용히 낙관적인 수치가 나온다.

추종 RMS는 **활성 구간만** 잰다: 축이 꺼진 스텝의 cmd·필터 노드는 0
(disabled_output)이라 게이팅 없이 재면 "꺼진 축이 안 따라간다"는 거짓 오차가
지표를 지배한다. 전 구간 꺼짐·판정 불가는 0이 아니라 None — "오차가 없다"와
"잴 수 없다"는 다른 사실이다 (duty의 None 규약과 동일).
"""

import numpy as np

from claw.analysis.duty import CHANNELS, POS_TOL, surface_positions
from claw.pipeline.influence import METRICS


def wrap_pi(a):
    """벡터화 wrap — 연산 순서는 ir_exec._OP_FN["wrap_pi"] 자구 그대로 (이중 정의지만
    스칼라·배열 형이 달라 공유가 안 된다; 대조는 test_metrics가 수치로 못박는다)."""
    a = np.asarray(a, dtype=float)
    return -((-a + np.pi) % (2.0 * np.pi) - np.pi)


def _arr(signals, name):
    v = signals.get(name)
    return None if v is None else np.asarray(v, dtype=float)


def _rms(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return None if x.size == 0 else float(np.sqrt(np.mean(x * x)))


def _tracking_rms(signals, cmd_key, y_key, on_key, *, angular=False):
    cmd, y, on = _arr(signals, cmd_key), _arr(signals, y_key), _arr(signals, on_key)
    if cmd is None or y is None:
        return None
    mask = np.ones(cmd.shape, dtype=bool) if on is None else on > 0.5
    if not mask.any():
        return None
    e = y[mask] - cmd[mask]
    if angular:
        e = wrap_pi(e)
    return _rms(e)


def _surf_sat_frac(signals, meta):
    limits = dict((meta or {}).get("limits") or {})
    try:
        surfaces = surface_positions(signals)
    except KeyError:
        return None
    masks = []
    for key, _label, prefix in CHANNELS:
        lo, hi = limits.get(f"{prefix}_lo"), limits.get(f"{prefix}_hi")
        if lo is None and hi is None:
            continue  # 한계 미상 채널은 판정 불가 — 0으로 위장하지 않는다
        x = surfaces[key]
        m = np.zeros(x.shape, dtype=bool)
        if hi is not None:
            m |= x >= float(hi) - POS_TOL
        if lo is not None:
            m |= x <= float(lo) + POS_TOL
        masks.append(m)
    if not masks:
        return None
    return float(np.mean(np.any(masks, axis=0)))


def _xtrack_rms(signals, waypoints):
    if not waypoints:
        return None
    pn, pe = _arr(signals, "pn"), _arr(signals, "pe")
    if pn is None or pe is None:
        return None
    wps = np.asarray(waypoints, dtype=float).reshape(-1, 2)
    pts = np.column_stack([pn, pe])
    if wps.shape[0] == 1:
        return _rms(np.hypot(pn - wps[0, 0], pe - wps[0, 1]))
    best = np.full(pn.shape, np.inf)
    for a, b in zip(wps[:-1], wps[1:]):
        ab = b - a
        L2 = float(ab @ ab)
        if L2 == 0.0:
            d = np.hypot(pn - a[0], pe - a[1])
        else:
            s = np.clip((pts - a) @ ab / L2, 0.0, 1.0)
            proj = a + s[:, None] * ab
            d = np.hypot(pn - proj[:, 0], pe - proj[:, 1])
        best = np.minimum(best, d)
    return _rms(best)


def metric_values(t, signals, envelope, meta, waypoints=None) -> dict:
    """설계 지표 8개 전부 — 키 집합은 METRICS 선언과 일치한다 (test_metrics 핀).

    waypoints 인자가 정본이고, 없으면 저장 meta의 동봉본(routes/sim.py가 싣는다)을
    쓴다. 둘 다 없으면 xtrack_rms=None.
    """
    envelope = envelope or {}
    meta = meta or {}
    if waypoints is None:
        waypoints = meta.get("waypoints")

    flags = envelope.get("flags") or {}
    any_arr = None
    for arr in flags.values():
        b = np.asarray(arr, dtype=bool)
        any_arr = b if any_arr is None else (any_arr | b)

    worst = envelope.get("worst_margin")
    la = signals.get("limiter_active")

    out = {
        "worst_stall_margin": None if worst is None else float(worst),
        "envelope_flags": None if any_arr is None else int(any_arr.sum()),
        "alt_rms": _tracking_rms(signals, "cmd_alt", "h", "alt_on"),
        "spd_rms": _tracking_rms(signals, "cmd_speed", "V", "speed_on"),
        "hdg_rms": _tracking_rms(signals, "cmd_heading", "psi", "heading_on",
                                 angular=True),
        "surf_sat_frac": _surf_sat_frac(signals, meta),
        "limiter_frac": (
            None if la is None else float(np.mean(np.asarray(la, dtype=bool)))
        ),
        "xtrack_rms": _xtrack_rms(signals, waypoints),
    }
    assert set(out) == {m.key for m in METRICS}, "METRICS 선언·계산 드리프트"
    return out
