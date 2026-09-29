"""초기 게인 빠른 탐색 — 게인이 없는 기체에 조종효율로 부호를, 앵커 튜닝으로 크기를 채운다 (05 §10)."""

import copy
import time

import pytest

import statistics

from claw.common.constants import G0
from claw.design.seed import (
    REASON_SEED_NO_ANCHOR,
    REASON_SEED_NO_GRID,
    REASON_SEED_THIN_ANCHORS,
    REASON_SEED_VERIFY_FAILED,
    SEED_SCHEDULED,
    SEED_SOURCE,
    SEPARATION,
    WC_MATCH_RTOL,
    _autopilot,
    _inner_crossovers,
    quick_seed,
)
from claw.env import isa_atmosphere
from claw.fcl.assemble import assemble_law
from claw.profile import build_profile, load_example, load_showcase

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


def test_seed_signs_follow_the_example_hand_design_and_the_roll_damper_seeds_from_every_anchor():
    """부호는 조종효율 B에서 온다 — 예제 손설계(피치 kp<0·롤 kp>0, 댐퍼 부호 제각각)와 전부 같다.

    예제 조성(요 워시아웃)에서 종전 댐퍼 가드("극 전부 안정")는 워시아웃이 되돌려 놓은 느린 나선을 보고 롤 댐퍼를
    한 앵커만 남기고 꺼 버렸다(나머지 no_stable_gain) — 그 한 점 값(손설계의 약 1/8)이라 채택되지 않았다. 가드가
    비행성 기준 안의 나선을 면제한 뒤로는 세 앵커 모두에서 롤 댐퍼가 튜닝되고 시드가 채택된다."""
    built = build_profile(load_example())
    hand = built.design_gains()
    out = quick_seed(built)
    for name in TUNED:
        assert _sign(out["slots"][name]["value"]) == _sign(hand[name]), (name, out["slots"][name])
    assert out["ok"] is True, (out["reason"], out["slots"])
    assert out["slots"]["roll.k_rate"]["anchors_used"] == len(out["anchors"]) == 3
    assert all(out["slots"][n]["reason"] is None for n in TUNED)
    # 문서에 스케줄이 있으면 그 규칙으로 되돌린다 — 새로 만들지 않는다
    assert out["schedule"] is None and out["schedule_created"] is False
    assert out["design"]["provenance"]["schedule"] == "document"


def test_thin_anchor_seed_is_not_adopted(monkeypatch):
    """설계 실패 없이 튜닝한 앵커가 둘 미만인 자리는 채택하지 않는다 — 한 점 값으로 전 엔벨로프 스케줄을 세우지 않는다.

    예제 기체가 더는 이 모양을 내지 않아(위 테스트) 튜너 결과를 대역한다: 가운데 앵커를 뺀 둘에서 롤 댐퍼가
    no_stable_gain이면 롤 댐퍼는 한 앵커 값뿐이다. 같은 규칙(tune.failed_gain_slots)이 그 앵커들의 롤 자세 게인도
    뺀다 — 실패한 댐퍼 위에서 튜닝된 값이다."""
    import claw.design.seed as S

    real = S.tune_point
    calls = []

    def fake(*a, **kw):
        out = real(*a, **kw)
        calls.append(1)
        if len(calls) > 1:  # 첫 호출 = 가운데 앵커
            out["slots"]["roll_rate"] = {**out["slots"]["roll_rate"], "status": "infeasible",
                                         "reason": "no_stable_gain"}
        return out

    monkeypatch.setattr(S, "tune_point", fake)
    out = quick_seed(build_profile(load_example()))
    assert out["ok"] is False
    for name in ("roll.k_rate", "roll.kp", "roll.ki"):
        assert out["slots"][name]["reason"] == REASON_SEED_THIN_ANCHORS, (name, out["slots"][name])
        assert out["slots"][name]["anchors_used"] == 1 and out["slots"][name]["reason_text"]
    # 피치 자세는 두 앵커다 — 이관 9단계부터 앵커는 요구영역(trim_grid 초안 M0.3~0.55 · 200 kg) 기본 격자에서 나온다
    # (중앙 M0.4/100 m · 최저 q̄ M0.3/3000 m · 최고 q̄ M0.55/100 m). 한 앵커의 pitch_att 튜닝이 설계 실패라 그 앵커를 뺀다
    # (롤처럼 한 점으로 줄지는 않아 채택)
    assert out["slots"]["pitch.kp"]["reason"] is None and out["slots"]["pitch.kp"]["anchors_used"] == 2


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
    # DB 마하 범위가 없으면 옛 격자(요구영역 없는 기체)는 못 만든다. 요구영역이 있으면 격자는 요구영역에서 나오고 DB 범위
    # 미기재는 「모델 범위를 판단하지 않음」이다(opspace ModelRange) — 이관 9단계부터 이 사유는 요구영역 없는 기체의 것
    no_range = _blank()
    no_range["aero"]["db_ranges"]["mach"] = None
    no_range["mission_template"] = None
    out = quick_seed(build_profile(no_range))
    assert (out["ok"], out["reason"], out["design"]) == (False, REASON_SEED_NO_GRID, None)
    assert "db_ranges.mach" in out["reason_text"]

    heavy = _blank()
    heavy["mass"]["m_empty"] *= 40.0  # 1g조차 못 버티는 무게 — 격자에 엔벨로프 안 점이 없다
    out = quick_seed(build_profile(heavy))
    assert (out["ok"], out["reason"]) == (False, REASON_SEED_NO_ANCHOR)


# ── 자동조종 시간척도 — 가짜 자세 교차 ─────────────────────────────────────


def _att(wc, wcp=None, reason="ok"):
    """튜너 achieved의 자세 자리 모양 — wcp를 안 주면 목표 교차가 곧 루프 교차(한 번 지나는 루프)."""
    return {"wc_att": wc, "wcp": wc if wcp is None else wcp, "reason": reason}


def _showcase_blank():
    """쇼케이스 기체(S1)에서 설계·스케줄·확정 표를 뺀 것 — 빠른 탐색이 처음부터 잡는 모양."""
    d = load_showcase()
    d["id"] = "showcase-blank"
    d["law"]["design"] = d["law"]["schedule"] = d["law"]["gain_tables"] = None
    return d


def test_inner_crossover_takes_the_design_point_target_only_when_it_is_the_loop_crossover():
    """바깥 루프 시간척도 — ① 설계점의 목표 교차가 루프의 실측 이득교차면 그것 ② 아니면 목표가 루프 교차인 다른
    앵커들의 중앙값 ③ 그것도 없으면 설계점 루프의 실측 이득교차."""
    good = {"pitch_att": _att(1.03), "roll_att": _att(3.0)}
    # S1 중앙 앵커 모양 — 목표 0.0967은 장주기 공진이 만든 레이트 교차 ÷ 3이고 루프는 0.514에서 마지막으로 1을 지난다
    phantom = {"pitch_att": _att(0.0967, 0.514), "roll_att": _att(3.14)}
    lo, hi = {"pitch_att": _att(0.7285), "roll_att": _att(3.52)}, {"pitch_att": _att(1.607), "roll_att": _att(2.33)}

    wc, notes = _inner_crossovers(good, [lo, hi])
    assert wc == {"pitch": 1.03, "roll": 3.0} and notes == []  # ① — 다른 앵커를 섞지 않는다(예제 경로)

    wc, notes = _inner_crossovers(phantom, [lo, hi])
    assert wc["pitch"] == statistics.median([0.7285, 1.607]) and wc["roll"] == 3.14  # ②
    assert len(notes) == 1 and "0.0967" in notes[0] and "0.514" in notes[0] and "2곳" in notes[0]

    # 다른 앵커도 가짜면 빌려 오지 않는다 — 설계점 루프가 실제로 내는 대역폭 ③
    wc, notes = _inner_crossovers(phantom, [{"pitch_att": _att(0.1, 0.5), "roll_att": _att(3.5)}])
    assert wc["pitch"] == 0.514 and "실측 이득교차 0.514 rad/s로" in notes[0]

    # 설계 실패 자리 — 다른 앵커가 있으면 그 중앙값, 없으면 종전대로 None(_autopilot이 남은 자리로 잡는다)
    failed = {"pitch_att": _att(0.5, reason="margin_floor"), "roll_att": _att(3.0)}
    wc, notes = _inner_crossovers(failed, [lo, hi])
    assert wc["pitch"] == statistics.median([0.7285, 1.607]) and "margin_floor" in notes[0]
    assert _inner_crossovers(failed) == ({"pitch": None, "roll": 3.0}, [])

    # 같은 교차를 두 방법으로 잰 반올림 차이는 같은 수다 — 허용 안이면 ①
    wc, notes = _inner_crossovers({"pitch_att": _att(1.0, 1.0 + 0.5 * WC_MATCH_RTOL), "roll_att": _att(3.0)})
    assert wc["pitch"] == 1.0 and notes == []
    # 교차를 못 잰 자리(부호 모름 — wc_att·wcp가 없다)는 쓸 교차가 없다
    wc, _ = _inner_crossovers({"pitch_att": {"reason": "seed_sign_ambiguous"}, "roll_att": _att(3.0)})
    assert wc["pitch"] is None


def test_showcase_quick_seed_sizes_a_live_autopilot():
    """S1 빠른 탐색 — 중앙 앵커(M0.1305/해면/연료 25)의 피치 자세 목표가 장주기 공진이 만든 가짜 교차(0.097 rad/s)라
    종전에는 자동조종이 kp_spd 0 · ki_spd 1e-4 · kp_hdg 0.088로 나왔다(웹 기본 미션에서 발사 8 s 만에 접지·추락).
    같은 점의 산출 근거 직행(한 점 — 그 점의 목표는 루프 교차다)과 같은 크기의 바깥 루프여야 한다."""
    from claw.design.basis import apply_seed_basis

    built = build_profile(_showcase_blank())
    out = quick_seed(built)
    assert out["ok"], (out["reason"], out["slots"])
    ap = out["design"]["autopilot"]
    assert ap["kp_spd"] > 0.0 and ap["ki_spd"] > 0.0
    c = out["anchors"][0]
    ref = apply_seed_basis(built, c["mach"], c["alt"], c["fuel"])
    assert ref["ok"] and ref["basis"]["outer"]["notes"] == [], ref["basis"]["outer"]
    for k in ("kp_spd", "ki_spd", "kp_alt", "ki_alt", "kp_hdg"):
        ratio = ap[k] / ref["design"]["autopilot"][k]
        assert 0.5 < ratio < 2.0, (k, ap[k], ref["design"]["autopilot"][k])
    # 자동조종은 자동 설계가 다시 잡지 않는다 — 대역폭을 어디서 잡았는지가 문서 출처에 남는다
    assert out["design"]["provenance"]["autopilot_notes"] == out["autopilot_notes"]


@pytest.mark.parametrize("which", ["legacy", "shipped"])
def test_example_autopilot_keeps_the_centre_anchor_timescale(monkeypatch, which):
    """예제 — 구 기체 픽스처(테스트의 예제 자리)와 제품에 실린 예제 둘 다. 세 앵커 모두 목표 교차가 루프 교차라,
    자동조종은 종전 그대로 중앙 앵커의 느린 자세 교차 ÷ SEPARATION에서 나온다(가짜 교차 규칙이 예제 값을 한
    비트도 바꾸지 않는다)."""
    import claw.design.seed as seed_mod
    from claw.profile import load_shipped_example

    tuned = []
    real = seed_mod.tune_point

    def spy(*a, **kw):
        tuned.append(real(*a, **kw))
        return tuned[-1]

    monkeypatch.setattr(seed_mod, "tune_point", spy)
    out = quick_seed(build_profile(_blank(load_shipped_example() if which == "shipped" else None)))
    assert out["ok"] and len(tuned) == len(out["anchors"]) == 3, (out["reason"], out["anchors"])
    for r in tuned:
        for slot in ("pitch_att", "roll_att"):
            a = r["achieved"][slot]
            assert abs(a["wcp"] - a["wc_att"]) <= WC_MATCH_RTOL * a["wc_att"], (slot, a)  # 전제 — 모두 ①
    centre = tuned[0]["achieved"]
    w = min(centre["pitch_att"]["wc_att"], centre["roll_att"]["wc_att"]) / SEPARATION
    c = out["anchors"][0]
    v = c["mach"] * isa_atmosphere(c["alt"]).a
    assert out["design"]["autopilot"]["kp_hdg"] == w * v / G0
    assert out["autopilot_notes"] == []


def test_autopilot_says_so_when_the_speed_gain_formula_goes_negative():
    """속도 kp 식 (2ζω + A_uu)/b가 음수면 0으로 깎되 조용히 하지 않는다 — S1의 kp_spd 0은 메모 없이 나왔다."""
    import types

    from claw.common.contracts import TrimCase
    from claw.trim import linearize, split_axes, trim

    built = build_profile(_showcase_blank())
    case = TrimCase("M0.1305_h0_f25", mach=0.1305, alt=0.0, fuel=25.0)
    tr = trim(built.aircraft(), case, fingerprint=built.plant_fingerprint)
    assert tr.converged
    lon, _ = split_axes(linearize(built.aircraft(), tr))
    centre = types.SimpleNamespace(case=case)
    slow, _, notes = _autopilot(built, centre, lon, {"pitch": 0.0967, "roll": 3.14}, None)  # 종전 S1 입력
    assert slow["kp_spd"] == 0.0 and slow["ki_spd"] > 0.0
    assert len(notes) == 1 and "0으로" in notes[0] and "−A_uu" in notes[0], notes
    live, _, notes = _autopilot(built, centre, lon, {"pitch": 1.17, "roll": 3.14}, None)
    assert live["kp_spd"] > 0.0 and notes == []


# ── 이관 9단계 — 앵커는 요구영역의 기본 격자(연료 한 층)에서 ─────────────────────────────────────────────
def test_seed_anchors_come_from_the_region_base_grid_at_the_middle_fuel_layer():
    """제품 예제 — 요구영역 M0.10~0.28 · 100/1000/3000 m, 기본 격자 연료 층 25 kg(연료 범위 10~50의 가운데에 가장 가까운 층).
    종전에는 coarse_grid(0/1000/3000/5000 m를 운용 고도로 거름 × fuel_max·0.5)였다."""
    from claw.opspace import region_of
    from claw.profile import load_shipped_example

    built = build_profile(_blank(load_shipped_example()))
    region = region_of(built.doc)
    out = quick_seed(built)
    assert out["anchors"]
    for a in out["anchors"]:
        assert a["fuel"] == 25.0 and a["alt"] in region.grid["alts"]
        assert region.classify(a["mach"], a["alt"], a["fuel"]) is None  # 요구영역 안


def test_seed_without_a_region_keeps_the_legacy_grid():
    doc = _blank()
    doc["mission_template"] = None
    built = build_profile(doc)
    from claw.opspace import region_of

    assert region_of(built.doc) is None
    out = quick_seed(built)
    assert out["anchors"] and all(a["fuel"] == built.doc["mass"]["fuel_max"] * 0.5 for a in out["anchors"])
