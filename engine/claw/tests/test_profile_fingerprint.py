"""기체 지문 둘 — 계보(profile_fp)와 플랜트(plant_fp) (02 §5.6)."""

import re

from claw.profile import (
    FP_EXCLUDED,
    build_profile,
    load_example,
    validate_document,
)
from claw.profile.schema import document_warnings, effective_document


def _fps(doc, variant=None):
    p = build_profile(validate_document(doc), variant, validated=True)
    return p.fingerprint, p.plant_fingerprint


def test_excluded_fields_are_pinned():
    # 이 목록이 넓어지면 "같은 기체"의 정의가 넓어진다 — 조용히 늘면 안 된다
    assert FP_EXCLUDED == ("/id", "/name", "/description", "/is_example", "/variants",
                           "/law/design/provenance", "/law/alloc/de_trim/provenance", "/mission_template",
                           "/display")


def test_mission_template_does_not_change_either_fingerprint():
    """화면 기본값은 계산에 쓰이지 않는다 — 고쳐도, 없어도 같은 기체다(옛 결과·스냅숏의 계보가 끊기지 않게)."""
    base = _fps(load_example())
    doc = load_example()
    doc["mission_template"]["sim"]["climb"]["speed"] = 130.0
    assert _fps(doc) == base
    doc = load_example()
    del doc["mission_template"]  # 이 절이 생기기 전 문서
    assert _fps(doc) == base
    doc["mission_template"] = None
    assert _fps(doc) == base


def test_display_model_does_not_change_either_fingerprint():
    """표시 모델은 화면이 기체를 그리는 방법이다 — 바꿔도, 없어도 같은 기체다."""
    base = _fps(load_example())
    doc = load_example()
    doc["display"]["model"] = "other.glb"
    assert _fps(doc) == base
    doc["display"] = None
    assert _fps(doc) == base
    del doc["display"]  # 이 절이 생기기 전 문서
    assert _fps(doc) == base


def test_example_eoir_variant_only_swaps_the_display_model():
    """예제의 EO/IR형은 표시 모델(기수 대신 짐벌 볼 GLB)만 바꾼다 — 짐벌의 질량·항력 자료가 없어 계산 입력은 기본형 그대로다.
    그래서 두 지문이 기본형과 같고(같은 기체로 계산된다), 기본형의 문서 알림이 변형 몫으로 겹쳐 나오지 않는다."""
    doc = validate_document(load_example())
    assert [(v["id"], v["name"]) for v in doc["variants"]] == [("eoir", "EO/IR형")]
    assert effective_document(doc, "eoir")["display"] == {"kind": "model", "model": "shahed136_eoir.glb"}
    assert _fps(load_example(), "eoir") == _fps(load_example())
    assert [w["variant"] for w in document_warnings(doc)] == [None]


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
