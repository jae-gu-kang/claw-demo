"""successive loop closure 조성 — 설계·검증 공용의 축별 루프 정의.

openloop.GROUP_LOOPS(평탄 SISO 선언)와 **의도적으로 다르다**. 그 선언은 게인 Δ의
마진 민감도용이고, 절대 판정에는 두 가지 실측 병리가 있다 (데모 M0.6 실증):
- 순수 P 레이트 루프(q←δe)는 DC 0 + 장주기 봉우리 교차 아티팩트로 control.margin이
  0.06 rad/s 교차의 PM −45° 같은 무의미한 수치를 낸다 — 레이트 댐퍼의 고전 판정
  기준은 마진이 아니라 **폐루프 모드 감쇠·대역폭**이다.
- 자세 PI를 레이트 피드백 없이 보면 설계점조차 PM 12°(피치)·5.6°(롤)로 나온다 —
  실제 법칙은 레이트 항이 함께 도니, 자세 루프 마진은 **레이트 폐쇄 후 플랜트**에서
  봐야 설계 의도와 일치한다.

그래서 조성은: 축별 레이트 댐퍼(횡축은 롤·요 **둘 다** — 요 댐퍼 없이는 더치롤
감쇠 판정이 성립하지 않는다)를 상태 피드백으로 접은 A′ 위에서
- 레이트 자리: 모드 지표 (ζ_sp / ζ_dr / λ_roll) 판정
- 자세 자리: PI 개루프 마진 (작동기+지연 포함) 판정

개루프 부호는 자동 방향 결정(oriented_margins) — 설계 게인의 부호가 자리마다
달라(피치 kp<0, 롤 kp>0) 고정 sign 하나로는 절반이 음의 DC 루프가 된다.
PM>0인 방향을 취하고 어느 방향이었는지를 결과에 남긴다.
"""

import numpy as np

from claw.analysis import loop_margins, pi_loop
from claw.analysis.modes import damp
from claw.common.contracts import LinearModel

# 축 → successive closure 명세. rates 순서 = 닫는 순서(튜닝 순서이기도 하다 —
# 요 댐퍼로 더치롤을 감쇠시킨 뒤 롤 댐퍼·자세 루프를 본다).
AXIS_SPECS = {
    "lon": {
        "rates": (("pitch", "q", "de"),),
        "att": ("pitch", "theta", "de"),
    },
    "lat": {
        "rates": (("yaw", "r", "dr"), ("roll", "p", "da")),
        "att": ("roll", "phi", "da"),
    },
}
_WN_FLOOR_FRAC = 0.4  # 모드 지표에서 저주파(장주기·나선) 제외 문턱 = 개루프 기준 wn × 이 값


def close_rates(lm_axis, rate_gains: dict) -> LinearModel:
    """레이트 댐퍼 상태 피드백을 접은 축 모델 — A′ = A + Σ B[:,u]·k·e_rateᵀ.

    실제 법칙의 u += k_rate·rate 항 그대로다 (부호는 게인이 보유). B는 그대로 —
    자세 PI 루프가 같은 입력으로 들어간다.
    """
    A = lm_axis.A.copy()
    spec = AXIS_SPECS[lm_axis.axis]
    for group, x_rate, u_in in spec["rates"]:
        k = float(rate_gains.get(f"{group}.k_rate", 0.0))
        if k == 0.0:
            continue
        i = lm_axis.x_names.index(x_rate)
        j = lm_axis.u_names.index(u_in)
        A[:, i] += lm_axis.B[:, j] * k
    return LinearModel(
        A=A, B=lm_axis.B, C=lm_axis.C, D=lm_axis.D,
        x_names=lm_axis.x_names, u_names=lm_axis.u_names, axis=lm_axis.axis,
        dt=lm_axis.dt, case=lm_axis.case, params_fingerprint=lm_axis.params_fingerprint,
    )


def wn_reference(lm_axis) -> float:
    """개루프 축의 기준 wn — 최속 진동쌍(단주기/더치롤 자리). 진동쌍이 없으면 최속 모드."""
    modes = damp(lm_axis.A)
    pairs = [m for m in modes if m["eig"].imag > 1e-9]
    return float((pairs or modes)[0]["wn"])


def lon_metrics(A, wn_floor) -> dict:
    """종축 폐쇄 A′ → {"zeta_sp"} — wn ≥ floor 모드의 최소 ζ.

    댐퍼가 세지면 단주기가 실근으로 갈라진다(ζ→1 취급) — classify_lon의 비정형
    예외를 데이터로 흡수한다. floor 위 모드가 없으면 1.0 (과감쇠).
    """
    fast = [m for m in damp(A) if m["wn"] >= wn_floor]
    return {"zeta_sp": min((m["zeta"] for m in fast), default=1.0)}


def lat_metrics(A, wn_floor) -> dict:
    """횡축 폐쇄 A′ → {"zeta_dr", "roll_lambda"}.

    zeta_dr: floor 위 진동쌍의 최소 ζ (없으면 1.0 — 모드가 실근으로 교환된 상태).
    roll_lambda: 실근 모드의 최대 |Re| — 롤 수렴 모드 대역폭 [rad/s].
    """
    modes = damp(A)
    pairs = [m for m in modes if m["eig"].imag > 1e-9 and m["wn"] >= wn_floor]
    reals = [m for m in modes if abs(m["eig"].imag) <= 1e-9]
    return {
        "zeta_dr": min((m["zeta"] for m in pairs), default=1.0),
        "roll_lambda": max((abs(m["eig"].real) for m in reals), default=0.0),
    }


def axis_metrics(lm_axis, rate_gains: dict) -> dict:
    """개루프 축 모델 + 레이트 게인 → 폐쇄 모드 지표 (판정·튜닝 목적함수 공용)."""
    floor = _WN_FLOOR_FRAC * wn_reference(lm_axis)
    A = close_rates(lm_axis, rate_gains).A
    return (lon_metrics if lm_axis.axis == "lon" else lat_metrics)(A, floor)


def oriented_margins(loop) -> tuple:
    """개루프 → (마진, 방향 ±1) — PM>0이 되는 방향을 취한다.

    자리마다 설계 게인 부호가 달라(피치 kp<0·롤 kp>0) 고정 sign으로는 절반이
    음의 DC 루프가 된다. 두 방향 다 PM≤0(또는 nan)이면 주어진 방향 그대로 —
    뒤집어도 안 되는 루프를 통과로 위장하지 않는다.
    """
    m_pos = loop_margins(loop)
    if np.isfinite(m_pos["pm_deg"]) and m_pos["pm_deg"] > 0.0:
        return m_pos, 1
    m_neg = loop_margins(-loop)
    if np.isfinite(m_neg["pm_deg"]) and m_neg["pm_deg"] > 0.0:
        return m_neg, -1
    return m_pos, 1


def att_margin_loop(
    lm_axis, rate_gains: dict, kp, ki, *,
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
):
    """자세 PI 개루프 — 레이트 폐쇄 A′ 위 PI(kp,ki)·G·Act·Delay (sign=+1 기저).

    방향은 oriented_margins가 결정하므로 여기서는 +1로 조성한다.
    """
    closed = close_rates(lm_axis, rate_gains)
    _group, x_out, u_in = AXIS_SPECS[lm_axis.axis]["att"]
    return pi_loop(
        closed, x_out=x_out, u_in=u_in, kp=kp, ki=ki, sign=1.0,
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )


def rate_loop_crossover(
    lm_axis, group, x_rate, u_in, k, *,
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
) -> float:
    """레이트 루프 |L|=1 최고 교차 주파수 [rad/s] — 작동기 대역폭 예산 검사용.

    교차가 없으면 0.0. 마진 판정용이 아니라 ωc ≤ wc_frac_act×actuator_wn 캡
    (01 §4.2 "PM 91°→−76.3°" 사고 재발 방지) 검사용이다.
    """
    if k == 0.0:
        return 0.0
    loop = pi_loop(
        lm_axis, x_out=x_rate, u_in=u_in, kp=k, ki=0.0, sign=1.0,
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )
    w_hi = 10.0 * (actuator_wn if actuator_wn else wn_reference(lm_axis))
    w = np.logspace(-2, np.log10(w_hi), 600)
    mag = np.abs(loop.frequency_response(w).magnitude).reshape(-1)
    above = np.nonzero(mag >= 1.0)[0]
    if above.size == 0:
        return 0.0
    i = int(above[-1])
    if i >= len(w) - 1:
        return float(w[-1])
    # 교차 구간 로그 보간
    m0, m1 = mag[i], mag[i + 1]
    t = (np.log(m0) - 0.0) / (np.log(m0) - np.log(m1)) if m1 > 0 else 0.0
    return float(np.exp(np.log(w[i]) + t * (np.log(w[i + 1]) - np.log(w[i]))))
