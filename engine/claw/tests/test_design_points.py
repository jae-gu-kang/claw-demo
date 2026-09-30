"""M17 points 검증 — 설계점·검증점 두 역할과 편입, 인접 관계, 서펜타인 순서, 직렬화 왕복."""

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_DESIGN,
    ROLE_VALIDATION,
    OperatingPoint,
    PointSet,
    case_name,
)


def _pt(mach, alt, fuel, role=ROLE_DESIGN, origin="coarse"):
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


def test_promote_is_validation_to_design_only():
    """편입은 검증점 → 설계점 하나뿐이다(05 §2 개정 — 역할 서열 폐지). 설계점을 다시 편입하거나 되돌리는 길은 없다.

    출처는 `promoted:<사유>`로 바뀌고, 편입 전 출처는 이력에 남는다 — 중점 검증점이었다는 사실(coverage 집계)이 사라지지 않게."""
    ps = PointSet([_pt(0.5, 1000.0, 200.0, role=ROLE_VALIDATION, origin="midpoint:a|b")])
    name = "M0.5_h1000_f200"
    ps.promote(name, reason="gain_interp_valley")
    pt = ps.get(name)
    assert pt.role == ROLE_DESIGN and pt.origin == "promoted:gain_interp_valley"
    assert pt.history == [{"from": ROLE_VALIDATION, "to": ROLE_DESIGN, "reason": "gain_interp_valley",
                           "origin": "midpoint:a|b"}]
    with pytest.raises(ValueError, match="편입"):
        ps.promote(name, reason="again")
    # 역할 이름 자체도 두 개뿐이다 — 옛 서열 이름으로 새 점을 세우지 못한다
    for bad in ("anchor", "breakpoint"):
        with pytest.raises(ValueError, match="미정의 역할"):
            _pt(0.6, 1000.0, 200.0, role=bad)


def test_legacy_roles_load_as_design_points():
    """옛 저장본의 anchor·breakpoint는 설계점으로 읽는다 — 이력에 `legacy:role_hierarchy_removed`를 남긴다.

    둘 다 게인을 정하던 점(앵커는 튜닝, breakpoint는 승격 게인 주입)이라 새 모델에서는 튜닝하는 설계점이다."""
    d = {"points": [
        {"name": "M0.3_h1000_f200", "mach": 0.3, "alt": 1000.0, "fuel": 200.0, "role": "anchor", "origin": "coarse"},
        {"name": "M0.4_h1000_f200", "mach": 0.4, "alt": 1000.0, "fuel": 200.0, "role": "breakpoint",
         "origin": "midpoint:x|y", "history": [{"from": "validation", "to": "breakpoint", "reason": "valley"}]},
        {"name": "M0.5_h1000_f200", "mach": 0.5, "alt": 1000.0, "fuel": 200.0, "role": "validation",
         "origin": "midpoint:x|y"},
    ]}
    ps = PointSet.from_dict(d)
    assert [p.role for p in ps] == [ROLE_DESIGN, ROLE_DESIGN, ROLE_VALIDATION]
    bp = ps.get("M0.4_h1000_f200")
    assert bp.history[-1] == {"from": "breakpoint", "to": ROLE_DESIGN, "reason": "legacy:role_hierarchy_removed"}
    assert bp.history[0]["to"] == "breakpoint" and bp.origin == "midpoint:x|y"
    assert ps.get("M0.5_h1000_f200").history == []
    # 옮긴 뒤의 저장본은 새 역할로 왕복한다 — 두 번 옮기지 않는다
    again = PointSet.from_dict(ps.to_dict())
    assert again.to_dict() == ps.to_dict()


def test_role_queries():
    ps = PointSet([
        _pt(0.3, 1000.0, 200.0, role=ROLE_DESIGN),
        _pt(0.4, 1000.0, 200.0, role=ROLE_VALIDATION),
        _pt(0.5, 1000.0, 200.0, role=ROLE_DESIGN),
    ])
    assert [p.case.mach for p in ps.by_role(ROLE_DESIGN)] == [0.3, 0.5]
    assert [p.case.mach for p in ps.by_role(ROLE_VALIDATION)] == [0.4]
    # 역할을 주면 그 역할끼리만 이웃이다(설계점끼리의 인접 — 보강·플랜트 거리), 안 주면 전 점
    assert ps.adjacent_pairs(ROLE_DESIGN) == [("M0.3_h1000_f200", "M0.5_h1000_f200", "mach")]
    assert len(ps.adjacent_pairs()) == 2
    assert ps.flanking("M0.4_h1000_f200", ROLE_DESIGN) == ("M0.3_h1000_f200", "M0.5_h1000_f200", "mach")
    assert [c.mach for c in ps.serpentine(ROLE_DESIGN)] == [0.3, 0.5]
    assert len(ps.serpentine()) == 3


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
        _pt(0.3, 1000.0, 200.0, role=ROLE_DESIGN),
        _pt(0.5, 1000.0, 200.0, role=ROLE_VALIDATION, origin="midpoint"),
    ])
    ps.get("M0.5_h1000_f200").trimmable = False
    ps.promote("M0.5_h1000_f200", reason="valley")
    d = ps.to_dict()
    ps2 = PointSet.from_dict(d)
    assert ps2.to_dict() == d
    assert ps2.get("M0.5_h1000_f200").trimmable is False
    assert ps2.get("M0.5_h1000_f200").role == ROLE_DESIGN


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
    """판정 입력만 갖춘 최소 TrimResult 대역 — 조건 판정(opspace/verdict.py)이 보는 필드는
    converged·flags·control·case·state(받음각)뿐이라 사유 조합을 자유로 만든다. 조건은 예제 기체의
    편한 순항(M0.4 1000 m 200 kg, α ≈ 0.04 rad)이라 모델·제한 항목은 늘 통과다."""
    from types import SimpleNamespace

    import numpy as np

    sat_ok = abs(de) < 0.95 * 0.35 and 0.02 < thr < 0.95
    return SimpleNamespace(
        converged=converged,
        flags={"saturation_ok": sat_ok, "alpha_margin_ok": alpha_ok},
        control=SimpleNamespace(elevon=[de], throttle=[thr]),
        case=TrimCase(name="fake", mach=0.4, alt=1000.0, fuel=200.0),
        state=SimpleNamespace(vel_b=np.array([130.0, 0.0, 5.0])),
    )


def test_envelope_verdict_reasons_priority():
    """envelope_verdict — ok는 조건 판정의 채택, reasons는 옛 코드를 우선순위 순으로 먼저 전체 귀속.

    saturated_throttle_high는 이제 **대리 지표가 아니라 추진 한계 그 자체**다 —
    프로펠러 추력 모델(plant/prop.py PropEngine)이 들어오면서 포화가 곧 "이 조건에서
    프로펠러가 더 못 낸다"가 됐다 (판정선 criteria.trim_margin.sat_frac 95% 등고선 기준).

    α 여유는 트림 때 찍힌 플래그가 아니라 **지금 기준의 판정선**으로 다시 잰다(이관 12단계) — 대역의 받음각(≈ 0.038 rad)이
    판정 한계를 넘도록 트림 α 여유를 크게 적은 기체 문맥(strict)에서 본다. 실제 기체에서는 트림 α 여유(0.035)가 리미터
    여유(0.05)보다 작아 α 여유 미달 해가 모두 리미터 제한에 먼저 걸린다(05 §11.3) — 채택을 막지 않는 여유 사유만 떼어
    보려고 판정선을 옮긴다.
    """
    from claw.design.points import envelope_ok, envelope_verdict
    from claw.opspace.verdict import VerdictContext, condition_verdict
    from claw.profile import build_profile, example_profile, load_example

    ctx = VerdictContext.from_profile(example_profile())
    doc = load_example()
    a_stall = float(example_profile().stall_table().interp(mach=0.4))
    doc["criteria"] = {"trim_margin": {"alpha_margin": a_stall - 0.02}}
    strict = VerdictContext.from_profile(build_profile(doc))
    good = _fake_tr()
    # 대역에는 트림 여유 수치가 없다 — reserve는 None(미계산)이지 0이 아니다
    assert envelope_verdict(good, ctx) == {"ok": True, "reasons": [], "reserve": None,
                                           "verdict": condition_verdict(good, ctx)}

    # 여유 미달(α 여유·포화)은 채택을 막지 않는다(v1.65 채택 정책) — ok는 참, 사유는 옛 코드 그대로, 판정의 margin이
    # 미달이다. 트림 실패만 제외다(가짜 해라 모델·제한은 통과)
    tr = _fake_tr(converged=False)
    v = envelope_verdict(tr, ctx)
    assert v["ok"] is False and v["ok"] == envelope_ok(tr, ctx)
    assert v["reasons"][0] == "not_converged" and v["verdict"]["exclusion"]["category"] == "trim"
    cases = [
        (_fake_tr(alpha_ok=False), "alpha_margin", "alpha_margin", strict),
        (_fake_tr(thr=0.97), "saturated_throttle_high", "throttle_high", ctx),
        (_fake_tr(de=0.34), "saturated_de", "de", ctx),
        (_fake_tr(de=-0.34), "saturated_de", "de", ctx),  # 음의 한계 쪽 — 방향별 한계식의 lo 가지
        (_fake_tr(thr=0.01), "saturated_throttle_low", "throttle_low", ctx),
    ]
    for tr, reason, margin_code, c in cases:
        v = envelope_verdict(tr, c)
        assert v["ok"] is True and v["ok"] == envelope_ok(tr, c), reason
        assert v["reasons"] == [reason], reason
        assert v["verdict"]["exclusion"] is None, reason
        assert v["verdict"]["margin"] == {"status": "short", "reasons": [margin_code]}, reason

    # 복합 실패 — 우선순위 순서 유지 (첫 항목이 표시 대표)
    multi = _fake_tr(converged=False, alpha_ok=False, thr=0.97)
    assert envelope_verdict(multi, strict)["reasons"] == [
        "not_converged", "alpha_margin", "saturated_throttle_high"]


def test_pre_trim_states_match_the_verdict_and_designable_leaves_them_out():
    """트림 전 제외 점은 목록에 남고(보고) 설계 보기(designable)에서만 빠진다 — 같은 객체를 나눈다(이관 2단계)."""
    from claw.design.points import PRE_TRIM_STATES, pre_excluded
    from claw.opspace.verdict import PRE_TRIM_CATEGORY, pre_trim_verdict

    assert PRE_TRIM_STATES == frozenset(PRE_TRIM_CATEGORY)

    class _Ctx:
        region = None
        loadings_declared = 0

    ps = PointSet()
    for m in (0.3, 0.4, 0.5):
        ps.add(OperatingPoint(case=TrimCase(name=case_name(m, 0.0, 0.0), mach=m, alt=0.0, fuel=0.0), role=ROLE_DESIGN))
    gap = ps.get(case_name(0.5, 0.0, 0.0))
    gap.verdict, gap.trimmable = pre_trim_verdict("model_gap", _Ctx()), False
    view = ps.designable()
    assert pre_excluded(gap) and not pre_excluded(ps.get(case_name(0.3, 0.0, 0.0)))
    assert view.names() == (case_name(0.3, 0.0, 0.0), case_name(0.4, 0.0, 0.0)) and len(ps) == 3
    assert view.get(case_name(0.3, 0.0, 0.0)) is ps.get(case_name(0.3, 0.0, 0.0))
