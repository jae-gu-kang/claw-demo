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

import math

import numpy as np

from claw.analysis.duty import (
    CHANNELS, POS_TOL, _limits_for, saturation, surface_positions,
)
from claw.pipeline.influence import METRICS

# ── 응답특성의 **정의** 상수 — 문턱이 아니라 측정 규약이라 criteria가 아니라
# 여기 산다 (측정과 정의는 한 몸 — criteria.ResponseCriteria 참조 주석의 짝).
SETTLE_BAND_FRAC = 0.02  # Ts 정착 밴드: 스텝 크기의 ±2 % (고전 관례)
TR_LO, TR_HI = 0.10, 0.90  # Tr: 10→90 % 도달 시간
SSE_TAIL_FRAC = 0.10  # sse: 창 마지막 10 % 평균 잔차
_STEP_TOL = 1e-9  # 명령 변화 감지 — 유도 목표는 조각상수라 부동소수 왕복분이면 충분


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
    wps = np.asarray(waypoints, dtype=float)
    if wps.ndim == 1:
        wps = wps.reshape(-1, 2)  # 평탄 목록 관용 (종전 동작 유지)
    # (n, e) 또는 (n, e, alt) — 고도 열은 **수평** 경로오차와 무관하므로 버린다.
    # 종전처럼 reshape(-1, 2)로 뭉개면 3열 목록이 조용히 엉뚱한 좌표쌍이 된다:
    # 원소 수가 짝수이기만 하면 예외도 안 나서 xtrack_rms가 말없이 거짓이 된다
    wps = wps[:, :2]
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


def climb_rate(signals, k):
    """표본 k의 승강률 ḣ [m/s] (상승 +) — 시뮬이 기록한 참값 신호를 읽는다.

    **여기에 오일러 전개식을 적지 않는다.** 시뮬이 body_to_ned로 정확히 계산해
    "hdot" 신호로 남기므로(sim/simulator.py), 로그에서 그것을 다시 유도하면 같은
    물리량이 두 번 정의된다 — 실제로 그 사본이 웹까지 세 벌로 늘어났고, 그중
    하나가 φ·v 항을 빠뜨린 φ=0 특수해였다(측풍 접지에서 0.5 m/s 오차).

    신호가 없거나(지면 도입 전 저장 결과) 비유한이면 None — NaN을 수치인 척
    흘려보내지 않는다.
    """
    return _finite_at(signals, "hdot", k)


def _finite_at(signals, name, k):
    """표본 k의 유한값 또는 None — NaN이 지표 자리로 새지 않게 하는 공통 관문."""
    a = _arr(signals, name)
    if a is None or k >= len(a):
        return None
    x = float(a[k])
    return x if math.isfinite(x) else None


def _landing_metrics(t, signals, meta) -> dict:
    """이착륙 지표 — 그 단계가 없으면 **전부 None**이다 (01 §3.3.1).

    0으로 채우면 착륙하지 않은 런이 "접지 강하율 0 = 완벽한 착륙"으로, 발사하지
    않은 런이 "사출 하중 0 = 안전"으로 읽힌다. 없는 것은 없다고 말한다
    (01 §4.2 판정 불가를 0으로 위장하지 않는다와 같은 자리).

    단계 시각은 시뮬이 meta["phases"]에 이미 넣어 둔 것을 쓴다 — 여기서 wow를
    다시 훑어 접지 시각을 구하면 같은 판정이 두 곳에 적히고, 어긋나면 지표와
    화면이 다른 접지를 가리킨다 (02 §5.5).
    """
    out = {"td_sink_rate": None, "td_speed": None, "rollout_dist": None, "launch_gx": None}
    ph = (meta or {}).get("phases") or {}
    t_arr = np.asarray(t, dtype=float)

    # 발사가 **있었는가**의 직접 근거는 on_rail이다. launch_exit_t로 관문을 걸면
    # 레일 구간에서 절단된 런(구조 하중 판정이 가장 급한 런)이 이탈 시각 없음을
    # 이유로 측정값을 버린다 — 하중은 배열에 멀쩡히 기록돼 있는데도.
    rail = _arr(signals, "on_rail")
    gx = _arr(signals, "launch_gx")
    if rail is not None and gx is not None and len(gx) and np.any(rail > 0.0):
        peak = np.abs(gx[np.isfinite(gx)])
        if peak.size:
            out["launch_gx"] = float(peak.max())

    td = ph.get("touchdown_t")
    if td is None or len(t_arr) == 0:
        return out
    k = int(np.argmin(np.abs(t_arr - float(td))))

    hdot = climb_rate(signals, k)
    # **크기로 낸다.** better='lower'가 문자 그대로 참이어야 하는데, 부호 있는 승강률로는
    # 'higher'도 'lower'도 거짓이다 — 접지 순간 위로 튄 런(ḣ>0)이 소프트 랜딩보다
    # 좋게 랭크되거나 그 반대가 된다. |ḣ|는 "지면에 닿을 때 수직으로 얼마나 빨랐나"라
    # 구조 하중과 직결되고 작을수록 좋은 것이 항상 참이다. 부호가 필요한 소비자는
    # climb_rate()를 직접 부른다.
    out["td_sink_rate"] = None if hdot is None else abs(hdot)
    out["td_speed"] = _finite_at(signals, "V", k)

    st = ph.get("stop_t")
    if st is not None:
        j = int(np.argmin(np.abs(t_arr - float(st))))
        # 컴프리헨션으로 묶으면 언패킹 순서를 읽는 사람이 매번 다시 검증해야 한다 —
        # 네 줄이 더 짧지도 않으면서 검증이 필요 없다
        pn_k, pn_j = _finite_at(signals, "pn", k), _finite_at(signals, "pn", j)
        pe_k, pe_j = _finite_at(signals, "pe", k), _finite_at(signals, "pe", j)
        if None not in (pn_k, pn_j, pe_k, pe_j):
            out["rollout_dist"] = float(math.hypot(pn_j - pn_k, pe_j - pe_k))
    return out


def step_metrics(t, cmd, y, on, *, angular=False) -> dict:
    """축 하나의 스텝 응답 특성 — {"tr", "ts", "mp", "sse"} (A⑤·B급 지표의 계산부).

    스텝 경계는 **명령 신호 자체**에서 찾는다: 유도 목표는 조각상수라(모드가 목표를
    홀드) cmd의 변화점이 곧 스텝 시각이다 — 모드 시각표를 meta에 따로 실으면 같은
    사실이 두 곳에 적힌다. 창은 그 스텝부터 같은 축의 다음 변화(또는 런 끝)까지.

    값의 삼분법(0으로 위장 금지의 세 갈래):
    - **None**: 스텝이 없다(축이 꺼져 있거나 명령이 안 움직였다) — 잰 것이 없다
    - **inf**: 스텝이 있는데 창 안에서 그 일이 안 일어났다(90 % 미도달·미정착) —
      "느리다"의 극한이지 측정 불가가 아니다. 직렬화는 "inf"로 살아남고("inf" 규약)
      판정은 어떤 유한 상한보다도 크므로 자연히 fail이 된다
    - 유한값: 측정된 사실

    여러 스텝이면 **최악**(max)을 낸다 — 지표는 보증이지 평균이 아니다.
    Mp는 스텝 방향 기준 초과분/스텝 크기(무차원), sse는 창 꼬리 평균 잔차(절대 단위).
    """
    cmd_a, y_a = _arr({"c": cmd}, "c"), _arr({"y": y}, "y")
    if cmd_a is None or y_a is None or cmd_a.size < 2:
        return {"tr": None, "ts": None, "mp": None, "sse": None}
    t_a = np.asarray(t, dtype=float)
    mask = np.ones(cmd_a.shape, dtype=bool) if on is None else np.asarray(on) > 0.5

    diff = np.abs(np.diff(cmd_a))
    if angular:
        diff = np.abs(wrap_pi(np.diff(cmd_a)))
    starts = [int(k) + 1 for k in np.flatnonzero(diff > _STEP_TOL)
              if mask[int(k) + 1]]
    if not starts:
        return {"tr": None, "ts": None, "mp": None, "sse": None}
    bounds = starts + [cmd_a.size]

    worst = {"tr": None, "ts": None, "mp": None, "sse": None}

    def keep(key, v):
        if v is not None and (worst[key] is None or v > worst[key]):
            worst[key] = v

    for k0, k1 in zip(starts, bounds[1:]):
        if k1 - k0 < 2:
            continue
        y0, y1 = float(y_a[k0 - 1]), float(cmd_a[k0])
        e0 = (y1 - y0)
        if angular:
            e0 = float(wrap_pi(np.array([e0]))[0])
        h = abs(e0)
        if h <= _STEP_TOL:
            continue
        seg_t = t_a[k0:k1] - t_a[k0]
        err = y_a[k0:k1] - y1
        if angular:
            err = wrap_pi(err)
        if not np.isfinite(err).all():
            # 발산으로 잘린 창 — NaN은 비교에서 False라 그대로 두면 "정착"으로
            # 위장된다. 네 값 모두 inf: "그 일이 창 안에서 안 일어났다"의 극한이고
            # 발산한 런이 초록이 되는 일은 없다
            for key in ("tr", "ts", "mp", "sse"):
                keep(key, math.inf)
            continue
        # 진행률 = (y − y0)/e0. err = y − y1 = (진행률 − 1)·e0 이므로 1 + err/e0.
        # 시작(err = −e0)에서 0, 목표 도달에서 1, 초과에서 1 초과 — 부호가 스텝
        # 방향으로 접혀 하강 스텝에서도 같은 축이다
        travel = 1.0 + err / e0

        # Tr — 10 %·90 % 최초 도달. 90 % 미도달이면 inf (창 안에서 안 일어난 일)
        i10 = np.flatnonzero(travel >= TR_LO)
        i90 = np.flatnonzero(travel >= TR_HI)
        if i90.size:
            k10 = int(i10[0]) if i10.size else 0
            keep("tr", float(seg_t[int(i90[0])] - seg_t[k10]))
        else:
            keep("tr", math.inf)

        # Ts — 밴드(스텝 크기의 ±2 %) 밖 마지막 시각. 끝까지 밖이면 inf
        out = np.abs(err) > SETTLE_BAND_FRAC * h
        if not out.any():
            keep("ts", 0.0)
        elif bool(out[-1]):
            keep("ts", math.inf)
        else:
            keep("ts", float(seg_t[int(np.flatnonzero(out)[-1])]))

        # Mp — 목표 초과분(스텝 방향)의 최대 / 스텝 크기 = max(0, travel − 1)
        keep("mp", float(np.maximum(0.0, travel - 1.0).max()))

        # sse — 창 꼬리 평균 잔차 (절대 단위)
        tail = max(1, int(round(SSE_TAIL_FRAC * (k1 - k0))))
        keep("sse", float(np.mean(np.abs(err[-tail:]))))
    return worst


def _authority_metrics(signals, meta) -> dict:
    """비행 중 잔여 권한 — min(배분 한계)/엘레본 예산 (A⑦, 커밋 0e56bcf 배분 신호).

    배분 미장착 형상(신호 없음)·예산 미상이면 None — "권한을 다 썼다(0)"와
    "계측이 없다"는 다른 사실이다.
    """
    hi = ((meta or {}).get("limits") or {}).get("elevon_hi")
    out = {}
    for key, sig_name in (("min_pitch_authority_frac", "alloc_pitch_hi"),
                          ("min_roll_authority_frac", "alloc_roll_hi")):
        a = _arr(signals, sig_name)
        if a is None or hi is None or not float(hi) > 0.0:
            out[key] = None
            continue
        f = a[np.isfinite(a)]
        out[key] = None if f.size == 0 else float(f.min() / float(hi))
    return out


def _sat_longest(signals, meta, t) -> float | None:
    """타면 위치 포화의 최장 연속 시간 [s] — 채널 최악 (B급 포화 지속).

    surf_sat_frac(시간비)과 다른 질문이다: 짧게 여러 번(리밋사이클 징후)과 길게
    한 번(조종권 부족)은 비율이 같아도 다른 사고다. 한계 미상이면 None.
    """
    limits = dict((meta or {}).get("limits") or {})
    try:
        surfaces = surface_positions(signals)
    except KeyError:
        return None
    t_a = np.asarray(t, dtype=float)
    dt = float((meta or {}).get("dt_plant") or
               (t_a[1] - t_a[0] if t_a.size > 1 else 0.0))
    if dt <= 0.0:
        return None
    longest = None
    for key, _label, prefix in CHANNELS:
        lo, hi = _limits_for(limits, prefix)
        s = saturation(surfaces[key], dt, lo, hi)
        if s is None:
            continue
        longest = s["longest"] if longest is None else max(longest, s["longest"])
    return longest


def metric_values(t, signals, envelope, meta, waypoints=None) -> dict:
    """설계 지표 전부 — 키 집합은 METRICS 선언과 일치한다 (test_metrics 핀).

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

    # 축별 스텝 응답 특성 (A⑤ Ts·Mp + B급 Tr·sse) — 접두사 = 추종 RMS와 동일 축
    steps = {}
    for axis, cmd_key, y_key, on_key, ang in (
        ("alt", "cmd_alt", "h", "alt_on", False),
        ("spd", "cmd_speed", "V", "speed_on", False),
        ("hdg", "cmd_heading", "psi", "heading_on", True),
    ):
        sm = step_metrics(t, signals.get(cmd_key), signals.get(y_key),
                          signals.get(on_key), angular=ang)
        for name, v in sm.items():
            steps[f"{axis}_{name}"] = v

    out = {
        "worst_stall_margin": None if worst is None else float(worst),
        "envelope_flags": None if any_arr is None else int(any_arr.sum()),
        "alt_rms": _tracking_rms(signals, "cmd_alt", "h", "alt_on"),
        "spd_rms": _tracking_rms(signals, "cmd_speed", "V", "speed_on"),
        "hdg_rms": _tracking_rms(signals, "cmd_heading", "psi", "heading_on",
                                 angular=True),
        **steps,
        "surf_sat_frac": _surf_sat_frac(signals, meta),
        "sat_longest": _sat_longest(signals, meta, t),
        "limiter_frac": (
            None if la is None else float(np.mean(np.asarray(la, dtype=bool)))
        ),
        **_authority_metrics(signals, meta),
        "xtrack_rms": _xtrack_rms(signals, waypoints),
        **_landing_metrics(t, signals, meta),
    }
    assert set(out) == {m.key for m in METRICS}, "METRICS 선언·계산 드리프트"
    return out
