"""공력 DB 뷰어 계산 — 기체 문서의 계수 계산기로 한 축을 따라 곡선을 낸다 (02 §5.2 · 02 §5.6).

뷰어는 표를 따로 들고 있지 않는다 — 시뮬·트림이 쓰는 **같은 계산기**(make_coef_fn)를 부른다. 그래서 곡선이
곧 기체가 느끼는 계수다(표 항·상수항·타면 증분이 합쳐진 값). 무차원 각속도는 0, V는 마하 × 그 고도 음속이다.

양력·항력은 동체축 계수에서 풍축으로 되돌려 낸다(두 형식 공통, plant/aero.wind_to_body_coeffs의 역):
    CL = CX·sinα − CZ·cosα,   CD = (−CX·cosα − CZ·sinα) / cosβ
실속 추출은 **참고용**이다 — α를 따라 CL이 오르다 (평평한 구간을 지나) **실제로 떨어지는** 첫 꼭대기. 정본은
공력팀의 실속 표다(01 §2.3). 그래서 둘을 나란히 내고 차이를 적는다 — 어긋나면 표와 DB 중 하나를 다시 볼 자리다.
추출은 CL을 만드는 표 항의 α 격자와 DB 유효 범위(db_ranges.alpha)가 겹치는 구간 안에서만 한다 — 그 밖은
외삽이라(clip이면 평평, 동체축 형식이면 CX·sinα − CZ·cosα가 α만으로 떨어진다) 꺾여도 실속이 아니라 표 끝이다.
"""

import math

from claw.env import isa_atmosphere
from claw.plant.dispersion import DispersionSet
from claw.profile.aero_terms import make_coef_fn

SLICE_AXES = ("alpha", "beta", "mach", "alt", "de", "da", "dr")
MAX_POINTS = 401
DEFAULT_POINT = {"alpha": 0.0, "beta": 0.0, "mach": 0.5, "alt": 0.0, "de": 0.0, "da": 0.0, "dr": 0.0}
COEFFICIENTS = ("CL", "CD", "CX", "CY", "CZ", "Cl", "Cm", "Cn")


def _cl_alpha_window(aero: dict) -> tuple:
    """CL을 만드는 표 항의 α 격자 구간과 db_ranges.alpha의 교집합 (lo, hi). 제약이 없는 쪽은 ±inf."""
    lo, hi = -math.inf, math.inf
    for name in ("CL",) if aero["form"] == "lift_drag" else ("CX", "CZ"):
        for t in aero["coefficients"][name]:
            grid = t["k"]["table"]["axes"].get("alpha") if isinstance(t["k"], dict) else None
            if grid:
                lo, hi = max(lo, grid[0]), min(hi, grid[-1])
    r = aero["db_ranges"]["alpha"]
    if r is not None:
        lo, hi = max(lo, r[0]), min(hi, r[1])
    return lo, hi


def _cl_peak(xs, cl, lo, hi):
    """구간 [lo, hi] 안에서 CL이 오르다 평평한 구간을 지나 **떨어지는** 첫 꼭대기의 α. 없으면 None.

    떨어짐까지 구간 안에서 봐야 한다 — 표 끝 뒤 clip의 평평함을 꼭대기로 치면 선형 DB가 실속하는 것처럼 보인다."""
    idx = [i for i, x in enumerate(xs) if lo <= x <= hi]
    if len(idx) < 3:
        return None
    # 평평함의 허용 폭 — 같은 값 두 격자 사이도 보간 가중 합이 한 ulp씩 흔들린다(0.0 + w₀·d + w₁·d ≠ d)
    tol = 1e-12 * max(1.0, max(abs(c) for c in cl))
    a, b = idx[0], idx[-1]
    i = a + 1
    while i < b:
        if cl[i] - cl[i - 1] > tol and cl[i + 1] - cl[i] <= tol:
            j = i
            while j < b and abs(cl[j + 1] - cl[j]) <= tol:
                j += 1
            if j < b and cl[j + 1] - cl[j] < -tol:
                return xs[i]
            i = j + 1  # 평평하다 다시 오르거나 구간 끝 — 다음 꼭대기를 찾는다
            continue
        i += 1
    return None


def _slice_args(start, stop, n, fixed):
    """공용 인자 검증 — (xs 격자, 고정 입력점). aero_slice·stability_slice가 같은 계약을 쓴다."""
    n = int(n)
    if not 2 <= n <= MAX_POINTS:
        raise ValueError(f"점 수는 2~{MAX_POINTS}: {n}")
    start, stop = float(start), float(stop)
    if not (math.isfinite(start) and math.isfinite(stop) and start < stop):
        raise ValueError(f"구간은 유한하고 시작 < 끝이어야 함: [{start}, {stop}]")
    point = dict(DEFAULT_POINT)
    for key, value in (fixed or {}).items():
        if key not in SLICE_AXES:
            raise ValueError(f"고정 입력은 {list(SLICE_AXES)} 중 하나: {key!r}")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"고정 입력 {key}는 유한값이어야 함: {value}")
        point[key] = value
    return [start + (stop - start) * i / (n - 1) for i in range(n)], point


def aero_slice(built, along, start, stop, n, fixed=None) -> dict:
    """BuiltProfile → {along, x, fixed, coefficients{CL…Cn: [..]}, stall, db_ranges, form}. 틀린 인자는 ValueError."""
    if along not in SLICE_AXES:
        raise ValueError(f"따라갈 축은 {list(SLICE_AXES)} 중 하나: {along!r}")
    xs, point = _slice_args(start, stop, n, fixed)
    coef = make_coef_fn(built.doc["aero"], DispersionSet())
    series = {c: [] for c in COEFFICIENTS}
    for x in xs:
        p = dict(point)
        p[along] = x
        atm = isa_atmosphere(p["alt"])
        c = coef({**p, "V": p["mach"] * atm.a, "phat": 0.0, "qhat": 0.0, "rhat": 0.0})
        sa, ca, cb = math.sin(p["alpha"]), math.cos(p["alpha"]), math.cos(p["beta"])
        series["CL"].append(c["CX"] * sa - c["CZ"] * ca)
        series["CD"].append((-c["CX"] * ca - c["CZ"] * sa) / cb)
        for k in ("CX", "CY", "CZ", "Cl", "Cm", "Cn"):
            series[k].append(c[k])

    stall_table = built.stall_table()
    stall = {"table_at": None, "table_curve": None, "extracted": None, "delta": None, "reason": None,
             "window": None}
    if along == "alpha":
        stall["table_at"] = float(stall_table.interp(mach=point["mach"]))
        lo, hi = _cl_alpha_window(built.doc["aero"])
        stall["window"] = [lo if math.isfinite(lo) else None, hi if math.isfinite(hi) else None]
        peak = _cl_peak(xs, series["CL"], lo, hi)
        if peak is not None:
            stall["extracted"] = peak
            stall["delta"] = peak - stall["table_at"]
        elif math.isfinite(lo) or math.isfinite(hi):
            stall["reason"] = ("표 α 격자·DB 유효 범위 안에서 CL이 오르다 떨어지는 점이 없다 — 실속 전 구간이거나 선형"
                               " 모델이다 (범위 밖 곡선은 외삽이라 보지 않는다)")
        else:
            stall["reason"] = "이 구간에서 CL이 오르다 떨어지는 점이 없다 — 실속 전 구간이거나 선형 모델이다"
    elif along == "mach":
        stall["table_curve"] = [float(stall_table.interp(mach=x)) for x in xs]
    return {
        "along": along,
        "x": xs,
        "fixed": {k: v for k, v in point.items() if k != along},
        "coefficients": series,
        "stall": stall,
        "db_ranges": dict(built.doc["aero"]["db_ranges"]),
        "form": built.doc["aero"]["form"],
    }


# 정적 안정성 도함수의 중앙차분 간격 [rad] — 표 항은 구간 선형이라 격자점 사이에서는
# 정확한 기울기고, 격자점 위에서는 좌우 기울기의 평균이다(더 나은 단일 답이 없다)
FD_STEP = 1e-4
# 도함수 → 안정 부호. 횡 Clβ < 0(상반각 효과) · 방향 Cnβ > 0(풍향계 안정) · 종 Cmα < 0
STABILITY_SIGNS = {"Cl_beta": -1.0, "Cn_beta": 1.0, "Cm_alpha": -1.0}


def _sign_violations(xs, vals, sign):
    """안정 부호를 벗어난 α 구간 [[α_시작, α_끝], …] — 도함수 0(중립)도 위반이다.

    0을 통과로 치면 β에 무반응인 기체(Clβ ≡ 0)가 "횡 안정"으로 찍힌다 — 복원
    모멘트가 없는 것은 안정이 아니다."""
    out = []
    i = 0
    while i < len(xs):
        if vals[i] * sign <= 0.0:
            j = i
            while j + 1 < len(xs) and vals[j + 1] * sign <= 0.0:
                j += 1
            out.append([xs[i], xs[j]])
            i = j + 1
        else:
            i += 1
    return out


def stability_slice(built, start, stop, n, fixed=None) -> dict:
    """정적 안정성 도함수 곡선 — α 격자에서 Clβ·Cnβ·Cmα를 중앙차분으로 (02 §5.2 확장).

    뷰어(aero_slice)와 **같은 계산기**(make_coef_fn)를 쓴다 — 도함수가 별도 모델이
    아니라 시뮬·트림이 느끼는 그 계수의 기울기다. β 도함수는 고정 β(기본 0) 주변,
    α 도함수는 그 α 주변에서 잰다. 판정은 STABILITY_SIGNS 부호 관례고, 위반 구간을
    [[α, α], …]로 낸다 — 전 구간 안정이면 빈 목록이다.
    """
    xs, point = _slice_args(start, stop, n, fixed)
    coef = make_coef_fn(built.doc["aero"], DispersionSet())

    def coef_at(p):
        atm = isa_atmosphere(p["alt"])
        return coef({**p, "V": p["mach"] * atm.a, "phat": 0.0, "qhat": 0.0, "rhat": 0.0})

    h = FD_STEP
    derivs = {name: [] for name in STABILITY_SIGNS}
    for x in xs:
        p = dict(point)
        p["alpha"] = x
        bp = coef_at({**p, "beta": p["beta"] + h})
        bm = coef_at({**p, "beta": p["beta"] - h})
        ap = coef_at({**p, "alpha": x + h})
        am = coef_at({**p, "alpha": x - h})
        derivs["Cl_beta"].append((bp["Cl"] - bm["Cl"]) / (2.0 * h))
        derivs["Cn_beta"].append((bp["Cn"] - bm["Cn"]) / (2.0 * h))
        derivs["Cm_alpha"].append((ap["Cm"] - am["Cm"]) / (2.0 * h))
    judgments = {}
    for name, sign in STABILITY_SIGNS.items():
        violations = _sign_violations(xs, derivs[name], sign)
        judgments[name] = {
            "stable_sign": "+" if sign > 0 else "-",
            "violations": violations,
            "all_ok": not violations,
        }
    return {
        "x": xs,
        "fixed": {k: v for k, v in point.items() if k != "alpha"},
        "derivatives": derivs,
        "judgments": judgments,
        "step": h,
        "db_ranges": dict(built.doc["aero"]["db_ranges"]),
        "form": built.doc["aero"]["form"],
    }
