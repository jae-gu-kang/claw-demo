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
                           "/law/design/provenance", "/law/alloc/de_trim/provenance",
                           "/law/gain_tables/provenance",  # v2 — 표는 지문 안, 출처 기록만 밖
                           "/mission_template", "/display",
                           "/criteria", "/tuning",  # v1.51 기준 통합 ① — 판정·설계 목표이지 기체가 아니다
                           "/operating_region")  # 격자 체계 ② — 요구 운용영역은 요구이지 기체가 아니다


def test_operating_region_changes_neither_fingerprint():
    """요구 운용영역을 적어도 같은 기체다 — 요구를 바꿨다고 트림이 낡으면 안 된다(05 §11.8 변경 영향표)."""
    doc = load_example()
    region = {"mach": [0.1, 0.28], "alt": [100.0, 3000.0], "fuel": [5.0, 25.0], "boundary": None,
              "base_grid": {"n_mach": 5, "alts": [100.0, 3000.0], "fuels": [25.0]}}
    assert _fps({**doc, "operating_region": region}) == _fps(doc)


def test_criteria_and_tuning_change_neither_fingerprint():
    """기준·목표를 적어도, 바꿔도, 없애도 같은 기체다 — 기준을 바꿨다고 트림·게인 표가 낡으면 안 된다.
    어느 기준으로 났는지는 기준 지문 둘이 따로 말한다(판정 기준 지문은 바뀐다)."""
    base = _fps(load_example())
    doc = load_example()
    doc["criteria"] = {"margin": {"pm_min_deg": 40.0}}
    doc["tuning"] = {"targets": {"zeta_sp": 0.9}}
    assert _fps(doc) == base
    doc = load_example()
    doc.pop("criteria", None)
    doc.pop("tuning", None)  # 이 절이 생기기 전 문서
    assert _fps(doc) == base
    from claw.profile import build_profile as bp
    j0 = bp(validate_document(load_example()), validated=True).eval_criteria.judgement_fingerprint()
    doc = load_example()
    doc["criteria"] = {"margin": {"pm_min_deg": 40.0}}
    assert bp(validate_document(doc), validated=True).eval_criteria.judgement_fingerprint() != j0


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
    """예제의 EO/IR형은 표시 모델(기수 대신 총알형 EO/IR 헤드 GLB)만 바꾼다 — 짐벌의 질량·항력 자료가 없어 계산 입력은 기본형 그대로다.
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
