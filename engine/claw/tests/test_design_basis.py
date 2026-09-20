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


def test_apply_seed_basis_assembles_a_full_design_that_builds_and_flies():
    """한 점 후보 → law.design 저장용 조립(검증 전) — 저장한 문서가 실제로 조립돼야 한다.

    빠른 탐색과 같은 조립 규칙(자세 kp·ki + 레이트 후보 + 자동조종 휴리스틱/문서 값)이고,
    스케줄 없는 문서에는 스케줄도 만든다(안 만들면 설계는 있는데 조립이 거부되는 반쪽 문서가 된다)."""
    import copy

    from claw.design.basis import apply_seed_basis
    from claw.fcl.assemble import assemble_law
    from claw.profile import build_profile, load_example

    blank = copy.deepcopy(load_example())
    blank["id"], blank["is_example"] = "blank-basis", False
    blank["law"]["design"] = blank["law"]["schedule"] = blank["law"]["alloc"] = None
    out = apply_seed_basis(build_profile(blank), **CASE)
    assert out["ok"], out.get("reason_text")
    prov = out["design"]["provenance"]
    assert prov["source"] == "seed_basis"
    assert "검증 전" in prov["note"]  # 한 점 후보 — quick_seed 채택 게이트 미통과를 문서에 남긴다
    assert out["schedule"] is not None and out["schedule_created"] is True

    cand = copy.deepcopy(blank)
    cand["law"]["design"] = out["design"]
    cand["law"]["schedule"] = out["schedule"]
    built = build_profile(cand)
    law = assemble_law(built)  # 조립이 실제로 선다
    assert law.schedule is not None
    gains = built.design_gains()
    hand = build_profile(load_example()).design_gains()
    for slot in ("pitch.k_rate", "yaw.k_rate", "roll.k_rate", "pitch.kp", "roll.kp"):
        assert gains[slot] != 0.0, slot
        assert (gains[slot] > 0) == (hand[slot] > 0), slot  # 부호는 손설계와 같아야 한다

    # 설계·스케줄이 이미 있는 문서 — 스케줄은 문서 것을 쓰고(새로 안 만듦) yaw 자세·washout은 문서 값 유지
    keep = apply_seed_basis(build_profile(load_example()), **CASE)
    assert keep["ok"] and keep["schedule_created"] is False and keep["schedule"] is None
    prev = build_profile(load_example()).doc["law"]["design"]["scas"]["yaw"]
    assert keep["design"]["scas"]["yaw"]["kp"] == prev["kp"]
    assert keep["design"]["scas"]["yaw"]["washout_tau"] == prev["washout_tau"]


def test_apply_seed_basis_stores_design_point_base_values():
    """저장값은 스케줄 배율을 나눈 **기저값**이다 — 조립이 배율을 도로 곱해 이 점에서 확인한
    후보로 돌아온다(quick_seed k0 나누기와 같은 규칙). 예제 스케줄은 이 점에서 배율이 1이
    아니므로 그대로 저장하면 조립된 법칙이 검증한 값의 배율배로 난다 — 리뷰가 잡은 결함을
    값 수준으로 핀한다."""
    from claw.design.basis import apply_seed_basis
    from claw.design.seed import _factor

    sched = load_example()["law"]["schedule"]
    f = _factor(sched, "pitch.k_rate", CASE["mach"])
    assert abs(f - 1.0) > 0.2  # 배율이 1이면 이 시험은 나누기를 못 본다 (픽스처 전제를 명시)
    keep = apply_seed_basis(build_profile(load_example()), **CASE)
    assert keep["ok"], keep.get("reason_text")
    for slot, group, key in (("pitch.k_rate", "pitch", "k_rate"), ("yaw.k_rate", "yaw", "k_rate"),
                             ("roll.k_rate", "roll", "k_rate"), ("pitch.kp", "pitch", "kp"),
                             ("roll.ki", "roll", "ki")):
        fac = _factor(sched, slot, CASE["mach"])
        rec = keep["basis"]["rates"].get(f"{group}_rate") if key == "k_rate" else None
        at_point = (rec["candidate"]["k"] if rec
                    else keep["basis"]["attitude"][f"{group}_att"][key])
        assert keep["design"]["scas"][group][key] == pytest.approx(at_point / fac, rel=1e-9), slot
    # provenance가 두 값(이 점의 확인값·저장 기저값)과 배율을 같이 말한다 — 화면·기록이 재계산하지 않게
    p = keep["design"]["provenance"]["slots"]["pitch.k_rate"]
    assert p["stored"] == keep["design"]["scas"]["pitch"]["k_rate"]
    assert p["schedule_factor"] == pytest.approx(f, rel=1e-9)
    assert p["k"] == pytest.approx(p["stored"] * p["schedule_factor"], rel=1e-9)


def test_basis_missing_slots_refuses_failed_attitude_not_just_zero_kp():
    """직행 저장 관문 — quick_seed의 앵커 제외(SLOT_DESIGN_FAILED)와 같은 선. kp == 0만 보면
    부호 반전 백오프 해(sign_mismatch — 이 플랜트에서 정궤환)가 0이 아니라는 이유로 통과한다."""
    from claw.design.basis import basis_missing_slots
    from claw.design.tune import REASON_CAPPED, REASON_OK, REASON_SIGN_MISMATCH

    out = {
        "order": ["pitch_rate", "yaw_rate", "roll_rate"],
        "rates": {"pitch_rate": {"candidate": {"k": 0.1}}, "yaw_rate": {"candidate": None},
                  "roll_rate": {"candidate": {"k": -0.2}}},
        "attitude": {"pitch_att": {"kp": -0.5, "reason": REASON_OK},
                     "roll_att": {"kp": 0.4, "reason": REASON_SIGN_MISMATCH}},
    }
    assert basis_missing_slots(out) == ["yaw_rate", "roll_att"]
    # 통과 사유(ok)와 물리 한계(capped — 작동하는 댐퍼를 냈다)는 거부 목록이 아니다
    out["rates"]["yaw_rate"]["candidate"] = {"k": 0.3}
    out["attitude"]["roll_att"] = {"kp": 0.4, "reason": REASON_CAPPED}
    assert basis_missing_slots(out) == []
    # 축퇴(kp 0)는 사유와 무관하게 못 쓴다
    out["attitude"]["pitch_att"] = {"kp": 0.0, "reason": REASON_OK}
    assert basis_missing_slots(out) == ["pitch_att"]
