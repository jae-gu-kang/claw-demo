"""기체 편집 폼 서술 — 예제 문서의 모든 값이 칸에 속하고, 모든 칸이 실재하고, 칸의 선택지·「없음」
허용이 검증기와 같다 (02 §5.6 · 06 §8). 검증기에 키가 늘거나 규칙이 바뀌면 폼이 낡았다고 빨개진다."""

import copy
import json

import pytest

from claw.profile import ProfileError, load_example, validate_document
from claw.profile import schema
from claw.profile.form import META_KEYS, form_spec
from claw.profile.patch import get_pointer, parse_pointer

KINDS = {"number", "range", "vec3", "mat3", "rows3", "table_mach", "choice", "multichoice",
         "numlist", "text_json", "terms", "registry", "component", "group"}


def _walk(items):
    for f in items:
        yield f
        if f["kind"] == "group":
            yield from _walk(f["fields"])


def _fields():
    return [f for sec in form_spec()["sections"] for f in _walk(sec["fields"])]


def _set(doc, ptr, value):
    tokens = parse_pointer(ptr)
    node = doc
    for t in tokens[:-1]:
        node = node[int(t)] if isinstance(node, list) else node[t]
    node[tokens[-1]] = value


def test_spec_is_plain_json_with_known_kinds_and_unique_paths():
    spec = form_spec()
    json.dumps(spec, ensure_ascii=False, allow_nan=False)
    paths = [f["path"] for f in _fields()]
    assert len(paths) == len(set(paths))
    for f in _fields():
        assert f["kind"] in KINDS and f["label"], f
        parse_pointer(f["path"])


def test_sections_follow_the_document_order():
    keys = [s["key"] for s in form_spec()["sections"]]
    assert keys == [k for k in schema.SECTIONS if k not in META_KEYS]


def test_every_field_exists_in_the_example():
    doc = load_example()
    for f in _fields():
        get_pointer(doc, f["path"])  # 없는 경로면 ProfileError


def test_every_example_value_belongs_to_a_field():
    doc = load_example()
    owners = {f["path"] for f in _fields() if f["kind"] != "group"}
    missing = []

    def walk(node, path):
        if path in owners:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        else:
            missing.append(path)

    for k, v in doc.items():
        if k not in META_KEYS:
            walk(v, f"/{k}")
    assert missing == [], "폼에 칸이 없는 문서 값"


def test_choices_are_the_validator_constants():
    by_path = {f["path"]: f for f in _fields()}
    assert by_path["/aero/form"]["choices"] == list(schema.AERO_FORMS)
    assert by_path["/surfaces/layout"]["choices"] == list(schema.LAYOUTS)
    assert by_path["/law/template"]["choices"] == list(schema.TEMPLATES)
    assert by_path["/law/schedule/rule"]["choices"] == list(schema.SCHEDULE_RULES)
    assert by_path["/law/alloc/de_trim/source"]["choices"] == list(schema.DE_TRIM_SOURCES)
    assert by_path["/actuator"]["reserved"] == list(schema.ACTUATOR_RESERVED)
    assert by_path["/law/design/scas/pitch"]["reserved"] == list(schema.SCAS_RESERVED)
    doc = load_example()
    doc["law"]["schedule"]["scheduled"] = list(by_path["/law/schedule/scheduled"]["choices"])
    validate_document(doc)  # 고를 수 있는 자리 전부가 실제로 통과한다


def test_nullable_flags_match_the_validator():
    """폼이 「없음」을 허용한 칸만 검증기가 null을 받는다 — 어긋나면 폼이 저장 못 할 값을 만들거나 가능한 선택을 막는다."""
    for f in _fields():
        if f["kind"] not in ("number", "range", "group"):
            continue
        doc = load_example()
        _set(doc, f["path"], None)
        if f["path"] == "/law/design":
            doc["law"]["schedule"] = None  # 스케줄은 설계 게인 없이 둘 수 없다 — 함께 비운다
        if f.get("nullable"):
            validate_document(doc)
        else:
            with pytest.raises(ProfileError):
                validate_document(copy.deepcopy(doc))


def test_term_input_rules_come_from_the_validator():
    spec = form_spec()
    assert spec["term_inputs"] == list(schema.TERM_INPUTS)
    extra = {(e["form"], e["coef"]): tuple(e["inputs"]) for e in spec["term_extra_inputs"]}
    assert extra == schema.TERM_EXTRA_INPUTS
    assert spec["dispersion_tags"] == {t: {"coef": c, "input": i} for t, (c, i) in schema.DISPERSION_TAGS.items()}
