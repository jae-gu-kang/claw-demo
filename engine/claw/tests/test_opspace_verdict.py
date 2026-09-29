"""조건 판정 (05 §11.3 · 이관 8단계) — 트림 · 모델 · 제한 · 여유를 따로 판정하고, 자동 설계 채택은 그 결과와 공통 정책으로.

트림 탭(서버 /trim/batch)과 자동 설계(격자 채택·보강·마진 맵·튜닝·초기 게인 탐색)가 **같은 함수**로 판정해야 같은 조건에
같은 사유가 선다 — 종전에는 트림 탭이 조건 상태를, 자동 설계가 `envelope_ok` 한 비트를 따로 냈다."""

import copy
import dataclasses

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.opspace import COMPUTABLE, ModelRange, trim_assessment
from claw.opspace.verdict import VerdictContext, condition_verdict, margin_of
from claw.profile import build_profile
from claw.profile.document import load_shipped_example as load_example
from claw.trim import trim_level

WIDE_MODEL = ModelRange(mach=(0.0, 0.9), fuel=(0.0, 50.0))


@pytest.fixture(scope="module")
def example():
    return build_profile(load_example())


@pytest.fixture(scope="module")
def eoir():
    return build_profile(load_example(), "eoir")


def _trim(built, mach, alt, fuel):
    return trim_level(built.aircraft(), TrimCase(name="t", mach=mach, alt=alt, fuel=fuel))


def _with_alpha(tr, alpha):
    """해의 받음각만 바꾼 사본 — 제한·모델 검사의 경계를 짚는 데만 쓴다(판정은 받음각·여유 수치를 읽는다)."""
    v = float(np.hypot(tr.state.vel_b[0], tr.state.vel_b[2]))
    state = dataclasses.replace(tr.state, vel_b=np.array([v * np.cos(alpha), 0.0, v * np.sin(alpha)]))
    reserve = copy.deepcopy(tr.reserve)
    reserve["alpha"]["trim"] = alpha
    reserve["alpha"]["stall_reserve"] = reserve["alpha"]["stall"] - alpha
    flags = {**tr.flags, "alpha_margin_ok": bool(alpha < reserve["alpha"]["limit"])}
    return dataclasses.replace(tr, state=state, reserve=reserve, flags=flags)


# ── 여섯 항목이 따로 선다 ────────────────────────────────────────────────────
def test_comfortable_trim_is_adopted_with_every_check_met(example):
    v = condition_verdict(_trim(example, 0.18, 1000.0, 25.0), VerdictContext.from_profile(example))
    assert v["trim"] == {"status": COMPUTABLE, "reasons": []}
    assert v["model"] == {"status": "valid", "reasons": []}
    assert v["limits"] == {"status": "met", "reasons": []}
    assert v["margin"] == {"status": "met", "reasons": []}
    assert v["adopted"] is True and v["exclusion"] is None


def test_margin_short_trim_is_adopted_and_keeps_its_margin_flag(eoir):
    # EO/IR형 M0.28 2000 m·25 kg — 스로틀 95.1 %에서 수렴. 날 수 있는 평형이라 설계에 채택하고(사용자 결정 v1.65),
    # 추진 여유 미달 표시는 그대로 남긴다 — 여유 미달은 채택을 막지 않는다
    v = condition_verdict(_trim(eoir, 0.28, 2000.0, 25.0), VerdictContext.from_profile(eoir))
    assert v["trim"]["status"] == COMPUTABLE and v["margin"] == {"status": "short", "reasons": ["throttle_high"]}
    assert v["adopted"] is True and v["exclusion"] is None


def test_unconverged_trim_gets_the_evidence_based_trim_state(example):
    # 기체를 아는 문맥(from_profile)이면 미수렴도 트림 탭과 같은 근거 판정(trim_assessment)을 거친다 — 자동 설계와 트림 탭이
    # 같은 조건에 같은 트림 사유를 내게. assess=False(δe_trim 도출처럼 범주만 쓰는 호출자)면 수렴 여부만 본다
    tr = _trim(example, 0.5, 100.0, 25.0)
    ctx = VerdictContext.from_profile(example)
    v = condition_verdict(tr, ctx)
    assert v["trim"] == {"status": "infeasible", "reasons": ["thrust_deficit", "throttle_high"]}
    assert v["margin"]["status"] == "unevaluated" and v["exclusion"]["category"] == "trim"
    assert condition_verdict(tr, ctx, assess=False)["trim"] == {"status": "unassessed", "reasons": ["not_converged"]}


def test_a_given_trim_assessment_is_used_verbatim(example):
    # 트림 탭은 근거까지 잰 조건 상태를 이미 갖고 있다 — 판정은 그것을 다시 풀지 않고 그대로 싣는다
    tr = _trim(example, 0.5, 100.0, 25.0)
    a = trim_assessment(tr, example, WIDE_MODEL)
    v = condition_verdict(tr, VerdictContext.from_profile(example), trim=(a["state"], a["reasons"]))
    assert v["trim"] == {"status": "infeasible", "reasons": ["thrust_deficit", "throttle_high"]}
    assert v["exclusion"] == {"category": "trim", "reasons": ["thrust_deficit", "throttle_high"]}


# ── 제한: 실속 경계 · 동압 · M_NO · 리미터 ─────────────────────────────────────
def test_converged_trim_past_stall_is_a_stall_boundary_violation_not_infeasible(example):
    # 수치 평형은 있다(트림 계산 가능) — 허용 운용조건을 어긴 것이다. 두 사실을 따로 말한다
    tr = _trim(example, 0.18, 1000.0, 25.0)
    past = _with_alpha(tr, float(tr.reserve["alpha"]["stall"]) + 0.01)
    assert trim_assessment(past, example, WIDE_MODEL)["state"] == COMPUTABLE
    v = condition_verdict(past, VerdictContext.from_profile(example))
    assert "stall_boundary" in v["limits"]["reasons"] and v["limits"]["status"] == "violated"
    assert v["exclusion"]["category"] == "limits"


def test_limiter_clipping_the_trim_is_a_limit_violation(example):
    # 트림 α가 α 리미터 문턱(α_stall − law.alpha_margin) 위 — 정상비행 중에 리미터가 트림을 자른다. 실속 경계 아래라도 위반
    tr = _trim(example, 0.18, 1000.0, 25.0)
    a_stall = float(tr.reserve["alpha"]["stall"])
    lm = example.law["alpha_margin"]
    v = condition_verdict(_with_alpha(tr, a_stall - lm / 2), VerdictContext.from_profile(example))
    assert v["limits"]["reasons"] == ["limiter_clips_trim"]
    # 근거는 문턱 초과만이 아니라 리미터 작동식 — 수평 정상비행(θ = α)에서 θ_cmd ≤ α_max로 받음각이 묶인다
    d = v["limits"]["detail"]["limiter"]
    assert d["alpha_max"] == pytest.approx(a_stall - lm) and d["alpha_trim"] > d["alpha_max"]
    assert d["law"] == "theta_cmd <= theta + (alpha_max - alpha)"
    # 리미터를 끈 분석에는 적용하지 않는다
    off = dataclasses.replace(VerdictContext.from_profile(example), limiter_margin=None)
    assert condition_verdict(_with_alpha(tr, a_stall - lm / 2), off)["limits"]["status"] == "met"


def test_q_max_and_mach_no_are_checked_when_the_aircraft_has_them(example):
    tr = _trim(example, 0.18, 1000.0, 25.0)
    ctx = dataclasses.replace(VerdictContext.from_profile(example), q_max=100.0, mach_no=0.15)
    assert condition_verdict(tr, ctx)["limits"]["reasons"] == ["q_max", "mach_no"]
    # 없는 한계(null)는 검사하지 않는다 — 없는 데이터로 위반을 만들지 않는다
    assert condition_verdict(tr, dataclasses.replace(ctx, q_max=None, mach_no=None))["limits"]["status"] == "met"


def test_outside_the_stall_axis_the_declared_extrapolation_is_the_basis(example):
    # 실속표 축(M0.1~) 밖 — 근거 없음이 아니다. 외삽(clip)은 데이터가 선언한 정책이라 그 값(0.40)으로 판정한다
    tr = _trim(example, 0.18, 1000.0, 25.0)
    moved = dataclasses.replace(tr, case=dataclasses.replace(tr.case, mach=0.05))
    v = condition_verdict(moved, VerdictContext.from_profile(example))
    assert v["limits"]["status"] == "met" and v["margin"]["status"] == "met" and v["adopted"] is True


def test_without_a_stall_table_the_stall_items_are_unevaluated_not_passed(example):
    # 실속 근거 자체가 없으면 — 통과로 처리하지 않고 미평가로, 채택하지 않는다
    tr = _trim(example, 0.18, 1000.0, 25.0)
    base = VerdictContext.from_profile(example)
    ctx = dataclasses.replace(base, trim_bounds={k: v for k, v in base.trim_bounds.items() if k != "stall"})
    v = condition_verdict(tr, ctx)
    assert v["limits"] == {"status": "unevaluated", "reasons": ["stall_basis_missing"]}
    assert v["margin"]["status"] == "unevaluated" and "stall_basis_missing" in v["margin"]["reasons"]
    assert v["adopted"] is False and v["exclusion"]["category"] == "limits"


# ── 모델 유효성 ───────────────────────────────────────────────────────────────
def test_trim_alpha_outside_the_db_range_is_a_model_gap(example):
    tr = _trim(example, 0.18, 1000.0, 25.0)
    ctx = dataclasses.replace(VerdictContext.from_profile(example), db_ranges={"alpha": (0.2, 0.45), "mach": (0.0, 0.9)})
    v = condition_verdict(tr, ctx)
    assert v["model"] == {"status": "gap", "reasons": ["db_alpha"]}
    assert v["exclusion"]["category"] == "model"


def test_mach_outside_the_db_and_fuel_outside_the_tank_are_model_gaps(example):
    tr = _trim(example, 0.18, 1000.0, 25.0)
    ctx = dataclasses.replace(VerdictContext.from_profile(example), db_ranges={"mach": (0.2, 0.9)}, fuel_max=20.0)
    assert condition_verdict(tr, ctx)["model"]["reasons"] == ["db_mach", "fuel_range"]


# ── 여유 판정은 한 곳 ─────────────────────────────────────────────────────────
def test_trim_assessment_and_verdict_share_one_margin_rule(eoir):
    tr = _trim(eoir, 0.28, 2000.0, 25.0)
    assert trim_assessment(tr, eoir, WIDE_MODEL)["margin"] == margin_of(tr, eoir.trim_bounds)


def test_region_is_classified_from_the_context_not_the_model_state(example):
    # 요구영역 판정은 문맥이 든 요구영역으로 — 모델 부족 같은 트림 전 상태가 요구영역 칸에 섞이지 않는다
    ctx = VerdictContext.from_profile(example)
    inside = condition_verdict(_trim(example, 0.18, 1000.0, 25.0), ctx)
    assert inside["region"] == {"status": "in", "confirmed": True}
    outside = condition_verdict(_trim(example, 0.18, 5000.0, 25.0), ctx)
    assert outside["region"]["status"] == "out_of_region"
    assert outside["adopted"] is True  # 요구영역은 아직 채택에 쓰지 않는다(이관 2단계에서 격자가 요구영역에서 나온다)
    bare = dataclasses.replace(ctx, region=None)
    assert condition_verdict(_trim(example, 0.18, 1000.0, 25.0), bare)["region"] is None


# ── 트림 전 제외 (이관 2단계) — 기본 격자가 모델 부족·요구영역 밖·요구 미정의로 표시한 점 ─────────────────
@pytest.mark.parametrize("state, category, region_status", [
    ("model_gap", "model", "in"),  # 모델 부족은 요구 **안**이다 — 요구영역 칸에 모델 상태가 섞이지 않는다
    ("out_of_region", "region", "out_of_region"),
    ("undefined", "region", "undefined"),
])
def test_pre_trim_verdict_has_the_condition_verdict_shape_and_says_why(example, state, category, region_status):
    from claw.opspace.verdict import pre_trim_verdict

    ctx = VerdictContext.from_profile(example)
    v = pre_trim_verdict(state, ctx)
    ref = condition_verdict(_trim(example, 0.18, 1000.0, 25.0), ctx)
    assert set(v) == set(ref)  # 같은 모양 — 화면·보고가 한 형식으로 읽는다
    assert v["trim"] == {"status": state, "reasons": [state]}
    for item in ("model", "limits", "margin"):
        assert v[item] == {"status": "unevaluated", "reasons": []}  # 트림을 안 돌렸다 — 통과가 아니다
    assert v["region"] == {"status": region_status, "confirmed": True}
    assert v["adopted"] is False
    assert v["exclusion"] == {"category": category, "reasons": [state]}
    assert pre_trim_verdict(state, dataclasses.replace(ctx, region=None))["region"] is None


def test_pre_trim_verdict_refuses_states_decided_by_a_trim(example):
    from claw.opspace.verdict import pre_trim_verdict

    with pytest.raises(ValueError, match="트림 전"):
        pre_trim_verdict(COMPUTABLE, VerdictContext.from_profile(example))
