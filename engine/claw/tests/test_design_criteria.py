"""M17 criteria 검증 — 판정 경계, nan/inf 취급, 지문·직렬화, 튜닝 목표와의 정합."""

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


def test_deficit():
    c = MarginCriteria()
    d = c.deficit({"pm_deg": 40.0, "gm_db": 4.0})
    assert d["pm_deg"] == pytest.approx(5.0)
    assert d["gm_db"] == pytest.approx(2.0)
    d2 = c.deficit({"pm_deg": 60.0, "gm_db": float("inf")})
    assert d2["pm_deg"] < 0 and d2["gm_db"] == 0.0


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
