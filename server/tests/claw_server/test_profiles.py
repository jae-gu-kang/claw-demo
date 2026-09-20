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


def test_summary_reports_confirmed_gain_tables_and_their_staleness():
    plain = validate_document(load_example())
    assert ProfileStore.summary(plain, 1)["gain_tables"] is None

    tabled = validate_document(_tabled(plain))
    assert ProfileStore.summary(tabled, 1)["gain_tables"] == {"source": "auto_design", "stale": False,
                                                             "stale_variants": []}

    # 반영 뒤 문서가 바뀌면 낡는다 — 기준 지문 대조(조립 거부와 같은 판정)
    edited = copy.deepcopy(tabled)
    edited["mass"]["m_empty"] += 1.0
    edited = validate_document(edited)
    # 기본이 낡으면 변형도 낡다 — 예제의 eoir(표시-only)까지 기준 지문이 어긋난다
    assert ProfileStore.summary(edited, 2)["gain_tables"] == {"source": "auto_design", "stale": True,
                                                             "stale_variants": ["eoir"]}

    # 출처 기록이 이상해도 요약이 죽지 않는다 — source는 없으면 null, 낡음은 참
    odd = copy.deepcopy(tabled)
    odd["law"]["gain_tables"]["provenance"] = {}
    odd = validate_document(odd)
    assert ProfileStore.summary(odd, 3)["gain_tables"] == {"source": None, "stale": True,
                                                          "stale_variants": ["eoir"]}


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
