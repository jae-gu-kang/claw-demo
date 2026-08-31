"""운영점별 SCAS 게인 자동 튜닝 — 결정론적 2단 (댐퍼 감쇠 목표 → 자세 PI 루프쉐이핑).

docs -02의 "자동 PID 튜닝 스코프 제외 [확정]"을 번복하는 구현 (사용자 확정).
LQR 제외는 유지 — PI 구조 불변, 튜닝 방식만 자동화한다. 대상은 SCAS 내측
7자리(pitch/roll kp·ki·k_rate + yaw.k_rate)이고 AP 외측(고도·속도·헤딩)은 v1
제외 — 분리모델에 h·ψ 상태가 없다는 openloop.py GROUP_LOOPS의 정직성과 같은 이유.

2단 구조 (closure.py의 successive closure 조성과 같은 정의 — 튜닝과 검증이 같은
자로 잰다):
1. 레이트 댐퍼 — 폐쇄 모드 지표 목표의 단조 스캔+이분: pitch ζ_sp→zeta_sp,
   yaw ζ_dr→zeta_dr(먼저 — 더치롤 감쇠 없이는 횡축이 성립 안 함), roll
   λ_roll→roll_lambda. 부호는 설계값이 보유(방향만 쓴다), 탐색은 |설계값|×4 브래킷.
   댐퍼 안정 캡: 작동기·지연 포함 폐루프 고유치 안정을 위반하면 |k|를 안정 경계
   아래로 이분 축소 (01 §4.2 "PM 91°→−76.3°" 실증 사고의 재발 방지 가드 —
   교차 주파수 캡이 아니라 폐루프 안정성 판정이다: |L|<1 댐퍼는 교차가 없다).
2. 자세 PI — 목표 교차 ωc_att = (레이트 ωc 또는 기준 wn)/wc_ratio_att에서
   |PI·G′·Act·Delay|=1이 되게 |kp| 결정 (PI 영점 = ωc_att×ki_zero_frac),
   oriented_margins로 검증 → PM/GM 미달 시 ωc_att ← backoff× 기하 백오프,
   바닥(wc_att_floor_frac) 도달 시 status="infeasible" — **던지지 않는다**.
   infeasible도 결과다: 분류기(classify)의 structural_limit 판정 근거가 된다.

polish=True는 선택적 Nelder-Mead 마무리(kp·ki 2변수, 대역폭 보상−마진 벌점) —
기본 OFF, 결정론·재현성 우선.
"""

import math
from dataclasses import asdict, dataclass

import numpy as np

from claw.design.closure import (
    AXIS_SPECS,
    att_margin_loop,
    axis_metrics,
    close_rates,
    oriented_margins,
    rate_loop_crossover,
    wn_reference,
)
from claw.trim import split_axes

_SCAN_N = 33  # 레이트 게인 브래킷 스캔 밀도
_BISECT_N = 24  # 이분 반복 (브래킷 폭 ×2^-24)
_BRACKET_GROWTH = 4.0  # 목표 미도달 시 브래킷 상한 배율
_BRACKET_EXPANSIONS = 3  # 확장 횟수 상한 (4^3 = 설계값의 256배까지)
# 최종 조성 재측정의 목표 달성 허용오차 — 탐색은 프리픽스 조성에서 이분 수렴하므로
# 조성이 바뀐 값은 목표선 양쪽에 임의로 떨어진다 (실측 상대오차 ~6e-5)
_FINAL_METRIC_RTOL = 1e-3
# 마무리(Nelder-Mead)의 초기 simplex — log 배율 0.3 ≈ ×1.35. scipy 기본값에 맡기면
# x0 = [0, 0]이라 변 길이가 0.00025가 되어 탐색이 사실상 일어나지 않는다.
_POLISH_SIMPLEX = ((0.0, 0.0), (0.3, 0.0), (0.0, 0.3))
_POLISH_GUARD_PM = 0.5  # 벌점 무릎의 가드 [deg] — 최적점이 판정선에 정확히 붙는 것을 막는다
_POLISH_GUARD_GM = 0.25  # 같은 목적 [dB]
# 마무리가 게인을 바꿔도 그대로인 메타 — 요구선과 "목표 교차가 다른 물리량으로
# 갈아탔다"는 표시. 마무리 결과에 물려받지 않으면 구제된 자리에서만 사라진다
_ATT_META = ("target_pm_deg", "target_gm_db", "target_wc_frac", "wc_fallback")

# 자리별 포기 사유 — "왜 목표에 못 갔나"를 한 낱말로. 종전에는 점 단위 status 하나에
# 서로 다른 사유 넷이 뭉쳐 있었고, 안내 문구는 그중 한 경우에 **사실과 달랐다**
# (마진은 통과했는데 "마진 미달"이라 적었다).
REASON_OK = "ok"
REASON_ZERO_DESIGN = "zero_design"  # 설계값 0 — 방향 정보가 없어 튜닝 자체를 안 한다
REASON_TARGET_UNREACHED = "target_unreached"  # 브래킷을 끝까지 넓혀도 미달 (플랜트 한계)
REASON_CAPPED = "capped"  # 댐퍼 안정 캡이 목표 전에 묶었다 (작동기·지연 예산)
REASON_NO_STABLE_GAIN = "no_stable_gain"  # 안정한 |k|가 없어 댐퍼를 껐다
REASON_BANDWIDTH_COLLAPSE = "bandwidth_collapse"  # 마진은 통과, 교차가 하한 아래
REASON_MARGIN_FLOOR = "margin_floor"  # 백오프 바닥까지 PM/GM 미달
REASON_DEGENERATE = "degenerate"  # 기저 루프 응답이 무의미 — 튜닝 불가
REASON_RESCUED = "rescued"  # 백오프 해가 하한 미달이라 마무리로 구제됨 (통과)
REASON_NA_NO_CROSSOVER = "na_no_crossover"  # 교차가 없어 마진을 잴 수 없다 (통과 아님)

# 사유 → 사람이 읽는 한 줄 + 다음 수. 화면·원장이 이 표를 쓴다 (엔진이 정본).
REASON_TEXT = {
    REASON_OK: "설계 목표 달성",
    REASON_ZERO_DESIGN: "설계 게인이 0이라 방향 정보가 없다 — 이 자리를 쓸 것이면 설계값을 먼저 정한다",
    REASON_TARGET_UNREACHED: "게인을 아무리 키워도 목표 지표가 안 나온다 — 플랜트 한계다."
                             " 목표를 낮추거나 이 조건을 설계 범위에서 뺀다",
    REASON_CAPPED: "작동기·지연 포함 폐루프 안정 경계가 목표 전에 묶는다 —"
                   " 작동기 대역폭 예산을 늘리거나 목표를 낮춘다",
    REASON_NO_STABLE_GAIN: "어떤 게인으로도 이 댐퍼 루프가 안정하지 않아 0으로 두었다 —"
                           " 플랜트·루프 구조를 검토한다",
    REASON_BANDWIDTH_COLLAPSE: "마진은 넘겼으나 교차 주파수가 하한 아래다 — 성능이 무너졌다."
                               " 지연·작동기 예산을 늘리거나 대역폭 하한을 낮춘다",
    REASON_MARGIN_FLOOR: "대역폭을 바닥까지 버려도 PM/GM 목표에 못 미친다 —"
                         " 지연·작동기 예산이 병목이다",
    REASON_DEGENERATE: "이 자리의 기저 루프 응답이 무의미하다 — 입출력·플랜트를 확인한다",
    REASON_RESCUED: "백오프 해가 대역폭 하한 아래여서 마무리로 되찾았다 (통과)",
    REASON_NA_NO_CROSSOVER: "교차가 없어 이 루프의 마진을 잴 수 없다 — 통과가 아니라"
                            " 판정 불가다. 루프 조성·게인 부호를 확인한다",
}
# 통과로 보는 사유 — 나머지는 자리 status가 infeasible이다 (= "자유 게인으로도 설계
# 목표를 못 맞춘 자리". classify의 structural_limit 입력이 바로 이것이다)
_PASSING = (REASON_OK, REASON_RESCUED)
# 그중에서도 **루프를 설계 목표대로 성형하지 못한** 사유. 넷 다 안정한 게인은
# 내지만(백오프 최선해·0 댐퍼도 게인이긴 하다) 그 자리의 설계가 성립하지 않은 것이다.
# 반면 capped·target_unreached는 물리 한계에 걸렸을 뿐 **작동하는 댐퍼를 냈다** —
# 합격선은 넘길 수 있으므로 성격이 다르다. 점 단위 status가 이 둘을 가르고,
# 분류기의 구조 한계 게이트도 이 목록을 본다 (classify가 import한다 — 두 모듈에
# 같은 목록이 손으로 두 번 적히면 갈린다)
SLOT_DESIGN_FAILED = (REASON_NO_STABLE_GAIN, REASON_DEGENERATE, REASON_MARGIN_FLOOR,
                      REASON_BANDWIDTH_COLLAPSE, REASON_NA_NO_CROSSOVER)


@dataclass(frozen=True)
class TuneTargets:
    pm_deg: float = 50.0  # 설계 목표 위상여유 — 합격 45°보다 여유 (히스테리시스)
    gm_db: float = 8.0  # 설계 목표 이득여유 — 합격 6 dB보다 여유
    zeta_sp: float = 0.7  # 단주기 감쇠 목표
    zeta_dr: float = 0.5  # 더치롤 감쇠 목표
    roll_lambda: float = 12.0  # 롤 수렴 모드 대역폭 목표 [rad/s]
    wc_ratio_att: float = 3.0  # 자세 교차 = 레이트 교차 ÷ 이 값 (successive closure 관례)
    ki_zero_frac: float = 0.125  # PI 영점 = ωc_att × 이 값 (한 옥타브×3 아래)
    backoff: float = 0.7  # 마진 미달 시 ωc_att 기하 축소비
    wc_att_floor_frac: float = 0.05  # ωc_att 탐색 바닥 = 초기 목표 × 이 값
    wc_att_ok_frac: float = 0.2  # 달성 대역폭 하한 — 이보다 낮은 ωc에서만 마진이
    # 통과하면 infeasible이다. 백오프는 대역폭을 버리면 거의 항상 마진을 만들 수
    # 있으므로(지연 위상 ∝ ω), 하한 없는 "통과"는 성능 붕괴를 조용히 합격으로 위장한다.

    def __post_init__(self):
        """값 검증 — 백오프 루프의 종료가 이 불변식에 걸려 있다.

        `_tune_att`의 `while wc >= floor_frac*wc0`는 backoff ≥ 1이면 영원히 돌고,
        floor_frac = 0이면 wc가 언더플로로 0이 된 뒤에도 참이다. 그 루프는
        on_progress를 부르지 않아 잡 취소로도 못 멈춘다 — 서버가 config로 이
        값들을 받으므로(routes/design.py) 검증이 없으면 워커를 영구 점유시킬 수 있다.
        """
        if not 0.0 < self.backoff < 1.0:
            raise ValueError(f"backoff는 (0, 1) 구간: {self.backoff} — 1 이상이면 백오프가 끝나지 않는다")
        if not 0.0 < self.wc_att_floor_frac < 1.0:
            raise ValueError(f"wc_att_floor_frac는 (0, 1) 구간: {self.wc_att_floor_frac}")
        if not self.wc_att_floor_frac <= self.wc_att_ok_frac:
            raise ValueError(
                f"wc_att_ok_frac({self.wc_att_ok_frac}) ≥ wc_att_floor_frac"
                f"({self.wc_att_floor_frac}) 필요 — 탐색 바닥보다 낮은 합격 하한은 무의미"
            )
        if self.wc_ratio_att <= 0.0:
            raise ValueError(f"wc_ratio_att는 양수: {self.wc_ratio_att}")
        if self.ki_zero_frac <= 0.0:
            raise ValueError(f"ki_zero_frac는 양수: {self.ki_zero_frac}")
        if not 0.0 < self.zeta_sp <= 1.0 or not 0.0 < self.zeta_dr <= 1.0:
            raise ValueError(f"감쇠 목표는 (0, 1]: zeta_sp={self.zeta_sp}, zeta_dr={self.zeta_dr}")
        if self.roll_lambda <= 0.0:
            raise ValueError(f"roll_lambda는 양수: {self.roll_lambda}")
        if self.pm_deg <= 0.0 or self.gm_db <= 0.0:
            raise ValueError(f"마진 목표는 양수: pm={self.pm_deg}, gm={self.gm_db}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TuneTargets":
        return cls(**{k: float(v) for k, v in d.items()})


# 레이트 자리 → (축, 지표 키, 목표 필드). 순서 = 닫는 순서(요 먼저 — closure.py).
_RATE_PLAN = (
    ("pitch", "lon", "zeta_sp", "zeta_sp"),
    ("yaw", "lat", "zeta_dr", "zeta_dr"),
    ("roll", "lat", "roll_lambda", "roll_lambda"),
)


def _metric(lm_axis, rate_gains, key, rate_filters=None):
    return axis_metrics(lm_axis, rate_gains, rate_filters)[key]


def _first_reach_bisect(f, k_lo, k_hi, target, n_scan=_SCAN_N,
                        expansions=_BRACKET_EXPANSIONS):
    """|k| 오름차순 스캔으로 f ≥ target 첫 도달 구간을 잡아 이분 — (k, 도달 여부, 확장 횟수).

    f가 뒤에서 비단조여도(모드 교환) 첫 도달 구간만 쓰므로 안전하다.

    브래킷 안에서 못 닿으면 상한을 ×_BRACKET_GROWTH로 넓혀 다시 본다. 초기 상한은
    **손설계 게인의 배수**라 "그 기체의 손튜닝이 얼마나 맞았나"에 달린 값이지 플랜트가
    낼 수 있는 한계가 아니다 — 넓히지 않으면 "플랜트가 못 한다"와 "브래킷이 좁다"가
    갈리지 않고 둘 다 목표 미달로만 보고된다. 데모 M0.2/h0에서 실측: 롤 λ는 상한
    0.8에서 8.65로 끊겼지만 |k|≈1.15면 목표 12에 닿는다(브래킷 탓). 같은 점의 요 ζ_dr은
    |k|≈1.55에서 0.477로 정점을 찍고 내려가 어떤 상한에서도 0.5에 못 닿는다(플랜트 탓).

    확장은 **새 구간만 이어 스캔한다** — 이미 촘촘히 본 구간을 성긴 격자로 다시 덮으면
    좁은 도달 구간을 놓칠 수 있다. 도달 실패는 이미 확인된 뒤이므로 되돌아볼 이유도 없다.
    끝내 못 닿으면 argmax를 낸다 (최선 달성 — 목표 미달 플래그·확장 횟수와 함께).
    """
    ks = np.linspace(k_lo, k_hi, n_scan)
    vals = [f(k) for k in ks]
    grown = 0
    while True:
        reach = [i for i, v in enumerate(vals) if v >= target]
        if reach:
            i = reach[0]
            if i == 0:
                return float(ks[0]), True, grown
            lo, hi = ks[i - 1], ks[i]
            for _ in range(_BISECT_N):
                mid = 0.5 * (lo + hi)
                if f(mid) >= target:
                    hi = mid
                else:
                    lo = mid
            return float(hi), True, grown
        if grown >= expansions:
            # **nan을 argmax에 넘기면 안 된다.** np.argmax는 nan을 최댓값으로 집는다.
            # 지표가 nan을 낼 수 있게 된 뒤(closure.lat_metrics — 롤 모드를 실근으로
            # 지목 못 하면 nan) 이 자리가 노출됐다: 데모 격자에서 스캔 117회 중 14회가
            # vals에 nan을 담고, 전부 |k| = 0 표본이다. 그대로 두면 "최선 달성값"이
            # **댐퍼를 끈 게인**이 되어 스케줄에 박힌다. 종전 0.0은 최솟값이라 절대
            # 안 뽑혔는데 nan은 항상 뽑힌다
            finite = np.where(np.isfinite(vals), vals, -np.inf)
            if not np.any(np.isfinite(finite)):
                # 전 표본이 못 잰 값 — 최선을 고를 근거가 없다. 설계값 방향의 0을
                # 낸다 (댐퍼를 끄는 것과 같지만, 사유가 미달로 흘러 보고된다)
                return float(k_lo), False, grown
            return float(ks[int(np.argmax(finite))]), False, grown
        grown += 1
        span = float(ks[-1]) - float(k_lo)
        ks_new = np.linspace(float(ks[-1]), float(k_lo) + span * _BRACKET_GROWTH,
                             n_scan)[1:]
        ks = np.concatenate([ks, ks_new])
        vals = vals + [f(k) for k in ks_new]


def _damper_loop_stable(lm_axis, group, x_rate, u_in, k, act_kw, zeta_act_min=0.10) -> bool:
    """레이트 댐퍼 폐루프(작동기 2차계+Padé 지연 포함)의 안정 판정.

    01 §4.2 실증 사고(작동기·지연 포함 시 PM 91°→−76.3° 불안정 전환)를 직접 막는
    가드다. 교차 주파수 캡은 틀린 가드였다 — |L|<1인 댐퍼는 교차가 없고(소이득
    안정), 교차가 있어도 다중 교차(장주기 봉우리) 탓에 SISO PM이 진짜 안정성과
    어긋난다. 판정: 폐루프 극 전부 안정 + 작동기 대역 부근(>0.3×wn_act) 진동극의
    ζ ≥ zeta_act_min (간신히 안정한 작동기 공진을 합격으로 두지 않는다).
    """
    import control

    from claw.analysis import pi_loop

    kw = dict(act_kw)
    # act_kw는 그룹별 dict를 나르고 pi_loop는 자리 하나를 받는다 — 이 자리 것만 꺼낸다
    filt = (kw.pop("rate_filters", None) or {}).get(group)
    loop = pi_loop(
        lm_axis, x_out=x_rate, u_in=u_in, kp=k, ki=0.0, sign=1.0,
        rate_filter=filt, **kw
    )
    # 물리 댐퍼는 u = +k·rate (안정화 부호는 k가 보유, closure.close_rates의
    # A+Bk·eᵀ와 동일) — 폐루프 특성식은 1 − L = 0이므로 양의 되먹임으로 닫는다
    poles = control.feedback(loop, 1, sign=1).poles()
    if np.any(poles.real >= -1e-9):
        return False
    wn_act = act_kw.get("actuator_wn") or 0.0
    if wn_act:
        for p in poles:
            wn = abs(p)
            if p.imag > 1e-9 and wn > 0.3 * wn_act and (-p.real / wn) < zeta_act_min:
                return False
    return True


def _cap_by_stability(lm_axis, group, x_rate, u_in, k, act_kw):
    """댐퍼 폐루프가 불안정해지면 |k|를 축소 — (k', 사유) 사유 ∈ {None,'capped','no_stable_gain'}.

    [0, |k|]를 먼저 **스캔**해 안정한 표본을 찾고, 그중 가장 큰 것(=목표에 가장 가까운
    것)을 상한 경계의 이분 하한으로 삼는다. 순수 이분으로 내려오면 "|k|가 커질수록
    불안정"이라는 **단조성을 전제**하게 되는데, 그 전제는 두 자리에서 깨진다:
    개루프가 이미 불안정한 플랜트(후방 CG·완화 정안정)와, 안정 구간이 [k_lo>0, k_hi]인
    조건부 안정이다. 둘 다 이분의 lo가 0에 머물러 **존재하는 안정 구간을 못 찾고
    댐퍼를 꺼 버린다**. 스캔은 그 구간을 직접 본다.

    끝내 안정한 표본이 하나도 없을 때만 no_stable_gain이다 — 그건 "안정 경계를
    찾았다"가 아니라 아무 댐핑도 없는 형상이므로 사유를 구분해 남긴다 (판정은 뒤에서
    ζ<0 → fail로 흐르지만, 로그가 "캡 적용"이라 말하면 안 된다).

    스캔은 초기 |k|가 불안정할 때만 돈다 (안정하면 첫 줄에서 반환).
    """
    if k == 0.0 or _damper_loop_stable(lm_axis, group, x_rate, u_in, k, act_kw):
        return k, None
    sign = math.copysign(1.0, k)
    mags = np.linspace(0.0, abs(k), _SCAN_N)
    stable_idx = [i for i in range(1, len(mags))
                  if _damper_loop_stable(lm_axis, group, x_rate, u_in, sign * mags[i], act_kw)]
    if not stable_idx:
        return 0.0, "no_stable_gain"
    # 마지막 표본은 |k| 자신이고 불안정으로 이미 확인됐다 — i+1은 항상 존재한다
    lo, hi = mags[stable_idx[-1]], mags[stable_idx[-1] + 1]
    for _ in range(_BISECT_N):
        mid = 0.5 * (lo + hi)
        if _damper_loop_stable(lm_axis, group, x_rate, u_in, sign * mid, act_kw):
            lo = mid
        else:
            hi = mid
    return sign * lo, "capped"


def _tune_rates(lon, lat, design, targets, act_kw) -> tuple:
    """레이트 3자리 순차 튜닝 — (gains, achieved, notes)."""
    axes = {"lon": lon, "lat": lat}
    gains: dict = {}
    achieved: dict = {}
    notes: list = []
    pending: list = []  # 2차 패스(최종 조성 재측정) 대기 목록
    for group, axis, metric_key, target_field in _RATE_PLAN:
        slot = f"{group}.k_rate"
        lm_axis = axes[axis]
        k_design = float(design[slot])
        if k_design == 0.0:
            gains[slot] = 0.0
            achieved[f"{group}_rate"] = {
                "kind": "damping" if metric_key != "roll_lambda" else "bandwidth",
                "target": getattr(targets, target_field), "reason": REASON_ZERO_DESIGN,
            }
            notes.append(f"{slot}: 설계값 0 — 방향 정보가 없어 튜닝하지 않는다")
            continue
        sign = math.copysign(1.0, k_design)
        target = getattr(targets, target_field)
        # 이 자리 **앞에서 이미 닫은** 레이트만 담긴다 (gains에 slot이 아직 없다).
        # 곧 A′로 접어 캡·교차 측정의 플랜트가 된다. 탐색도 이 프리픽스 조성에서
        # 하지만(successive closure 순서 그대로), **보고·판정은 아래 2차 패스에서
        # 최종 조성으로 다시 잰다** — 검증(schedmap)이 세 자리를 다 닫고 재기 때문이다.
        spec_rates = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
                      for g, _, _ in AXIS_SPECS[axis]["rates"]}
        # successive closure 조성 그대로 — 롤 댐퍼는 **요 댐퍼가 닫힌 뒤** 판정한다
        # (closure.py AXIS_SPECS "rates 순서 = 닫는 순서"). 생 lat에서 재면 요 댐퍼가
        # 없는 횡축을 보게 되는데, 그건 출하되지 않는 구성이다. 요 댐퍼의 r 되먹임이
        # **나선근을 직접 옮긴다** — 데모 M0.6/h1000 개루프 실근이 (−0.98, −0.0075)에서
        # 요를 닫으면 (−6.45, −2.24)로 간다. 생 lat에 롤 루프를 닫으면 그 느린 근이
        # 양으로 넘어가고(M0.3/h1000 손설계 게인 기준 +0.0142, 2배 시간 49 s) 캡이
        # 그걸 보고 |k|를 100분의 1로 깎거나(capped) 아예 0으로 끈다(no_stable_gain).
        # 실제로 M0.3/h1000에서 −0.592(λ 12 달성) → −0.0047(λ 0.76)이 됐다.
        lm_prior = close_rates(lm_axis, spec_rates, act_kw.get("rate_filters"))

        _rf = act_kw.get("rate_filters")

        def f(mag, _slot=slot, _lm=lm_axis, _sign=sign, _base=dict(spec_rates),
              _mk=metric_key, _rf=_rf):
            g = dict(_base)
            g[_slot] = _sign * mag
            return _metric(_lm, g, _mk, _rf)

        mag, reached, grown = _first_reach_bisect(f, 0.0, 4.0 * abs(k_design), target)
        k = sign * mag
        x_rate, u_in = next((x, u) for g, x, u in AXIS_SPECS[axis]["rates"] if g == group)
        k, capped = _cap_by_stability(lm_prior, group, x_rate, u_in, k, act_kw)
        gains[slot] = k
        achieved[f"{group}_rate"] = {
            "kind": "damping" if metric_key != "roll_lambda" else "bandwidth",
            "target": target,
            # ωc는 프리픽스 조성에서 잰다 — 검증(schedmap)도 `prior`로 같게 잰다
            "wc": rate_loop_crossover(lm_prior, group, x_rate, u_in, k, **act_kw),
            "capped": capped,
            "reached": reached,
            # 확장 횟수 — 목표 미달을 보고할 때 "브래킷 탓이 아니다"의 증거가 된다
            "bracket_growth": grown,
        }
        pending.append((group, axis, metric_key, target, reached, grown, capped, slot))

    _report_rates_on_final_composition(axes, gains, achieved, notes, pending,
                                       act_kw.get("rate_filters"))
    return gains, achieved, notes


def _report_rates_on_final_composition(axes, gains, achieved, notes, pending,
                                       rate_filters=None):
    """레이트 자리의 **보고값·사유**를 세 자리가 다 정해진 뒤 다시 잰다.

    탐색은 successive closure 순서대로 프리픽스 조성에서 한다 (요를 닫은 뒤 롤).
    그런데 그 순서 때문에 **요 차례에는 롤이 아직 열려 있고**, 검증(schedmap)은
    세 자리를 다 닫고 잰다. 프리픽스 값을 그대로 보고하면 튜너와 검증이 같은 자리에
    다른 수를 말한다 — 데모 실측:

        M0.2/h0/f40  ζ_dr  튜닝(롤 열림) 0.4766  /  검증(롤 닫힘) 0.7736
        M0.3/h0/f200 ζ_dr        0.5000        /        0.6233
        M0.6/h1000   ζ_dr        0.5000        /        0.5302

    차이가 판정을 뒤집는다: 0.4766은 목표 0.5 미달이라 `target_unreached`가 되고
    "설계값의 256배까지 넓혀도 미달 — 플랜트가 그 지표를 못 낸다"는 **단정**이
    붙는데, 출하되는 조성에서는 0.774다. 그 단정이 다시 구조 한계 에스컬레이션으로
    이어져 "플랜트·루프 구조를 검토하라"는 최종 안내가 나왔다.

    탐색 조성은 바꾸지 않는다 (그건 설계 방식이다). 바꾸는 것은 **무엇을 보고하고
    무엇으로 판정하는가**뿐이다.
    """
    for group, axis, metric_key, target, reached, grown, capped, slot in pending:
        lm_axis = axes[axis]
        final_all = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
                     for g, _, _ in AXIS_SPECS[axis]["rates"]}
        fm = axis_metrics(lm_axis, final_all, rate_filters)
        got = fm[metric_key]
        # 사유는 **왜 목표에 못 갔나**를 가른다. 캡이 걸렸어도 최종 조성에서 목표를
        # 넘겼으면 결함이 아니다 (안정 경계 아래에서 목표 달성 = 정상)
        # 허용오차: 탐색은 **프리픽스 조성**에서 target에 이분 수렴하는데 여기서는
        # **최종 조성**으로 다시 잰다. 조성이 다르므로 값이 목표선 양쪽에 임의로
        # 떨어진다 — 같은 조성에서 재던 시절의 1e-9는 동전 던지기가 된다 (실측:
        # 상대오차 6e-5 미달로 자리 status가 infeasible이 되는 자리가 12건 나왔다)
        if got >= target * (1.0 - _FINAL_METRIC_RTOL):
            reason = REASON_OK
        elif capped == "no_stable_gain":
            reason = REASON_NO_STABLE_GAIN
        elif capped == "capped":
            reason = REASON_CAPPED
        else:
            reason = REASON_TARGET_UNREACHED
        achieved[f"{group}_rate"].update({
            metric_key: got,
            "reason": reason,
            # λ의 |Re|가 지운 부호와, 그 실근이 롤 상태를 얼마나 담았나 —
            # 발산근이면 수치와 무관하게 실패이고, 참여도가 낮으면 애초에 롤
            # 대역폭을 잰 게 아니다 (판정은 criteria.judge_bandwidth 소관)
            "unstable": bool(fm.get("roll_unstable", False)),
            "participation": fm.get("roll_participation"),
        })
        if reason == REASON_TARGET_UNREACHED and not reached:
            # 브래킷 단정은 **탐색이 실제로 못 닿았을 때만** 낸다. reason은 최종
            # 조성에서 정하고 grown·reached는 탐색 조성의 양이라, 둘을 뭉치면
            # "브래킷을 한 번도 안 넓혔는데 넓혀도 미달"이라 적게 된다 (실측 12건)
            limit = 4.0 * _BRACKET_GROWTH ** grown
            notes.append(
                f"{slot}: 설계값의 {limit:g}배까지 넓혀도 목표 {target} 미달 (최종 조성"
                f" 달성 {got:.4g}) — 최선 달성값 채택. 브래킷이 아니라 이 플랜트가 그"
                " 지표를 못 낸다"
            )
        elif reason == REASON_TARGET_UNREACHED:
            # 탐색은 닿았는데 최종 조성에서 미달 — 뒤에 닫힌 댐퍼가 이 지표를 끌어내렸다.
            # 브래킷 이야기를 하면 거짓이다
            notes.append(
                f"{slot}: 탐색 조성에서는 목표 {target}에 닿았으나 최종 조성에서"
                f" {got:.4g} — 뒤에 닫힌 댐퍼가 끌어내렸다"
            )
        elif not reached:
            # 탐색 조성에서는 못 닿았는데 최종 조성에서는 닿았다 — 뒤에 닫히는
            # 댐퍼가 이 지표를 끌어올린 것이다. 조용히 넘기면 "왜 목표를 넘겼나"가
            # 안 남는다 (successive closure 순서의 부수 효과다)
            notes.append(
                f"{slot}: 탐색 조성(앞선 자리만 닫음)에서는 목표 {target} 미달이었으나"
                f" 최종 조성에서 {got:.4g} — 뒤에 닫힌 댐퍼가 끌어올렸다"
            )
        if capped == "capped":
            notes.append(f"{slot}: 댐퍼 안정 캡 적용 — 작동기·지연 포함 폐루프 안정 경계 아래로 축소")
        elif capped == "no_stable_gain":
            # 경계를 찾은 게 아니라 댐퍼를 끈 것이다 — 로그가 그렇게 말해야 한다
            notes.append(
                f"{slot}: 안정한 댐퍼 게인이 없다 — 어떤 |k|도 작동기·지연 포함 폐루프를"
                " 안정화하지 못해 0으로 두었다 (개루프 불안정 플랜트이거나 조건부 안정 구간)."
                " 이 축의 판정은 감쇠 미달로 흐르고 structural_limit 후보가 된다"
            )


def _bandwidth_ok(wc, wc0, targets) -> bool:
    """달성 교차가 대역폭 하한을 넘는가 — 백오프·구제·note가 **같은 식을 쓴다**.

    세 곳에 손으로 적혀 있던 판정이다. 게다가 두 곳이 서로 **다른 물리량**을 같은
    문턱에 댔다: 백오프는 설계 목표 교차(wc), 구제는 마무리 뒤의 실측 이득교차(wcp).
    게인이 바뀌었으니 후자가 맞지만, 식이 흩어져 있으면 한쪽만 고쳐도 아무도 모른다.
    """
    return bool(wc0) and math.isfinite(wc) and wc >= targets.wc_att_ok_frac * wc0


def _att_margin_verdict(m, targets) -> str:
    """자세 마진 수용 판정 — "ok" | "short" | "na". 백오프와 구제가 **같은 식을 쓴다**.

    nan과 inf를 가른다 (loop_margins의 규약: 교차가 없으면 nan, 무한 여유는 inf —
    "판정 불가를 무한 여유로 오인하지 않도록" 둘을 구분해 낸다). 종전 식은 그 구분을
    무너뜨렸다:

        gm_ok = not (isfinite(gm) and gm < target)

    `isfinite`가 False인 두 경우를 똑같이 통과로 쳤다 — inf(무한 여유, 통과가 맞다)와
    **nan(판정 불가, 통과가 아니다)**. PM은 반대로 nan이면 불통과였다. 한 판정식
    안에서 같은 값에 다른 규약을 쓴 셈이고, 그래서 "GM을 못 잰 자리"가 조용히
    설계 목표 달성으로 기록됐다.

    inf는 그대로 통과다 — `inf < target`이 False이므로 아래 비교가 그것을 처리한다.
    """
    pm, gm = float(m["pm_deg"]), float(m["gm_db"])
    if math.isnan(pm) or math.isnan(gm):
        return "na"  # 판정 불가 — 통과도 미달도 아니다
    if pm < targets.pm_deg or gm < targets.gm_db:
        return "short"
    return "ok"


def _tune_att(lm_axis, group, rate_gains, rate_wc, design, targets, act_kw) -> tuple:
    """자세 PI 루프쉐이핑 + 마진 검증 백오프 — (kp, ki, achieved, reason, evals)."""
    kp_design = float(design[f"{group}.kp"])
    sign = math.copysign(1.0, kp_design) if kp_design != 0.0 else 1.0
    # rate_wc = 0이면(댐퍼가 0으로 캡됐거나 교차를 못 찾음) 목표 교차가 **다른 물리량**
    # 으로 바뀐다 — 개루프 최속 진동 wn. 조용히 갈아타지 않고 플래그로 남긴다
    wc_fallback = not (rate_wc > 0)
    wc0 = (rate_wc if rate_wc > 0 else wn_reference(lm_axis)) / targets.wc_ratio_att
    wc = wc0
    evals = 0
    best = None
    last_verdict = "na"
    while wc >= targets.wc_att_floor_frac * wc0:
        zc = wc * targets.ki_zero_frac
        base = att_margin_loop(lm_axis, rate_gains, kp=1.0, ki=zc, **act_kw)
        mag = float(np.abs(base.frequency_response([wc]).magnitude).reshape(-1)[0])
        evals += 1
        if mag <= 0.0 or not math.isfinite(mag):
            wc *= targets.backoff
            continue
        kp = sign / mag
        ki = kp * zc
        m, orient = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
        evals += 1
        # wc0(초기 목표 교차)을 함께 낸다 — 이게 없으면 "대역폭이 얼마나 무너졌나"가
        # 결과 밖에서 계산 불가능하다. 판정식 wc ≥ wc_att_ok_frac·wc0의 분모다
        verdict = _att_margin_verdict(m, targets)
        best = (kp, ki, {**m, "orientation": orient, "wc_att": wc, "wc0": wc0,
                         "wc_fallback": wc_fallback, "target_pm_deg": targets.pm_deg,
                         "target_gm_db": targets.gm_db,
                         "target_wc_frac": targets.wc_att_ok_frac})
        if verdict == "ok":
            # 대역폭 하한 — 이 밑에서만 통과하는 것은 성능 붕괴다 (structural limit).
            # **마진은 통과했다** — 사유를 margin_floor와 뭉개면 안내가 거짓이 된다
            reason = (REASON_OK if _bandwidth_ok(wc, wc0, targets)
                      else REASON_BANDWIDTH_COLLAPSE)
            return kp, ki, best[2], reason, evals
        last_verdict = verdict
        wc *= targets.backoff
    if best is None:
        return 0.0, 0.0, {"wc0": wc0, "wc_fallback": wc_fallback}, REASON_DEGENERATE, evals
    kp, ki, ach = best
    # 백오프를 다 쓰고도 **판정 불가로만** 끝났으면 "마진 미달"이 아니다 —
    # 교차가 없어 잴 수 없었던 것이고, 그 둘을 뭉개면 안내가 엉뚱한 예산을 가리킨다
    return kp, ki, ach, (REASON_NA_NO_CROSSOVER if last_verdict == "na"
                         else REASON_MARGIN_FLOOR), evals


def tune_point(
    lm_full, design, *, targets=None,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    rate_filters=None, polish=False, max_evals=60,
) -> dict:
    """한 운영점의 SCAS 7자리 자동 튜닝 — {"gains", "achieved", "slots", "status", ...}.

    slots: {자리 이름: {"status", "reason", "target", "achieved"}} — **판정의 단위**.
    자리는 5개(pitch_rate·yaw_rate·roll_rate·pitch_att·roll_att)이고 이름은 검증
    쪽(openloop.GROUP_LOOPS·schedmap)과 같다. status는 "ok"(설계 목표 달성) |
    "infeasible"(미달) | "na"(잴 수 없음 — 설계값 0), reason은 그 사유다.

    status(점 단위): "ok" | "degraded"(설계 목표는 못 채웠으나 안정한 게인은 나왔다 —
    캡·플랜트 한계) | "infeasible"(그 자리를 설계 목표대로 성형하지 못한 자리가 있다 —
    댐퍼 꺼짐·기저 무의미·마진 바닥·대역폭 붕괴). **점 단위 판정을 자리 단위 결정에
    쓰면 안 된다** — 어느 자리가 실패했는지가 지워져서, 피치가 안 되는 점의 롤 실패까지
    "상위 설계 문제"로 넘어간다 (classify는 slots를 본다).
    예외로 던지지 않는다: infeasible도 결과다.
    """
    targets = targets if targets is not None else TuneTargets()
    act_kw = dict(
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
        # 그룹별 레이트 필터 스펙 — 법칙에 있는 필터(데모 요축 워시아웃)와
        # 완화 프로브가 가정하는 필터가 같은 통로로 흐른다
        rate_filters=dict(rate_filters or {}),
    )
    lon, lat = split_axes(lm_full)
    gains, achieved, notes = _tune_rates(lon, lat, design, targets, act_kw)

    evals = 0
    for lm_axis, group in ((lon, "pitch"), (lat, "roll")):
        spec = AXIS_SPECS[lm_axis.axis]
        rate_gains = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
                      for g, _, _ in spec["rates"]}
        rate_wc = achieved.get(f"{group}_rate", {}).get("wc", 0.0)
        kp, ki, ach, st, ev = _tune_att(
            lm_axis, group, rate_gains, rate_wc, design, targets, act_kw
        )
        evals += ev
        if st != REASON_OK and ach.get("wc0"):
            # 구제 마무리 — 백오프가 대역폭만 버리는 한 방향 탐색이라 놓친 해를 찾는다.
            # **실패한 자리에만** 돈다: 통과한 자리까지 벌점 무릎으로 밀면 전 운영점이
            # 마진 경계에 앉게 되고(작동기 공진에 가까워진다) 결정론적 결과도 흔들린다.
            # 통과시키지 못하면 채택하지 않는다 — 이 경로는 결과를 나쁘게 만들 수 없다.
            kp2, ki2, ach2, ev2 = _polish_att(
                lm_axis, group, rate_gains, kp, ki, targets, act_kw,
                max_evals=max(0, max_evals - evals), wc0=ach["wc0"],
                meta={k: ach[k] for k in _ATT_META if k in ach},
            )
            evals += ev2
            # 마무리가 **후퇴**했으면(게인이 그대로) 구제라 부를 수 없다 — wcp가 wc보다
            # 큰 루프에서는 아무것도 안 바꾸고 "구제됨"이 될 수 있다
            if ach2.get("polished") and _att_margin_verdict(ach2, targets) == "ok" \
                    and _bandwidth_ok(ach2["wc_att"], ach["wc0"], targets):
                kp, ki, ach, st = kp2, ki2, ach2, REASON_RESCUED
                notes.append(
                    f"{group}.kp/ki: 백오프 해가 대역폭 하한 미달이라 마무리로 구제 —"
                    f" 교차 {ach['wc_att'] / ach['wc0']:.3f}×목표 (하한"
                    f" {targets.wc_att_ok_frac:g})"
                )
        gains[f"{group}.kp"] = kp
        gains[f"{group}.ki"] = ki
        ach["reason"] = st
        achieved[f"{group}_att"] = ach
        if st not in _PASSING:
            # 사유별로 정확히 적는다. 종전에는 어느 경우든 "백오프 바닥까지 PM/GM 미달"
            # 이었는데, 대역폭 붕괴에서는 **마진을 통과한 뒤** 하한에 걸린 것이라
            # 문구가 사실과 달랐다 (실측 PM 103°·GM 9.6 dB)
            detail = ""
            if st == REASON_BANDWIDTH_COLLAPSE:
                detail = (f" — 교차 {ach['wc_att'] / ach['wc0']:.3f}×목표"
                          f" (하한 {targets.wc_att_ok_frac:g}), PM {ach['pm_deg']:.1f}°/"
                          f"GM {ach['gm_db']:.1f} dB는 통과")
            elif st == REASON_MARGIN_FLOOR:
                detail = (f" — 최선 PM {ach['pm_deg']:.1f}°/GM {ach['gm_db']:.1f} dB,"
                          f" 목표 {targets.pm_deg}°/{targets.gm_db} dB")
            notes.append(f"{group}.kp/ki: {REASON_TEXT[st]}{detail}")
        if polish and st in _PASSING and not ach.get("polished"):
            kp, ki, ach, ev = _polish_att(
                lm_axis, group, rate_gains, kp, ki, targets, act_kw,
                max_evals=max(0, max_evals - evals), wc0=ach.get("wc0"),
                meta={k: ach[k] for k in _ATT_META if k in ach},
            )
            evals += ev
            gains[f"{group}.kp"], gains[f"{group}.ki"] = kp, ki
            ach["reason"] = st
            achieved[f"{group}_att"] = ach
    slots = _slot_records(achieved)
    reasons = [s["reason"] for s in slots.values()]
    if any(r in SLOT_DESIGN_FAILED for r in reasons):
        status = "infeasible"
    elif any(s["status"] == "infeasible" for s in slots.values()):
        status = "degraded"
    else:
        status = "ok"
    return {"gains": gains, "achieved": achieved, "slots": slots, "status": status,
            "notes": notes, "evals": evals}


_METRIC_KEYS = ("zeta_sp", "zeta_dr", "roll_lambda", "pm_deg")


def _slot_records(achieved: dict) -> dict:
    """achieved → 자리별 판정 레코드 {status, reason, target, achieved}.

    자리 단위가 판정의 단위다. 종전에는 점 단위 status 하나뿐이라 "어느 자리가
    실패했나"가 지워졌고, 그 하나를 자리별 분류에 쓰는 바람에 피치가 안 되는 점의
    롤 실패까지 에스컬레이션으로 넘어갔다 (고칠 수 있는 것을 못 고치게 만든다).
    """
    out = {}
    for name, a in achieved.items():
        reason = a.get("reason", REASON_OK)
        if reason == REASON_ZERO_DESIGN:
            status = "na"  # 튜닝을 안 한 것이지 실패한 것이 아니다
        else:
            status = "ok" if reason in _PASSING else "infeasible"
        got = next((a[k] for k in _METRIC_KEYS if k in a), None)
        # 대표 지표 하나만 스칼라로 낸다 — 레이트 자리는 ζ/λ, 자세 자리는 PM.
        # 자세 자리의 GM·대역폭 목표는 achieved[name]에 나란히 있고, 요구 대비
        # 부족은 criteria.shortfall이 그 entry에서 지표별로 낸다
        out[name] = {"status": status, "reason": reason,
                     "target": a.get("target", a.get("target_pm_deg")), "achieved": got}
    return out


def _polish_att(lm_axis, group, rate_gains, kp0, ki0, targets, act_kw, max_evals,
                wc0=None, meta=None) -> tuple:
    """마무리 — Nelder-Mead(kp·ki 로그 배율), 목적 = −교차 대역폭 + 마진 벌점.

    백오프는 ωc를 버려서 마진을 사는 **한 방향** 탐색이라, 마진 여유가 남았는데도
    대역폭 하한 아래로 내려간 자리가 생긴다. (kp, ki)를 함께 흔들면 같은 마진에서
    대역폭을 되찾을 수 있다 — 데모 M0.7~0.75/h0의 여섯 자리가 그 경우였다
    (교차비 0.168 → 0.215~0.276, 하한 0.2 통과). 예산(max_evals)을 다 주면 조금 더
    올라가지만 백오프가 쓴 평가를 빼고 남는 몫이 실제 값이다.

    벌점 무릎에 **가드 밴드**를 둔다. 목적이 대역폭을 최대화하므로 최적점은 벌점이
    켜지는 지점에 정확히 붙는데, 그러면 수용 판정이 부동소수 잡음으로 뒤집힌다
    (실측: GM이 목표 8.0에서 8.00−ε으로 앉아 판정이 오락가락했다).
    """
    from scipy.optimize import minimize

    def cost(x):
        kp, ki = kp0 * math.exp(x[0]), ki0 * math.exp(x[1])
        m, _ = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
        pen = 0.0
        if math.isfinite(m["pm_deg"]):
            pen += 10.0 * max(0.0, targets.pm_deg + _POLISH_GUARD_PM - m["pm_deg"])
        if math.isfinite(m["gm_db"]):
            pen += 10.0 * max(0.0, targets.gm_db + _POLISH_GUARD_GM - m["gm_db"])
        bw = m["wcp"] if math.isfinite(m["wcp"]) else 0.0
        return -bw + pen

    def _ach(m, orient, extra=None):
        # 마무리 뒤의 교차는 설계 목표 wc가 아니라 **실제 이득교차**다 (wcp).
        # 백오프 해가 실어 둔 메타(목표선·wc_fallback)는 **물려받는다** — 안 물려받으면
        # 요구선이 가장 설명이 필요한 자리(구제된 자리)에서만 null이 된다
        out = {**(meta or {}), **m, "orientation": orient, "wc0": wc0,
               "wc_att": m["wcp"] if math.isfinite(m["wcp"]) else float("nan")}
        return {**out, **(extra or {})}

    if max_evals < 4:
        m, orient = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp0, ki0, **act_kw))
        return kp0, ki0, _ach(m, orient), 1
    # 초기 simplex를 **명시**한다. x0 = [0, 0]이면 scipy는 0 성분에 zdelt = 0.00025를
    # 써서 변 길이가 0.025%인 simplex를 만든다 — 이 함수가 켜져 있어도 게인이
    # 사실상 안 움직였다 (실측 Δlog kp = 0.00025 그대로 종료).
    res = minimize(cost, [0.0, 0.0], method="Nelder-Mead",
                   options={"maxfev": max_evals, "xatol": 1e-3, "fatol": 1e-3,
                            "initial_simplex": _POLISH_SIMPLEX})
    kp, ki = kp0 * math.exp(res.x[0]), ki0 * math.exp(res.x[1])
    m, orient = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
    if math.isfinite(m["pm_deg"]) and m["pm_deg"] >= targets.pm_deg:
        return kp, ki, _ach(m, orient, {"polished": True}), int(res.nfev) + 1
    m0, o0 = oriented_margins(att_margin_loop(lm_axis, rate_gains, kp0, ki0, **act_kw))
    # 후퇴 — 마무리가 악화시켰다. 시도했다는 사실을 남긴다 (종전엔 흔적이 없었다)
    return kp0, ki0, _ach(m0, o0, {"polished": False}), int(res.nfev) + 2


def tune_points(
    aircraft, points, lms, trims, *, design, targets=None,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    rate_filters=None, polish=False, max_evals=60, on_progress=None,
) -> dict:
    """앵커 전체 튜닝 → gain surface 샘플 — {"gains": {자리: {이름: 값}}, "results", "aborted"}.

    trimmable=False·미수렴 앵커는 건너뛰고 skipped로 보고한다 (조용한 누락 금지).
    """
    from claw.design.points import ROLE_ANCHOR

    targets = targets if targets is not None else TuneTargets()
    anchors = points.by_role(ROLE_ANCHOR)
    gains: dict = {}
    results: dict = {}
    skipped: list = []
    aborted = None
    total = len(anchors)
    for done, pt in enumerate(anchors, start=1):
        name = pt.case.name
        tr = trims.get(name)
        if tr is None or not tr.converged or pt.trimmable is False:
            skipped.append(name)
        else:
            out = tune_point(
                lms.get(aircraft, tr), design, targets=targets,
                actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
                delay_s=delay_s, pade_order=pade_order, rate_filters=rate_filters,
                polish=polish, max_evals=max_evals,
            )
            results[name] = out
            for slot, v in out["gains"].items():
                gains.setdefault(slot, {})[name] = v
        if on_progress is not None and on_progress(done, total, f"tune {name}"):
            aborted = "cancelled"
            break
    return {
        "gains": gains, "results": results, "skipped": skipped,
        "aborted": aborted, "targets": targets.to_dict(),
    }
