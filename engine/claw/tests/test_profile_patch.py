"""형상 변형 — JSON Pointer 치환 맵 (02 §5.6)."""

import pytest

from claw.profile import (
    ProfileError,
    apply_patch,
    build_profile,
    effective_document,
    load_example,
    validate_document,
)
from claw.profile.patch import parse_pointer


def _with_variant(patch, vid="heavy"):
    doc = load_example()
    doc["variants"] = [{"id": vid, "name": "변형", "patch": patch}]
    return doc


def test_pointer_escapes():
    assert parse_pointer("/a~1b/c~0d") == ["a/b", "c~d"]
    with pytest.raises(ProfileError):
        parse_pointer("mass/m_empty")


def test_variant_replaces_values_without_touching_the_base():
    doc = validate_document(_with_variant({"/mass/m_empty": 900, "/stall/table/data/0": 0.41}))
    assert doc["variants"][0]["patch"] == {"/mass/m_empty": 900.0, "/stall/table/data/0": 0.41}
    assert type(doc["variants"][0]["patch"]["/mass/m_empty"]) is float  # 900 == 900.0이라 ==로는 못 잡는다
    eff = effective_document(doc, "heavy")
    assert eff["mass"]["m_empty"] == 900.0 and eff["stall"]["table"]["data"][0] == 0.41
    assert "variants" not in eff
    assert doc["mass"]["m_empty"] == 800.0  # 기본 문서는 그대로
    base = build_profile(doc, validated=True).aircraft()
    heavy = build_profile(doc, "heavy", validated=True).aircraft()
    assert heavy.fuel_mass.m_empty == base.fuel_mass.m_empty + 100.0


def test_null_is_a_value_where_the_schema_allows_it():
    doc = validate_document(_with_variant({"/ground/rail": None}))
    assert build_profile(doc, "heavy", validated=True).launch_rail() is None
    with pytest.raises(ProfileError) as ei:
        validate_document(_with_variant({"/mass/m_empty": None}))
    assert ei.value.path == "/variants/0/patch/mass/m_empty"


@pytest.mark.parametrize("ptr", ["/mass/nope", "/stall/table/data/99", "/mass/m_empty/0",
                                 "/stall/table/data/01", "/stall/table/data/²",
                                 "/stall/table/data/١"])
def test_invalid_pointers_are_rejected(ptr):
    with pytest.raises(ProfileError) as ei:
        validate_document(_with_variant({ptr: 1.0}))
    assert ei.value.path.startswith("/variants/0/patch")


@pytest.mark.parametrize("ptr,value", [("/id", "other-id"), ("/is_example", False),
                                       ("/schema_version", 1), ("/variants", [])])
def test_identity_roots_are_forbidden_even_with_well_typed_values(ptr, value):
    # 값이 타입까지 맞아야 금지 규칙 자체를 잰다 — 1.0을 넣으면 다른 검사가 대신 거부한다
    with pytest.raises(ProfileError) as ei:
        validate_document(_with_variant({ptr: value}))
    assert ei.value.path == f"/variants/0/patch{ptr}"
    assert "바꿀 수 없는" in ei.value.message


def test_pointer_without_leading_slash_reports_a_clean_path():
    with pytest.raises(ProfileError) as ei:
        validate_document(_with_variant({"mass/m_empty": 1.0}))
    assert ei.value.path == "/variants/0/patch" and "mass/m_empty" in ei.value.message


def test_variant_ids_are_unique_and_must_exist():
    doc = load_example()
    doc["variants"] = [{"id": "a", "name": "a", "patch": {}}, {"id": "a", "name": "b", "patch": {}}]
    with pytest.raises(ProfileError) as ei:
        validate_document(doc)
    assert ei.value.path == "/variants/1/id"
    with pytest.raises(ProfileError):
        effective_document(validate_document(_with_variant({})), "nope")


def test_apply_patch_does_not_mutate_its_input():
    doc = load_example()
    before = repr(doc)
    apply_patch(doc, {"/mass/J_empty": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]})
    assert repr(doc) == before
