"""M5 aero 검증 — 무차원화·손계산 대조, 풍축 변환 헬퍼, Table 결합, 6DOF 조립 스모크."""

import numpy as np
import pytest

from claw.common.constants import G0
from claw.plant import OMEGA, QUAT, VEL, AeroModel, RigidBody, gravity_body, pack, wind_to_body_coeffs
from claw.common.attitude import euler_to_quat
from claw.tables import Table

S, CBAR, B = 1.2, 0.8, 2.4


def test_constant_coefficients_hand_calc():
    coef = lambda inp: {"CX": -0.02, "CY": 0.01, "CZ": -0.5, "Cl": 0.001, "Cm": -0.03, "Cn": 0.002}  # noqa: E731
    aero = AeroModel(S=S, cbar=CBAR, b=B, coef_fn=coef)
    rho, v = 1.0, 100.0
    F, M = aero.forces(rho=rho, vel_air_b=np.array([v, 0.0, 0.0]), omega_b=np.zeros(3))
    qbar = 0.5 * rho * v * v
    assert F == pytest.approx([qbar * S * -0.02, qbar * S * 0.01, qbar * S * -0.5])
    assert M == pytest.approx([qbar * S * B * 0.001, qbar * S * CBAR * -0.03, qbar * S * B * 0.002])


def test_zero_velocity_no_nan():
    aero = AeroModel(S=S, cbar=CBAR, b=B, coef_fn=lambda inp: {"CX": -1.0, "CY": 0, "CZ": -1.0, "Cl": 0, "Cm": 0, "Cn": 0})
    F, M = aero.forces(rho=1.2, vel_air_b=np.zeros(3), omega_b=np.array([1.0, 1.0, 1.0]))
    assert np.allclose(F, 0.0) and np.allclose(M, 0.0)


def test_nondimensional_inputs_passed():
    seen = {}

    def coef(inp):
        seen.update(inp)
        return {"CX": 0, "CY": 0, "CZ": 0, "Cl": 0, "Cm": 0, "Cn": 0}

    aero = AeroModel(S=S, cbar=CBAR, b=B, coef_fn=coef)
    v, p, q, r = 50.0, 0.2, -0.1, 0.3
    aero.forces(
        rho=1.0,
        vel_air_b=np.array([v, 0.0, 5.0]),
        omega_b=np.array([p, q, r]),
        controls={"de": 0.05},
        mach=0.4,
    )
    V = np.sqrt(v * v + 25.0)
    assert seen["alpha"] == pytest.approx(np.arctan2(5.0, v))
    assert seen["beta"] == pytest.approx(0.0)
    assert seen["phat"] == pytest.approx(p * B / (2 * V))
    assert seen["qhat"] == pytest.approx(q * CBAR / (2 * V))
    assert seen["rhat"] == pytest.approx(r * B / (2 * V))
    assert seen["mach"] == pytest.approx(0.4)
    assert seen["de"] == pytest.approx(0.05)


def test_wind_to_body_helper():
    # α=β=0: CX=-CD, CZ=-CL
    cx, cy, cz = wind_to_body_coeffs(CL=0.5, CD=0.05, alpha=0.0, beta=0.0)
    assert (cx, cy, cz) == pytest.approx((-0.05, 0.0, -0.5))
    # α=90°: 양력이 전방(+x), 항력이 하방(-z... CX=CL, CZ=-CD)
    cx, _, cz = wind_to_body_coeffs(CL=0.5, CD=0.05, alpha=np.pi / 2, beta=0.0)
    assert (cx, cz) == pytest.approx((0.5, -0.05), abs=1e-12)
    # 일반각 손계산: CX = CL·sinα − CD·cosα·cosβ
    a, b_ = 0.1, 0.05
    cx, cy, cz = wind_to_body_coeffs(CL=0.4, CD=0.06, alpha=a, beta=b_)
    assert cx == pytest.approx(0.4 * np.sin(a) - 0.06 * np.cos(a) * np.cos(b_))
    assert cy == pytest.approx(-0.06 * np.sin(b_))
    assert cz == pytest.approx(-0.4 * np.cos(a) - 0.06 * np.sin(a) * np.cos(b_))


def test_table_driven_pitch_moment():
    """Cm(α, δe) 선형 테이블 → 모멘트가 해석식 q̄·S·c̄·(Cmα·α + Cmδe·δe)와 일치."""
    cma, cmde = -1.5, -0.9
    alphas = np.linspace(-0.3, 0.3, 7)
    des = np.linspace(-0.4, 0.4, 5)
    aa, dd = np.meshgrid(alphas, des, indexing="ij")
    cm_table = Table({"alpha": alphas, "de": des}, cma * aa + cmde * dd)

    def coef(inp):
        return {"CX": 0, "CY": 0, "CZ": 0, "Cl": 0,
                "Cm": cm_table.interp(alpha=inp["alpha"], de=inp["de"]), "Cn": 0}

    aero = AeroModel(S=S, cbar=CBAR, b=B, coef_fn=coef)
    rho, u, w, de = 1.1, 80.0, 8.0, 0.1
    F, M = aero.forces(rho=rho, vel_air_b=np.array([u, 0.0, w]), omega_b=np.zeros(3), controls={"de": de})
    V2 = u * u + w * w
    alpha = np.arctan2(w, u)
    expected = 0.5 * rho * V2 * S * CBAR * (cma * alpha + cmde * de)
    assert M[1] == pytest.approx(expected, rel=1e-9)


def test_pitch_dynamics_smoke():
    """조립 스모크: 정적 안정(Cmα<0) + 피치 댐핑(Cmq<0) → 받음각 진동이 감쇠."""
    m, Jyy = 200.0, 300.0
    rb = RigidBody(mass=m, inertia=np.diag([100.0, Jyy, 300.0]))

    def coef(inp):
        cl = 4.0 * inp["alpha"]
        cd = 0.02 + 0.1 * cl * cl
        cx, cy, cz = wind_to_body_coeffs(cl, cd, inp["alpha"], inp["beta"])
        return {"CX": cx, "CY": cy, "CZ": cz, "Cl": 0.0,
                "Cm": -1.2 * inp["alpha"] - 8.0 * inp["qhat"], "Cn": 0.0}

    aero = AeroModel(S=S, cbar=CBAR, b=B, coef_fn=coef)

    def fm(x):
        Fa, Ma = aero.forces(rho=1.225, vel_air_b=x[VEL], omega_b=x[OMEGA])
        return Fa + gravity_body(x[QUAT], m), Ma

    x = pack(np.array([0.0, 0.0, -500.0]), np.array([60.0, 0.0, 3.0]),
             euler_to_quat(0.0, 0.05, 0.0), np.zeros(3))
    alphas = []
    for _ in range(2000):  # 4초, dt=2ms
        x = rb.step(x, fm, 0.002)
        alphas.append(np.arctan2(x[VEL][2], x[VEL][0]))
    a = np.array(alphas)
    assert np.all(np.isfinite(a))
    early = np.max(np.abs(a[:500] - np.mean(a[1500:])))
    late = np.max(np.abs(a[1500:] - np.mean(a[1500:])))
    assert late < 0.3 * early  # 단주기성 진동 감쇠


def test_aero_validation():
    with pytest.raises(ValueError):
        AeroModel(S=0.0, cbar=CBAR, b=B, coef_fn=lambda i: {})
