"""게인 surface 적합 — 차수 에스컬레이션 + greedy knot로 최소 표현을 찾는다.

"모든 최적 게인을 breakpoint로 넣지 않는다"의 구현: 튜닝 샘플(tune.tune_points)을
보고 ① 실질 변동이 없는 축은 탈락시키고(select_axes — SCHED_VARS 부분집합 규약),
② 남은 축에서 1→2→3→4차 순으로 **허용치를 만족하는 최저 차수**를 찾고, ③ 그래도
안 되면 최대 잔차 위치에 knot를 넣어 구간을 나눈다 (max_segments 상한). 산출물은
PolyTable(tables/poly.py) — 다항 런타임 채택(사용자 확정)에 따라 설계 표현이 곧
런타임 표현이다.

- 적합은 web polyfit.js와 같은 센터·스케일 u-영역 (계수 왕복 호환) — 풀이만
  정규방정식 대신 lstsq (수치 우위, 결과 동일 차원).
- 경계 C0는 **구성적으로 강제**: 왼쪽 구간을 먼저 적합하고 오른쪽 구간은 경계값
  일치 제약 최소제곱으로 푼다 — 게인 불연속(채터링 원인)을 적합 단계에서 봉쇄.
  기울기 점프는 joints로 정량 보고 (max_adjacent_jump 원칙 — 판정은 호출자).
- 다축 변동: v1 다항 런타임은 1D 한정 [백로그] — 2축 이상 변동이면 지배 축으로
  적합하고 나머지 축 기여를 cross_axis_residual로 정직하게 보고한다.
- resample_to_table: 다항 → 선형 보간 허용치 내 최소 breakpoint Table — 기존
  claw_lookup1d 경로와의 호환 반출 (비교·백업용 보조 경로).
"""

import numpy as np

from claw.design.points import AXES
from claw.tables import PolyTable, Table


def _centered(xs):
    x0, x1 = float(np.min(xs)), float(np.max(xs))
    c = 0.5 * (x0 + x1)
    h = 0.5 * (x1 - x0) or 1.0
    return c, h


def _polyfit_free(xs, ys, degree):
    """비제약 최소제곱 — u-영역 오름차수 계수 (polyfit.js polyfit과 같은 정의)."""
    d = max(1, min(degree, len(xs) - 1))
    c, h = _centered(xs)
    u = (np.asarray(xs, dtype=float) - c) / h
    M = np.vander(u, d + 1, increasing=True)
    coeffs, *_ = np.linalg.lstsq(M, np.asarray(ys, dtype=float), rcond=None)
    return {"coeffs": tuple(float(v) for v in coeffs), "c": c, "h": h, "degree": d}


def _polyfit_pinned(xs, ys, degree, x_pin, v_pin):
    """경계값 제약 최소제곱 — p(x_pin) = v_pin 강제 (C0 구성 보장).

    a0를 제약으로 소거: p(u) = v_pin + Σ_{k≥1} a_k (u^k − u_pin^k).
    """
    d = max(1, min(degree, len(xs)))
    c, h = _centered(list(xs) + [x_pin])
    u = (np.asarray(xs, dtype=float) - c) / h
    u_pin = (float(x_pin) - c) / h
    M = np.column_stack([u**k - u_pin**k for k in range(1, d + 1)])
    rhs = np.asarray(ys, dtype=float) - v_pin
    ak, *_ = np.linalg.lstsq(M, rhs, rcond=None)
    a0 = float(v_pin - sum(a * u_pin**k for k, a in enumerate(ak, start=1)))
    return {"coeffs": (a0, *(float(a) for a in ak)), "c": c, "h": h, "degree": d}


def _eval(fit, x):
    u = (np.asarray(x, dtype=float) - fit["c"]) / fit["h"]
    v = np.zeros_like(u, dtype=float)
    for a in reversed(fit["coeffs"]):
        v = v * u + a
    return v


def _fit_segment(xs, ys, scale, tol_fit, max_degree, pin=None):
    """차수 에스컬레이션 — 허용치 만족 최저 차수, 못 맞추면 max_degree 최선."""
    best = None
    for d in range(1, max_degree + 1):
        fit = (_polyfit_free(xs, ys, d) if pin is None
               else _polyfit_pinned(xs, ys, d, *pin))
        resid = float(np.max(np.abs(np.asarray(ys) - _eval(fit, xs)))) if len(xs) else 0.0
        best = (fit, resid)
        if resid <= tol_fit * scale:
            break
    return best


def fit_gain_surface(xs, ys, *, tol_fit=0.02, max_degree=4, max_segments=4) -> dict:
    """1D 게인 surface → 구간별 다항 — {"segments", "max_residual", "rms", "scale", "joints"}.

    greedy: 전 구간 한 판 적합 → 잔차 초과 구간 중 최악을 그 구간의 최대 잔차
    격자점에서 분할 → 재적합(왼쪽부터 C0 제약 연쇄). max_segments 도달 시 최선 보고.
    """
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    order = np.argsort(xs, kind="stable")
    xs, ys = xs[order], ys[order]
    if len(xs) < 2:
        raise ValueError("적합에는 서로 다른 격자점 2개 이상 필요")
    scale = float(np.max(np.abs(ys))) or 1.0

    # 경계는 격자점 인덱스로 관리 — [시작, ..., 끝] (edges[i] ≤ 구간 i < edges[i+1])
    edges = [0, len(xs) - 1]

    def _refit():
        segs, resids = [], []
        pin = None
        for i in range(len(edges) - 1):
            lo, hi = edges[i], edges[i + 1]
            sl = slice(lo, hi + 1)
            fit, resid = _fit_segment(xs[sl], ys[sl], scale, tol_fit, max_degree, pin=pin)
            x1 = float(xs[hi])
            segs.append({"x0": float(xs[lo]), "x1": x1, **fit})
            resids.append((resid, i, lo, hi))
            pin = (x1, float(_eval(fit, x1)))  # 다음 구간 C0 제약
        return segs, resids

    segs, resids = _refit()
    while len(segs) < max_segments:
        # 잔차 큰 구간부터 쪼갤 자리를 찾는다. **못 쪼개는 구간에서 멈추지 않는다** —
        # 격자점 2개짜리 구간(pin 제약으로 흔하다)이 잔차 1위면, 종전 코드는 아직
        # 쪼갤 수 있는 다른 구간을 남겨 둔 채 루프 전체를 끝냈다(허용치의 1만 배로
        # 끝나는 경우가 실측됐다). max_segments를 다 쓰거나 후보가 마를 때까지 간다
        split = None
        for resid, _i, lo, hi in sorted(resids, key=lambda r: -r[0]):
            if resid <= tol_fit * scale:
                break  # 남은 구간은 전부 허용치 이내 — 더 쪼갤 이유가 없다
            fit = next(s for s in segs if s["x0"] == float(xs[lo]))
            local = np.abs(ys[lo:hi + 1] - _eval(fit, xs[lo:hi + 1]))
            cand = min(max(lo + int(np.argmax(local)), lo + 1), hi - 1)
            if cand not in edges:  # 양쪽 구간에 격자점이 남는 자리
                split = cand
                break
        if split is None:
            break
        edges = sorted(edges + [split])
        segs, resids = _refit()

    all_resid = np.concatenate([
        np.abs(ys[e0:e1 + 1] - _eval(s, xs[e0:e1 + 1]))
        for s, (e0, e1) in zip(segs, zip(edges, edges[1:]))
    ])
    joints = []
    for i in range(1, len(segs)):
        b = segs[i]["x0"]
        left = PolyTable("x", [segs[i - 1]])
        right = PolyTable("x", [segs[i]])
        joints.append({
            "x": b,
            "value_jump": float(right.interp(x=b) - left.interp(x=b)),
            "slope_jump": float(right.slope(b) - left.slope(b)),
        })
    return {
        "segments": segs,
        "max_residual": float(np.max(all_resid)),
        "rms": float(np.sqrt(np.mean(all_resid**2))),
        "scale": scale,
        "joints": joints,
        "tol_fit": float(tol_fit),
        "n_segments": len(segs),
        "max_degree_used": max(s["degree"] for s in segs),
    }


def _axis_spreads(samples: dict, points) -> dict:
    """축별 실질 변동 — 다른 축 고정 그룹 내 값 범위의 최대."""
    names = [n for n in samples if n in points]
    out = {}
    for axis_i, axis in enumerate(AXES):
        groups: dict = {}
        for n in names:
            c = points.get(n).coords()
            groups.setdefault(c[:axis_i] + c[axis_i + 1:], []).append(samples[n])
        out[axis] = max(
            (max(v) - min(v) for v in groups.values() if len(v) > 1), default=0.0
        )
    return out


def select_axes(samples: dict, points, *, flat_tol=0.02) -> tuple:
    """실질 변동 축 선택 — 다른 축 고정 그룹 내 값 범위가 flat_tol×scale 초과인 축만.

    samples: {케이스 이름: 게인 값}. 반환은 AXES 순서의 부분집합 (SCHED_VARS 규약).
    """
    names = [n for n in samples if n in points]
    scale = max((abs(samples[n]) for n in names), default=0.0) or 1.0
    spreads = _axis_spreads(samples, points)
    return tuple(axis for axis in AXES if spreads[axis] > flat_tol * scale)


def fit_slot(slot: str, samples: dict, points, *, flat_tol=0.02, tol_fit=0.02,
             max_degree=4, max_segments=4) -> dict:
    """자리 하나의 스케줄 표현 결정 — {"kind": "constant"|"poly", ...}.

    - 변동 축 없음 → 상수 (평균값 — 잔차를 report에 남긴다)
    - 1축 → PolyTable (다항 런타임)
    - 2축 이상 → v1 다항 런타임 1D 한정 [백로그]: 지배 축(변동 최대)으로 적합하고
      나머지 축 기여를 cross_axis_residual로 보고 — 조용히 뭉개지 않는다
    """
    names = [n for n in samples if n in points]
    vals = np.array([samples[n] for n in names], dtype=float)
    axes = select_axes(samples, points, flat_tol=flat_tol)
    if not axes:
        mean = float(np.mean(vals)) if len(vals) else 0.0
        resid = float(np.max(np.abs(vals - mean))) if len(vals) else 0.0
        return {"kind": "constant", "slot": slot, "value": mean, "max_residual": resid}

    # 지배 축: 축별 그룹 내 스프레드 최대 (1축이면 그 축)
    spreads = _axis_spreads(samples, points)
    axis = axes[0] if len(axes) == 1 else max(axes, key=lambda a: spreads[a])
    axis_i = AXES.index(axis)
    xs = np.array([points.get(n).coords()[axis_i] for n in names], dtype=float)

    # 같은 축값의 중복 샘플(다른 행)은 평균으로 접는다 — lstsq에 그대로 줘도 되지만
    # PolyTable knot가 격자점과 1:1이 되도록 대표값을 만든다
    uniq = {}
    for x, v in zip(xs, vals):
        uniq.setdefault(float(x), []).append(float(v))
    xs_u = np.array(sorted(uniq))
    ys_u = np.array([np.mean(uniq[x]) for x in xs_u])
    cross = float(max((max(v) - min(v) for v in uniq.values()), default=0.0))

    surface = fit_gain_surface(
        xs_u, ys_u, tol_fit=tol_fit, max_degree=max_degree, max_segments=max_segments
    )
    poly = PolyTable(axis, surface["segments"], name=slot)
    report = {k: v for k, v in surface.items() if k != "_poly"}
    report.update({
        "kind": "poly", "slot": slot, "axes_detected": axes, "axis": axis,
        "cross_axis_residual": cross,
    })
    return {"kind": "poly", "slot": slot, "table": poly, "report": report}


def fit_slots(gain_samples: dict, points, *, flat_tol=0.02, tol_fit=0.02,
              max_degree=4, max_segments=4) -> dict:
    """전 자리 적합 — {"tables": {자리: PolyTable}, "constants": {자리: 값}, "reports"}."""
    tables, constants, reports = {}, {}, {}
    for slot, samples in gain_samples.items():
        out = fit_slot(
            slot, samples, points, flat_tol=flat_tol, tol_fit=tol_fit,
            max_degree=max_degree, max_segments=max_segments,
        )
        if out["kind"] == "constant":
            constants[slot] = out["value"]
            reports[slot] = out
        else:
            tables[slot] = out["table"]
            reports[slot] = out["report"]
    return {"tables": tables, "constants": constants, "reports": reports}


def resample_to_table(poly: PolyTable, *, tol_interp=0.01, max_pts=65) -> Table:
    """다항 → 선형 보간 오차 허용치 내 최소 breakpoint Table (호환 반출 보조 경로).

    구간마다 재귀 이분: 현 [a,b]의 중점에서 |다항 − 현(chord)| > tol_interp×scale
    이면 분할. knot ∪ 세분점이 최종 격자다.
    """
    axis = poly.axis_names[0]
    scale = float(np.max(np.abs([
        poly.interp(**{axis: x})
        for x in np.linspace(poly.knots[0], poly.knots[-1], 101)
    ]))) or 1.0

    pts = set(float(k) for k in poly.knots)

    def _refine(a, b, depth):
        if len(pts) >= max_pts or depth > 12:
            return
        m = 0.5 * (a + b)
        pa, pb, pm = (poly.interp(**{axis: v}) for v in (a, b, m))
        if abs(pm - 0.5 * (pa + pb)) > tol_interp * scale:
            pts.add(m)
            _refine(a, m, depth + 1)
            _refine(m, b, depth + 1)

    for s in poly.segments:
        _refine(s["x0"], s["x1"], 0)
    xs = np.array(sorted(pts))
    data = np.array([poly.interp(**{axis: x}) for x in xs])
    return Table({axis: xs}, data, name=poly.name, extrapolate="clip")
