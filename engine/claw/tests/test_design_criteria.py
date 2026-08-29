"""M17 criteria 검증 — 판정 경계, nan/inf 취급, 지문·직렬화."""

import pytest

from claw.design import MarginCriteria


def test_judge_boundaries():
    c = MarginCriteria()  # PM 45/30°, GM 6/10 dB
    assert c.judge({"pm_deg": 60.0, "gm_db": 12.0}) == "ok"
    assert c.judge({"pm_deg": 45.0, "gm_db": 10.0}) == "ok"  # 경계 포함
    assert c.judge({"pm_deg": 60.0, "gm_db": 8.0}) == "warn"  # 합격이되 얇은 여유
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


def test_roundtrip_and_fingerprint():
    c = MarginCriteria(pm_min_deg=50.0)
    c2 = MarginCriteria.from_dict(c.to_dict())
    assert c2 == c
    assert c.fingerprint() == c2.fingerprint()
    assert c.fingerprint() != MarginCriteria().fingerprint()
