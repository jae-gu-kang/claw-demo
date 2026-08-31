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
from claw.blocks.filters import RATE_FILTERS, rate_filter_tau
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
_WC_GRID_EXPANSIONS = 6  # 교차 탐색 격자 천장 확장 시도 횟수 (4배씩 — 마지막 곱은
# 시험 없이 버려지므로 실제로 **시험되는 최대 천장은 초기값의 4^5 = 1024배**다)


# 1차 필터의 출력 사상 — 상태식은 둘 다 ẋ_f = (x_rate − x_f)/τ로 같고 출력만 다르다.
# (c_rate, c_filt): 댐퍼가 먹는 신호 = c_rate·x_rate + c_filt·x_f
#   저역통과 y = x_f            → (0, 1)
#   워시아웃 y = x_rate − x_f    → (1, −1)
_FILTER_OUT = {"lowpass": (0.0, 1.0), "washout": (1.0, -1.0)}
# 어휘가 늘면 여기서 죽는다 — 안 그러면 5번째 종류가 스테이지 한복판에서 맨
# KeyError를 내고, run()은 _Cancelled만 잡으므로 세션이 저장 없이 죽는다.
# 노치는 아래 close_rates가 사유를 달아 거부하므로 이 표의 대상이 아니다.
_UNSUPPORTED = {"notch"}
assert set(_FILTER_OUT) | _UNSUPPORTED == set(RATE_FILTERS) - {"none"}, (
    f"필터 어휘와 레이트 지표 표가 어긋남: "
    f"{sorted(set(RATE_FILTERS) - {'none'})} vs {sorted(set(_FILTER_OUT) | _UNSUPPORTED)}"
)


def close_rates(lm_axis, rate_gains: dict, rate_filters: dict | None = None) -> LinearModel:
    """레이트 댐퍼 상태 피드백을 접은 축 모델 — A′ = A + Σ B[:,u]·k·e_rateᵀ.

    실제 법칙의 u += k_rate·rate 항 그대로다 (부호는 게인이 보유). B는 그대로 —
    자세 PI 루프가 같은 입력으로 들어간다.

    rate_filters: {group: 필터 스펙} — 그 자리의 댐퍼가 **필터를 거친 신호**를
    먹는 경우(데모 요축 워시아웃 τ=2 s, fcl/demo.py DEMO_YAW). 필터마다 상태를
    하나 **뒤에 붙인다** — 물리 상태 인덱스가 밀리지 않아야 이름 조회
    (x_names.index("p") 등)를 쓰는 소비자가 전부 그대로 동작한다.

    노치는 **거부한다**: f0에 복소쌍을 만들고 그 쌍이 `_WN_FLOOR_FRAC` 위에 들어와
    lat_metrics의 zeta_dr 최소값을 오염시킨다 (01 §7 "작동기·Padé 극이 강체 모드와
    섞인다"와 같은 문제 — 모드 선별 규칙을 새로 설계해야 한다). 조용히 무시하면
    지표가 필터를 반영한 척하므로 예외로 막는다. 노치의 마진 평가는 pi_loop 경유.
    """
    A = lm_axis.A.copy()
    B = lm_axis.B
    x_names = list(lm_axis.x_names)
    specs = dict(rate_filters or {})
    spec = AXIS_SPECS[lm_axis.axis]

    # 붙일 필터 상태를 먼저 세어 A를 한 번에 확장 — 물리 상태는 앞쪽 그대로다
    pending = []
    for group, x_rate, u_in in spec["rates"]:
        k = float(rate_gains.get(f"{group}.k_rate", 0.0))
        fs = specs.get(group)
        if k == 0.0:
            continue  # 댐퍼가 꺼진 자리 — 필터도 루프에 없다 (종류를 따지지 않는다)
        kind = fs.get("kind", "none") if fs is not None else "none"
        if kind in _UNSUPPORTED:
            raise ValueError(
                f"{group}: 노치는 레이트 지표 경로(close_rates)에서 지원하지 않는다 — "
                "f0 복소쌍이 모드 지표를 오염시킨다 (마진은 pi_loop 경유로 평가할 것)"
            )
        use_filter = kind != "none"
        pending.append((group, x_rate, u_in, k, fs if use_filter else None))

    n0 = A.shape[0]
    n_new = sum(1 for *_, fs in pending if fs is not None)
    if n_new:
        A = np.pad(A, ((0, n_new), (0, n_new)))
        B = np.pad(B, ((0, n_new), (0, 0)))

    slot = n0
    for group, x_rate, u_in, k, fs in pending:
        i = x_names.index(x_rate)
        j = lm_axis.u_names.index(u_in)
        if fs is None:
            A[:n0, i] += lm_axis.B[:, j] * k  # 물리 행만 — 확장된 필터 행은 B가 안 닿는다
            continue
        tau = rate_filter_tau(fs)  # 환산 정본은 blocks.filters
        c_rate, c_filt = _FILTER_OUT[fs["kind"]]
        A[slot, i] += 1.0 / tau  # ẋ_f = (x_rate − x_f)/τ
        A[slot, slot] += -1.0 / tau
        if c_rate:
            A[:n0, i] += lm_axis.B[:, j] * (k * c_rate)
        A[:n0, slot] += lm_axis.B[:, j] * (k * c_filt)
        x_names.append(f"{group}_filt")
        slot += 1

    C = np.pad(lm_axis.C, ((0, 0), (0, n_new))) if n_new else lm_axis.C
    return LinearModel(
        A=A, B=B, C=C, D=lm_axis.D,
        x_names=tuple(x_names), u_names=lm_axis.u_names, axis=lm_axis.axis,
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


def roll_real_mode(A, p_index):
    """롤 상태(p)를 가장 많이 담은 **실근**과 그 참여도 — (eig, participation).

    종전에는 "실근 중 max|Re|"를 롤 수렴 모드로 봤다. 그 휴리스틱은 두 군데서 깨진다:

    1) 요 댐퍼가 만든 빠른 실근이 롤 근보다 빠르면 그쪽이 뽑힌다. 데모 M0.6/h1000
       실측 — 롤 게인을 설계값의 0.2배로 줄여도 λ가 6.58에서 안 내려가고, **0으로
       완전히 꺼도 6.45다**. 재려는 게인에 거의 반응하지 않는 지표였다.
    2) 댐퍼가 약해지면 롤 모드가 더치롤·나선과 합쳐져 **실근으로 존재하지 않는다**.
       위 0.2배에서 남은 실근 둘의 p 참여도는 0.080·(나머지)로, 어느 쪽도 롤이 아니다.

    참여도 = |V[p,k] · V⁻¹[k,p]| (표준 participation factor — 모드별 상태 합이 1).
    호출자는 참여도가 낮으면 "롤 대역폭을 잴 수 없다"로 다뤄야 한다 — 낮은 참여도
    근의 |Re|를 롤 대역폭이라 부르는 것이 이 지표가 하던 일이다.

    고유벡터 행렬이 특이하면(결함 행렬) (None, None) — 호출자가 판정 불가로 흘린다.
    """
    w, V = np.linalg.eig(np.asarray(A, dtype=float))
    try:
        Winv = np.linalg.inv(V)
    except np.linalg.LinAlgError:
        return None, None
    best, best_part = None, -1.0
    for k, lam in enumerate(w):
        if abs(lam.imag) > 1e-9:
            continue
        part = float(abs(V[p_index, k] * Winv[k, p_index]))
        if part > best_part:
            best, best_part = complex(lam), part
    return best, (None if best is None else best_part)


def lat_metrics(A, wn_floor, p_index=1) -> dict:
    """횡축 폐쇄 A′ → {"zeta_dr", "roll_lambda", "roll_unstable", "roll_participation"}.

    zeta_dr: floor 위 진동쌍의 최소 ζ (없으면 1.0 — 모드가 실근으로 교환된 상태).
    roll_lambda: **p 참여도로 지목한** 실근의 |Re| — 롤 수렴 모드 대역폭 [rad/s].
    roll_unstable: 그 근이 발산근인가. |Re|는 부호를 지우므로(+12가 "목표 12 달성"으로
      보인다) 따로 낸다 — 튜너는 댐퍼 안정 캡이 걸러 주지만 검증에는 그 게이트가 없다.
    roll_participation: 지목의 신뢰도. 낮으면 롤 모드가 실근으로 존재하지 않는 것이다.

    판정은 하지 않는다 — criteria.judge_bandwidth가 이 셋을 받아 한다 (지표 계산과
    판정의 분리). p_index 기본 1은 lat 상태 순서 (v, p, r, phi)의 p 자리다
    (trim.linearize.LAT_STATES 정본 — axis_metrics가 x_names에서 찾아 넘긴다).
    """
    modes = damp(A)
    pairs = [m for m in modes if m["eig"].imag > 1e-9 and m["wn"] >= wn_floor]
    lam_mode, part = roll_real_mode(A, p_index)
    return {
        "zeta_dr": min((m["zeta"] for m in pairs), default=1.0),
        # 지목 실패(실근이 없거나 고유벡터 행렬이 특이)는 **0.0이 아니라 nan**이다.
        # 0.0을 내면 판정이 "목표의 0배 → fail"로 흘러 못 잰 것이 실패로 둔갑한다 —
        # nan은 judge_bandwidth가 na로 받는다 (loop_margins가 nan을 유지하는 원칙과 동일)
        "roll_lambda": float("nan") if lam_mode is None else abs(lam_mode.real),
        "roll_unstable": lam_mode is not None and lam_mode.real > 0.0,
        "roll_participation": part,
    }


def axis_metrics(lm_axis, rate_gains: dict, rate_filters: dict | None = None) -> dict:
    """개루프 축 모델 + 레이트 게인 → 폐쇄 모드 지표 (판정·튜닝 목적함수 공용).

    floor는 **개루프** 기준 wn으로 잡는다 — 필터 상태가 붙어도 기준선은 안 움직인다.
    """
    floor = _WN_FLOOR_FRAC * wn_reference(lm_axis)
    A = close_rates(lm_axis, rate_gains, rate_filters).A
    if lm_axis.axis == "lon":
        return lon_metrics(A, floor)
    # p 자리를 이름으로 찾는다 — 상태 순서를 여기 손으로 적으면 정본(LAT_STATES)과 갈린다
    return lat_metrics(A, floor, p_index=lm_axis.x_names.index("p"))


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
    rate_filters=None,
):
    """자세 PI 개루프 — 레이트 폐쇄 A′ 위 PI(kp,ki)·G·Act·Delay (sign=+1 기저).

    방향은 oriented_margins가 결정하므로 여기서는 +1로 조성한다.
    rate_filters는 **레이트 폐쇄에만** 든다 — 자세 경로에는 필터가 없다.
    """
    closed = close_rates(lm_axis, rate_gains, rate_filters)
    _group, x_out, u_in = AXIS_SPECS[lm_axis.axis]["att"]
    return pi_loop(
        closed, x_out=x_out, u_in=u_in, kp=kp, ki=ki, sign=1.0,
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )


def rate_loop_crossover(
    lm_axis, group, x_rate, u_in, k, *,
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
    rate_filters=None,
) -> float:
    """레이트 루프 |L|=1 최고 교차 주파수 [rad/s] — 작동기 대역폭 예산 검사용.

    반환: 교차 주파수 · **0.0**(격자 안에서 |L|이 1에 한 번도 안 닿음 = 교차 없음) ·
    **nan**(천장 확장을 다 쓰고도 |L| ≥ 1 = 격자 밖이라 못 쟀다). 셋을 구분해야
    소비자가 "교차 없음"과 "못 쟀다"를 가른다 — 종전에는 후자에 천장 값을 돌려줘
    교차 주파수가 아닌 수를 교차라 불렀다.

    마진 판정용이 아니라 작동기 대역폭 예산 검사용이다 (01 §4.2 "PM 91°→−76.3°"
    사고 재발 방지). 캡 자체는 `tune._cap_by_stability`가 폐루프 극으로 판정한다.
    """
    if k == 0.0:
        return 0.0
    loop = pi_loop(
        lm_axis, x_out=x_rate, u_in=u_in, kp=k, ki=0.0, sign=1.0,
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
        rate_filter=(rate_filters or {}).get(group),
    )
    # 격자 천장에서 |L|이 아직 1 이상이면 교차는 격자 **밖**이다. 그대로 w[-1]을
    # 돌려주면 교차 주파수가 아니라 천장 값을 내놓는 조용한 오답이 된다 — 천장을
    # 넓혀 실제 교차를 찾는다. 이 함정은 작동기 인자가 없을 때(w_hi가 wn_reference
    # 기반) 실제로 밟힌다: 레이트를 접은 A′는 진동 모드가 사라져 wn_reference가
    # 작아지고(데모 M0.6 요-닫은 lat 0.887 vs 생 4.216) 천장이 8.87로 내려앉아
    # 참값 15.7 대신 8.87이 나왔다.
    w_hi = 10.0 * (actuator_wn if actuator_wn else wn_reference(lm_axis))
    exhausted = True
    for _ in range(_WC_GRID_EXPANSIONS):
        w = np.logspace(-2, np.log10(w_hi), 600)
        mag = np.abs(loop.frequency_response(w).magnitude).reshape(-1)
        if mag[-1] < 1.0:
            exhausted = False
            break
        w_hi *= 4.0
    if exhausted:
        # 4096배까지 넓히고도 |L| ≥ 1이면 교차는 여전히 격자 밖이다. w[-1]을 내면
        # 종류가 같은 조용한 오답이다(천장을 교차라 부른다). nan은 "못 쟀다"이고,
        # 소비자는 이미 그 값을 통과로 안 친다 — 튜너는 rate_wc > 0이 거짓이 되어
        # wc_fallback 경로로 가고(플래그가 남는다), 직렬화는 null로 낸다
        return float("nan")
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
