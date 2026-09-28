"""프로파일 스토어 요약 — 목록 한 줄이 싣는 판단(게인 출처·표 낡음)의 단위 검증 (02 §5.6)."""

import copy

from claw.profile import load_example, validate_document
from claw.profile.fingerprint import gain_tables_basis_fingerprint
from claw_server.profiles import ProfileStore


def _tabled(doc):
    """확정 게인 표(v2)를 단 문서 — 기준 지문까지 유효하게."""
    d = copy.deepcopy(doc)
    grid = d["law"]["schedule"]["mach_grid"]
    d["law"]["gain_tables"] = {
        "tables": {"pitch.kp": {"axes": {"mach": list(grid)}, "data": [-2.0] * len(grid),
                                "extrapolate": "clip"}},
        "provenance": {"source": "auto_design",
                       "basis_fingerprint": gain_tables_basis_fingerprint(validate_document(d))},
    }
    return d


def test_summary_carries_variant_fingerprints_for_freshness_checks():
    """목록 요약의 변형 줄에 지문 동봉 — 결과 신선도 대조(웹 lib/freshness.js)가 변형 결과도 지문으로
    판정할 근거다. 기본 지문과 다르고, 문서 조회(_fingerprints)의 변형 지문과 같다."""
    from claw.profile import build_profile

    plain = validate_document(load_example())
    out = ProfileStore.summary(plain, 1)
    assert out["fingerprint"] == build_profile(plain).fingerprint
    for v in out["variants"]:
        assert v["fingerprint"] == build_profile(plain, v["id"], validated=True).fingerprint
    # 지문 밖 절(/display)만 바꾸는 변형은 기본과 같은 지문 — 같은 기체다(표시-only 변형의
    # 결과는 display 편집에도 신선을 유지). 예제의 eoir가 어느 쪽인지는 픽스처마다 다르므로
    # (제품 예제는 질량도 패치한다) 단정하지 않고, 규약은 아래 두 조작 변형으로 고정한다
    skin = copy.deepcopy(plain)
    skin["variants"] = [{"id": "skin", "name": "표시만", "patch": {"/display": None}}]
    sout = ProfileStore.summary(validate_document(skin), 1)
    assert sout["variants"][0]["fingerprint"] == sout["fingerprint"]
    # 문서를 바꾸는 변형은 달라진다
    heavy = copy.deepcopy(plain)
    heavy["variants"] = [{"id": "heavy", "name": "무거움",
                          "patch": {"/mass/m_empty": plain["mass"]["m_empty"] + 5.0}}]
    hout = ProfileStore.summary(validate_document(heavy), 1)
    assert hout["variants"][0]["fingerprint"] != hout["fingerprint"]


def test_summary_reports_confirmed_gain_tables_and_their_staleness():
    plain = validate_document(load_example())
    assert ProfileStore.summary(plain, 1)["gain_tables"] is None

    tabled = validate_document(_tabled(plain))
    assert ProfileStore.summary(tabled, 1)["gain_tables"] == {"source": "auto_design", "stale": False,
                                                             "stale_variants": [],
                                                             "variants": {"eoir": {"source": "confirmed"}}}

    # 반영 뒤 문서가 바뀌면 낡는다 — 기준 지문 대조(조립 거부와 같은 판정)
    edited = copy.deepcopy(tabled)
    edited["mass"]["m_empty"] += 1.0
    edited = validate_document(edited)
    # 기본이 낡으면 변형도 낡다 — 예제의 eoir(표시-only)까지 기준 지문이 어긋난다
    assert ProfileStore.summary(edited, 2)["gain_tables"] == {"source": "auto_design", "stale": True,
                                                             "stale_variants": ["eoir"],
                                                             "variants": {"eoir": {"source": "stale"}}}

    # 출처 기록이 이상해도 요약이 죽지 않는다 — source는 없으면 null, 낡음은 참
    odd = copy.deepcopy(tabled)
    odd["law"]["gain_tables"]["provenance"] = {}
    odd = validate_document(odd)
    assert ProfileStore.summary(odd, 3)["gain_tables"] == {"source": None, "stale": True,
                                                          "stale_variants": ["eoir"],
                                                          "variants": {"eoir": {"source": "stale"}}}


def test_summary_names_the_variants_whose_confirmed_tables_are_stale():
    """문서를 바꾸는 형상 변형은 기준 지문이 어긋나 그 변형에서 표가 낡음이다 — 표시-only 변형은
    아니다(지문 밖). δe_trim stale_variants와 같은 사전 통보."""
    plain = validate_document(load_example())
    tabled = copy.deepcopy(_tabled(plain))
    tabled["variants"] = [
        {"id": "heavy", "name": "무거움", "patch": {"/mass/m_empty": plain["mass"]["m_empty"] + 5.0}},
        {"id": "skin", "name": "표시만", "patch": {"/display": None}},
    ]
    tabled = validate_document(tabled)
    out = ProfileStore.summary(tabled, 1)["gain_tables"]
    assert out["stale"] is False and out["stale_variants"] == ["heavy"]
    assert out["variants"] == {"heavy": {"source": "stale"}, "skin": {"source": "confirmed"}}


def test_summary_says_which_gains_each_variant_flies():
    """변형마다 **실제로 나는** 게인의 출처 — 기본형의 확정 표 배너를 변형에 그대로 달면 거짓이 되는 자리를 웹이
    가른다. 쇼케이스 EO/IR형처럼 패치가 /law/gain_tables를 비운 변형은 규칙 스케줄(설계 게인 × q̄ 역비)로 난다.
    스케줄·설계가 없어 스케줄 게인으로 조립되지 않는 변형은 none. 변형이 제 표를 실으면 그 표의 신선도다."""
    from claw.profile import build_profile, load_showcase

    plain = validate_document(load_example())
    tabled = copy.deepcopy(_tabled(plain))
    heavy_patch = {"/mass/m_empty": plain["mass"]["m_empty"] + 5.0}
    tabled["variants"] = [
        {"id": "heavy", "name": "무거움", "patch": dict(heavy_patch)},
        {"id": "heavy-rule", "name": "무거움 — 규칙 스케줄", "patch": {**heavy_patch, "/law/gain_tables": None}},
        {"id": "unscheduled", "name": "스케줄 없음", "patch": {"/law/gain_tables": None, "/law/schedule": None}},
        {"id": "skin", "name": "표시만", "patch": {"/display": None}},
    ]
    tabled = validate_document(tabled)
    out = ProfileStore.summary(tabled, 1)["gain_tables"]
    assert out["variants"] == {"heavy": {"source": "stale"}, "heavy-rule": {"source": "rule_schedule"},
                               "unscheduled": {"source": "none"}, "skin": {"source": "confirmed"}}
    assert out["stale_variants"] == ["heavy"]  # 표를 비운 변형은 낡음이 아니다 — 조립이 선다
    # 규칙 스케줄이라고 말한 변형은 실제로 확정 표 없이 조립된다(assemble_law가 규칙 스케줄로 떨어진다)
    rule = build_profile(tabled, "heavy-rule", validated=True)
    assert rule.confirmed_gain_tables() is None and set(rule.gain_tables()) == set(tabled["law"]["schedule"]["scheduled"])

    # 패키지 쇼케이스 문서 — 기본형은 확정 표, EO/IR형은 규칙 스케줄(IB1)
    show = validate_document(load_showcase())
    sgt = ProfileStore.summary(show, 1)["gain_tables"]
    assert sgt["stale"] is False and sgt["stale_variants"] == []
    assert sgt["variants"] == {"eoir": {"source": "rule_schedule"}}
