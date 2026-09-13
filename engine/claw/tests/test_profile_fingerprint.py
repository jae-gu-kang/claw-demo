"""기체 지문 둘 — 계보(profile_fp)와 플랜트(plant_fp) (02 §5.6)."""

import re

from claw.profile import (
    FP_EXCLUDED,
    build_profile,
    load_example,
    validate_document,
)


def _fps(doc, variant=None):
    p = build_profile(validate_document(doc), variant, validated=True)
    return p.fingerprint, p.plant_fingerprint


def test_excluded_fields_are_pinned():
    # 이 목록이 넓어지면 "같은 기체"의 정의가 넓어진다 — 조용히 늘면 안 된다
    assert FP_EXCLUDED == ("/id", "/name", "/description", "/is_example", "/variants",
                           "/law/design/provenance", "/law/alloc/de_trim/provenance")


def test_fingerprints_are_16_hex():
    fp, plant = _fps(load_example())
    assert re.fullmatch(r"[0-9a-f]{16}", fp) and re.fullmatch(r"[0-9a-f]{16}", plant)


def test_labels_and_provenance_do_not_change_the_aircraft():
    base = _fps(load_example())
    doc = load_example()
    doc.update(id="renamed", name="다른 이름", description="…", is_example=False)
    doc["law"]["design"]["provenance"] = "다른 출처"
    doc["law"]["alloc"]["de_trim"]["provenance"] = None
    doc["variants"] = [{"id": "v", "name": "v", "patch": {}}]
    assert _fps(doc) == base


def test_plant_change_moves_both_gain_change_moves_only_profile():
    fp0, plant0 = _fps(load_example())
    heavy = load_example()
    heavy["mass"]["m_empty"] = 900.0
    fp1, plant1 = _fps(heavy)
    assert fp1 != fp0 and plant1 != plant0
    retuned = load_example()
    retuned["law"]["design"]["scas"]["pitch"]["kp"] = -2.5
    fp2, plant2 = _fps(retuned)
    assert fp2 != fp0 and plant2 == plant0


def test_integer_spelling_does_not_split_the_fingerprint():
    doc = load_example()
    doc["mass"]["m_empty"] = 800
    assert _fps(doc) == _fps(load_example())


def test_variant_fingerprint_follows_effective_values():
    doc = load_example()
    doc["variants"] = [{"id": "same", "name": "같음", "patch": {"/mass/m_empty": 800.0}},
                       {"id": "heavy", "name": "무거움", "patch": {"/mass/m_empty": 950.0}}]
    base = _fps(load_example())
    assert _fps(doc, "same") == base
    assert _fps(doc, "heavy") != base
