"""게인 surface 적합 — 차수 에스컬레이션 + greedy knot로 최소 표현을 찾는다.

"모든 최적 게인을 breakpoint로 넣지 않는다"의 구현: 튜닝 샘플(tune.tune_points)을
보고 ① 실질 변동이 없는 축은 탈락시키고(select_axes — SCHED_VARS 부분집합 규약),
② 남은 축에서 1→2→3→4차 순으로 **허용치를 만족하는 최저 차수**를 찾고, ③ 그래도
안 되면 최대 잔차 위치에 knot를 넣어 구간을 나눈다 (max_segments 상한). 산출물은
PolyTable(tables/poly.py) — 다항 런타임 채택(사용자 확정)에 따라 설계 표현이 곧
런타임 표현이다.

**표현은 두 가지다 (mode)** — `fit_slots(..., mode=)`이 고르고, 자동 설계의 기본은
`AutoDesignConfig.fit_mode`가 정한다 (05 §5):
- `"poly"` — 위 절차. 매끄럽고 계수가 적지만 **급변을 뭉갠다**: 부호 보호
  (_fit_preserving_sign)가 어느 차수로도 부호를 못 지키면 그 자리를 상수로 굳혀
  스케줄 하나가 통째로 사라질 수 있다 (예제 기체 실측 — roll.k_rate).
- `"table"` — 선형 보간 Table. 분할점은 **표별 절점 집합**(knots.py — 05 §11.5)이 정하고 값은 설계점 표본 전부의
  최소제곱(구간 선형 기저 — table_on_knots)이다. 절점을 안 주면(knots None — 옛 규칙) 튜닝값을 **그대로 분할점에
  놓는다**: 튜닝한 마하마다 분할점이라 설계점을 늘리면 절점이 늘었다(쇼케이스 36점 — 이관 3단계가 뗀 결합). 표본이
  절점 위에만 있으면 두 규칙은 같은 표다. 대가는 **1축 붕괴의 톱니**다: 지배 축 하나로
  펴면서 다른 축(고도·연료) 샘플을 같은 축값에서 평균하므로, 축값마다 참여한 행이
  달라 값이 오르내린다 (예제 기체 실측 — pitch.k_rate 방향 반전 20회). 톱니는
  숨기지 않고 `joints`(분할점마다의 기울기 꺾임)·`zigzag`·`adjacent_jump_frac`으로
  보고하며, fit_quality가 다항과 **같은 자**로 재어 문턱 판정에 넣는다. 근본 해소는
  다축 표이고 격자를 사각으로 채우는 절차가 필요하다 [백로그 — 05 §9].

- 적합은 web polyfit.js와 같은 센터·스케일 u-영역 (계수 왕복 호환) — 풀이만
  정규방정식 대신 lstsq (수치 우위, 결과 동일 차원).
- 경계 C0는 **구성적으로 강제**: 왼쪽 구간을 먼저 적합하고 오른쪽 구간은 경계값
  일치 제약 최소제곱으로 푼다 — 게인 불연속(채터링 원인)을 적합 단계에서 봉쇄.
  기울기 점프는 joints로 정량 보고 (max_adjacent_jump 원칙 — 판정은 호출자).
- 다축 변동: v1 다항 런타임은 1D 한정 [백로그] — 2축 이상 변동이면 지배 축으로
  적합하고 나머지 축 기여를 cross_axis_residual로 정직하게 보고한다.
- 스케줄 축 제한(axes): 적합 축 후보를 호출자가 준 부분집합으로 좁힌다. 자동 설계는
  **마하만** 준다(AutoDesignConfig.sched_axes) — 산출 표가 가는 곳(기체 문서
  law.gain_tables·게인 탭)이 마하 1축 표만 받기 때문이다. 제한 밖 축의 변동은 버리지
  않고 보고에 남긴다(axes_excluded) — 그 변동이 마진을 깨는지는 VERIFY가 **반출될 그
  마하 표로** 판정한다(고도 표로 검증해 놓고 마하 표를 반출하면 검증받지 않은 형상이
  나간다). 제한은 표현(mode)과 직교한다 — 표 모드에서는 반출 표가 곧 검증한 표이고
  (orchestrator `reverify_resampled`가 동일 표로 인용), 제한 밖 축의 기여는 1축 붕괴의
  톱니·cross_axis_residual로 드러난다.
- resample_to_table: 다항 → 선형 보간 허용치 내 최소 breakpoint Table. **웹 「채택」·
  apply-gains가 실제로 주입하는 반출 표다** (routes/design.py `_gain_export` → 웹
  작업본·기체 문서 law.gain_tables) — 세션이 검증한 것은 다항이므로, 반출 표는
  `DesignSession.reverify_resampled`로 판정을 다시 받아 차이를 고지한다 (05 §5.1).
"""

import numpy as np

from claw.design.points import AXES
from claw.tables import PolyTable, Table

# 톱니(zigzag) 집계에서 무시할 변화 폭 — 그 자리 스케일 대비 비율. tol_fit 0.02의
# 1/4로, **적합 허용치 안의 잡음을 방향 반전으로 세지 않기** 위한 값이다 [기본값] —
# 실측 근거는 없고 톱니 수는 판정이 아니라 보고용 facts다 (판정은 joints → fit_quality)
_ZIGZAG_EPS_FRAC = 0.005


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

    tol_fit 0.02 [기본값]의 근거(정본 — fit_slot·fit_slots·AutoDesignConfig가 이 수를
    물려받는다): 잔차를 `scale = max|ys|`로 나눈 비율이라 "그 자리 게인 크기의 2%"다.
    웹 수동 적합(lib/polyfit.js)과 같은 관례값이고 **실측 근거는 없다** — 마진 민감도로
    확정하는 것은 폐쇄망 몫(04 §10). flat_tol(축 탈락, select_axes)도 같은 자의 비율이라
    같은 수를 쓴다.
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


def table_surface(xs, ys) -> dict:
    """1D 표 표현 — 튜닝값을 그대로 분할점에 놓는다 (적합 없음).

    보고 형상은 fit_gain_surface와 나란히 둔다(scale·joints·rms) — 소비자(fit_quality·
    원장·화면)가 표현 종류로 갈라지지 않게 하려는 것이다. 다만 뜻이 다른 곳이 둘 있다:
    - `joints`는 knot 관절이 아니라 **내부 분할점 전부**다. 선형 보간은 분할점마다
      기울기가 꺾이므로 관절 수가 곧 분할점 수 − 2다. 값은 구성적으로 연속이라
      value_jump는 0이다 (다항의 C0 강제와 같은 성질).
    - `max_residual`·`rms`는 0이 아니다 — 같은 축값에 놓인 다른 축(고도·연료) 샘플을
      평균해서 한 점으로 접기 때문이다. 이 값이 곧 **1축 붕괴의 대가**이고, 0으로
      위장하지 않는다 (호출자가 cross_axis_residual과 함께 보고한다).
    """
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    order = np.argsort(xs, kind="stable")
    xs, ys = xs[order], ys[order]
    if len(xs) < 2:
        raise ValueError("표에는 서로 다른 분할점 2개 이상 필요")
    scale = float(np.max(np.abs(ys))) or 1.0
    slopes = np.diff(ys) / np.diff(xs)
    joints = [{"x": float(xs[i]), "value_jump": 0.0,
               "slope_jump": float(slopes[i] - slopes[i - 1])}
              for i in range(1, len(slopes))]
    # 톱니 수 — 인접 분할점 간 변화의 부호가 뒤집힌 횟수. 스케일의 _ZIGZAG_EPS_FRAC
    # 미만인 변화는 방향을 논하지 않는다 (적합 허용치 tol_fit 0.02의 1/4 — 허용치
    # 안의 잡음을 방향 반전으로 세지 않기 위한 값이고 실측 근거는 없다 [기본값])
    d = np.diff(ys)
    big = d[np.abs(d) > _ZIGZAG_EPS_FRAC * scale]
    zigzag = int(np.sum(np.sign(big[1:]) != np.sign(big[:-1]))) if len(big) > 1 else 0
    return {
        "breakpoints": [float(x) for x in xs],
        "values": [float(y) for y in ys],
        "n_breakpoints": len(xs),
        "scale": scale,
        "joints": joints,
        "zigzag": zigzag,
        # 인접 분할점 간 최대 변화 비율 — fcl.schedule.max_adjacent_jump와 같은 양을
        # 그 자리 스케일로 무차원화한 것(기체 무관 규약). 룩업 표 자체의 거칠기다
        "adjacent_jump_frac": float(np.max(np.abs(d)) / scale) if len(d) else 0.0,
    }


def _hat_basis(xs, knots):
    """구간 선형(hat) 기저 행렬 A[j, i] = φ_i(x_j) — 끝 절점 밖 표본은 끝 절점으로 clip(탑재 형식의 끝단 처리와 같다)."""
    k = np.asarray(knots, dtype=float)
    x = np.clip(np.asarray(xs, dtype=float), k[0], k[-1])
    A = np.zeros((len(x), len(k)))
    j = np.clip(np.searchsorted(k, x, side="right") - 1, 0, len(k) - 2)
    t = (x - k[j]) / (k[j + 1] - k[j])
    rows = np.arange(len(x))
    A[rows, j] = 1.0 - t
    A[rows, j + 1] += t
    return A


# 절점 받침 문턱 — 표본 하나라도 기저 가중이 이 값 이상(절점에서 반 구간 안)이어야 그 절점 값을 정할 수 있다고 본다.
# 가중이 작은 표본만 닿으면 값이 v_이웃 + (y − v_이웃)/t로 1/t배 증폭된다(리뷰 실측: 가중 0.02에 1.763 → 31.2, 가운데
# 절점 2501). 0.5는 「그 절점이 가장 가까운 절점인 표본이 있다」와 같다 — 이웃과 사이 표본은 둘 중 하나에 0.5 이상이다.
# 실측 근거로 고른 값은 아니다 [기본값]
SUPPORT_MIN_WEIGHT = 0.5
_SUPPORT_EPS = 1e-9  # 중점 표본(가중 정확히 0.5)이 부동소수 오차로 떨어지지 않게
# 정칙화 가중치(무차원) — y를 자기 스케일로 나눈 뒤 쓴다. 종전에는 |y|에 비례해 게인 크기가 해를 바꿨다
_SMOOTH_W = 1e-6


def _support(xs, k) -> list:
    """절점별 받침 — [(최대 기저 가중, 기저 범위 안 표본 수)]. 끝 절점 바깥 표본은 끝 절점으로 clip돼 가중 1이다."""
    if len(xs) == 0:
        return [(0.0, 0)] * len(k)
    A = _hat_basis(xs, k)
    return [(float(np.max(A[:, i])), int(np.sum(A[:, i] > 0.0))) for i in range(len(k))]


def table_on_knots(xs, ys, knots) -> dict:
    """절점 위 1D 표 — 표본 전부의 최소제곱(구간 선형 기저)으로 절점 값을 정한다 (05 §11.5 — 설계점과 절점 분리).

    반환은 table_surface와 같은 보고 형상(breakpoints·values·n_breakpoints·scale·joints·zigzag·adjacent_jump_frac)에
    `unsupported_knots`(뺀 절점 좌표)·`unsupported_detail`([{knot, reason none|far, weight, text}])·`sample_residual`
    (표본 최대 잔차)·`rms`·`sign_guard`·`underdetermined`를 더한다.

    - **받쳐지지 않은 절점은 뺀다** — 기저 가중 SUPPORT_MIN_WEIGHT(0.5) 이상인 표본(절점에서 반 구간 안 — 끝 절점은 바깥
      clip 표본 포함)이 없으면 그 값은 먼 표본 하나에 1/가중배로 끌려 표본 범위를 한참 벗어난다. 지어내지 않고 그 표에서
      빼고 사유(표본 없음 none · 멀다 far)와 함께 보고한다 — 뺀 절점 너머는 남은 끝 절점 값으로 clip된다. 빼면 이웃 기저가
      넓어지므로 안정될 때까지 다시 잰다.
    - 표본이 절점 위에만 있으면 식이 절점마다 갈라져 해가 **절점별 평균**이다 — 종전 표 모드(같은 마하 평균)와 같다.
    - 식이 모자라면(가중 0.5 표본 하나가 이웃 두 절점을 함께 정하는 경우) 최소 노름 해는 게인을 0 쪽으로 끌어간다 —
      그 대신 이웃 절점 간 2차 차분이 작은 해(곧은 보간)를 고른다. y를 스케일로 나눈 뒤 고정 무차원 가중치라 해가 게인
      크기와 무관하다. 그 사실을 underdetermined로 남긴다.
    - **부호 보호** — 최소제곱은 0 근처 표본 사이에서 부호를 넘길 수 있다(다항의 _fit_preserving_sign이 막던 병리).
      표본이 한 부호면 넘긴(정확히 0 포함 — 0은 그 자리 루프를 끄는 값이다) 절점 값을 **그 절점 기저 범위 안** 같은 부호
      표본의 가장 작은 크기로 되돌리고 sign_guard.clipped에 남긴다. 되돌린 뒤 다시 풀지는 않는다 — 이웃 절점 값은 그대로라
      sample_residual이 되돌림의 대가를 그대로 보인다.
    """
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    k = np.asarray(sorted(float(c) for c in knots), dtype=float)
    if len(k) < 2:
        raise ValueError("절점 위 표에는 절점 2개 이상 필요")
    detail = []
    while len(k) >= 2:
        sup = _support(xs, k)
        weak = [i for i, (w, _n) in enumerate(sup) if w < SUPPORT_MIN_WEIGHT - _SUPPORT_EPS]
        if not weak:
            break
        for i in weak:
            w, n = sup[i]
            far = n > 0
            detail.append({"knot": float(k[i]), "reason": "far" if far else "none", "weight": w,
                           "text": (f"표본이 절점에서 멀다(가중 {w:.2g} < {SUPPORT_MIN_WEIGHT:g})" if far
                                    else "표본 없음")})
        k = np.delete(k, weak)
    detail.sort(key=lambda d: d["knot"])
    unsupported = [d["knot"] for d in detail]
    if len(k) < 2:
        raise ValueError(f"표본이 받치는 절점이 {len(k)}개 — 표를 세울 수 없다")
    A = _hat_basis(xs, k)
    underdetermined = int(np.linalg.matrix_rank(A)) < len(k)
    if underdetermined:
        # 곧은 보간 쪽 정칙화 — 2차 차분 행을 작은 가중치로 덧붙인다(표본 식이 이긴다). y를 스케일로 나눠 무차원으로 푼다
        s = float(np.max(np.abs(ys))) or 1.0
        D = np.zeros((len(k) - 2, len(k)))
        for i in range(len(k) - 2):
            h0, h1 = k[i + 1] - k[i], k[i + 2] - k[i + 1]
            D[i, i], D[i, i + 1], D[i, i + 2] = 1.0 / h0, -(1.0 / h0 + 1.0 / h1), 1.0 / h1
        A_s = np.vstack([A, _SMOOTH_W * D * (k[-1] - k[0])])
        v, *_ = np.linalg.lstsq(A_s, np.concatenate([ys / s, np.zeros(len(D))]), rcond=None)
        v = v * s
    else:
        v, *_ = np.linalg.lstsq(A, ys, rcond=None)
    want = _constant_sign(ys)
    clipped = []
    if want != 0.0:
        same = np.sign(ys) == want
        for i in range(len(v)):
            if v[i] * want <= 0.0:
                # 그 절점 기저 범위 안 같은 부호 표본의 최소 크기 — 전역 최소는 먼 자리의 작은 게인을 끌고 온다
                near = same & (A[:, i] > 0.0)
                pool = ys[near] if np.any(near) else ys[same]
                floor = want * float(np.min(np.abs(pool)))
                clipped.append({"knot": float(k[i]), "from": float(v[i]), "to": floor})
                v[i] = floor
    surface = table_surface(k, v)
    resid = np.abs(ys - A @ v)
    surface.update({
        "unsupported_knots": unsupported,
        "unsupported_detail": detail,
        "sample_residual": float(np.max(resid)),
        "rms": float(np.sqrt(np.mean(resid**2))),
        "underdetermined": underdetermined,
        "sign_guard": {"want": want, "degree_used": None, "lowered": False, "clipped": clipped,
                       "note": ("절점 값 최소제곱이 표본 부호를 넘겨 그 절점 근처 같은 부호 최소 표본 크기로 되돌렸다"
                                if clipped else "절점 위 표 — 최소제곱 절점 값이 표본 부호를 지켰다")},
    })
    return surface


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


def _allowed_axes(axes) -> tuple:
    """스케줄 축 제한 인자 정규화 — None = 전 축(AXES). AXES 밖 이름·빈 목록은 거부."""
    if axes is None:
        return AXES
    axes = tuple(axes)
    bad = [a for a in axes if a not in AXES]
    if not axes or bad:
        raise ValueError(f"스케줄 축은 {list(AXES)}의 비어 있지 않은 부분집합: {list(axes)}")
    return axes


def fit_slot(slot: str, samples: dict, points, *, flat_tol=0.02, tol_fit=0.02,
             max_degree=4, max_segments=4, mode="poly", axes=None, knots=None) -> dict:
    """자리 하나의 스케줄 표현 결정 — {"kind": "constant"|"poly"|"table", ...}.

    - 변동 축 없음 → 상수 (평균값 — 잔차를 report에 남긴다). **mode와 무관하다**:
      축 탈락은 표현의 문제가 아니라 "이 자리는 실질 변동이 없다"는 판정이다
    - 1축 → mode="poly"면 PolyTable(다항 런타임), mode="table"이면 튜닝값을 그대로
      분할점에 놓은 Table (모듈 머리말의 두 표현)
    - 2축 이상 → v1은 1D 한정 [백로그]: 지배 축(변동 최대)으로 펴고 나머지 축 기여를
      cross_axis_residual로 보고 — 조용히 뭉개지 않는다. 표 모드에서는 그 기여가
      분할점 값의 톱니로 나타나므로 zigzag·adjacent_jump_frac도 함께 낸다
    - axes(스케줄 축 제한, None = 전 축): 지배 축은 이 안에서만 고른다. 변동은 있는데
      제한 밖인 축은 axes_excluded로 보고한다 — 제한 안에 변동 축이 없으면 상수로
      접히고, 그 변동은 상수의 max_residual에 그대로 남는다. **mode와 직교한다**:
      제한은 "어느 축으로 펴는가", mode는 "편 것을 어떻게 싣는가"다. 제한 밖 축의
      기여는 두 표현 모두 cross_axis_residual(→ fit_quality cross_axis_frac)로, 표
      모드에서는 톱니(zigzag·joints)로도 드러난다
    - knots(표 모드 전용, 마하 절점 좌표 — None이면 옛 규칙): 지배 축이 마하면 분할점이 이 절점이고 값은 표본 전부의
      최소제곱(table_on_knots). 표본 없는 절점은 빠지고 보고된다(unsupported_knots). 지배 축이 마하가 아니면 절점을 쓸
      수 없어 옛 규칙으로 가고 note에 남긴다(절점 집합의 첫 적용은 마하 1축 — 05 §11.5). 다항 모드는 쓰지 않는다
    """
    if mode not in ("poly", "table"):
        raise ValueError(f"mode는 'poly'|'table': {mode!r}")
    allowed = _allowed_axes(axes)
    names = [n for n in samples if n in points]
    vals = np.array([samples[n] for n in names], dtype=float)
    detected = select_axes(samples, points, flat_tol=flat_tol)
    excluded = tuple(a for a in detected if a not in allowed)
    axes = tuple(a for a in detected if a in allowed)
    if not axes:
        mean = float(np.mean(vals)) if len(vals) else 0.0
        resid = float(np.max(np.abs(vals - mean))) if len(vals) else 0.0
        out = {"kind": "constant", "slot": slot, "value": mean, "max_residual": resid}
        if excluded:
            # 제한 밖 축 변동을 상수로 접었다 — 조용히 뭉개지 않는다
            out.update({"axes_detected": detected, "axes_excluded": excluded,
                        "note": f"변동 축 {list(excluded)}이 스케줄 축 {list(allowed)} 밖이라 상수로"
                                " 접었다 — 그 변동은 max_residual에 있다"})
        return out

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

    if mode == "table" and knots is not None and axis == "mach":
        try:
            surface = table_on_knots(xs, vals, knots)
        except ValueError as e:
            # 표본이 닿는 절점이 둘 미만 — 표를 세울 수 없으니 상수로 굳히고 사유를 남긴다(옛 규칙의 한 점 분기와 같다)
            mean = float(np.mean(vals))
            out = {"kind": "constant", "slot": slot, "value": mean,
                   "max_residual": float(np.max(np.abs(vals - mean))), "axes_detected": detected,
                   "cross_axis_residual": cross, "knots": [float(c) for c in knots],
                   "note": f"절점 위 표를 세울 수 없어 상수로 굳혔다 — {e}"}
            if excluded:
                out["axes_excluded"] = excluded
            return out
        report = dict(surface)
        report.update({
            "kind": "table", "slot": slot, "axes_detected": detected, "axis": axis,
            "cross_axis_residual": cross, "max_residual": surface["sample_residual"],
            "knots": [float(c) for c in knots],
        })
        if excluded:
            report["axes_excluded"] = excluded
        return {"kind": "table", "slot": slot,
                "table": Table({axis: np.asarray(surface["breakpoints"])}, np.asarray(surface["values"]),
                               name=slot, extrapolate="clip"),
                "report": report}

    if mode == "table":
        if len(xs_u) < 2:
            # 지배 축에 서로 다른 축값이 하나뿐 — 변동은 전부 다른 축에서 온 것이다.
            # 표를 세울 수 없으니 상수로 굳히고 **그 사실을 사유로** 남긴다
            mean = float(np.mean(ys_u))
            out = {
                "kind": "constant", "slot": slot, "value": mean,
                "max_residual": float(np.max(np.abs(vals - mean))),
                "axes_detected": detected, "cross_axis_residual": cross,
                "note": f"지배 축 {axis}의 분할점이 한 점 — 표를 세울 수 없어 상수로 굳혔다",
            }
            if excluded:
                out["axes_excluded"] = excluded
            return out
        surface = table_surface(xs_u, ys_u)
        # 잔차는 접기 전 **표본 전부**에 대해 잰다 — 접은 대표값끼리 재면 정의상 0이다
        resid = np.abs(vals - np.interp(xs, xs_u, ys_u))
        report = dict(surface)
        report.update({
            # axes_detected는 변동 축 전부(제한 밖 포함) — 다항 보고와 같은 뜻(아래)
            "kind": "table", "slot": slot, "axes_detected": detected, "axis": axis,
            "cross_axis_residual": cross,
            "max_residual": float(np.max(resid)),
            "rms": float(np.sqrt(np.mean(resid**2))),
            # 표는 표본값을 그대로 쓴다 — 부호를 넘길 곡선이 없다(다항의 부호 보호 대응)
            "sign_guard": {"want": _constant_sign(ys_u), "degree_used": None,
                           "lowered": False,
                           "note": "표 모드 — 표본값을 그대로 놓아 부호가 유지된다"},
        })
        if excluded:
            report["axes_excluded"] = excluded
        if knots is not None:
            report["note"] = f"지배 축 {axis} — 마하 절점 집합을 쓸 수 없어 표본 축값마다 분할점을 두었다(옛 규칙)"
        return {"kind": "table", "slot": slot,
                "table": Table({axis: xs_u}, ys_u, name=slot, extrapolate="clip"),
                "report": report}

    surface, poly, guard = _fit_preserving_sign(
        xs_u, ys_u, axis, slot,
        tol_fit=tol_fit, max_degree=max_degree, max_segments=max_segments,
    )
    if poly is None:  # 어떤 차수로도 부호를 못 지켰다 — 상수로 굳힌다
        mean = float(np.mean(ys_u))
        out = {
            "kind": "constant", "slot": slot, "value": mean,
            "max_residual": float(np.max(np.abs(ys_u - mean))),
            "sign_guard": guard,
        }
        if excluded:
            out.update({"axes_detected": detected, "axes_excluded": excluded})
        return out
    report = dict(surface)
    report.update({
        # axes_detected는 **실제로 변동이 있는 축 전부**다(제한 밖 포함) — 종전과 같은
        # 뜻을 지키고, 제한 때문에 적합에서 뺀 축은 axes_excluded로 따로 적는다
        "kind": "poly", "slot": slot, "axes_detected": detected, "axis": axis,
        "cross_axis_residual": cross, "sign_guard": guard,
    })
    if excluded:
        report["axes_excluded"] = excluded
    return {"kind": "poly", "slot": slot, "table": poly, "report": report}


def _constant_sign(ys) -> float:
    """샘플 전체가 한 부호면 그 부호(±1), 아니면 0(제약 없음).

    부호는 설계값이 보유한다(conventions·fcl/demo) — 튜닝은 크기만 정하므로
    샘플 부호가 곧 그 자리의 설계 부호다. 0이 섞여 있어도 나머지가 한 부호면
    그 부호로 본다(0은 어느 쪽도 위반하지 않는다).
    """
    nz = [s for s in np.sign(np.asarray(ys, dtype=float)) if s != 0.0]
    if not nz or any(s != nz[0] for s in nz):
        return 0.0
    return float(nz[0])


def _sign_violation(poly, axis, want, n=257) -> float:
    """조밀 샘플에서 부호를 넘긴 최대 크기 — 0이면 위반 없음.

    격자점 사이의 극값을 보려는 것이므로 knot보다 촘촘히 훑는다. 도함수 근을
    정확히 풀지 않는 근사지만, 부호를 넘기는 다항은 구간 안에서 넉넉한 폭으로
    넘어가므로(0 근처 값에 고차를 씌운 결과다) 이 해상도로 잡힌다.
    """
    if want == 0.0:
        return 0.0
    xs = np.linspace(float(poly.knots[0]), float(poly.knots[-1]), n)
    vals = np.array([poly.interp(**{axis: float(x)}) for x in xs])
    bad = -vals * want  # 부호가 반대인 지점에서 양수
    return float(max(bad.max(), 0.0))


def _fit_preserving_sign(xs, ys, axis, slot, *, tol_fit, max_degree, max_segments):
    """적합하되 **설계 부호를 넘지 않게** — (surface, poly|None, guard 리포트).

    0 근처 값을 갖는 자리(요축 ki·롤 ki 등)에 고차 다항을 씌우면 구간 사이에서
    곡선이 0을 가로질러 **부호가 뒤집힌다**. 잔차는 슬롯 전체 스케일 기준이라
    작게 보이지만, 그 점의 실효 게인은 양의 되먹임이 된다 — 데모 형상에서 실제로
    roll.ki가 설계 +0.1인데 M0.4346에서 −0.00022로 나왔다.

    허용치를 만족하는 **가장 높은 차수부터** 낮춰 가며 부호를 지키는 첫 적합을
    택한다. 1차까지 내려도 안 되면 호출자가 상수로 굳힌다(부호는 확실히 지켜진다).
    """
    want = _constant_sign(ys)
    attempts = []
    for degree in range(max_degree, 0, -1):
        surface = fit_gain_surface(
            xs, ys, tol_fit=tol_fit, max_degree=degree, max_segments=max_segments
        )
        poly = PolyTable(axis, surface["segments"], name=slot)
        viol = _sign_violation(poly, axis, want)
        attempts.append({"degree": degree, "violation": viol})
        if viol <= 0.0:
            return surface, poly, {
                "want": want, "degree_used": surface["max_degree_used"],
                "lowered": degree < max_degree, "attempts": attempts,
            }
    return None, None, {
        "want": want, "degree_used": None, "lowered": True, "attempts": attempts,
        "fallback": "constant",
        "note": "1차까지 낮춰도 부호를 지키지 못해 상수로 굳혔다",
    }


def fit_quality(report: dict) -> dict:
    """적합 보고 → 무차원 품질 지표 — 판정(문턱 대조)은 호출자(orchestrator._stage_fit).

    04 §10이 기록한 갭("joints·cross_axis_residual — 문턱도 소비자도 렌더 경로도
    없다")의 지표 부분이다. 정규화는 기체 무관이어야 하므로 그 자리 자신의 스케일로
    잰다 (상수 하드코딩 금지):
    - slope_jump_norm_max = max|slope_jump| / (scale/axis_span) — "축 전폭에 걸쳐
      스케일만큼 변하는 기울기"가 1인 자. knot 관절의 꺾임이 그 자리 곡선의 평균
      기울기 규모 대비 얼마나 급한가 (급한 꺾임 = 스케줄 전이 채터링 소지).
    - cross_axis_frac = cross_axis_residual / scale — 지배 축 적합이 뭉갠 다른 축
      기여의 비율 (v1 1D 한정의 대가를 수치로).
    상수 자리는 관절도 축도 없다 — None으로 낸다 (0 위장 금지: "잴 것이 없다"와
    "품질이 완벽하다"는 다른 말이다).

    **표 모드도 같은 자로 잰다.** 선형 보간 표는 분할점마다 기울기가 꺾이므로 관절이
    내부 분할점 전부이고(table_surface의 joints), 정규화도 같다 — 그래서 문턱
    (`fit_slope_jump_max`)이 두 표현에 그대로 적용된다. 04 §10이 "문턱도 소비자도
    없다"고 적었던 지표가 표 모드에서 **실제로 걸리는 첫 자리**다: 1축 붕괴의 톱니가
    이 값으로 드러난다.
    """
    kind = report.get("kind")
    if kind not in ("poly", "table"):
        return {"slope_jump_norm_max": None, "cross_axis_frac": None}
    if kind == "table":
        bps = report["breakpoints"]
        span = float(bps[-1] - bps[0]) or 1.0
    else:
        segs = report["segments"]
        span = float(segs[-1]["x1"] - segs[0]["x0"]) or 1.0
    scale = float(report["scale"])  # fit_gain_surface가 0을 1.0으로 이미 막았다
    unit = scale / span
    jumps = [abs(float(j["slope_jump"])) for j in report.get("joints") or []]
    return {
        "slope_jump_norm_max": (max(jumps) / unit) if jumps else 0.0,
        "cross_axis_frac": float(report.get("cross_axis_residual") or 0.0) / scale,
    }


# 튜닝 실패 표본을 뺀 뒤에도 남아야 하는 표본 수 — 적합(서로 다른 격자점 2개)·표(분할점 2개)가 서는 최소다.
# 이보다 적게 남으면 제외를 **보류**하고 그 사실을 보고한다 (사용자 합의 규칙 "자리마다 표본 2개 이상은 남긴다")
_MIN_KEPT_SAMPLES = 2


def _drop_failed_samples(samples: dict, points, failed: dict | None) -> tuple:
    """튜닝이 성립하지 않은 표본을 적합 전에 뺀다 — (남은 표본, 뺀 기록 목록, 보류 기록 | None).

    failed: {점 이름: 사유 레코드(dict — loop·reason·basis 등, 호출자가 정한다)}. 기록에는 그 표본의
    값도 싣는다 — 뺀 것이 "0 자리값"이었다는 사실이 보고에 남아야 한다. 적합에 안 쓰이는 점(points 밖)은
    남은 수에 세지 않는다 (fit_slot이 그 이름을 어차피 버린다)."""
    hit = sorted(n for n in (failed or {}) if n in samples)
    if not hit:
        return samples, [], None
    rows = [{"point": n, "value": float(samples[n]), **dict(failed[n])} for n in hit]
    kept = {n: v for n, v in samples.items() if n not in failed}
    n_kept = sum(1 for n in kept if n in points)
    if n_kept < _MIN_KEPT_SAMPLES:
        return samples, [], {
            "kept_would_be": n_kept, "min_kept": _MIN_KEPT_SAMPLES, "samples": rows,
            "note": f"튜닝 실패 표본 {len(rows)}개를 빼면 {n_kept}개만 남아 표가 서지 않는다 —"
                    " 제외를 보류했다. 이 자리의 스케줄은 실패 표본을 담고 있다",
        }
    return kept, rows, None


def fit_slots(gain_samples: dict, points, *, flat_tol=0.02, tol_fit=0.02,
              max_degree=4, max_segments=4, mode="poly", axes=None, exclude=None,
              knots_by_slot=None) -> dict:
    """전 자리 적합 — {"tables": {자리: PolyTable|Table}, "constants": {자리: 값}, "reports"}.

    mode="table"이면 tables 항목이 Table(선형 보간)이다 — 모듈 머리말의 두 표현.
    tol_fit·max_degree·max_segments는 다항 전용이라 표 모드에서는 쓰이지 않는다
    (호출자가 그 사실을 알아야 한다: 표 모드에서 tighten_fit 처방은 듣지 않는다 —
    orchestrator.apply_actions가 사유를 달아 건너뛴다).
    axes: 스케줄 축 제한(fit_slot) — None이면 전 축. 표현(mode)과 무관하게 걸린다.

    exclude: {자리: {점 이름: 사유 레코드}} — **튜닝이 성립하지 않은 표본**(tune.SLOT_DESIGN_FAILED)을
    적합 전에 뺀다. 실패한 튜닝은 게인을 못 찾았다는 뜻이지 그 점의 게인이 0이라는 뜻이 아니다 — 자리값
    (댐퍼를 끈 0, 뒤집힌 루프의 백오프 해)이 표본으로 들어가면 표 모드는 그 값을 **그대로 분할점에** 놓고
    (S1 표 모드 실측: roll.k_rate가 M0.1077·M0.1130에서 정확히 0, 이웃 −0.49), 다항 모드는 곡선을 끌어
    내린다. 뺀 표본은 보고의 `excluded_samples`에 값·사유와 함께 남고, 그 점의 게인은 이웃 표본의 보간으로
    정해져 VERIFY가 **그 보간값으로** 판정한다. 표본이 `_MIN_KEPT_SAMPLES` 미만으로 남으면 빼지 않고
    `exclusion_withheld`로 보고한다. 표현(mode)과 무관하게 걸린다.

    knots_by_slot: {자리: 마하 절점 좌표} — 표 모드에서 그 자리의 표를 절점 위에 세운다(fit_slot knots). 없는 자리·None은
    옛 규칙(표본 마하마다 분할점). 다항 모드는 쓰지 않는다.
    """
    _allowed_axes(axes)  # 샘플이 없어도 잘못된 제한은 여기서 말한다
    tables, constants, reports = {}, {}, {}
    for slot, samples in gain_samples.items():
        samples, dropped, withheld = _drop_failed_samples(samples, points, (exclude or {}).get(slot))
        out = fit_slot(
            slot, samples, points, flat_tol=flat_tol, tol_fit=tol_fit,
            max_degree=max_degree, max_segments=max_segments, mode=mode, axes=axes,
            knots=(knots_by_slot or {}).get(slot) if mode == "table" else None,
        )
        if out["kind"] == "constant":
            constants[slot] = out["value"]
            reports[slot] = out
        else:
            tables[slot] = out["table"]
            reports[slot] = out["report"]
        if dropped:
            reports[slot]["excluded_samples"] = dropped
        if withheld:
            reports[slot]["exclusion_withheld"] = withheld
    return {"tables": tables, "constants": constants, "reports": reports}


def resample_to_table(poly: PolyTable, *, tol_interp=0.01, max_pts=65) -> Table:
    """다항 → 선형 보간 오차 허용치 내 최소 breakpoint Table — **채택되는 반출 표**.

    웹 「채택」과 apply-gains가 기체에 주입하는 것이 이 표다(모듈 머리말) — 검증받은
    다항의 근사이므로 반출 시 reverify_resampled로 판정 차이를 재확인한다.
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
