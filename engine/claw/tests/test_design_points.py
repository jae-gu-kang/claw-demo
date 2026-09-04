"""M17 points 검증 — 역할 래칫, 인접 관계, 서펜타인 순서, 직렬화 왕복."""

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


def test_case_name_precision_survives_refine_midpoints():
    """중점 반올림(refine._ROUND, 소수점 6자리)보다 이름이 거칠면 서로 다른 점이
    같은 이름을 갖는다 — 이름이 매핑 키라 트림·마진이 다른 점에 귀속된다."""
    a = case_name(0.4, 1007.8125, 200.0)
    b = case_name(0.4, 1007.81255, 200.0)
    assert a != b, f"고도 격자에서 이름이 겹친다: {a}"
    # 흔한 값은 기존 표기를 유지한다 (기존 결과·픽스처와의 호환)
    assert case_name(0.4, 1000.0, 200.0) == "M0.4_h1000_f200"
    assert case_name(0.2187, 1000.0, 200.0) == "M0.2187_h1000_f200"


def _fake_tr(converged=True, alpha_ok=True, de=0.0, thr=0.3):
    """판정 입력만 갖춘 최소 TrimResult 대역 — envelope_verdict가 보는 필드는
    converged·flags·control 뿐이라 사유 조합을 자유로 만든다."""
    from types import SimpleNamespace

    sat_ok = abs(de) < 0.95 * 0.35 and 0.02 < thr < 0.95
    return SimpleNamespace(
        converged=converged,
        flags={"saturation_ok": sat_ok, "alpha_margin_ok": alpha_ok},
        control=SimpleNamespace(elevon=[de], throttle=[thr]),
    )


def test_envelope_verdict_reasons_priority():
    """envelope_verdict — ok는 envelope_ok 정본, reasons는 우선순위 순 전체 귀속.

    saturated_throttle_high는 이제 **대리 지표가 아니라 추진 한계 그 자체**다 —
    프로펠러 추력 모델(plant/prop.py PropEngine)이 들어오면서 포화가 곧 "이 조건에서
    프로펠러가 더 못 낸다"가 됐다 (trim.py SAT_FRAC 95% 등고선 기준).
    """
    from claw.design.points import envelope_ok, envelope_verdict

    good = _fake_tr()
    assert envelope_verdict(good) == {"ok": True, "reasons": []}

    cases = [
        (_fake_tr(converged=False), "not_converged"),
        (_fake_tr(alpha_ok=False), "alpha_margin"),
        (_fake_tr(thr=0.97), "saturated_throttle_high"),
        (_fake_tr(de=0.34), "saturated_de"),
        (_fake_tr(thr=0.01), "saturated_throttle_low"),
    ]
    for tr, reason in cases:
        v = envelope_verdict(tr)
        assert v["ok"] is False and v["ok"] == envelope_ok(tr)
        assert v["reasons"] == [reason], reason

    # 복합 실패 — 우선순위 순서 유지 (첫 항목이 표시 대표)
    multi = _fake_tr(converged=False, alpha_ok=False, thr=0.97)
    assert envelope_verdict(multi)["reasons"] == [
        "not_converged", "alpha_margin", "saturated_throttle_high"]
