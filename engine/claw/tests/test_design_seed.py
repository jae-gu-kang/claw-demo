"""초기 게인 빠른 탐색 — 게인이 없는 기체에 조종효율로 부호를, 앵커 튜닝으로 크기를 채운다 (05 §10)."""

import copy
import time

import pytest

import statistics

from claw.design.seed import (
    REASON_SEED_NO_ANCHOR,
    REASON_SEED_NO_GRID,
    REASON_SEED_THIN_ANCHORS,
    REASON_SEED_VERIFY_FAILED,
    SEED_SCHEDULED,
    SEED_SOURCE,
    quick_seed,
)
from claw.fcl.assemble import assemble_law
from claw.profile import build_profile, load_example

TUNED = ("pitch.k_rate", "yaw.k_rate", "roll.k_rate", "pitch.kp", "pitch.ki", "roll.kp", "roll.ki")


def _blank(doc=None):
    """게인이 비어 있는 새 기체 — 예제 플랜트에 법칙 설계·스케줄·할당 표만 뺀 것."""
    d = copy.deepcopy(doc or load_example())
    d["id"], d["is_example"] = "blank", False
    d["law"]["design"] = d["law"]["schedule"] = d["law"]["alloc"] = None
    return d


def _sign(x):
    return (x > 0) - (x < 0)


@pytest.fixture(scope="module")
def blank_seed():
    doc = _blank()
    t0 = time.perf_counter()
    out = quick_seed(build_profile(doc))
    return doc, out, time.perf_counter() - t0


def test_seed_signs_follow_the_example_hand_design_but_a_thin_roll_seed_is_not_adopted():
    """부호는 조종효율 B에서 온다 — 예제 손설계(피치 kp<0·롤 kp>0, 댐퍼 부호 제각각)와 전부 같다.

    그러나 예제 조성(요 워시아웃)에서는 롤 댐퍼가 한 앵커에서만 튜닝된다(나머지는 no_stable_gain). 그 한 점 값
    (손설계의 약 1/8)으로 스케줄을 세우면 세 앵커 모두 롤 λ가 목표 12의 1/4 안팎이라, 다시 탐색이 멀쩡한 손설계를
    덮게 된다 — 채택하지 않는다."""
    built = build_profile(load_example())
    hand = built.design_gains()
    out = quick_seed(built)
    for name in TUNED:
        assert _sign(out["slots"][name]["value"]) == _sign(hand[name]), (name, out["slots"][name])
    assert out["ok"] is False
    assert out["slots"]["roll.k_rate"]["reason"] == REASON_SEED_THIN_ANCHORS
    assert out["slots"]["roll.k_rate"]["anchors_used"] == 1 and out["reason_text"]
    # 문서에 스케줄이 있으면 그 규칙으로 되돌린다 — 새로 만들지 않는다
    assert out["schedule"] is None and out["schedule_created"] is False
    assert out["design"]["provenance"]["schedule"] == "document"


def test_blank_aircraft_gets_a_design_and_schedule_that_assemble(blank_seed):
    doc, out, elapsed = blank_seed
    assert out["ok"], (out["reason"], out["slots"])
    assert elapsed < 5.0  # 선형 확인만 — 수 초 안(실측 0.3~0.5 s)
    prov = out["design"]["provenance"]
    assert prov["source"] == SEED_SOURCE and prov["plant_fingerprint"] == build_profile(doc).plant_fingerprint
    assert prov["ok"] is True and len(prov["anchors"]) == len(out["anchors"]) >= 1
    assert all(prov["slots"][n]["sign_basis"].startswith("B[") for n in TUNED)
    # 새로 만든 스케줄 — q̄ 역비 규칙, 설계 마하는 중앙 앵커
    sched = out["schedule"]
    assert out["schedule_created"] and sched["rule"] == "qbar_inverse" and sched["scheduled"] == list(SEED_SCHEDULED)
    assert sched["m_design"] == round(out["anchors"][0]["mach"], 4) and sched["mach_grid"][0] > 0.0
    # 유도식이 없는 자동조종 자리는 출처에 그렇게 적힌다 — 조용히 물려주지 않는다
    ap_src = prov["autopilot"]
    assert ap_src["kp_alt"] == ap_src["kp_hdg"] == ap_src["kp_spd"] == "heuristic"
    assert ap_src["tau_alt"] == "registry_default"
    assert out["design"]["scas"]["yaw"]["kp"] == 0.0 and prov["yaw_attitude"] == "zero"

    cand = copy.deepcopy(doc)
    cand["law"]["design"], cand["law"]["schedule"] = out["design"], sched
    built = build_profile(cand)  # 스키마를 넘는다(provenance의 수는 전부 유한)
    assemble_law(built)
    assert built.fingerprint == build_profile(cand).fingerprint


def test_seed_values_invert_the_schedule_rule(blank_seed):
    """자리 값은 앵커마다 튜닝한 게인을 스케줄 배율로 나눈 값의 중앙값이다 — 배율은 조립한 게인 표에서 거꾸로 읽는다
    (시드의 배율 계산과 독립). 설계 마하가 중앙 앵커라 다른 앵커의 배율은 1이 아니다."""
    doc, out, _ = blank_seed
    cand = copy.deepcopy(doc)
    cand["law"]["design"], cand["law"]["schedule"] = out["design"], out["schedule"]
    tables = build_profile(cand).gain_tables()
    factors = []
    for name in TUNED:
        value = out["slots"][name]["value"]
        used = [a for a in out["anchors"] if a["slots"][name.split(".")[0] + ("_rate" if "k_rate" in name else "_att")]
                not in ("no_stable_gain", "degenerate", "margin_floor", "bandwidth_collapse", "na_no_crossover",
                        "seed_required", "sign_mismatch")]
        assert len(used) == out["slots"][name]["anchors_used"] >= 2
        f = [tables[name].interp(mach=a["mach"]) / value for a in used]
        factors += f
        assert statistics.median(abs(a["gains"][name]) / fi for a, fi in zip(used, f)) == pytest.approx(abs(value), rel=1e-9)
    assert any(abs(fi - 1.0) > 0.05 for fi in factors)


def test_seed_is_not_adopted_when_verification_says_no(blank_seed, monkeypatch):
    """채택 게이트 — 어느 앵커든 부호 방향 결함이면, 또는 모든 앵커에서 fail인 루프가 있으면 ok가 아니다."""
    import claw.design.seed as seed_mod

    doc, _, _ = blank_seed
    real = seed_mod.scheduled_margin_point

    def with_mismatch(*a, **kw):
        out = real(*a, **kw)
        out["roll_att"] = {**out["roll_att"], "sign_mismatch": True}
        return out

    monkeypatch.setattr(seed_mod, "scheduled_margin_point", with_mismatch)
    out = quick_seed(build_profile(doc))
    assert (out["ok"], out["reason"]) == (False, "sign_mismatch") and out["design"]["provenance"]["ok"] is False

    def pitch_rate_fails(*a, **kw):
        out = real(*a, **kw)
        out["pitch_rate"] = {**out["pitch_rate"], "status": "fail"}
        return out

    monkeypatch.setattr(seed_mod, "scheduled_margin_point", pitch_rate_fails)
    out = quick_seed(build_profile(doc))
    assert (out["ok"], out["reason"], out["failed_loops"]) == (False, REASON_SEED_VERIFY_FAILED, ["pitch_rate"])

    # 한 앵커에서만 fail이면 경고다 — 모든 앵커에서 fail인 루프만 채택을 막는다
    calls = []

    def fails_once(*a, **kw):
        out = real(*a, **kw)
        calls.append(1)
        if len(calls) == 1:
            out["pitch_rate"] = {**out["pitch_rate"], "status": "fail"}
        return out

    monkeypatch.setattr(seed_mod, "scheduled_margin_point", fails_once)
    out = quick_seed(build_profile(doc))
    assert len(calls) == len(out["anchors"]) >= 2
    assert out["ok"] is True and out["failed_loops"] == []
    assert any("pitch_rate" in w for w in out["warnings"])


def test_seed_signs_flip_with_the_control_derivatives(blank_seed):
    """롤·요 조종 미계수 부호를 뒤집은 기체 — 시드 부호가 따라 뒤집히고 피치는 그대로다."""
    _, base, _ = blank_seed
    doc = _blank()
    for coef, inp in (("Cl", "da"), ("Cn", "dr")):
        hits = [t for t in doc["aero"]["coefficients"][coef] if t["inputs"] == [inp]]
        assert hits
        for t in hits:
            t["k"] = -t["k"]
    out = quick_seed(build_profile(doc))
    assert out["ok"], (out["reason"], out["slots"])
    for name in TUNED:
        flipped = name.startswith(("roll.", "yaw."))
        assert _sign(out["slots"][name]["value"]) == (-1 if flipped else 1) * _sign(base["slots"][name]["value"]), name


def test_seed_names_what_is_missing():
    no_range = _blank()
    no_range["aero"]["db_ranges"]["mach"] = None
    out = quick_seed(build_profile(no_range))
    assert (out["ok"], out["reason"], out["design"]) == (False, REASON_SEED_NO_GRID, None)
    assert "db_ranges.mach" in out["reason_text"]

    heavy = _blank()
    heavy["mass"]["m_empty"] *= 40.0  # 1g조차 못 버티는 무게 — 격자에 엔벨로프 안 점이 없다
    out = quick_seed(build_profile(heavy))
    assert (out["ok"], out["reason"]) == (False, REASON_SEED_NO_ANCHOR)
