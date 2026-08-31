"""M9 trim — 구속 트림 (scipy SLSQP) + 배치 (01 §4.1, MATLAB trim 대체).

두 가지 조건을 푼다 — TrimCase.condition이 고른다 (dispatcher: trim):

- "level"  : 수평정상비행 (trim_level). 미지수 z = [α, δe, throttle], 잔차 (u̇, ẇ, q̇)
- "ground" : 지상 정지 평형 (trim_ground). 미지수 z = [h_cg, θ, φ], 잔차 = 6축 가속도

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
from claw.common.constants import G0
from claw.common.contracts import SurfaceCommand, TrimResult, VehicleState
from claw.env import isa_atmosphere
from claw.plant.aircraft import XE_H, XE_P, XE_PHI, XE_Q, XE_R, XE_THETA, XE_U, XE_V, XE_W

ALPHA_BOUNDS = (-0.10, 0.35)  # [rad]
DE_BOUNDS = (-0.35, 0.35)  # [rad]
THR_BOUNDS = (0.0, 1.0)
RESID_TOL = 1e-4  # [m/s², rad/s²]
SAT_FRAC = 0.95
THR_MARGIN = 0.02  # 스로틀 하한 여유 — 아이들 포화 해 검출
ALPHA_MARGIN = 0.035  # [rad] ≈ 2° — 실속 경계 테이블 확보 전 대용 [기본값]
CONTINUITY_STEP = np.array([0.05, 0.05, 0.15])  # 인접 케이스 허용 Δ[α, δe, thr]

_Z0_DEFAULT = np.array([0.05, 0.0, 0.3])


def _saturation_channels(de, thr) -> dict:
    """포화 채널별 판정 — saturation_ok의 부정과 동치인 세 갈래 (상수 단일 거처).

    throttle_high가 추진 한계의 대리 지표다 — 전용 추력 모델 [TBD] 확보 전까지
    수평비행 추력 부족은 스로틀 상한 포화로만 드러난다 (01 §2.6).
    """
    return {
        "de": bool(abs(de) >= SAT_FRAC * DE_BOUNDS[1]),
        "throttle_high": bool(thr >= SAT_FRAC * THR_BOUNDS[1]),
        "throttle_low": bool(thr <= THR_BOUNDS[0] + THR_MARGIN),
    }


def saturation_detail(tr) -> dict:
    """TrimResult → 포화 채널 상세 {"de", "throttle_high", "throttle_low"}.

    trim_level의 saturation_ok과 같은 식(_saturation_channels) — 어느 채널이
    걸렸는지는 설계 엔벨로프 스캔(제어 가능 영역 귀속)의 입력이 된다.
    """
    return _saturation_channels(float(tr.control.elevon[0]), float(tr.control.throttle[0]))


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
    saturation_ok = not any(_saturation_channels(de, thr).values())
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


GROUND_TILT_BOUNDS = (-0.5, 0.5)  # [rad] 지상 평형 탐색의 θ·φ 범위
GROUND_RESID_TOL = 1e-6  # [m/s², rad/s²] — 6축 전부에 적용


def trim_ground(aircraft, case, fingerprint=""):
    """지상 정지 평형 — 착륙장치 반력이 중력을 받는 자세·높이 (01 §3.3.1).

    trim_level과 **대칭**이다: 미지수 3개를 움직여 가속도를 0으로 만든다. 다만 무엇을
    움직이는지가 다르다 — 수평비행은 (α, δe, thr)로 (u̇, ẇ, q̇)를, 지상 평형은
    (h_cg, θ, φ)로 **6축 가속도 전부**를 0으로 만든다. 6축을 다 보는 이유는 지상에서는
    어느 축이든 남은 가속도가 곧 "기체가 미끄러지거나 기울어진다"는 뜻이라 하나도
    버릴 수 없기 때문이다.

    V=0이므로 공력은 정확히 0이고(aero.forces의 V≤0 분기) 타면은 아무 일도 하지 않는다.
    스로틀도 0으로 둔다 — 정칙화 마찰은 v=0에서 0이라(plant/ground.py §마찰) 추력이
    있으면 평형이 아니라 가속이다. 그래서 **포화·α 여유는 미판정(None)** 이다:
    V=0에서 그 둘은 의미가 없고 True로 두면 "여유가 있다"는 없는 정보를 만든다
    (연속성 미판정과 같은 자리 — 화면은 flagBadge가 "미판정"으로 낸다).

    case.alt는 **활주로 표고**로 읽는다(비행 트림에서 비행 고도인 것과 대비).
    case.mach는 0이어야 한다 — 정지 상태라 쓰이지 않는 값을 조용히 받지 않는다.
    """
    if aircraft.ground is None:
        raise ValueError("지상 평형은 착륙장치가 달린 기체에서만 — Aircraft(ground=...)")
    if float(case.mach) != 0.0:
        raise ValueError(f"지상 평형은 정지 상태 — mach는 0이어야 함: {case.mach}")

    elev = float(case.alt)
    gear = aircraft.ground
    z_lo = float(np.min(gear.contacts[:, 2]))
    z_hi = float(np.max(gear.contacts[:, 2]))
    if z_hi <= 0.0:
        raise ValueError("접촉점이 CG 아래(z>0)에 하나도 없음 — 지상 평형을 세울 수 없음")
    m, _cg, _J = aircraft.fuel_mass.at(case.fuel)
    h_seed = elev + z_hi - gear.rest_penetration(m * G0)
    controls = {"de": 0.0, "da": 0.0, "dr": 0.0, "throttle": (0.0, 0.0)}

    def _xe(z):
        xe = np.zeros(12)
        xe[XE_H] = z[0]
        xe[XE_THETA] = z[1]
        xe[XE_PHI] = z[2]
        return xe

    def resid(z):
        xd = aircraft.deriv_euler(_xe(z), controls, case.fuel, ground_elev=elev)
        return np.array([xd[XE_U], xd[XE_V], xd[XE_W], xd[XE_P], xd[XE_Q], xd[XE_R]])

    res = minimize(
        lambda z: float(np.sum(resid(z) ** 2)),
        np.array([h_seed, 0.0, 0.0]),
        method="SLSQP",
        bounds=[(elev + 0.5 * z_lo, elev + 2.0 * z_hi), GROUND_TILT_BOUNDS, GROUND_TILT_BOUNDS],
        # ftol은 trim_level과 같은 1e-16. 1e-16보다 작게 잡으면 도달 불가라 솔버가
        # maxiter를 다 돌고 success=False를 보고한다 — 잔차는 1e-8로 이미 맞는데도
        # "미수렴"이 되어 시뮬 진입이 막힌다(실측: ftol 1e-18에서 nit 300·실패,
        # 1e-16에서 nit 2·성공, 두 경우 잔차는 같은 자릿수).
        options={"maxiter": 300, "ftol": 1e-16},
    )
    h_cg, theta, phi = res.x
    r = resid(res.x)
    residual_ok = bool(np.all(np.abs(r) < GROUND_RESID_TOL))

    q_nb = euler_to_quat(phi, theta, 0.0)
    pos_n = np.array([0.0, 0.0, -h_cg])
    st = gear.contact_state(pos_n, np.zeros(3), q_nb, np.zeros(3), elev)
    flags = {
        "residual_ok": residual_ok,
        # 정지 상태에선 타면·α가 아무 일도 하지 않는다 — 통과로 위장하지 않는다
        "saturation_ok": None,
        "alpha_margin_ok": None,
        "continuity_ok": None,
        # 지상 평형 고유: 기체가 실제로 받쳐지고 있는가 (반력이 0이면 떠 있거나 빠졌다)
        "supported_ok": bool(st["wow"]),
    }
    state = VehicleState(
        t=0.0,
        pos_n=pos_n,
        vel_b=np.zeros(3),
        q_nb=q_nb,
        omega_b=np.zeros(3),
        fuel=case.fuel,
    )
    control = SurfaceCommand(elevon=np.zeros(4), rudder=0.0, throttle=np.zeros(2))
    return TrimResult(
        case=case,
        state=state,
        control=control,
        converged=bool(res.success) and residual_ok and bool(st["wow"]),
        cost=float(res.fun),
        flags=flags,
        params_fingerprint=fingerprint,
    )


_CONDITIONS = {"level": trim_level, "ground": trim_ground}


def trim(aircraft, case, fingerprint=""):
    """TrimCase.condition으로 트림 종류를 고른다 — 조건 문자열의 단일 해석 지점.

    이 필드는 계약에 있으면서 아무도 읽지 않던 자리였다(01 §4.1이 "수평정상비행부터"
    라고 적어 둔 확장 구멍). 지상 평형이 들어오면서 실제로 갈라진다.
    모르는 조건은 거부한다 — 조용히 level로 떨어지면 지상 케이스가 비행 트림으로
    풀려 "수렴했다"는 엉뚱한 해가 나온다.
    """
    fn = _CONDITIONS.get(str(case.condition))
    if fn is None:
        raise ValueError(
            f"모르는 트림 조건: {case.condition!r} (가능: {sorted(_CONDITIONS)})"
        )
    return fn(aircraft, case, fingerprint=fingerprint)


def trim_batch(aircraft, cases, fingerprint="", on_progress=None):
    """케이스 목록 순서대로 트림 — 직전 수렴해를 다음 초기값으로 시드, 연속성 판정 포함.

    on_progress(done, total, tr): 케이스마다 호출 (M13 서버 진행률 경로).
    truthy 반환 = 협조적 취소 — 지금까지의 부분 결과를 반환한다. 콜백 예외는
    전파된다 (부분 결과 소실) — 취소는 반드시 truthy 반환으로.
    """
    cases = list(cases)
    total = len(cases)
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
        if on_progress is not None and on_progress(len(results), total, tr):
            break
    return results
