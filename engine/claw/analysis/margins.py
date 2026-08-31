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
        # 주의: delay_s·pade_order가 함께 커지면 이 계수가 유한한 채로 거대해져
        # (0.001 s·20차에서 |den|max ≈ 3e89) **뒤이은 근 계산이** 넘친다. 계수
        # 유한성 검사로는 못 잡는다 — 실패는 control.margin 안에서 나므로 소비자가
        # 사유를 붙여 보고한다 (routes/analysis.py). 여기서 상한을 발명하지 않는다
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


def omega_covering(*loops, n_points=400):
    """주어진 개루프를 **모두** 덮는 log 주파수 격자 — 극·영점에서 유도, 양끝 ±1 decade.

    범위를 손으로 고정하면 기체·게인이 바뀔 때 정작 교차점이 화면 밖으로 나간다.
    적분기(원점 극)와 무한대 영점은 제외 — log 축에 올릴 수 없다.

    여러 개를 받는 이유: 두 조립(예: 필터 미반영/반영)을 겹쳐 비교하려면 **같은
    축**이어야 한다. 각자 자기 범위를 잡으면 두 곡선이 서로 다른 x에 놓여 비교가
    성립하지 않고, 한쪽에만 있는 극(워시아웃 코너 등)이 다른 쪽 범위 밖으로 나가
    그 교차를 통째로 놓친다.
    """
    feats = []
    for loop in loops:
        f = np.abs(np.concatenate([control.poles(loop), control.zeros(loop)]))
        feats.append(f[np.isfinite(f) & (f > 1e-9)])
    allf = np.concatenate(feats) if feats else np.array([])
    if allf.size == 0:
        lo_exp, hi_exp = -2.0, 2.0  # 특징 주파수가 없는 순수 이득 — 임의 범위 [기본값]
    else:
        lo_exp = math.floor(math.log10(float(allf.min()))) - 1
        hi_exp = math.ceil(math.log10(float(allf.max()))) + 1
    return np.logspace(lo_exp, hi_exp, int(n_points))


def _level_crossings(w, y, level):
    """표본 격자에서 y가 level을 지나는 주파수 목록 — log-w 선형보간.

    표본 사이는 보간이므로 격자가 성길수록 위치가 흐려진다. 그래도 "몇 개인가"는
    보존되는 쪽을 택했다 — 개수야말로 이 함수를 만든 이유이기 때문(아래 참조).
    """
    out = []
    d = np.asarray(y, dtype=float) - float(level)
    logw = np.log(np.asarray(w, dtype=float))
    n = len(d)
    i = 0
    while i < n:
        if d[i] == 0.0:
            # 정확히 준위에 앉은 표본 — 연달아 있으면 **접점 하나**지 교차 여럿이
            # 아니다. 묶어서 한 번만 낸다 (순수 이득 루프가 0 dB에 놓이면 표본
            # 수만큼 교차가 나던 것: 400점 격자에서 399개)
            j = i
            while j + 1 < n and d[j + 1] == 0.0:
                j += 1
            out.append(float(np.exp((logw[i] + logw[j]) / 2.0)))
            i = j + 1
            continue
        if i + 1 < n and d[i + 1] != 0.0 and d[i] * d[i + 1] < 0.0:
            t = d[i] / (d[i] - d[i + 1])
            out.append(float(np.exp(logw[i] + t * (logw[i + 1] - logw[i]))))
        i += 1
    return out


def bode_data(loop, w=None, n_points=400) -> dict:
    """개루프 → 보드선도 데이터 + 교차점 전량 (01 §4.2).

    **GM과 PM은 같은 곡선의 서로 다른 자리에서 읽는 수다** — PM은 이득이 0 dB를
    지나는 주파수(wcp)에서의 위상 여유, GM은 위상이 −180°를 지나는 주파수(wcg)
    에서의 이득 여유. 히트맵은 두 수를 따로 칠할 뿐 둘이 주파수축 어디에 있는지
    말하지 않으므로, 같은 축 위에 놓아 비교하게 하는 것이 이 데이터의 목적이다.

    crossings는 표본 격자에서 찾은 **모든** 교차를 낸다. `control.margin`은 다중
    교차 중 하나씩만 골라 (gm, pm)로 답하므로, 교차가 여럿이면 보고된 수가 어느
    자리 것인지 화면이 말할 수 있어야 한다 — 01 §4.2에 기록된 사례가 정확히
    이것이다: 요축 워시아웃을 반영하자 yaw_rate 마진이 91.4° → −86.7°로 튀었는데
    개선이 아니라 다중 0 dB 교차 중 선택이 바뀐 것이었고, 유의미한 고주파 교차의
    위상은 −88.6° → −85.9°로 거의 그대로였다. 그 구분을 눈으로 하게 하는 도구다.

    마진 수치는 `loop_margins`가 정본 — 여기서 다시 계산하지 않는다(두 번 적으면
    갈린다). 위상은 unwrap한 도(°)이므로 −180°의 등가 준위(−180 ± 360k)도 함께
    훑는다 — wrap된 값만 보면 저주파에서 감긴 교차를 통째로 놓친다.
    """
    w = omega_covering(loop, n_points=n_points) if w is None else np.asarray(w, dtype=float)
    resp = control.frequency_response(loop, w)
    mag = np.asarray(resp.magnitude, dtype=float).ravel()
    phase_deg = np.degrees(np.unwrap(np.asarray(resp.phase, dtype=float).ravel()))
    with np.errstate(divide="ignore"):
        mag_db = 20.0 * np.log10(mag)

    phase_levels = []
    if phase_deg.size:
        k_lo = math.floor((float(phase_deg.min()) + 180.0) / 360.0)
        k_hi = math.ceil((float(phase_deg.max()) + 180.0) / 360.0)
        phase_levels = [-180.0 + 360.0 * k for k in range(k_lo, k_hi + 1)]
    phase_cross = sorted(
        x for lv in phase_levels for x in _level_crossings(w, phase_deg, lv)
    )
    return {
        "w": [float(x) for x in w],
        "mag_db": [float(x) for x in mag_db],
        "phase_deg": [float(x) for x in phase_deg],
        "margins": loop_margins(loop),  # 정본 재사용 — 재계산 금지
        "crossings": {
            "gain": _level_crossings(w, mag_db, 0.0),
            "phase": phase_cross,
        },
    }
