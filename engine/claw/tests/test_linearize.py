"""M9 linearize 검증 — 중력·운동학 해석 핀, 종/횡 분리·비결합, 소신호 비선형 일치 (verify 층2)."""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.plant import (
    XE_H,
    XE_P,
    XE_PHI,
    XE_Q,
    XE_THETA,
    XE_U,
    XE_W,
    make_demo_aircraft,
    rk4_step,
)
from claw.common.constants import G0
from claw.trim import LAT_INPUTS, LAT_STATES, LON_INPUTS, LON_STATES, linearize, split_axes, trim_level


@pytest.fixture(scope="module")
def setup():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("lin", mach=0.6, alt=1000.0, fuel=200.0), fingerprint="fp1")
    lm = linearize(ac, tr)
    return ac, tr, lm


def test_gravity_and_kinematic_pins(setup):
    """θ만 흔들면 중력 투영만 변함 → ∂u̇/∂θ = -g·cosθ0 등 해석값과 일치."""
    _, tr, lm = setup
    th0 = tr.state.euler()[1]
    A = lm.A
    assert A[XE_U, XE_THETA] == pytest.approx(-G0 * np.cos(th0), rel=1e-5)
    assert A[XE_W, XE_THETA] == pytest.approx(-G0 * np.sin(th0), rel=1e-3, abs=1e-6)
    assert A[XE_PHI, XE_P] == pytest.approx(1.0, rel=1e-9)  # φ̇ = p (+tanθ 항은 q,r 소관)
    # ḣ = u·sinθ − w·cosθ (φ=0) → ∂ḣ/∂w = −cosθ0, ∂ḣ/∂u = sinθ0
    assert A[XE_H, XE_W] == pytest.approx(-np.cos(th0), rel=1e-6)
    assert A[XE_H, XE_U] == pytest.approx(np.sin(th0), rel=1e-4)


def test_split_axes_and_decoupling(setup):
    """대칭 트림에서 종축↔횡축 비결합 — 교차 블록 ≈ 0."""
    _, tr, lm = setup
    lon, lat = split_axes(lm)
    assert lon.axis == "lon" and lat.axis == "lat"
    assert lon.x_names == LON_STATES and lon.u_names == LON_INPUTS
    assert lat.x_names == LAT_STATES and lat.u_names == LAT_INPUTS
    assert lon.A.shape == (4, 4) and lon.B.shape == (4, 2)
    assert lat.A.shape == (4, 4) and lat.B.shape == (4, 2)
    assert lon.case is tr.case and lon.params_fingerprint == "fp1"
    lon_idx = [XE_U, XE_W, XE_Q, XE_THETA]
    lat_idx = [1, XE_P, 5, XE_PHI]  # v, p, r, phi
    assert np.max(np.abs(lm.A[np.ix_(lat_idx, lon_idx)])) < 1e-6
    assert np.max(np.abs(lm.A[np.ix_(lon_idx, lat_idx)])) < 1e-6


def test_lon_modes_stable(setup):
    """데모 기체 종축: 단주기+장주기 두 복소쌍, 전부 안정."""
    _, _, lm = setup
    lon, _ = split_axes(lm)
    eigs = np.linalg.eigvals(lon.A)
    assert np.all(eigs.real < 0.0)
    assert np.sum(eigs.imag > 1e-6) == 2  # 복소쌍 2개 (켤레 제외)


def test_small_signal_match(setup):
    """미소섭동에서 비선형 응답과 선형모델 응답 일치 (구현 문서 §7 층2)."""
    ac, tr, lm = setup
    xe0 = np.zeros(12)
    xe0[XE_U], xe0[XE_W] = tr.state.vel_b[0], tr.state.vel_b[2]
    xe0[XE_THETA], xe0[XE_H] = tr.state.euler()[1], tr.case.alt
    de0, thr0 = tr.control.elevon[0], tr.control.throttle[0]
    d_de = 1e-3  # 엘레베이터 미소 스텝 [rad]

    dt, n = 0.01, 100
    x_nl = xe0.copy()
    f_nl = lambda x: ac.deriv_euler(  # noqa: E731
        x, {"de": de0 + d_de, "da": 0.0, "dr": 0.0, "throttle": (thr0, thr0)}, tr.case.fuel
    )
    dx_lin = np.zeros(12)
    du = np.array([d_de, 0.0, 0.0, 0.0])
    f_lin = lambda dx: lm.A @ dx + lm.B @ du  # noqa: E731
    for _ in range(n):
        x_nl = rk4_step(f_nl, x_nl, dt)
        dx_lin = rk4_step(f_lin, dx_lin, dt)
    err = np.abs((x_nl - xe0) - dx_lin)
    scale = np.max(np.abs(dx_lin))
    assert scale > 0
    assert np.max(err[[XE_U, XE_W, XE_Q, XE_THETA]]) < 0.02 * scale
