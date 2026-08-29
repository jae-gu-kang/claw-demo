"""M16 points 검증 — 역할 래칫, 인접 관계, 서펜타인 순서, 직렬화 왕복."""

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    ROLE_BREAKPOINT,
    ROLE_VALIDATION,
    OperatingPoint,
    PointSet,
    case_name,
)


def _pt(mach, alt, fuel, role=ROLE_ANCHOR, origin="coarse"):
    return OperatingPoint(
        case=TrimCase(name=case_name(mach, alt, fuel), mach=mach, alt=alt, fuel=fuel),
        role=role,
        origin=origin,
    )


def test_case_name_is_not_rounded():
    """반올림 이름은 정밀 격자에서 겹친다 — 격자 값 그대로 (web nameCases 원칙)."""
    assert case_name(0.4, 1000.0, 200.0) == "M0.4_h1000_f200"
    assert case_name(0.425, 1000.0, 200.0) == "M0.425_h1000_f200"
    assert case_name(0.4, 1000.0, 200.0) != case_name(0.425, 1000.0, 200.0)


def test_duplicate_name_rejected():
    ps = PointSet([_pt(0.4, 1000.0, 200.0)])
    with pytest.raises(ValueError, match="중복"):
        ps.add(_pt(0.4, 1000.0, 200.0))


def test_promote_ratchet():
    """validation → breakpoint → anchor 단방향. 역행·제자리는 거부, 이력이 남는다."""
    ps = PointSet([_pt(0.5, 1000.0, 200.0, role=ROLE_VALIDATION)])
    name = "M0.5_h1000_f200"
    ps.promote(name, ROLE_BREAKPOINT, reason="gain_interp_valley")
    ps.promote(name, ROLE_ANCHOR, reason="plant_variation")
    pt = ps.get(name)
    assert pt.role == ROLE_ANCHOR
    assert [h["to"] for h in pt.history] == [ROLE_BREAKPOINT, ROLE_ANCHOR]
    with pytest.raises(ValueError, match="래칫"):
        ps.promote(name, ROLE_VALIDATION, reason="oops")
    with pytest.raises(ValueError, match="래칫"):
        ps.promote(name, ROLE_ANCHOR, reason="again")


def test_role_queries():
    ps = PointSet([
        _pt(0.3, 1000.0, 200.0, role=ROLE_ANCHOR),
        _pt(0.4, 1000.0, 200.0, role=ROLE_BREAKPOINT),
        _pt(0.5, 1000.0, 200.0, role=ROLE_VALIDATION),
    ])
    assert [p.case.mach for p in ps.by_role(ROLE_ANCHOR)] == [0.3]
    # anchor는 breakpoint·validation 역할을 겸한다 (서열 의미)
    assert [p.case.mach for p in ps.at_least(ROLE_BREAKPOINT)] == [0.3, 0.4]
    assert len(ps.at_least(ROLE_VALIDATION)) == 3


def test_adjacent_pairs_axis_aligned():
    """한 축만 다른 최근접끼리만 이웃 — 행마다 mach 격자가 달라도 성립."""
    ps = PointSet([
        _pt(0.3, 1000.0, 200.0),
        _pt(0.5, 1000.0, 200.0),
        _pt(0.7, 1000.0, 200.0),
        _pt(0.4, 3000.0, 200.0),  # 다른 고도 행 — mach 격자가 다르다
    ])
    pairs = ps.adjacent_pairs()
    assert ("M0.3_h1000_f200", "M0.5_h1000_f200", "mach") in pairs
    assert ("M0.5_h1000_f200", "M0.7_h1000_f200", "mach") in pairs
    # 0.3과 0.7은 최근접이 아니다 (사이에 0.5)
    assert ("M0.3_h1000_f200", "M0.7_h1000_f200", "mach") not in pairs
    # 고도축 인접은 mach가 같아야 성립 — 여기는 없다
    assert not [p for p in pairs if p[2] == "alt"]
    assert set(ps.neighbors("M0.5_h1000_f200")) == {"M0.3_h1000_f200", "M0.7_h1000_f200"}


def test_serpentine_adjacency():
    """서펜타인 순서에서 리스트 인접 = 물리 인접 (trim_batch 인접 시드 전제)."""
    ps = PointSet([
        _pt(m, a, 200.0)
        for a in (1000.0, 3000.0)
        for m in (0.3, 0.5, 0.7)
    ])
    cases = ps.serpentine()
    machs = [c.mach for c in cases]
    assert machs == [0.3, 0.5, 0.7, 0.7, 0.5, 0.3]  # 두 번째 행은 역방향
    # 행 경계에서도 mach 점프가 없다 (0.7 → 0.7)
    assert cases[2].mach == cases[3].mach


def test_roundtrip_serialization():
    ps = PointSet([
        _pt(0.3, 1000.0, 200.0, role=ROLE_ANCHOR),
        _pt(0.5, 1000.0, 200.0, role=ROLE_VALIDATION, origin="midpoint"),
    ])
    ps.get("M0.5_h1000_f200").trimmable = False
    ps.promote("M0.5_h1000_f200", ROLE_BREAKPOINT, reason="valley")
    d = ps.to_dict()
    ps2 = PointSet.from_dict(d)
    assert ps2.to_dict() == d
    assert ps2.get("M0.5_h1000_f200").trimmable is False
    assert ps2.get("M0.5_h1000_f200").role == ROLE_BREAKPOINT
