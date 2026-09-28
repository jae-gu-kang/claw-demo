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
      예제 기체 law.design.scas.yaw)이 그 예다. 미지정이면 필터 없음이고, 그 경우
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


def _path_tf(kp, ki, sign, delay_s, pade_order):
    """루프 한 개의 되먹임 경로 sign·PI·지연 (작동기 제외 — 작동기는 입력 자리에 한 번만 선다)."""
    s = control.tf("s")
    path = sign * (kp + ki / s if ki != 0.0 else control.tf([kp], [1.0]))
    if delay_s > 0.0:
        num, den = control.pade(delay_s, pade_order)
        path = path * control.tf(num, den)
    return path


def broken_loop(
    lm, x_out, u_in, kp, ki=0.0, sign=-1.0, others=(), *,
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
    rate_filter=None,
):
    """루프 하나를 끊고 **같은 축의 나머지 루프는 닫은** 개루프 — AS94900 안정 여유의 끊는 자리 (e2e D2).

    AS94900(舊 MIL-F-9490D) 3.1.3.6의 여유는 "루프 하나를 끊고 나머지는 닫은" 개루프에서 잰다. pi_loop는 루프
    하나만 있는 축에서 잰다 — 같은 축에 다른 루프가 있으면 그 루프를 **연 채로** 재는 셈이라 기체가 실제로 나는
    폐루프가 아니다. 쇼케이스 기체 roll_p를 요 댐퍼를 연 채로 재면 이 루프만 닫은 폐루프의 나선이 발산해(실근
    +0.009~+0.04 rad/s) GM이 ω = 0에서 −9.7 dB로 읽혔다 — 요 댐퍼를 닫으면 그 발산은 없다.

    others: [{"x_out", "u_in", "kp", "ki", "sign"}, …] — 이 축에서 닫아 둘 루프(각자 pi_loop와 같은 부호 관례:
    u = −sign·PI·x). 비면 **pi_loop 그대로**다(같은 객체 경로 — 루프 하나짜리 요청의 수는 비트까지 종전과 같다).

    조립(선형 시불변 — 소신호 전제는 pi_loop와 같다):
    - 작동기 2차계는 **입력 자리마다 한 번** 선다(같은 타면을 쓰는 루프가 둘이어도 작동기는 하나다).
    - 지연(Padé)은 **루프 경로마다** 선다(센서·연산 지연 — 끊는 루프의 경로에도).
    - 끊는 자리는 이 루프의 되먹임 경로(센서 쪽)다 — L = sign·PI·지연·[u_in → x_out | 나머지 닫힘].
      나머지 루프가 같은 입력을 쓰면 작동기 입력에서 끊은 값(전 루프 합)과 다르다 — 루프별 판독이다.
    - rate_filter는 끊는 루프의 경로에만(pi_loop와 같다). 닫아 둔 루프는 필터 없이(마진 맵의 정적 게인 계약).
    전달함수로 낸다 — nyquist_margins의 폐루프 판정(극·영점 상쇄를 걷는 minreal)이 pi_loop 결과와 같은 길을 탄다.
    """
    others = list(others)
    if not others:
        return pi_loop(lm, x_out, u_in, kp, ki=ki, sign=sign,
                       actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
                       delay_s=delay_s, pade_order=pade_order, rate_filter=rate_filter)
    if (actuator_wn is None) != (actuator_zeta is None):
        raise ValueError("actuator_wn·actuator_zeta는 함께 지정해야 함 (한쪽만 지정 불가)")
    if delay_s < 0.0:
        raise ValueError(f"delay_s는 음수 불가: {delay_s}")
    if delay_s > 0.0 and pade_order < 1:
        raise ValueError(f"pade_order는 1 이상이어야 함: {pade_order}")

    ins = []
    for u in [u_in] + [o["u_in"] for o in others]:
        if u not in ins:
            ins.append(u)
    outs = [o["x_out"] for o in others] + [x_out]  # 마지막 출력이 끊는 루프의 것
    # 폐루프를 행렬로 직접 쌓는다 — control의 MIMO 전달함수 변환은 slycot이 있어야 하고, 정적 이득 블록(상태 0개)은
    # numpy 경고를 낸다. 플랜트(+입력 자리마다 작동기)는 D = 0이다
    n = lm.A.shape[0]
    Cp = np.zeros((len(outs), n))
    for r, x in enumerate(outs):
        Cp[r, lm.x_names.index(x)] = 1.0
    Ap, Bp = np.asarray(lm.A, dtype=float), np.asarray(lm.B, dtype=float)[:, [lm.u_names.index(u) for u in ins]]
    if actuator_wn is not None:
        # 입력 자리마다 [a, ȧ]: ä = wn²(u − a) − 2ζwn·ȧ, 플랜트는 a를 받는다 — pi_loop의 2차계와 같은 전달함수
        wn2, c = actuator_wn * actuator_wn, 2.0 * actuator_zeta * actuator_wn
        m = len(ins)
        Aa = np.kron(np.eye(m), np.array([[0.0, 1.0], [-wn2, -c]]))
        Ba = np.kron(np.eye(m), np.array([[0.0], [wn2]]))
        Ca = np.kron(np.eye(m), np.array([[1.0, 0.0]]))
        Ap = np.block([[Ap, Bp @ Ca], [np.zeros((2 * m, n)), Aa]])
        Bp = np.vstack([np.zeros((n, m)), Ba])
        Cp = np.hstack([Cp, np.zeros((len(outs), 2 * m))])
    # 닫아 둘 루프의 경로(sign·PI·지연)를 블록 대각으로 — 출력 자리 r → 입력 자리 ins.index(u_in)
    blocks = []
    for o in others:
        path = _path_tf(float(o["kp"]), float(o.get("ki", 0.0)), float(o.get("sign", -1.0)), delay_s, pade_order)
        num, den = path.num[0][0], path.den[0][0]
        if len(den) == 1:  # 정적 이득 — 상태 없음
            blocks.append((np.zeros((0, 0)), np.zeros((0, 1)), np.zeros((1, 0)), np.array([[num[0] / den[0]]])))
        else:
            sp = control.ss(path)
            blocks.append((sp.A, sp.B, sp.C, sp.D))
    nc = sum(b[0].shape[0] for b in blocks)
    Ac, Bc = np.zeros((nc, nc)), np.zeros((nc, len(outs)))
    Cc, Dc = np.zeros((len(ins), nc)), np.zeros((len(ins), len(outs)))
    k = 0
    for r, (o, (a, b, c_, d)) in enumerate(zip(others, blocks)):
        j, q = ins.index(o["u_in"]), a.shape[0]
        Ac[k:k + q, k:k + q] = a
        Bc[k:k + q, r] = b[:, 0]
        Cc[j, k:k + q] += c_[0, :]
        Dc[j, r] += d[0, 0]
        k += q
    # u = r − (Cc·xc + Dc·y) — pi_loop의 1 + L 관례와 같은 음의 되먹임(u = −sign·PI·x), r은 끊는 루프의 입력 자리
    A_cl = np.block([[Ap - Bp @ Dc @ Cp, -Bp @ Cc], [Bc @ Cp, Ac]])
    B_cl = np.vstack([Bp[:, [ins.index(u_in)]], np.zeros((nc, 1))])
    C_cl = np.hstack([Cp[[len(outs) - 1], :], np.zeros((1, nc))])
    siso = control.ss2tf(control.ss(A_cl, B_cl, C_cl, np.zeros((1, 1))))
    loop = _path_tf(kp, ki, sign, delay_s, pade_order) * siso
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


# 폐루프 극의 안정 판정선 — Re ≥ −이 값이면 안정이 아니다(한계 안정도 안정으로 치지 않는다). 튜너 댐퍼 가드
# (design/tune.py _spiral_exempt_verdict)와 같은 선이다 — 같은 루프를 두 곳이 다르게 판정하지 않게
_CL_STABLE_TOL = 1e-9
# 폐루프 극을 세기 전에 걷어낼 극·영점 상쇄의 절대 거리 — 전달함수에 없는 숨은 모드(아래 closed_loop_unstable)만.
# 1e-7이면 수치 오차로 갈라진 정확한 상쇄(원점 쌍은 근 계산 뒤 ~1e-12)는 걷고, 가까울 뿐인 물리 쌍(더치롤 극과
# p←δa 영점 — 상대 1e-3 이상 떨어져 있다)은 남긴다
_CANCEL_TOL = 1e-7


def _gm_to_db(gm) -> float:
    """선형 GM → dB — loop_margins와 같은 규약(nan 유지 · inf · 0 이하 −inf)."""
    if np.isnan(gm):
        return float("nan")
    if np.isinf(gm):
        return float("inf")
    return float(20.0 * np.log10(gm)) if gm > 0 else float("-inf")


def closed_loop_unstable(loop) -> list:
    """이 루프 **하나만** 음의 되먹임(1 + L)으로 닫은 폐루프의 불안정 극 — [[Re, Im≥0], …] (안정이면 빈 목록).

    다중 교차 루프에서 교차 하나의 PM 부호로는 안정을 말할 수 없다 — 나이퀴스트 판정(= 폐루프 극)이 정본이다.
    극·영점 상쇄는 걷어낸 뒤 센다: PI 적분기와 q←δe의 원점 영점(q = θ̇)은 전달함수 L에 없는 **숨은 모드**라
    (적분기 상태와 θ의 상수 차) 그대로 두면 원점(Re ≈ −1e−16)에 앉은 그 극을 한계 안정 발산으로 센다.
    켤레쌍은 하나(Im ≥ 0)만 낸다.
    """
    tf = loop if isinstance(loop, control.TransferFunction) else control.ss2tf(loop)
    poles = control.poles(control.feedback(tf.minreal(_CANCEL_TOL), 1))
    return [[float(p.real), float(abs(p.imag))] for p in poles
            if p.real >= -_CL_STABLE_TOL and p.imag >= 0.0]


def nyquist_margins(loop) -> dict:
    """개루프 → 나이퀴스트에 맞는 이득·위상여유 + 공개 — 마진 맵·보드선도의 정본 (01 §4.2, e2e D2).

    `loop_margins`(control.margin 그대로)는 교차가 여럿이면 |PM|이 가장 작은 0 dB 교차와 |log GM|이 가장 작은
    −180° 교차를 고르고 **부호째** 낸다. 고르는 자리는 나이퀴스트 그대로다(−1에 가장 가까운 교차 — AS94900이
    ±로 요구하는 여유가 그것이다). 틀린 것은 부호의 뜻이다: control의 PM 부호는 교차점이 실축 **위(음수)·아래
    (양수)** 어느 쪽인가이고, GM 부호는 이득을 **올려(양수)·내려(음수)** −1에 닿는가다. 교차가 하나뿐인 교과서
    루프에서만 그 부호가 곧 안정·불안정이다. 레이트 루프(q·p·r ← 타면)는 원점 영점(q = θ̇) 때문에 저주파
    봉우리(장주기·나선)에서 0 dB를 여러 번 지나고 — 쇼케이스 기체 pitch_q는 0.2~0.3 rad/s 교차의 "−50~−79°"를
    냈는데 그 점은 −1에서 50~79° 떨어진 위쪽이고 폐루프는 안정이었다. roll_p의 "GM −9.7 dB @ ω = 0"은 이 루프만
    닫으면 나선이 느리게 발산한다는 사실의 다른 얼굴이었다(루프 대역의 GM은 +10 dB). 화면·판정선은 음수를
    부족으로 칠하므로 둘 다 전 칸 빨강이 됐다.

    그래서 **이 루프 하나만 닫은 폐루프의 극(나이퀴스트 판정)을 먼저 보고** 둘로 가른다:

    - **안정** — 여유는 −1까지의 거리다: `pm_deg` = min |PM_i|(교차점에서 −1까지의 위상 거리, 늘 ≥ 0),
      `gm_db` = min |GM_j|dB(이득을 올리든 내리든 −1에 닿는 가장 작은 배율, 늘 ≥ 0). 고르는 교차는
      control.margin과 같다. 불안정해지는 방향이 종전 부호와 반대 쪽이면 표시를 단다 — `pm_lead: True`(지연이
      아니라 **진상**이 넘긴다 — 교차점이 실축 위), `gm_lower: True`(이득을 **내리면** 넘긴다 — 조건부 안정).
    - **불안정** — 안정 여유는 정의되지 않는다. 대신 루프가 설계된 자리의 고전 판독을 부호째 낸다: 루프 교차
      (가장 높은 0 dB 교차 — 루프 대역폭을 정하는 자리, 튜너의 작동기 대역 예산 closure.rate_loop_crossover와 같은
      정의)의 PM과, 그 교차에 가장 가까운(log 주파수) −180° 교차의 GM(음수 = 그 자리에서 이미 넘었다). 발산극은
      `closed_loop`({"stable": False, "unstable": [[Re, Im]…]})로 따로 낸다 — 교차 대역의 발산(음수가 곧 문제)과
      루프 대역 한참 아래의 느린 실근(단독 해석에서만 보이는 나선 — 교차 여유는 멀쩡하다)을 화면이 가르게.
    - **공개** — 0 dB·−180° 교차가 둘 이상이면 `crossings`(교차마다 control 부호 관례의 PM·GM)를 싣는다.

    교차가 하나씩이고 폐루프가 안정이며 부호가 교과서 그대로면 네 키뿐이고 값도 `loop_margins`와 비트 같다
    (서버 골든 margin_map이 이것을 지킨다). 교차가 없으면 control.margin 관례(0 dB 교차 없음 → PM inf·wcp nan,
    −180° 교차 없음 → GM inf·wcg nan)다.
    """
    gm, pm, _sm, w180, wc, _ws = control.stability_margins(loop, returnall=True)
    gm, pm = np.atleast_1d(np.asarray(gm, dtype=float)), np.atleast_1d(np.asarray(pm, dtype=float))
    w180, wc = np.atleast_1d(np.asarray(w180, dtype=float)), np.atleast_1d(np.asarray(wc, dtype=float))
    unstable = closed_loop_unstable(loop)
    usable = [j for j in range(gm.size) if np.isfinite(gm[j]) and gm[j] > 0.0]  # |L| = 0·∞인 판독은 배율이 아니다

    out = {}
    if not unstable:
        # control.margin과 같은 선택(−1에 가장 가까운 교차) — 첫 최소(np.where(...)[0][0])까지 같다
        i = int(np.argmin(np.abs(pm))) if pm.size else None
        j = min(usable, key=lambda k: abs(math.log(gm[k]))) if usable else None
        pm_raw = float(pm[i]) if i is not None else float("inf")
        gm_raw = float(gm[j]) if j is not None else float("inf")
        out = {
            "gm_db": abs(_gm_to_db(gm_raw)),
            "pm_deg": abs(pm_raw),
            "wcg": float(w180[j]) if j is not None else float("nan"),
            "wcp": float(wc[i]) if i is not None else float("nan"),
        }
        if pm_raw < 0.0:
            out["pm_lead"] = True
        if gm_raw < 1.0:
            out["gm_lower"] = True
    else:
        i = int(np.argmax(wc)) if wc.size else None  # 루프 교차 — 가장 높은 0 dB 교차
        if i is not None:
            near = [k for k in usable if w180[k] > 0.0]
            j = min(near, key=lambda k: abs(math.log(w180[k] / wc[i]))) if near else None
        else:
            j = min(usable, key=lambda k: abs(math.log(gm[k]))) if usable else None  # 루프 교차가 없다
        out = {
            "gm_db": _gm_to_db(float(gm[j])) if j is not None else float("inf"),
            "pm_deg": float(pm[i]) if i is not None else float("inf"),
            "wcg": float(w180[j]) if j is not None else float("nan"),
            "wcp": float(wc[i]) if i is not None else float("nan"),
        }
    if wc.size > 1 or w180.size > 1:
        out["crossings"] = {
            "gain": [{"w": float(w), "pm_deg": float(p)} for w, p in zip(wc, pm)],
            "phase": [{"w": float(w), "gm_db": _gm_to_db(g)} for w, g in zip(w180, gm)],
        }
    if unstable:
        out["closed_loop"] = {"stable": False, "unstable": unstable}
    return out


def margin_map(loops):
    """{케이스 이름: 개루프} → {케이스 이름: 마진 dict} — 마진 맵의 수치 계층 (nyquist_margins가 정본)."""
    return {name: nyquist_margins(sys) for name, sys in loops.items()}


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

    crossings는 표본 격자에서 찾은 **모든** 교차를 낸다. 마진은 다중 교차 중 하나씩만
    골라 (gm, pm)로 답하므로, 교차가 여럿이면 보고된 수가 어느 자리 것인지 화면이 말할
    수 있어야 한다 — 01 §4.2에 기록된 사례가 정확히 이것이다: 요축 워시아웃을 반영하자
    yaw_rate 마진이 91.4° → −86.7°로 튀었는데 개선이 아니라 다중 0 dB 교차 중
    control.margin의 선택이 바뀐 것이었고, 유의미한 고주파 교차의 위상은 −88.6° →
    −85.9°로 거의 그대로였다. 그 구분을 눈으로 하게 하는 도구다.

    마진 수치는 `nyquist_margins`가 정본(마진 맵 칸과 같은 정의) —
    여기서 다시 계산하지 않는다(두 번 적으면 갈린다). 위상은 unwrap한 도(°)이므로
    −180°의 등가 준위(−180 ± 360k)도 함께 훑는다 — wrap된 값만 보면 저주파에서 감긴
    교차를 통째로 놓친다.
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
        "margins": nyquist_margins(loop),  # 정본 재사용(마진 맵 칸과 같은 정의) — 재계산 금지
        "crossings": {
            "gain": _level_crossings(w, mag_db, 0.0),
            "phase": phase_cross,
        },
    }
