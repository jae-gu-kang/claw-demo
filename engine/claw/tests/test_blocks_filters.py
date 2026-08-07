"""M2 필터·PID 검증 — 1차 필터는 ZOH-정확 해석해 대조(abs 1e-12), 노치는 주파수영역 검증."""

import cmath
import math

import pytest

from claw.blocks import PID, Lag, LeadLag, LowPass, Notch, Washout

DT = 0.01


# ---- Lag / LowPass: ZOH-정확 이산화 → 스텝응답이 표본점에서 해석해와 기계정밀도 일치 ----


@pytest.mark.parametrize("dt", [0.01, 0.02])  # 100 vs 50 Hz — 둘 다 해석해와 정확 일치
def test_lag_step_exact(dt):
    tau = 0.1
    lag = Lag(tau).init(dt)
    outs = [lag.step(1.0) for _ in range(30)]
    for k, y in enumerate(outs):
        assert y == pytest.approx(1.0 - math.exp(-k * dt / tau), abs=1e-12)


def test_lowpass_equals_lag():
    fc = 3.0
    lp = LowPass(fc).init(DT)
    lag = Lag(1.0 / (2.0 * math.pi * fc)).init(DT)
    seq = [0.5, 1.0, -0.2, 0.0, 2.0, 1.0]
    assert [lp.step(u) for u in seq] == pytest.approx([lag.step(u) for u in seq], abs=1e-15)


def test_lag_invalid_tau():
    with pytest.raises(ValueError):
        Lag(0.0)


# ---- Washout ----


def test_washout_step_exact():
    tau = 0.2
    wo = Washout(tau).init(DT)
    outs = [wo.step(1.0) for _ in range(50)]
    assert outs[0] == pytest.approx(1.0, abs=1e-15)  # 초기값 정확히 1
    for k, y in enumerate(outs):
        assert y == pytest.approx(math.exp(-k * DT / tau), abs=1e-12)


def test_washout_ramp_steady_state():
    """램프 a·t 입력의 이산 정상상태 = a·dt/(1-p) → dt→0 극한에서 a·tau."""
    tau, a = 0.5, 2.0
    wo = Washout(tau).init(DT)
    for k in range(3000):
        y = wo.step(a * k * DT)
    p = math.exp(-DT / tau)
    assert y == pytest.approx(a * DT / (1.0 - p), abs=1e-9)


# ---- LeadLag ----


@pytest.mark.parametrize("t1, t2", [(0.2, 0.05), (0.05, 0.2)])  # 리드 / 래그 양쪽
def test_leadlag_step_exact(t1, t2):
    c = t1 / t2
    ll = LeadLag(t1, t2).init(DT)
    outs = [ll.step(1.0) for _ in range(60)]
    assert outs[0] == pytest.approx(c, abs=1e-12)  # 초기값 t1/t2
    for k, y in enumerate(outs):
        assert y == pytest.approx(1.0 + (c - 1.0) * math.exp(-k * DT / t2), abs=1e-11)


# ---- Notch: 주파수영역 정본 검증 (다항식 평가 — 시뮬 불요) ----


def _freq_response(nt, f_hz):
    z = cmath.exp(1j * 2.0 * math.pi * f_hz * nt.dt)
    b0, b1, b2 = nt.b
    a1, a2 = nt.a
    return (b0 + b1 / z + b2 / z**2) / (1.0 + a1 / z + a2 / z**2)


def test_notch_frequency_response():
    f0 = 5.0
    nt = Notch(f0=f0, q=2.0).init(DT)
    assert abs(_freq_response(nt, f0)) < 1e-12  # 중심주파수 완전 차단 (프리워핑 정확)
    assert abs(_freq_response(nt, 1e-9)) == pytest.approx(1.0, abs=1e-6)  # DC 이득 1
    assert abs(_freq_response(nt, 45.0)) == pytest.approx(1.0, abs=0.1)  # 고주파 통과


def test_notch_time_domain():
    f0 = 5.0
    nt = Notch(f0=f0, q=2.0).init(DT)
    outs = [nt.step(math.sin(2.0 * math.pi * f0 * k * DT)) for k in range(600)]
    assert max(abs(y) for y in outs[-100:]) < 0.05  # f0 정현파 감쇠
    nt.reset()
    outs = [nt.step(math.sin(2.0 * math.pi * (f0 / 4) * k * DT)) for k in range(600)]
    assert max(abs(y) for y in outs[-100:]) > 0.9  # f0/4 통과
    nt.reset()
    outs = [nt.step(1.0) for _ in range(800)]
    assert outs[-1] == pytest.approx(1.0, abs=1e-6)  # DC 스텝 정착


def test_notch_nyquist_guard():
    with pytest.raises(ValueError):
        Notch(f0=60.0, q=2.0).init(DT)  # 60 Hz >= 나이퀴스트(50 Hz)


# ---- PID ----


def test_pid_p_only_and_override():
    pid = PID(kp=1.5).init(DT)
    assert pid.step(2.0) == pytest.approx(3.0)
    assert pid.step(2.0, kp=3.0) == pytest.approx(6.0)  # 게인 스케줄 덮어쓰기


def test_pid_pi_exact_sequence():
    kp, ki, e = 2.0, 3.0, 0.5
    pid = PID(kp=kp, ki=ki).init(DT)
    for k in range(10):
        y = pid.step(e)
        assert y == pytest.approx(kp * e + ki * e * k * DT, abs=1e-12)


def test_pid_derivative_kick():
    pid = PID(kp=0.0, ki=0.0, kd=1.0).init(DT)
    assert pid.step(1.0) == pytest.approx(1.0 / DT)
    assert pid.step(1.0) == pytest.approx(0.0)


def test_pid_antiwindup():
    pid = PID(kp=1.0, ki=1.0, out_lo=-1.0, out_hi=1.0).init(0.1)
    for _ in range(30):
        y = pid.step(1.0)
    assert y == pytest.approx(1.0)  # 출력 포화
    assert pid.step(-1.0) == pytest.approx(0.0)  # 반전 즉시 이탈 (I가 1로 클램프되어 있음)


def test_pid_reset_warm_start():
    pid = PID(kp=0.0, ki=1.0).init(DT)
    pid.reset(0.7)  # 적분기 웜스타트 (범프리스 전환 계약)
    assert pid.step(0.0) == pytest.approx(0.7)
