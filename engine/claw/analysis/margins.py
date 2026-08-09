"""이득·위상여유 (python-control 래퍼, MATLAB margin 대체) + 마진 맵 (01 §4.2 [확정]).

마진 맵의 격자 시각화는 M14(web) 소관 — 여기서는 케이스별 수치 산출까지.
"""

import control
import numpy as np


def make_siso(lm, x_out, u_in):
    """LinearModel → 단일 입력(u_in) → 단일 상태(x_out) 상태공간 모델."""
    xi = lm.x_names.index(x_out)
    ui = lm.u_names.index(u_in)
    n = lm.A.shape[0]
    C = np.zeros((1, n))
    C[0, xi] = 1.0
    return control.ss(lm.A, lm.B[:, [ui]], C, [[0.0]])


def pi_loop(
    lm, x_out, u_in, kp, ki=0.0, sign=-1.0,
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
):
    """PI(kp+ki/s)와 SISO 플랜트(u_in→x_out)를 결합한 개루프 — 마진 맵 표준 루프.

    sign 기본 −1: 데모 부호 관례(δe + → 기수 하방, Cmde<0)에서 음피드백
    개루프가 양의 DC 이득을 갖도록 반전 — 부호는 설계값이 보유 (conventions).

    작동기·지연 포함은 둘 다 [기본값] 미포함(하위호환 — 기존 호출과 동일 결과).
    포함 여부는 호출자(서버 요청)가 결정 — "작동기·지연 제외 마진은 낙관적"
    (01 §4.2)이므로 포함이 웹 기본 폼값이지만, 엔진 계층은 중립을 유지한다.

    - actuator_wn·actuator_zeta: 함께 지정 시 개루프에 2차계 wn²/(s²+2ζωn·s+wn²)를
      캐스케이드 — 작동기(plant.actuator.SecondOrderActuator)의 실제 동특성을
      재사용하는 것이지 새 지연 모델이 아니다 (레이트/위치 한계는 비선형이라
      소신호 마진 해석에서는 제외 — 트림점 근방 미포화 전제).
    - delay_s: 항법 출력 지연 + 제어주기 등가지연 등 **작동기와 무관한** 순수
      전송지연 총합 [s]. e^(-s·delay_s)는 유한차원 상태공간으로 표현 불가 →
      Padé 근사(pade_order차, [기본값] 2 — 마진 해석에서 흔히 쓰는 차수) 캐스케이드.
    """
    if (actuator_wn is None) != (actuator_zeta is None):
        raise ValueError("actuator_wn·actuator_zeta는 함께 지정해야 함 (한쪽만 지정 불가)")
    if delay_s < 0.0:
        raise ValueError(f"delay_s는 음수 불가: {delay_s}")
    if delay_s > 0.0 and pade_order < 1:
        raise ValueError(f"pade_order는 1 이상이어야 함: {pade_order}")

    s = control.tf("s")
    pi = kp + ki / s if ki != 0.0 else control.tf([kp], [1.0])
    loop = sign * pi * make_siso(lm, x_out, u_in)
    if actuator_wn is not None:
        wn2 = actuator_wn * actuator_wn
        loop = loop * (wn2 / (s * s + 2.0 * actuator_zeta * actuator_wn * s + wn2))
    if delay_s > 0.0:
        num, den = control.pade(delay_s, pade_order)
        loop = loop * control.tf(num, den)
    return loop


def loop_margins(loop):
    """개루프 → {gm_db, pm_deg, wcg, wcp}. 이득여유 무한대는 inf, 해당 교차 없으면 nan."""
    gm, pm, wcg, wcp = control.margin(loop)
    if np.isnan(gm):
        gm_db = np.nan  # 판정 불가를 무한 여유로 오인하지 않도록 nan 유지
    elif np.isinf(gm):
        gm_db = np.inf
    else:
        gm_db = 20.0 * np.log10(gm) if gm > 0 else -np.inf
    return {"gm_db": float(gm_db), "pm_deg": float(pm), "wcg": float(wcg), "wcp": float(wcp)}


def margin_map(loops):
    """{케이스 이름: 개루프} → {케이스 이름: 마진 dict} — 마진 맵의 수치 계층."""
    return {name: loop_margins(sys) for name, sys in loops.items()}
