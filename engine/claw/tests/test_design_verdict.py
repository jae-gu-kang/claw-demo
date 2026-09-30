"""자동 설계가 공통 조건 판정을 쓴다 (이관 8단계 · 05 §11.3) — 같은 조건이면 트림 탭 판정과 자동 설계 채택·제외 사유가 같다.

종전에는 `design.points.envelope_ok`(수렴 ∧ 포화 여유 ∧ α 여유) 한 비트가 격자·보강·마진 맵·튜닝의 채택을 정했고,
δe_trim 도출은 `saturation_ok`로 따로 걸렀다. 이제 셋 다 `opspace.verdict.condition_verdict` 하나를 본다."""

import dataclasses

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_DESIGN,
    LinearModelSet,
    MarginCriteria,
    OperatingPoint,
    PointSet,
    case_name,
    coarse_grid,
    scheduled_margin_map,
)
from claw.design.points import envelope_ok, envelope_verdict
from claw.fcl.demo import demo_design_gains, make_demo_gain_tables
from claw.opspace.verdict import VerdictContext, condition_verdict
from claw.profile import build_profile, example_profile, load_shipped_example
from claw.profile.derive import derive_de_trim
from claw.trim import trim_level


@pytest.fixture(scope="module")
def legacy():
    built = example_profile()
    return built, built.aircraft(), VerdictContext.from_profile(built)


@pytest.fixture(scope="module")
def eoir():
    return build_profile(load_shipped_example(), "eoir")


def _trim(ac, mach, alt, fuel):
    return trim_level(ac, TrimCase(name=case_name(mach, alt, fuel), mach=mach, alt=alt, fuel=fuel))


# ── envelope_ok · envelope_verdict — 판정 정본은 condition_verdict 하나 ─────────────
def test_envelope_ok_needs_the_verdict_context_and_is_its_adoption(legacy):
    _, ac, ctx = legacy
    tr = _trim(ac, 0.4, 1000.0, 200.0)
    with pytest.raises(TypeError):
        envelope_ok(tr)  # 옛 정의(한 비트)로 조용히 되돌아가는 길이 없다 — 두 정의를 없애는 것이 목적이다
    for m in (0.2, 0.4, 0.6, 0.75):
        tr = _trim(ac, m, 1000.0, 200.0)
        assert envelope_ok(tr, ctx) is condition_verdict(tr, ctx)["adopted"], m


def test_envelope_verdict_keeps_the_legacy_reason_order_then_adds_the_verdict_codes(legacy):
    _, ac, ctx = legacy
    good = _trim(ac, 0.4, 1000.0, 200.0)
    v = envelope_verdict(good, ctx)
    assert v["ok"] is True and v["reasons"] == [] and v["verdict"] == condition_verdict(good, ctx)
    assert set(v["reserve"]) == {"de_frac", "thr_reserve", "alpha_stall_reserve", "alpha_limit"}

    # M0.6 h1000 f200 — 스로틀 95.04 %(test_trim.py DESIGN_POINT). 옛 사유 코드는 그대로 싣되, 여유 미달은 채택을 막지
    # 않는다(v1.65 채택 정책) — 수렴한 평형이라 채택하고 여유 미달 표시만 남긴다
    sat = _trim(ac, 0.6, 1000.0, 200.0)
    v = envelope_verdict(sat, ctx)
    assert v["ok"] is True and v["reasons"] == ["saturated_throttle_high"]
    assert v["verdict"]["exclusion"] is None
    assert v["verdict"]["margin"] == {"status": "short", "reasons": ["throttle_high"]}

    # 리미터가 트림을 못 잡는 점 — 해면 공허 M0.175(α_trim이 α_stall − 리미터 여유를 넘는다). 제한 위반으로 빠지고
    # 근거(작동식·수치)를 limits.detail.limiter에 싣는다
    clip = _trim(ac, 0.175, 0.0, 0.0)
    v = envelope_verdict(clip, ctx)
    assert clip.converged and v["ok"] is False and v["reasons"] == ["limiter_clips_trim"]
    assert v["verdict"]["exclusion"] == {"category": "limits", "reasons": ["limiter_clips_trim"]}
    lim = v["verdict"]["limits"]["detail"]["limiter"]
    assert lim["alpha_trim"] > lim["alpha_max"] and lim["law"] == "theta_cmd <= theta + (alpha_max - alpha)"

    # 같은 해를 M_NO 밖·DB 밖 마하에 둔다 — 옛 사유(포화)가 먼저, 새 사유(모델·제한)가 뒤에 중복 없이. 실속표 축 밖은
    # 선언된 외삽(clip)으로 판정하므로 근거 없음 사유가 붙지 않는다
    far = dataclasses.replace(sat, case=dataclasses.replace(sat.case, mach=0.95))
    v = envelope_verdict(far, ctx)
    assert v["reasons"][0] == "saturated_throttle_high"
    assert v["reasons"][1:] == ["db_mach", "mach_no"]
    assert len(set(v["reasons"])) == len(v["reasons"])
    assert v["ok"] is False and v["verdict"]["exclusion"] == {"category": "model", "reasons": ["db_mach"]}

    # 미수렴 — 옛 코드 not_converged가 맨 앞이다(웹 스캔 라벨이 첫 항목을 대표로 쓴다)
    bad = dataclasses.replace(good, converged=False)
    v = envelope_verdict(bad, ctx)
    assert v["reasons"][0] == "not_converged" and v["verdict"]["exclusion"]["category"] == "trim"


# ── OperatingPoint.verdict 왕복 ───────────────────────────────────────────────────
def test_operating_point_carries_the_verdict_through_serialisation(legacy):
    _, ac, ctx = legacy
    tr = _trim(ac, 0.6, 1000.0, 200.0)
    pt = OperatingPoint(case=tr.case, role=ROLE_DESIGN, origin="coarse")
    pt.verdict = condition_verdict(tr, ctx)
    pt.trimmable = pt.verdict["adopted"]
    d = PointSet([pt]).to_dict()
    back = PointSet.from_dict(d).get(tr.case.name)
    assert back.verdict == pt.verdict and back.trimmable is True  # 여유 미달이지만 채택 — 표시는 판정에 남는다
    assert back.verdict["margin"]["status"] == "short"
    # 옛 결과에는 verdict 칸이 없다 — 미판정(None)으로 읽는다
    old = {k: v for k, v in d["points"][0].items() if k != "verdict"}
    assert OperatingPoint.from_dict(old).verdict is None


# ── 마진 맵 — 제외 점에 범주와 사유를 싣는다 ─────────────────────────────────────
def test_margin_map_names_the_exclusion_category(legacy):
    """M0.45는 여유 충족, M0.6은 여유 미달(스로틀 95.04 %)이지만 채택 — 둘 다 판정 우주 안이다. 해면 공허 M0.175는
    리미터가 트림을 못 잡아 제한 위반 — 마진은 내되 엔벨로프 실경계로 빠지고 범주·사유를 싣는다."""
    _, ac, ctx = legacy
    coords = ((0.45, 1000.0, 200.0), (0.6, 1000.0, 200.0), (0.175, 0.0, 0.0))
    ps = PointSet([OperatingPoint(case=TrimCase(name=case_name(*c), mach=c[0], alt=c[1], fuel=c[2]),
                                  role=ROLE_DESIGN, origin="coarse") for c in coords])
    out = scheduled_margin_map(ac, ps, LinearModelSet(), make_demo_gain_tables(), demo_design_gains(),
                               criteria=MarginCriteria(), trims={}, ctx=ctx,
                               actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035)
    inside, short, clip = (out["cases"][case_name(*c)] for c in coords)
    for entry in (inside, short):
        assert "outside_envelope" not in entry and "exclusion" not in entry
    assert ps.get(case_name(*coords[1])).verdict["margin"]["status"] == "short"
    assert clip["outside_envelope"] is True
    assert clip["exclusion"] == {"category": "limits", "reasons": ["limiter_clips_trim"]}
    assert "제한 위반" in clip["note"] and "포화·α" not in clip["note"]
    assert ps.get(case_name(*coords[2])).verdict["exclusion"] == clip["exclusion"]


def test_margin_map_without_a_context_refuses_to_judge_new_points(legacy):
    _, ac, _ctx = legacy
    ps = PointSet([OperatingPoint(case=TrimCase(name=case_name(0.45, 1000.0, 200.0), mach=0.45, alt=1000.0, fuel=200.0),
                                  role=ROLE_DESIGN, origin="coarse")])
    with pytest.raises(ValueError, match="판정 문맥"):
        scheduled_margin_map(ac, ps, LinearModelSet(), make_demo_gain_tables(), demo_design_gains(),
                             criteria=MarginCriteria(), trims={})


# ── 완료 기준: 같은 조건이면 트림 탭 판정 = 자동 설계 기록 ─────────────────────────
def test_auto_design_records_the_same_exclusion_as_the_trim_tab_verdict(eoir):
    """EO/IR형 설계 격자 — 채택·제외 사유가 트림 탭(서버 /trim/batch)이 같은 조건에 내는 판정과 점마다 같다.

    탭 쪽은 **라우트가 만드는 방식 그대로** 만든다 — 근거까지 잰 조건 상태(trim_assessment)를 trim=으로 넘긴다. 같은
    함수를 자기 자신과 비교하면 라우트가 trim=을 빼거나 바꿔도 통과한다(v1.65 리뷰가 잡은 빈 테스트)."""
    from claw.opspace import model_range_of, trim_assessment

    ctx = VerdictContext.from_profile(eoir)
    grid = coarse_grid(eoir.aircraft(), eoir.stall_table(), eoir.structural_limits(), eoir.db_ranges(), ctx=ctx)
    points = list(grid["points"])
    tab_ctx, model = VerdictContext.from_profile(eoir), model_range_of(eoir)
    for pt in points:
        tr = grid["trims"][pt.name]
        a = trim_assessment(tr, eoir, model, cache=tab_ctx.cache)
        tab = condition_verdict(tr, tab_ctx, trim=(a["state"], a["reasons"]))
        assert pt.verdict == tab, pt.name
        assert pt.trimmable is tab["adopted"], pt.name
    excluded = [pt for pt in points if not pt.trimmable]
    assert excluded, "제외 점이 없으면 사유 일치를 재는 테스트가 아니다"
    # 여유(margin)는 채택을 막지 않는다 — 제외 범주는 트림·모델·제한 셋뿐이다(v1.65 채택 정책)
    assert all(pt.verdict["exclusion"]["category"] in ("trim", "model", "limits") for pt in excluded)
    # 트림 제외 사유는 「미수렴」 한 낱말이 아니라 근거까지 잰 조건 상태다 — 추력 부족이 실제로 선다
    trim_reasons = [r for pt in excluded if pt.verdict["exclusion"]["category"] == "trim"
                    for r in pt.verdict["exclusion"]["reasons"]]
    assert "thrust_deficit" in trim_reasons, trim_reasons


def test_resumed_pre_v165_session_is_rejudged_under_the_current_policy(eoir):
    # v1.65 전에 저장된 세션은 점에 verdict가 없고 trimmable이 옛 한 비트(여유 미달 = False)다. 재개 때 그대로 두면 한 세션
    # 안에 두 정책이 섞인다 — 옛 점은 여유 미달을 빼고 새 검증점은 넣는다. 문맥이 오면 트림이 남아 있는 옛 점을 다시 판정한다
    from claw.design.orchestrator import DesignSession

    ctx = VerdictContext.from_profile(eoir)
    grid = coarse_grid(eoir.aircraft(), eoir.stall_table(), eoir.structural_limits(), eoir.db_ranges(), ctx=ctx)
    short = [pt for pt in grid["points"] if pt.verdict["adopted"] and pt.verdict["margin"]["status"] == "short"]
    assert short, "여유 미달 채택점이 있어야 옛 정책과 갈리는 것을 잰다"
    for pt in grid["points"]:  # 옛 저장본 흉내 — 판정 없음, 옛 한 비트
        tr = grid["trims"][pt.name]
        pt.trimmable = bool(tr.converged and tr.flags.get("saturation_ok") and tr.flags.get("alpha_margin_ok"))
        pt.verdict = None
    s = DesignSession()
    s.points, s.trims, s.verdict_ctx = grid["points"], dict(grid["trims"]), ctx
    s._rejudge_legacy_points()
    for pt in grid["points"]:
        assert pt.verdict == condition_verdict(grid["trims"][pt.name], ctx), pt.name
        assert pt.trimmable is pt.verdict["adopted"]
    assert all(pt.trimmable for pt in short)


def test_run_refuses_to_judge_without_a_context():
    # 판정 문맥이 없으면 점을 판정하는 단계 전에 이름으로 멈춘다 — 트림 콜백 안의 AttributeError가 아니라
    from claw.design.orchestrator import DesignSession

    with pytest.raises(ValueError, match="verdict_ctx"):
        DesignSession().run(None, None, None, None, None, verdict_ctx=None)


# ── δe_trim 도출 — 여유 미달 트림도 요구다, 제한 위반은 아니다 ─────────────────────
def test_derive_counts_a_margin_short_trim_but_not_a_limit_violation(eoir):
    """EO/IR형 M0.28 2000 m 25 kg — 스로틀 95.1 %로 수렴(여유 미달). 날 수 있는 평형이라 그 δe는 예약해야 할 요구다
    (종전에는 포화라며 뺐다). 같은 트림도 M_NO를 그 아래로 둔 기체에서는 제한 위반이라 요구가 아니다."""
    fuel = 25.0
    frac = fuel / eoir.doc["mass"]["fuel_max"]
    kw = dict(machs=(0.2, 0.24, 0.28), alts=(2000.0,), fuel_fracs=(frac,), check_step=0.04)
    tr = _trim(eoir.aircraft(), 0.28, 2000.0, fuel)
    v = condition_verdict(tr, VerdictContext.from_profile(eoir))
    assert v["adopted"] is True and v["margin"] == {"status": "short", "reasons": ["throttle_high"]}
    assert tr.flags["saturation_ok"] is False  # 종전 규칙이 뺐던 트림이다
    out = derive_de_trim(eoir, **kw)
    req = dict(zip(out["requirement"]["mach"], out["requirement"]["need"]))
    assert req[0.28] == pytest.approx(abs(float(tr.control.elevon[0])), rel=0, abs=1e-12)
    prov = out["alloc"]["de_trim"]["provenance"]
    assert prov["excluded_trims"] == 0 and prov["excluded_by"] == {}

    doc = load_shipped_example()
    doc["structural"]["mach_no"] = 0.26
    capped = build_profile(doc, "eoir")
    assert condition_verdict(_trim(capped.aircraft(), 0.28, 2000.0, fuel), VerdictContext.from_profile(capped))[
        "exclusion"] == {"category": "limits", "reasons": ["mach_no"]}
    out = derive_de_trim(capped, **kw)
    assert 0.28 not in out["requirement"]["mach"]
    prov = out["alloc"]["de_trim"]["provenance"]
    assert prov["excluded_trims"] == 1 and prov["excluded_by"] == {"limits": 1}
