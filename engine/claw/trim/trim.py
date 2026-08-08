"""M9 trim — 수평정상비행 구속 트림 (scipy SLSQP) + 배치 (01 §4.1, MATLAB trim 대체).

미지수 z = [α, δe(collective), throttle(양 엔진 공통)] — 대칭 가정 (β=φ=δa=δr=0).
상태 구성: θ = α (수평비행 γ=0 → ḣ=0 자동), 잔차 = (u̇, ẇ, q̇).
배치는 인접 케이스 시드(직전 수렴해를 초기값으로) [기본값] — 초기값 민감성 대응 (01 §4.1).

자동 판정 플래그 (01 §4.1 [기본값], TrimResult.flags):
- residual_ok    : |u̇|,|ẇ| < RESID_TOL, |q̇| < RESID_TOL
- saturation_ok  : δe·스로틀이 한계의 SAT_FRAC 이내 (스로틀 하한 여유 THR_MARGIN 포함)
- alpha_margin_ok: α가 상한 대비 ALPHA_MARGIN 이상 여유 (실속 경계 [TBD] 확보 전 대용)
- continuity_ok  : 배치에서 인접 케이스 해와의 급변 없음. **None = 미판정**
  (첫 케이스·비교 기준 부재) — 미판정을 합격으로 오인하지 않도록 3-상태
"""

import numpy as np
from scipy.optimize import minimize

from claw.common.attitude import euler_to_quat
from claw.common.contracts import SurfaceCommand, TrimResult, VehicleState
from claw.env import isa_atmosphere
from claw.plant.aircraft import XE_H, XE_Q, XE_THETA, XE_U, XE_W

ALPHA_BOUNDS = (-0.10, 0.35)  # [rad]
DE_BOUNDS = (-0.35, 0.35)  # [rad]
THR_BOUNDS = (0.0, 1.0)
RESID_TOL = 1e-4  # [m/s², rad/s²]
SAT_FRAC = 0.95
THR_MARGIN = 0.02  # 스로틀 하한 여유 — 아이들 포화 해 검출
ALPHA_MARGIN = 0.035  # [rad] ≈ 2° — 실속 경계 테이블 확보 전 대용 [기본값]
CONTINUITY_STEP = np.array([0.05, 0.05, 0.15])  # 인접 케이스 허용 Δ[α, δe, thr]

_Z0_DEFAULT = np.array([0.05, 0.0, 0.3])


def _controls(z):
    return {"de": float(z[1]), "da": 0.0, "dr": 0.0, "throttle": (float(z[2]), float(z[2]))}


def _xe(z, v_true, alt):
    xe = np.zeros(12)
    xe[XE_U] = v_true * np.cos(z[0])
    xe[XE_W] = v_true * np.sin(z[0])
    xe[XE_THETA] = z[0]  # θ = α → γ = 0
    xe[XE_H] = alt
    return xe


def trim_level(aircraft, case, z0=None, fingerprint=""):
    atm = isa_atmosphere(case.alt)
    v_true = case.mach * atm.a

    def resid(z):
        xd = aircraft.deriv_euler(_xe(z, v_true, case.alt), _controls(z), case.fuel)
        return np.array([xd[XE_U], xd[XE_W], xd[XE_Q]])

    def cost(z):
        return float(np.sum(resid(z) ** 2))

    res = minimize(
        cost,
        _Z0_DEFAULT if z0 is None else np.asarray(z0, dtype=float),
        method="SLSQP",
        bounds=[ALPHA_BOUNDS, DE_BOUNDS, THR_BOUNDS],
        options={"maxiter": 300, "ftol": 1e-16},
    )
    alpha, de, thr = res.x
    r = resid(res.x)

    residual_ok = bool(np.all(np.abs(r) < RESID_TOL))
    saturation_ok = bool(
        abs(de) < SAT_FRAC * DE_BOUNDS[1]
        and THR_BOUNDS[0] + THR_MARGIN < thr < SAT_FRAC * THR_BOUNDS[1]
    )
    alpha_margin_ok = bool(alpha < ALPHA_BOUNDS[1] - ALPHA_MARGIN)
    flags = {
        "residual_ok": residual_ok,
        "saturation_ok": saturation_ok,
        "alpha_margin_ok": alpha_margin_ok,
        "continuity_ok": None,  # 미판정 — 배치(trim_batch)가 비교 기준 확보 시 판정
    }
    state = VehicleState(
        t=0.0,
        pos_n=np.array([0.0, 0.0, -case.alt]),
        vel_b=np.array([v_true * np.cos(alpha), 0.0, v_true * np.sin(alpha)]),
        q_nb=euler_to_quat(0.0, alpha, 0.0),
        omega_b=np.zeros(3),
        fuel=case.fuel,
    )
    control = SurfaceCommand(
        elevon=np.full(4, de), rudder=0.0, throttle=np.array([thr, thr])
    )
    return TrimResult(
        case=case,
        state=state,
        control=control,
        converged=bool(res.success) and residual_ok,
        cost=float(res.fun),
        flags=flags,
        params_fingerprint=fingerprint,
    )


def trim_batch(aircraft, cases, fingerprint="", on_progress=None):
    """케이스 목록 순서대로 트림 — 직전 수렴해를 다음 초기값으로 시드, 연속성 판정 포함.

    on_progress(done, total, tr): 케이스마다 호출 (M13 서버 진행률 경로).
    truthy 반환 = 협조적 취소 — 지금까지의 부분 결과를 반환한다.
    """
    results = []
    z_prev = None
    for case in cases:
        tr = trim_level(aircraft, case, z0=z_prev, fingerprint=fingerprint)
        z = np.array([tr.state.euler()[1], tr.control.elevon[0], tr.control.throttle[0]])
        if z_prev is not None:
            tr.flags["continuity_ok"] = bool(np.all(np.abs(z - z_prev) < CONTINUITY_STEP))
        if tr.converged:
            z_prev = z
        results.append(tr)
        if on_progress is not None and on_progress(len(results), len(cases), tr):
            break
    return results
