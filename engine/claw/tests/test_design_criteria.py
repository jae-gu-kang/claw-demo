"""M17 criteria 검증 — 판정 경계, nan/inf 취급, 지문·직렬화, 튜닝 목표와의 정합."""

import math

import pytest

from claw.common.contracts import TrimCase
from claw.design import MarginCriteria, tune_point
from claw.fcl.demo import demo_design_gains
from claw.plant import make_demo_aircraft
from claw.trim import linearize, trim_level


def test_judge_boundaries():
    c = MarginCriteria()  # PM 45/30°, GM 6(합격)/8(목표) dB
    assert c.judge({"pm_deg": 60.0, "gm_db": 12.0}) == "ok"
    assert c.judge({"pm_deg": 45.0, "gm_db": 8.0}) == "ok"  # 경계 포함
    assert c.judge({"pm_deg": 60.0, "gm_db": 7.0}) == "warn"  # 합격이되 목표 미달
    assert c.judge({"pm_deg": 44.9, "gm_db": 12.0}) == "fail"
    assert c.judge({"pm_deg": 60.0, "gm_db": 5.9}) == "fail"
    assert c.judge({"pm_deg": 20.0, "gm_db": 3.0}) == "fail"


def test_judge_nan_is_na_not_fail():
    """판정 불가(nan)를 fail로 뭉개면 분류기가 엉뚱한 처방을 낸다."""
    c = MarginCriteria()
    assert c.judge({"pm_deg": float("nan"), "gm_db": 12.0}) == "na"
    assert c.judge({"pm_deg": 60.0, "gm_db": float("nan")}) == "na"


def test_judge_inf_passes():
    c = MarginCriteria()
    assert c.judge({"pm_deg": 60.0, "gm_db": float("inf")}) == "ok"


def test_shortfall_reports_requirement_not_just_achieved():
    c = MarginCriteria()
    sf = c.shortfall({"pm_deg": 40.0, "gm_db": 4.0})
    assert sf["pm_deg"] == {"required": 45.0, "achieved": 40.0,
                            "deficit": pytest.approx(5.0),
                            "deficit_frac": pytest.approx(5.0 / 45.0),
                            # PM에는 목표선이 없다 — judge()가 PM으로 warn을 안 낸다
                            "goal": None, "deficit_goal": None}
    assert sf["gm_db"]["deficit_frac"] == pytest.approx(2.0 / 6.0)
    # GM에는 목표선이 있다. warn은 "합격선은 넘겼으나 목표선 미달"이므로, 부족을
    # 합격선으로만 재면 warn 행이 **자기가 넘긴 선에 대한 여유**를 보여 주고 정작
    # 못 넘긴 선은 이름조차 안 나온다 (실측: "GM 요구 6 dB · 달성 7.22 · 여유 1.22"가
    # "미달 원장" 표에 떴다)
    assert sf["gm_db"]["goal"] == 8.0
    assert sf["gm_db"]["deficit_goal"] == pytest.approx(4.0)
    warn = c.shortfall({"pm_deg": 60.0, "gm_db": 7.22})["gm_db"]
    assert warn["deficit"] < 0 and warn["deficit_goal"] > 0, (
        "합격선은 넘고 목표선은 못 넘긴 자리가 두 수로 구분돼야 한다")
    # 여유는 음수 부족 — 통과한 자리도 "얼마나 여유인지"가 같은 필드로 나온다
    assert c.shortfall({"pm_deg": 60.0, "gm_db": 12.0})["pm_deg"]["deficit"] < 0


def test_shortfall_nan_is_none_not_zero():
    """교차 없음(nan)을 부족 0으로 두면 "판정 불가"가 "부족 없음"과 같아진다.

    종전 deficit()이 그랬다: `pm - self.pm_min_deg if isfinite else 0.0`. 그러면
    분류기의 히스테리시스 판정에서 nan 자리가 조용히 "밴드 안"으로 들어가 확대
    경고가 안 붙고, 원장에는 부족 0인 실패로 실린다.
    """
    c = MarginCriteria()
    rec = c.shortfall({"pm_deg": float("nan"), "gm_db": 4.0})["pm_deg"]
    assert rec["deficit"] is None and rec["deficit_frac"] is None
    assert rec["achieved"] is None and rec["required"] == 45.0


def test_shortfall_picks_metrics_from_entry_shape():
    """자리 종류마다 담는 키가 다르다 — 없는 지표를 지어내지 않는다."""
    c = MarginCriteria()
    assert set(c.shortfall({"kind": "margin", "pm_deg": 40.0, "gm_db": 4.0})) == {
        "pm_deg", "gm_db"}
    # 감쇠 자리는 이름이 셋 (schedmap "zeta", tune achieved "zeta_sp"/"zeta_dr")
    assert set(c.shortfall({"kind": "damping", "zeta": 0.2})) == {"zeta"}
    assert c.shortfall({"zeta_dr": 0.15})["zeta_dr"]["required"] == 0.30
    # λ만 요구선이 그 실행의 튜닝 목표에서 온다 — target이 없으면 지표를 안 낸다
    assert c.shortfall({"kind": "bandwidth", "roll_lambda": 3.0}) == {}
    lam = c.shortfall({"kind": "bandwidth", "roll_lambda": 3.0, "target": 12.0})
    assert lam["roll_lambda"]["required"] == pytest.approx(6.0)  # 12 × lam_min_frac
    assert lam["roll_lambda"]["deficit"] == pytest.approx(3.0)


def test_severity_orders_by_shortage_fraction_not_absolute_units():
    """자리 종류가 섞인 목록을 한 축에서 세운다 — 이 정렬이 곧 분류기의 작업 순서다.

    종전 축(PM은 도 그대로, ζ는 ×90)은 ×90 환산이 감쇠 부족을 과대평가해 **순서를
    뒤집었다**: PM 35°는 축에서 35.0, ζ 0.28은 25.2라 감쇠가 더 심각하게 섰다.
    실제로는 PM이 요구선의 22%를, 감쇠는 6.7%를 모자란다.
    """
    c = MarginCriteria()
    pm = c.severity({"kind": "margin", "pm_deg": 35.0, "gm_db": 12.0})
    zeta = c.severity({"kind": "damping", "zeta": 0.28})
    assert pm > zeta, "부족이 훨씬 큰 위상여유가 뒤로 밀렸다 — 절대 축으로 되돌아갔다"
    assert pm == pytest.approx(10.0 / 45.0)  # 크기도 실제 부족 비율이다
    assert zeta == pytest.approx(0.02 / 0.30)
    # 종전 축이 앞세우던 순서 (이 값들이 옛 정렬 키다 — 25.2 < 35.0이라 ζ가 먼저였다)
    assert 0.28 * 90.0 < 35.0
    # 잴 지표가 하나도 없으면 +inf — "얼마나 나쁜지 모른다"가 목록 맨 앞이다
    assert c.severity({"kind": "margin", "pm_deg": float("nan"),
                       "gm_db": float("nan")}) == float("inf")
    assert c.severity({"kind": "bandwidth", "roll_lambda": 1.0}) == float("inf")


def test_judge_bandwidth_uses_target_and_rejects_divergent_root():
    """λ는 목표 대비 비율로 재고, 발산근이면 수치와 무관하게 fail.

    closure.lat_metrics의 λ = max|Re|는 부호를 지운다 — 발산근 +12 rad/s가 "목표 12
    달성"으로 보인다. 튜너는 댐퍼 안정 캡이 거르지만 검증에는 그 게이트가 없어서
    이 인자가 유일한 방어다.
    """
    c = MarginCriteria()  # lam_min_frac 0.5, lam_good_frac 0.8
    assert c.judge_bandwidth(12.0, 12.0) == "ok"
    assert c.judge_bandwidth(7.0, 12.0) == "warn"
    assert c.judge_bandwidth(5.9, 12.0) == "fail"
    # 경계 포함(≥가 통과)은 곱이 정확히 표현되는 목표에서 잰다 — 0.8×12는 부동소수로
    # 9.600000000000001이라 9.6이 경계 아래로 떨어진다. 판정선이 절대 상수가 아니라
    # 곱이라 생기는 성질이고, 실제로도 목표 근처 1e-15는 구분할 일이 아니다
    assert c.judge_bandwidth(8.0, 10.0) == "ok"  # 0.8×10 = 8.0 정확
    assert c.judge_bandwidth(5.0, 10.0) == "warn"  # 0.5×10 = 5.0 정확 (합격선 포함)
    assert c.judge_bandwidth(12.0, 12.0, unstable=True) == "fail"
    assert c.judge_bandwidth(float("nan"), 12.0) == "na"
    assert c.judge_bandwidth(12.0, 0.0) == "na"  # 목표가 없으면 잴 자가 없다


def test_lam_fracs_ordering_rejected():
    with pytest.raises(ValueError):
        MarginCriteria(lam_min_frac=0.9, lam_good_frac=0.5)
    with pytest.raises(ValueError):
        MarginCriteria(lam_good_frac=1.5)


def test_invalid_ordering_rejected():
    with pytest.raises(ValueError):
        MarginCriteria(pm_min_deg=30.0, pm_bad_deg=45.0)
    with pytest.raises(ValueError):
        MarginCriteria(gm_min_db=12.0, gm_good_db=6.0)


def test_tuned_point_judges_ok_not_warn():
    """튜닝이 성공한 점은 판정에서 ok여야 한다 — warn이 의미를 갖기 위한 불변식.

    warn의 뜻은 "합격선은 넘겼으나 설계 목표에 못 미친다"이다. 그런데 판정선
    (MarginCriteria)과 튜닝 목표(TuneTargets)는 서로를 모른 채 각자 기본값을 들고
    있어서 조용히 어긋난다 — 실제로 gm_good_db 10 dB > TuneTargets.gm_db 8 dB로
    어긋나 있던 동안 **자유 게인 최적점조차 warn**이었고, 화면이 의미 없는 경고로
    뒤덮여 사용자가 진짜 문제를 골라낼 수 없었다.

    설정 정합은 AutoDesignConfig가 부등식으로 막지만(test_design_orchestrator),
    그 부등식이 **실제 달성 수치**에서 의도한 결과를 내는지는 여기서 잰다 —
    부등식만 있으면 판정 함수 쪽 규약이 바뀌어도 걸리지 않는다.
    """
    ac = make_demo_aircraft()
    design = demo_design_gains()
    tr = trim_level(ac, TrimCase("t", mach=0.6, alt=1000.0, fuel=200.0), fingerprint="fp")
    assert tr.converged
    out = tune_point(linearize(ac, tr), design, actuator_wn=30.0, actuator_zeta=0.7,
                     delay_s=0.035, pade_order=2)
    assert out["status"] == "ok"
    c = MarginCriteria()
    for axis in ("pitch", "roll"):
        ach = out["achieved"][f"{axis}_att"]
        assert c.judge(ach) == "ok", f"{axis}_att 튜닝 성공점이 ok가 아니다 — {ach}"
    # 감쇠 자리도 같은 자로 — 목표 달성(ζ_sp 0.7 / ζ_dr 0.5)이 곧 ok여야 한다
    assert c.judge_damping(out["achieved"]["pitch_rate"]["zeta_sp"]) == "ok"
    assert c.judge_damping(out["achieved"]["yaw_rate"]["zeta_dr"]) == "ok"


def test_roundtrip_and_fingerprint():
    c = MarginCriteria(pm_min_deg=50.0)
    c2 = MarginCriteria.from_dict(c.to_dict())
    assert c2 == c
    assert c.fingerprint() == c2.fingerprint()
    assert c.fingerprint() != MarginCriteria().fingerprint()


def test_zero_requirement_does_not_divide():
    """요구선 0은 서버 입력으로 **도달 가능한** 값이다 — 나누면 잡 스레드가 죽는다.

    `config: {"criteria": {"gm_min_db": 0}}`가 라우트를 통과하던 동안, 첫 VERIFY의
    `_worst_failures`가 실패마다 shortfall을 불러 ZeroDivisionError로 잡이 죽었다 —
    "202를 받았는데 사유 없이 실패"하는 형태다. 이제 두 겹으로 막는다: 설정 시점의
    양수 검사와, 그래도 0이 들어왔을 때 판정 불가로 흘리는 것.
    """
    with pytest.raises(ValueError):
        MarginCriteria(gm_min_db=0.0)
    with pytest.raises(ValueError):
        MarginCriteria(pm_min_deg=0.0, pm_bad_deg=0.0)
    # 생성자를 우회해 들어온 경우에도 나누지 않는다 — 검증은 __post_init__에만 있고
    # 세션 역직렬화·직접 구성 같은 경로가 그것을 지나치지 않는다는 보장이 없다
    bad = object.__new__(MarginCriteria)
    object.__setattr__(bad, "pm_min_deg", 45.0)
    object.__setattr__(bad, "gm_min_db", 0.0)
    for f in ("pm_bad_deg", "gm_good_db", "zeta_min", "zeta_good",
              "lam_min_frac", "lam_good_frac", "lam_part_min"):
        object.__setattr__(bad, f, getattr(MarginCriteria(), f))
    rec = bad.shortfall({"pm_deg": 50.0, "gm_db": 4.0})["gm_db"]
    assert rec["deficit"] is None and rec["deficit_frac"] is None
    assert bad.severity({"pm_deg": 50.0, "gm_db": 4.0}) == pytest.approx(-5.0 / 45.0)


def test_divergent_root_beats_the_participation_gate():
    """발산근은 참여도보다 **먼저** 본다 — 순서가 바뀌면 발산극이 조용히 빠진다.

    참여도가 낮으면 "롤 대역폭을 못 쟀다"(na)가 맞지만, 그 근이 **발산근**이면
    얘기가 다르다. na는 실패 목록에도 판정 수에도 안 들어가고, ζ_dr은 진동쌍만
    보므로 그 발산극은 어디서도 보고되지 않는다. "못 쟀다"가 "발산극을 잠자코
    넘긴다"의 이유가 될 수는 없다 — 검증 쪽에는 댐퍼 안정 캡이 없어 이 인자가
    유일한 방어다.
    """
    c = MarginCriteria()  # lam_part_min 0.5
    # 이 커밋 계열이 고친 **바로 그 조합** — 참여도 낮음 ∧ 발산근
    assert c.judge_bandwidth(6.45, 12.0, unstable=True, participation=0.08) == "fail"
    # 발산이 아니면 같은 참여도가 na다 (게이트 자체는 살아 있다)
    assert c.judge_bandwidth(6.45, 12.0, unstable=False, participation=0.08) == "na"
    # 참여도가 높으면 종전대로
    assert c.judge_bandwidth(6.45, 12.0, unstable=True, participation=0.99) == "fail"
    assert c.judge_bandwidth(11.0, 12.0, unstable=False, participation=0.99) == "ok"


def test_unidentifiable_roll_mode_is_nan_not_zero():
    """롤 모드를 실근으로 지목 못 하면 λ는 0.0이 아니라 nan이다.

    0.0을 내면 판정이 "목표의 0배 → fail"로 흐르고 부족 비율 1.0(양수 지표의
    **최대**)이라 실패 목록 맨 앞에 선다 — 재지도 못한 값으로 이터 예산을 태운다.
    nan은 judge_bandwidth가 na로 받는다.
    """
    import numpy as np

    from claw.design.closure import lat_metrics

    # 실근이 하나도 없는 횡축 (전부 복소쌍) — 롤 모드가 더치롤·나선과 합쳐진 상태
    A = np.array([[0.0, -2.0, 0.0, 0.0],
                  [2.0, 0.0, 0.0, 0.0],
                  [0.0, 0.0, 0.0, -3.0],
                  [0.0, 0.0, 3.0, 0.0]])
    m = lat_metrics(A, wn_floor=0.1)
    assert math.isnan(m["roll_lambda"]), "못 잰 λ가 0으로 나가 fail이 된다"
    assert m["roll_participation"] is None
    assert MarginCriteria().judge_bandwidth(m["roll_lambda"], 12.0) == "na"
