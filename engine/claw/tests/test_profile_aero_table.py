"""공력 표 항 — 문서의 표 k가 계수 계산기·기체 조립·뷰어까지 이어진다 (02 §5.6 · 02 §5.2)."""

import copy
import math

import numpy as np
import pytest

from claw.plant.dispersion import DispersionSet
from claw.plant.aero import wind_to_body_coeffs
from claw.profile import ProfileError, build_profile, load_example, validate_document
from claw.profile.aero_terms import make_coef_fn
from claw.profile.aeroview import aero_slice

ALPHAS = [-0.2, 0.0, 0.1, 0.2, 0.3, 0.4, 0.6]
MACHS = [0.1, 0.5, 0.9]


def _cl_linear_terms(doc):
    """예제 CL에서 상수항·α항만 골라 (CL0, CLa)와 나머지 항을 돌려준다."""
    terms = doc["aero"]["coefficients"]["CL"]
    const = [t for t in terms if t["inputs"] == [] and t["dispersion"] is None]
    lin = [t for t in terms if t["inputs"] == ["alpha"] and t["dispersion"] is None]
    rest = [t for t in terms if t not in const and t not in lin]
    return (const[0]["k"] if const else 0.0), (lin[0]["k"] if lin else 0.0), rest


def _with_cl_table(doc, fn, axes=None):
    d = copy.deepcopy(doc)
    cl0, cla, rest = _cl_linear_terms(d)
    axes = axes or {"alpha": ALPHAS, "mach": MACHS}
    grids = list(axes.values())
    data = np.zeros([len(g) for g in grids])
    for idx in np.ndindex(*data.shape):
        data[idx] = fn(cl0, cla, *[g[i] for g, i in zip(grids, idx)])
    d["aero"]["coefficients"]["CL"] = [{"k": {"table": {"axes": axes, "data": data.tolist(), "extrapolate": "clip"}},
                                        "inputs": [], "dispersion": None}] + rest
    return d


def test_linear_table_reproduces_the_numeric_terms_inside_the_grid():
    """α에 선형인 CL을 표로 옮기면 격자 안 어디서나 같은 계수다 — 다중선형 보간이 선형 함수에 정확하다."""
    ex = load_example()
    tab = validate_document(_with_cl_table(ex, lambda cl0, cla, a, m: cl0 + cla * a))
    f_num = make_coef_fn(ex["aero"], DispersionSet())
    f_tab = make_coef_fn(tab["aero"], DispersionSet())
    rs = np.random.RandomState(3)
    for _ in range(200):
        inp = {"alpha": rs.uniform(-0.2, 0.6), "beta": rs.uniform(-0.2, 0.2), "V": 100.0,
               "mach": rs.uniform(0.1, 0.9), "phat": 0.0, "qhat": rs.uniform(-0.1, 0.1), "rhat": 0.0,
               "de": rs.uniform(-0.3, 0.3)}
        a, b = f_num(dict(inp)), f_tab(dict(inp))
        for k in ("CX", "CZ", "Cm"):
            assert math.isclose(a[k], b[k], rel_tol=1e-12, abs_tol=1e-12), (k, a[k], b[k])


def test_altitude_axis_reaches_the_table_through_the_aircraft():
    """고도가 **표에** 닿는지를 밀도와 떼어 본다 — 같은 고도에서 고도 축만 다른 두 표를 비교한다.

    두 표는 0 m에서 같고 10 km에서만 다르다. 호출 경로가 고도를 0으로 넘기면(또는 안 넘기면) 두 기체가 같은 힘을 낸다."""
    ex = load_example()
    flat = _with_cl_table(ex, lambda cl0, cla, a, h: cl0 + cla * a, axes={"alpha": ALPHAS, "alt": [0.0, 10000.0]})
    fade = _with_cl_table(ex, lambda cl0, cla, a, h: (cl0 + cla * a) * (1.0 - h / 20000.0),
                          axes={"alpha": ALPHAS, "alt": [0.0, 10000.0]})
    b_flat, b_fade = build_profile(flat), build_profile(fade)
    coef = make_coef_fn(b_fade.doc["aero"], DispersionSet())
    base = {"alpha": 0.1, "beta": 0.0, "V": 100.0, "mach": 0.3, "phat": 0.0, "qhat": 0.0, "rhat": 0.0}
    with pytest.raises(ValueError, match="alt"):
        coef(dict(base))  # 고도를 안 넘긴 호출은 이유와 함께 거부 — 조용히 0 m로 읽지 않는다

    vel, w, q = np.array([100.0, 0.0, 10.0]), np.zeros(3), np.array([1.0, 0, 0, 0])
    at = lambda b, h: b.aircraft().fm(vel, w, q, h, {"de": 0.0}, 200.0)[0]
    assert np.array_equal(at(b_flat, 0.0), at(b_fade, 0.0))
    assert at(b_flat, 5000.0)[2] != at(b_fade, 5000.0)[2]  # Aircraft.fm이 고도를 표에 넘긴다

    from claw.analysis.envelope import vn_stall_boundary
    n_of = lambda b, alt: vn_stall_boundary(b.aircraft(), b.stall_table(), alt, 0.5, [0.4])["n"][0]
    assert n_of(b_flat, 0.0) == n_of(b_fade, 0.0)
    assert n_of(b_fade, 5000.0) < n_of(b_flat, 5000.0)  # V-n 실속 경계도 고도를 표에 넘긴다


def test_dispersion_tag_scales_a_table_term_in_the_numeric_order():
    """표 항의 섭동은 (T·(1+d))·입력 — 수치 k의 (k·(1+d))·입력과 같은 순서라 격자점에서 비트까지 같다."""
    doc = load_example()
    cm = doc["aero"]["coefficients"]["Cm"]
    tagged = next(t for t in cm if t["dispersion"] == "cmalpha")
    tagged["k"] = {"table": {"axes": {"mach": [0.1, 0.9]}, "data": [tagged["k"], tagged["k"]], "extrapolate": "clip"}}
    doc = validate_document(doc)
    for mach in (0.1, 0.9):  # 격자점 — 보간이 표 값을 그대로 낸다
        inp = {"alpha": 0.2, "beta": 0.0, "V": 100.0, "mach": mach, "phat": 0.0, "qhat": 0.0, "rhat": 0.0}
        for d in (0.2, -0.2):
            scaled = make_coef_fn(doc["aero"], DispersionSet(cmalpha=d))(dict(inp))["Cm"]
            base = make_coef_fn(load_example()["aero"], DispersionSet(cmalpha=d))(dict(inp))["Cm"]
            assert scaled == base
        assert make_coef_fn(doc["aero"], DispersionSet())(dict(inp))["Cm"] != scaled


def test_document_caps_bound_the_work_per_request(monkeypatch):
    """한 장 상한만으로는 문서 한 벌의 비용을 못 막는다 — 계수마다 항 수, 표 모서리 합, 문서 칸 합(변형 곱)을 막는다."""
    from claw.profile import schema

    def fails(doc):
        with pytest.raises(ProfileError) as e:
            validate_document(doc)
        return e.value

    many = load_example()
    many["aero"]["coefficients"]["Cl"] = [{"k": 0.0, "inputs": [], "dispersion": None}] * (schema.MAX_TERMS_PER_COEF + 1)
    assert fails(many).path == "/aero/coefficients/Cl"

    corners = load_example()
    seven = {"table": {"axes": {a: [0.0, 1.0] for a in schema.TABLE_AXES},
                       "data": np.zeros([2] * 7).tolist(), "extrapolate": "clip"}}
    n_tables = schema.MAX_TABLE_CORNERS // 128 + 1
    corners["aero"]["coefficients"]["Cl"] = [{"k": seven, "inputs": [], "dispersion": None}] * n_tables
    assert fails(corners).path == "/aero/coefficients" and "모서리" in fails(corners).message

    monkeypatch.setattr(schema, "MAX_DOCUMENT_TABLE_CELLS", 50)
    doc = _with_cl_table(load_example(), lambda cl0, cla, a, m: cl0 + cla * a)  # 7 × 3 = 21칸
    table = copy.deepcopy(doc["aero"]["coefficients"]["CL"][0])
    variant = lambda i, patch: {"id": f"v{i}", "name": f"v{i}", "patch": patch}
    doc["variants"] = [variant(1, {"/geometry/S": 1.0})]
    validate_document(doc)  # 21 × 2 = 42
    doc["variants"].append(variant(2, {"/geometry/S": 2.0}))
    assert fails(doc).path == "/variants"  # 21 × 3 = 63 — 변형 수가 곱해진다
    doc["variants"] = [variant(1, {"/aero/coefficients/Cm": [table]})]
    err = fails(doc)
    assert err.path == "/variants" and "변형이 넣는 표 21칸" in err.message  # 21 × 2 + 21 = 63


def test_axis_order_is_part_of_both_fingerprints():
    """축 객체 순서가 data 중첩 순서다 — 격자 점 수가 같은 두 축을 맞바꾸면 물리가 달라지므로 지문도 달라야 한다."""
    from claw.profile.fingerprint import plant_fingerprint, profile_fingerprint

    ab = load_example()
    ab["aero"]["coefficients"]["CL"] = [{"k": {"table": {"axes": {"alpha": [0.0, 0.5], "mach": [0.2, 0.8]},
                                                          "data": [[0.0, 1.0], [2.0, 3.0]], "extrapolate": "clip"}},
                                         "inputs": [], "dispersion": None}]
    ba = copy.deepcopy(ab)
    tab = ba["aero"]["coefficients"]["CL"][0]["k"]["table"]
    tab["axes"] = {"mach": tab["axes"]["mach"], "alpha": tab["axes"]["alpha"]}
    ab, ba = validate_document(ab), validate_document(ba)
    inp = {"alpha": 0.5, "beta": 0.0, "V": 100.0, "mach": 0.2, "phat": 0.0, "qhat": 0.0, "rhat": 0.0}
    assert make_coef_fn(ab["aero"], DispersionSet())(dict(inp)) != make_coef_fn(ba["aero"], DispersionSet())(dict(inp))
    assert plant_fingerprint(ab) != plant_fingerprint(ba)
    assert profile_fingerprint(ab) != profile_fingerprint(ba)


def test_table_validation_names_the_path():
    def bad(mutate):
        doc = _with_cl_table(load_example(), lambda cl0, cla, a, m: cl0 + cla * a)
        mutate(doc["aero"]["coefficients"]["CL"][0]["k"]["table"])
        with pytest.raises(ProfileError) as e:
            validate_document(doc)
        return e.value.path
    base = "/aero/coefficients/CL/0/k/table"
    assert bad(lambda t: t["axes"].update({"qhat": [0.0, 1.0]})) == f"{base}/axes/qhat"
    assert bad(lambda t: t["axes"].__setitem__("alpha", [0.0, 0.0, 1.0])).startswith(f"{base}/axes/alpha")
    assert bad(lambda t: t["data"].pop()) == f"{base}/data"
    assert bad(lambda t: t["data"][0].__setitem__(1, float("nan"))) == f"{base}/data/0/1"
    assert bad(lambda t: t.__setitem__("extrapolate", "cubic")) == f"{base}/extrapolate"


def test_slice_inverts_wind_axes_and_extracts_a_stall_peak():
    ex = build_profile(load_example())
    s = aero_slice(ex, "alpha", -0.1, 0.5, 61, {"mach": 0.4, "beta": 0.05})
    assert len(s["x"]) == 61 and set(s["coefficients"]) == {"CL", "CD", "CX", "CY", "CZ", "Cl", "Cm", "Cn"}
    for i in range(0, 61, 10):
        a = s["x"][i]
        cx, _cy, cz = wind_to_body_coeffs(s["coefficients"]["CL"][i], s["coefficients"]["CD"][i], a, 0.05)
        assert math.isclose(cx, s["coefficients"]["CX"][i], rel_tol=1e-9, abs_tol=1e-12)
        assert math.isclose(cz, s["coefficients"]["CZ"][i], rel_tol=1e-9, abs_tol=1e-12)
    # 예제는 선형 CL — 꺾이는 점이 없다고 말한다(지어내지 않는다)
    assert s["stall"]["extracted"] is None and s["stall"]["reason"] and s["stall"]["table_at"] is not None

    peak = build_profile(_with_cl_table(load_example(),
                                        lambda cl0, cla, a, m: cl0 + cla * min(a, 0.3) - 2.0 * max(a - 0.3, 0.0)))
    p = aero_slice(peak, "alpha", -0.2, 0.6, 81, {"mach": 0.5})
    assert math.isclose(p["stall"]["extracted"], 0.3, abs_tol=1e-9)
    assert math.isclose(p["stall"]["delta"], 0.3 - p["stall"]["table_at"], abs_tol=1e-12)
    m = aero_slice(peak, "mach", 0.1, 0.9, 9, {"alpha": 0.1})
    assert len(m["stall"]["table_curve"]) == 9 and m["stall"]["extracted"] is None


@pytest.mark.parametrize("args", [("qhat", 0, 1, 5), ("alpha", 0.2, 0.1, 5), ("alpha", 0, 1, 1),
                                  ("alpha", 0, 1, 402), ("alpha", 0, float("inf"), 5)])
def test_slice_rejects_bad_arguments(args):
    with pytest.raises(ValueError):
        aero_slice(build_profile(load_example()), *args)
    with pytest.raises(ValueError):
        aero_slice(build_profile(load_example()), "alpha", 0, 1, 5, {"V": 100.0})


def test_stall_is_not_extracted_at_the_end_of_the_table():
    """표 끝 뒤 clip의 평평함, 또는 외삽 구간의 하강은 실속이 아니다 — 격자·DB 유효 범위 안의 하강만 본다."""
    doc = _with_cl_table(load_example(), lambda cl0, cla, a, m: cl0 + cla * a,
                         axes={"alpha": [-0.2, 0.0, 0.2, 0.4], "mach": MACHS})
    doc["aero"]["db_ranges"]["alpha"] = None
    flat = aero_slice(build_profile(doc), "alpha", -0.2, 0.6, 81, {"mach": 0.5})
    assert flat["stall"]["extracted"] is None and flat["stall"]["window"] == [-0.2, 0.4]  # 예전엔 0.41

    # 표 끝 뒤에서 수치 항이 CL을 실제로 떨어뜨려도 외삽 구간이라 추출하지 않는다
    drop = copy.deepcopy(doc)
    cl0, cla, _ = _cl_linear_terms(load_example())
    tab = drop["aero"]["coefficients"]["CL"][0]["k"]["table"]
    tab["data"] = [[cl0 + 2.0 * cla * a] * len(MACHS) for a in tab["axes"]["alpha"]]
    drop["aero"]["coefficients"]["CL"].append({"k": -cla, "inputs": ["alpha"], "dispersion": None})
    assert aero_slice(build_profile(drop), "alpha", -0.2, 0.6, 81, {"mach": 0.5})["stall"]["extracted"] is None

    # 평평한 꼭대기 뒤에 실제로 떨어지면 꼭대기의 시작이 추출점이다
    plateau = _with_cl_table(load_example(),
                             lambda cl0, cla, a, m: cl0 + cla * min(a, 0.2) - (2.0 * (a - 0.3) if a > 0.3 else 0.0),
                             axes={"alpha": [-0.2, 0.0, 0.2, 0.3, 0.4, 0.6], "mach": MACHS})
    plateau["aero"]["db_ranges"]["alpha"] = None
    s = aero_slice(build_profile(plateau), "alpha", -0.2, 0.6, 81, {"mach": 0.5})
    assert math.isclose(s["stall"]["extracted"], 0.2, abs_tol=1e-9)


# ── 정적 안정성 도함수 (stability_slice — Clβ·Cnβ·Cmα vs α) ─────────────────


def test_stability_slice_matches_finite_difference_of_slices():
    """도함수 곡선은 같은 계산기(aero_slice)의 유한차분과 일치한다 — 별도 모델이 아니다."""
    from claw.profile.aeroview import FD_STEP, stability_slice

    ex = build_profile(load_example())
    fixed = {"mach": 0.4, "alt": 500.0, "beta": 0.02}
    s = stability_slice(ex, -0.1, 0.4, 11, fixed)
    assert set(s["derivatives"]) == {"Cl_beta", "Cn_beta", "Cm_alpha"}
    assert len(s["x"]) == 11 and s["fixed"]["beta"] == 0.02
    h = FD_STEP
    up = aero_slice(ex, "alpha", -0.1, 0.4, 11, {**fixed, "beta": 0.02 + h})
    dn = aero_slice(ex, "alpha", -0.1, 0.4, 11, {**fixed, "beta": 0.02 - h})
    for i in (0, 5, 10):
        for name in ("Cl", "Cn"):
            fd = (up["coefficients"][name][i] - dn["coefficients"][name][i]) / (2 * h)
            assert math.isclose(s["derivatives"][f"{name}_beta"][i], fd, rel_tol=1e-9, abs_tol=1e-12)
    cm = aero_slice(ex, "alpha", -0.1 - h, 0.4 - h, 11, fixed)  # α축 이동 곡선으로 Cmα 대조
    cm2 = aero_slice(ex, "alpha", -0.1 + h, 0.4 + h, 11, fixed)
    for i in (0, 5, 10):
        fd = (cm2["coefficients"]["Cm"][i] - cm["coefficients"]["Cm"][i]) / (2 * h)
        assert math.isclose(s["derivatives"]["Cm_alpha"][i], fd, rel_tol=1e-6, abs_tol=1e-10)


def test_stability_slice_judgments_and_violation_intervals():
    """부호 판정 — 안정 부호(Clβ<0·Cnβ>0·Cmα<0)와 위반 구간 [α_시작, α_끝]."""
    from claw.profile.aeroview import stability_slice

    doc = load_example()
    # 횡: α에 따라 부호가 바뀌는 Clβ — α ≥ 0.2에서 +(위반). 표 k(α) × β 항
    doc["aero"]["coefficients"]["Cl"] = [{
        "k": {"table": {"axes": {"alpha": [-0.2, 0.1999, 0.2, 0.6]},
                        "data": [-0.1, -0.1, 0.05, 0.05], "extrapolate": "clip"}},
        "inputs": ["beta"], "dispersion": None}]
    # 방향: 상수 풍향계 안정
    doc["aero"]["coefficients"]["Cn"] = [{"k": 0.12, "inputs": ["beta"], "dispersion": None}]
    s = stability_slice(build_profile(doc), 0.0, 0.4, 5, {"mach": 0.4})  # α 격자 0.0~0.4 (0.1 간격)
    jl = s["judgments"]["Cl_beta"]
    assert jl["stable_sign"] == "-" and jl["all_ok"] is False
    assert jl["violations"] == [[0.2, 0.4]]  # 0.2부터 끝까지 한 구간
    jn = s["judgments"]["Cn_beta"]
    assert jn["stable_sign"] == "+" and jn["all_ok"] is True and jn["violations"] == []
    assert s["judgments"]["Cm_alpha"]["stable_sign"] == "-"


def test_stability_slice_neutral_counts_as_violation():
    """도함수 0(중립)은 안정이 아니다 — 0을 통과로 치면 β 무반응 기체가 «안정»이 된다."""
    from claw.profile.aeroview import stability_slice

    doc = load_example()
    doc["aero"]["coefficients"]["Cl"] = []  # 횡 모멘트 없음 → Clβ ≡ 0
    s = stability_slice(build_profile(doc), -0.1, 0.1, 3, {"mach": 0.4})
    j = s["judgments"]["Cl_beta"]
    assert j["all_ok"] is False and j["violations"] == [[-0.1, 0.1]]


@pytest.mark.parametrize("args", [(0.2, 0.1, 5), (0, 1, 1), (0, 1, 402), (0, float("nan"), 5)])
def test_stability_slice_rejects_bad_arguments(args):
    from claw.profile.aeroview import stability_slice

    with pytest.raises(ValueError):
        stability_slice(build_profile(load_example()), *args)
    with pytest.raises(ValueError):
        stability_slice(build_profile(load_example()), 0, 1, 5, {"V": 100.0})
