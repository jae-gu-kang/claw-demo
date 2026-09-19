"""초기 게인 산출 근거 — 저차 근사 닫힌꼴 + 전체 모델 확인 + 조종면 예산 (05 §10.1)."""

import math

import numpy as np
import pytest

from claw.design.basis import (
    NEIGHBOR_MULTS,
    REASON_BASIS_TRIM_FAILED,
    match_zeta_2x2,
    reason_text,
    seed_basis,
)
from claw.design.tune import TuneTargets
from claw.profile import build_profile, load_example

CASE = dict(mach=0.45, alt=1000.0, fuel=200.0)  # 구 기체 격자 중앙 부근 — 서버 트림 시험과 같은 점


def _sign(x):
    return (x > 0) - (x < 0)


@pytest.fixture(scope="module")
def basis():
    built = build_profile(load_example())
    return built, seed_basis(built, **CASE)


def test_basis_covers_three_rate_slots_and_matches_hand_design_signs(basis):
    built, out = basis
    assert out["ok"], (out["reason"], out["reason_text"])
    assert out["order"] == ["pitch_rate", "yaw_rate", "roll_rate"]
    hand = built.design_gains()
    for name in out["order"]:
        rec = out["rates"][name]
        assert rec["candidate"] is not None, (name, rec["reason"])
        k = rec["candidate"]["k"]
        if k != 0.0:
            assert _sign(k) == _sign(hand[rec["slot"]]), (name, k, hand[rec["slot"]])
    # 판정선(목표)은 결과가 동봉한다 — 화면이 재기술하지 않는다
    assert out["targets"]["zeta_sp"] == TuneTargets().zeta_sp
    assert out["e_ref_dps"] == 10.0
    assert out["case"]["mach"] == CASE["mach"]


def test_roll_candidate_places_the_low_order_pole_at_the_target(basis):
    _, out = basis
    rec = out["rates"]["roll_rate"]
    m = rec["model"]
    assert m["kind"] == "first_order" and m["a"] < 0.0
    lam = out["targets"]["roll_lambda"]
    k = rec["candidate"]["k"]
    if k == 0.0:
        assert -m["a"] >= lam  # 개루프 롤 감쇠가 이미 목표 이상 — 댐퍼 불요
    else:
        assert m["a"] + m["b"] * k == pytest.approx(-lam, rel=1e-9)


def test_pitch_candidate_satisfies_the_coefficient_matching_identity(basis):
    _, out = basis
    rec = out["rates"]["pitch_rate"]
    m = rec["model"]
    assert m["kind"] == "second_order" and m["states"] == ["w", "q"]
    k = rec["candidate"]["k"]
    zeta = out["targets"]["zeta_sp"]
    c1 = m["c1"] + m["c1_k"] * k
    c0 = m["c0"] + m["c0_k"] * k
    assert c1 > 0.0 and c0 > 0.0
    assert c1 == pytest.approx(2.0 * zeta * math.sqrt(c0), rel=1e-6)


def test_budget_measures_p_output_against_trim_remaining_deflection(basis):
    _, out = basis
    e_ref = math.radians(out["e_ref_dps"])
    for name, surface in (("pitch_rate", "elevon"), ("yaw_rate", "rudder"), ("roll_rate", "elevon")):
        b = out["rates"][name]["budget"]
        assert b["surface"] == surface and b["margin"] > 0.0
        k = out["rates"][name]["candidate"]["k"]
        assert b["delta_cmd"] == pytest.approx(abs(k) * e_ref, rel=1e-12)
        assert b["ok"] is (b["delta_cmd"] <= b["margin"])


def test_full_model_check_and_neighbors_share_the_tuner_yardstick(basis):
    _, out = basis
    for name in out["order"]:
        rec = out["rates"][name]
        full = rec["full"]
        assert isinstance(full["stable"], bool)
        assert full["achieved"] is None or math.isfinite(full["achieved"])
        if full["achieved"] is None:
            assert full["ok"] is None  # 못 잰 것을 미달로 위장하지 않는다
        ns = rec["neighbors"]
        if rec["candidate"]["k"] == 0.0:
            assert ns == []  # 배수가 전부 0 — 같은 줄 셋은 정보가 아니다
            continue
        assert [n["mult"] for n in ns] == list(NEIGHBOR_MULTS)
        mid = next(n for n in ns if n["mult"] == 1.0)
        assert mid["k"] == rec["candidate"]["k"]
        for n in ns:
            assert isinstance(n["stable"], bool)


def test_reported_metrics_are_measured_on_the_final_composition(basis):
    """조성 일관성이 이 기능의 중심 주장이다 — 보고 지표를 같은 자(axis_metrics, 최종 조성)로
    재계산해 대조한다. 요가 핵심이다: 프리픽스(롤 열림)로 재면 검증(schedmap)과 다른 수가 나온다."""
    from claw.common.contracts import TrimCase
    from claw.design.closure import axis_metrics
    from claw.trim import linearize, split_axes, trim

    built, out = basis
    ac = built.aircraft()
    tr = trim(ac, TrimCase("t", mach=CASE["mach"], alt=CASE["alt"], fuel=CASE["fuel"]))
    lon, lat = split_axes(linearize(ac, tr))
    rf = built.rate_filters()
    k = {out["rates"][n]["slot"]: out["rates"][n]["candidate"]["k"] for n in out["order"]}
    lat_gains = {"yaw.k_rate": k["yaw.k_rate"], "roll.k_rate": k["roll.k_rate"]}
    for name, lm_axis, gains, key in (
        ("pitch_rate", lon, {"pitch.k_rate": k["pitch.k_rate"]}, "zeta_sp"),
        ("yaw_rate", lat, lat_gains, "zeta_dr"),
        ("roll_rate", lat, lat_gains, "roll_lambda"),
    ):
        got = axis_metrics(lm_axis, gains, rf)[key]
        assert got == pytest.approx(out["rates"][name]["full"]["achieved"], rel=1e-9), name


def test_attitude_reuses_the_tuner_loopshaping_and_outer_is_a_timescale(basis):
    built, out = basis
    hand = built.design_gains()
    for group in ("pitch", "roll"):
        a = out["attitude"][f"{group}_att"]
        assert a["reason"] is not None
        assert a["passing"] is (a["reason"] in ("ok", "rescued"))  # 화면이 재기술하지 않게 동봉
        if a["kp"]:
            assert _sign(a["kp"]) == _sign(hand[f"{group}.kp"]), (group, a["kp"])
            assert a["wc0"] > 0.0 and a["wc_att"] > 0.0
    outer = out["outer"]
    assert outer["separation"] == 5.0
    if outer["wc_outer"] is not None:
        inner = [a["wc_att"] for a in out["attitude"].values() if a.get("wc_att")]
        assert outer["wc_outer"] == pytest.approx(min(inner) / 5.0)


def test_design_now_reports_the_document_gains(basis):
    built, out = basis
    dn = out["design_now"]
    assert dn is not None
    assert dn["gains"]["pitch.k_rate"] == built.design_gains()["pitch.k_rate"]


def test_unconverged_trim_reports_and_carries_no_candidates():
    built = build_profile(load_example())
    out = seed_basis(built, mach=0.05, alt=1000.0, fuel=200.0)
    assert out["ok"] is False and out["reason"] == REASON_BASIS_TRIM_FAILED
    assert reason_text(out["reason"])
    assert out["rates"] == {} and out["attitude"] == {}
    assert out["trim"]["converged"] is False


def test_match_zeta_2x2_solves_the_coefficient_matching_quadratic():
    A2 = np.array([[-1.0, 1.0], [-4.0, -2.0]])
    b2 = np.array([0.0, 5.0])
    k, roots = match_zeta_2x2(A2, b2, 0.7)
    assert k is not None and k in roots
    c1 = 3.0 - 5.0 * k  # c10 = −tr = 3, dc1/dk = −b₂[rate]
    c0 = 6.0 - 5.0 * k  # d0 = det = 6, dc0/dk = A[0,0]·b₂[1] − A[1,0]·b₂[0] = −5
    assert c1 > 0.0 and c0 > 0.0
    assert c1 == pytest.approx(2.0 * 0.7 * math.sqrt(c0), rel=1e-9)
    assert abs(k) == min(abs(r) for r in roots)
    assert _sign(k) == -_sign(float(b2[1]))  # 감쇠 부호 관례 — u = +k·rate가 감쇠를 더한다


def test_match_zeta_2x2_returns_none_when_no_stable_match_exists():
    # c1 = 0 고정(무감쇠 진동 + b가 레이트 행에 안 닿음) — 어떤 근도 c1 > 0을 못 만든다
    A2 = np.array([[0.0, 1.0], [-1.0, 0.0]])
    b2 = np.array([1.0, 0.0])
    k, roots = match_zeta_2x2(A2, b2, 0.7)
    assert k is None and roots == []
