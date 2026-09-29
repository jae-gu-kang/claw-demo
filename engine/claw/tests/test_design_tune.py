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


def _guard_off(mp):
    """레이트 루프 마진 가드(AS94900 끊은 루프 여유 — tune._rate_margin_verdict)를 끈다. 가드가 없던 때의 튜너와 같다."""
    from claw.design import tune as T

    mp.setattr(T, "_rate_margin_verdict", lambda m, targets: "ok")


@pytest.fixture
def no_rate_margin_guard(monkeypatch):
    """이 시험의 대상은 다른 기구(브래킷·2차 패스·부호·구제·전체 폐루프 등)다 — 그 기구의 수치는 가드 없이 쟀고, 이 픽스처
    점들(구 기체·쇼케이스 저동압)은 레이트 루프 여유가 설계 목표 아래라 가드가 댐퍼를 묶어 다른 점이 된다(구 기체 M0.45
    피치 GM 5.6 dB·요 PM 41°, M0.6 요 PM 22°·GM 3.7 dB). 가드 자체는 test_rate_margin_guard_*가 잰다."""
    _guard_off(monkeypatch)


@pytest.fixture(scope="module")
def setup():
    ac = make_demo_aircraft()
    design = demo_design_gains()
    tr = trim_level(ac, TrimCase("t", mach=0.45, alt=1000.0, fuel=200.0), fingerprint="fp")
    assert tr.converged
    return ac, design, tr, linearize(ac, tr)


def test_design_point_meets_targets(setup):
    """데모 설계점(구 기체 M0.45/h1000)에서 자동 튜닝이 목표(PM≥50°/GM≥8dB)를 지킨다 — 자세 루프와 **레이트 루프 둘 다**.

    레이트 루프 여유(AS94900 끊은 루프 — 같은 축 다른 레이트 루프 닫음, 작동기 30 rad/s·지연 35 ms)를 재기 전에는 이 점이
    status "ok"였다: 피치 댐퍼는 ζ_sp 목표 0.7에서 GM 7.66 dB, 롤 댐퍼는 λ 목표 12에서 GM 4.84 dB·PM 39.2°(합격선 6 dB·
    45° 아래)였는데 판정은 모드 지표만 봤다. 이제 마진 가드가 둘을 여유 목표(+가드 밴드 0.25 dB)에서 묶는다 — 피치
    ζ_sp 0.668, 롤 λ 8.29(capped — 점은 degraded). 요 댐퍼는 목표 ζ_dr에서 여유가 이미 목표 위라 손대지 않는다."""
    _, design, _, lm = setup
    out = tune_point(lm, design, **ACT)
    assert out["status"] == "degraded"
    g = out["gains"]
    assert set(g) == {
        "pitch.k_rate", "pitch.kp", "pitch.ki",
        "roll.k_rate", "roll.kp", "roll.ki", "yaw.k_rate",
    }
    for axis in ("pitch", "roll"):
        att = out["achieved"][f"{axis}_att"]
        assert att["pm_deg"] >= 50.0
        assert not (math.isfinite(att["gm_db"]) and att["gm_db"] < 8.0)
    # 레이트 루프 여유 — 세 자리 모두 설계 목표 위(보고는 최종 조성)
    for loop in ("pitch_rate", "yaw_rate", "roll_rate"):
        r = out["achieved"][loop]
        assert r["pm_deg"] >= 50.0 - 1e-6 and r["gm_db"] >= 8.0 - 1e-6, (loop, r["pm_deg"], r["gm_db"])
    # 여유가 묶은 자리는 그렇다고 말한다 — 지표는 목표 아래지만 합격선(ζ 0.3 · λ 목표의 0.5배) 위의 작동하는 댐퍼다
    for loop in ("pitch_rate", "roll_rate"):
        assert out["slots"][loop]["reason"] == "capped" and out["achieved"][loop]["cap_bound"] == "margin", loop
    pr, rr = out["achieved"]["pitch_rate"], out["achieved"]["roll_rate"]
    assert pr["zeta_sp"] == pytest.approx(0.6683, abs=2e-3)
    assert pr["gm_db"] == pytest.approx(8.25, abs=1e-3) and rr["gm_db"] == pytest.approx(8.25, abs=1e-3)
    # 롤 댐퍼도 자기 목표로 잰다. 이 자리를 안 재면 캡이 **어느 플랜트에서** 걸렸는지가
    # 아무 데도 안 걸린다 — 실제로 캡이 요 댐퍼를 닫기 전 생 lat에서 판정하던 동안
    # λ가 목표 12의 1/16(0.76)로 나오면서도 위 단정은 전부 통과했다
    assert rr["roll_lambda"] == pytest.approx(8.291, abs=0.01) and rr["roll_lambda"] > 0.5 * rr["target"]
    assert out["slots"]["yaw_rate"]["reason"] == "ok" and out["achieved"]["yaw_rate"].get("cap_bound") is None
    assert out["achieved"]["yaw_rate"]["zeta_dr"] == pytest.approx(TuneTargets().zeta_dr, rel=1e-3)


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
    for m in (0.35, 0.45):
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
    assert set(out["results"]) == {case_name(0.35, 1000.0, 200.0), case_name(0.45, 1000.0, 200.0)}
    # gain surface 샘플 형식 — 자리별 {이름: 값}
    assert set(out["gains"]["pitch.kp"]) == set(out["results"])


def test_polish_does_not_break_criteria(setup, no_rate_margin_guard):
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
    k, reason = _cap_by_stability(unstable, "pitch", "q", "de", 0.4, ACT)
    assert reason == "no_stable_gain"
    assert k == 0.0
    # 정상 축에서는 캡이 아예 안 걸리거나(None) 경계까지 줄인다('capped')
    k2, reason2 = _cap_by_stability(lon, "pitch", "q", "de", 0.4, ACT)
    assert reason2 in (None, "capped")


@pytest.fixture(scope="module")
def low_mach():
    """M0.2/h0 — 손설계 게인의 4배 브래킷이 실제로 좁은 저동압 점."""
    ac = make_demo_aircraft()
    design = demo_design_gains()
    tr = trim_level(ac, TrimCase("lo", mach=0.2, alt=0.0, fuel=40.0), fingerprint="fp")
    assert tr.converged
    return design, linearize(ac, tr)


def test_bracket_widens_when_the_target_is_reachable(low_mach, no_rate_margin_guard):
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


def test_rate_metrics_are_reported_on_the_final_composition(low_mach, no_rate_margin_guard):
    """레이트 자리의 보고값은 **세 자리가 다 닫힌 뒤**의 값이어야 한다.

    탐색은 successive closure 순서대로 프리픽스 조성에서 한다(요를 닫은 뒤 롤).
    그래서 요 차례에는 롤이 아직 열려 있는데, 검증(schedmap)은 세 자리를 다 닫고
    잰다. 프리픽스 값을 그대로 보고하면 튜너와 검증이 같은 자리에 다른 수를 말한다.

    이 점이 정확히 그 경우다 — 요 ζ_dr이 탐색 조성에서는 목표(기본 0.6 — 종전 0.5에도)에
    못 닿아 브래킷을 끝까지(설계값 256배) 넓히고도 실패로 끝나지만, 롤 댐퍼가 닫힌 최종
    조성에서는 0.77이다. 종전에는 그 차이로 `target_unreached`가 되어 "브래킷이 아니라
    이 플랜트가 그 지표를 못 낸다"는 **단정**이 붙었다. 이제는 거기서 한 걸음 더 간다 —
    롤을 닫은 조성에서 요를 다시 찾아(2차 패스) argmax 1.5 대신 목표에 처음 닿는 1.089를
    쓴다(최종 조성 ζ_dr 0.7736 → 0.6 — 목표 0.5였을 때는 0.858). 보고값은 여전히 검증이
    재는 그 값이어야 한다.
    """
    from claw.design.closure import AXIS_SPECS, axis_metrics
    from claw.trim import split_axes

    design, lm = low_mach
    out = tune_point(lm, design, **ACT)
    yr = out["achieved"]["yaw_rate"]

    # 1차 패스는 탐색 조성에서 못 닿아 브래킷을 끝까지 넓혔다 — 그 값이 기록으로 남는다
    sp = yr["second_pass"]
    assert sp["adopted"] is True
    assert sp["k_first"] == pytest.approx(1.5, rel=1e-3)
    assert sp["metric_first"] == pytest.approx(0.7736, abs=1e-3)
    # 2차 패스는 롤을 닫은 조성에서 목표에 **처음** 닿는 크기 — 1차보다 작고 목표 달성
    assert out["gains"]["yaw.k_rate"] == pytest.approx(1.0886, rel=2e-3)
    assert yr["reached"] and yr["zeta_dr"] == pytest.approx(TuneTargets().zeta_dr, rel=1e-3)
    assert out["slots"]["yaw_rate"]["reason"] == "ok"
    assert not any("플랜트가 그 지표를 못 낸다" in n for n in out["notes"]), (
        "출하 조성에서 목표를 넘기는 자리에 플랜트 한계라 단정했다")
    assert any("다시 찾았다" in n for n in out["notes"]), "재탐색 사실이 어디에도 안 남았다"
    # 롤은 1차 패스 값 그대로 닫혀 있고 여전히 목표를 낸다
    assert out["slots"]["roll_rate"]["reason"] == "ok"

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
                        lambda lm, grp, x, u, k, act: 0.55 <= abs(k) <= 0.60)
    k, reason = T._cap_by_stability(None, "roll", "p", "da", -1.0, {})
    assert reason == "capped", "안정 구간이 있는데 댐퍼를 껐다"
    assert k == pytest.approx(-0.60, abs=1e-3)  # 구간 상단, 부호 유지

    # 단조 경우는 종전과 같은 답 — 넓힌 탐색이 보통 경로를 바꾸지 않는다
    monkeypatch.setattr(T, "_damper_loop_stable", lambda lm, grp, x, u, k, act: abs(k) <= 0.42)
    assert T._cap_by_stability(None, "roll", "p", "da", 1.0, {}) == (
        pytest.approx(0.42, abs=1e-3), "capped")

    # 안정 표본이 정말 하나도 없을 때만 no_stable_gain
    monkeypatch.setattr(T, "_damper_loop_stable", lambda *a: False)
    assert T._cap_by_stability(None, "roll", "p", "da", -1.0, {}) == (0.0, "no_stable_gain")


@pytest.fixture(scope="module")
def bandwidth_collapse():
    """마진은 통과하는데 교차가 하한 아래로 내려가는 점 — **지연을 키워 만든다.**

    종전에는 M0.7/h0이 그 자리였다. 프로펠러 전환으로 그 조건이 못 나게 됐고
    (해면 상단 M0.60), 더 중요하게는 **엔벨로프 안 어디에서도 기본 작동기 설정
    (delay 0.035)으로는 이 현상이 안 난다** — 비행 가능 범위가 좁아지면서 동압 폭이
    줄어 게인 스케줄의 롤오프가 1.03배까지만 가기 때문이다(격자 전수 탐색으로 확인:
    fuel 40·200·400 × alt 0~4000 × M0.25~0.55에서 0건).

    이 테스트가 보는 것은 기체가 아니라 **튜너의 구제 경로**이므로, 조건을 억지로
    찾는 대신 지연을 0.1 s로 키워 현상을 만든다 — 같은 성격(마진은 남는데 교차가
    하한에 걸림)이고 그 편이 정직하다. 실측: PM 104.4° · GM 8.2 dB · 교차 0.219배.
    """
    ac = make_demo_aircraft()
    design = demo_design_gains()
    tr = trim_level(ac, TrimCase("bw", mach=0.4, alt=1000.0, fuel=200.0), fingerprint="fp")
    assert tr.converged
    act = {**ACT, "delay_s": 0.1}
    return design, linearize(ac, tr), act


def test_rescue_polish_recovers_bandwidth_collapse(bandwidth_collapse, monkeypatch, no_rate_margin_guard):
    """백오프가 대역폭만 버려서 놓친 해를 마무리가 되찾는다 — **구제 경로의 기구**만 잰다.

    이 점의 자세 루프는 **마진이 모자라서** infeasible이던 게 아니다: 백오프 해가
    PM 104°·GM 8.2 dB로 목표를 크게 넘겼는데 교차가 목표의 0.219배까지 내려가
    대역폭 하한(0.2)에 걸렸다. 백오프는 ωc를 버려 마진을 사는 한 방향 탐색이라
    "마진은 남는데 대역폭이 없는" 해에서 멈춘다 — (kp, ki)를 함께 흔들면
    같은 마진에서 대역폭이 돌아온다.

    지연 0.1 s인 이 점에서는 백오프 해도 구제 해도 **축 전체 폐루프가 발산한다** — 수용 조건에 전체 폐루프
    판정이 들어간 뒤로는 구제되지 않는다(test_rescue_is_refused_when_the_full_loop_diverges). 기구를 재려고 그
    판정만 대역한다(항상 합격).
    """
    from claw.design import tune as T
    from claw.design.tune import REASON_CAPPED, REASON_RESCUED

    monkeypatch.setattr(T, "_strict_verdict", lambda poles, act_kw: {"stable": True, "bound": None})
    design, lm, act = bandwidth_collapse
    out = tune_point(lm, design, **act)
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


def test_rescue_is_refused_when_the_full_loop_diverges(bandwidth_collapse, no_rate_margin_guard):
    """구제 해는 보드 마진(레이트를 이상 폐쇄한 A′ 위)만 보고 게인을 민다 — 실제 조성에서 발산하면 받지 않는다.

    같은 점(지연 0.1 s): 마무리 해는 PM 102°·GM 8.25 dB로 수용 조건을 다 넘는데, 피치 댐퍼까지 작동기·지연을
    거쳐 한꺼번에 닫으면 10 rad/s 진동이 실부 +0.21로 발산한다. 종전에는 이 해가 `rescued`(통과)로 나갔다.
    발산 여부는 closure.closed_loop_poles와 **다른 경로**(채널에서 끊은 전달함수)로 재서 대조한다."""
    import control

    from claw.analysis.margins import make_siso
    from claw.design import tune as T
    from claw.design.closure import AXIS_SPECS
    from claw.trim import split_axes

    design, lm, act = bandwidth_collapse
    out = tune_point(lm, design, **act)
    assert out["slots"]["pitch_att"]["reason"] != T.REASON_RESCUED
    assert not any("마무리로 구제" in n for n in out["notes"]), out["notes"]
    # 전체 폐루프가 서는 자세 해가 없었다 — 마진은 서는데 발산하니 "마진 미달"이 아니라 loop_unstable
    assert out["slots"]["pitch_att"]["reason"] == T.REASON_LOOP_UNSTABLE
    assert out["status"] == "infeasible"

    # 거부된 구제 해를 직접 만들어 독립 경로로 발산을 확인한다
    lon, lat = split_axes(lm)
    gains, ach, _ = T._tune_rates(lon, lat, design, TuneTargets(), act)
    rg = {f"{g}.k_rate": gains[f"{g}.k_rate"] for g, _, _ in AXIS_SPECS["lon"]["rates"]}
    kp, ki, a0, _st, _ev = T._tune_att(lon, "pitch", rg, ach["pitch_rate"]["wc"], design, TuneTargets(), act)
    kp2, ki2, a2, _ev2 = T._polish_att(lon, "pitch", rg, kp, ki, TuneTargets(), act, max_evals=60, wc0=a0["wc0"])
    assert a2["polished"] and a2["pm_deg"] >= 50.0 and a2["gm_db"] >= 8.0  # 보드 마진으로는 합격
    s = control.tf("s")
    C = rg["pitch.k_rate"] * control.ss2tf(make_siso(lon, "q", "de")) \
        - (kp2 + ki2 / s) * control.ss2tf(make_siso(lon, "theta", "de"))
    num, den = control.pade(act["delay_s"], act["pade_order"])
    wn, z = act["actuator_wn"], act["actuator_zeta"]
    L = control.minreal(C * (wn * wn / (s * s + 2 * z * wn * s + wn * wn)) * control.tf(num, den), verbose=False)
    assert max(control.feedback(L, 1, sign=1).poles().real) > 0.1
    assert not T._full_loop_stable(lon, rg, kp2, ki2, 1, act)


def test_rescue_leaves_passing_slots_untouched(setup):
    """구제는 **실패한 자리에만** 돈다 — 통과한 자리까지 벌점 무릎으로 밀면
    전 운영점이 마진 경계에 앉고(작동기 공진에 가까워진다) 결과도 흔들린다."""
    _, design, _, lm = setup
    out = tune_point(lm, design, **ACT)
    # 자세 두 자리는 통과다(점은 레이트 자리 마진 캡으로 degraded — test_design_point_meets_targets)
    assert out["slots"]["pitch_att"]["reason"] == out["slots"]["roll_att"]["reason"] == "ok"
    for axis in ("pitch", "roll"):
        assert "polished" not in out["achieved"][f"{axis}_att"], axis
    assert not any("구제" in n for n in out["notes"])


def test_polish_initial_simplex_is_explicit(setup, no_rate_margin_guard):
    """초기 simplex를 명시하지 않으면 마무리가 사실상 아무것도 안 한다.

    x0 = [0, 0]이라 scipy는 0 성분에 zdelt = 0.00025를 써서 **변 길이 0.025%**인
    simplex를 만든다. 종전 코드는 polish=True로 켜도 Δlog kp = 0.00025 그대로
    끝났다 — 켜져 있으나 없는 설계변수였다.
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
    # 피치 자세만 실패시킨다 — 설계값 0이면 부호를 몰라 튜닝하지 않는다(seed_required). 종전에는 지연 0.6 s로
    # 피치를 무너뜨렸는데, 그 지연에서는 요·롤 댐퍼를 함께 닫은 조성도 발산해 롤 자세가 멀쩡하지 않다(전체 폐루프 확인)
    out = tune_point(lm, {**design, "pitch.kp": 0.0}, **ACT)
    assert out["status"] == "infeasible"  # 점 전체로는 실패인데…
    assert out["slots"]["pitch_att"]["status"] == "infeasible"
    assert out["slots"]["roll_att"]["status"] == "ok"  # …이 자리는 멀쩡하다
    assert set(out["slots"]) == {
        "pitch_rate", "yaw_rate", "roll_rate", "pitch_att", "roll_att"}


def test_zero_design_slot_requires_a_seed_and_fails_the_point(setup):
    """설계값 0인 자리는 부호를 몰라 튜닝하지 않는다 — 그리고 그것은 **통과가 아니다**.

    종전에는 na라 점 판정을 끌어내리지 않았다. 새 기체의 첫 설계(게인이 비어 있는 문서)가 바로 이 모양이라,
    댐퍼가 꺼진 채 자동 설계가 조용히 통과할 수 있었다. 초기 게인 빠른 탐색이 채울 자리다."""
    from claw.design.tune import REASON_SEED_REQUIRED

    _, design, _, lm = setup
    out = tune_point(lm, {**design, "yaw.k_rate": 0.0}, **ACT)
    slot = out["slots"]["yaw_rate"]
    assert slot["status"] == "infeasible" and slot["reason"] == REASON_SEED_REQUIRED
    assert out["gains"]["yaw.k_rate"] == 0.0
    assert out["status"] == "infeasible"


def test_zero_attitude_design_is_not_guessed_positive(setup):
    """자세 kp가 0이면 부호를 +1로 짐작하지 않는다 — 짐작한 부호가 틀려도 뒤집은 루프가 통과해 보인다."""
    from claw.design.tune import REASON_SEED_REQUIRED

    _, design, _, lm = setup
    out = tune_point(lm, {**design, "pitch.kp": 0.0, "pitch.ki": 0.0}, **ACT)
    assert out["slots"]["pitch_att"]["reason"] == REASON_SEED_REQUIRED
    assert (out["gains"]["pitch.kp"], out["gains"]["pitch.ki"]) == (0.0, 0.0)
    assert out["slots"]["roll_att"]["status"] == "ok"  # 다른 자리는 그대로 튜닝된다


def test_attitude_gain_sign_opposite_to_the_plant_fails(setup):
    """피치 kp·ki 부호를 뒤집으면 루프를 뒤집어야만 PM>0이다 — 종전에는 PM 100° 넘게 「ok」였다(양의 되먹임)."""
    from claw.design.tune import REASON_SIGN_MISMATCH

    _, design, _, lm = setup
    flipped = {**design, "pitch.kp": -design["pitch.kp"], "pitch.ki": -design["pitch.ki"]}
    out = tune_point(lm, flipped, **ACT)
    att = out["slots"]["pitch_att"]
    assert att["status"] == "infeasible" and att["reason"] == REASON_SIGN_MISMATCH
    assert out["achieved"]["pitch_att"]["orientation"] == -1
    assert out["status"] == "infeasible"
    # 마무리가 켜져 있어도 틀린 부호를 구제하지 않는다
    assert tune_point(lm, flipped, polish=True, **ACT)["slots"]["pitch_att"]["reason"] == REASON_SIGN_MISMATCH
    # 부호가 맞는 설계는 그대로 +방향 통과다
    assert tune_point(lm, design, **ACT)["achieved"]["pitch_att"]["orientation"] == 1


def test_rate_damper_sign_opposite_to_the_plant_fails(no_rate_margin_guard):
    """롤·요 조종 미계수 부호를 뒤집은 기체에 손설계 게인 — 레이트 댐퍼가 반대로 걸린다.

    종전에는 브래킷을 넓혀도 목표에 못 닿고 안정 캡에 걸려 capped(통과 쪽 사유)로 끝났다. 피치는 그대로 통과."""
    import copy

    from claw.design.tune import REASON_SIGN_MISMATCH
    from claw.profile import build_profile, load_example

    ex = load_example()
    hand = build_profile(ex).design_gains()
    flip = copy.deepcopy(ex)
    for coef, inp in (("Cl", "da"), ("Cn", "dr")):
        for t in flip["aero"]["coefficients"][coef]:
            if t["inputs"] == [inp]:
                t["k"] = -t["k"]
    ac = build_profile(flip).aircraft()
    lm = linearize(ac, trim_level(ac, TrimCase(name="flip", mach=0.45, alt=1000.0, fuel=200.0)))
    out = tune_point(lm, hand, **ACT)
    assert out["slots"]["yaw_rate"]["reason"] == REASON_SIGN_MISMATCH
    assert out["slots"]["roll_rate"]["reason"] == REASON_SIGN_MISMATCH
    assert out["gains"]["yaw.k_rate"] == out["gains"]["roll.k_rate"] == 0.0
    assert out["slots"]["pitch_rate"]["status"] == "ok" and out["status"] == "infeasible"
    # 부호를 맞춘 설계는 같은 기체에서 통과한다 — 결함은 부호다
    fixed = {**hand, "yaw.k_rate": -hand["yaw.k_rate"], "roll.k_rate": -hand["roll.k_rate"],
             "roll.kp": -hand["roll.kp"], "roll.ki": -hand["roll.ki"]}
    ok = tune_point(lm, fixed, **ACT)
    assert REASON_SIGN_MISMATCH not in {s["reason"] for s in ok["slots"].values()}


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


def test_gain_margin_is_the_distance_to_the_nearest_stability_boundary():
    """GM은 경계까지의 거리다 — 공칭 폐루프가 안정인 루프의 이득 감소 쪽 경계(음의 dB)는 미달이 아니라 반대 방향의 여유.

    control.margin은 −180° 교차 가운데 0 dB에 가장 가까운 경계 하나를 부호째 낸다. 개루프 불안정 루프는 나이키스트
    조건상 게인을 줄이면 깨지는 경계가 반드시 있다(게인 0이면 개루프 발산이 그대로 남는다). 공칭이 안정이면 그
    경계까지의 |dB|가 여유이고(closure.gain_margin_sides가 gm_db를 거리로 바꿔 싣는다), 공칭이 불안정이면 음의 GM은
    "안정하려면 줄여야 할 양"이라 여유가 아니다. 튜너 수용(_att_margin_verdict)과 검증 판정(criteria.judge)이 같은
    값을 읽는다."""
    import control

    from claw.analysis import loop_margins
    from claw.design.closure import att_margins, gain_margin_sides
    from claw.design.criteria import MarginCriteria
    from claw.design.tune import _att_margin_verdict

    tg = TuneTargets()  # PM 50° / GM 8 dB
    act = control.tf([100.0], [1.0, 14.0, 100.0])
    # 개루프 불안정(+0.2) · 공칭 안정 — 유일한 −180° 교차가 직류의 감소 쪽 경계(GM 0.2 = −14.0 dB)
    unstable_ol = control.tf([2.0, 1.0], [1.0, -0.2]) * act
    raw = loop_margins(unstable_ol)
    assert raw["gm_db"] == pytest.approx(-13.98, abs=0.01)
    m = gain_margin_sides(raw, unstable_ol)
    assert m["gm_down_db"] == raw["gm_db"] and m["gm_up_db"] == float("inf") and m["gm_nominal_stable"] is True
    assert m["gm_db"] == pytest.approx(13.98, abs=0.01)
    assert _att_margin_verdict(m, tg) == "ok" and MarginCriteria().judge(m) == "ok"
    assert gain_margin_sides(m, unstable_ol) == m  # 두 번 걸어도 같다
    # att_margins가 같은 결과를 낸다(방향 +1)
    am, orient = att_margins(unstable_ol)
    assert orient == 1 and am == m
    # 같은 모양에서 게인을 줄여 감소 쪽 경계가 3.5 dB 앞 — 거리가 목표 미달이다
    near = 0.3 * control.tf([2.0, 1.0], [1.0, -0.2]) * act
    mn = gain_margin_sides(loop_margins(near), near)
    assert mn["gm_nominal_stable"] is True and 0.0 < mn["gm_db"] < 6.0
    assert _att_margin_verdict(mn, tg) == "short" and MarginCriteria().judge(mn) == "fail"
    # 개루프 안정인데 게인이 커 −1을 감싼 루프 — 음의 GM은 여유가 아니다(공칭 불안정, 값 그대로)
    wrapped = control.tf([20.0], [1.0, 3.0, 3.0, 1.0])
    mw = gain_margin_sides(loop_margins(wrapped), wrapped)
    assert mw["gm_nominal_stable"] is False and mw["gm_db"] == mw["gm_down_db"] < 0.0
    assert _att_margin_verdict({**mw, "pm_deg": 60.0}, tg) == "short"
    # 증가 쪽 경계가 가장 가까우면 손대지 않는다 — 감소 쪽(−17.4 dB)이 있어도 더 멀다. 판정이 종전과 같다
    both = control.tf([4.0, 4.0], [1.0, -0.5, 0.0]) * control.tf([400.0], [1.0, 28.0, 400.0])
    mb = loop_margins(both)
    assert mb["gm_db"] > 0.0 and gain_margin_sides(mb, both) == mb


def test_open_loop_unstable_attitude_loop_is_not_rejected_for_its_gain_reduction_margin():
    """댐퍼 가드의 나선 면제가 롤 자세 루프의 A′를 개루프 불안정으로 남긴 점 — 감소 쪽 경계를 미달로 읽지 않는다.

    구 기체 M0.3/h0/f200, 작동기·지연 없는 튜닝(tune_point가 받는 모드): 롤 댐퍼를 닫은 A′에 +0.0131(면제한 나선).
    첫 후보(ωc0 3.88)의 −180° 교차가 −49.0 dB(0.081 rad/s)·+293.9 dB, PM 66.5°, 축 전체 폐루프 안정인데 종전 판정은
    −49.0을 "GM < 8 dB"로 읽어 백오프했고, 게인을 줄일수록 감소 쪽 경계가 0 dB로 다가와 margin_floor(교차 0.058배,
    GM −24.6 dB)로 끝났다 — 설계 실패 사유라 자세 표본이 적합에서 빠졌다."""
    import numpy as np

    from claw.design.closure import close_rates
    from claw.fcl.demo import demo_rate_filters
    from claw.trim import split_axes

    from claw.design.criteria import MarginCriteria
    from claw.design.schedmap import scheduled_margin_point

    ac = make_demo_aircraft()
    case = TrimCase("t", mach=0.3, alt=0.0, fuel=200.0)
    lm = linearize(ac, trim_level(ac, case, fingerprint="fp"))
    rf = demo_rate_filters()
    out = tune_point(lm, demo_design_gains(), rate_filters=rf, actuator_wn=None, actuator_zeta=None, delay_s=0.0)
    ra = out["achieved"]["roll_att"]
    assert out["slots"]["roll_att"]["reason"] == "ok", out["notes"]
    assert ra["wc_att"] == ra["wc0"]  # 백오프 없이 첫 후보가 선다
    assert ra["pm_deg"] == pytest.approx(66.5, abs=0.1)
    # gm_db는 경계까지의 거리 — control.margin이 고른 감소 쪽 경계 −49.05 dB의 |dB|(증가 쪽은 훨씬 멀다)
    assert ra["gm_down_db"] == pytest.approx(-49.05, abs=0.05) and ra["gm_db"] == -ra["gm_down_db"]
    assert ra["gm_up_db"] > ra["gm_db"] and ra["gm_nominal_stable"] is True
    assert ra["closed_loop"]["stable"]
    # 근본원인 — 롤 댐퍼까지 닫은 A′가 개루프 불안정(느린 나선)이다
    lat = split_axes(lm)[1]
    rg = {k: out["gains"][k] for k in ("yaw.k_rate", "roll.k_rate")}
    eig = np.linalg.eigvals(close_rates(lat, rg, rf).A)
    assert max(eig.real) == pytest.approx(0.0131, abs=5e-4)
    # 검증도 같은 자로 잰다 — 튜너가 받아들인 게인을 검증이 GM −49 dB "fail"로 떨어뜨리지 않는다
    ver = scheduled_margin_point(lm, {}, out["gains"], case, criteria=MarginCriteria(), rate_filters=rf)
    assert ver["roll_att"]["status"] == "ok" and ver["roll_att"]["gm_db"] == pytest.approx(ra["gm_db"], rel=1e-9)


def test_actuator_resonance_record_cites_the_pole_that_failed_the_floor(no_rate_margin_guard):
    """전체 폐루프가 작동기 대역 공진 감쇠(ζ < 0.10)로 걸리면 기록·note가 **그 극**을 가리킨다.

    그 판정은 극이 전부 안정한 채 걸린다 — 종전에는 실부 최대 극(느린 실근 −0.018, 허수부 0)을 worst_pole로 적어
    "작동기 대역 공진"이라 해 놓고 0 rad/s 모드를 가리켰다. 구 기체 M0.6/h0/f40 피치(작동기 30/0.7·지연 0.035 s):
    걸린 극은 −1.647 ± 17.73j(ζ 0.0925). max_re는 발산 판정의 양이라 그대로 실부 최대다."""
    import numpy as np

    from claw.design.closure import closed_loop_poles
    from claw.design.tune import _ZETA_ACT_MIN, AXIS_SPECS
    from claw.trim import split_axes

    ac = make_demo_aircraft()
    lm = linearize(ac, trim_level(ac, TrimCase("t", mach=0.6, alt=0.0, fuel=40.0), fingerprint="fp"))
    out = tune_point(lm, demo_design_gains(), **ACT)
    pa = out["achieved"]["pitch_att"]
    cl = pa["closed_loop"]
    assert cl["stable"] is False and cl["bound"] == "actuator_resonance"
    assert cl["worst_pole"] == pytest.approx([-1.647, 17.73], abs=5e-3)
    assert cl["worst_zeta"] == pytest.approx(0.0925, abs=5e-4) and cl["worst_zeta"] < _ZETA_ACT_MIN
    # 구현 독립 대조 — 같은 게인으로 닫은 극에서 작동기 대역(> 0.3 × 30 rad/s) 진동극의 최소 ζ
    lon = split_axes(lm)[0]
    g = out["gains"]
    full = closed_loop_poles(lon, {f"{h}.k_rate": g[f"{h}.k_rate"] for h, _, _ in AXIS_SPECS["lon"]["rates"]},
                             kp=g["pitch.kp"], ki=g["pitch.ki"], orientation=float(pa["orientation"]),
                             actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2)
    band = [p for p in full if p.imag > 1e-9 and abs(p) > 9.0]
    worst = min(band, key=lambda p: -p.real / abs(p))
    assert cl["worst_pole"] == pytest.approx([worst.real, worst.imag], rel=1e-9)
    assert cl["max_re"] == pytest.approx(float(np.max(full.real)), rel=1e-9) and cl["max_re"] < 0.0
    # 백오프가 이미 loop_unstable로 끝낸 자리에도 걸린 극이 note에 남는다
    assert out["slots"]["pitch_att"]["reason"] == "loop_unstable"
    notes = [n for n in out["notes"] if n.startswith("pitch.kp/ki") and "작동기 대역 공진 감쇠 부족" in n]
    assert notes and "ζ 0.0925" in notes[0] and "17.7j" in notes[0] and "허수부 0 rad/s" not in notes[0]


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

    # 판정 문맥 없이는 판정하지 않는다 — 옛 한 비트 정의로 되돌아가는 길이 없다(이관 8단계)
    with pytest.raises(TypeError):
        envelope_ok(_T(True, True, True))

    # 세 모듈이 **같은 판정**(opspace/verdict.py condition_verdict)을 부른다 — 각자 다시 적으면 경로가 갈린다
    for mod in (grid, refine, schedmap):
        src = inspect.getsource(mod)
        assert "condition_verdict(tr, ctx)" in src, mod.__name__
        assert 'flags.get("saturation_ok")' not in src, (
            f"{mod.__name__}이 엔벨로프 조건을 다시 적었다")


def test_polish_result_inherits_the_requirement_metadata(setup):
    """마무리를 거친 자리도 **요구선**을 들고 있어야 한다.

    `_polish_att`가 새 achieved를 만들 때 백오프 해의 메타(target_pm_deg·
    target_gm_db·target_wc_frac·wc_fallback)를 안 물려받으면, `evidence["tuned"]
    ["target"]`이 **구제된 자리에서만** null이 된다 — 요구선을 함께 낸다고 넣은 값이
    가장 설명이 필요한 자리에서 빠진다. `wc_fallback`도 마찬가지로, 그 플래그가
    켜지는 상황이 대개 구제가 도는 상황이다.
    """
    from claw.design.closure import AXIS_SPECS
    from claw.design.tune import _polish_att, _tune_att, _tune_rates
    from claw.trim import split_axes

    _, design, _, lm = setup
    lon, lat = split_axes(lm)
    gains, ach, _ = _tune_rates(lon, lat, design, TuneTargets(), ACT)
    rg = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
          for g, _, _ in AXIS_SPECS["lon"]["rates"]}
    kp0, ki0, a0, _st, _ev = _tune_att(
        lon, "pitch", rg, ach["pitch_rate"]["wc"], design, TuneTargets(), ACT)
    meta_keys = ("target_pm_deg", "target_gm_db", "target_wc_frac", "wc_fallback")
    assert all(k in a0 for k in meta_keys), "백오프 해가 메타를 안 실었다 — 전제가 다르다"

    _kp, _ki, a, _e = _polish_att(
        lon, "pitch", rg, kp0, ki0, TuneTargets(), ACT, max_evals=40,
        wc0=a0["wc0"], meta={k: a0[k] for k in meta_keys})
    for k in meta_keys:
        assert a.get(k) == a0[k], f"마무리가 {k}를 잃었다"


def test_crossover_search_says_it_could_not_measure(setup):
    """천장 확장을 다 쓰고도 |L| ≥ 1이면 **천장 값이 아니라 nan**이다.

    그대로 천장을 돌려주면 교차 주파수가 아닌 수를 교차라 부르는 조용한 오답이다
    (확장 자체가 그 함정을 막으려고 들어왔는데, 소진 경로에 같은 함정이 남아
    있었다). nan이면 소비자가 통과로 안 친다 — 튜너는 rate_wc > 0이 거짓이 되어
    wc_fallback 경로로 가고 플래그가 남는다.
    """
    from claw.design.closure import rate_loop_crossover
    from claw.trim import split_axes

    _, _design, _, lm = setup
    lon, _lat = split_axes(lm)
    # 확장을 0회로 막으면 천장 밖 교차가 소진 경로를 탄다
    import claw.design.closure as C

    saved = C._WC_GRID_EXPANSIONS
    try:
        C._WC_GRID_EXPANSIONS = 0
        wc = rate_loop_crossover(lon, "pitch", "q", "de", 50.0, actuator_wn=30.0,
                                 actuator_zeta=0.7, delay_s=0.035, pade_order=2)
    finally:
        C._WC_GRID_EXPANSIONS = saved
    assert math.isnan(wc), "소진 경로가 천장 값을 교차라 불렀다"
    # 정상 경로는 유한값을 낸다 (이 테스트가 항진이 아님을 보인다)
    ok = rate_loop_crossover(lon, "pitch", "q", "de", 50.0, actuator_wn=30.0,
                             actuator_zeta=0.7, delay_s=0.035, pade_order=2)
    assert math.isfinite(ok) and ok > 0.0


def test_argmax_does_not_pick_an_unmeasurable_sample():
    """못 잰 표본(nan)을 "최선 달성값"으로 뽑으면 안 된다.

    `np.argmax([1.0, nan, 3.0])`은 **1**을 낸다 — nan이 하나라도 있으면 그 자리를
    고른다. 지표가 nan을 낼 수 있게 된 뒤(closure.lat_metrics — 롤 모드를 실근으로
    지목 못 하면 nan) 이 자리가 노출됐다. 데모 격자에서 스캔 117회 중 14회가 vals에
    nan을 담고 **전부 |k| = 0 표본**이라, 그대로 두면 "최선 달성값"이 **댐퍼를 끈
    게인**이 되어 스케줄에 박힌다. 종전 0.0은 최솟값이라 절대 안 뽑혔다.

    지금 데모에서 이 가지를 안 타는 이유는 롤 λ가 |k|에 단조라 `reached`가 늘
    True이기 때문이다 — 그 불변식은 작동기 캡·목표·플랜트가 바뀌면 깨진다.
    합성 함수로 직접 잰다.
    """
    from claw.design.tune import _first_reach_bisect

    # |k| = 0에서만 nan (지목 실패), 나머지는 유한하고 0.6이 최대 — 목표 5.0은 못 닿는다
    def f(k):
        return float("nan") if k == 0.0 else 0.6 - abs(k - 0.5)

    k, reached, _grown = _first_reach_bisect(f, 0.0, 1.0, 5.0)
    assert not reached
    assert k == pytest.approx(0.5, abs=0.1), (
        f"못 잰 표본을 최선이라 뽑았다 (k={k}) — 댐퍼를 끈 게인이 스케줄에 박힌다")

    # 전 표본이 못 잰 값이면 최선을 고를 근거가 없다 — 하한을 낸다 (사유가 미달로 흐른다)
    k2, reached2, _g2 = _first_reach_bisect(lambda _k: float("nan"), 0.0, 1.0, 5.0)
    assert not reached2 and k2 == 0.0


# 쇼케이스 기체(200 kg급 EO/IR 정찰 델타 무미익) M0.107725/h0/연료 25 트림의 분리 모델 — S1 표 모드 자동 설계
# (n_mach 7 · alts [0, 3000] · fuels [25] · zeta_sp 0.9)에서 roll.k_rate가 **정확히 0**으로 박혔던 앵커다.
# 값은 그 세션의 선형모델 그대로 싣는다 — 문서가 다시 생성돼도 이 회귀 입력은 안 움직여야 한다
_S1_LOWQ_LON_A = [[-0.07723857968234622, 0.1619003546426316, -8.933238282720941, -9.513260243709608],
                  [-0.23150299355582313, -1.2176820191665598, 35.10667791349066, -2.380811574831958],
                  [0.03555040464156186, -0.14205254210447923, -1.0982508931721375, 0.0],
                  [0.0, 0.0, 1.0, 0.0]]
_S1_LOWQ_LON_B = [[-0.3825518909284905, 4.6140563015342195], [-5.186587257022827, 0.0],
                  [-7.5151753209722125, 0.0], [0.0, 0.0]]
_S1_LOWQ_LAT_A = [[-0.2074573551569944, 8.899695116668443, -35.56145166220098, 9.513260243708752],
                  [-0.6236980380977879, -2.572754407153248, 0.38981127381109815, 0.0],
                  [0.06787134625109192, -0.021561904005940387, -0.12937142403564234, 0.0],
                  [0.0, 1.0, 0.2502624246390964, 0.0]]
_S1_LOWQ_LAT_B = [[0.0, 1.1288100073949998], [20.577265759804686, 0.0],
                  [-0.2529343806582906, -1.264671903291453], [0.0, 0.0]]
# 그 세션의 설계값(쇼케이스 문서 초기 게인) — 부호가 방향을 정한다: 롤 댐퍼 음(B[p,da] > 0), 요 댐퍼 양(B[r,dr] < 0)
_S1_SEED = {"pitch.kp": -0.6698509591760828, "pitch.ki": -0.09745512790566056,
            "pitch.k_rate": 0.17328858217403667, "roll.kp": 0.903830572438492,
            "roll.ki": 0.32141009839610063, "roll.k_rate": -0.21976637122515477,
            "yaw.k_rate": 0.8185133581853344}


def _full_model(lon_a, lon_b, lat_a, lat_b):
    """분리 모델 두 개 → 전체축 LinearModel (split_axes가 그대로 되돌린다 — 축 사이 결합 0)."""
    import numpy as np

    from claw.common.contracts import LinearModel
    from claw.plant.aircraft import XE_NAMES
    from claw.trim import U_NAMES
    from claw.trim.linearize import LAT_INPUTS, LAT_STATES, LON_INPUTS, LON_STATES

    n, m = len(XE_NAMES), len(U_NAMES)
    A, B = np.zeros((n, n)), np.zeros((n, m))
    for states, inputs, a, b in ((LON_STATES, LON_INPUTS, lon_a, lon_b),
                                 (LAT_STATES, LAT_INPUTS, lat_a, lat_b)):
        xi = [XE_NAMES.index(s) for s in states]
        ui = [U_NAMES.index(u) for u in inputs]
        A[np.ix_(xi, xi)] = a
        B[np.ix_(xi, ui)] = b
    return LinearModel(A=A, B=B, C=np.eye(n), D=np.zeros((n, m)), x_names=XE_NAMES,
                       u_names=U_NAMES, axis="full", dt=0.0, case=None, params_fingerprint="")


def test_roll_damper_direction_is_not_decided_by_a_merged_roll_mode(no_rate_margin_guard):
    """저동압 델타의 롤 댐퍼 — 작은 닫기에서 롤 모드가 실근으로 없는데 그 "λ"로 부호를 가르면 안 된다.

    요를 닫은 조성에서 롤 게인을 설계값의 0.1배로 닫으면 롤 모드가 더치롤과 합쳐져 진동쌍에 들고, 남은 실근
    둘의 p 참여도가 0.06~0.10으로 비슷하다. 종전 판정은 그중 "가장 큰" 쪽의 |Re|를 비교해 반대 부호가
    λ를 네 배 준다(4.32 vs 1.17)고 보고 sign_mismatch → 댐퍼 0 → 그 위에서 롤 자세 kp 0.32·ki 0.035(이웃
    ~2.0·0.85)를 냈다. 이웃 점은 참여도 순서가 반대로 떨어져 멀쩡했다 — 표 모드가 그 0을 그대로 반출했다.
    설계 크기에서는 설계 부호가 온전한 롤 모드(참여도 ≈1)를 내고 반대 부호는 더치롤을 발산시킨다 —
    유효한 댐퍼가 있고, 튜너는 그것을 찾아야 한다."""
    from claw.design.closure import axis_metrics
    from claw.design.tune import REASON_OK
    from claw.trim import split_axes

    lm = _full_model(_S1_LOWQ_LON_A, _S1_LOWQ_LON_B, _S1_LOWQ_LAT_A, _S1_LOWQ_LAT_B)
    out = tune_point(lm, _S1_SEED, targets=TuneTargets(zeta_sp=0.9), **ACT)
    rr = out["slots"]["roll_rate"]
    assert rr["reason"] == REASON_OK, out["notes"]
    k = out["gains"]["roll.k_rate"]
    # 이웃 앵커(M0.1062 −0.495 · M0.1093 −0.464) 사이 — 목표 λ 12를 최종 조성에서 낸다
    assert k == pytest.approx(-0.479, rel=0.02)
    assert out["achieved"]["roll_rate"]["roll_lambda"] >= 12.0 * (1.0 - 1e-3)
    assert out["achieved"]["roll_rate"]["participation"] > 0.9
    # 롤 댐퍼가 닫히니 요 자리도 최종 조성에서 목표를 넘는다 (종전 target_unreached ζ 0.42)
    assert out["slots"]["yaw_rate"]["reason"] == REASON_OK
    # 자세 루프는 작동하는 댐퍼 위에서 튜닝된다 — 이웃 수준의 kp·ki
    assert out["slots"]["roll_att"]["reason"] == REASON_OK
    assert out["gains"]["roll.kp"] == pytest.approx(2.0, rel=0.05)
    assert out["gains"]["roll.ki"] == pytest.approx(0.84, rel=0.05)

    # 근본원인의 실측 — 작은 닫기에서는 양쪽 다 롤 모드가 아니고, 설계 크기에서만 갈린다
    lat = split_axes(lm)[1]
    # 롤 부호는 1차 패스의 요 게인(탐색 조성 argmax 3.58)을 닫은 조성에서 갈랐다 — 요 자리는 뒤에 2차 패스로
    # 롤을 닫은 조성에서 다시 찾아져 작아진다(최종 요 게인으로는 근본원인이 재현되지 않는다)
    yk = out["achieved"]["yaw_rate"]["second_pass"]["k_first"]
    assert yk == pytest.approx(3.581, rel=1e-3)
    kd = abs(_S1_SEED["roll.k_rate"])
    for kr in (-0.1 * kd, 0.1 * kd):
        m = axis_metrics(lat, {"yaw.k_rate": yk, "roll.k_rate": kr})
        assert m["roll_participation"] < 0.5, (kr, m)
    good = axis_metrics(lat, {"yaw.k_rate": yk, "roll.k_rate": -kd})
    bad = axis_metrics(lat, {"yaw.k_rate": yk, "roll.k_rate": kd})
    assert good["roll_participation"] > 0.9 and not good["roll_unstable"]
    assert bad["zeta_dr"] < 0.0  # 반대 부호 = 양의 되먹임 — 더치롤 발산


def test_sign_probe_skips_a_magnitude_measured_on_one_side_only():
    """한쪽만 모드를 잡은 크기는 부호를 가르지 않는다 — "못 잰 것"이 "나쁜 것"으로 둔갑하면 안 된다.

    예제 기체 M0.119/h0에서 실측한 모양: 0.1배 닫기에서 설계 부호 쪽 실근의 p 참여도가 0.497(문턱 바로 밑)이고
    반대 부호 쪽은 0.744라, nan을 가장 나쁜 값으로 치면 반대 부호가 이긴다. 설계 크기에서는 설계 부호 λ 4.95,
    반대 부호는 롤 근 발산 — 부호는 맞다."""
    from claw.design.tune import _rate_sign_opposes

    nan, inf = float("nan"), float("inf")
    probe = {0.1: nan, -0.1: 1.81, 1.0: 4.95, -1.0: -inf}
    assert _rate_sign_opposes(lambda m: probe[round(m, 9)], 1.0) is False
    # 크기를 키워도(탐색 브래킷 4배까지) 한쪽만 잰 값이고 발산으로도 못 가르면 모르는 것이다 — 결함이라 하지 않는다
    unknown = {0.1: nan, -0.1: 1.81, 1.0: 3.0, -1.0: nan, 2.0: 5.0, -2.0: nan, 4.0: 8.0, -4.0: nan}
    assert _rate_sign_opposes(lambda m: unknown[round(m, 9)], 1.0) is False
    assert _rate_sign_opposes(lambda m: unknown[round(m, 9)], 1.0, lambda m: False) is False
    # 양쪽을 다 잰 크기에서 반대 부호가 분명히 나으면 여전히 결함이다 (부호를 뒤집은 기체)
    flipped = {0.1: 0.8, -0.1: 1.3, 1.0: -inf, -1.0: 5.0}
    assert _rate_sign_opposes(lambda m: flipped[round(m, 9)], 1.0) is True
    # 설계 부호의 롤 근만 발산이면(−inf) 반대 부호의 유한값이 이긴다
    diverge = {0.1: nan, -0.1: nan, 1.0: -inf, -1.0: 2.0}
    assert _rate_sign_opposes(lambda m: diverge[round(m, 9)], 1.0) is True


def test_sign_probe_resolves_an_unmeasured_roll_mode_by_divergence():
    """nan(롤 모드를 못 잡음)은 "모른다"로 끝나지 않는다 — nan인 쪽 조성이 발산하고 다른 쪽이 서면 nan 쪽이 나쁘다.

    부호가 반대인 롤 댐퍼는 저동압에서 롤 모드를 더치롤과 합쳐 진동 발산으로 만든다 — λ가 nan이라 종전 규칙은
    두 크기 다 "못 가른다"로 넘겨 틀린 부호로 탐색했다(쇼케이스 Cl/δa 부호를 뒤집은 M0.1/h0: 설계 크기 [nan, 5.72],
    설계 부호 더치롤 ζ −0.36). 가르는 규칙의 경계:
    - 0.1배 탐침에서는 발산으로 가르지 않는다(프리픽스와 거의 같은 조성 — 발산이 갈려도 부호 탓이 아니다).
    - 양쪽 다 발산하면(부호와 무관한 발산) 가르지 않는다. 발산이 nan 쪽이 아니면(잰 쪽이 발산) 가르지 않는다.
    - 설계 크기에서 못 가르면 2배·4배(탐색 브래킷)로 키운다 — 설계 크기가 작아 설계 부호가 아직 발산 전인 경우.
    - 같은 값(nan 아님)이면 설계 크기에서 멈춘다 — 감쇠 지표의 과감쇠 동률은 키워 가를 근거가 아니다."""
    from claw.design.tune import _rate_sign_opposes

    nan = float("nan")

    def run(vals, div=None):
        return _rate_sign_opposes(lambda m: vals[round(m, 9)], 1.0,
                                  None if div is None else (lambda m: div.get(round(m, 9), False)))

    merged = {0.1: nan, -0.1: nan, 1.0: nan, -1.0: 5.72, 2.0: nan, -2.0: 9.7, 4.0: nan, -4.0: 17.7}
    assert run(merged, {1.0: True, 2.0: True, 4.0: True}) is True
    # 같은 모양에 발산 판정이 없으면 종전처럼 모른다 (감쇠 지표 자리 — nan을 내지 않으니 이 경로에 안 온다)
    assert run(merged) is False
    # 반대로 반대 부호 쪽이 nan이면서 발산하면 설계 부호가 맞다
    assert run({0.1: nan, -0.1: nan, 1.0: 5.55, -1.0: nan}, {-1.0: True}) is False
    # 양쪽 다 nan이어도 한쪽만 발산하면 가른다 (뒤집은 쇼케이스 M0.119/h5000: 반대 부호 참여도 0.43)
    assert run({0.1: nan, -0.1: nan, 1.0: nan, -1.0: nan}, {1.0: True}) is True
    # 양쪽 다 발산 — 부호와 무관한 발산이다. 끝까지 못 가르면 결함이라 하지 않는다
    both = {0.1: nan, -0.1: nan, 1.0: nan, -1.0: 2.0, 2.0: nan, -2.0: 3.0, 4.0: nan, -4.0: 4.0}
    assert run(both, {m: True for m in (1.0, -1.0, 2.0, -2.0, 4.0, -4.0)}) is False
    # 발산이 잰 쪽(반대 부호 λ 2.0)에 있으면 nan 쪽을 나쁘다 할 근거가 아니다
    assert run(both, {-1.0: True, -2.0: True, -4.0: True}) is False
    # 0.1배 탐침의 발산은 쓰지 않는다 — 설계 크기에서 설계 부호가 이긴다
    assert run({0.1: nan, -0.1: 1.5, 1.0: 4.0, -1.0: -float("inf")}, {0.1: True}) is False
    # 설계 크기가 작아 설계 부호가 아직 발산 전 — 2배에서 가른다 (쇼케이스 뒤집음, 설계 크기 절반)
    small = {0.1: nan, -0.1: nan, 1.0: nan, -1.0: 1.43, 2.0: nan, -2.0: 5.72}
    assert run(small, {2.0: True}) is True
    # 같은 값이면 설계 크기에서 멈춘다 — 2배를 묻지 않는다(묻으면 KeyError)
    assert run({0.1: 1.0, -0.1: 1.0, 1.0: 1.0, -1.0: 1.0}, {}) is False


# 뒤집은 에일러론 — _S1_LOWQ 조성에서 δa 열 전체의 부호만 바꾼다(롤·요 모멘트 모두). 같은 플랜트에서 설계 부호가
# 맞는 쪽은 위 test_roll_damper_direction_is_not_decided_by_a_merged_roll_mode가 고정한다
def _s1_lowq_reversed_aileron():
    lat_b = [[-row[0], row[1]] for row in _S1_LOWQ_LAT_B]
    return _full_model(_S1_LOWQ_LON_A, _S1_LOWQ_LON_B, _S1_LOWQ_LAT_A, lat_b)


def test_reversed_aileron_roll_damper_is_a_sign_mismatch_at_low_dynamic_pressure():
    """저동압에서 부호가 반대인 롤 댐퍼 — 롤 모드가 합쳐져 λ가 nan이어도 sign_mismatch로 잡혀 표본에서 빠진다.

    종전: 두 탐침 크기 다 설계 부호 쪽이 nan이라 "모른다" → 틀린 부호로 탐색 → 안정 캡이 설계값의 절반(−0.105)으로
    깎아 capped(통과 쪽 사유, "작동기·지연 안정 경계") → failed_gain_slots가 roll.k_rate를 빼지 않아 양의 되먹임
    표본이 적합에 들어갔다. 같은 기체의 고동압 이웃은 sign_mismatch로 빠지므로 표가 틀린 부호 값으로만 채워진다."""
    from claw.design.closure import axis_metrics
    from claw.design.tune import REASON_SIGN_MISMATCH, failed_gain_slots
    from claw.trim import split_axes

    lm = _s1_lowq_reversed_aileron()
    out = tune_point(lm, _S1_SEED, targets=TuneTargets(zeta_sp=0.9), **ACT)
    assert out["slots"]["roll_rate"]["reason"] == REASON_SIGN_MISMATCH, out["notes"]
    assert out["gains"]["roll.k_rate"] == 0.0
    assert "roll.k_rate" in failed_gain_slots(out["slots"])
    assert not any("댐퍼 안정 캡" in n for n in out["notes"] if n.startswith("roll.k_rate"))
    # 근본원인 — 설계 크기에서 설계 부호는 롤 모드를 못 잡고(nan) 축이 진동 발산, 반대 부호는 온전한 롤 모드
    lat = split_axes(lm)[1]
    kd = abs(_S1_SEED["roll.k_rate"])
    # 롤 부호를 가른 프리픽스 = 1차 패스 요 게인(롤이 0이라 2차 패스가 없어 그대로 남는다). δa는 요 조성에 없으니
    # 위 정상 부호 시험과 같은 값이다
    yk = out["gains"]["yaw.k_rate"]
    assert yk == pytest.approx(3.581, rel=1e-3)
    bad = axis_metrics(lat, {"yaw.k_rate": yk, "roll.k_rate": -kd})
    good = axis_metrics(lat, {"yaw.k_rate": yk, "roll.k_rate": kd})
    assert bad["roll_participation"] < 0.5 and bad["zeta_dr"] < 0.0
    assert good["roll_participation"] > 0.5 and not good["roll_unstable"] and good["zeta_dr"] > 0.0


def test_reversed_aileron_on_the_shipped_example_is_caught_where_the_roll_mode_merges(no_rate_margin_guard):
    """제품 예제 기체(출하 문서)의 Cl/δa 부호를 뒤집은 저동압 점 — 종전 capped(−0.110), 이제 sign_mismatch.
    뒤집지 않은 같은 점은 그대로 ok다(오탐 없음)."""
    import copy

    from claw.design.tune import REASON_SIGN_MISMATCH
    from claw.profile import build_profile
    from claw.profile.document import load_shipped_example

    ex = load_shipped_example()
    prof = build_profile(ex)
    hand, rf = prof.design_gains(), prof.rate_filters()
    flip = copy.deepcopy(ex)
    for t in flip["aero"]["coefficients"]["Cl"]:
        if t["inputs"] == ["da"]:
            t["k"] = -t["k"]
    case = TrimCase(name="lowq", mach=0.1, alt=0.0, fuel=0.5 * ex["mass"]["fuel_max"])
    for doc, want in ((flip, REASON_SIGN_MISMATCH), (ex, "ok")):
        ac = build_profile(doc).aircraft()
        out = tune_point(linearize(ac, trim_level(ac, case)), hand, rate_filters=rf, **ACT)
        assert out["slots"]["roll_rate"]["reason"] == want, (want, out["notes"])


def test_direction_score_counts_only_a_roll_mode():
    """방향 판정용 λ — 롤 모드로 지목된 근(참여도 ≥ 판정 문턱)만 수치, 발산근은 가장 나쁜 값.

    |Re|는 부호를 지운다 — 반대 부호 댐퍼가 롤 근을 +2로 밀어낸 것을 "λ 2"로 읽으면 안 된다.
    문턱은 판정(MarginCriteria.lam_part_min)과 같은 선이다 — 튜너와 판정이 "롤 모드를 잰 것"을 다르게 부르지 않게."""
    import math

    from claw.design.criteria import MarginCriteria
    from claw.design.tune import _direction_score

    part_min = MarginCriteria().lam_part_min
    lam = {"roll_lambda": 6.4, "roll_unstable": False}
    assert _direction_score({**lam, "roll_participation": part_min}, "roll_lambda") == 6.4
    assert math.isnan(_direction_score({**lam, "roll_participation": part_min * 0.99}, "roll_lambda"))
    assert math.isnan(_direction_score({**lam, "roll_participation": None}, "roll_lambda"))
    assert _direction_score({"roll_lambda": 2.09, "roll_unstable": True, "roll_participation": 1.3},
                            "roll_lambda") == -math.inf
    # 감쇠 지표는 그대로 — 모드 지목 문제가 없다(없으면 1.0으로 정의돼 있다)
    assert _direction_score({"zeta_dr": 0.42}, "zeta_dr") == 0.42


# ── 댐퍼 가드의 나선 면제 · 전체 폐루프 확인 · 2차 패스 · 표본 제외 규칙 ──

def test_spiral_exemption_line_is_the_flying_qualities_failure_state_spiral():
    """면제선은 새 수가 아니라 기체 비행성 기준(analysis.fq.FQCriteria)의 나선 배가시간이다 — 댐퍼만 닫힌 조성은
    자세 루프가 빠진 고장 상태라 수준 2(8 s). 정상 상태(자세까지 닫힘)는 전체 폐루프 확인이 나선 안정을 요구한다."""
    from claw.analysis.fq import FQCriteria
    from claw.design.tune import _SPIRAL_T2_MIN_S

    assert _SPIRAL_T2_MIN_S == FQCriteria().spiral_t2_l2 == 8.0


def test_spiral_exemption_is_one_slow_real_root_on_the_lateral_axis_only(setup):
    """면제는 **횡축의 느린 실근 하나**뿐이다 — 종축(장주기)·진동 발산·둘 이상의 발산·기준보다 빠른 나선은 아니다.

    극 집합을 직접 넣어 규칙만 잰다(느림의 문턱은 모드 지표가 장주기·나선을 빼는 _WN_FLOOR_FRAC × 기준 wn)."""
    from claw.design.tune import _spiral_exempt_verdict
    from claw.trim import split_axes

    _, _, _, lm = setup
    lon, lat = split_axes(lm)
    fast = [-5.0 + 2.0j, -5.0 - 2.0j, -3.0]
    ok = _spiral_exempt_verdict(fast + [0.05], lat)  # 배가 13.9 s ≥ 8 s
    assert ok["stable"] and ok["spiral_t2_s"] == pytest.approx(13.86, rel=1e-3)
    assert _spiral_exempt_verdict(fast + [0.05], lon)["bound"] == "unstable"  # 종축엔 면제가 없다
    short = _spiral_exempt_verdict(fast + [0.1], lat)  # 배가 6.9 s < 8 s
    assert not short["stable"] and short["bound"] == "spiral"
    assert _spiral_exempt_verdict(fast + [0.01 + 0.02j, 0.01 - 0.02j], lat)["bound"] == "unstable"
    assert _spiral_exempt_verdict(fast + [0.01, 0.002], lat)["bound"] == "unstable"  # 나선은 하나뿐이다
    assert _spiral_exempt_verdict(fast + [1.5], lat)["bound"] == "unstable"  # 느린 근이 아니다
    assert _spiral_exempt_verdict(fast + [-0.01], lat) == {
        "stable": True, "bound": None, "spiral_t2_s": None, "max_re": -0.01}


def test_damper_guard_passes_a_slow_spiral_within_the_criterion_and_nothing_else(monkeypatch):
    """구 기체 M0.3/h0 + 요 워시아웃: 롤 댐퍼(−0.5225)를 닫은 조성에서 요 댐퍼(0.5742)를 닫으면 나선이 +0.0132
    (배가 52 s)로 발산한다 — 워시아웃이 나선 주파수에서 요 댐퍼 권한을 없앤 탓이다. 종전 가드("극 전부 안정")는 이런
    조성을 불안정으로 보고 롤 댐퍼까지 꺼 버렸다(no_stable_gain, λ 2.32). 비행성 기준 안의 나선은 가드를 넘고,
    기준선을 그 배가시간 위로 올리면(대역) 같은 댐퍼가 다시 걸린다 — 면제의 근거가 정확히 그 선이다."""
    import control

    from claw.analysis import pi_loop
    from claw.design import tune as T
    from claw.design.closure import close_rates
    from claw.fcl.demo import demo_rate_filters

    ac = make_demo_aircraft()
    lat = split_axes_of(linearize(ac, trim_level(ac, TrimCase("t", mach=0.3, alt=0.0, fuel=200.0))))[1]
    rf = demo_rate_filters()
    prior = close_rates(lat, {"yaw.k_rate": 0.0, "roll.k_rate": -0.5225}, rf)
    act = {**ACT, "rate_filters": rf}
    v = T._damper_loop_verdict(prior, "yaw", "r", "dr", 0.5742, act)
    assert v["stable"] and v["spiral_t2_s"] == pytest.approx(52.4, rel=5e-3)
    assert v["max_re"] > 0.0  # 종전 규칙이면 불합격이었다
    loop = pi_loop(prior, x_out="r", u_in="dr", kp=0.5742, ki=0.0, sign=1.0, rate_filter=rf["yaw"], **ACT)
    unstable = [p for p in control.feedback(loop, 1, sign=1).poles() if p.real >= 0.0]
    assert len(unstable) == 1 and abs(unstable[0].imag) < 1e-9
    monkeypatch.setattr(T, "_SPIRAL_T2_MIN_S", 60.0)
    v2 = T._damper_loop_verdict(prior, "yaw", "r", "dr", 0.5742, act)
    assert not v2["stable"] and v2["bound"] == "spiral"


def split_axes_of(lm):
    from claw.trim import split_axes

    return split_axes(lm)


def _low_mach_washout(spiral_line=None):
    """구 기체 M0.2/h0/f40 + 요 워시아웃 — 댐퍼만 닫은 조성의 나선이 배가 18 s(수준 2 선 8 s와 수준 1 선 20 s
    사이)인 점. spiral_line을 주면 면제선을 그 값으로 바꿔(대역) 튜닝한다."""
    from claw.design import tune as T
    from claw.fcl.demo import demo_rate_filters

    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("lo", mach=0.2, alt=0.0, fuel=40.0), fingerprint="fp")
    assert tr.converged
    with pytest.MonkeyPatch.context() as mp:
        _guard_off(mp)  # 나선 면제선의 기구를 잰다 — 레이트 루프 마진 가드는 뺀다(no_rate_margin_guard와 같은 이유)
        if spiral_line is not None:
            mp.setattr(T, "_SPIRAL_T2_MIN_S", spiral_line)
        return tune_point(linearize(ac, tr), demo_design_gains(), **ACT, rate_filters=demo_rate_filters())


@pytest.fixture(scope="module")
def low_mach_washout():
    return _low_mach_washout()


@pytest.fixture(scope="module")
def low_mach_washout_level1():
    """같은 점을 나선 수준 1 선(20 s)으로 — 그 선이면 롤 댐퍼가 나선에 묶이고 요 2차 패스가 0을 낸다."""
    from claw.analysis.fq import FQCriteria

    return _low_mach_washout(FQCriteria().spiral_t2_l1)


def test_level_2_line_keeps_the_roll_damper_that_a_level_1_line_would_cap(low_mach_washout, low_mach_washout_level1):
    """면제선의 수준이 결과를 가르는 점 — 댐퍼만 닫은 조성의 나선이 배가 18.6 s다(요 목표 0.5였을 때 18.4 s — 요
    댐퍼가 세지면 조금 늘어난다). 수준 2 선(8 s, 기본)에서는 롤 댐퍼가 목표 λ 12를 내고(−1.117) 자세까지 닫은 전체
    폐루프가 안정이다. 수준 1 선(20 s)이었다면 나선 때문에 −0.718에 묶여 λ 7.78이었다 — 고장 상태(자세 루프가 빠진
    조성)의 나선 요구가 정상 상태의 롤 댐퍼를 깎는 모양."""
    out = low_mach_washout
    rr = out["achieved"]["roll_rate"]
    assert out["slots"]["roll_rate"]["reason"] == "ok" and rr["capped"] is None
    assert out["gains"]["roll.k_rate"] == pytest.approx(-1.117, rel=2e-3)
    assert rr["spiral_t2_s"] == pytest.approx(18.56, rel=5e-3)
    assert out["achieved"]["roll_att"]["closed_loop"]["stable"]
    strict = low_mach_washout_level1
    assert strict["slots"]["roll_rate"]["reason"] == "capped"
    assert strict["achieved"]["roll_rate"]["roll_lambda"] == pytest.approx(7.78, rel=2e-3)


def test_spiral_bound_cap_says_so_and_keeps_a_working_damper(low_mach_washout_level1):
    """나선 기준이 묶은 캡은 그렇다고 말한다 — "작동기·지연 경계"라 적으면 다음 수(작동기 예산)가 거짓이 된다.

    종전 이 점은 요·롤 댐퍼가 둘 다 꺼지고(no_stable_gain) 롤 자세가 마진 바닥이었다(λ 0.41). 나선선을 20 s로 두면
    롤 댐퍼는 나선 배가시간이 그 선에 닿는 크기(−0.718)에서 묶이고 λ 7.78을 낸다 — 작동하는 댐퍼다(capped는
    표본으로 남는다). 기본선(8 s)에서는 이 점이 캡에 안 걸린다 — 선을 대역해 문구 경로를 잰다."""
    out = low_mach_washout_level1
    rr = out["achieved"]["roll_rate"]
    assert out["slots"]["roll_rate"]["reason"] == "capped" and rr["cap_bound"] == "spiral"
    assert rr["spiral_t2_s"] == pytest.approx(20.0, rel=1e-3)
    assert out["gains"]["roll.k_rate"] == pytest.approx(-0.718, rel=2e-3)
    assert rr["roll_lambda"] == pytest.approx(7.78, rel=2e-3)
    assert any("나선 배가시간이 비행성 기준선" in n for n in out["notes"])
    assert not any("작동기·지연 포함 폐루프 안정 경계 아래로 축소" in n for n in out["notes"])
    assert out["slots"]["roll_att"]["reason"] == "ok"
    assert out["achieved"]["roll_att"]["closed_loop"]["stable"]


def test_second_pass_retunes_yaw_with_the_roll_damper_closed(no_rate_margin_guard):
    """저동압 델타(쇼케이스 M0.1077/h0): 롤이 열린 탐색 조성에서는 ζ_dr이 목표(기본 0.6 — 종전 0.5에도)에 못 닿아
    argmax 3.58(설계값 4.4배 — 대표 오차 10 °/s에 러더 36°)을 채택했다. 롤을 닫은 조성에서 다시 찾으면 1.29에서
    목표에 닿는다(10 °/s에 러더 13° — 목표 0.5였을 때 0.94) — 채택된다."""
    lm = _full_model(_S1_LOWQ_LON_A, _S1_LOWQ_LON_B, _S1_LOWQ_LAT_A, _S1_LOWQ_LAT_B)
    out = tune_point(lm, _S1_SEED, targets=TuneTargets(zeta_sp=0.9), **ACT)
    yr = out["achieved"]["yaw_rate"]
    sp = yr["second_pass"]
    assert {k: sp[k] for k in ("adopted", "k_first", "metric_first", "reached_first")} == {
        "adopted": True, "k_first": pytest.approx(3.581, rel=1e-3), "metric_first": pytest.approx(1.0),
        "reached_first": False}
    # 롤 댐퍼가 빠진 고장 상태(요 댐퍼만) — 채택 값에서 ζ_dr 0.316(목표 0.5일 때 0.283), 비행성 수준 1(하한 수준 2는
    # 묶지 않는다)
    fs = sp["failstate"]
    assert fs["level"] == 1 and fs["ok"] and fs["floor_mag"] is None
    assert fs["zeta_dr"] == pytest.approx(0.3155, abs=2e-3)
    assert out["gains"]["yaw.k_rate"] == pytest.approx(1.2931, rel=2e-3)
    assert yr["zeta_dr"] == pytest.approx(TuneTargets().zeta_dr, rel=1e-3) and yr["reached"]
    # 롤은 1차 패스 값 그대로이고, 바뀐 요 위에서도 목표를 낸다
    assert out["achieved"]["roll_rate"]["roll_lambda"] >= 12.0 * (1.0 - 1e-3)
    assert out["slots"]["roll_rate"]["reason"] == out["slots"]["yaw_rate"]["reason"] == "ok"
    assert out["achieved"]["roll_att"]["closed_loop"]["stable"]


def test_second_pass_is_not_adopted_when_it_would_switch_the_damper_off(low_mach_washout_level1):
    """롤(나선선 20 s에 묶인 −0.718)을 닫은 조성에서는 요 없이도 ζ_dr 0.5가 선다 — 재탐색은 0을 낸다. 댐퍼를 끄는
    해는 "다시 튜닝한 값"이 아니다(표에 0이 박히면 실패 자리값과 구별이 안 된다). 1차 패스 값을 그대로 쓰고 불채택
    사유를 남긴다."""
    out = low_mach_washout_level1
    sp = out["achieved"]["yaw_rate"]["second_pass"]
    assert sp["adopted"] is False and sp["k_second"] == 0.0 and "0" in sp["why"]
    assert out["gains"]["yaw.k_rate"] == pytest.approx(1.3, rel=1e-3)
    assert any("불채택" in n for n in out["notes"])


# 쇼케이스 기체 해면·연료 25 트림의 분리 모델 두 점 — _S1_LOWQ와 같은 S1 표 모드 세션의 이웃 앵커다. 롤 열림 조성
# (요 댐퍼만)의 더치롤 봉우리가 설계 목표 0.5를 사이에 두고 갈린다(아래 점 0.493 < 0.5 ≤ 0.504 위 점) — 접근 속도
# 42 m/s(해면 M0.123) 바로 위, 종전 규칙에서 요 표가 2.9배 뛰던 자리다. 값은 그 세션의 선형모델 그대로 싣는다.
# 경계는 목표가 정한다 — 기본 목표가 0.6으로 오른 뒤에는 두 점 다 봉우리가 목표 아래라, 경계 검사는 이 두 점이
# 갈리는 목표 0.5를 명시해 잰다(_S1_BOUNDARY_TARGETS)
_S1_BELOW_LON_A = [[-0.06756512940928665, 0.13427243712544157, -7.797512691223691, -9.640441704050316],
                   [-0.2032646823292587, -1.3992466457020714, 41.12523518056988, -1.7978509311953008],
                   [0.031019786353938077, -0.16633444592420887, -1.2690162908108777, 0.0],
                   [0.0, 0.0, 1.0, 0.0]]
_S1_BELOW_LON_B = [[-0.42186768179622697, 3.9931650137207595], [-6.786069825856039, 0.0],
                   [-10.033914153412912, 0.0], [0.0, 0.0]]
_S1_BELOW_LAT_A = [[-0.21939539285738632, 7.765499842450566, -41.64018675541677, 9.6404417040128],
                   [-0.720675918238303, -2.97278816273289, 0.45042244889892263, 0.0],
                   [0.08969231658484385, -0.024914532384677925, -0.1494871943080675, 0.0],
                   [0.0, 1.0, 0.18649051427321925, 0.0]]
_S1_BELOW_LAT_B = [[0.0, 1.507134860595], [27.473812562929684, 0.0],
                   [-0.3377062747812099, -1.68853137390605], [0.0, 0.0]]
_S1_ABOVE_LON_A = [[-0.06666918574144998, 0.13084082462384403, -7.623324619695618, -9.655390880262917],
                   [-0.19979369880302034, -1.4259039072029336, 42.19642063982184, -1.7157538194234279],
                   [0.030325810759858067, -0.17065831426948475, -1.2999885462154444, 0.0],
                   [0.0, 0.0, 1.0, 0.0]]
_S1_ABOVE_LON_B = [[-0.4259788635018984, 3.898027770349341], [-7.103597207008403, 0.0],
                   [-10.529676730004091, 0.0], [0.0, 0.0]]
_S1_ABOVE_LAT_A = [[-0.22220723826446545, 7.591769939094085, -42.72262454373038, 9.655390880257984],
                   [-0.7382651003199081, -3.045343538819514, 0.46141568769992625, 0.0],
                   [0.09188139276708715, -0.025522609101967755, -0.15313565461180648, 0.0],
                   [0.0, 1.0, 0.17769905337447703, 0.0]]
_S1_ABOVE_LAT_B = [[0.0, 1.581600423118968], [28.831257713106186, 0.0],
                   [-0.3543919001867085, -1.771959500933543], [0.0, 0.0]]
# 위 두 점이 롤 열림 도달 경계를 사이에 두는 목표 — 쇼케이스 기록 설정(zeta_sp 0.9)에 종전 요 목표 0.5
_S1_BOUNDARY_TARGETS = TuneTargets(zeta_sp=0.9, zeta_dr=0.5)


def test_second_pass_keeps_the_yaw_table_continuous_across_the_open_composition_reach_boundary(no_rate_margin_guard):
    """롤 열림 조성에서 목표가 서기 시작하는 경계 양쪽 — 종전에는 표가 뛰었다(0.922 → 2.671, 마하 0.003 사이 2.9배).

    아래 점(M0.124475/h0)은 롤 열림 봉우리 0.493이라 1차 패스가 못 닿아 2차 패스가 0.922를 냈다. 위 점(M0.127513/h0)은
    봉우리 0.504라 1차 패스가 봉우리 옆 2.671에서 닿았고, 종전 규칙(못 닿은 자리에만 2차 패스)은 그 값을 그대로 썼다 —
    최종 조성 ζ_dr 1.0(과감쇠), 대표 오차 10 °/s에 러더 27°. 이제 닿은 자리도 롤을 닫은 조성에서 목표에 처음 닿는
    크기로 다시 찾아 0.905다(이웃 비 1.02). 롤 댐퍼가 빠진 고장 상태는 두 점 다 ζ_dr 0.31(비행성 수준 1)이다.
    경계가 이 두 점 사이에 서는 목표 0.5로 잰다(_S1_BOUNDARY_TARGETS) — 기본 목표 0.6에서는 경계가 여기 없고, 두 점의
    표 값이 이어지는지만 끝에서 따로 본다."""
    kw = dict(targets=_S1_BOUNDARY_TARGETS, **ACT)
    below = tune_point(_full_model(_S1_BELOW_LON_A, _S1_BELOW_LON_B, _S1_BELOW_LAT_A, _S1_BELOW_LAT_B), _S1_SEED, **kw)
    above = tune_point(_full_model(_S1_ABOVE_LON_A, _S1_ABOVE_LON_B, _S1_ABOVE_LAT_A, _S1_ABOVE_LAT_B), _S1_SEED, **kw)
    kb, ka = below["gains"]["yaw.k_rate"], above["gains"]["yaw.k_rate"]
    assert kb == pytest.approx(0.9223, rel=2e-3)
    assert ka == pytest.approx(0.9054, rel=2e-3)
    assert max(kb / ka, ka / kb) < 1.1, f"경계 양쪽 요 게인 {kb:.4g} / {ka:.4g} — 표가 뛴다"
    spb, spa = below["achieved"]["yaw_rate"]["second_pass"], above["achieved"]["yaw_rate"]["second_pass"]
    assert spb["reached_first"] is False and spa["reached_first"] is True, "경계를 사이에 둔 두 점이 아니다"
    assert spa["adopted"] and spa["k_first"] == pytest.approx(2.671, rel=1e-3)
    assert spa["metric_first"] == pytest.approx(1.0), "1차 값이 최종 조성에서 과감쇠였다는 전제"
    for out in (below, above):
        yr = out["achieved"]["yaw_rate"]
        assert yr["zeta_dr"] == pytest.approx(0.5, rel=1e-3) and out["slots"]["yaw_rate"]["reason"] == "ok"
        assert out["slots"]["roll_rate"]["reason"] == "ok"
        assert out["achieved"]["roll_att"]["closed_loop"]["stable"]
        fs = yr["second_pass"]["failstate"]
        assert fs["level"] == 1 and fs["floor_mag"] is None
        assert fs["zeta_dr"] == pytest.approx(0.31, abs=5e-3)
    assert any("과감쇠" in n and "다시 찾았다" in n for n in above["notes"]), above["notes"]
    # 기본 목표(쇼케이스 기록 설정 — zeta_sp만 덮는다)에서도 두 점의 표 값은 이어진다: 둘 다 롤 열림에서 못 닿아 2차
    # 패스 값 1.227 · 1.200(이웃 비 1.02)
    kw0 = dict(targets=TuneTargets(zeta_sp=0.9), **ACT)
    b0 = tune_point(_full_model(_S1_BELOW_LON_A, _S1_BELOW_LON_B, _S1_BELOW_LAT_A, _S1_BELOW_LAT_B), _S1_SEED, **kw0)
    a0 = tune_point(_full_model(_S1_ABOVE_LON_A, _S1_ABOVE_LON_B, _S1_ABOVE_LAT_A, _S1_ABOVE_LAT_B), _S1_SEED, **kw0)
    kb0, ka0 = b0["gains"]["yaw.k_rate"], a0["gains"]["yaw.k_rate"]
    assert (kb0, ka0) == (pytest.approx(1.2266, rel=2e-3), pytest.approx(1.2004, rel=2e-3))
    assert max(kb0 / ka0, ka0 / kb0) < 1.1
    for out in (b0, a0):
        assert out["achieved"]["yaw_rate"]["zeta_dr"] == pytest.approx(TuneTargets().zeta_dr, rel=1e-3)
        assert out["slots"]["yaw_rate"]["reason"] == out["slots"]["roll_rate"]["reason"] == "ok"


def _s1_lowq_point():
    return _full_model(_S1_LOWQ_LON_A, _S1_LOWQ_LON_B, _S1_LOWQ_LAT_A, _S1_LOWQ_LAT_B)


# 고장 상태 하한 경로를 재는 목표 — 이 점의 2차 값이 대역 하한(수준 2 ζ 0.30) 아래에 서는 종전 요 목표 0.5(2차 값 0.939 →
# 롤 열림 ζ_dr 0.283). 기본 목표 0.6이면 2차 값 1.293의 롤 열림 ζ_dr이 0.316이라 그 대역 하한이 묶이지 않는다 — 목표를
# 올린 것이 고장 상태 하한과 부딪히지 않는다는 뜻이기도 하다
_S1_FLOOR_TARGETS = TuneTargets(zeta_sp=0.9, zeta_dr=0.5)


def _strict_dutch_roll_levels(monkeypatch, zeta_l1, zeta_l2):
    """고장 상태 하한을 대역한다 — 기본 기준(수준 2 ζ ≥ 0.02)은 실측 네 설정 어디서도 묶지 않으므로 규칙 경로를
    재려면 더치롤 수준 ζ 선만 올린 기준을 튜너에 넣는다(ζωn·ωn 선은 그대로)."""
    from claw.analysis.fq import FQCriteria
    from claw.design import tune as T

    monkeypatch.setattr(T, "FQCriteria", lambda: FQCriteria(dr_zeta_l1=zeta_l1, dr_zeta_l2=zeta_l2))


def test_failure_state_floor_raises_the_second_pass_gain_to_its_first_reach(monkeypatch):
    """고장 상태 하한이 묶으면 두 요구(정상 상태 목표·고장 상태 수준)를 다 채우는 최소 크기로 올린다.

    이 점(M0.1077/h0)의 2차 값 0.939(목표 0.5 — _S1_FLOOR_TARGETS)는 롤 열림 ζ_dr 0.283이다. 수준 2 ζ 선을 0.30으로
    대역하면 하한 밖이라, 롤 열림 조성에서 0.30에 처음 닿는 1.12로 오른다 — 최종 조성은 목표를 넘기고(ζ_dr 0.55), 1차
    값 3.58보다는 여전히 작다."""
    _strict_dutch_roll_levels(monkeypatch, 0.35, 0.30)
    out = tune_point(_s1_lowq_point(), _S1_SEED, targets=_S1_FLOOR_TARGETS, **ACT)
    yr = out["achieved"]["yaw_rate"]
    sp, fs = yr["second_pass"], yr["second_pass"]["failstate"]
    assert sp["adopted"] and fs["floor_attainable"]
    assert fs["floor_mag"] == pytest.approx(1.120, rel=5e-3)
    assert abs(out["gains"]["yaw.k_rate"]) == pytest.approx(fs["floor_mag"], rel=1e-9), "하한 크기로 오르지 않았다"
    assert fs["zeta_dr"] >= 0.30 and fs["level"] == 2 and fs["ok"]
    assert yr["zeta_dr"] > 0.5 and out["slots"]["yaw_rate"]["reason"] == "ok"
    assert abs(out["gains"]["yaw.k_rate"]) < sp["k_first"]
    assert any("하한이 크기를" in n for n in out["notes"]), out["notes"]


def test_failure_state_floor_is_not_applied_where_the_yaw_damper_alone_cannot_reach_it(monkeypatch, no_rate_margin_guard):
    """요 댐퍼만으로는 어떤 크기에서도 하한에 못 드는 자리(롤 열림 봉우리 0.420 < 대역 수준 2 ζ 0.45) — 1차 값도 못
    채우므로 가를 근거가 없다. 하한을 걸지 않고 정상 상태 값(0.939)을 쓰며, 그 사실을 남긴다."""
    _strict_dutch_roll_levels(monkeypatch, 0.5, 0.45)
    out = tune_point(_s1_lowq_point(), _S1_SEED, targets=_S1_FLOOR_TARGETS, **ACT)
    sp = out["achieved"]["yaw_rate"]["second_pass"]
    assert sp["adopted"] and sp["failstate"]["floor_attainable"] is False and not sp["failstate"]["ok"]
    assert out["gains"]["yaw.k_rate"] == pytest.approx(0.939, rel=2e-3)
    assert any("어떤 크기에서도 들지 못한다" in n for n in out["notes"]), out["notes"]


def test_second_pass_is_not_adopted_when_it_drops_the_failure_state_below_the_floor(monkeypatch):
    """1차 값이 지키던 고장 상태 하한을 2차 값이 버리면 불채택이다 — 비행성 요구가 권한 절약보다 앞선다.

    대역 수준 2 ζ 0.30에서 1차 값 3.58은 롤 열림 ζ_dr 0.42로 하한 안이다. 하한으로 올린 1.12를 가드가 그 아래로
    깎는 상황(대역 — 올린 호출만 0.9배로 캡)이면 채택 값의 고장 상태가 하한 밖이 된다 → 1차 값을 그대로 둔다."""
    from claw.design import tune as T

    _strict_dutch_roll_levels(monkeypatch, 0.35, 0.30)
    orig = T._search_rate

    def capped_raise(*a, mag_min=0.0, **kw):
        k, entry = orig(*a, mag_min=mag_min, **kw)
        if mag_min > 0.0:
            return math.copysign(0.9 * mag_min, k), {**entry, "capped": "capped"}
        return k, entry

    monkeypatch.setattr(T, "_search_rate", capped_raise)
    out = tune_point(_s1_lowq_point(), _S1_SEED, targets=_S1_FLOOR_TARGETS, **ACT)
    sp = out["achieved"]["yaw_rate"]["second_pass"]
    assert sp["adopted"] is False and "고장 상태" in sp["why"], sp
    assert not sp["failstate"]["ok"]
    assert out["gains"]["yaw.k_rate"] == pytest.approx(3.581, rel=1e-3)


def test_failure_state_dutch_roll_without_an_oscillatory_mode_passes(setup):
    """고장 상태 조성에 진동 더치롤이 없으면(모드가 실근으로 교환 — 지표가 ζ 1.0·wn None) 감쇠 요구가 걸릴 모드가
    없다 — 통과다. 구 기체 M0.45/h1000에 요 댐퍼만 닫으면 1.0에서 그렇다(0.9에서는 ζ 0.958·wn 2.66 진동쌍 — 수준 1).
    요 댐퍼가 약하면(0.05 — ζ 0.088) 수준 1 선(0.08) 바로 위다. 수준은 비행성 기준(FQCriteria)이 가른다."""
    from claw.design.tune import _failstate_dr
    from claw.trim import split_axes

    _, _, _, lm = setup
    lat = split_axes(lm)[1]
    fs = _failstate_dr(lat, {"yaw.k_rate": 1.0, "roll.k_rate": 0.0}, {})
    assert fs == {"zeta_dr": 1.0, "wn_dr": None, "level": None, "ok": True}
    osc = _failstate_dr(lat, {"yaw.k_rate": 0.9, "roll.k_rate": 0.0}, {})
    assert osc["wn_dr"] == pytest.approx(2.66, rel=1e-2) and osc["level"] == 1 and osc["ok"]
    weak = _failstate_dr(lat, {"yaw.k_rate": 0.05, "roll.k_rate": 0.0}, {})
    assert weak["zeta_dr"] == pytest.approx(0.0876, abs=1e-3) and weak["level"] == 1


def test_tuned_attitude_loop_is_stable_with_everything_closed(no_rate_margin_guard):
    """보드 마진(레이트를 이상 폐쇄한 A′ 위 SISO)만으로 받던 자세 해가 실제 조성에서는 서지 않았다 — 구 기체 설계점
    M0.6/h1000의 종전 피치 해(kp −0.6865·ki −0.1029, 자세 루프 PM·GM 합격)는 피치 댐퍼까지 작동기·지연을 거쳐 닫으면
    15.9 rad/s 진동의 ζ가 0.024다(δe 채널에서 끊은 루프로 GM 0.9 dB·PM 4.6°). 백오프는 이제 전체 폐루프가 서는
    해만 받는다 — 교차를 더 낮춘 해(대역폭 하한 미달 — 통과가 아니다)를 내고, 그 해는 전체 폐루프가 선다."""
    from claw.design import tune as T
    from claw.design.closure import closed_loop_poles
    from claw.fcl.demo import demo_design_gains

    ac = make_demo_aircraft()
    lm = linearize(ac, trim_level(ac, TrimCase("t", mach=0.6, alt=1000.0, fuel=200.0), fingerprint="fp"))
    lon = split_axes_of(lm)[0]
    out = tune_point(lm, demo_design_gains(), **ACT)
    kr = out["gains"]["pitch.k_rate"]
    assert kr == pytest.approx(0.1001, rel=1e-3)
    old = closed_loop_poles(lon, {"pitch.k_rate": kr}, kp=-0.6865, ki=-0.1029, **ACT)
    worst = min((p for p in old if p.imag > 1e-9 and abs(p) > 9.0), key=lambda p: -p.real / abs(p))
    assert abs(worst) == pytest.approx(15.9, abs=0.1) and -worst.real / abs(worst) < 0.03
    assert not T._full_loop_stable(lon, {"pitch.k_rate": kr}, -0.6865, -0.1029, 1, ACT)
    pa = out["achieved"]["pitch_att"]
    assert out["slots"]["pitch_att"]["reason"] == T.REASON_BANDWIDTH_COLLAPSE
    assert pa["closed_loop"]["stable"] and pa["pm_deg"] >= 50.0
    for axis in ("pitch", "roll"):
        assert out["achieved"][f"{axis}_att"]["closed_loop"]["stable"], axis


def test_joint_damper_divergence_fails_the_last_closed_damper_too(setup, no_rate_margin_guard):
    """댐퍼마다 가드를 넘어도 함께 닫으면 발산할 수 있다 — 롤 가드는 요 댐퍼를 **이상 폐쇄**로 접은 프리픽스에서
    잰다. 지연 0.2 s에서 요·롤이 각자 합격인데 함께 닫으면 발산한다: 마지막에 닫힌 롤 댐퍼와 롤 자세가 둘 다
    loop_unstable이다(요는 자기 조성에서 성립했다). 그러면 적합 제외가 롤 세 자리를 함께 뺀다."""
    from claw.design.tune import REASON_LOOP_UNSTABLE, failed_gain_slots

    _, design, _, lm = setup
    out = tune_point(lm, design, **{**ACT, "delay_s": 0.2})
    cl = out["achieved"]["roll_att"]["closed_loop"]
    assert not cl["stable"] and not cl["rates_only"]["stable"]
    assert out["slots"]["roll_rate"]["reason"] == out["slots"]["roll_att"]["reason"] == REASON_LOOP_UNSTABLE
    assert out["slots"]["yaw_rate"]["reason"] == "ok"
    assert set(failed_gain_slots(out["slots"])) >= {"roll.k_rate", "roll.kp", "roll.ki"}
    assert any("댐퍼를 함께 닫은 조성" in n for n in out["notes"])


def test_failed_gain_slots_follow_the_closure_order():
    """표본으로 못 쓰는 게인 — 자기 실패는 그 자리, 레이트 실패는 **뒤에 닫히는** 같은 축 자리 전부.

    요 실패는 롤 댐퍼(요 = 0 프리픽스에서 찾음)와 롤 자세를, 롤 댐퍼 실패는 롤 자세만, 피치 댐퍼 실패는 피치 자세를
    끌고 간다. 자세 실패는 자기뿐이다. 자기 실패 사유가 rate_loop 표시보다 우선한다. capped·target_unreached는
    작동하는 댐퍼라 표본이다."""
    from claw.design.tune import downstream_loops, failed_gain_slots

    assert downstream_loops("yaw_rate") == ["roll_rate", "roll_att"]
    assert downstream_loops("roll_rate") == ["roll_att"]
    assert downstream_loops("pitch_rate") == ["pitch_att"]
    assert downstream_loops("roll_att") == [] and downstream_loops("nope") == []
    ok = {"reason": "ok"}
    got = failed_gain_slots({"yaw_rate": {"reason": "no_stable_gain"}, "roll_rate": dict(ok),
                             "roll_att": {"reason": "margin_floor"}, "pitch_rate": {"reason": "capped"},
                             "pitch_att": dict(ok)})
    assert got == {
        "yaw.k_rate": {"loop": "yaw_rate", "reason": "no_stable_gain", "basis": "own"},
        "roll.k_rate": {"loop": "yaw_rate", "reason": "no_stable_gain", "basis": "rate_loop"},
        "roll.kp": {"loop": "roll_att", "reason": "margin_floor", "basis": "own"},
        "roll.ki": {"loop": "roll_att", "reason": "margin_floor", "basis": "own"},
    }
    assert failed_gain_slots({"pitch_rate": {"reason": "target_unreached"}, "yaw_rate": {"reason": "capped"}}) == {}


# ── 레이트 루프 마진 가드 (AS94900 끊은 루프 — Q1) ─────────────────────────────────────────────────────────────


def _s1_point(mach, alt, fuel):
    """쇼케이스 기체(200 kg급 EO/IR 정찰 델타) 문서 그대로의 선형 모델 + 문서 설계 게인·레이트 필터."""
    from claw.profile import build_profile, load_showcase

    prof = build_profile(load_showcase())
    ac = prof.aircraft()
    tr = trim_level(ac, TrimCase("s1", mach=mach, alt=alt, fuel=fuel), fingerprint="fp")
    assert tr.converged
    return linearize(ac, tr), prof.design_gains(), prof.rate_filters()


def test_rate_margin_guard_caps_the_roll_damper_to_the_design_margin():
    """쇼케이스 기체 M0.12/h200(P6 마진 맵이 roll_p GM 4.1~5.1 dB를 찾은 자리) — 롤 λ 목표 12가 댐퍼 교차를 작동기(30 rad/s)
    쪽으로 밀어 AS94900 끊은 루프(요 댐퍼 닫음, 작동기+Padé 35 ms) 여유가 GM 6.97 dB(목표 8)다. 가드는 |k|를 여유가 설계
    목표(TuneTargets PM 50°·GM 8 dB) + 가드 밴드(0.25 dB — 검증점이 목표선에 동전 던지기로 앉지 않게)에 닿는 크기로 묶고
    그 사실을 사유(capped)·cap_bound("margin")·note로 남긴다. 그 대가로 λ가 목표 아래다(10.65 — 합격선 6·목표선 9.6 위)."""
    from claw.design import tune as T

    lm, design, rf = _s1_point(0.12, 200.0, 10.0)
    on = tune_point(lm, design, rate_filters=rf, **ACT)
    with pytest.MonkeyPatch.context() as mp:
        _guard_off(mp)
        off = tune_point(lm, design, rate_filters=rf, **ACT)
    r_off, r_on = off["achieved"]["roll_rate"], on["achieved"]["roll_rate"]
    # 가드 없이는 목표 λ를 내고 여유가 목표 아래다 — 이 시험이 재는 결함 그 자체
    assert off["slots"]["roll_rate"]["reason"] == "ok"
    assert r_off["gm_db"] == pytest.approx(6.97, abs=0.02) and r_off["gm_db"] < TuneTargets().gm_db
    # 가드가 묶는다 — 여유가 목표에 닿고(이분 수렴), 게인은 작아지며, 사유가 무엇이 묶었는지 말한다
    assert on["slots"]["roll_rate"]["reason"] == T.REASON_CAPPED and r_on["cap_bound"] == "margin"
    # 가드는 탐색 조성(1차 요 값을 닫음)에서 목표 + 밴드에 붙이고, 보고는 최종 조성(2차 패스 요)에서 다시 잰다 — 8.251 dB
    assert r_on["gm_db"] == pytest.approx(TuneTargets().gm_db + 0.25, abs=0.01)
    assert r_on["pm_deg"] >= TuneTargets().pm_deg
    assert abs(on["gains"]["roll.k_rate"]) < abs(off["gains"]["roll.k_rate"])
    assert r_on["roll_lambda"] == pytest.approx(10.65, abs=0.02)
    assert r_on["loop_margins"]["closed_with"] == ["yaw_rate"] and not r_on["loop_margins"]["divergent"]
    assert any(n.startswith("roll.k_rate: 레이트 루프 마진 가드 적용") for n in on["notes"]), on["notes"]
    # 롤 자세와 전체 폐루프는 묶인 댐퍼 위에서 그대로 성립한다
    assert on["slots"]["roll_att"]["reason"] == "ok" and on["achieved"]["roll_att"]["closed_loop"]["stable"]


def test_rate_margin_guard_leaves_a_point_that_already_keeps_the_margin_unchanged():
    """이미 여유를 지키는 점(쇼케이스 M0.2/h0 — 레이트 루프 GM 9.6·14.9·15.4 dB)은 가드가 있든 없든 게인·사유가 비트까지 같다."""
    lm, design, rf = _s1_point(0.2, 0.0, 25.0)
    on = tune_point(lm, design, rate_filters=rf, **ACT)
    with pytest.MonkeyPatch.context() as mp:
        _guard_off(mp)
        off = tune_point(lm, design, rate_filters=rf, **ACT)
    assert on["gains"] == off["gains"]
    assert {k: v["reason"] for k, v in on["slots"].items()} == {k: v["reason"] for k, v in off["slots"].items()}
    assert on["notes"] == off["notes"]
    for loop in ("pitch_rate", "yaw_rate", "roll_rate"):
        r = on["achieved"][loop]
        assert r["gm_db"] >= 9.0 and r["pm_deg"] >= 50.0 and r.get("cap_bound") is None, loop


def test_rate_loop_margins_read_the_loop_band_only():
    """끊은 루프 여유는 루프 대역 교차만 읽는다 — 수치 자체는 엔진 nyquist_margins(broken_loop) 그대로다(재계산 없음).

    예제 기체 M0.112875/h0/f50 롤 댐퍼(요 댐퍼 닫음): 닫아 둔 요 루프가 워시아웃 없이(정적 게인 — broken_loop 계약)
    닫혀 ω = 0에 GM 0.33 dB·0.013 rad/s에 PM 17.9° 교차가 생긴다 — 나선 영역이고 워시아웃째 닫은 조성에는 없는 교차다.
    nyquist_margins는 그것을 최솟값으로 고른다. 루프 대역(0.4 × 더치롤 wn 위)의 교차는 PM 35.0° @ 12.5 rad/s · GM
    4.08 dB @ 18.9 rad/s이고, 뺀 교차는 low_band로 공개한다."""
    from claw.analysis.margins import broken_loop, nyquist_margins
    from claw.design.tune import rate_loop_margins
    from claw.profile import build_profile
    from claw.profile.document import load_shipped_example
    from claw.trim import split_axes

    prof = build_profile(load_shipped_example())  # 제품 예제 — 시험의 load_example은 구 기체다(conftest)
    ac = prof.aircraft()
    lat = split_axes(linearize(ac, trim_level(ac, TrimCase("x", mach=0.112875, alt=0.0, fuel=50.0))))[1]
    # 예제 기본 설정 자동 설계의 그 앵커 게인 그대로 — 저주파 교차는 게인 넷째 자리에도 크게 움직인다(0.7417·−0.7221로
    # 반올림하면 ω = 0 GM이 0.33 → 18 dB). 조성에 민감한 자리라 판정에서 빼는 근거이기도 하다
    g = {"yaw.k_rate": 0.7417231857776643, "roll.k_rate": -0.7221055261790754}
    m = rate_loop_margins(lat, "roll", g, {**ACT, "rate_filters": prof.rate_filters()})
    ref = nyquist_margins(broken_loop(lat, "p", "da", g["roll.k_rate"], 0.0, -1.0,
                                      [{"x_out": "r", "u_in": "dr", "kp": g["yaw.k_rate"], "ki": 0.0, "sign": -1.0}],
                                      **ACT))
    assert ref["gm_db"] == pytest.approx(0.334, abs=2e-3) and ref["wcg"] == 0.0  # 전 교차 최솟값은 나선 영역
    band_g = [c for c in ref["crossings"]["gain"] if c["w"] >= m["band_floor"]]
    band_p = [c for c in ref["crossings"]["phase"] if c["w"] >= m["band_floor"]]
    assert m["pm_deg"] == min(abs(c["pm_deg"]) for c in band_g) == pytest.approx(34.95, abs=0.02)
    assert m["gm_db"] == min(abs(c["gm_db"]) for c in band_p) == pytest.approx(4.083, abs=2e-3)
    assert m["wcp"] == pytest.approx(12.49, abs=0.01) and m["wcg"] == pytest.approx(18.88, abs=0.01)
    assert m["low_band"] == {"pm_deg": pytest.approx(17.90, abs=0.01), "gm_db": pytest.approx(0.334, abs=2e-3)}
    assert m["closed_with"] == ["yaw_rate"] and m["divergent"] is False and "closed_loop" not in m
    # 게인 0인 자리는 잴 루프가 없다 — 0 dB로 위장하지 않는다. 닫아 둘 루프가 0이면 그 루프는 빠진다
    assert rate_loop_margins(lat, "roll", {**g, "roll.k_rate": 0.0}, ACT) is None
    assert rate_loop_margins(lat, "roll", {**g, "yaw.k_rate": 0.0}, ACT)["closed_with"] == []
    # 루프 대역에서 발산(2배 — 20 rad/s 진동 실부 +1.58)은 여유가 정의되지 않는다: divergent, 가드 판정은 미달
    big = rate_loop_margins(lat, "roll", {**g, "roll.k_rate": 2.0 * g["roll.k_rate"]}, ACT)
    assert big["divergent"] is True and big["closed_loop"]["unstable"][0][1] > 10.0
    from claw.design.tune import _rate_margin_verdict
    assert _rate_margin_verdict(big, TuneTargets()) == "short"
    assert _rate_margin_verdict(None, TuneTargets()) == "ok"


def test_rate_margin_cap_is_the_largest_gain_that_keeps_the_target():
    """_cap_by_margins — 목표를 지키면 손대지 않고(None), 못 지키면 목표 + 가드 밴드(PM 0.5°·GM 0.25 dB) 경계로 이분한
    크기(부호 유지). 목표와 밴드 사이(여유 8~8.25 dB)는 이미 목표를 지키므로 손대지 않는다."""
    from claw.design.tune import _cap_by_margins, rate_loop_margins
    from claw.trim import split_axes

    lm, design, rf = _s1_point(0.12, 200.0, 10.0)
    lat = split_axes(lm)[1]
    act = {**ACT, "rate_filters": rf}
    others = {"yaw.k_rate": 0.6}
    k, why = _cap_by_margins(lat, "roll", -0.1, others, act, TuneTargets())
    assert (k, why) == (-0.1, None)
    k, why = _cap_by_margins(lat, "roll", -2.0, others, act, TuneTargets())
    assert why == "capped" and -2.0 < k < 0.0
    m = rate_loop_margins(lat, "roll", {**others, "roll.k_rate": k}, act)
    assert min(m["gm_db"] - 8.25, m["pm_deg"] - 50.5) == pytest.approx(0.0, abs=1e-4)
    # 목표와 밴드 사이 크기는 그대로다 — 여유 8.1 dB가 되는 크기(경계 크기 × 10^(0.15/20))
    k_mid = k * 10 ** (0.15 / 20)
    assert 8.0 < rate_loop_margins(lat, "roll", {**others, "roll.k_rate": k_mid}, act)["gm_db"] < 8.25
    assert _cap_by_margins(lat, "roll", k_mid, others, act, TuneTargets()) == (k_mid, None)
