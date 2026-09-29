"""스키마 v3 (05 §11.13 이관 11·12단계) — 절 재편·업그레이더·해석 설정 지문·트림 여유 판정선·탑재 구성 자리.

- operating 절 폐지(운용 고도 = 요구영역 고도), trim 절 → solver(해석 설정 — 플랜트 지문 밖·계보 지문 안) +
  criteria.trim_margin(판정선), mass.loadings 자리, mission_template.envelope.scan_* 폐지
- v2 → v3 업그레이더: 옮기고, 버린 값은 알리고, 멱등이고, 다른 칸은 건드리지 않는다
- 트림 설정이 바뀌면 트림 키·δe_trim 도출이 낡는다(05 §11.8), 판정선이 바뀌면 트림을 다시 풀지 않고 여유 판정만 바뀐다
"""

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from claw.common.contracts import TrimCase
from claw.profile import (ProfileError, SCHEMA_VERSION, build_profile, load_example, trim_fingerprint,
                          upgrade_document, validate_document)
from claw.profile.form import form_spec
from claw.profile.schema import DEFAULT_RESID_TOL, document_warnings


def _v2(doc=None):
    """v3 문서 → 옛 v2 원문 모양(업그레이더 입력). 예제의 옛 절 값(v2 파일과 같은 값)을 되살린다."""
    d = copy.deepcopy(doc or load_example())
    out = {}
    for k, v in d.items():
        if k == "solver":
            out["operating"] = {"alt_min": None, "alt_max": None}
            out["ground"] = d["ground"]
            out["trim"] = {"alpha_bounds": v["trim_alpha_bounds"], "alpha_margin": 0.035}
            continue
        if k == "ground":
            continue
        out[k] = v
    out["schema_version"] = 2
    out["mass"] = {k: v for k, v in out["mass"].items() if k != "loadings"}
    if out.get("mission_template"):
        out["mission_template"]["envelope"].update(scan_mach={"from": 0.2, "to": 0.7, "step": 0.05},
                                                   scan_alt=[0.0, 1000.0])
    return out


# ── 절 재편 ────────────────────────────────────────────────────────────────


def test_version_three_sections():
    doc = load_example()
    assert SCHEMA_VERSION == 3 and doc["schema_version"] == 3
    assert "operating" not in doc and "trim" not in doc
    assert doc["solver"] == {"trim_alpha_bounds": [-0.1, 0.35], "resid_tol": 1e-4}
    assert doc["mass"]["loadings"] is None
    assert set(doc["mission_template"]["envelope"]) == {"alt", "fuel"}


@pytest.mark.parametrize("section", ["operating", "trim"])
def test_old_sections_are_unknown_keys(section):
    doc = load_example()
    doc[section] = {}
    with pytest.raises(ProfileError) as ei:
        validate_document(doc)
    assert ei.value.path == f"/{section}"


def test_v2_document_is_rejected_by_the_validator_but_upgraded_by_the_upgrader():
    with pytest.raises(ProfileError) as ei:
        validate_document(_v2())
    assert ei.value.path == "/schema_version"
    new, _ = upgrade_document(_v2())
    assert validate_document(new) == load_example()


@pytest.mark.parametrize("path,mutate", [
    ("/solver/resid_tol", lambda s: s.__setitem__("resid_tol", 0.0)),
    ("/solver/resid_tol", lambda s: s.__setitem__("resid_tol", None)),
    ("/solver/trim_alpha_bounds", lambda s: s.__setitem__("trim_alpha_bounds", [0.3, 0.1])),
    ("/solver/extra", lambda s: s.__setitem__("extra", 1.0)),
])
def test_solver_is_validated_with_paths(path, mutate):
    doc = load_example()
    mutate(doc["solver"])
    with pytest.raises(ProfileError) as ei:
        validate_document(doc)
    assert ei.value.path == path


def test_loadings_slot():
    doc = load_example()
    doc["mass"]["loadings"] = [{"id": "eo", "name": "EO 짐벌", "payload_kg": 20, "cg": [0.1, 0, 0]},
                               {"id": "empty", "name": "빈 동체", "payload_kg": 0.0, "cg": None}]
    out = validate_document(doc)["mass"]["loadings"]
    assert out[0] == {"id": "eo", "name": "EO 짐벌", "payload_kg": 20.0, "cg": [0.1, 0.0, 0.0]}
    assert out[1]["cg"] is None
    for bad, path in [
        ([{"id": "a", "name": "a", "payload_kg": -1.0, "cg": None}], "/mass/loadings/0/payload_kg"),
        ([{"id": "a", "name": "a", "payload_kg": 1.0, "cg": None}] * 2, "/mass/loadings/1/id"),
        ([{"id": "a b", "name": "a", "payload_kg": 1.0, "cg": None}], "/mass/loadings/0/id"),
        ([{"id": "a", "name": "a", "payload_kg": 1.0, "cg": [0.0, 0.0]}], "/mass/loadings/0/cg"),
        ([{"id": "a", "name": "a", "payload_kg": 1.0}], "/mass/loadings/0/cg"),
        ({}, "/mass/loadings"),
    ]:
        doc["mass"]["loadings"] = bad
        with pytest.raises(ProfileError) as ei:
            validate_document(doc)
        assert ei.value.path == path, bad


def test_scan_fields_are_gone_from_the_mission_template():
    doc = load_example()
    doc["mission_template"]["envelope"]["scan_alt"] = [0.0]
    with pytest.raises(ProfileError) as ei:
        validate_document(doc)
    assert ei.value.path == "/mission_template/envelope/scan_alt"


# ── 지문 ─────────────────────────────────────────────────────────────────


def _built(doc, variant=None):
    return build_profile(validate_document(doc), variant, validated=True)


def test_solver_is_outside_the_plant_fingerprint_but_inside_the_lineage_and_trim_key():
    """풀이 설정은 기체가 아니다 — 플랜트 지문은 그대로, 계보 지문·트림 키는 바뀐다(05 §11.8)."""
    base = _built(load_example())
    doc = load_example()
    doc["solver"]["resid_tol"] = 1e-5
    b = _built(doc)
    assert b.plant_fingerprint == base.plant_fingerprint
    assert b.fingerprint != base.fingerprint
    assert b.trim_fingerprint != base.trim_fingerprint
    assert b.trim_fingerprint == trim_fingerprint(b.doc)


def test_loadings_do_not_change_the_plant_fingerprint():
    """구성은 자리만 있다 — 트림이 보지 않으므로 적었다고 δe_trim 표가 낡지 않는다(계보에는 든다)."""
    base = _built(load_example())
    doc = load_example()
    doc["mass"]["loadings"] = [{"id": "eo", "name": "EO", "payload_kg": 20.0, "cg": None}]
    b = _built(doc)
    assert b.plant_fingerprint == base.plant_fingerprint and b.trim_fingerprint == base.trim_fingerprint
    assert b.fingerprint != base.fingerprint and b.loadings_declared == 1


def test_trim_margin_is_a_judged_criteria_group_outside_the_fingerprints():
    """판정선은 기준이다 — 지문 밖(트림·표가 낡지 않는다), 판정 기준 지문 안."""
    base = _built(load_example())
    doc = load_example()
    doc["criteria"] = {"trim_margin": {"sat_frac": 0.9}}
    b = _built(doc)
    assert (b.fingerprint, b.plant_fingerprint, b.trim_fingerprint) == \
        (base.fingerprint, base.plant_fingerprint, base.trim_fingerprint)
    assert b.eval_criteria.judgement_fingerprint() != base.eval_criteria.judgement_fingerprint()
    assert b.trim_margin == {"sat_frac": 0.9, "thr_margin": 0.02, "alpha_margin": 0.035}


def test_trim_margin_values_are_validated_with_paths():
    doc = load_example()
    for bad in ({"sat_frac": 1.5}, {"thr_margin": -0.1}, {"alpha_margin": "x"}, {"nope": 1.0}):
        doc["criteria"] = {"trim_margin": bad}
        with pytest.raises(ProfileError) as ei:
            validate_document(doc)
        assert ei.value.path.startswith("/criteria/trim_margin"), bad


# ── 트림 범위·판정선 ─────────────────────────────────────────────────────


def test_trim_margin_defaults_are_the_v2_constants():
    """값의 출처만 옮긴다 — 도구 기본값은 v2 상수·예제 값 그대로(조용한 판정 변화 금지)."""
    from claw.pipeline.criteria import GainEvalCriteria, TRIM_MARGIN_LABELS

    tm = GainEvalCriteria().trim_margin
    assert (tm.sat_frac, tm.thr_margin, tm.alpha_margin) == (0.95, 0.02, 0.035)
    assert DEFAULT_RESID_TOL == 1e-4
    assert set(TRIM_MARGIN_LABELS) == {"sat_frac", "thr_margin", "alpha_margin"}


def test_trim_bounds_carry_solver_and_criteria():
    doc = load_example()
    doc["solver"] = {"trim_alpha_bounds": [-0.2, 0.3], "resid_tol": 2e-4}
    doc["criteria"] = {"trim_margin": {"sat_frac": 0.9, "thr_margin": 0.05, "alpha_margin": 0.02}}
    tb = _built(doc).trim_bounds
    assert tb["alpha"] == (-0.2, 0.3) and tb["resid_tol"] == 2e-4
    assert (tb["sat_frac"], tb["thr_margin"], tb["alpha_margin"]) == (0.9, 0.05, 0.02)


def test_trim_refuses_bounds_without_judgement_lines():
    from claw.trim import trim_level

    ac = _built(load_example()).aircraft()
    ac.trim_bounds = {k: v for k, v in ac.trim_bounds.items() if k != "sat_frac"}
    with pytest.raises(ValueError, match="sat_frac"):
        trim_level(ac, TrimCase(name="c", mach=0.4, alt=1000.0, fuel=200.0))


def test_resid_tol_decides_convergence():
    from claw.trim import trim_level

    case = TrimCase(name="c", mach=0.4, alt=1000.0, fuel=200.0)
    assert trim_level(_built(load_example()).aircraft(), case).converged
    doc = load_example()
    doc["solver"]["resid_tol"] = 1e-300  # 풀이기가 닿을 수 없는 허용치 — 잔차 판정이 이 값을 읽는다
    tr = trim_level(_built(doc).aircraft(), case)
    assert not tr.flags["residual_ok"] and not tr.converged


def test_changing_the_judgement_line_rejudges_without_retrimming():
    """판정선을 바꾸면 같은 트림 해의 여유 판정만 바뀐다 — 트림 때 찍힌 플래그가 아니라 지금 기준으로 잰다(05 §11.3)."""
    from claw.opspace.verdict import VerdictContext, margin_of
    from claw.trim import trim_level

    built = _built(load_example())
    tr = trim_level(built.aircraft(), TrimCase(name="c", mach=0.4, alt=1000.0, fuel=200.0))
    assert margin_of(tr, built.trim_bounds)["status"] == "met"
    doc = load_example()
    thr = float(tr.control.throttle[0])
    doc["criteria"] = {"trim_margin": {"sat_frac": thr * 0.5, "alpha_margin": 0.4}}
    strict = _built(doc)
    m = margin_of(tr, strict.trim_bounds)
    assert m["status"] == "short" and {"throttle_high", "alpha_margin"} <= set(m["reasons"])
    assert tr.flags["saturation_ok"] and tr.flags["alpha_margin_ok"]  # 트림 결과는 그대로다
    assert VerdictContext.from_profile(strict).trim_bounds["sat_frac"] == thr * 0.5


def test_condition_verdict_carries_the_mass_condition():
    """탑재 구성은 계산에 들지 않는다 — 판정이 그렇다고 말하고 CG는 늘 미지원이다(통과로 세지 않는다)."""
    from claw.opspace.verdict import VerdictContext, condition_verdict, pre_trim_verdict
    from claw.trim import trim_level

    doc = load_example()
    doc["mass"]["loadings"] = [{"id": "eo", "name": "EO", "payload_kg": 20.0, "cg": [0.1, 0.0, 0.0]}]
    built = _built(doc)
    ctx = VerdictContext.from_profile(built)
    tr = trim_level(built.aircraft(), TrimCase(name="c", mach=0.4, alt=1000.0, fuel=200.0))
    v = condition_verdict(tr, ctx)
    assert v["mass_condition"] == {"loading": None, "loadings_declared": 1, "cg_supported": False}
    assert pre_trim_verdict("model_gap", ctx)["mass_condition"] == v["mass_condition"]
    ctx0 = VerdictContext.from_profile(_built(load_example()))
    assert condition_verdict(tr, ctx0)["mass_condition"]["loadings_declared"] == 0


# ── δe_trim 낡음 — 트림 설정 ────────────────────────────────────────────


def _derived(doc, prov):
    doc["law"]["alloc"] = {"resv_frac": 0.5, "de_trim": {
        "source": "derived", "table": {"axes": {"mach": [0.2, 0.6]}, "data": [0.1, 0.01], "extrapolate": "clip"},
        "provenance": prov}}
    return _built(doc)


def test_de_trim_goes_stale_when_the_solver_changes():
    base = _built(load_example())
    prov = {"plant_fingerprints": [base.plant_fingerprint], "solver": base.solver, "solvers": [base.solver]}
    assert not _derived(load_example(), prov).de_trim_stale
    doc = load_example()
    doc["solver"]["trim_alpha_bounds"] = [-0.1, 0.30]
    b = _derived(doc, prov)
    assert b.plant_fingerprint == base.plant_fingerprint and b.de_trim_stale  # 플랜트는 같아도 트림 설정이 다르다
    with pytest.raises(ProfileError):
        b.alloc_trim_table()
    # 풀이 설정 기록이 없는 옛 도출 — 어느 설정으로 풀었는지 모른다
    assert _derived(load_example(), {"plant_fingerprints": [base.plant_fingerprint]}).de_trim_stale
    # 판정선은 도출과 무관하다 — 기준을 바꿔도 낡지 않는다
    doc = load_example()
    doc["criteria"] = {"trim_margin": {"alpha_margin": 0.1}}
    assert not _derived(doc, prov).de_trim_stale


def test_derive_records_the_solver():
    from claw.profile.derive import derive_de_trim

    built = _built(load_example())
    out = derive_de_trim(built, machs=[0.3, 0.4], alts=[1000.0], fuel_fracs=(0.5,), check_step=0.05)
    prov = out["alloc"]["de_trim"]["provenance"]
    assert prov["solver"] == built.solver and prov["solvers"] == [built.solver]
    doc = load_example()
    doc["law"]["alloc"] = out["alloc"]
    assert not _built(doc).de_trim_stale


# ── 경고 ─────────────────────────────────────────────────────────────────


def test_low_search_bound_warning_points_at_the_solver_and_reads_the_criteria():
    doc = load_example()
    hi_stall = max(doc["stall"]["table"]["data"])
    doc["solver"]["trim_alpha_bounds"] = [-0.1, hi_stall - 0.05]
    assert [w["path"] for w in document_warnings(validate_document(doc))] == ["/solver/trim_alpha_bounds/1"]
    doc["criteria"] = {"trim_margin": {"alpha_margin": 0.06}}  # 판정 한계가 탐색 상한 아래로 — 가리는 것이 없다
    assert document_warnings(validate_document(doc)) == []


# ── 업그레이더 ───────────────────────────────────────────────────────────


def test_upgrade_moves_solver_and_drops_screen_fields_idempotently():
    v2 = _v2()
    before = copy.deepcopy(v2)
    new, notes = upgrade_document(v2)
    assert v2 == before  # 입력을 고치지 않는다
    assert new["schema_version"] == 3 and "trim" not in new and "operating" not in new
    assert new["solver"] == {"trim_alpha_bounds": [-0.1, 0.35], "resid_tol": DEFAULT_RESID_TOL}
    assert list(new)[list(new).index("ground") + 1] == "solver"  # trim이 있던 자리(저장본 순서를 지킨다)
    assert new["mass"]["loadings"] is None
    assert "scan_mach" not in new["mission_template"]["envelope"]
    assert new.get("criteria") == before.get("criteria")  # 기본값 여유는 문서에 굳히지 않는다
    paths = [n["path"] for n in notes]
    assert "/mission_template/envelope" in paths and "/trim/alpha_margin" in paths
    assert "/operating" not in paths  # 값이 없던 운용 고도는 말할 것이 없다
    # 멱등 — v3는 그대로
    again, notes2 = upgrade_document(new)
    assert again == new and notes2 == []
    # 그 밖의 칸은 그대로다
    keep = [k for k in before if k not in ("schema_version", "trim", "operating", "mass", "mission_template")]
    assert all(new[k] == before[k] for k in keep)


def test_upgrade_moves_a_non_default_alpha_margin_into_the_criteria():
    v2 = _v2()
    v2["trim"]["alpha_margin"] = 0.05
    v2["criteria"] = {"margin": {"pm_min_deg": 40.0}}
    new, notes = upgrade_document(v2)
    assert new["criteria"] == {"margin": {"pm_min_deg": 40.0}, "trim_margin": {"alpha_margin": 0.05}}
    assert _built(new).trim_bounds["alpha_margin"] == 0.05
    assert any(n["path"] == "/trim/alpha_margin" and "0.05" in n["message"] for n in notes)


@pytest.mark.parametrize("region_alt,op,word", [
    (None, {"alt_min": 0.0, "alt_max": 3500.0}, "옮길 자리가 없다"),
    ([0.0, 3500.0], {"alt_min": 0.0, "alt_max": 3500.0}, "잃은 것이 없다"),
    ([200.0, 3000.0], {"alt_min": 0.0, "alt_max": 3500.0}, "잃었다"),
    ([200.0, 3000.0], {"alt_min": None, "alt_max": 3000.0}, "잃은 것이 없다"),
])
def test_upgrade_says_whether_the_operating_altitudes_were_covered(region_alt, op, word):
    v2 = _v2()
    v2["operating"] = op
    v2["operating_region"] = None if region_alt is None else {
        "mach": [0.2, 0.6], "alt": region_alt, "fuel": [0.0, 400.0], "boundary": None,
        "base_grid": {"n_mach": 5, "alts": [region_alt[0]], "fuels": [200.0]}}
    new, notes = upgrade_document(v2)
    validate_document(new)
    [note] = [n for n in notes if n["path"] == "/operating"]
    assert word in note["message"]


def test_upgrade_rewrites_variant_patches():
    v2 = _v2()
    v2["variants"] = [{"id": "narrow", "name": "좁은 탐색", "patch": {
        "/trim/alpha_bounds": [-0.1, 0.30], "/trim/alpha_margin": 0.05, "/operating/alt_max": 2000.0,
        "/mission_template/envelope/scan_alt": [0.0], "/mass/m_empty": 1000.0}}]
    new, notes = upgrade_document(v2)
    doc = validate_document(new)
    assert doc["variants"][0]["patch"] == {"/solver/trim_alpha_bounds": [-0.1, 0.30], "/mass/m_empty": 1000.0}
    lost = {n["path"] for n in notes}
    assert {"/variants/narrow/patch/trim/alpha_margin", "/variants/narrow/patch/operating/alt_max",
            "/variants/narrow/patch/mission_template/envelope/scan_alt"} <= lost


def test_upgrade_says_derived_tables_go_stale_without_a_region_record():
    """요구영역 없이 돈 v2 도출은 검사 고도를 운용 고도 절로 걸렀다 — v3에는 그 절이 없어 다시 찍지 않는다(낡음·사유)."""
    v2 = _v2()
    v2["law"]["alloc"] = {"resv_frac": 0.5, "de_trim": {
        "source": "derived", "table": {"axes": {"mach": [0.2, 0.6]}, "data": [0.1, 0.01], "extrapolate": "clip"},
        "provenance": {"plant_fingerprints": ["x"]}}}
    new, notes = upgrade_document(v2)
    [note] = [n for n in notes if n["path"] == "/law/alloc/de_trim"]
    assert "요구영역" in note["message"] and "operating" in note["message"]
    assert _built(new).de_trim_stale


# ── v2 계보 도장 다시 찍기 (실제 v1.67 파일) ─────────────────────────────


_FIX = Path(__file__).resolve().parent / "fixtures"


def _v2_file(name):
    """v1.67(3a2bd4c) 엔진이 낸 v2 예제 파일 그대로 — delta_demo_v2.json · showcase_delta_v2.json."""
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


def _all_build(doc):
    """기본형·형상 변형 전부에서 δe_trim 표와 확정 게인 표가 낡음 거부 없이 조립되는가."""
    v = validate_document(doc)
    for vid in [None] + [item["id"] for item in v["variants"] or []]:
        b = build_profile(v, vid, validated=True)
        b.alloc_trim_table()
        b.confirmed_gain_tables()
        assert not b.de_trim_stale and not b.gain_tables_stale, vid


def test_v2_fingerprints_are_reproduced_from_the_upgraded_document():
    """증명의 바탕 — 올린 문서에서 옛 정의로 다시 잰 v2 지문이 v1.67이 파일에 찍은 도장과 같다."""
    from claw.profile.fingerprint import gain_tables_basis_fingerprint
    from claw.profile.schema import _v2_configs, _v2_plant_fp

    for name in ("delta_demo_v2.json", "showcase_delta_v2.json"):
        raw = _v2_file(name)
        cfgs = _v2_configs(raw, validate_document(upgrade_document(raw)[0]))
        prov = raw["law"]["alloc"]["de_trim"]["provenance"]
        assert [_v2_plant_fp(c["shadow"]) for c in cfgs] == prov["plant_fingerprints"], name
        if raw["law"].get("gain_tables") is not None:
            assert gain_tables_basis_fingerprint(cfgs[0]["shadow"]) == \
                raw["law"]["gain_tables"]["provenance"]["basis_fingerprint"]


@pytest.mark.parametrize("name,shipped", [("delta_demo_v2.json", "example"), ("showcase_delta_v2.json", "showcase")])
def test_upgraded_v2_example_is_the_shipped_v3_law_and_builds(name, shipped):
    """v2에서 최신이던 도출 δe_trim·확정 게인 표는 올린 뒤에도 조립된다 — 법칙 절이 배포된 v3 예제와 같다."""
    from claw.profile import load_showcase
    from claw.profile.document import load_shipped_example

    raw = _v2_file(name)
    new, notes = upgrade_document(raw)
    ref = load_shipped_example() if shipped == "example" else load_showcase()
    assert validate_document(new)["law"] == ref["law"]
    _all_build(new)
    msgs = {n["path"]: n["message"] for n in notes}
    assert "다시 찍었다" in msgs["/law/alloc/de_trim"]
    if raw["law"].get("gain_tables") is not None:
        assert "다시 찍었다" in msgs["/law/gain_tables"]
    json.dumps(notes, ensure_ascii=False)


def test_restamp_keeps_v2_staleness():
    """v2에서 이미 낡은 표는 올려도 낡음이다 — 도장을 새로 찍어 낡음을 덮지 않는다."""
    raw = _v2_file("showcase_delta_v2.json")
    raw["law"]["alloc"]["de_trim"]["provenance"]["plant_fingerprints"] = ["0000000000000000"]
    raw["law"]["gain_tables"]["provenance"]["basis_fingerprint"] = "0000000000000000"
    new, notes = upgrade_document(raw)
    b = _built(new)
    assert b.de_trim_stale and b.gain_tables_stale
    msgs = {n["path"]: n["message"] for n in notes}
    assert "v2에서 이미 낡은" in msgs["/law/alloc/de_trim"] and "v2에서 이미 낡은" in msgs["/law/gain_tables"]


def test_restamp_keeps_only_the_fresh_variant():
    """기본형은 최신·형상 변형은 v2에서 낡았던 표 — 기본형만 새 지문으로, 변형은 낡음 그대로이고 그렇다고 적는다."""
    raw = _v2_file("delta_demo_v2.json")
    prov = raw["law"]["alloc"]["de_trim"]["provenance"]
    prov["plant_fingerprints"] = prov["plant_fingerprints"][:1]
    new, notes = upgrade_document(raw)
    assert not _built(new).de_trim_stale and _built(new, "eoir").de_trim_stale
    [note] = [n for n in notes if n["path"] == "/law/alloc/de_trim"]
    assert "eoir" in note["message"]


def test_region_less_documents_keep_their_derived_table_stale():
    raw = _v2_file("delta_demo_v2.json")
    raw["law"]["alloc"]["de_trim"]["provenance"]["region"] = None  # 요구영역 없이 돈 도출(운용 고도로 거른 고도)
    new, notes = upgrade_document(raw)
    assert _built(new).de_trim_stale
    with pytest.raises(ProfileError, match="스키마"):
        _built(new).alloc_trim_table()


def test_variant_patch_tables_are_restamped_or_noted():
    """형상 변형 패치가 든 표도 같은 규칙 — 최신이면 패치 안의 도장을, 기록 안쪽을 따로 고친 패치는 증명하지 않는다."""
    raw = _v2_file("delta_demo_v2.json")
    de = copy.deepcopy(raw["law"]["alloc"]["de_trim"])
    raw["variants"][0]["patch"]["/law/alloc/de_trim"] = de  # 변형이 표를 통째로 든다 — 기록은 도출 그대로(최신)
    new, notes = upgrade_document(raw)
    _all_build(new)
    msgs = {n["path"]: n["message"] for n in notes}
    assert "다시 찍었다" in msgs["/variants/eoir/patch/law/alloc/de_trim"]
    # 기록 안쪽 칸을 따로 고친 패치 — 섞인 기록은 증명하지 않는다(낡음·사유)
    raw = _v2_file("delta_demo_v2.json")
    raw["variants"][0]["patch"]["/law/alloc/de_trim/provenance/iterations"] = 3
    new, notes = upgrade_document(raw)
    assert _built(new, "eoir").de_trim_stale and not _built(new).de_trim_stale
    assert any(n["path"] == "/variants/eoir/patch" and "섞였다" in n["message"] for n in notes)


def test_huge_resid_tol_is_warned():
    doc = load_example()
    doc["solver"]["resid_tol"] = 0.05
    tol = [w for w in document_warnings(validate_document(doc)) if w["path"] == "/solver/resid_tol"]
    assert len(tol) == 1 and "0.05" in tol[0]["message"]
    doc["solver"]["resid_tol"] = 1e-2  # 경계값 자체는 경고하지 않는다
    assert not [w for w in document_warnings(validate_document(doc)) if w["path"] == "/solver/resid_tol"]


@pytest.mark.parametrize("doc", [None, [], {"schema_version": 1}, {"schema_version": True}, {"schema_version": 3}])
def test_upgrade_leaves_other_versions_alone(doc):
    new, notes = upgrade_document(doc)
    assert new == doc and notes == []


def test_upgraded_documents_are_json_plain():
    new, notes = upgrade_document(_v2())
    json.dumps(new, allow_nan=False)
    json.dumps(notes, ensure_ascii=False)


# ── 폼 ──────────────────────────────────────────────────────────────────


def test_form_has_the_solver_section_and_loadings_field_and_no_old_fields():
    spec = form_spec()
    keys = [s["key"] for s in spec["sections"]]
    assert "solver" in keys and "operating" not in keys and "trim" not in keys
    paths = json.dumps(spec)
    assert "/mass/loadings" in paths and "/solver/resid_tol" in paths
    assert "/operating/" not in paths and "scan_mach" not in paths and '"/trim/' not in paths
    assert spec["schema_version"] == 3


def test_verdict_context_equality_includes_loadings():
    built = _built(load_example())
    from claw.opspace.verdict import VerdictContext

    a = VerdictContext.from_profile(built)
    assert dataclasses.replace(a, loadings_declared=2) != a
