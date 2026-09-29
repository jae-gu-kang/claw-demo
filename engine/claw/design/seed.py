"""초기 게인 빠른 탐색 — 게인이 없는(또는 다시 잡을) 기체에 SCAS·자동조종 게인의 부호·크기를 채운다
(05 §10 · 02 §5.6).

자동 설계(tune_point)는 설계값에서 **부호와 탐색 브래킷**만 읽는다(05 §7). 게인이 비어 있는 새 기체는 그
출발점이 없어 튜닝 자체가 성립하지 않는다(seed_required). 여기서 출발점을 기체에서 **재서** 만든다:

1. 앵커 — 요구영역의 기본 격자(design.grid.region_grid — 연료는 한 층: 요구 연료 범위의 가운데에 가장 가까운 기본
   격자 연료, 이관 9단계)에서 채택한 점(조건 판정 — 트림 탭과 같은 판정)을 q̄ 순으로 세우고 중앙·최저·최고를 쓴다.
   요구영역이 없는 기체만 옛 설계 격자(coarse_grid — 설계 기본 고도를 운용 고도로 거름 × fuel_max·fuel_frac)다. 앵커마다 튜닝한 게인을 스케줄 규칙(q̄ 역비)으로 설계 마하 값으로 되돌려 자리마다
   중앙값을 쓴다.
2. 부호 — 선형 모델 B의 조종효율에서: 레이트 댐퍼 k = −sign(B[ṙate, u])(u = +k·rate가 감쇠를 더한다),
   자세 kp = +sign(B). 레이트는 ±로 조금 닫아 지표가 실제로 좋아지는 쪽인지 확인한다. 앵커끼리 부호가
   다르면(조종 반전·효율 소멸) 그 자리를 실패시킨다 — 스케줄 표 하나로 부호를 뒤집을 수 없다.
3. 크기 — k_ref = wn_ref/|B|의 0.01~100배를 로그 17점으로 훑어 목표에 처음 닿는 크기의 절반을 시드로
   삼고(튜너의 첫 브래킷 4|k| 안) tune_point이 다듬는다. 자세 PI 크기는 튜너가 교차 주파수에서 정한다.
4. 확인 — 합친 게인으로 스케줄 표를 만들어 앵커마다 schedmap 검증을 돌린다. **채택 조건**:
   - 자리마다 설계 실패 사유가 아닌 앵커가 min(2, 앵커 수) 이상 — 한 점 값으로 전 엔벨로프 스케줄을 세우지 않는다
   - 어느 앵커에도 부호 방향 결함이 없다
   - 모든 앵커에서 fail인 루프가 없다 — 한두 앵커의 fail은 경고로 싣는다(시드는 자동 설계의 출발점이고, 예제
     기체의 손설계도 저속 앵커의 롤 자세 루프는 fail이다)
   예제 기체(요 워시아웃이 켜진 조성)는 롤 댐퍼가 한 앵커에서만 튜닝돼 채택되지 않는다 — 다시 탐색이 멀쩡한
   손설계를 덮는 것을 이 조건이 막는다.
5. 자동조종 — 선형 모델이 없어 시간척도 분리 휴리스틱이다(바깥 루프 대역폭 = 두 자세 교차 중 느린 것 ÷
   SEPARATION — 헤딩·고도·속도가 한 시간척도를 쓴다. 피치 교차만 쓰면 저속 앵커에서 고도 루프가 0.7 rad/s로
   빨라진다). 자세 교차는 중앙 앵커의 튜너 목표 교차이되, 그 목표가 루프의 실측 이득교차가 아니면(장주기
   공진이 만든 가짜 레이트 교차 — _inner_crossovers) 목표가 루프 교차인 다른 앵커들의 중앙값을 쓴다.
   부호는 SCAS가 θ·φ를 추종하면 기체와 무관하다. 명령필터 시정수·자세 한계·선회 보상은 유도식이 없어
   문서 값(있으면) 또는 레지스트리 기본값이고, 출처에 자리마다 그렇게 적는다 — 조용히 물려주지 않는다.
   sim_check=True면 중앙 앵커 한 케이스로 평가(evaluate depth="full")를 돌려 결과를 싣는다(채택 판정에는
   쓰지 않는다 — 선형 확인만 판정이다).

문서에 쓰지 않는다 — 결과 dict를 돌려주고 저장(새 리비전)은 호출자(서버 잡)가 한다. 출처(provenance)는
지문 밖이다(fingerprint.FP_EXCLUDED).
"""

import copy
import math
import statistics
import time

import numpy as np

from claw.analysis.envelope import DEFAULT_SCHEDULE_ALTS
from claw.common.constants import G0
from claw.design.closure import AXIS_SPECS, axis_metrics, wn_reference
from claw.design.criteria import MarginCriteria
from claw.design.grid import coarse_grid, region_grid
from claw.design.schedmap import scheduled_margin_point
from claw.design.tune import (
    _RATE_PLAN,
    REASON_SIGN_MISMATCH,
    SLOT_DESIGN_FAILED,
    TuneTargets,
    failed_gain_slots,
    tune_point,
)
from claw.design.tune import REASON_TEXT as TUNE_REASON_TEXT
from claw.env import isa_atmosphere
from claw.opspace.region import region_of
from claw.opspace.verdict import VerdictContext
from claw.trim import linearize, split_axes

SEED_SOURCE = "quick_seed"
SEPARATION = 5.0  # [기본값] 바깥 루프(헤딩·고도·속도) 대역폭 = 느린 자세 루프 교차 ÷ 이 값
ZETA_ALT = 0.8  # [기본값] 고도 루프 감쇠
ZETA_SPEED = 0.7  # [기본값] 속도 루프 감쇠
# [기본값] V·|k_hdot| — 승강률 되먹임의 무차원 크기. θ가 명령을 곧바로 따른다고 보면 ḣ = V·θ라 고도 루프 특성식이
# (1 + r)·s² + V·kp·s + V·ki = 0이다. r은 같은 대역폭·감쇠를 kp·ki를 몇 배로 키워 얻을지(오차 되먹임 대 승강률
# 되먹임의 몫)를 정한다 — 식이 주지 않는 선택이라 기본값으로 적는다
HDOT_RATIO = 1.5
# 튜너의 목표 교차(wc_att)와 루프의 실측 이득교차(wcp)가 같은 수로 보는 허용 — 루프가 목표에서 한 번만 1을
# 지나면 둘은 같은 교차를 두 방법으로 잰 것이라 반올림 차이뿐이다(설계 격자 n_mach 7 × 연료 3벌 — 예제 69점·
# 구 기체 49점·S1 63점의 자세 루프 362개 중 목표가 루프 교차인 것의 실측 상대차 ≤ 4.3e-15). 목표가 루프의 교차가
# 아니면 수 배 어긋난다(S1 7개 루프, 실측 wcp/wc_att ×2.9~×5.4 — 예제·구 기체는 0개) — 그 사이 어디든 가른다
WC_MATCH_RTOL = 1e-3
SWEEP = tuple(float(f) for f in np.logspace(-2.0, 2.0, 17))  # k_ref 배수
DIRECTION_PROBE = 0.1  # k_ref 배 — 부호 확인용 작은 닫기
FUEL_FRAC = 0.5  # [기본값] 앵커 연료 = fuel_max × 이 값
DEFAULT_CAP = 2.0  # [기본값] 새로 만드는 스케줄의 배율 상한
MACH_STEP = 0.05  # [기본값] 새로 만드는 스케줄의 마하 격자 간격
# 새로 만드는 스케줄이 싣는 자리 — 튜너가 잡는 7자리. 조종효율 ∝ q̄라 같은 q̄ 역비 규칙이 모두에 선다
SEED_SCHEDULED = ("pitch.kp", "pitch.ki", "pitch.k_rate", "roll.kp", "roll.ki", "roll.k_rate", "yaw.k_rate")

REASON_SEED_NO_GRID = "seed_no_grid"
REASON_SEED_NO_ANCHOR = "seed_no_anchor"
REASON_SEED_SIGN_AMBIGUOUS = "seed_sign_ambiguous"
REASON_SEED_SIGN_VARIES = "seed_sign_varies"
REASON_SEED_CANCELLED = "seed_cancelled"
REASON_SEED_THIN_ANCHORS = "seed_thin_anchors"
REASON_SEED_VERIFY_FAILED = "seed_verify_failed"
REASON_TEXT = {
    REASON_SEED_NO_GRID: "공력 DB 마하 유효 범위(aero.db_ranges.mach)가 없어 설계 격자를 못 만든다 — 범위를 넣는다",
    REASON_SEED_NO_ANCHOR: "설계 격자에 엔벨로프 안(트림 수렴·포화 여유·α 여유) 점이 없다 — 트림 탭에서 성립 영역을 먼저"
                           " 확인한다",
    REASON_SEED_SIGN_AMBIGUOUS: "조종효율(B)이 0이거나, 그 부호로 닫아도 지표가 좋아지지 않는다 — 조종 미계수 부호·크기를"
                                " 확인한다",
    REASON_SEED_SIGN_VARIES: "앵커끼리 조종효율 부호가 다르다(조종 반전·효율 소멸) — 스케줄 표 하나로 부호를 뒤집을 수 없다",
    REASON_SEED_CANCELLED: "취소됐다",
    REASON_SEED_THIN_ANCHORS: "이 자리를 설계 실패 없이 튜닝한 앵커가 둘 미만이다 — 한 점 값으로 전 엔벨로프 스케줄을"
                              " 세우지 않는다(게인이 있는 기체면 지금 게인을 덮지 않는다)",
    REASON_SEED_VERIFY_FAILED: "합친 스케줄의 검증에서 모든 앵커가 fail인 루프가 있다 — 채택하지 않는다",
}

_RATE_B = {"pitch": ("lon", "q", "de"), "yaw": ("lat", "r", "dr"), "roll": ("lat", "p", "da")}
_ATT_B = {"pitch": ("lon", "q", "de"), "roll": ("lat", "p", "da")}
_GAIN_SLOT = {"pitch.k_rate": "pitch_rate", "yaw.k_rate": "yaw_rate", "roll.k_rate": "roll_rate",
              "pitch.kp": "pitch_att", "pitch.ki": "pitch_att", "roll.kp": "roll_att", "roll.ki": "roll_att"}
_SIGN_GROUP = {"pitch.k_rate": "pitch_rate", "yaw.k_rate": "yaw_rate", "roll.k_rate": "roll_rate",
               "pitch.kp": "pitch_att", "pitch.ki": "pitch_att", "roll.kp": "roll_att", "roll.ki": "roll_att"}


def reason_text(reason) -> str | None:
    """시드 사유와 튜너 사유를 한 표로 — 자리 실패는 튜너 사유(seed_required·no_stable_gain …)로도 온다."""
    return REASON_TEXT.get(reason) or TUNE_REASON_TEXT.get(reason)


def _b(axes, axis, x, u) -> float:
    m = axes[axis]
    return float(m.B[m.x_names.index(x), m.u_names.index(u)])


def _score(v) -> float:
    return v if v is not None and math.isfinite(v) else -math.inf


def _rate_seeds(axes, targets, rate_filters) -> dict:
    """앵커 하나의 레이트 3자리 → {"pitch_rate": {b, sign, k_ref, seed, reached, reason}, …} (닫는 순서대로)."""
    out = {}
    closed = {}
    for group, axis, key, tfield in _RATE_PLAN:
        slot = f"{group}.k_rate"
        _, x, u = _RATE_B[group]
        m = axes[axis]
        b = _b(axes, axis, x, u)
        rec = {"b": b, "sign": 0.0, "k_ref": None, "seed": 0.0, "reached": False, "reason": None}
        out[f"{group}_rate"] = rec
        if b == 0.0 or not math.isfinite(b):
            rec["reason"] = REASON_SEED_SIGN_AMBIGUOUS
            continue
        sign = -math.copysign(1.0, b)
        k_ref = wn_reference(m) / abs(b)
        base = {f"{g}.k_rate": closed.get(f"{g}.k_rate", 0.0) for g, _, _ in AXIS_SPECS[axis]["rates"]}

        def metric(k, _base=base, _slot=slot, _m=m, _key=key):
            g = dict(_base)
            g[_slot] = k
            try:
                return _score(axis_metrics(_m, g, rate_filters)[_key])
            except (ValueError, np.linalg.LinAlgError):
                return -math.inf

        up, down = metric(sign * DIRECTION_PROBE * k_ref), metric(-sign * DIRECTION_PROBE * k_ref)
        if not up > down:
            # 작은 닫기에서 못 가르면(판정할 모드가 아직 없다 — 롤 λ가 nan) 기준 크기에서 한 번 더
            up, down = metric(sign * k_ref), metric(-sign * k_ref)
        rec.update(sign=sign, k_ref=k_ref)
        if not up > down:
            rec["reason"] = REASON_SEED_SIGN_AMBIGUOUS
            continue
        target = getattr(targets, tfield)
        reach = next((k_ref * f for f in SWEEP if metric(sign * k_ref * f) >= target), None)
        rec["seed"] = sign * (0.5 * reach if reach is not None else k_ref)
        rec["reached"] = reach is not None
        closed[slot] = rec["seed"]
    return out


def _qbar(case) -> float:
    atm = isa_atmosphere(case.alt)
    v = case.mach * atm.a
    return 0.5 * atm.rho * v * v


def _factor(schedule, name, mach) -> float:
    """스케줄 표가 이 마하에서 설계값에 곱하는 배율 — 표와 같게 마하 격자에서 보간(clip)한다."""
    if schedule is None or name not in schedule["scheduled"]:
        return 1.0
    grid = np.asarray(schedule["mach_grid"], dtype=float)
    cap = schedule["caps"]["by_group"].get(name.split(".", 1)[0], schedule["caps"]["default"])
    return float(np.interp(mach, grid, np.minimum((schedule["m_design"] / grid) ** 2, cap)))


def _new_schedule(machs, m_design) -> dict:
    lo = max(MACH_STEP, math.floor(min(machs) / MACH_STEP) * MACH_STEP)
    hi = max(lo + MACH_STEP, math.ceil(max(machs) / MACH_STEP) * MACH_STEP)
    n = int(round((hi - lo) / MACH_STEP)) + 1
    return {"rule": "qbar_inverse", "m_design": round(float(m_design), 4),
            "mach_grid": [round(lo + i * MACH_STEP, 4) for i in range(n)],
            "caps": {"default": DEFAULT_CAP, "by_group": {}}, "scheduled": list(SEED_SCHEDULED)}


def _clean(v):
    """출처·결과를 JSON에 싣게 — 비유한 수는 null, numpy 수는 float. 저장소가 NaN 문서를 거부한다."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (bool, str)) or v is None:
        return v
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    return v


def _loop_crossover(ach) -> tuple:
    """자세 자리 achieved 하나 → (목표 교차가 루프의 실측 이득교차인가, 실측 이득교차 | None).

    설계 실패 사유인 자리(성형하지 못한 루프)·교차를 못 잰 자리는 (False, None)이다."""
    if not ach or ach.get("reason") in SLOT_DESIGN_FAILED:
        return False, None
    wc, wcp = ach.get("wc_att"), ach.get("wcp")
    if wcp is None or not math.isfinite(wcp) or wcp <= 0.0:
        return False, None
    return bool(wc is not None and math.isfinite(wc) and abs(wcp - wc) <= WC_MATCH_RTOL * wc), wcp


def _inner_crossovers(design_point, others=()) -> tuple:
    """자동조종 시간척도의 기준 자세 교차 — ({"pitch": ω | None, "roll": …}, 메모 목록).

    design_point·others는 튜너 achieved 모양({"pitch_att": {...}, "roll_att": {...}} — tune_point의 achieved·
    산출 근거의 attitude)이다. design_point는 자동조종을 설계하는 점(빠른 탐색의 중앙 앵커·산출 근거의 한 점),
    others는 나머지 앵커다.

    튜너의 wc_att는 **설계 목표** 교차다 — |PI·G·Act·지연| = 1을 그 주파수에 맞춘다. 루프가 거기서 한 번만 1을
    지나면 그것이 실측 이득교차(wcp)이고 곧 자세 대역폭이다. 그런데 목표는 레이트 루프 교차 ÷ wc_ratio_att이고,
    레이트 댐퍼가 약하면(개루프 단주기 ζ가 이미 목표 근처) 레이트 루프 |L|의 최댓값이 단주기가 아니라 장주기
    공진에 선다 — 그 봉우리가 1을 살짝 넘으면 레이트 교차가 장주기 주파수로 잡힌다. S1 중앙 앵커(M0.1305/해면/
    연료 25)에서 튜닝한 피치 댐퍼 0.1984가 장주기(0.28 rad/s, ζ 0.16) 봉우리를 1.008로 올려 레이트 교차 0.29 →
    자세 목표 0.097 rad/s였다. 2 % 작은 0.1937(산출 근거 닫힌꼴)은 봉우리가 0.984라 교차가 없고 목표가 단주기
    기준(wn/3 = 1.03)이다 — 댐퍼 게인 2 %에 목표가 10배 뛴다. 그 목표로 성형한 루프는 0.0085·0.097·0.514
    rad/s에서 1을 세 번 지나고 목표 교차의 위상여유는 −148°다 — 목표 교차는 대역폭이 아니다. 그 수로 바깥
    루프를 잡으면 ω = 0.019 rad/s라 속도 kp 식이 음수가 되어 kp_spd = 0 · 헤딩 kp 0.088이었다(S1 빠른 탐색
    실측 — 웹 기본 미션에서 발사 8 s 만에 접지·추락).

    자리마다: ① 설계점의 목표 교차가 루프 교차면 그것 ② 아니면(설계 실패 포함) 목표 교차가 루프 교차인 다른
    앵커들의 중앙값 — 자세 대역폭은 마하·고도·연료를 따라 이어지는 양이라 이웃 앵커가 그 점의 값을 말한다(S1:
    같은 고도·연료의 이웃 격자점 0.93·1.13, 다른 두 앵커 0.73·1.61 → 1.17) ③ 그것도 없으면 설계점 루프의 실측
    이득교차 — 그 루프가 실제로 내는 대역폭이다. 설계 실패 사유인 자리는 ①·③에서 뺀다(성형하지 못한 루프의
    교차는 대역폭이 아니다 — 종전 규칙). 예제 기체는 세 앵커 모두 ①이라 종전 값 그대로다."""
    wc, notes = {}, []
    for group in ("pitch", "roll"):
        slot = f"{group}_att"
        own = design_point.get(slot) or {}
        matched, measured = _loop_crossover(own)
        if matched:
            wc[group] = own["wc_att"]
            continue
        if own.get("reason") in SLOT_DESIGN_FAILED:
            why = f"설계점 {group} 자세 자리가 설계 실패({own.get('reason')})라"
        elif measured is None:
            why = f"설계점 {group} 자세 루프의 이득교차를 잴 수 없어"
        else:
            why = (f"설계점 {group} 자세의 목표 교차 {own['wc_att']:.3g} rad/s가 루프의 실측 이득교차"
                   f"({measured:.3g} rad/s)가 아니라(루프가 1을 여러 번 지난다)")
        usable = [a[slot]["wc_att"] for a in others if _loop_crossover(a.get(slot))[0]]
        if usable:
            wc[group] = statistics.median(usable)
            notes.append(f"{why} 목표 교차가 루프 교차인 다른 앵커 {len(usable)}곳의 중앙값"
                         f" {wc[group]:.3g} rad/s로 바깥 루프 대역폭을 잡았다")
        elif measured is not None:
            wc[group] = measured
            notes.append(f"{why} 루프의 실측 이득교차 {measured:.3g} rad/s로 바깥 루프 대역폭을 잡았다")
        else:
            wc[group] = None  # 종전 규칙 — _autopilot이 남은 자리로 잡고 메모를 단다
    return wc, notes


def _autopilot(built, center, lon, wc, act_existing):
    """자동조종 18자리 — (값, 자리별 출처, 메모). wc = {"pitch": 자세 교차, "roll": …} (없으면 None —
    _inner_crossovers가 고른다)."""
    from claw.params.registry import REGISTRY

    defs = {d.name: d.default for d in REGISTRY.param_defs("fcl", "Autopilot")}
    values, source = {}, {}
    for name, default in defs.items():
        if act_existing is not None and name in act_existing:
            values[name], source[name] = act_existing[name], "document"
        else:
            values[name], source[name] = default, "registry_default"
    notes = []
    atm = isa_atmosphere(center.case.alt)
    v = center.case.mach * atm.a
    inner = [w for w in (wc.get("pitch"), wc.get("roll")) if w]
    if len(inner) < 2:
        notes.append("자세 교차가 "
                     + ("하나뿐이라 그것으로" if inner else "없어 바깥 루프 게인을 유도하지 못했다 — 출처의 값을 그대로 둔다")
                     + (" 바깥 루프 대역폭을 잡았다" if inner else ""))
    if inner:
        w_a = min(inner) / SEPARATION
        values.update(kp_hdg=w_a * v / G0, ki_hdg=0.0)  # ψ̇ = (g/V)·φ, φ = kp·e_ψ → 극 kp·g/V
        source.update(kp_hdg="heuristic", ki_hdg="heuristic")
        d = 1.0 + HDOT_RATIO
        values.update(kp_alt=2.0 * ZETA_ALT * w_a * d / v, ki_alt=w_a * w_a * d / v, k_hdot=-HDOT_RATIO / v,
                      kp_vs=HDOT_RATIO / v, ki_vs=w_a * d / v)  # 승강률 루프 극 V·ki/(1 + V·kp) = ω
        source.update(kp_alt="heuristic", ki_alt="heuristic", k_hdot="heuristic", kp_vs="heuristic",
                      ki_vs="heuristic")
        iu = lon.x_names.index("u")
        b = float(lon.B[iu, lon.u_names.index("thr")])
        a_uu = float(lon.A[iu, iu])
        if b > 0.0 and math.isfinite(b):
            # u̇ ≈ A_uu·u + b·thr, thr = kp·e + ki·∫e → s² + (b·kp − A_uu)·s + b·ki
            kp_spd = (2.0 * ZETA_SPEED * w_a + a_uu) / b
            values.update(kp_spd=max(0.0, kp_spd), ki_spd=w_a * w_a / b)
            source.update(kp_spd="heuristic", ki_spd="heuristic")
            if kp_spd < 0.0:
                # 0으로 깎는 것은 조용히 하지 않는다 — S1의 kp_spd 0은 이 자리에서 아무 말 없이 나왔다
                notes.append(f"속도 kp 식 (2ζω + A_uu)/b = {kp_spd:.3g}가 음수라 0으로 두었다 — 바깥 루프 대역폭"
                             f" ω = {w_a:.3g} rad/s가 속도 자연 감쇠 −A_uu = {-a_uu:.3g} 1/s보다 느려 적분만 남는다")
        else:
            notes.append(f"스로틀 효율 B[u,thr]={b:.4g}가 양이 아니어서 속도 게인을 유도하지 못했다")
    n_lim = built.doc["structural"]["n_limit_pos"]
    if n_lim > 1.0 and 1.0 / math.cos(values["phi_max"]) > n_lim:
        values["phi_max"] = math.acos(1.0 / n_lim)  # 정상 선회 하중배수 1/cosφ가 제한 하중을 넘지 않게
        source["phi_max"] = "structural_limit"
    return values, source, notes


LEGACY_N_MACH = 5  # 요구영역 없는 기체의 옛 격자 마하 점 수


def seed_fuel_layer(region) -> float:
    """요구영역에서 앵커를 둘 연료 층 — 기본 격자 연료 중 요구 연료 범위의 가운데에 가장 가까운 것(같으면 작은 쪽)."""
    mid = 0.5 * (region.fuel[0] + region.fuel[1])
    return float(min(region.grid["fuels"], key=lambda f: (abs(float(f) - mid), float(f))))


def quick_seed(built, *, targets=None, fuel_frac=FUEL_FRAC, n_mach=None, delay_s=0.035, pade_order=2,
               sim_check=False, on_progress=None) -> dict:
    """BuiltProfile → {"ok", "reason", "reason_text", "design", "schedule", "schedule_created", "anchors",
    "slots", "verification", "failed_loops", "warnings", "autopilot_notes", "sim_check", "grid", "elapsed_s"}.

    grid는 **실제로 쓴 격자 조건**이다(05 §11.13 13단계 — 화면 기본값·문서 명세로 돈 조건도 결과에 남긴다): source
    ("region_base_grid" | "coarse_grid"), n_mach, alts, fuels [kg], points(격자 점 수), trimmable(채택 점 수). 격자를
    세우기 전에 실패하면 None.
    design은 law.design 모양(provenance 포함)이고 schedule은 문서에 스케줄이 없을 때만 새로 만든 것(있으면 None —
    문서의 것을 쓴다). n_mach None = 요구영역 기본 격자 명세(없는 기체는 LEGACY_N_MACH). fuel_frac은 요구영역 없는 기체의
    옛 격자에만 쓴다 — 요구영역이 있으면 연료 층은 seed_fuel_layer다. ok가 False여도 design은 싣는다(화면이 무엇이 안 됐는지 보인다) — 저장은 호출자가 ok일 때만."""
    t0 = time.perf_counter()
    targets = targets if targets is not None else TuneTargets()
    doc = built.doc
    law = doc["law"]
    existing = law["design"]
    act = built.actuator_params()
    act_kw = {"actuator_wn": act.get("wn"), "actuator_zeta": act.get("zeta"),
              "delay_s": delay_s, "pade_order": pade_order}
    rate_filters = built.rate_filters() if existing is not None else {}

    grid_echo = None

    def fail(reason, **extra):
        return _clean({"ok": False, "reason": reason, "reason_text": reason_text(reason), "design": None,
                       "schedule": None, "schedule_created": False, "anchors": [], "slots": {},
                       "verification": {}, "failed_loops": [], "warnings": [], "autopilot_notes": [],
                       "sim_check": None, "grid": grid_echo,
                       "elapsed_s": time.perf_counter() - t0, **extra})

    ac = built.aircraft()
    ctx = VerdictContext.from_profile(built)
    region = region_of(doc)
    if region is not None:
        # 요구영역의 기본 격자에서 — 요구를 실속 하한·DB 상한으로 깎지 않는다(05 §11.2). 모델 부족 점은 트림 전 제외
        g_fuels = (seed_fuel_layer(region),)
        g_n = int(region.grid["n_mach"]) if n_mach is None else int(n_mach)
        grid_echo = {"source": "region_base_grid", "n_mach": g_n,
                     "alts": sorted(float(a) for a in region.grid["alts"]), "fuels": [float(f) for f in g_fuels]}
        grid = region_grid(ac, region, ctx.model, ctx=ctx, n_mach=n_mach, fuels=g_fuels,
                           fingerprint=built.plant_fingerprint, on_progress=on_progress)
    else:
        db = built.db_ranges()
        if "mach" not in db:
            return fail(REASON_SEED_NO_GRID)
        # 요구영역 없는 기체의 옛 격자 — 고도는 설계 기본 고도 그대로(스키마 v3에는 운용 고도 절이 없다)
        g_n = LEGACY_N_MACH if n_mach is None else int(n_mach)
        g_alts = [float(a) for a in DEFAULT_SCHEDULE_ALTS]
        g_fuels = (doc["mass"]["fuel_max"] * fuel_frac,)
        grid_echo = {"source": "coarse_grid", "n_mach": g_n, "alts": g_alts, "fuels": [float(f) for f in g_fuels]}
        grid = coarse_grid(ac, built.stall_table(), built.structural_limits(), db, ctx=ctx, n_mach=g_n,
                           alts=g_alts, fuels=g_fuels, fingerprint=built.plant_fingerprint,
                           on_progress=on_progress)
    grid_echo.update(points=len(grid["points"]), trimmable=sum(1 for pt in grid["points"] if pt.trimmable))
    if grid["aborted"]:
        return fail(REASON_SEED_CANCELLED)
    inside = [pt for pt in grid["points"] if pt.trimmable]
    if not inside:
        return fail(REASON_SEED_NO_ANCHOR, grid_points=len(grid["points"]))
    order = sorted(inside, key=lambda pt: _qbar(pt.case))
    picks = []
    for pt in (order[len(order) // 2], order[0], order[-1]):
        if pt not in picks:
            picks.append(pt)

    schedule = law["schedule"]
    created = schedule is None
    if created:
        schedule = _new_schedule([pt.case.mach for pt in inside], picks[0].case.mach)

    anchors = []
    for i, pt in enumerate(picks):
        if on_progress is not None and on_progress(i, len(picks), f"시드 앵커 {pt.case.name}"):
            return fail(REASON_SEED_CANCELLED)
        tr = grid["trims"][pt.case.name]
        lm = linearize(ac, tr)
        lon, lat = split_axes(lm)
        axes = {"lon": lon, "lat": lat}
        rates = _rate_seeds(axes, targets, rate_filters)
        att = {}
        for group, (axis, x, u) in _ATT_B.items():
            b = _b(axes, axis, x, u)
            sign = math.copysign(1.0, b) if b != 0.0 and math.isfinite(b) else 0.0
            att[f"{group}_att"] = {"b": b, "sign": sign,
                                   "reason": None if sign else REASON_SEED_SIGN_AMBIGUOUS}
        start = {f"{g}.k_rate": rates[f"{g}_rate"]["seed"] for g in ("pitch", "yaw", "roll")}
        for group in _ATT_B:
            start[f"{group}.kp"] = att[f"{group}_att"]["sign"]
            start[f"{group}.ki"] = 0.0
        tuned = tune_point(lm, start, targets=targets, rate_filters=rate_filters, **act_kw)
        anchors.append({"point": pt, "tr": tr, "lm": lm, "lon": lon, "signs": {**rates, **att}, "tuned": tuned})

    values, slots, failed = {}, {}, {}
    for name, slot in _GAIN_SLOT.items():
        group = _SIGN_GROUP[name]
        signs = {a["signs"][group]["sign"] for a in anchors if a["signs"][group]["sign"]}
        # 표본으로 쓸 수 없는 앵커를 뺀다 — 자기 튜닝 실패와, 실패한 레이트 루프 위에서 튜닝된 뒤 자리(요 실패 점의
        # 롤 댐퍼·자세 등). 적합 제외(orchestrator)와 같은 규칙(tune.failed_gain_slots)이다
        unusable = [failed_gain_slots(a["tuned"]["slots"]) for a in anchors]
        used = [a for a, bad in zip(anchors, unusable) if a["signs"][group]["sign"] and name not in bad]
        center = anchors[0]
        g, kind = group.split("_")
        _, x, u = (_RATE_B if kind == "rate" else _ATT_B)[g]
        label = f"B[{x},{u}]"
        rec = {"sign_basis": f"{label}={center['signs'][group]['b']:.4g}", "anchors_used": len(used),
               "reason": None, "value": 0.0}
        if len(signs) > 1:
            rec["reason"] = REASON_SEED_SIGN_VARIES
            rec["sign_basis"] = ", ".join(f"{a['point'].case.name} {label}={a['signs'][group]['b']:.4g}"
                                          for a in anchors)
        elif not used:
            rec["reason"] = (center["signs"][group]["reason"]
                             or (unusable[0].get(name) or {}).get("reason")
                             or center["tuned"]["slots"][slot]["reason"])
        else:
            sign = signs.pop()
            k0 = [abs(a["tuned"]["gains"][name]) / _factor(schedule, name, a["point"].case.mach) for a in used]
            rec["value"] = sign * statistics.median(k0)
            if group.endswith("_rate"):
                rec["reached"] = bool(center["signs"][group].get("reached"))
            if len(used) < min(2, len(anchors)):
                rec["reason"] = REASON_SEED_THIN_ANCHORS
        if rec["reason"] is not None:
            rec["reason_text"] = reason_text(rec["reason"])
            failed[name] = rec["reason"]
        values[name] = rec["value"]
        slots[name] = rec

    wc, wc_notes = _inner_crossovers(anchors[0]["tuned"]["achieved"],
                                     [a["tuned"]["achieved"] for a in anchors[1:]])
    ap, ap_source, ap_notes = _autopilot(built, anchors[0]["point"], anchors[0]["lon"],
                                         wc, None if existing is None else existing["autopilot"])
    ap_notes = wc_notes + ap_notes

    scas = {}
    for group in ("pitch", "roll", "yaw"):
        prev = existing["scas"][group] if existing is not None else {}
        scas[group] = {
            "kp": values.get(f"{group}.kp", prev.get("kp", 0.0)),
            "ki": values.get(f"{group}.ki", prev.get("ki", 0.0)),
            "k_rate": values[f"{group}.k_rate"],
            "washout_tau": prev.get("washout_tau", 0.0),
        }
    design = {
        "scas": scas, "autopilot": ap,
        "k_diff_thr": existing["k_diff_thr"] if existing is not None else 0.0,
        "provenance": {
            "source": SEED_SOURCE,
            "note": "초기 게인 빠른 탐색 — 자동 설계 전. 부호는 조종효율 B, 크기는 앵커 튜닝의 중앙값, 자동조종은"
                    " 시간척도 분리 휴리스틱",
            "plant_fingerprint": built.plant_fingerprint,
            "anchors": [a["point"].case.name for a in anchors],
            "slots": slots,
            "autopilot": ap_source,
            # 자동조종은 자동 설계가 다시 잡지 않는다(튜너는 SCAS 7자리만) — 바깥 루프 대역폭을 어디서 잡았는지가
            # 결과가 아니라 문서에 남아야 나중에 읽는 사람이 안다(apply_seed_basis와 같은 자리)
            "autopilot_notes": ap_notes,
            "yaw_attitude": "document" if existing is not None else "zero",
            "schedule": "created" if created else "document",
        },
    }

    verification, warnings, failed_loops, reason = {}, [], [], None
    if failed:
        reason = next(iter(failed.values()))
    else:
        from claw.profile import build_profile

        cand = copy.deepcopy(doc)
        cand["variants"] = []
        cand["law"]["design"] = design
        cand["law"]["schedule"] = schedule
        # 새 시드는 새 설계의 출발이다 — 옛 확정 게인 표(자동 설계 반영, v2)는 이 설계값과 무관해
        # 무효다. 안 지우면 기준 지문 대조가 낡음으로 거부해 확인 평가(sim_check)가 조립에서 죽는다
        cand["law"]["gain_tables"] = None
        cb = build_profile(cand)
        tables, gains, rf = cb.gain_tables(), cb.design_gains(), cb.rate_filters()
        for a in anchors:
            sm = scheduled_margin_point(a["lm"], tables, gains, a["point"].case, criteria=MarginCriteria(),
                                        targets=targets, rate_filters=rf, **act_kw)
            verification[a["point"].case.name] = {
                loop: {"status": e.get("status"), "sign_mismatch": bool(e.get("sign_mismatch"))}
                for loop, e in sm.items() if isinstance(e, dict) and "status" in e}
        loops = [(name, loop, e) for name, ls in verification.items() for loop, e in ls.items()]
        common = set.intersection(*(set(ls) for ls in verification.values()))
        failed_loops = sorted(loop for loop in common
                              if all(ls[loop]["status"] == "fail" for ls in verification.values()))
        if any(e["sign_mismatch"] for _, _, e in loops):
            reason = REASON_SIGN_MISMATCH
        elif failed_loops:
            reason = REASON_SEED_VERIFY_FAILED
        warnings = [f"{name} {loop}: 스케줄 검증 fail — 자동 설계가 다듬을 자리" for name, loop, e in loops
                    if e["status"] == "fail"]
    ok = reason is None
    design["provenance"]["ok"] = ok

    sim = None
    if ok and sim_check:
        from claw.pipeline.criteria import GainEvalCriteria
        from claw.pipeline.evaluate import evaluate
        from claw.pipeline.influence import Shape

        res = evaluate(cb.aircraft(), [anchors[0]["tr"]], Shape(profile=cb), GainEvalCriteria(), depth="full")
        sim = {"case": anchors[0]["point"].case.name, "hard_fail": res["aggregate"]["hard_fail"],
               "cards": {c["key"]: c["status"] for c in res["cards"]},
               "checks": {c["key"]: c["status"] for c in res["checks"]["list"]}}
        design["provenance"]["sim_check"] = sim

    return _clean({
        "ok": ok, "reason": reason, "reason_text": reason_text(reason) if reason else None,
        "design": design, "schedule": schedule if created else None, "schedule_created": created,
        "anchors": [{"name": a["point"].case.name, "mach": a["point"].case.mach, "alt": a["point"].case.alt,
                     "fuel": a["point"].case.fuel, "qbar": _qbar(a["point"].case),
                     "slots": {k: s["reason"] for k, s in a["tuned"]["slots"].items()},
                     "gains": {n: a["tuned"]["gains"][n] for n in _GAIN_SLOT}} for a in anchors],
        "slots": slots, "verification": verification, "failed_loops": failed_loops, "warnings": warnings,
        "autopilot_notes": ap_notes,
        "sim_check": sim,
        "grid": grid_echo,
        "elapsed_s": time.perf_counter() - t0,
    })
