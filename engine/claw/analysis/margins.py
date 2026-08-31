"""이득·위상여유 (python-control 래퍼, MATLAB margin 대체) + 마진 맵 (01 §4.2 [확정]).

마진 맵의 격자 시각화는 M14(web) 소관 — 여기서는 케이스별 수치 산출까지.
"""

import math

import control
import numpy as np

from claw.blocks.filters import RATE_FILTERS, rate_filter_tau


def _tf_washout(s, spec):
    tau = rate_filter_tau(spec)  # fc→tau 환산의 정본은 blocks.filters (두 해석 경로 공유)
    return (tau * s) / (tau * s + 1.0)


def _tf_lowpass(s, spec):
    tau = rate_filter_tau(spec)
    return 1.0 / (tau * s + 1.0)


def _tf_notch(s, spec):
    f0, q = float(spec["f0"]), float(spec["q"])
    if not f0 > 0.0 or not q > 0.0:
        raise ValueError(f"노치 f0·q는 양수여야 함: f0={f0} [Hz], q={q}")
    w0 = 2.0 * math.pi * f0
    return (s * s + w0 * w0) / (s * s + (w0 / q) * s + w0 * w0)


# 필터 종류 → 연속시간 전달함수. 어휘 정본은 blocks.RATE_FILTERS이고 여기는 그
# 해석 표현이다 — 어휘만 늘리고 TF를 안 늘리면 아래 단정문이 import 시점에 죽는다
# (codegen/ir_exec.py의 `assert set(_OP_FN) == set(OPS)`와 같은 가드).
_FILTER_TF = {
    "washout": _tf_washout,
    "lowpass": _tf_lowpass,
    "notch": _tf_notch,
}
assert set(_FILTER_TF) == set(RATE_FILTERS) - {"none"}, (
    f"필터 어휘와 마진 TF가 어긋남: {sorted(set(RATE_FILTERS) - {'none'})} vs {sorted(_FILTER_TF)}"
)


def filter_tf(spec):
    """필터 스펙 → 연속시간 전달함수 (None이면 필터 없음).

    spec: {"kind": "washout"|"lowpass"|"notch", <파라미터>} 또는 None/{"kind":"none"}.
    파라미터 이름·단위는 블록 PARAM_DEFS 그대로 — washout `tau`[s],
    lowpass `fc`[Hz], notch `f0`[Hz]·`q`. 단위를 여기서 새로 정하지 않는다.

    **연속시간 근사**: 실제 블록은 이산이다(1차는 ZOH-정확 `p=e^(-dt/tau)`,
    노치는 RBJ biquad). pi_loop가 작동기 2차계·Padé도 연속으로 모델하므로
    같은 자를 쓴 것이고, 제어주기(100 Hz)가 루프 대역보다 충분히 높다는 전제다.
    """
    if spec is None:
        return None
    kind = spec.get("kind", "none")
    if kind == "none":
        return None
    fn = _FILTER_TF.get(kind)
    if fn is None:
        raise ValueError(f"미정의 필터 종류 {kind!r} — 허용: {sorted(RATE_FILTERS)}")
    return fn(control.tf("s"), spec)


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
    rate_filter=None,
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
    - rate_filter: 레이트 피드백 경로 필터 스펙(filter_tf 규격). 법칙에 실제로
      들어 있는 필터를 루프에 반영한다 — 데모 요축 워시아웃(τ=2 s,
      fcl/demo.py DEMO_YAW)이 그 예다. 미지정이면 필터 없음이고, 그 경우
      **필터가 실제로 있어도 루프는 정적 게인으로 본다**(호출자가 선언해야 한다 —
      pipeline/openloop.py GROUP_LOOPS가 그 선언의 정본).
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
    filt = filter_tf(rate_filter)
    if filt is not None:
        loop = loop * filt
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
