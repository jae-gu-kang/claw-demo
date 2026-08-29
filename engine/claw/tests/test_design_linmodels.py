"""M16 linmodels 검증 — 캐시·직렬화 왕복, 거리 지표의 대칭성·0·단조 경향."""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.design import LinearModelSet, model_distance, case_name
from claw.plant import make_demo_aircraft
from claw.trim import trim_level


@pytest.fixture(scope="module")
def setup():
    ac = make_demo_aircraft()
    trs = {}
    for mach in (0.25, 0.3, 0.6, 0.7):
        case = TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach, alt=1000.0, fuel=200.0)
        tr = trim_level(ac, case, fingerprint="fp")
        assert tr.converged
        trs[mach] = tr
    return ac, trs


def test_cache_hits_and_rejects_unconverged(setup):
    ac, trs = setup
    lms = LinearModelSet()
    lm1 = lms.get(ac, trs[0.6])
    lm2 = lms.get(ac, trs[0.6])
    assert lm1 is lm2  # 같은 (케이스, 지문)은 재선형화하지 않는다
    assert len(lms) == 1
    bad = trim_level(ac, TrimCase("bad", mach=0.05, alt=1000.0, fuel=200.0))
    if not bad.converged:
        with pytest.raises(ValueError, match="미수렴"):
            lms.get(ac, bad)


def test_roundtrip_serialization(setup):
    ac, trs = setup
    lms = LinearModelSet()
    lm = lms.get(ac, trs[0.6])
    lms2 = LinearModelSet.from_dict(lms.to_dict())
    lm2 = lms2.peek(trs[0.6].case.name, "fp")
    assert lm2 is not None
    np.testing.assert_allclose(lm2.A, lm.A)
    np.testing.assert_allclose(lm2.B, lm.B)
    assert lm2.x_names == lm.x_names and lm2.u_names == lm.u_names
    assert lm2.case.mach == 0.6


def test_distance_zero_and_symmetric(setup):
    ac, trs = setup
    lms = LinearModelSet()
    lm_a, lm_b = lms.get(ac, trs[0.6]), lms.get(ac, trs[0.7])
    d_same = model_distance(lm_a, lm_a, trs[0.6], trs[0.6])
    assert d_same["d_total"] == pytest.approx(0.0, abs=1e-12)
    d_ab = model_distance(lm_a, lm_b, trs[0.6], trs[0.7])
    d_ba = model_distance(lm_b, lm_a, trs[0.7], trs[0.6])
    assert d_ab["d_total"] == pytest.approx(d_ba["d_total"], rel=1e-9)
    assert d_ab["d_total"] > 0.0
    assert d_ab["d_total"] == pytest.approx(
        max(d_ab["d_trim"], d_ab["d_mode"], d_ab["d_ctrl"])
    )


def test_distance_larger_at_low_mach(setup):
    """동압 역비 스케일의 원인 — 저마하 인접쌍이 고마하 인접쌍보다 플랜트 변화가 크다.

    같은 Δmach=0.05·0.1 격자에서 리파인이 저마하 구간에 몰리는 근거가 이 단조 경향이다.
    """
    ac, trs = setup
    lms = LinearModelSet()
    d_low = model_distance(
        lms.get(ac, trs[0.25]), lms.get(ac, trs[0.3]), trs[0.25], trs[0.3]
    )
    d_high = model_distance(
        lms.get(ac, trs[0.6]), lms.get(ac, trs[0.7]), trs[0.6], trs[0.7]
    )
    # 저마하 Δ0.05가 고마하 Δ0.1보다도 크다 — 동압 1/M² 급변 구간
    assert d_low["d_total"] > d_high["d_total"]
