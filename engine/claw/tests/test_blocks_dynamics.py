"""M2 dynamics 블록 검증 — Integrator(3방식·안티와인드업)/Derivative/RateLimiter 해석해 대조."""

import pytest

from claw.blocks import Derivative, Integrator, RateLimiter

DT = 0.01


# ---- Integrator: 상수 입력의 방식별 정확 수열 ----


@pytest.mark.parametrize(
    "method, offset",
    [("forward", 0.0), ("backward", 1.0), ("tustin", 0.5)],
)
def test_integrator_constant_input(method, offset):
    """u=c 상수 입력: y_k = ki·c·dt·(k + offset) — forward 0, backward 1, tustin 0.5."""
    ki, c = 2.0, 3.0
    itg = Integrator(ki=ki, method=method).init(DT)
    outs = [itg.step(c) for _ in range(6)]
    for k, y in enumerate(outs):
        assert y == pytest.approx(ki * c * DT * (k + offset), abs=1e-12)


def test_integrator_tustin_ramp_exact():
    """사다리꼴(tustin)은 1차 신호 적분이 정확: u=a·t → y(t_k) = a·t_k²/2."""
    a = 4.0
    itg = Integrator(method="tustin").init(DT)
    for k in range(100):
        y = itg.step(a * k * DT)
    assert y == pytest.approx(a * (99 * DT) ** 2 / 2, rel=1e-12)


@pytest.mark.parametrize(
    "method, after_reversal",
    [("forward", [1.0, 0.9]), ("backward", [0.9, 0.8]), ("tustin", [1.0, 0.9])],
)
def test_integrator_antiwindup_clamp(method, after_reversal):
    """포화 도달 후 입력 반전 시 와인드업 지연 없이 이탈 (클램프 방식)."""
    itg = Integrator(ki=1.0, hi=1.0, method=method).init(0.1)
    for _ in range(50):
        y = itg.step(1.0)
    assert y == pytest.approx(1.0)
    outs = [itg.step(-1.0), itg.step(-1.0)]
    assert outs == pytest.approx(after_reversal, abs=1e-12)


def test_integrator_initial_and_reset():
    itg = Integrator(initial=5.0, method="backward").init(DT)
    assert itg.step(0.0) == pytest.approx(5.0)
    itg.reset(2.0)  # 웜스타트 (범프리스 전환 계약)
    assert itg.step(0.0) == pytest.approx(2.0)
    itg.reset()
    assert itg.step(0.0) == pytest.approx(5.0)


def test_integrator_invalid_args():
    with pytest.raises(ValueError):
        Integrator(lo=1.0, hi=-1.0)
    with pytest.raises(ValueError):
        Integrator(method="rk4")


# ---- Derivative ----


def test_derivative_step_impulse():
    kd = 2.0
    d = Derivative(kd=kd).init(DT)
    outs = [d.step(1.0), d.step(1.0), d.step(1.0)]
    assert outs[0] == pytest.approx(kd / DT)
    assert outs[1:] == [0.0, 0.0]


def test_derivative_ramp():
    a = 3.0
    d = Derivative().init(DT)
    outs = [d.step(a * k * DT) for k in range(5)]
    assert outs[0] == pytest.approx(0.0)
    for y in outs[1:]:
        assert y == pytest.approx(a, rel=1e-9)


# ---- RateLimiter ----


def test_rate_limiter_ramp_to_step():
    r = 2.0
    rl = RateLimiter(rate_up=r, rate_dn=r).init(DT)
    outs = [rl.step(1.0) for _ in range(60)]
    for k in range(50):  # 도달 전: 스텝당 정확히 r·dt 램프
        assert outs[k] == pytest.approx(r * DT * (k + 1), abs=1e-12)
    assert outs[49] == pytest.approx(1.0)
    assert outs[50] == pytest.approx(1.0)  # 도달 후 유지


def test_rate_limiter_asymmetric_down():
    rl = RateLimiter(rate_up=10.0, rate_dn=1.0, initial=1.0).init(DT)
    assert rl.step(-1.0) == pytest.approx(1.0 - 1.0 * DT)


def test_rate_limiter_passes_slow_input():
    rl = RateLimiter(rate_up=2.0, rate_dn=2.0).init(DT)
    for k in range(10):
        u = 0.001 * k
        assert rl.step(u) == pytest.approx(u, abs=1e-12)


# ---- 샘플레이트 파라미터화 (100 vs 50 Hz) ----


def test_integrator_tustin_rate_independent_for_linear_input():
    """u(t)=t를 1초 적분 — tustin은 dt와 무관하게 정확값 0.5."""
    for dt in (0.01, 0.02):
        n = round(1.0 / dt)
        itg = Integrator(method="tustin").init(dt)
        for k in range(n + 1):
            y = itg.step(k * dt)
        assert y == pytest.approx(0.5, rel=1e-12)


def test_reinit_with_new_dt_no_state_pollution():
    """같은 인스턴스를 다른 dt로 재-init하면 새 인스턴스와 동일하게 동작."""
    reused = Integrator(method="tustin").init(0.01)
    for _ in range(10):
        reused.step(1.0)
    reused.init(0.02)
    fresh = Integrator(method="tustin").init(0.02)
    seq = [0.5, -0.3, 1.2, 0.0]
    assert [reused.step(u) for u in seq] == [fresh.step(u) for u in seq]
