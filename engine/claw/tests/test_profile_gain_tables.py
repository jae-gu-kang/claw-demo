"""문서의 확정 게인 표(law.gain_tables) — 자동 설계 산출의 정본 되쓰기 (02 §5.6, 스키마 v2).

고정하는 계약: 스키마 검증(자리·마하 축·설계 없이 금지) · 지문(표는 안, provenance는 밖) ·
낡음 거부(δe_trim과 같은 원칙 — 반영 뒤 문서가 바뀌면 조립이 거부) · 조립 우선순위(주입 >
확정 표 > 규칙 표).
"""

import copy

import pytest

from claw.fcl.assemble import assemble_law
from claw.profile import ProfileError, build_profile, load_example, validate_document
from claw.profile.fingerprint import gain_tables_basis_fingerprint


def _with_tables(doc=None, *, slots=("pitch.kp",), factor=0.5, basis=True):
    """확정 게인 표를 단 문서 — 규칙 표와 다른 값(설계 상수 × factor의 평탄 표)으로 만들어 구분한다."""
    d = copy.deepcopy(doc or load_example())
    built = build_profile(d)
    design = built.design_gains()
    grid = d["law"]["schedule"]["mach_grid"]
    d["law"]["gain_tables"] = {
        "tables": {s: {"axes": {"mach": list(grid)}, "data": [design[s] * factor] * len(grid),
                       "extrapolate": "clip"} for s in slots},
        "provenance": {"source": "test"},
    }
    if basis:
        d["law"]["gain_tables"]["provenance"]["basis_fingerprint"] = \
            gain_tables_basis_fingerprint(validate_document(d))
    return d


def test_schema_v2_and_v1_documents_are_rejected_with_the_version_path():
    d = load_example()
    assert d["schema_version"] == 2
    assert d["law"]["gain_tables"] is None  # 없으면 없음(null) — 예제는 확정 표 없이 출발
    old = copy.deepcopy(d)
    old["schema_version"] = 1
    with pytest.raises(ProfileError) as e:
        validate_document(old)
    assert e.value.path == "/schema_version"


def test_schema_validates_tables_and_their_slots():
    ok = validate_document(_with_tables())
    t = ok["law"]["gain_tables"]["tables"]["pitch.kp"]
    assert t["extrapolate"] == "clip" and len(t["data"]) == len(t["axes"]["mach"])

    bad = _with_tables()
    bad["law"]["gain_tables"]["tables"] = {}
    with pytest.raises(ProfileError) as e:
        validate_document(bad)
    assert e.value.path == "/law/gain_tables/tables"

    bad = _with_tables()
    bad["law"]["gain_tables"]["tables"]["speed.k_rate"] = bad["law"]["gain_tables"]["tables"]["pitch.kp"]
    with pytest.raises(ProfileError) as e:
        validate_document(bad)
    assert "스케줄 불가" in e.value.message

    bad = _with_tables()
    bad["law"]["gain_tables"]["tables"]["pitch.kp"]["axes"]["mach"] = [0.3, 0.2]
    with pytest.raises(ProfileError):
        validate_document(bad)

    # 설계 게인 없이 확정 표만 둘 수 없다 — 표는 설계의 산출물이다
    bad = _with_tables()
    bad["law"]["design"] = bad["law"]["schedule"] = bad["law"]["alloc"] = None
    with pytest.raises(ProfileError) as e:
        validate_document(bad)
    assert e.value.path == "/law/gain_tables"


def test_fingerprint_covers_tables_but_not_provenance():
    base = build_profile(_with_tables()).fingerprint
    prov = _with_tables()
    prov["law"]["gain_tables"]["provenance"]["note"] = "출처 기록은 지문 밖"
    assert build_profile(prov).fingerprint == base
    data = _with_tables()
    data["law"]["gain_tables"]["tables"]["pitch.kp"]["data"][0] *= 1.1
    assert build_profile(data).fingerprint != base
    # 표 절 자체가 없던 문서와도 다르다 — 계산에 쓰는 값이라 지문 안이다
    assert build_profile(load_example()).fingerprint != base


def test_basis_fingerprint_excludes_the_tables_themselves():
    """기준 지문은 표를 뺀 문서의 지문 — 표가 있든 없든 같아야 자기 참조가 없다."""
    plain = validate_document(load_example())
    tabled = validate_document(_with_tables())
    assert gain_tables_basis_fingerprint(plain) == gain_tables_basis_fingerprint(tabled)


def test_confirmed_tables_win_over_the_rule_schedule_in_assembly():
    built = build_profile(_with_tables(slots=("pitch.kp", "roll.kp"), factor=0.5))
    tables = built.confirmed_gain_tables()
    assert set(tables) == {"pitch.kp", "roll.kp"}
    m = built.doc["law"]["schedule"]["mach_grid"][0]
    assert tables["pitch.kp"].interp(mach=m) == pytest.approx(built.design_gains()["pitch.kp"] * 0.5)
    # 조립이 확정 표를 쓴다 — 스케줄 자리 집합이 표의 키 집합이다(규칙의 scheduled가 아니라)
    law = assemble_law(built)
    assert set(law.schedule.tables) == {"pitch.kp", "roll.kp"}
    # 주입은 여전히 전체 교체로 이긴다 (파라미터 스터디 계약 불변)
    injected = {"pitch.kp": tables["pitch.kp"]}
    assert set(assemble_law(built, gain_tables=injected).schedule.tables) == {"pitch.kp"}


def test_stale_confirmed_tables_are_rejected_like_de_trim():
    d = _with_tables()
    built = build_profile(d)
    assert built.gain_tables_stale is False
    d2 = copy.deepcopy(d)
    d2["mass"]["m_empty"] += 1.0  # 반영 뒤 플랜트가 바뀌었다
    stale = build_profile(d2)
    assert stale.gain_tables_stale is True
    with pytest.raises(ProfileError) as e:
        stale.confirmed_gain_tables()
    assert e.value.path == "/law/gain_tables"
    with pytest.raises(ProfileError):
        assemble_law(stale)  # 낡은 표로 조용히 조립하지 않는다
    # 지문 밖 변경(표시 모델)은 낡음이 아니다
    d3 = copy.deepcopy(d)
    d3["display"] = None
    assert build_profile(d3).gain_tables_stale is False
    # 기준 지문이 없는 표(손으로 넣음)는 낡은 것으로 취급한다 — 근거 없는 표로 조립하지 않는다
    d4 = _with_tables(basis=False)
    assert build_profile(d4).gain_tables_stale is True


def test_gain_scale_sweeps_use_the_confirmed_tables_as_their_base():
    """게인 영향 스윕의 배율 기저는 조립 기본과 같은 표다 — 배율 1.0 지점이 실제 운용 법칙(확정 표)과
    같아야 스윕 중심이 기준 계산·시뮬과 갈리지 않는다 (v1.31 리뷰가 잡은 자리)."""
    from claw.pipeline.influence import Shape, make_law

    built = build_profile(_with_tables(factor=0.5))
    m = built.doc["law"]["schedule"]["mach_grid"][0]
    base = built.design_gains()["pitch.kp"] * 0.5
    law = make_law(Shape(profile=built, gain_scale={"pitch.kp": 1.0}))
    assert law.schedule.tables["pitch.kp"].interp(mach=m) == pytest.approx(base)
    law2 = make_law(Shape(profile=built, gain_scale={"pitch.kp": 2.0}))
    assert law2.schedule.tables["pitch.kp"].interp(mach=m) == pytest.approx(2.0 * base)
