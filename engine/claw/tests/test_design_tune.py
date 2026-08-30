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
    """지연을 인위로 키우면 infeasible — 던지지 않고 결과로 낸다.

    사유는 **대역폭 붕괴**이지 마진 미달이 아니다. 지연 위상은 ω에 비례하므로 백오프가
    ωc를 버리면 마진은 거의 항상 만들어진다 — 이 점에서도 PM 86°·GM 10 dB로 목표를
    한참 넘긴 채 교차만 목표의 0.082배로 내려앉는다. 종전 note는 어느 경우든
    "백오프 바닥까지 PM/GM 미달"이라 적었는데, 그건 **여기서 일어나지 않는 일**이다.
    사유를 뭉개면 화면이 "마진이 모자란다"와 "성능이 무너졌다"를 구별해 안내할 수 없고,
    사용자는 마진을 늘리려 애쓰게 된다 — 늘려야 하는 것은 대역폭 예산이다.
    """
    from claw.design.tune import REASON_BANDWIDTH_COLLAPSE

    _, design, _, lm = setup
    out = tune_point(lm, design, actuator_wn=30.0, actuator_zeta=0.7,
                     delay_s=0.6, pade_order=2)
    assert out["status"] == "infeasible"
    slot = out["slots"]["pitch_att"]
    assert slot["reason"] == REASON_BANDWIDTH_COLLAPSE
    ach = out["achieved"]["pitch_att"]
    assert ach["pm_deg"] >= 50.0 and ach["gm_db"] >= 8.0, "마진은 통과한 상태여야 한다"
    assert ach["wc_att"] / ach["wc0"] < TuneTargets().wc_att_ok_frac
    assert any("교차 주파수가 하한 아래" in n for n in out["notes"])
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


def test_bracket_widens_when_the_target_is_reachable(low_mach):
    """초기 브래킷은 **손튜닝이 얼마나 맞았나**에 달린 값이지 플랜트의 한계가 아니다.

    이 점의 롤 λ는 상한 0.8에서 8.65로 끊겼는데 |k|≈1.12면 목표 12에 닿는다.
    넓히지 않으면 "목표 미달"로만 보고되어, 게인을 더 밀어 볼 여지가 있는지
    사용자가 알 수 없다.
    """
    design, lm = low_mach
    out = tune_point(lm, design, **ACT)
    rr = out["achieved"]["roll_rate"]
    assert rr["reached"], f"롤 λ가 여전히 목표 미달 — {rr}"
    assert rr["bracket_growth"] > 0, "확장 없이 닿았다면 이 점이 브래킷을 재는 자리가 아니다"
    assert abs(out["gains"]["roll.k_rate"]) > 4.0 * abs(design["roll.k_rate"]), (
        "채택된 게인이 종전 브래킷 안이다 — 확장이 결과를 바꾸지 않았다"
    )
    assert out["slots"]["roll_rate"]["reason"] == "ok"


def test_rate_metrics_are_reported_on_the_final_composition(low_mach):
    """레이트 자리의 보고값은 **세 자리가 다 닫힌 뒤**의 값이어야 한다.

    탐색은 successive closure 순서대로 프리픽스 조성에서 한다(요를 닫은 뒤 롤).
    그래서 요 차례에는 롤이 아직 열려 있는데, 검증(schedmap)은 세 자리를 다 닫고
    잰다. 프리픽스 값을 그대로 보고하면 튜너와 검증이 같은 자리에 다른 수를 말한다.

    이 점이 정확히 그 경우다 — 요 ζ_dr이 탐색 조성에서는 목표 0.5에 못 닿아
    브래킷을 끝까지(설계값 256배) 넓히고도 실패로 끝나지만, 롤 댐퍼가 닫힌 최종
    조성에서는 0.77이다. 그 차이가 판정을 뒤집는다: 종전에는 `target_unreached`가
    되어 "브래킷이 아니라 이 플랜트가 그 지표를 못 낸다"는 **단정**이 붙었고,
    그 단정이 다시 구조 한계 에스컬레이션으로 이어졌다. 출하되는 조성에서는
    목표를 넘기는 자리인데도.
    """
    from claw.design.closure import AXIS_SPECS, axis_metrics
    from claw.trim import split_axes

    design, lm = low_mach
    out = tune_point(lm, design, **ACT)
    yr = out["achieved"]["yaw_rate"]

    assert not yr["reached"], "탐색 조성에서 닿았다면 이 점의 전제가 사라졌다"
    assert yr["bracket_growth"] == 3, "끝까지 넓혀 보지도 않고 결론을 내면 안 된다"
    # 그런데 최종 조성에서는 목표를 넘긴다 → 사유는 ok이고 "플랜트 한계"가 아니다
    assert yr["zeta_dr"] >= 0.5
    assert out["slots"]["yaw_rate"]["reason"] == "ok"
    assert not any("플랜트가 그 지표를 못 낸다" in n for n in out["notes"]), (
        "출하 조성에서 목표를 넘기는 자리에 플랜트 한계라 단정했다")
    assert any("뒤에 닫힌 댐퍼가 끌어올렸다" in n for n in out["notes"]), (
        "탐색과 보고의 조성이 다르다는 사실이 어디에도 안 남았다")

    # 보고값이 **검증이 재는 그 값**인지 직접 대조한다 — 이게 이 수정의 요지다
    _lon, lat = split_axes(lm)
    closed_all = {f"{g}.k_rate": out["gains"][f"{g}.k_rate"]
                  for g, _, _ in AXIS_SPECS["lat"]["rates"]}
    assert yr["zeta_dr"] == axis_metrics(lat, closed_all)["zeta_dr"]
    # 프리픽스 조성(롤 열림)의 값과는 달라야 한다 — 같으면 판별력이 없는 테스트다
    prefix_only = {"yaw.k_rate": out["gains"]["yaw.k_rate"], "roll.k_rate": 0.0}
    assert yr["zeta_dr"] != axis_metrics(lat, prefix_only)["zeta_dr"]


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


@pytest.fixture(scope="module")
def bandwidth_collapse():
    """M0.7/h0 — 마진은 통과하는데 교차가 하한 아래로 내려가던 점."""
    ac = make_demo_aircraft()
    design = demo_design_gains()
    tr = trim_level(ac, TrimCase("bw", mach=0.7, alt=0.0, fuel=40.0), fingerprint="fp")
    assert tr.converged
    return design, linearize(ac, tr)


def test_rescue_polish_recovers_bandwidth_collapse(bandwidth_collapse):
    """백오프가 대역폭만 버려서 놓친 해를 마무리가 되찾는다.

    이 점의 자세 루프는 **마진이 모자라서** infeasible이던 게 아니다: 백오프 해가
    PM 103°·GM 9.6 dB로 목표를 크게 넘겼는데 교차가 목표의 0.168배까지 내려가
    대역폭 하한(0.2)에 걸렸다. 백오프는 ωc를 버려 마진을 사는 한 방향 탐색이라
    "마진은 남는데 대역폭이 없는" 해에서 멈춘다 — (kp, ki)를 함께 흔들면
    같은 마진에서 대역폭이 돌아온다.
    """
    from claw.design.tune import REASON_CAPPED, REASON_RESCUED

    design, lm = bandwidth_collapse
    out = tune_point(lm, design, **ACT)
    slot = out["slots"]["pitch_att"]
    assert slot["status"] == "ok", f"구제되지 않았다 — {out['notes']}"
    assert slot["reason"] == REASON_RESCUED
    ach = out["achieved"]["pitch_att"]
    assert ach["polished"] is True
    assert ach["wc_att"] / ach["wc0"] >= TuneTargets().wc_att_ok_frac
    assert ach["pm_deg"] >= 50.0 and ach["gm_db"] >= 8.0
    assert any("마무리로 구제" in n for n in out["notes"])
    # 이 점은 여전히 무결하지 않다 — 피치 댐퍼가 안정 캡에 묶여 ζ 목표에 못 간다.
    # 자세 자리를 구제했다고 점 전체를 ok로 적으면 그 사실이 지워진다
    assert out["slots"]["pitch_rate"]["reason"] == REASON_CAPPED
    assert out["status"] == "degraded"


def test_rescue_leaves_passing_slots_untouched(setup):
    """구제는 **실패한 자리에만** 돈다 — 통과한 자리까지 벌점 무릎으로 밀면
    전 운영점이 마진 경계에 앉고(작동기 공진에 가까워진다) 결과도 흔들린다."""
    _, design, _, lm = setup
    out = tune_point(lm, design, **ACT)
    assert out["status"] == "ok"
    for axis in ("pitch", "roll"):
        assert "polished" not in out["achieved"][f"{axis}_att"], axis
    assert not any("구제" in n for n in out["notes"])


def test_polish_initial_simplex_is_explicit(setup):
    """초기 simplex를 명시하지 않으면 마무리가 사실상 아무것도 안 한다.

    x0 = [0, 0]이라 scipy는 0 성분에 zdelt = 0.00025를 써서 **변 길이 0.025%**인
    simplex를 만든다. 종전 코드는 polish=True로 켜도 Δlog kp = 0.00025 그대로
    끝났다 — 켜져 있으나 없는 손잡이였다.
    """
    from claw.design.closure import AXIS_SPECS
    from claw.design.tune import _polish_att, _tune_att, _tune_rates
    from claw.trim import split_axes

    _, design, _, lm = setup
    lon, _lat = split_axes(lm)
    gains, ach, _ = _tune_rates(lon, _lat, design, TuneTargets(), ACT)
    rg = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
          for g, _, _ in AXIS_SPECS["lon"]["rates"]}
    kp0, ki0, a0, _st, _ev = _tune_att(
        lon, "pitch", rg, ach["pitch_rate"]["wc"], design, TuneTargets(), ACT)
    kp, _ki, a, _ev2 = _polish_att(
        lon, "pitch", rg, kp0, ki0, TuneTargets(), ACT, max_evals=60, wc0=a0["wc0"])
    assert abs(math.log(abs(kp / kp0))) > 0.01, (
        "마무리가 게인을 사실상 안 움직였다 — 기본 simplex(0.00025)로 되돌아갔다")
    assert a["wc_att"] > a0["wc_att"], "마무리의 목적은 같은 마진에서의 대역폭이다"
    assert a["pm_deg"] >= 50.0 and a["gm_db"] >= 8.0, "마진 벌점이 지켜지지 않았다"


def test_slot_status_survives_a_failing_sibling(setup):
    """한 자리가 실패해도 다른 자리의 판정이 지워지면 안 된다.

    점 단위 status 하나뿐이던 동안 분류기가 그걸 자리 단위 판정에 썼다 — 피치가
    안 되는 점의 롤 실패까지 "상위 설계 문제(에스컬레이션)"로 넘어가, 실행 가능한
    처방(승격·재적합)이 사라졌다. 그 오귀속을 막을 **재료**가 여기 있어야 한다.
    """
    _, design, _, lm = setup
    out = tune_point(lm, design, actuator_wn=30.0, actuator_zeta=0.7,
                     delay_s=0.6, pade_order=2)
    assert out["status"] == "infeasible"  # 점 전체로는 실패인데…
    assert out["slots"]["pitch_att"]["status"] == "infeasible"
    assert out["slots"]["roll_att"]["status"] == "ok"  # …이 자리는 멀쩡하다
    assert set(out["slots"]) == {
        "pitch_rate", "yaw_rate", "roll_rate", "pitch_att", "roll_att"}


def test_zero_design_slot_is_na_not_failure(setup):
    """설계값 0인 자리는 튜닝을 **안 한** 것이지 실패한 것이 아니다."""
    from claw.design.tune import REASON_ZERO_DESIGN

    _, design, _, lm = setup
    out = tune_point(lm, {**design, "yaw.k_rate": 0.0}, **ACT)
    slot = out["slots"]["yaw_rate"]
    assert slot["status"] == "na" and slot["reason"] == REASON_ZERO_DESIGN
    assert out["gains"]["yaw.k_rate"] == 0.0
    # na가 점 status를 실패로 끌어내리지 않는다 (판정 불가 ≠ 불합격)
    assert out["status"] != "infeasible"


def test_unmeasurable_margin_is_not_a_pass():
    """nan(판정 불가)과 inf(무한 여유)를 가른다 — 종전 식은 둘을 같이 통과시켰다.

    `loop_margins`는 그 둘을 일부러 구분해 낸다(margins.py: "판정 불가를 무한 여유로
    오인하지 않도록 nan 유지"). 그런데 수용식이
        gm_ok = not (isfinite(gm) and gm < target)
    라 `isfinite`가 False인 두 경우를 똑같이 통과로 쳤다. PM은 반대로 nan이면
    불통과였다 — 한 판정식 안에서 같은 값에 다른 규약을 쓴 셈이고, 그래서
    "GM을 못 잰 자리"가 조용히 설계 목표 달성으로 기록됐다.
    """
    from claw.design.tune import _att_margin_verdict

    tg = TuneTargets()  # PM 50° / GM 8 dB
    assert _att_margin_verdict({"pm_deg": 60.0, "gm_db": 12.0}, tg) == "ok"
    # 무한 여유는 통과다 — 그 축에 잘라 낼 이득이 없다는 뜻이다
    assert _att_margin_verdict({"pm_deg": 60.0, "gm_db": float("inf")}, tg) == "ok"
    # 판정 불가는 통과가 아니다
    assert _att_margin_verdict({"pm_deg": 60.0, "gm_db": float("nan")}, tg) == "na"
    assert _att_margin_verdict({"pm_deg": float("nan"), "gm_db": 12.0}, tg) == "na"
    assert _att_margin_verdict({"pm_deg": 40.0, "gm_db": 12.0}, tg) == "short"


def test_envelope_check_is_one_helper_for_all_three_stages():
    """엔벨로프 판정을 세 곳이 각자 하면 같은 조건의 점이 갈린다.

    schedmap만 `converged`를 봤고 grid·refine은 포화·α 여유까지 봤다. 그래서
    **트림은 되지만 포화하는 중점 검증점**은 `outside_envelope` 표시를 못 받고
    판정·승격·튜닝까지 흘러갔는데, 같은 조건의 coarse 앵커는 TUNE이 건너뛰고
    실패 목록에서도 빠졌다.
    """
    import inspect

    from claw.design import grid, refine, schedmap
    from claw.design.points import envelope_ok

    class _T:
        def __init__(self, conv, sat, alpha):
            self.converged, self.flags = conv, {
                "saturation_ok": sat, "alpha_margin_ok": alpha}

    assert envelope_ok(_T(True, True, True)) is True
    assert envelope_ok(_T(True, False, True)) is False  # 포화 — 엔벨로프 경계다
    assert envelope_ok(_T(True, True, False)) is False  # α 여유 미달
    assert envelope_ok(_T(False, True, True)) is False  # 미수렴

    # 세 모듈이 **그 헬퍼를 부른다** — 각자 다시 적으면 이 단정이 무의미해진다
    for mod in (grid, refine, schedmap):
        src = inspect.getsource(mod)
        assert "envelope_ok(" in src, mod.__name__
        assert 'flags.get("saturation_ok")' not in src, (
            f"{mod.__name__}이 엔벨로프 조건을 다시 적었다")
