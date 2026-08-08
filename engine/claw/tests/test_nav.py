"""M6 nav 등가 오차 모델 검증 — 무오차 패스스루, 지연, 갱신주기, 잡음 통계, 바이어스 상관."""

import numpy as np
import pytest

from claw.common.attitude import euler_to_quat
from claw.common.contracts import VehicleState
from claw.nav import NavErrorModel
from claw.params.registry import REGISTRY

DT = 0.01


def clean_model(**over):
    """모든 오차원을 끈 기본 모델 — 개별 테스트가 필요한 항만 켠다."""
    kw = dict(
        pos_std=0.0, vel_std=0.0, att_std=0.0, psi_std=0.0, rate_std=0.0,
        bias_std=0.0, bias_tau=60.0, delay_s=0.0, update_hz=100.0, seed=0,
    )
    kw.update(over)
    return NavErrorModel(**kw)


def truth_at(t):
    return VehicleState(
        t=t,
        pos_n=np.array([100.0 * t, -20.0 * t, -500.0]),
        vel_b=np.array([100.0, -20.0, 0.0]),
        q_nb=euler_to_quat(0.05, 0.1, 0.3),
        omega_b=np.array([0.01, -0.02, 0.03]),
    )


def test_zero_error_passthrough():
    nav = clean_model().init(DT)
    for k in range(10):
        out = nav.step(truth_at(k * DT))
    s = truth_at(9 * DT)
    assert out.valid
    assert out.t == pytest.approx(s.t)
    assert out.t_meas == pytest.approx(s.t)
    assert out.pos_n == pytest.approx(s.pos_n, abs=1e-12)
    assert out.vel_n == pytest.approx(s.vel_n(), abs=1e-12)
    assert out.q_nb == pytest.approx(s.q_nb, abs=1e-12)
    assert out.omega_b == pytest.approx(s.omega_b, abs=1e-12)


def test_fuel_passthrough():
    """연료 게이지 참값 통과 — 오차 모델 대상 아님 (게인 스케줄 변수 소비처)."""
    nav = clean_model().init(DT)
    s = truth_at(0.0)
    s.fuel = 123.5
    assert nav.step(s).fuel == 123.5


def test_delay_shifts_measurement():
    nav = clean_model(delay_s=0.05).init(DT)
    outs = [nav.step(truth_at(k * DT)) for k in range(12)]
    assert not outs[0].valid  # 첫 측정이 아직 릴리스되지 않음
    assert outs[4].valid is False
    assert outs[5].valid  # t=0.05에서 t_meas=0 측정 릴리스
    assert outs[5].t_meas == pytest.approx(0.0)
    assert outs[5].pos_n == pytest.approx(truth_at(0.0).pos_n, abs=1e-12)
    assert outs[11].t_meas == pytest.approx(0.06)  # t=0.11 − 0.05


def test_update_rate_hold():
    """25 Hz 항법 / 100 Hz 틱 → 출력은 4틱마다 갱신 (멀티레이트 홀드)."""
    nav = clean_model(update_hz=25.0).init(DT)
    outs = [nav.step(truth_at(k * DT)) for k in range(12)]
    for k in range(12):
        expected_meas_t = (k // 4) * 4 * DT
        assert outs[k].t_meas == pytest.approx(expected_meas_t)
    assert outs[3].pos_n == pytest.approx(outs[0].pos_n, abs=1e-15)  # 홀드 구간 동일
    assert not np.allclose(outs[4].pos_n, outs[3].pos_n)  # 갱신 시점에 변화


def test_seed_reproducibility():
    a = clean_model(pos_std=2.0, seed=7).init(DT)
    b = clean_model(pos_std=2.0, seed=7).init(DT)
    c = clean_model(pos_std=2.0, seed=8).init(DT)
    pa = [a.step(truth_at(k * DT)).pos_n.copy() for k in range(20)]
    pb = [b.step(truth_at(k * DT)).pos_n.copy() for k in range(20)]
    pc = [c.step(truth_at(k * DT)).pos_n.copy() for k in range(20)]
    assert np.allclose(pa, pb)
    assert not np.allclose(pa, pc)


def test_white_noise_statistics():
    sigma = 2.0
    nav = clean_model(pos_std=sigma, seed=1).init(DT)
    errs = np.array([nav.step(truth_at(k * DT)).pos_n - truth_at(k * DT).pos_n for k in range(20000)])
    assert np.mean(errs) == pytest.approx(0.0, abs=0.05)
    assert np.std(errs) == pytest.approx(sigma, rel=0.05)


def test_markov_bias_correlation():
    """1차 마르코프 바이어스: 측정 간 lag-1 자기상관 ≈ exp(-T_up/tau)."""
    tau = 1.0
    nav = clean_model(bias_std=1.0, bias_tau=tau, seed=2).init(DT)
    b = np.array([(nav.step(truth_at(k * DT)).pos_n - truth_at(k * DT).pos_n)[0] for k in range(20000)])
    p_expected = np.exp(-DT / tau)
    r1 = np.corrcoef(b[:-1], b[1:])[0, 1]
    assert r1 == pytest.approx(p_expected, abs=0.01)
    assert np.std(b) == pytest.approx(1.0, rel=0.2)  # 정상상태 표준편차 = bias_std (상관 표본이라 느슨)


def test_attitude_noise_keeps_unit_quaternion():
    nav = clean_model(att_std=0.01, psi_std=0.02, seed=3).init(DT)
    for k in range(50):
        out = nav.step(truth_at(k * DT))
        assert np.linalg.norm(out.q_nb) == pytest.approx(1.0, abs=1e-12)
    assert not np.allclose(out.q_nb, truth_at(49 * DT).q_nb)


def test_noninteger_update_ratio_rejected():
    """틱 주기의 비정수배 갱신주기는 조용한 양자화 대신 명시적 오류 (40 Hz / 100 Hz 틱)."""
    with pytest.raises(ValueError):
        clean_model(update_hz=40.0).init(DT)
    fast = clean_model(update_hz=1000.0).init(DT)  # 틱보다 빠른 항법 → 틱 주기로 상한
    assert fast._n_up == 1


def test_released_output_is_isolated():
    """소비자가 출력 배열을 훼손해도 내부 보관 측정치는 오염되지 않는다."""
    nav = clean_model(update_hz=25.0).init(DT)
    out0 = nav.step(truth_at(0.0))
    out0.pos_n[:] = 999.0
    out1 = nav.step(truth_at(DT))  # 같은 측정의 홀드 출력
    assert not np.allclose(out1.pos_n, 999.0)


def test_registered_as_component():
    """항법 모델은 교체 가능 컴포넌트 — 추후 실제 EKF 코드로 교체 (02 §3.1 인터페이스 개방)."""
    assert "ErrorModel" in REGISTRY.names("nav")
    nav = REGISTRY.create("nav", "ErrorModel", {"pos_std": 1.0, "delay_s": 0.0}).init(DT)
    out = nav.step(truth_at(0.0))
    assert out.valid
