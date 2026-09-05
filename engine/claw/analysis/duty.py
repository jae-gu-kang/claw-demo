"""타면 사용 통계 (duty) — 타각 범위별 체류 시간·포화·타율 (01 §2.4 작동기 사양 검증).

시계열은 "언제 무슨 일이 있었나"를 말하지만 "**어느 타각에 얼마나 오래 머물렀나**"는
말하지 않는다. 작동기 사이징·힌지모멘트 듀티·리밋사이클 판정은 후자의 언어로
쓰인다 — 이 모듈은 폐루프 런 하나를 그 언어로 옮긴다.

**모든 통계는 시간 가중이다.** 플랜트 적분 주기 dt가 고정이므로 표본 개수×dt가
곧 체류 시간이고, "빈도"와 "시간"이 같은 양의 두 표기가 된다 (frac = time/t_total).

## 채널 = 물리 타면 (축 명령이 아니라)

위치 한계·rate 한계에 실제로 부딪히는 대상은 엘레본 좌/우와 러더다. 축 명령
δe/δa는 믹싱 전 가상량이라 포화를 판정할 기준선이 없다. 좌우를 나눠야 지속
선회·트림 편향이 **비대칭**으로 드러난다 (합쳐 놓으면 상쇄되어 안 보인다).

## 새 계측이 필요 없는 이유 (복원 항등)

믹서가 내/외측 1:1 고정 믹싱이라 `elevon = [좌, 좌, 우, 우]`이고(fcl/mixer.py),
시뮬이 로깅하는 de·da가 정확히 그 평균·차동이다(sim/simulator.py):

    de = (좌 + 우) / 2,  da = (좌 − 우) / 2   →   좌 = de + da,  우 = de − da

작동기 장착 시에도 4기가 동일 파라미터·동일 입력이라 좌 쌍·우 쌍이 각각 같은
값이므로 항등이 그대로 성립한다. **믹싱 비율이 1:1을 벗어나면 이 복원이 조용히
거짓말을 하므로** test_duty.py가 Mixer와 직접 대조하는 드리프트 가드를 둔다.

타율(δ̇)도 마찬가지다. 작동기가 스텝당 위치 변화를 ±rate_max·dt로 직접
클램프하므로(plant/actuator.py) 로그된 위치의 차분이 곧 **실현된 rate**이고
rate_max에 정확히 물린다 — 내부 속도 상태보다 오히려 듀티 판정에 맞는 양이다.

## 작동기 미장착일 때

명령이 직결되어 제어주기 ZOH가 된다. 그대로 차분하면 임펄스 열이 나오므로
제어주기만큼 솎아(decimate) dt_ctrl 기준으로 계산하고, 그 결과는 실현된 타율이
아니라 **요구 slew**임을 플래그로 알린다 (rate_is_command_slew).

단위는 내부 규약대로 rad·rad/s (03 §3). deg 변환은 표시 계층 소관.
"""

import numpy as np

# 채널 정의 — (키, 표시 이름, meta["limits"]의 한계 키 접두)
CHANNELS = (
    ("elevon_l", "엘레본(좌)", "elevon"),
    ("elevon_r", "엘레본(우)", "elevon"),
    ("rudder", "러더", "rudder"),
)

# 포화 판정 허용오차. 작동기는 한계에 **정확히** 클램프하므로(등호 경계) 오차는
# 부동소수 왕복분만 있으면 된다 — 넓게 잡으면 "거의 다 썼다"가 "포화"로 둔갑한다.
POS_TOL = 1e-6  # rad
RATE_TOL = 1e-9  # rad/s
# 반전 판정 불감대 [기준 rate 대비] — 정지 근처 수치 잡음이 반전으로 세어지는 것을 막는다.
# 반전 횟수는 이 값에 민감하므로 결과에 함께 실어 보낸다 (해석 가능하게).
REVERSAL_DEADBAND_FRAC = 0.02


def surface_positions(signals) -> dict:
    """시뮬 신호 → 물리 타면 위치 {elevon_l, elevon_r, rudder} [rad].

    복원 항등은 모듈 docstring 참조 — 믹서 1:1 고정 믹싱 전제이며 test_duty.py가
    Mixer와 직접 대조해 가드한다. JSON 왕복(NaN→null)을 견디도록 float 캐스트.
    """
    missing = [k for k in ("de", "da", "dr") if k not in signals]
    if missing:
        raise KeyError(f"타면 복원에 필요한 신호 없음: {missing} (de·da·dr 필요)")
    de = np.asarray(signals["de"], dtype=float)
    da = np.asarray(signals["da"], dtype=float)
    dr = np.asarray(signals["dr"], dtype=float)
    return {"elevon_l": de + da, "elevon_r": de - da, "rudder": dr}


def zoh_decimate(meta, dt) -> tuple:
    """타율 차분의 솎음 폭 — (decimate, 경고문 | None). duty_report·평가 공용.

    작동기 미장착이면 명령 직결 ZOH라 제어주기만큼 솎아야 차분이 임펄스 열이 되지
    않는다(그때 타율은 실현값이 아니라 요구 slew이고 rate 한계도 없다 — 경고문이
    그 사실을 든다). 이 판정이 두 곳에 복사되면 ZOH 미묘함이 따로 낡는다.
    """
    if bool((meta or {}).get("actuators")):
        return 1, None
    decimate = 1
    control_hz = float((meta or {}).get("control_hz") or 0.0)
    if control_hz > 0 and dt > 0:
        decimate = max(1, int(round(1.0 / (control_hz * dt))))
    return decimate, (
        "작동기 미장착 — 명령이 직결되어 타율은 실현값이 아니라 요구 slew이고, "
        "rate 한계가 없어 타율 포화는 판정하지 않는다."
    )


def rate_series(x, dt, decimate: int = 1):
    """(위치 정렬본, 타율) — decimate만큼 솎아 dt·decimate 기준 차분.

    반환 위치는 두 표본의 **중점**이다: 그 구간을 지나는 동안의 평균 타율이므로
    한쪽 끝에 붙이면 밀도 그림이 반 칸 밀린다. 표본 하나가 대표하는 시간은 dt가
    아니라 dt·decimate — 시간 가중 통계는 그 값을 써야 한다 (duty_report가 전달).
    """
    if decimate < 1:
        raise ValueError(f"decimate는 1 이상: {decimate}")
    xs = np.asarray(x, dtype=float)[::decimate]
    if xs.size < 2:
        empty = np.zeros(0)
        return empty, empty
    return 0.5 * (xs[:-1] + xs[1:]), np.diff(xs) / (dt * decimate)


def time_histogram(x, edges, dt) -> dict:
    """타각 → 빈별 체류 시간 [s]. 개수×dt (dt 고정이라 정확).

    범위 밖 표본은 버리지 않고 양끝 빈으로 clip하고 그 시간을 out_of_range에
    따로 적는다 — 버리면 시간 합이 총 시간과 어긋나 "빠진 시간"이 조용히 생기고,
    말없이 clip하면 한계 밖 표본이 정상 표본으로 위장된다.
    """
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    edges = np.asarray(edges, dtype=float)
    lo, hi = float(edges[0]), float(edges[-1])
    n_out = int(np.count_nonzero((a < lo) | (a > hi)))
    counts, _ = np.histogram(np.clip(a, lo, hi), bins=edges)
    time = counts * dt
    total = float(time.sum())
    return {
        "edges": edges,
        "time": time,
        "frac": time / total if total > 0 else np.zeros_like(time),
        "out_of_range": n_out * dt,
    }


def exceedance(x, dt, n_levels: int = 64) -> dict:
    """누적 초과 — |δ| ≥ level인 시간 [s] (단조감소) + 백분위.

    "95% 구간이 어디였나"에 직접 답하는 표현. |δ|로 세는 이유는 하방 타각도
    작동기에는 같은 일이기 때문 — 부호로 나누면 반쪽이 0으로 보인다.
    정렬 후 searchsorted라 레벨 수와 무관하게 정확하다 (레벨마다 다시 세면 O(n·levels)).
    """
    a = np.abs(np.asarray(x, dtype=float))
    a = a[np.isfinite(a)]
    if a.size == 0:
        z = np.zeros(int(n_levels))
        return {"level": z, "time": z, "p50": None, "p95": None, "p99": None}
    s = np.sort(a)
    hi = float(s[-1])
    levels = np.linspace(0.0, hi if hi > 0 else 1e-9, int(n_levels))
    time = (a.size - np.searchsorted(s, levels, side="left")) * dt
    p50, p95, p99 = (float(v) for v in np.percentile(a, [50.0, 95.0, 99.0]))
    return {"level": levels, "time": time, "p50": p50, "p95": p95, "p99": p99}


def density2d(x, xdot, x_edges, y_edges, dt_rate) -> dict:
    """(타각, 타율) 셀별 체류 시간 [s] — 산점도가 아니라 격자인 이유:

    ① 시간 가중이 히스토그램·초과곡선과 같은 단위로 읽힌다 ② 크기가 표본 수와
    무관하게 유계다 ③ 다운샘플이 극값을 몰래 버리지 않는다 (빈 셀과 찬 셀은 정확).
    셀 값의 합 = 총 시간이므로 겹쳐 찍힌 점 뒤에 숨는 밀도가 그대로 드러난다.
    """
    a = np.asarray(x, dtype=float)
    b = np.asarray(xdot, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    x_edges = np.asarray(x_edges, dtype=float)
    y_edges = np.asarray(y_edges, dtype=float)
    counts, _, _ = np.histogram2d(
        np.clip(a[ok], x_edges[0], x_edges[-1]),
        np.clip(b[ok], y_edges[0], y_edges[-1]),
        bins=[x_edges, y_edges],
    )
    return {"x_edges": x_edges, "y_edges": y_edges, "time": counts * dt_rate}


def run_stats(mask, dt, times=None) -> dict:
    """불리언 마스크 → 체류 시간·비율·구간 수·최장 구간·최초 시각.

    구간 수는 "한계에 몇 번 부딪혔나", 최장 구간은 "얼마나 오래 붙어 있었나" —
    다른 질문이라 둘 다 센다 (짧게 여러 번 = 리밋사이클 징후, 길게 한 번 =
    조종권 부족). 처음부터 물려 있으면 상승엣지가 없지만 1회로 센다.
    """
    m = np.asarray(mask, dtype=bool)
    n = int(m.sum())
    out = {
        "time": n * dt,
        "frac": (n / m.size) if m.size else 0.0,
        "events": 0,
        "longest": 0.0,
        "first_t": None,
        "total_time": float(m.size * dt),
    }
    if n == 0:
        return out
    # 0으로 감싸 상승/하강 경계를 만든 뒤 구간 길이를 잰다 (양끝 구간도 놓치지 않게)
    d = np.diff(np.concatenate(([0], m.astype(np.int8), [0])))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    out["events"] = int(starts.size)
    out["longest"] = float((ends - starts).max() * dt)
    i0 = int(np.argmax(m))
    out["first_t"] = float(times[i0]) if times is not None else float(i0 * dt)
    return out


def saturation(x, dt, lo, hi, times=None, tol: float = POS_TOL):
    """위치 포화 집계 — 한계가 미상(None)이면 0이 아니라 None.

    "한계에 0초 붙어 있었다"와 "한계를 몰라 판정할 수 없다"는 다른 사실이다.
    """
    if lo is None and hi is None:
        return None
    a = np.asarray(x, dtype=float)
    m = np.zeros(a.shape, dtype=bool)
    if hi is not None:
        m |= a >= hi - tol
    if lo is not None:
        m |= a <= lo + tol
    return run_stats(m, dt, times)


def rate_saturation(xdot, dt_rate, rate_max, times=None, tol: float = RATE_TOL):
    """타율 포화 집계 — rate_max 미상(작동기 미장착 등)이면 None."""
    if rate_max is None:
        return None
    a = np.abs(np.asarray(xdot, dtype=float))
    return run_stats(a >= rate_max - tol, dt_rate, times)


def reversals(xdot, dt_rate, deadband) -> dict:
    """타율 방향 반전 횟수·분당 반전율 — 리밋사이클 탐지선.

    불감대 아래 표본은 세지 않는다 (정지 근처 잡음이 반전으로 둔갑). 횟수가
    불감대에 민감하므로 쓴 값을 함께 돌려준다 — 숫자만으로는 해석이 안 된다.
    """
    a = np.asarray(xdot, dtype=float)
    a = a[np.isfinite(a) & (np.abs(a) > deadband)]
    n = int(np.count_nonzero(np.diff(np.sign(a)) != 0)) if a.size >= 2 else 0
    minutes = (np.asarray(xdot).size * dt_rate) / 60.0
    return {
        "count": n,
        "per_min": (n / minutes) if minutes > 0 else 0.0,
        "deadband": float(deadband),
    }


def _limits_for(limits, prefix):
    lo = limits.get(f"{prefix}_lo")
    hi = limits.get(f"{prefix}_hi")
    return (None if lo is None else float(lo), None if hi is None else float(hi))


def _pos_edges(x, lo, hi, bins):
    """히스토그램 경계 — 한계를 알면 **한계 전 구간**으로 잡는다.

    데이터 범위로만 잡으면 어떤 런이든 양끝이 차 보여 "조종권을 얼마나 남겼나"가
    사라진다. 쓰지 않은 구간이 빈 채로 보여야 여유가 읽힌다.
    """
    if lo is not None and hi is not None and hi > lo:
        return np.linspace(lo, hi, int(bins) + 1)
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return np.linspace(-1e-3, 1e-3, int(bins) + 1)
    x0, x1 = float(a.min()), float(a.max())
    pad = 0.05 * (x1 - x0) if x1 > x0 else 1e-3
    return np.linspace(x0 - pad, x1 + pad, int(bins) + 1)


def _scalar_stats(x, dt, times=None) -> dict:
    """평균·표준편차·최소/최대·최대 |값|과 그 시각. 전부 비유한이면 None들."""
    a = np.asarray(x, dtype=float)
    ok = np.isfinite(a)
    if not ok.any():
        return dict.fromkeys(("mean", "std", "min", "max", "max_abs", "max_abs_t"))
    f = a[ok]
    i = int(np.argmax(np.where(ok, np.abs(a), -np.inf)))
    return {
        "mean": float(f.mean()),
        "std": float(f.std()),
        "min": float(f.min()),
        "max": float(f.max()),
        "max_abs": float(abs(a[i])),
        "max_abs_t": float(times[i]) if times is not None else float(i * dt),
    }


def _usage(max_abs, lo, hi):
    """조종권 사용률 = 최대 |타각| / 한계 크기 — 여유의 단일 요약 (미상이면 None)."""
    span = max(abs(lo) if lo is not None else 0.0, abs(hi) if hi is not None else 0.0)
    if max_abs is None or span <= 0.0:
        return None
    return float(max_abs / span)


def duty_report(t, signals, meta, bins: int = 32, rate_bins: int = 24,
                n_levels: int = 64) -> dict:
    """폐루프 런 하나 → 타면 사용 통계 일습 (채널×전체 + 채널×모드).

    t·signals·meta는 SimResult의 것 그대로 (JSON 왕복본도 허용 — 리스트·null 수용).
    **전 해상도 입력을 전제**한다: stride 다운샘플본으로 계산하면 최대 타율과 짧은
    포화 구간이 통째로 사라져 조용히 낙관적인 수치가 나온다. 그래서 소비자(웹)가
    아니라 저장된 원본을 쥔 쪽(서버)에서 부른다.
    """
    t = np.asarray(t, dtype=float)
    dt = float(meta.get("dt_plant") or (t[1] - t[0] if t.size > 1 else 1.0))
    limits = dict(meta.get("limits") or {})
    has_act = bool(meta.get("actuators"))
    warnings = []

    # 작동기 미장착 = 명령 직결 ZOH — 판정은 zoh_decimate 한 곳 (평가와 공용)
    decimate, zoh_warning = zoh_decimate(meta, dt)
    if zoh_warning:
        warnings.append(zoh_warning)
    dt_rate = dt * decimate
    td = t[::decimate]
    t_rate = 0.5 * (td[:-1] + td[1:]) if td.size > 1 else td[:0]

    surfaces = surface_positions(signals)
    modes = list(signals.get("mode") or [])
    mode_names = list(dict.fromkeys(modes))  # 등장 순서 유지
    rate_max = limits.get("rate_max")
    rate_max = None if rate_max is None else float(rate_max)

    channels = []
    for key, label, prefix in CHANNELS:
        x = surfaces[key]
        lo, hi = _limits_for(limits, prefix)
        xmid, xdot = rate_series(x, dt, decimate)
        edges = _pos_edges(x, lo, hi, bins)
        # 타율 축은 한계와 실제 요구 중 큰 쪽까지 — 한계를 넘는 요구가 능력 상자
        # 밖으로 삐져나와 보여야 한다 (한계로 잘라 그리면 초과가 사라진다)
        ymax = max(rate_max or 0.0, float(np.abs(xdot).max()) if xdot.size else 0.0)
        y_edges = (np.linspace(-1.05 * ymax, 1.05 * ymax, int(rate_bins) + 1)
                   if ymax > 0 else np.linspace(-1e-3, 1e-3, int(rate_bins) + 1))
        deadband = REVERSAL_DEADBAND_FRAC * (rate_max or ymax or 1.0)

        stats = _scalar_stats(x, dt, t)
        rate_stats = _scalar_stats(xdot, dt_rate, t_rate)
        chan = {
            "key": key,
            "label": label,
            "unit": "rad",
            "pos_lo": lo,
            "pos_hi": hi,
            "rate_max": rate_max,
            "hist": time_histogram(x, edges, dt),
            "exceedance": exceedance(x, dt, n_levels),
            "density": density2d(xmid, xdot, edges, y_edges, dt_rate),
            "stats": {
                **stats,
                "max_rate_abs": rate_stats["max_abs"],
                "max_rate_abs_t": rate_stats["max_abs_t"],
                "usage": _usage(stats["max_abs"], lo, hi),
            },
            "reversals": reversals(xdot, dt_rate, deadband),
            "pos_sat": saturation(x, dt, lo, hi, t),
            "rate_sat": rate_saturation(xdot, dt_rate, rate_max, t_rate),
            "by_mode": {},
        }
        for name in mode_names:
            m = np.fromiter((mm == name for mm in modes), dtype=bool, count=len(modes))
            # 타율 계열은 솎임+중점이라 위치 마스크를 그대로 못 쓴다 —
            # 각 차분 구간을 왼쪽 표본의 모드로 사상한다 (구간 경계는 한 표본 오차)
            mr = m[::decimate][:xdot.size]
            chan["by_mode"][name] = {
                "time": float(m.sum() * dt),
                "hist": time_histogram(x[m], edges, dt),
                "stats": _scalar_stats(x[m], dt, t[m]),
                "pos_sat": saturation(x[m], dt, lo, hi, t[m]),
                "rate_sat": rate_saturation(xdot[:mr.size][mr], dt_rate, rate_max),
            }
        channels.append(chan)

    return {
        "dt": dt,
        "n": int(t.size),
        "t_total": float(t.size * dt),
        "actuators": has_act,
        "rate_dt": dt_rate,
        "rate_is_command_slew": not has_act,
        "limits": limits,
        "modes": mode_names,
        "mode_time": {n: float(sum(1 for m in modes if m == n) * dt) for n in mode_names},
        "bins": int(bins),
        "rate_bins": int(rate_bins),
        "warnings": warnings,
        "channels": channels,
    }
