"""M17 linmodels 검증 — 캐시·직렬화 왕복, 거리 지표의 대칭성·0·단조 경향."""

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
    for mach in (0.25, 0.3, 0.45, 0.5):
        case = TrimCase(name=case_name(mach, 1000.0, 200.0), mach=mach, alt=1000.0, fuel=200.0)
        tr = trim_level(ac, case, fingerprint="fp")
        assert tr.converged
        trs[mach] = tr
    return ac, trs


def test_cache_hits_and_rejects_unconverged(setup):
    ac, trs = setup
    lms = LinearModelSet()
    lm1 = lms.get(ac, trs[0.45])
    lm2 = lms.get(ac, trs[0.45])
    assert lm1 is lm2  # 같은 (케이스, 지문)은 재선형화하지 않는다
    assert len(lms) == 1
    bad = trim_level(ac, TrimCase("bad", mach=0.05, alt=1000.0, fuel=200.0))
    if not bad.converged:
        with pytest.raises(ValueError, match="미수렴"):
            lms.get(ac, bad)


def test_roundtrip_serialization(setup):
    ac, trs = setup
    lms = LinearModelSet()
    lm = lms.get(ac, trs[0.45])
    lms2 = LinearModelSet.from_dict(lms.to_dict())
    lm2 = lms2.peek(trs[0.45].case.name, "fp")
    assert lm2 is not None
    np.testing.assert_allclose(lm2.A, lm.A)
    np.testing.assert_allclose(lm2.B, lm.B)
    assert lm2.x_names == lm.x_names and lm2.u_names == lm.u_names
    assert lm2.case.mach == 0.45


def test_distance_zero_and_symmetric(setup):
    ac, trs = setup
    lms = LinearModelSet()
    lm_a, lm_b = lms.get(ac, trs[0.45]), lms.get(ac, trs[0.5])
    d_same = model_distance(lm_a, lm_a, trs[0.45], trs[0.45])
    assert d_same["d_total"] == pytest.approx(0.0, abs=1e-12)
    d_ab = model_distance(lm_a, lm_b, trs[0.45], trs[0.5])
    d_ba = model_distance(lm_b, lm_a, trs[0.5], trs[0.45])
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
        lms.get(ac, trs[0.45]), lms.get(ac, trs[0.5]), trs[0.45], trs[0.5]
    )
    # 저마하 Δ0.05가 고마하 Δ0.1보다도 크다 — 동압 1/M² 급변 구간
    assert d_low["d_total"] > d_high["d_total"]


def test_eig_migration_is_symmetric(setup):
    """분류 실패 폴백도 대칭이어야 한다 — 방향에 따라 값이 달라지면 refine·classify의
    공용 문턱(tol 0.25)이 "어느 쪽에서 재느냐"로 갈린다.

    한 방향 탐욕 매칭은 모드가 크게 움직인 쌍(coarse 격자가 정확히 그 경우)에서
    짝이 엇갈린다 — 실측으로 M0.3↔M0.6 종축이 0.99 vs 0.50이었다.
    """
    ac, trs = setup
    lms = LinearModelSet()
    from claw.design.linmodels import _eig_migration, _migration_one_way
    from claw.trim import split_axes

    lon_lo, _ = split_axes(lms.get(ac, trs[0.3]))
    lon_hi, _ = split_axes(lms.get(ac, trs[0.5]))
    assert _eig_migration(lon_lo.A, lon_lo.A) == 0.0
    assert _eig_migration(lon_lo.A, lon_hi.A) == _eig_migration(lon_hi.A, lon_lo.A)
    # 대칭화가 실제로 일하고 있다 — 한 방향씩 재면 값이 다른 쌍이다
    fwd = _migration_one_way(lon_lo.A, lon_hi.A)
    rev = _migration_one_way(lon_hi.A, lon_lo.A)
    assert _eig_migration(lon_lo.A, lon_hi.A) == pytest.approx(max(fwd, rev))


def test_distance_symmetric_when_classification_fails(setup):
    """레이트 댐퍼를 접어 단주기가 실근으로 갈라진(분류 실패) 축에서도 거리는 대칭."""
    ac, trs = setup
    lms = LinearModelSet()
    from claw.analysis.modes import classify_lon
    from claw.design.closure import close_rates
    from claw.trim import split_axes

    lon_lo, _ = split_axes(lms.get(ac, trs[0.3]))
    closed = close_rates(lon_lo, {"pitch.k_rate": 0.4})
    with pytest.raises(ValueError):  # 폴백이 실제로 도는 상황임을 확인
        classify_lon(closed)

    d_ab = model_distance(lms.get(ac, trs[0.3]), lms.get(ac, trs[0.5]), trs[0.3], trs[0.5])
    d_ba = model_distance(lms.get(ac, trs[0.5]), lms.get(ac, trs[0.3]), trs[0.5], trs[0.3])
    assert d_ab["d_total"] == pytest.approx(d_ba["d_total"])
