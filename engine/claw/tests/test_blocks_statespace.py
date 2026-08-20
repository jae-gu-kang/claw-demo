"""M2 blocks 검증 — StateSpace/TransferFunction(ZOH)·IIRFilter·MovingAverage (Phase 1 백로그 소진).

교차검증 전략: 이미 해석해 대조를 마친 Lag·Integrator와 표본점 기계정밀도 일치를 요구
(둘 다 직달항 없는 ZOH-정확 이산화 + 동일 샘플 규약이므로 허용오차가 필요 없다).
"""

import math

import numpy as np
import pytest

from claw.blocks import IIRFilter, Integrator, Lag, MovingAverage, StateSpace, TransferFunction

DT = 0.01


# ---- StateSpace ----


def test_statespace_pure_integrator_matches_integrator_block():
    ss = StateSpace(A=[[0.0]], B=[[1.0]], C=[[1.0]]).init(DT)
    integ = Integrator(ki=1.0, method="forward").init(DT)
    for k in range(50):
        u = math.sin(0.1 * k)
        assert ss.step(u) == pytest.approx(integ.step(u), abs=1e-15)


def test_statespace_direct_feedthrough():
    ss = StateSpace(A=[[-1.0]], B=[[0.0]], C=[[0.0]], D=[[2.5]]).init(DT)
    assert ss.step(3.0) == pytest.approx(7.5)  # 상태 무관 y = D·u


def test_statespace_mimo_shapes():
    # 독립 적분기 2개 (2입력 2출력)
    ss = StateSpace(A=np.zeros((2, 2)), B=np.eye(2), C=np.eye(2)).init(0.1)
    y = ss.step([1.0, 2.0])
    assert y.shape == (2,) and np.allclose(y, [0.0, 0.0])
    y = ss.step([1.0, 2.0])
    assert np.allclose(y, [0.1, 0.2])


def test_statespace_rediscretize_on_new_dt():
    ss = StateSpace(A=[[0.0]], B=[[1.0]], C=[[1.0]]).init(0.01)
    for _ in range(10):
        y100 = ss.step(1.0)
    ss.init(0.02)  # 50 Hz 재이산화 — 상태도 초기화
    for _ in range(5):
        y50 = ss.step(1.0)
    assert y100 == pytest.approx(0.09)  # 9·0.01 (forward: 첫 스텝 0)
    assert y50 == pytest.approx(0.08)  # 4·0.02


def test_statespace_shape_validation():
    with pytest.raises(ValueError):
        StateSpace(A=[[0.0, 1.0]], B=[[1.0]], C=[[1.0]])  # A 비정방
    with pytest.raises(ValueError):
        StateSpace(A=[[0.0]], B=[[1.0], [0.0]], C=[[1.0]])  # B 행 불일치
    with pytest.raises(ValueError):
        StateSpace(A=[[0.0]], B=[[1.0]], C=[[1.0]], D=[[1.0], [0.0]])  # D 형상


def test_statespace_warm_start_validation():
    ss = StateSpace(A=np.zeros((2, 2)), B=np.eye(2), C=np.eye(2)).init(DT)
    ss.reset([1.0, 2.0])
    assert np.allclose(ss.step([0.0, 0.0]), [1.0, 2.0])
    with pytest.raises(ValueError):
        ss.reset([1.0])  # 길이 불일치


# ---- TransferFunction ----


def test_transfer_function_matches_lag_exactly():
    tau = 0.7
    tf = TransferFunction(num=[1.0], den=[tau, 1.0]).init(DT)
    lag = Lag(tau=tau).init(DT)
    for k in range(100):
        u = math.sin(0.05 * k) + 0.5
        assert tf.step(u) == pytest.approx(lag.step(u), abs=1e-12)


def test_transfer_function_dc_gain():
    tf = TransferFunction(num=[3.0], den=[0.2, 1.0]).init(DT)
    y = 0.0
    for _ in range(3000):
        y = tf.step(2.0)
    assert y == pytest.approx(6.0, rel=1e-6)  # DC 이득 3


def test_transfer_function_rejects_improper():
    with pytest.raises(ValueError):
        TransferFunction(num=[1.0, 0.0, 0.0], den=[1.0, 1.0])  # 미분기 — 비프로퍼


# ---- IIRFilter ----


def test_iir_fir_moving_average_equivalence():
    fir = IIRFilter(b=(0.25, 0.25, 0.25, 0.25)).init(DT)
    ma = MovingAverage(n=4).init(DT)
    for u in [1.0, 2.0, -3.0, 4.0, 5.0, 0.5]:
        assert fir.step(u) == pytest.approx(ma.step(u), abs=1e-15)


def test_iir_first_order_difference_equation():
    # y[k] = 0.5·y[k-1] + 0.5·u[k] — 상수 입력 1에 대해 1로 수렴
    f = IIRFilter(b=(0.5,), a=(1.0, -0.5)).init(DT)
    y = 0.0
    for _ in range(100):
        y = f.step(1.0)
    assert y == pytest.approx(1.0, rel=1e-9)


def test_iir_normalizes_by_a0():
    f1 = IIRFilter(b=(1.0,), a=(2.0,)).init(DT)  # 이득 0.5로 정규화
    assert f1.step(4.0) == pytest.approx(2.0)


def test_iir_pure_gain_order_zero():
    f = IIRFilter(b=(3.0,), a=(1.0,)).init(DT)
    assert f.step(2.0) == pytest.approx(6.0)


def test_iir_validation_and_warm_start():
    with pytest.raises(ValueError):
        IIRFilter(b=(), a=(1.0,))
    with pytest.raises(ValueError):
        IIRFilter(b=(1.0,), a=(0.0, 1.0))  # a[0] = 0
    f = IIRFilter(b=(0.5, 0.5), a=(1.0, -0.5)).init(DT)
    with pytest.raises(ValueError):
        f.reset([1.0, 2.0])  # 차수 1 → 상태 길이 1


# ---- MovingAverage ----


def test_moving_average_window():
    ma = MovingAverage(n=4).init(DT)
    outs = [ma.step(u) for u in [4.0, 4.0, 4.0, 4.0, 8.0]]
    assert outs[3] == pytest.approx(4.0)  # 윈도우 가득 — 평균 4
    assert outs[4] == pytest.approx(5.0)  # (4+4+4+8)/4


def test_moving_average_validation():
    with pytest.raises(ValueError):
        MovingAverage(n=0)
    with pytest.raises(ValueError):
        MovingAverage(n=2.5)
    ma = MovingAverage(n=3).init(DT)
    with pytest.raises(ValueError):
        ma.reset([1.0])  # 웜스타트 버퍼 길이 불일치
