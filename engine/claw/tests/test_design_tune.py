"""M17 tune 검증 — 설계점 목표 달성, 부호·캡 준수, infeasible 경로, 결정론."""

import math

import pytest

from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    LinearModelSet,
    OperatingPoint,
    PointSet,
    TuneTargets,
    case_name,
    tune_point,
    tune_points,
)
from claw.fcl.demo import demo_design_gains
from claw.plant import make_demo_aircraft
from claw.trim import linearize, trim_level

ACT = dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2)


@pytest.fixture(scope="module")
def setup():
    ac = make_demo_aircraft()
    design = demo_design_gains()
    tr = trim_level(ac, TrimCase("t", mach=0.6, alt=1000.0, fuel=200.0), fingerprint="fp")
    assert tr.converged
    return ac, design, tr, linearize(ac, tr)


def test_design_point_meets_targets(setup):
    """데모 설계점(M0.6)에서 자동 튜닝이 목표(PM≥50°/GM≥8dB, ζ 목표)를 달성한다."""
    _, design, _, lm = setup
    out = tune_point(lm, design, **ACT)
    assert out["status"] == "ok"
    g = out["gains"]
    assert set(g) == {
        "pitch.k_rate", "pitch.kp", "pitch.ki",
        "roll.k_rate", "roll.kp", "roll.ki", "yaw.k_rate",
    }
    for axis in ("pitch", "roll"):
        att = out["achieved"][f"{axis}_att"]
        assert att["pm_deg"] >= 50.0
        assert not (math.isfinite(att["gm_db"]) and att["gm_db"] < 8.0)
    # 피치 댐퍼는 작동기 캡(ωc≤9 rad/s, wn_sp≈9.2)이 먼저 묶는다 — ζ 목표 0.7 대신
    # 캡 내 최선 달성. 합격선(zeta_min 0.3)은 넘어야 한다
    pr = out["achieved"]["pitch_rate"]
    assert pr["capped"] or pr["zeta_sp"] == pytest.approx(0.7, abs=0.05)
    assert pr["zeta_sp"] >= 0.3
    assert out["achieved"]["yaw_rate"]["zeta_dr"] >= 0.45
    # 롤 댐퍼도 자기 목표로 잰다. 이 자리를 안 재면 캡이 **어느 플랜트에서** 걸렸는지가
    # 아무 데도 안 걸린다 — 실제로 캡이 요 댐퍼를 닫기 전 생 lat에서 판정하던 동안
    # λ가 목표 12의 1/16(0.76)로 나오면서도 위 단정은 전부 통과했다
    rr = out["achieved"]["roll_rate"]
    assert rr["roll_lambda"] == pytest.approx(rr["target"], rel=0.02), (
        f"롤 댐퍼가 목표 대역폭 미달 — {rr}"
    )


def test_signs_follow_design(setup):
    """게인 부호는 설계값이 보유 — 크기만 튜닝한다 (diagnose.py 방향 관례)."""
    _, design, _, lm = setup
    g = tune_point(lm, design, **ACT)["gains"]
    for slot in g:
        if g[slot] != 0.0 and design[slot] != 0.0:
            assert math.copysign(1.0, g[slot]) == math.copysign(1.0, design[slot]), slot


def _damper_poles(lm_axis, prior, x_rate, u_in, k):
    """댐퍼 폐루프 극 — 판정 플랜트는 **앞서 닫은 댐퍼까지 접은 A′**.

    물리 댐퍼 u = +k·rate → 특성식 1 − L (tune._damper_loop_stable과 동일 규약).
    """
    import control

    from claw.analysis import pi_loop
    from claw.design.closure import close_rates

    loop = pi_loop(close_rates(lm_axis, prior), x_out=x_rate, u_in=u_in,
                   kp=k, ki=0.0, sign=1.0, **ACT)
    return control.feedback(loop, 1, sign=1).poles()


def test_damper_closed_loop_stable_with_actuator(setup):
    """튜닝된 댐퍼는 작동기·지연 포함 폐루프가 안정 — 01 §4.2 실증 사고 재발 방지 가드.

    조성은 successive closure 순서 그대로다 (closure.py AXIS_SPECS "rates 순서 =
    닫는 순서") — 축·입력 목록을 여기 손으로 다시 적으면 정본과 갈린다.
    """
    from claw.design.closure import AXIS_SPECS
    from claw.trim import split_axes

    _, design, _, lm = setup
    out = tune_point(lm, design, **ACT)
    for lm_axis in split_axes(lm):
        prior = {}
        for group, x_rate, u_in in AXIS_SPECS[lm_axis.axis]["rates"]:
            slot = f"{group}.k_rate"
            k = out["gains"][slot]
            poles = _damper_poles(lm_axis, prior, x_rate, u_in, k)
            assert (poles.real < 0).all(), slot
            prior[slot] = k


def test_rate_plan_order_matches_closure_order():
    """_RATE_PLAN의 축별 순서 = AXIS_SPECS의 rates 순서 — 캡·검증이 같은 prior를 쓴다.

    이 둘이 갈리면 조용히 어긋난다. tune은 _RATE_PLAN 순서로 gains를 쌓아 prior를
    만들고(`spec_rates`), schedmap은 AXIS_SPECS를 `[:idx]`로 잘라 prior를 만든다 —
    순서가 다르면 설계 플랜트와 검증 플랜트가 달라지는데 어느 쪽도 예외를 안 낸다.
    (_RATE_PLAN을 pitch·roll·yaw로 뒤집으면 롤이 다시 capped로 떨어진다.)
    """
    from claw.design.closure import AXIS_SPECS
    from claw.design.tune import _RATE_PLAN

    for axis, spec in AXIS_SPECS.items():
        planned = [g for g, a, _, _ in _RATE_PLAN if a == axis]
        assert planned == [g for g, _, _ in spec["rates"]], axis


def test_raw_axis_is_the_wrong_stability_plant(setup):
    """생 축모델 판정은 **출하 손설계 게인조차** 불안정으로 본다 — 캡이 그걸 쓰면 안 되는 이유.

    캡을 생 lat에서 재던 동안 롤 댐퍼가 엔벨로프 전역에서 100분의 1로 깎이거나
    (capped) 아예 꺼졌다(no_stable_gain). 원인은 요 댐퍼가 안 닫힌 횡축 — 출하되지
    않는 구성이고, 거기서 뜨는 유일한 불안정근은 느린 나선이다 (이 설계점
    M0.6/h1000에서 2배 시간 ~470 s — 안정성 사고가 아니라 조종성 항목의 크기다).

    이 단정은 그 판정 기준 자체가 틀렸음을 고정한다: 같은 기준이 데모의 손설계
    게인을 불안정으로 판정하고, 요 댐퍼를 닫으면 같은 게인이 안정으로 나온다.
    한쪽만 성립하면 전제가 바뀐 것이니 캡의 플랜트 선택을 다시 봐야 한다.
    """
    from claw.trim import split_axes

    _, design, _, lm = setup
    _lon, lat = split_axes(lm)
    k_design = design["roll.k_rate"]
    assert k_design != 0.0

    raw = _damper_poles(lat, {}, "p", "da", k_design)
    assert (raw.real >= 0).any(), "생 lat에서 손설계 롤 댐퍼가 안정 — 이 테스트의 전제가 사라졌다"
    # 그 불안정근은 나선 하나뿐이고 발산이 느리다 (안정성 사고가 아니라 조종성 항목).
    # 가장 **빠른** 발산을 재야 한다 — 최솟값을 보면 근이 늘어도 통과한다
    unstable = [p.real for p in raw if p.real >= 0]
    assert len(unstable) == 1 and max(unstable) < 0.01, f"예상 밖 불안정 모드: {unstable}"

    closed = _damper_poles(lat, {"yaw.k_rate": design["yaw.k_rate"]}, "p", "da", k_design)
    assert (closed.real < 0).all(), "요 댐퍼를 닫아도 손설계 롤 댐퍼가 불안정 — 전제가 바뀌었다"


def test_infeasible_with_excess_delay(setup):
    """지연을 인위로 키우면 백오프 바닥에서 infeasible — 던지지 않고 결과로 낸다."""
    _, design, _, lm = setup
    out = tune_point(lm, design, actuator_wn=30.0, actuator_zeta=0.7,
                     delay_s=0.6, pade_order=2)
    assert out["status"] == "infeasible"
    assert any("structural_limit" in n for n in out["notes"])
    assert "pitch.kp" in out["gains"]  # 최선 달성 게인은 그래도 낸다


def test_deterministic(setup):
    _, design, _, lm = setup
    a = tune_point(lm, design, **ACT)
    b = tune_point(lm, design, **ACT)
    assert a["gains"] == b["gains"]


def test_tune_points_skips_untrimmable(setup):
    ac, design, _, _ = setup
    points = PointSet()
    trims = {}
    for m in (0.5, 0.7):
        case = TrimCase(name=case_name(m, 1000.0, 200.0), mach=m, alt=1000.0, fuel=200.0)
        tr = trim_level(ac, case, fingerprint="fp")
        trims[case.name] = tr
        pt = OperatingPoint(case=case, role=ROLE_ANCHOR, origin="coarse")
        pt.trimmable = True
        points.add(pt)
    bad = OperatingPoint(
        case=TrimCase(name=case_name(0.9, 1000.0, 200.0), mach=0.9, alt=1000.0, fuel=200.0),
        role=ROLE_ANCHOR, origin="coarse",
    )
    bad.trimmable = False
    points.add(bad)
    out = tune_points(ac, points, LinearModelSet(), trims, design=design, **ACT)
    assert out["skipped"] == [bad.case.name]
    assert set(out["results"]) == {case_name(0.5, 1000.0, 200.0), case_name(0.7, 1000.0, 200.0)}
    # gain surface 샘플 형식 — 자리별 {이름: 값}
    assert set(out["gains"]["pitch.kp"]) == set(out["results"])


def test_polish_does_not_break_criteria(setup):
    """선택적 마무리(polish=True) — 기본 OFF라 회귀에 안 걸리던 경로.

    대역폭을 밀어 올리되 합격선을 깨면 후퇴하는 계약이라, 켜도 마진이 나빠지면 안 된다.
    """
    _, design, _, lm = setup
    base = tune_point(lm, design, **ACT)
    pol = tune_point(lm, design, polish=True, max_evals=40, **ACT)
    assert pol["status"] == "ok"
    assert pol["evals"] > base["evals"]  # 마무리가 실제로 돌았다
    for axis in ("pitch", "roll"):
        b, p = base["achieved"][f"{axis}_att"], pol["achieved"][f"{axis}_att"]
        assert p["pm_deg"] >= 45.0, f"{axis} 폴리시가 합격선을 깼다"
        assert p["wcp"] >= b["wcp"] * 0.99, f"{axis} 폴리시가 대역폭을 되레 깎았다"


def test_polish_falls_back_when_budget_too_small(setup):
    """예산이 최소 미만이면 최적화를 돌리지 않고 원 게인을 그대로 낸다."""
    _, design, _, lm = setup
    base = tune_point(lm, design, **ACT)
    tiny = tune_point(lm, design, polish=True, max_evals=2, **ACT)
    assert tiny["gains"] == base["gains"]


def test_targets_reject_nonterminating_backoff():
    """백오프 루프의 종료가 이 검증에 걸려 있다 — 서버가 config로 받는 값이다.

    backoff ≥ 1이면 wc가 줄지 않고, floor_frac = 0이면 언더플로 후에도 조건이 참이라
    `_tune_att`가 영원히 돈다. 그 루프는 on_progress를 안 불러 취소도 안 된다.
    """
    with pytest.raises(ValueError, match="backoff"):
        TuneTargets(backoff=1.0)
    with pytest.raises(ValueError, match="backoff"):
        TuneTargets(backoff=0.0)
    with pytest.raises(ValueError, match="wc_att_floor_frac"):
        TuneTargets(wc_att_floor_frac=0.0)
    with pytest.raises(ValueError, match="wc_ratio_att"):
        TuneTargets(wc_ratio_att=0.0)
    with pytest.raises(ValueError, match="감쇠 목표"):
        TuneTargets(zeta_sp=0.0)
    TuneTargets()  # 기본값은 유효해야 한다


def test_cap_reports_no_stable_gain_separately(setup):
    """안정한 댐퍼 게인이 없는 경우와 경계까지 줄인 경우를 구분해 보고한다.

    lo가 0인 채 끝나면 "경계를 찾았다"가 아니라 댐퍼를 끈 것이다 — 한 플래그로
    뭉개면 로그가 "캡 적용"이라 말하면서 아무 댐핑도 없는 형상을 내놓는다.
    """
    import numpy as np

    from claw.common.contracts import LinearModel
    from claw.design.tune import _cap_by_stability
    from claw.trim import split_axes

    _, _design, _, lm = setup
    lon, _lat = split_axes(lm)
    # 개루프가 크게 불안정한 합성 종축 — 어떤 |k|도 안정화하지 못한다
    A = lon.A.copy()
    A[2, 2] += 40.0  # q̇/q 를 크게 양수로
    unstable = LinearModel(A=A, B=lon.B, C=lon.C, D=lon.D, x_names=lon.x_names,
                           u_names=lon.u_names, axis="lon")
    k, reason = _cap_by_stability(unstable, "q", "de", 0.4, ACT)
    assert reason == "no_stable_gain"
    assert k == 0.0
    # 정상 축에서는 캡이 아예 안 걸리거나(None) 경계까지 줄인다('capped')
    k2, reason2 = _cap_by_stability(lon, "q", "de", 0.4, ACT)
    assert reason2 in (None, "capped")


@pytest.fixture(scope="module")
def low_mach():
    """M0.2/h0 — 손설계 게인의 4배 브래킷이 실제로 좁은 저동압 점."""
    ac = make_demo_aircraft()
    design = demo_design_gains()
    tr = trim_level(ac, TrimCase("lo", mach=0.2, alt=0.0, fuel=40.0), fingerprint="fp")
    assert tr.converged
    return design, linearize(ac, tr)


def test_bracket_widens_until_the_plant_is_the_limit(low_mach):
    """"브래킷이 좁다"와 "플랜트가 못 한다"를 가른다 — 한 점에서 둘 다 나온다.

    초기 상한 4×|손설계 게인|은 **그 기체의 손튜닝이 얼마나 맞았나**에 달린 값이지
    플랜트가 낼 수 있는 한계가 아니다. 넓히지 않으면 둘 다 "목표 미달"로만 보고되어
    사용자가 게인을 더 밀어 볼 여지가 있는지 알 수 없다.

    이 점에서 실측(확장 전):
      roll λ  상한 0.8에서 8.65로 끊김 — |k|≈1.12면 목표 12에 닿는다  (브래킷 탓)
      yaw ζ_dr |k|≈1.55에서 0.477로 정점을 찍고 내려간다 — 어떤 상한에서도 못 닿는다
    """
    design, lm = low_mach
    out = tune_point(lm, design, **ACT)

    rr = out["achieved"]["roll_rate"]
    assert rr["reached"], f"롤 λ가 여전히 목표 미달 — {rr}"
    assert rr["bracket_growth"] > 0, "확장 없이 닿았다면 이 점이 브래킷을 재는 자리가 아니다"
    assert abs(out["gains"]["roll.k_rate"]) > 4.0 * abs(design["roll.k_rate"]), (
        "채택된 게인이 종전 브래킷 안이다 — 확장이 결과를 바꾸지 않았다"
    )

    yr = out["achieved"]["yaw_rate"]
    assert not yr["reached"], "요 ζ_dr이 닿았다면 이 점의 전제가 바뀌었다"
    assert yr["bracket_growth"] == 3, "끝까지 넓혀 보지도 않고 플랜트 탓이라 말하면 안 된다"
    assert any("플랜트가 그 지표를 못 낸다" in n for n in out["notes"])


def test_first_reach_separates_narrow_bracket_from_flat_plant():
    """확장 로직 단위 — 도달 가능한 목표는 넓혀서 찾고, 불가능한 목표는 최선을 낸다."""
    from claw.design.tune import _BRACKET_EXPANSIONS, _first_reach_bisect

    # 단조 증가: 목표 2.0은 초기 상한 1.0 밖 → 넓혀서 도달
    k, reached, grown = _first_reach_bisect(lambda x: x, 0.0, 1.0, 2.0)
    assert reached and grown == 1 and k == pytest.approx(2.0, abs=1e-3)
    # 봉우리형: 최대가 목표 아래 → 끝까지 넓혀 보고 argmax를 낸다
    k, reached, grown = _first_reach_bisect(lambda x: 1.0 - (x - 3.0) ** 2, 0.0, 1.0, 5.0)
    assert not reached and grown == _BRACKET_EXPANSIONS
    assert k == pytest.approx(3.0, abs=0.2), "최선 달성점(argmax)이 아니다"
    # 초기 브래킷 안에서 닿으면 넓히지 않는다 (쓸데없는 평가 금지)
    assert _first_reach_bisect(lambda x: x, 0.0, 1.0, 0.5)[1:] == (True, 0)


def test_cap_finds_conditionally_stable_window(monkeypatch):
    """안정 구간이 [k_lo>0, k_hi]면 순수 이분은 못 찾고 **댐퍼를 꺼 버린다**.

    이분은 "|k|가 커질수록 불안정"이라는 단조성을 전제한다. 그 전제는 개루프가 이미
    불안정한 플랜트(후방 CG·완화 정안정)와 조건부 안정에서 깨지고, 그때 lo가 0에
    머물러 no_stable_gain이 된다 — 존재하는 안정 구간을 두고 댐핑을 0으로 출하한다.

    판정식이 아니라 **탐색**의 결함이므로 안정 판정을 대역해 탐색만 잰다.

    구간은 **이분이 실제로 놓치는 폭**이어야 한다. [0.3, 0.7]처럼 넓으면 첫 중점
    0.5가 우연히 구간 안에 떨어져 순수 이분도 찾아낸다 — 그런 구간으로는 이 수정이
    무엇을 고쳤는지 잴 수 없다. [0.55, 0.60]에서는 이분이 0.5 → 0.25 → …로 계속
    아래로만 내려가 lo가 0에 머문다.
    """
    from claw.design import tune as T

    monkeypatch.setattr(T, "_damper_loop_stable",
                        lambda lm, x, u, k, act: 0.55 <= abs(k) <= 0.60)
    k, reason = T._cap_by_stability(None, "p", "da", -1.0, {})
    assert reason == "capped", "안정 구간이 있는데 댐퍼를 껐다"
    assert k == pytest.approx(-0.60, abs=1e-3)  # 구간 상단, 부호 유지

    # 단조 경우는 종전과 같은 답 — 넓힌 탐색이 보통 경로를 바꾸지 않는다
    monkeypatch.setattr(T, "_damper_loop_stable", lambda lm, x, u, k, act: abs(k) <= 0.42)
    assert T._cap_by_stability(None, "p", "da", 1.0, {}) == (
        pytest.approx(0.42, abs=1e-3), "capped")

    # 안정 표본이 정말 하나도 없을 때만 no_stable_gain
    monkeypatch.setattr(T, "_damper_loop_stable", lambda *a: False)
    assert T._cap_by_stability(None, "p", "da", -1.0, {}) == (0.0, "no_stable_gain")
