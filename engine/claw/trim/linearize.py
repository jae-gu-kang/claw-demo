"""수치섭동 선형화 (MATLAB linmod 대체, 01 §4.2) — 트림점 주변 중앙차분.

상태는 오일러 12-상태(XE_*, aircraft.py), 입력 u = (δe, δa, δr, thr[양엔진 공통]).
중앙차분 스텝은 상태 크기에 비례(하한 1e-5) — 잘림오차 O(ε²)와 반올림 균형.

종/횡축 분리 (01 §4.2 [확정]):
    lon: [u, w, q, θ] × [δe, thr] / lat: [v, p, r, φ] × [δa, δr]
각 LinearModel은 트림 케이스 메타와 params_fingerprint(계보)를 승계한다.
"""

import numpy as np

from claw.common.contracts import LinearModel
from claw.plant.aircraft import XE_NAMES

U_NAMES = ("de", "da", "dr", "thr")
LON_STATES = ("u", "w", "q", "theta")
LON_INPUTS = ("de", "thr")
LAT_STATES = ("v", "p", "r", "phi")
LAT_INPUTS = ("da", "dr")


def _controls(u):
    return {"de": float(u[0]), "da": float(u[1]), "dr": float(u[2]), "throttle": (float(u[3]), float(u[3]))}


def _trim_point(tr):
    xe0 = np.zeros(12)
    xe0[0] = tr.state.vel_b[0]
    xe0[1] = tr.state.vel_b[1]
    xe0[2] = tr.state.vel_b[2]
    xe0[3:6] = tr.state.omega_b
    phi, theta, psi = tr.state.euler()
    xe0[6:9] = (phi, theta, psi)
    xe0[11] = tr.case.alt
    u0 = np.array([tr.control.elevon[0], 0.0, tr.control.rudder, tr.control.throttle[0]])
    return xe0, u0


def linearize(aircraft, tr, eps_scale=1e-5):
    """TrimResult → 연속시간 전체축 LinearModel (A 12x12, B 12x4, C=I, D=0)."""
    xe0, u0 = _trim_point(tr)
    fuel = tr.case.fuel

    def f(xe, u):
        return aircraft.deriv_euler(xe, _controls(u), fuel)

    A = np.zeros((12, 12))
    for j in range(12):
        e = eps_scale * max(1.0, abs(xe0[j]))
        xp, xm = xe0.copy(), xe0.copy()
        xp[j] += e
        xm[j] -= e
        A[:, j] = (f(xp, u0) - f(xm, u0)) / (2.0 * e)
    B = np.zeros((12, 4))
    for j in range(4):
        e = eps_scale
        up, um = u0.copy(), u0.copy()
        up[j] += e
        um[j] -= e
        B[:, j] = (f(xe0, up) - f(xe0, um)) / (2.0 * e)

    return LinearModel(
        A=A,
        B=B,
        C=np.eye(12),
        D=np.zeros((12, 4)),
        x_names=XE_NAMES,
        u_names=U_NAMES,
        axis="full",
        dt=0.0,
        case=tr.case,
        params_fingerprint=tr.params_fingerprint,
    )


def _extract(lm, states, inputs, axis):
    xi = [lm.x_names.index(s) for s in states]
    ui = [lm.u_names.index(s) for s in inputs]
    return LinearModel(
        A=lm.A[np.ix_(xi, xi)],
        B=lm.B[np.ix_(xi, ui)],
        C=np.eye(len(xi)),
        D=np.zeros((len(xi), len(ui))),
        x_names=tuple(states),
        u_names=tuple(inputs),
        axis=axis,
        dt=lm.dt,
        case=lm.case,
        params_fingerprint=lm.params_fingerprint,
    )


def split_axes(lm):
    """전체축 모델 → (종축, 횡축) 부분모델 (01 §4.2 분리 해석)."""
    lon = _extract(lm, LON_STATES, LON_INPUTS, "lon")
    lat = _extract(lm, LAT_STATES, LAT_INPUTS, "lat")
    return lon, lat
