"""M17 schedmap 검증 — 실효 게인 보간, 상수 게인 마진맵과의 차이, actuator/delay 조성 일치."""

import numpy as np
import pytest

from claw.analysis import loop_margins, pi_loop
from claw.common.contracts import TrimCase
from claw.design import (
    ROLE_ANCHOR,
    ROLE_BREAKPOINT,
    LinearModelSet,
    MarginCriteria,
    OperatingPoint,
    PointSet,
    case_name,
    midpoint_validation_points,
    scheduled_gains,
    scheduled_margin_map,
    scheduled_margin_point,
)
from claw.design.closure import AXIS_SPECS, close_rates, rate_loop_crossover
from claw.fcl.demo import demo_design_gains, make_demo_gain_tables
from claw.plant import make_demo_aircraft
from claw.tables import Table
from claw.trim import linearize, split_axes, trim_level


@pytest.fixture(scope="module")
def setup():
    ac = make_demo_aircraft()
    tables = make_demo_gain_tables()
    design = demo_design_gains()
    return ac, tables, design


def _case(mach, alt=1000.0, fuel=200.0):
    return TrimCase(name=case_name(mach, alt, fuel), mach=mach, alt=alt, fuel=fuel)


def test_effective_gain_on_breakpoint_equals_table(setup):
    """breakpoint 좌표에서 보간 게인 == 테이블 값, 스케줄 안 덮는 자리는 설계 상수."""
    _, tables, design = setup
    case = _case(0.4)  # 데모 테이블 breakpoint (0.15~0.95 step 0.05)
    eff = scheduled_gains(tables, design, case)
    t = tables["pitch.kp"]
    i = int(np.argwhere(np.isclose(t.axes[0], 0.4))[0][0])
    assert eff["pitch.kp"] == pytest.approx(float(t.data[i]))
    assert eff["yaw.k_rate"] == pytest.approx(design["yaw.k_rate"])  # 스케줄 밖 자리


def test_midpoint_gain_is_interpolated(setup):
    """breakpoint 사이 중점은 선형 보간값 — 상수도 어느 한쪽 breakpoint 값도 아니다."""
    _, tables, design = setup
    eff = scheduled_gains(tables, design, _case(0.425))
    t = tables["pitch.kp"]
    lo = float(t.interp(mach=0.4))
    hi = float(t.interp(mach=0.45))
    assert eff["pitch.kp"] == pytest.approx((lo + hi) / 2.0)
    assert eff["pitch.kp"] != pytest.approx(design["pitch.kp"])


def test_margin_point_matches_direct_composition(setup):
    """scheduled_margin_point == 실효 게인으로 직접 조성한 successive closure 마진/지표."""
    ac, tables, design = setup
    case = _case(0.6)
    tr = trim_level(ac, case)
    assert tr.converged
    lm = linearize(ac, tr)
    out = scheduled_margin_point(
        lm, tables, design, case,
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    )
    from claw.design.closure import att_margin_loop, axis_metrics, oriented_margins
    from claw.trim import split_axes

    lon, lat = split_axes(lm)
    eff = scheduled_gains(tables, design, case)
    ref_m, ref_orient = oriented_margins(att_margin_loop(
        lon, {"pitch.k_rate": eff["pitch.k_rate"]}, eff["pitch.kp"], eff["pitch.ki"],
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    ))
    assert out["pitch_att"]["pm_deg"] == pytest.approx(ref_m["pm_deg"])
    assert out["pitch_att"]["orientation"] == ref_orient
    ref_zeta = axis_metrics(lon, {"pitch.k_rate": eff["pitch.k_rate"]})["zeta_sp"]
    assert out["pitch_rate"]["zeta"] == pytest.approx(ref_zeta)
    # 횡축은 요·롤 댐퍼를 함께 닫은 지표 — 요 자리가 ζ_dr, 롤 자리가 λ_roll
    assert out["yaw_rate"]["kind"] == "damping" and "zeta" in out["yaw_rate"]
    assert out["roll_rate"]["kind"] == "bandwidth" and out["roll_rate"]["roll_lambda"] > 0


def test_design_point_composition_is_sane(setup):
    """설계점(M0.6)에서 설계 게인의 조성 판정이 정상 범위 — 자세 마진 PM>0, 댐퍼 감쇠 개선.

    평탄 SISO 선언(GROUP_LOOPS)으로 절대 판정하면 설계점조차 PM 12°/−168°가 나온다
    (closure.py 머리말) — successive closure 조성이 그 병리를 벗어났는지 핀한다.
    """
    ac, tables, design = setup
    case = _case(0.6)
    tr = trim_level(ac, case)
    lm = linearize(ac, tr)
    out = scheduled_margin_point(lm, tables, design, case)
    assert out["pitch_att"]["pm_deg"] > 30.0  # 레이트 폐쇄 후에는 설계점 자세 마진이 정상
    assert out["pitch_rate"]["zeta"] > 0.5  # 개루프 ζ_sp 0.19 → 댐퍼가 올린다
    assert out["yaw_rate"]["zeta"] > 0.3  # 개루프 ζ_dr 0.05 → 요 댐퍼가 올린다


def test_scheduled_differs_from_constant_gain_map(setup):
    """저마하에서 스케줄 실효 게인(동압 스케일 ×배)의 판정은 설계 상수와 유의미하게 다르다.

    기존 마진맵(상수 게인) 경로가 §3.4 검증 요구를 대신할 수 없다는 실증.
    """
    ac, tables, design = setup
    case = _case(0.3)  # f = (0.6/0.3)² = 4 (상한) — 실효 게인이 설계값의 4배
    tr = trim_level(ac, case)
    assert tr.converged
    lm = linearize(ac, tr)
    sched = scheduled_margin_point(lm, tables, design, case)
    const = scheduled_margin_point(lm, {}, design, case)  # 스케줄 없음 = 설계 상수
    assert sched["pitch_rate"]["gains"]["k_rate"] == pytest.approx(
        design["pitch.k_rate"] * 4.0
    )
    # 실효 게인 4배 → 레이트 루프 교차 주파수가 뚜렷이 다르다 (동압 보상의 실체)
    assert sched["pitch_rate"]["wc"] > 2.0 * const["pitch_rate"]["wc"]
    assert abs(sched["pitch_att"]["pm_deg"] - const["pitch_att"]["pm_deg"]) > 1.0


def test_midpoint_validation_points():
    ps = PointSet([
        OperatingPoint(case=_case(0.4), role=ROLE_ANCHOR, origin="coarse"),
        OperatingPoint(case=_case(0.6), role=ROLE_BREAKPOINT, origin="coarse"),
    ])
    mids = midpoint_validation_points(ps)
    assert len(mids) == 1
    assert mids[0].case.mach == pytest.approx(0.5)
    assert mids[0].role == "validation"
    ps.add(mids[0])
    # 검증점 밀도 기본값 = breakpoint 구간당 중점 1개 — 검증점은 새 구간을 만들지
    # 않으므로(인접 정의가 breakpoint 이상) 재생성해도 추가분이 없다 (멱등)
    assert midpoint_validation_points(ps) == []
    # 검증점을 breakpoint로 승격하면 구간이 쪼개져 새 중점 2개가 나온다
    ps.promote(mids[0].case.name, ROLE_BREAKPOINT, reason="valley")
    more = sorted(p.case.mach for p in midpoint_validation_points(ps))
    assert more == pytest.approx([0.45, 0.55])


def test_margin_map_end_to_end_and_cancel(setup):
    ac, tables, design = setup
    ps = PointSet([
        OperatingPoint(case=_case(m), role=ROLE_ANCHOR, origin="coarse")
        for m in (0.4, 0.6)
    ])
    for mid in midpoint_validation_points(ps):
        ps.add(mid)
    lms = LinearModelSet()
    crit = MarginCriteria()
    trims = {}
    out = scheduled_margin_map(
        ac, ps, lms, tables, design, criteria=crit, trims=trims,
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035,
    )
    assert out["aborted"] is None
    assert set(out["cases"]) == set(ps.names())
    assert set(trims) == set(ps.names())  # 호출자 dict가 제자리 갱신된다
    v = out["cases"]["M0.5_h1000_f200"]
    assert v["role"] == "validation"
    assert "pitch_rate" in v["loops"] and "status" in v["loops"]["pitch_rate"]
    assert out["criteria_fingerprint"] == crit.fingerprint()
    # 협조적 취소 — 첫 마진 계산 후 중단해도 완료분은 남는다
    cancelled = scheduled_margin_map(
        ac, ps, lms, tables, design, criteria=crit, trims=dict(trims),
        on_progress=lambda done, total, msg: msg.startswith("margin"),
    )
    assert cancelled["aborted"] == "cancelled"
    assert len(cancelled["cases"]) == 1


def test_rate_wc_is_measured_on_the_prior_closed_plant(setup):
    """레이트 ωc는 **앞서 닫은 레이트까지 접은 플랜트**에서 잰 값이어야 한다.

    이 자리의 조성이 곧 "튜닝과 검증이 같은 자로 잰다"는 전제다: 튜너는 자세 PI의
    목표 교차를 이 ωc로 정하므로(tune._tune_att의 wc0 = wc/wc_ratio_att), 한쪽만 생
    모델로 재면 같은 형상의 설계 기준과 검증 기준이 갈린다.

    정확 일치(==)로 잰다. 생 플랜트와의 차이는 데모 게인에서 상대 3e-6~4e-4뿐이라
    (요 댐퍼 0.8이 롤 루프를 조금만 옮긴다) 어떤 approx 톨러런스로도 안 잡힌다 —
    실제로 이 자리의 플랜트를 생 모델로 되돌리는 뮤테이션이 전체 스위트를 통과했다.
    반대로 정상 경로는 같은 함수를 같은 행렬에 부르므로 비트 일치라 취약하지 않다.
    """
    ac, tables, design = setup
    spec = AXIS_SPECS["lat"]
    idx = 1  # 롤 = 두 번째 (요를 먼저 닫는다 — 유일하게 prior가 비지 않는 자리)
    group, x_rate, u_in = spec["rates"][idx]
    act = dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2)
    for mach in (0.3, 0.6, 0.8):
        case = _case(mach)
        lm = linearize(ac, trim_level(ac, case))
        reported = scheduled_margin_point(lm, tables, design, case, **act)["roll_rate"]["wc"]
        _lon, lat = split_axes(lm)
        eff = scheduled_gains(tables, design, case)
        prior = {f"{g}.k_rate": eff[f"{g}.k_rate"] for g, _, _ in spec["rates"][:idx]}
        assert prior, "prior가 비면 두 플랜트가 같아져 이 테스트가 항진이 된다"
        k = eff[f"{group}.k_rate"]
        on_prior = rate_loop_crossover(
            close_rates(lat, prior), group, x_rate, u_in, k, **act)
        on_raw = rate_loop_crossover(lat, group, x_rate, u_in, k, **act)
        assert reported == on_prior, f"M{mach}: 보고 ωc가 prior-닫은 플랜트 값이 아니다"
        assert reported != on_raw, f"M{mach}: 두 플랜트가 같은 값을 내 판별력이 없다"


def test_outside_envelope_point_is_measured_but_not_prescribed(setup):
    """포화·α 여유 미달 점 — 마진은 내되 실패 목록·판정 수에서 뺀다.

    이 점은 TUNE이 이미 건너뛴다(tune_points: trimmable is False → skipped). 스케줄이
    덮으라고 요구받은 적 없는 조건인데 채점만 하면, 나오는 처방이 **반영해도 듣지
    않는다** — 앵커로 승격해도 TUNE이 또 건너뛰어 게인 샘플이 하나도 안 는다.
    미수렴 점(loops 자체가 빔)과는 다른 상태라 따로 구분해 낸다.
    """
    ac, tables, design = setup
    ps = PointSet([
        OperatingPoint(case=_case(m), role=ROLE_ANCHOR, origin="coarse")
        for m in (0.4, 0.6)
    ])
    # 한 점을 엔벨로프 밖으로 표시 — 격자·리파인이 포화/α 여유로 세우는 플래그와 같다
    ps.get(case_name(0.4, 1000.0, 200.0)).trimmable = False
    out = scheduled_margin_map(
        ac, ps, LinearModelSet(), tables, design, criteria=MarginCriteria(), trims={},
        actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035,
    )
    marked = out["cases"][case_name(0.4, 1000.0, 200.0)]
    other = out["cases"][case_name(0.6, 1000.0, 200.0)]
    assert marked["outside_envelope"] is True
    assert marked["loops"], "마진 수치까지 없애면 왜 경계인지 볼 자료가 사라진다"
    assert "outside_envelope" not in other
    assert all(f["case"] != case_name(0.4, 1000.0, 200.0) for f in out["failures"])

    # 판정 수도 빠져야 한다 — 안 그러면 격자가 전부 엔벨로프 밖인 실행이
    # judged>0·failures=0으로 converged가 된다 (vacuous pass 가드가 막으려던 형태)
    from claw.design import AutoDesignConfig, DesignSession

    s = DesignSession(AutoDesignConfig(mode="auto"))
    s.margin_out = out
    assert s.outside_envelope_count() == 1
    marked_judged = sum(1 for m in marked["loops"].values()
                        if m.get("status") in ("ok", "warn", "fail"))
    assert marked_judged > 0, "이 점이 애초에 판정을 안 냈다면 배제를 재는 테스트가 아니다"
    all_judged = sum(
        1 for e in out["cases"].values() for m in e["loops"].values()
        if m.get("status") in ("ok", "warn", "fail")
    )
    assert s.judged_count() == all_judged - marked_judged


def test_sign_flip_fails_even_with_healthy_margin(setup):
    """실효 게인 부호가 설계와 반대면 마진이 좋아 보여도 fail.

    oriented_margins가 PM>0 방향을 골라 주기 때문에, 부호가 뒤집힌 게인도 화면에는
    멀쩡한 PM으로 뜬다 — 실제 기체에서는 양의 되먹임이다.
    """
    ac, tables, design = setup
    case = _case(0.6)
    tr = trim_level(ac, case)
    lm = linearize(ac, tr)
    flipped = {
        "pitch.kp": Table({"mach": (0.2, 0.9)},
                          (-design["pitch.kp"],) * 2, extrapolate="clip"),
    }
    out = scheduled_margin_point(lm, flipped, design, case, criteria=MarginCriteria())
    entry = out["pitch_att"]
    assert entry["status"] == "fail"
    assert entry["sign_flip"] == ["pitch.kp"]
    assert "부호" in entry["note"]
    # 부호가 맞으면 그대로 통과 — 검사가 무조건 fail을 내는 것이 아니다
    ok = scheduled_margin_point(lm, {}, design, case, criteria=MarginCriteria())
    assert "sign_flip" not in ok["pitch_att"]


def test_failures_are_ordered_worst_first_across_slot_kinds():
    """실패 목록은 **부족 비율이 큰 것부터**다 — 이 순서가 곧 분류기의 작업 목록.

    자리 종류가 섞이므로(마진 자리는 PM·GM, 감쇠 자리는 ζ) 절대 단위로는 한 줄에
    못 세운다. 종전 축(PM은 도 그대로, ζ는 ×90)은 ×90 환산이 감쇠 부족을 과대평가해
    **순서를 뒤집었다**: PM 35°가 축에서 35.0, ζ 0.28이 25.2라 6.7% 모자란 감쇠가
    22% 모자란 위상여유보다 앞에 섰다. 여기서는 둘 다 요구선 대비 비율로 잰다.

    잴 지표가 없는 실패(전 지표 nan)는 +inf라 맨 앞이다 — "얼마나 나쁜지 모른다"를
    맨 뒤로 보내면 예산이 끊길 때 가장 안 보이는 자리가 조용히 남는다.
    """
    from claw.design.schedmap import _worst_failures

    cases = {
        "shallow_zeta": {"loops": {"yaw_rate": {  # 0.30 대비 6.7% 부족 (옛 축 25.2)
            "kind": "damping", "zeta": 0.28, "status": "fail"}}},
        "deep_pm": {"loops": {"pitch_att": {  # 45 대비 22% 부족 (옛 축 35.0)
            "kind": "margin", "pm_deg": 35.0, "gm_db": 12.0, "status": "fail"}}},
        "worst_pm": {"loops": {"roll_att": {
            "kind": "margin", "pm_deg": 10.0, "gm_db": 12.0, "status": "fail"}}},
        "unmeasurable": {"loops": {"roll_att": {
            "kind": "margin", "pm_deg": float("nan"), "gm_db": float("nan"),
            "status": "fail"}}},
        # 엔벨로프 밖은 목록에 아예 안 든다 (처방이 듣지 않는 점)
        "outside": {"outside_envelope": True, "loops": {"pitch_att": {
            "kind": "margin", "pm_deg": 1.0, "gm_db": 1.0, "status": "fail"}}},
    }
    out = _worst_failures(cases, MarginCriteria())
    assert [f["case"] for f in out] == [
        "unmeasurable", "worst_pm", "deep_pm", "shallow_zeta"]
    # 부족량 레코드를 함께 실어 분류기·원장이 다시 계산하지 않게 한다
    deep = next(f for f in out if f["case"] == "deep_pm")
    assert deep["shortfall"]["pm_deg"]["required"] == 45.0
    assert deep["shortfall"]["pm_deg"]["deficit"] == pytest.approx(10.0)


def test_roll_rate_is_judged_against_its_target(setup):
    """roll_rate가 더 이상 상수 "ok"가 아니다 — λ를 그 실행의 튜닝 목표와 견준다.

    종전에는 entry에 target조차 없이 status="ok"를 박았다. 그래서 롤 댐퍼가 목표
    대역폭을 얼마나 놓치든 검증을 통과했고, 이 자리는 **절대 실패할 수 없는 판정**을
    하나 보태 judged 수를 부풀렸다. λ는 안정성 마진이 아니라 성능 지표라 관례적
    절대 합격선이 없으므로 목표 대비 비율로 잰다 (criteria.lam_min_frac/lam_good_frac).
    """
    from claw.design import TuneTargets

    ac, tables, design = setup
    case = _case(0.6)
    lm = linearize(ac, trim_level(ac, case))
    crit, tg = MarginCriteria(), TuneTargets()

    good = scheduled_margin_point(lm, tables, design, case, criteria=crit, targets=tg)
    rr = good["roll_rate"]
    assert rr["target"] == tg.roll_lambda, "무엇과 견줬는지가 결과에 남아야 한다"
    assert rr["status"] in ("ok", "warn", "fail")

    # 롤 댐퍼를 아예 끄면 λ가 무너진다 — 종전이라면 그래도 "ok"였다
    off = dict(tables)
    off["roll.k_rate"] = Table({"mach": (0.2, 0.9)}, (0.0, 0.0), extrapolate="clip")
    bad = scheduled_margin_point(lm, off, design, case, criteria=crit, targets=tg)
    assert bad["roll_rate"]["roll_lambda"] < rr["roll_lambda"]
    assert bad["roll_rate"]["participation"] > crit.lam_part_min, (
        "참여도가 낮으면 na가 맞다 — 이 테스트는 fail을 재려는 것이라 전제가 다르다")
    assert bad["roll_rate"]["status"] == "fail", (
        f"롤 대역폭이 무너졌는데 통과했다 — {bad['roll_rate']}")

    # 댐퍼가 어중간하게 약하면 롤 모드가 더치롤·나선과 합쳐져 **실근으로 존재하지
    # 않는다**. 남은 실근의 |Re|를 롤 대역폭이라 부르면 조용한 오답이다 — na여야 한다
    faint = dict(tables)
    faint["roll.k_rate"] = Table({"mach": (0.2, 0.9)},
                                 (design["roll.k_rate"] * 0.2,) * 2, extrapolate="clip")
    amb = scheduled_margin_point(lm, faint, design, case, criteria=crit, targets=tg)
    assert amb["roll_rate"]["participation"] < crit.lam_part_min
    assert amb["roll_rate"]["status"] == "na", (
        f"롤 모드가 아닌 근을 롤 대역폭으로 판정했다 — {amb['roll_rate']}")


def test_roll_lambda_carries_the_sign_it_would_otherwise_erase():
    """λ = max|Re|는 부호를 지운다 — 발산근 +12가 "목표 12 달성"으로 보인다.

    튜너 쪽은 댐퍼 안정 캡이 걸러 주지만 검증 쪽에는 그 게이트가 없다. 지표가
    부호를 함께 내지 않으면 발산하는 롤 모드가 성능 달성으로 기록된다.
    """
    from claw.design.closure import lat_metrics

    # 대각 행렬이라 모드 k = 상태 k. lat 상태 순서는 (v, p, r, phi)이므로 p는 1번
    stable = np.diag([-0.5, -12.0, -3.0, -0.02])
    m = lat_metrics(stable, wn_floor=0.1)
    assert m["roll_lambda"] == pytest.approx(12.0) and m["roll_unstable"] is False
    assert m["roll_participation"] == pytest.approx(1.0)

    diverging = np.diag([-0.5, +12.0, -3.0, -0.02])  # 크기는 같고 부호만 반대
    m2 = lat_metrics(diverging, wn_floor=0.1)
    assert m2["roll_lambda"] == pytest.approx(12.0), "크기는 그대로 나온다"
    assert m2["roll_unstable"] is True, "부호가 지워졌다 — 발산근이 달성으로 보인다"
    assert MarginCriteria().judge_bandwidth(12.0, 12.0, unstable=True) == "fail"


def test_roll_mode_is_picked_by_participation_not_by_speed():
    """"실근 중 가장 빠른 것"은 롤 모드가 아니다 — 롤 상태를 담은 근을 지목한다.

    데모 M0.6/h1000 실측: 요 댐퍼가 만든 실근이 −6.45 rad/s라, 롤 게인을 설계값의
    0.2배로 줄여도 max|Re|는 6.58에서 안 내려가고 **0으로 완전히 꺼도 6.45**다.
    재려는 게인에 거의 반응하지 않는 지표였다.
    """
    from claw.design.closure import lat_metrics, roll_real_mode

    # p(1번)에 느린 근, 다른 상태에 빠른 근 — max|Re|는 −9를 집는다
    A = np.diag([-9.0, -2.0, -4.0, -0.01])
    lam, part = roll_real_mode(A, p_index=1)
    assert lam.real == pytest.approx(-2.0), "롤과 무관한 빠른 근을 집었다"
    assert part == pytest.approx(1.0)
    assert lat_metrics(A, wn_floor=0.1)["roll_lambda"] == pytest.approx(2.0)
    assert max(abs(v) for v in (-9.0, -2.0, -4.0, -0.01)) == 9.0  # 종전 축의 답
