"""운영점별 SCAS 게인 자동 튜닝 — 결정론적 2단 (댐퍼 감쇠 목표 → 자세 PI 루프쉐이핑).

docs -02의 "자동 PID 튜닝 스코프 제외 [확정]"을 번복하는 구현 (사용자 확정).
LQR 제외는 유지 — PI 구조 불변, 튜닝 방식만 자동화한다. 대상은 SCAS 내측
**게인** 7자리(pitch/roll kp·ki·k_rate + yaw.k_rate)이고 AP 외측(고도·속도·헤딩)은 v1
제외 — 분리모델에 h·ψ 상태가 없다는 openloop.py GROUP_LOOPS의 정직성과 같은 이유.

2단 구조 (closure.py의 successive closure 조성과 같은 정의 — 튜닝과 검증이 같은
자로 잰다):
1. 레이트 댐퍼 — 폐쇄 모드 지표 목표의 단조 스캔+이분: pitch ζ_sp→zeta_sp,
   yaw ζ_dr→zeta_dr(먼저 — 더치롤 감쇠 없이는 횡축이 성립 안 함), roll
   λ_roll→roll_lambda. 부호는 설계값이 보유(방향만 쓴다), 탐색은 |설계값|×4 브래킷.
   댐퍼 안정 캡: 작동기·지연 포함 폐루프 고유치 안정을 위반하면 |k|를 안정 경계
   아래로 이분 축소 (01 §4.2 "PM 91°→−76.3°" 실증 사고의 재발 방지 가드 —
   교차 주파수 캡이 아니라 폐루프 안정성 판정이다: |L|<1 댐퍼는 교차가 없다).
   횡축의 **느린 나선 실근 하나**는 기체 비행성 기준(analysis.fq.FQCriteria — 자세 루프가 빠진 고장
   상태라 나선 수준 2 배가시간)을 만족하는 한 가드 위반이 아니다 — 나선은 자세 루프의 몫이다
   (_damper_loop_verdict, _SPIRAL_T2_MIN_S).
   레이트 루프 마진 가드: 안정만으로는 모자란다 — 댐퍼 크기가 AS94900 끊은 루프 마진(이 루프를 끊고 같은 축의
   다른 레이트 루프는 닫은 개루프, 작동기 2차계+Padé)의 설계 목표(TuneTargets.pm_deg·gm_db)를 지키도록 |k|를
   묶는다(_cap_by_margins, cap_bound "margin" — rate_loop_margins 머리말).
   앞 자리(요)는 뒤 자리(롤)를 닫은 조성에서 한 번 더 찾는다(2차 패스 — 정상 상태 목표 + 뒤 댐퍼가 빠진
   고장 상태의 비행성 수준 2 하한, _retune_with_later_closed).
2. 자세 PI — 목표 교차 ωc_att = (레이트 ωc 또는 기준 wn)/wc_ratio_att에서
   |PI·G′·Act·Delay|=1이 되게 |kp| 결정 (PI 영점 = ωc_att×ki_zero_frac),
   oriented_margins로 검증 → PM/GM 미달 시 ωc_att ← backoff× 기하 백오프,
   바닥(wc_att_floor_frac) 도달 시 status="infeasible" — **던지지 않는다**.
   infeasible도 결과다: 분류기(classify)의 structural_limit 판정 근거가 된다.
3. 전체 폐루프 확인 — 그 축의 댐퍼 전부 + 자세 PI를 채널마다 작동기·지연을 거쳐 한꺼번에
   닫고(closure.closed_loop_poles) 극이 전부 안정해야 한다. 여기에는 나선 면제가 없다 — 자세
   루프가 닫혔으면 나선도 잡혀야 한다. 불안정하면 자세 자리가 loop_unstable로 실패한다.

polish=True는 선택적 Nelder-Mead 마무리(kp·ki 2변수, 대역폭 보상−마진 벌점) —
기본 OFF, 결정론·재현성 우선.
"""

import math
from dataclasses import asdict, dataclass, replace

import numpy as np

from claw.analysis.fq import LN2, FQCriteria
from claw.analysis.margins import broken_loop, nyquist_margins
from claw.design.closure import (
    _WN_FLOOR_FRAC,
    AXIS_SPECS,
    att_margin_loop,
    att_margins,
    axis_metrics,
    close_rates,
    closed_loop_poles,
    rate_loop_crossover,
    wn_reference,
)
from claw.design.criteria import MarginCriteria
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
# 옛 결과의 사유 — 더는 내지 않는다(seed_required로 바뀜). 저장된 결과의 문구를 읽으려고 표에 남긴다
REASON_ZERO_DESIGN = "zero_design"
REASON_TARGET_UNREACHED = "target_unreached"  # 브래킷을 끝까지 넓혀도 미달 (플랜트 한계)
REASON_CAPPED = "capped"  # 댐퍼 안정 캡이 목표 전에 묶었다 (작동기·지연 예산)
REASON_NO_STABLE_GAIN = "no_stable_gain"  # 안정한 |k|가 없어 댐퍼를 껐다
REASON_BANDWIDTH_COLLAPSE = "bandwidth_collapse"  # 마진은 통과, 교차가 하한 아래
REASON_MARGIN_FLOOR = "margin_floor"  # 백오프 바닥까지 PM/GM 미달
REASON_DEGENERATE = "degenerate"  # 기저 루프 응답이 무의미 — 튜닝 불가
REASON_RESCUED = "rescued"  # 백오프 해가 하한 미달이라 마무리로 구제됨 (통과)
REASON_NA_NO_CROSSOVER = "na_no_crossover"  # 교차가 없어 마진을 잴 수 없다 (통과 아님)
# 설계값 0 — 방향(부호)을 몰라 튜닝하지 않았다. 종전에는 "튜닝 안 함(na)"이라 점 판정을 끌어내리지 않았고,
# 그래서 댐퍼·자세 루프가 꺼진 채 자동 설계가 통과할 수 있었다. 새 기체의 첫 설계가 바로 이 모양이다
REASON_SEED_REQUIRED = "seed_required"
# 게인 부호가 플랜트와 반대(양의 되먹임). 자세 자리: 루프를 뒤집어야만 위상여유가 난다 — oriented_margins가
# PM>0인 쪽을 골라 주므로 수치는 건강해 보인다(데모 피치 kp·ki 부호를 뒤집으면 PM 104~121°로 "ok"였다).
# 레이트 자리: 설계 부호로 조금 닫으면 반대 부호보다 감쇠·대역폭이 나빠진다 — 브래킷을 256배까지 넓혀도
# 목표에 못 닿고 안정 캡에 걸려 capped·target_unreached(통과 쪽 사유)로 끝났다(롤·요 조종 미계수 부호를
# 뒤집은 예제 기체에서 손설계 게인)
REASON_SIGN_MISMATCH = "sign_mismatch"
# 자세 루프까지 닫은 축 전체 폐루프(댐퍼 전부 + 자세 PI, 채널마다 작동기·지연)가 불안정. 개별 판정은 다 통과할 수
# 있다 — 댐퍼 가드는 자기 댐퍼 하나만 작동기를 거쳐 닫고, 자세 마진은 레이트를 이상 폐쇄한 A′ 위의 SISO 보드
# 마진이라 개루프 불안정 플랜트에서는 폐루프 안정을 보장하지 않는다. 구 기체 M0.61/h0 실측: 피치 댐퍼 가드·자세
# 마진 모두 통과(ok)인데 합친 루프가 17.1 rad/s에서 발산(실부 +0.0002)했다
REASON_LOOP_UNSTABLE = "loop_unstable"

# 사유 → 사람이 읽는 한 줄 + 다음 수. 화면·원장이 이 표를 쓴다 (엔진이 정본).
REASON_TEXT = {
    REASON_OK: "설계 목표 달성",
    REASON_ZERO_DESIGN: "설계 게인이 0이라 방향 정보가 없다 — 이 자리를 쓸 것이면 설계값을 먼저 정한다",
    REASON_SEED_REQUIRED: "설계 게인이 0이라 부호를 몰라 튜닝하지 않았다 — 초기 게인 빠른 탐색으로 부호·크기를"
                          " 채운 뒤 다시 돌린다 (부호를 짐작하면 틀린 부호도 통과해 보인다)",
    REASON_SIGN_MISMATCH: "게인 부호가 플랜트와 반대다(양의 되먹임) — 자세 루프는 뒤집어야만 위상여유가 나고,"
                          " 레이트 댐퍼는 반대 부호가 감쇠를 더 준다. 설계 게인 부호를 확인한다",
    REASON_TARGET_UNREACHED: "게인을 아무리 키워도 목표 지표가 안 나온다 — 플랜트 한계다."
                             " 목표를 낮추거나 이 조건을 설계 범위에서 뺀다",
    REASON_CAPPED: "댐퍼 안정 가드(작동기·지연 포함 폐루프 안정, 느린 나선은 비행성 기준 배가시간) 또는"
                   " 레이트 루프 마진 가드(AS94900 끊은 루프 여유가 설계 목표 PM/GM 아래로 내려가지 않게)가"
                   " 목표 전에 묶는다 — 작동기·지연이나 마진 가드가 묶었으면 작동기 대역폭·지연 예산을 늘리거나"
                   " 목표를 낮추고, 나선 기준이 묶었으면 목표를 낮춘다 (어느 쪽인지는 그 점의 note·cap_bound)",
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
    REASON_LOOP_UNSTABLE: "자세 루프까지 닫은 축 전체 폐루프(작동기·지연 포함)가 불안정하다(발산, 또는 작동기"
                          " 대역 공진의 감쇠가 댐퍼 가드와 같은 하한 미만) — 개별 루프의 댐퍼 가드·보드 마진은"
                          " 통과해도 합친 루프가 서지 않는다. 지연·작동기 예산을 늘리거나 게인(자세 교차·댐퍼)을 줄인다",
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
                      REASON_BANDWIDTH_COLLAPSE, REASON_NA_NO_CROSSOVER, REASON_SEED_REQUIRED,
                      REASON_SIGN_MISMATCH, REASON_LOOP_UNSTABLE)

# 판정 자리(루프) → 그 루프를 성형하는 게인 자리. 분류기(valley 괴리·승격 값)·적합 제외·시드가 같은 표를 쓴다
LOOP_SLOTS = {
    "pitch_att": ("pitch.kp", "pitch.ki"),
    "pitch_rate": ("pitch.k_rate",),
    "roll_att": ("roll.kp", "roll.ki"),
    "roll_rate": ("roll.k_rate",),
    "yaw_rate": ("yaw.k_rate",),
}


def downstream_loops(loop: str) -> list:
    """successive closure에서 이 루프 **뒤에** 닫히는 같은 축 루프 — 이 루프를 닫은 조성 위에서 튜닝된 자리들.

    축마다 순서는 레이트(AXIS_SPECS rates 순서 = 닫는 순서) → 자세다: 횡축 yaw_rate → roll_rate → roll_att,
    종축 pitch_rate → pitch_att. 자세 루프 뒤에는 아무것도 없다."""
    for spec in AXIS_SPECS.values():
        order = [f"{g}_rate" for g, _, _ in spec["rates"]] + [f"{spec['att'][0]}_att"]
        if loop in order:
            return order[order.index(loop) + 1:]
    return []


def failed_gain_slots(slots: dict) -> dict:
    """한 점의 자리 판정 레코드 → **표본으로 쓸 수 없는** 게인 자리 {게인 자리: {loop, reason, basis}}.

    두 겹이다 (사용자 합의 규칙 2026-09-27 — 2겹째는 뒤에 닫히는 레이트 자리(요 실패 → 롤 댐퍼)까지 넓혔다):
    - basis "own" — 그 루프의 튜닝이 성립하지 않았다(SLOT_DESIGN_FAILED). 실패한 튜닝이 남기는 게인은 자리값이다
      (댐퍼를 끈 0, 뒤집힌 루프의 백오프 해) — 표본이 아니다.
    - basis "rate_loop" — 실패한 레이트 루프 **뒤에** 닫히는 같은 축 자리(downstream_loops)는 그 실패한 조성 위에서
      튜닝됐다. 자세 PI는 레이트를 접은 A′ 위에서 성형하고, 롤 댐퍼는 요 댐퍼를 닫은 프리픽스에서 찾는다 —
      밑의 댐퍼가 자리값(0)이면 그 위의 값은 출하되지 않는 플랜트의 답이다. 롤 댐퍼가 그렇다: 요가 0인 생 횡축에서
      찾은 롤 게인은 요를 닫은 조성의 값과 크기부터 다르고(05 §4.1 — 데모 M0.3/h1000 −0.592 → −0.0047), 그 점의
      표 값은 적합 뒤 **이웃 보간 요 게인**과 함께 나가므로(요 표본도 빠진다) 요 = 0 조성의 답은 어느 조성과도
      맞지 않는다. 튜닝 단계에서 다시 찾을 수도 없다 — 보간 요 게인은 적합이 끝나야 정해진다(순환).
    target_unreached·capped는 빼지 않는다 — 목표엔 못 갔어도 **작동하는 댐퍼를 냈다**. 자기 실패 사유가
    rate_loop 표시보다 우선한다."""
    failed = [(loop, rec["reason"]) for loop, rec in slots.items()
              if rec.get("reason") in SLOT_DESIGN_FAILED]
    out: dict = {}
    for loop, reason in failed:
        for gslot in LOOP_SLOTS.get(loop, ()):
            out[gslot] = {"loop": loop, "reason": reason, "basis": "own"}
    for loop, reason in failed:
        for down in downstream_loops(loop):
            for gslot in LOOP_SLOTS.get(down, ()):
                out.setdefault(gslot, {"loop": loop, "reason": reason, "basis": "rate_loop"})
    return out


@dataclass(frozen=True)
class TuneTargets:
    pm_deg: float = 50.0  # 설계 목표 위상여유 — 합격 45°보다 여유 (히스테리시스)
    gm_db: float = 8.0  # 설계 목표 이득여유 — 합격 6 dB보다 여유
    zeta_sp: float = 0.7  # 단주기 감쇠 목표
    # 더치롤 감쇠 목표 — 판정 목표선(MarginCriteria.zeta_good 0.5) **위에 여유를 둔** 값이다. 튜너는 앵커에서 목표에
    # 처음 닿는 크기를 고르므로 앵커의 지표가 곧 목표이고, 출하되는 것은 그 게인을 이은 스케줄이다 — 1축 마하 표가
    # 설계 고도들을 한 축에 번갈아 놓아(3000 m 검증점이 해면 분할점 값을 받는 식) 검증점·재양자화에서 지표가 목표
    # 아래로 내려간다. 목표가 목표선과 같으면 그 표현 손실이 전부 warn이 된다 — 요 2차 패스를 닿은 점에도 돌린 뒤
    # (_retune_with_later_closed) 목표 0.5 = 목표선 0.5라 요 판정 ok/warn이 쇼케이스 기록 설정 96/35 · 예제 기본
    # 130/55였다. 피치(목표선이 목표의 71 %)와 롤(목표선 = 목표 × lam_good_frac 0.8)은 이미 여유가 있었다.
    # 값은 **잰 표현 손실을 덮는 크기**다: 판정 ζ_dr ÷ 목표의 최저가 목표 0.5 / 0.6에서 쇼케이스 기록 설정 0.870 / 0.849
    # · 구 기체 0.853 / 0.838 · 예제 기본 0.840 / 0.836(표 모드·작은 설정은 0.94·0.97) — 손실 최대 16.4 %라 목표선을
    # 지키는 최소 목표는 0.5 / (1 − 0.164) = 0.598 → 0.6(목표선이 목표의 83 % — 롤 80 %·피치 71 %와 같은 결).
    # 덮지 않은 한 점이 있다 — 예제 기본 M0.2159/h5000 검증점은 표가 해면 분할점 값을 통째로 줘 손실 23 %(요·롤 댐퍼
    # 모두 해면 값)다. 그건 감쇠 여유가 아니라 고도를 못 싣는 표 축의 몫이다. 롤과 같은 비율(0.625)은 쇼케이스 roll.ki의
    # 고도 톱니를 띠 비 2.37 → 2.51로 밀어 확정 표 급변 검사(2.5)를 넘고(0.6은 2.49), 0.7은 구 기체 4점에서 2차 패스가
    # 롤을 목표 아래로 끌어 불채택이 된다(롤 가드와 부딪히는 선). 실측 0.5 → 0.6(첫 정지 결과·실패 수·앵커 사유 불변,
    # 2차 패스 불채택 0, 고장 상태 전 앵커 수준 1 — 하한 묶임 0): 요 판정 ok/warn 쇼케이스 기록 설정 96/35 → 131/0 · 표
    # 모드 73/14 → 87/0 · 예제 기본 130/55 → 184/1(위 한 점) · 작은 설정 38/20 → 58/0 · 구 기체 155/15 → 170/0. 대가는
    # 러더다 — 요 게인 중앙값 ×1.21~1.33(쇼케이스 최대 0.955 → 1.293). 쇼케이스 기본 미션 러더 최대 7.2° → 8.8°(한계
    # ±20°, 포화 0), 앵커별 선형 응답(작동기·지연 포함 횡축 전체 폐루프)의 최대로 옆미끄럼 5° 교란 5.2° → 6.2°, 40° 뱅크
    # 스텝 13.5° → 16.0°(쇼케이스는 요 워시아웃이 없어 정상 선회 r에 맞선다 — 정상분 8.7° → 11.9°). 워시아웃이 있는
    # 예제·구 기체는 30° 뱅크 스텝 7.0° → 8.3° · 6.6° → 7.5°
    zeta_dr: float = 0.6
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
# 레이트 댐퍼 방향 확인 — 설계 크기의 이 배로 양 부호를 닫아 지표를 비교한다. 작은 닫기에서 가르는 이유: 크게
# 닫으면 ζ가 양쪽 다 1(과감쇠 실근)에 붙어 못 가르는 점이 있다(데모 M0.6 요 댐퍼). 못 가르면 설계 크기에서 한 번 더
_DIRECTION_PROBE = 0.1
# 방향 판정에서 롤 λ를 "잰 값"으로 칠 최소 p 참여도 — 판정 기본값(MarginCriteria.lam_part_min)과 같은 선이다.
# 튜너는 criteria를 받지 않으므로(분류기·시드도 tune_point를 부른다) 기본값을 한 자리에서 물려받는다.
# 판정 문턱이 아니라 "롤 모드가 실근으로 있나"의 문턱이라 설정 덧씀을 따라가지 않아도 판정이 갈리지 않는다
_DIRECTION_PART_MIN = MarginCriteria.lam_part_min
# 댐퍼 가드의 나선 면제선 [s] — 기체 비행성 기준(analysis.fq.FQCriteria — MIL-F-8785C Class I·Cat B [기본값])의
# 나선 **수준 2** 최소 배가시간을 그대로 쓴다(8 s). 새 수를 만들지 않는다 — 기준을 바꾸면(다른 급·비행단계) 따라간다.
# 수준을 가르는 것은 **어느 상태를 재는가**다. 8785C의 나선 요구는 비행제어계를 켠 채 조종간을 놓은 기체에 걸리고,
# 이 SCAS에서 그 정상 상태는 자세 루프까지 닫힌 조성이다 — tune_point 3단이 그 조성을 극 전부 안정(나선 안정 —
# 수준 1보다 강하다)으로 따로 확인한다. 댐퍼만 닫힌 조성은 자세 루프가 빠진 **고장 상태**이고, 8785C는 고장
# 상태에 한 단계 낮은 수준을 허용한다. 수준 1을 여기 걸면 고장 상태의 나선 요구가 정상 상태의 롤 댐퍼를 깎는다 —
# 예제 기체 기본 설정 실측: 앵커 135점 중 41점에서 롤 댐퍼가 나선 20 s 선에 묶여(λ 2.7~8.6, 목표 12) 검증 실패
# 37건이 남았고, 수준 2 선에서는 0건(전 점 전체 폐루프 안정)이다
_SPIRAL_T2_MIN_S = FQCriteria().spiral_t2_l2
# 작동기 대역 진동극의 최소 감쇠 — 간신히 안정한 작동기 공진을 합격으로 두지 않는다. 댐퍼 가드와 전체 폐루프 확인이
# 같은 선을 쓴다(대역 = 0.3 × 작동기 wn 위)
_ZETA_ACT_MIN = 0.10
# 요 2차 패스의 고장 상태 하한 — 뒤 댐퍼(롤)가 빠진 조성(1차 탐색 조성)의 더치롤이 지켜야 할 비행성 **수준**
# (analysis.fq.FQCriteria.judge_dutch_roll — Cat B 수준 2: ζ ≥ 0.02·ζωn ≥ 0.05·ωn ≥ 0.4). 나선 면제선(_SPIRAL_T2_MIN_S)과
# 같은 규칙이다 — 설계 목표(TuneTargets.zeta_dr)는 정상 상태(뒤 댐퍼까지 닫힌 최종 조성) 몫이고, 한 루프가 빠진 고장
# 상태에는 8785C가 한 단계 낮은 수준을 허용한다. 새 수를 만들지 않는다 — 기준을 바꾸면 따라간다.
# 판정 합격선(MarginCriteria.zeta_min 0.30)을 고장 상태 하한으로 쓰는 안은 (목표 0.5일 때) 재어 보고 버렸다: 롤 열림
# 봉우리가 0.30 바로 위인 저동압 모서리에서 봉우리 옆까지 끌어올려(쇼케이스 M0.113/h3000 봉우리 0.319 → k 2.44, 1차
# 패스 argmax 문제가 되살아난다) 앵커 367점 중 111점에서 묶였다(예제 기본 23 · 작은 설정 4 · 구 기체 50 · 쇼케이스 34
# — 전부 종전에도 2차 패스를 받던 롤 열림 미달 영역). 수준 2 하한은 네 설정 어디서도 묶지 않는다(채택 게인의 고장
# 상태가 전 앵커 수준 1, 최소 ζ 0.226 구 기체 M0.262/h5000 — 목표 0.6에서 0.251) — 결과를 바꾸는 선이 아니라 2차
# 패스가 고장 상태를 버리지 못하게 하는 가드다
_FAILSTATE_DR_LEVEL = 2

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


def _damper_loop_verdict(lm_axis, group, x_rate, u_in, k, act_kw, zeta_act_min=_ZETA_ACT_MIN) -> dict:
    """레이트 댐퍼 폐루프(작동기 2차계+Padé 지연 포함)의 안정 판정 — {"stable", "bound", "spiral_t2_s", "max_re"}.

    01 §4.2 실증 사고(작동기·지연 포함 시 PM 91°→−76.3° 불안정 전환)를 직접 막는
    가드다. 교차 주파수 캡은 틀린 가드였다 — |L|<1인 댐퍼는 교차가 없고(소이득
    안정), 교차가 있어도 다중 교차(장주기 봉우리) 탓에 SISO PM이 진짜 안정성과
    어긋난다. 판정: 폐루프 극 전부 안정 + 작동기 대역 부근(>0.3×wn_act) 진동극의
    ζ ≥ zeta_act_min (간신히 안정한 작동기 공진을 합격으로 두지 않는다).

    **나선 면제 (횡축만)** — 발산극이 정확히 하나이고 그것이 느린 실근(모드 지표가 저주파 장주기·나선을
    빼는 문턱 _WN_FLOOR_FRAC × 기준 wn 아래 — 횡축의 느린 실근은 나선뿐이다)이며 배가시간이 비행성 기준
    나선선(_SPIRAL_T2_MIN_S — 자세 루프가 빠진 고장 상태라 수준 2) 이상이면 안정으로 친다. 종전 "극 전부 안정"은 두 경우에 댐퍼를 꺼 버렸다:
    개루프 나선이 이미 양(예제 기체 M0.1/h500 +0.0096, 배가 72 s — 어떤 댐퍼로도 안 없어진다)이거나, 롤
    레이트 댐퍼가 나선근을 p/δa의 우반면 영점 쪽으로 밀어 느리게 양으로 넘긴 경우(M0.1129/h500 +0.025~
    +0.040)다. 같은 게인에서 λ 4.3~14.4·ζ_dr 0.74~0.80로 댐퍼 본연의 일은 정상이었고, 나선을 잡는 것은
    뱅크각 되먹임 — 자세 루프의 몫이다(자세까지 닫은 전체 폐루프는 tune_point가 면제 없이 따로 확인한다).
    면제 한도를 비행성 기준에서 받는 것은 댐퍼만 닫은 조성(자세 루프가 꺼진 고장 상태)도 나선만큼은 그
    상태의 비행성 요구를 지키게 하려는 것이다. 종축(장주기)·진동 발산·빠른 실근에는 면제가 없다.

    bound: 불안정일 때 무엇이 걸렸나 — "spiral"(느린 나선이 기준보다 빨리 발산) | "unstable"(그 밖의 발산극) |
    "actuator_resonance"(작동기 대역 진동극의 감쇠 부족). spiral_t2_s: 면제한 나선의 배가시간(면제 없으면 None).
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
    out = _spiral_exempt_verdict(poles, lm_axis)
    if out["stable"] and not _actuator_band_damped(poles, act_kw, zeta_act_min):
        return {**out, "stable": False, "bound": "actuator_resonance"}
    return out


def _actuator_band_damped(poles, act_kw, zeta_act_min=_ZETA_ACT_MIN) -> bool:
    """작동기 대역(> 0.3 × 작동기 wn) 진동극이 전부 ζ ≥ zeta_act_min인가 (작동기 인자가 없으면 참)."""
    _p, zeta = _band_least_damped(poles, act_kw)
    return zeta is None or zeta >= zeta_act_min


def _band_least_damped(poles, act_kw) -> tuple:
    """작동기 대역(> 0.3 × 작동기 wn) 진동극 가운데 ζ가 가장 작은 극 — (극, ζ). 대역 진동극이 없거나 작동기
    인자가 없으면 (None, None). 작동기 대역 감쇠 판정(_actuator_band_damped)과 그 판정에 걸린 극의 보고가 같은
    극을 본다."""
    wn_act = act_kw.get("actuator_wn") or 0.0
    if not wn_act:
        return None, None
    band = [complex(p) for p in poles if p.imag > 1e-9 and abs(p) > 0.3 * wn_act]
    if not band:
        return None, None
    p = min(band, key=lambda q: -q.real / abs(q))
    return p, float(-p.real / abs(p))


def _failing_pole(poles, bound, act_kw) -> dict:
    """판정에 **걸린** 극 — {"worst_pole": [Re, |Im|], "worst_zeta"}. 작동기 대역 공진(bound "actuator_resonance")이면
    대역 진동극 가운데 ζ가 가장 작은 극, 그 밖(발산·안정)이면 실부가 가장 큰 극.

    종전에는 어느 경우든 실부 최대 극을 적었다 — 작동기 대역 공진은 극이 전부 안정한 채 걸리는 판정이라 그 극은
    대개 느린 장주기·나선 실근이다. 구 기체 M0.6/h0/f40 피치 실측: 걸린 극은 −1.647 ± 17.73j(ζ 0.0925 < 0.10)인데
    기록·note는 "최대 극 실부 −0.0180 (허수부 0 rad/s)"를 가리켜 사용자를 엉뚱한 모드로 보냈다."""
    poles = np.asarray(poles)
    p = None
    if bound == "actuator_resonance":
        p, _z = _band_least_damped(poles, act_kw)
    if p is None:
        if not poles.size:
            return {"worst_pole": None, "worst_zeta": None}
        p = complex(poles[int(np.argmax(poles.real))])
    return {"worst_pole": [float(p.real), float(abs(p.imag))],
            "worst_zeta": float(-p.real / abs(p)) if abs(p) > 0.0 else None}


def _spiral_exempt_verdict(poles, lm_axis) -> dict:
    """극 집합 → 나선 면제를 적용한 안정 판정 {"stable", "bound", "spiral_t2_s", "max_re"} (_damper_loop_verdict 규칙).

    발산극(Re ≥ −1e-9)이 없으면 안정. 횡축에서 발산극이 정확히 하나이고 느린 실근(|Re| < _WN_FLOOR_FRAC ×
    기준 wn — 모드 지표가 장주기·나선으로 보고 빼는 저주파 문턱)이면 그것이 나선이다: 배가시간이 비행성 기준
    선(_SPIRAL_T2_MIN_S) 이상이면 안정(면제), 아니면 bound "spiral". 나머지 발산은 전부 bound "unstable"."""
    poles = np.asarray(poles)
    max_re = float(np.max(poles.real)) if poles.size else -math.inf
    bad = [p for p in poles if p.real >= -1e-9]
    if not bad:
        return {"stable": True, "bound": None, "spiral_t2_s": None, "max_re": max_re}
    p = bad[0]
    slow_real = (lm_axis.axis == "lat" and len(bad) == 1 and abs(p.imag) <= 1e-9
                 and abs(p.real) < _WN_FLOOR_FRAC * wn_reference(lm_axis))
    if not slow_real:
        return {"stable": False, "bound": "unstable", "spiral_t2_s": None, "max_re": max_re}
    t2 = LN2 / p.real if p.real > 0.0 else math.inf
    if t2 < _SPIRAL_T2_MIN_S:
        return {"stable": False, "bound": "spiral", "spiral_t2_s": t2, "max_re": max_re}
    return {"stable": True, "bound": None, "spiral_t2_s": t2, "max_re": max_re}


def _strict_verdict(poles, act_kw) -> dict:
    """극 집합 → 면제 없는 안정 판정 {"stable", "bound"} — 극 전부 안정 + 작동기 대역 진동극 ζ ≥ _ZETA_ACT_MIN."""
    if not np.all(np.asarray(poles).real < -1e-9):
        return {"stable": False, "bound": "unstable"}
    if not _actuator_band_damped(poles, act_kw):
        return {"stable": False, "bound": "actuator_resonance"}
    return {"stable": True, "bound": None}


def _closed_loop_check(lm_axis, gains, orientation, act_kw) -> dict:
    """자세 루프까지 닫은 축 전체 폐루프 확인 — {"stable", "bound", "max_re", "worst_pole", "worst_zeta", "rates_only"}.

    closure.closed_loop_poles로 그 축의 댐퍼 전부 + 자세 PI를 채널마다 작동기·지연을 거쳐 한꺼번에 닫는다.
    판정은 **극 전부 안정 + 작동기 대역 진동극 ζ ≥ _ZETA_ACT_MIN**(댐퍼 가드와 같은 선)이다 — 나선 면제가 없다:
    자세 루프가 닫혔으면 뱅크각 되먹임이 나선을 잡아야 하고, 그것이 댐퍼 가드가 나선을 면제한 근거다
    (_damper_loop_verdict). 개별 판정(댐퍼 가드 = 자기 댐퍼 하나, 자세 마진 = 이상 레이트 폐쇄 위 SISO 보드
    마진)을 다 통과해도 합친 루프는 발산할 수 있다.

    rates_only: 자세 PI를 뺀 같은 조성(댐퍼 전부, 작동기·지연 포함)의 판정 — 댐퍼 가드 규칙(나선 면제 포함)을
    쓴다. 전체가 불안정할 때 "자세 루프가 발산을 만들었나, 댐퍼 조성이 이미 발산하나"를 가른다(다음 수가 다르다)."""
    group = AXIS_SPECS[lm_axis.axis]["att"][0]
    kw = _loop_kw(act_kw)
    rates = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0) for g, _, _ in AXIS_SPECS[lm_axis.axis]["rates"]}
    full = closed_loop_poles(lm_axis, rates, kp=gains.get(f"{group}.kp", 0.0),
                             ki=gains.get(f"{group}.ki", 0.0), orientation=float(orientation or 1), **kw)
    only_poles = closed_loop_poles(lm_axis, rates, **kw)
    only = _spiral_exempt_verdict(only_poles, lm_axis)
    if only["stable"] and not _actuator_band_damped(only_poles, act_kw):
        only = {**only, "stable": False, "bound": "actuator_resonance"}
    verdict = _strict_verdict(full, act_kw)
    # max_re는 발산 판정의 양이라 늘 실부 최대 극이다. worst_pole·worst_zeta는 **판정에 걸린 극**이다 — 작동기 대역
    # 공진이면 그 대역에서 ζ가 가장 작은 극(_failing_pole)
    return {**verdict, "max_re": float(np.max(full.real)),
            **_failing_pole(full, verdict["bound"], act_kw),
            "rates_only": {"stable": only["stable"], "bound": only["bound"], "max_re": only["max_re"],
                           "spiral_t2_s": only["spiral_t2_s"],
                           **_failing_pole(only_poles, only["bound"], act_kw)}}


def _loop_kw(act_kw) -> dict:
    """act_kw → closed_loop_poles 인자 (지연 None·차수 None을 pi_loop 기본값으로)."""
    return {"actuator_wn": act_kw.get("actuator_wn"), "actuator_zeta": act_kw.get("actuator_zeta"),
            "delay_s": act_kw.get("delay_s") or 0.0, "pade_order": act_kw.get("pade_order") or 2,
            "rate_filters": act_kw.get("rate_filters")}


def _full_loop_stable(lm_axis, rate_gains, kp, ki, orientation, act_kw) -> bool:
    """자세 후보 (kp, ki)로 축 전체를 닫은 폐루프가 합격인가 — 백오프·구제의 수용 조건 (_closed_loop_check와 같은 판정)."""
    poles = closed_loop_poles(lm_axis, rate_gains, kp=kp, ki=ki, orientation=float(orientation or 1),
                              **_loop_kw(act_kw))
    return _strict_verdict(poles, act_kw)["stable"]


def _damper_loop_stable(lm_axis, group, x_rate, u_in, k, act_kw, zeta_act_min=_ZETA_ACT_MIN) -> bool:
    """댐퍼 가드의 합부만 — _damper_loop_verdict["stable"] (캡 탐색·산출 근거가 같은 판정을 쓴다)."""
    return _damper_loop_verdict(lm_axis, group, x_rate, u_in, k, act_kw, zeta_act_min)["stable"]


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


def rate_loop_margins(lm_axis, group, rate_gains, act_kw) -> dict | None:
    """레이트 루프 하나의 AS94900 끊은 루프 마진 — 튜너 가드(_cap_by_margins)와 검증(schedmap)이 같은 자로 잰다.

    AS94900(舊 MIL-F-9490D) 3.1.3.6의 안정 여유는 루프 하나를 끊고 나머지는 닫은 개루프에서 잰다. 이 도구는 레이트
    댐퍼를 모드 지표(ζ·λ)와 안정 가드로만 판정했고 여유를 안 쟀다 — 쇼케이스 기체 roll_p가 h200 M0.12~0.165에서 GM
    4.1~5.1 dB(6 dB 미만)·PM 45° 미만 6칸이었는데 게이트는 전부 통과였다(P6 마진 맵 실측, 루프 교차 12~13 rad/s ·
    작동기 30 rad/s · 지연 35 ms). 롤 λ 목표 12 rad/s가 댐퍼 교차를 작동기 대역 가까이 밀기 때문이다.

    조성 — 마진 맵 탭(서버 close_others)과 같은 엔진 조립(analysis.margins.broken_loop):
    - 끊는 루프: 이 자리의 댐퍼(u = +k·rate — broken_loop 부호 관례로 sign −1·kp k), 자기 레이트 필터 포함.
    - 닫아 둔 루프: **같은 축의 다른 레이트 루프**(게인이 0이 아닌 것) — 정적 게인(broken_loop 계약: 닫은 루프의
      필터는 빠진다). 자세 루프는 닫지 않는다 — 레이트 댐퍼는 successive closure에서 자세 루프보다 먼저 성형되고
      (튜너가 그 차례에 자세 게인을 모른다), 자세 루프는 레이트를 접은 A′ 위에서 따로 마진을 잰다(att_margins).
    - 작동기 2차계는 입력 자리마다 한 번, Padé 지연은 루프 경로마다(broken_loop).
    마진 수치는 nyquist_margins가 정본(−1까지의 거리 — 재계산하지 않는다). 여기서 하는 것은 **어느 교차를 읽나**뿐:

    **루프 대역 교차만** 읽는다 — 모드 지표가 장주기·나선을 빼는 문턱(_WN_FLOOR_FRAC × 개루프 기준 wn — lon은 단주기,
    lat는 더치롤 자리) 아래 교차는 뺀다. 그 아래는 나선·장주기가 0 dB·−180°를 지나는 자리이고, 닫아 둔 루프의 필터가
    빠진 조립(정적 게인)에서 특히 조성 의존적이다: 예제 기체 roll_p(M0.1129/h0/f50)는 요 댐퍼를 워시아웃 없이 닫으면
    ω = 0에서 GM 0.33 dB·0.013 rad/s에서 PM 17.9°로 읽히지만, 워시아웃째 닫은 조성에는 그 교차가 없다(루프 대역 PM
    35.0° @ 12.5 rad/s · GM 4.08 dB @ 18.9 rad/s는 두 조립이 같다). 나선은 댐퍼 가드의 면제 규칙과 자세까지 닫은 전체
    폐루프 확인의 몫이다. 뺀 교차는 low_band로 공개한다.

    이 루프를 닫은 폐루프가 발산하면(nyquist_margins closed_loop) 극을 댐퍼 가드와 같은 규칙(_spiral_exempt_verdict)으로
    가른다: 느린 나선 실근 하나면 루프 대역 교차의 −1까지 거리를 그대로 여유로 읽고(spiral_t2_s 공개 — 나선 판정은 가드
    몫), 그 밖의 발산이면 divergent(여유가 정의되지 않는다 — 판정은 미달).

    반환: {"pm_deg", "gm_db", "wcp", "wcg", "band_floor", "closed_with", "divergent"[, "low_band", "closed_loop"]} —
    pm_deg·gm_db는 늘 ≥ 0(거리), 루프 대역에 교차가 없으면 inf. 이 자리 게인이 0이면 None(잴 루프가 없다)."""
    spec = AXIS_SPECS[lm_axis.axis]
    k = float(rate_gains.get(f"{group}.k_rate", 0.0))
    if k == 0.0:
        return None
    x_rate, u_in = next((x, u) for g, x, u in spec["rates"] if g == group)
    others = [{"x_out": x, "u_in": u, "kp": float(rate_gains[f"{g}.k_rate"]), "ki": 0.0, "sign": -1.0}
              for g, x, u in spec["rates"]
              if g != group and float(rate_gains.get(f"{g}.k_rate", 0.0)) != 0.0]
    kw = _loop_kw(act_kw)
    filt = (kw.pop("rate_filters") or {}).get(group)
    m = nyquist_margins(broken_loop(lm_axis, x_rate, u_in, k, 0.0, -1.0, others, rate_filter=filt, **kw))
    floor = _WN_FLOOR_FRAC * wn_reference(lm_axis)
    cr = m.get("crossings")
    if cr is None:  # 교차가 하나씩 — 맨 위 값이 곧 그 교차(없는 교차는 w nan)
        cr = {"gain": [{"w": m["wcp"], "pm_deg": m["pm_deg"]}], "phase": [{"w": m["wcg"], "gm_db": m["gm_db"]}]}
    gain = [(float(c["w"]), abs(float(c["pm_deg"]))) for c in cr["gain"] if math.isfinite(c["w"])]
    phase = [(float(c["w"]), abs(float(c["gm_db"]))) for c in cr["phase"] if math.isfinite(c["w"])]
    in_g, in_p = [c for c in gain if c[0] >= floor], [c for c in phase if c[0] >= floor]
    pm = min(in_g, key=lambda c: c[1], default=(math.nan, math.inf))
    gm = min(in_p, key=lambda c: c[1], default=(math.nan, math.inf))
    out = {"pm_deg": pm[1], "gm_db": gm[1], "wcp": pm[0], "wcg": gm[0], "band_floor": floor,
           "closed_with": [f"{g}_rate" for g, _, _ in spec["rates"]
                           if g != group and float(rate_gains.get(f"{g}.k_rate", 0.0)) != 0.0],
           "divergent": False}
    lo_g, lo_p = [c[1] for c in gain if c[0] < floor], [c[1] for c in phase if c[0] < floor]
    if lo_g or lo_p:
        out["low_band"] = {"pm_deg": min(lo_g, default=math.inf), "gm_db": min(lo_p, default=math.inf)}
    cl = m.get("closed_loop")
    if cl is not None:
        v = _spiral_exempt_verdict(np.array([complex(re, im) for re, im in cl["unstable"]]), lm_axis)
        out["divergent"] = v["bound"] == "unstable"
        out["closed_loop"] = {"stable": False, "unstable": cl["unstable"], "spiral_t2_s": v["spiral_t2_s"]}
    return out


def _rate_margin_verdict(m, targets) -> str:
    """rate_loop_margins 결과 → "ok" | "short" | "na" — 설계 목표(TuneTargets.pm_deg·gm_db) 기준, 자세 루프와 같은 식
    (_att_margin_verdict). 발산(divergent)은 여유가 정의되지 않으므로 미달이다. 잴 루프가 없으면(None) ok."""
    if m is None:
        return "ok"
    if m.get("divergent"):
        return "short"
    return _att_margin_verdict(m, targets)


def _cap_by_margins(lm_axis, group, k, others_gains, act_kw, targets):
    """레이트 루프 마진 가드 — 끊은 루프 마진이 설계 목표 미달이면 |k|를 목표(+가드 밴드 PM 0.5°·GM 0.25 dB)를 지키는
    가장 큰 크기로 줄인다.

    (k', 사유) — 사유 ∈ {None, "capped", "no_stable_gain"}. 목표를 이미 지키면 k 그대로(None) — 가드가 없던 때와 비트까지
    같다. 축소는 _cap_by_stability와 같은 스캔+이분이다: [0, |k|]를 _SCAN_N 표본으로 훑어 목표를 지키는 가장 큰 표본과
    그 다음 표본(미달) 사이를 이분한다(단조를 전제하지 않는다). 판정 불가(na — nan)는 묶지 않는다(모르는 것을 미달로
    만들지 않는다). 작은 |k|는 루프 이득이 작아 여유가 커지므로 보통 표본이 선다 — 끝내 서지 않으면 no_stable_gain.

    others_gains: 이 조성에서 닫혀 있는 같은 축의 다른 레이트 게인(탐색 조성 그대로 — 1차 패스는 앞 자리만, 2차 패스는
    뒤 자리까지)."""
    sign = math.copysign(1.0, k)
    # 묶을 때는 목표선 위 가드 밴드까지 — 마무리(_polish_att)와 같은 밴드·같은 이유다: 이분은 경계에 정확히 붙으므로
    # 그대로 두면 검증점의 여유가 목표선(= 판정 목표선 gm_good_db) 양쪽에 동전 던지기로 떨어진다(재양자화 표가 warn ↔ ok를
    # 오간다). 묶을지 말지는 목표선 그대로 본다 — 이미 목표를 지키는 크기는 손대지 않는다
    aim = replace(targets, pm_deg=targets.pm_deg + _POLISH_GUARD_PM, gm_db=targets.gm_db + _POLISH_GUARD_GM)

    def ok(mag, tg=aim):
        g = {**others_gains, f"{group}.k_rate": sign * mag}
        return _rate_margin_verdict(rate_loop_margins(lm_axis, group, g, act_kw), tg) != "short"

    if k == 0.0 or ok(abs(k), targets):
        return k, None
    mags = np.linspace(0.0, abs(k), _SCAN_N)
    good = [i for i in range(1, len(mags) - 1) if ok(mags[i])]
    lo, hi = (mags[good[-1]], mags[good[-1] + 1]) if good else (0.0, mags[1])
    for _ in range(_BISECT_N):
        mid = 0.5 * (lo + hi)
        if ok(mid):
            lo = mid
        else:
            hi = mid
    if lo == 0.0:
        return 0.0, "no_stable_gain"
    return sign * lo, "capped"


def _direction_score(metrics, key) -> float:
    """방향 판정용 지표 값 — **잰 모드일 때만** 수치, 아니면 nan(판정할 모드 없음).

    롤 λ만 걸러진다. λ는 p 참여도가 가장 큰 실근의 |Re|인데(closure.roll_real_mode), 작은 닫기에서는
    롤 모드가 더치롤과 합쳐져 **실근으로 존재하지 않고** 남은 실근 둘의 참여도가 비슷하게 낮다. 그때
    "가장 큰 참여도"는 동전 던지기다 — 쇼케이스 기체 M0.1077/h0(요를 닫은 조성) 실측: 설계 부호 0.1배에서
    실근 −1.17(참여도 0.103)·−4.37(0.095)이라 1.17, 반대 부호에서 −1.09(0.055)·−4.32(0.060)이라 4.32가
    뽑혀 **반대 부호가 롤 대역폭을 네 배 준다**는 판정이 나왔다. 설계 크기에서는 설계 부호가 λ 6.41(참여도
    1.04)이고 반대 부호는 더치롤이 발산(ζ −0.43)하는데도 sign_mismatch로 댐퍼가 0이 됐다. 이웃 점은 참여도
    순서가 반대로 떨어져 멀쩡했다 — 참여도 동률이 점마다 뒤집히는 것이 1.5% 마하 간격의 0을 만들었다.

    판정(criteria.judge_bandwidth)과 **같은 문턱**을 쓴다: 참여도가 lam_part_min 미만이면 롤 대역폭을
    잰 게 아니다. 발산근은 |Re|가 부호를 지워 크게 보이므로 가장 나쁜 값(−inf)이다 — 반대 부호 댐퍼가
    롤 근을 양으로 밀어낸 것을 "λ가 더 크다"로 읽으면 안 된다.
    """
    v = metrics[key]
    if key != "roll_lambda":
        return v
    if metrics.get("roll_unstable"):
        return -math.inf
    part = metrics.get("roll_participation")
    if part is None or not part >= _DIRECTION_PART_MIN:
        return math.nan
    return v


def _closure_diverges(lm_axis, rate_gains, rate_filters=None) -> bool:
    """이상 레이트 폐쇄 A′(close_rates — 방향 판정·탐색과 같은 조성)에 **느린 나선 실근 밖의** 발산극이 있나.

    판정은 _spiral_exempt_verdict의 분류 그대로다 — bound "unstable"(진동 발산·빠른 실근 발산)만 참이다. 느린
    나선 실근 하나는 배가시간과 무관하게 빼고 본다: 나선은 자세 루프의 몫이고, 방향 판정이 묻는 것은 "이 부호의
    댐퍼가 축을 세우나 무너뜨리나"다."""
    poles = np.linalg.eigvals(np.asarray(close_rates(lm_axis, rate_gains, rate_filters).A, dtype=float))
    return _spiral_exempt_verdict(poles, lm_axis)["bound"] == "unstable"


def _rate_sign_opposes(f, mag, diverges=None) -> bool:
    """f(±크기) → 설계 부호가 반대 부호보다 **분명히** 나쁜가.

    f는 방향 판정용 값이다(_direction_score — 롤 λ는 롤 모드로 지목된 근일 때만 수치, 발산근은 −inf).
    diverges(±크기)는 그 조성이 느린 나선 밖으로 발산하나(_closure_diverges) — 롤 λ처럼 nan을 낼 수 있는
    지표에만 넘긴다(None이면 발산으로 가르지 않는다).

    **한쪽이라도 nan(판정할 모드 없음)인 크기는 λ로 가르지 않는다.** 그 전 규칙은 nan을 가장 나쁜
    값으로 쳐서 "한쪽만 모드를 잡았다"가 곧 부호 판정이 됐다 — 참여도 문턱 바로 밑(예제 기체 M0.119/h0
    설계 부호 0.1배에서 0.497)과 위(반대 부호 0.744)로 갈리는 것만으로 멀쩡한 부호를 결함으로 몰 수 있다.
    그렇다고 nan을 전부 "모른다"로 넘기면 **정말 뒤집힌 부호를 놓친다**: 부호가 반대인 롤 댐퍼는 저동압에서
    롤 모드를 더치롤과 합쳐 진동 발산으로 만들어 λ가 nan이 된다. 쇼케이스 기체의 조종 미계수 Cl/δa 부호를
    뒤집고 M0.1/h0에서 실측: 설계 크기의 설계 부호는 롤 모드 참여도 0.025(nan)·더치롤 ζ −0.36(최대 실부 +0.93),
    반대 부호는 λ 5.72(참여도 0.90)·안정 — 두 크기 다 nan이 섞여 "모른다"가 되어 틀린 부호로 탐색했고, 안정
    캡이 |k|를 절반으로 깎아 capped(통과 쪽 사유)로 끝나 양의 되먹임 표본이 적합에 들어갔다(예제 기체
    M0.1~0.13 8점 · 쇼케이스 M0.1~0.15 16점. 동압이 높은 이웃 점은 sign_mismatch로 빠졌다). 그래서 nan은
    **발산으로 가른다**: nan인 쪽 조성이 발산하고 다른 쪽은 발산하지 않으면 nan인 쪽이 나쁘다 — 모드를 못 잰
    것이 아니라 축이 무너진 것이다. 양쪽 다 발산하거나(개루프 더치롤 발산처럼 부호와 무관한 발산) 발산이 nan
    쪽이 아니면 가르지 않는다. 0.1배 탐침에서는 발산으로도 가르지 않는다 — 그 크기의 두 조성은 프리픽스와 거의
    같아서 발산 여부가 갈린다면 부호가 아니라 경계에 앉은 프리픽스 탓이다.

    크기는 방향 탐침(0.1배) → 설계 크기 → 탐색 브래킷(4배)까지 키운다. 설계 크기 너머로 넘어가는 것은 **nan
    때문에 못 가른 경우뿐**이다 — 같은 값(감쇠 지표가 양쪽 다 1.0 과감쇠)은 종전처럼 설계 크기에서 멈춘다. 설계
    크기가 작으면 설계 부호가 아직 발산 전이라 설계 크기에서 못 가를 수 있다 — 더 크게 닫아 본다: 제 부호는 크게
    닫을수록 롤 모드를 실근으로 떼어 내고, 반대 부호는 축을 무너뜨린다(위 뒤집은 쇼케이스 M0.1/h0에서 설계 크기를
    절반 |k| 0.110으로 두면: 설계 크기의 설계 부호는 참여도 0.04·ζ_dr 0.002로 아직 안정, 2배에서 ζ_dr −0.36
    발산·반대 부호 λ 5.72). 실측(쇼케이스·예제·구 기체의 롤 조종 미계수 부호를 뒤집은 격자 53점, 롤 설계 크기
    0.25·0.5·1·2배): 전 배율에서 53/53 sign_mismatch(종전 2배 50 · 1배 29 · 0.5배 14 · 0.25배 10), 뒤집지 않은
    같은 격자는 전 배율 0/53 — 오탐 없음. 끝까지 못 가르면 부호 결함이라 하지 않는다 — 모르는 것을 결함으로
    만들지 않는다."""
    mags = (_DIRECTION_PROBE * mag, mag, 2.0 * mag, _BRACKET_GROWTH * mag)
    for i, m in enumerate(mags):
        up, down = f(m), f(-m)
        if not (math.isnan(up) or math.isnan(down)):
            if up != down:
                return down > up
            if i >= 1:
                return False  # 설계 크기에서도 같은 값 — 더 키워 가를 근거가 아니다(nan이 아니다)
            continue
        if i >= 1 and diverges is not None:
            du, dd = diverges(m), diverges(-m)
            if du != dd and ((du and math.isnan(up)) or (dd and math.isnan(down))):
                return du
    return False


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
                "target": getattr(targets, target_field), "reason": REASON_SEED_REQUIRED,
            }
            notes.append(f"{slot}: {REASON_TEXT[REASON_SEED_REQUIRED]}")
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

        def f_dir(mag, _slot=slot, _lm=lm_axis, _sign=sign, _base=dict(spec_rates),
                  _mk=metric_key, _rf=_rf):
            g = dict(_base)
            g[_slot] = _sign * mag
            return _direction_score(axis_metrics(_lm, g, _rf), _mk)

        def f_div(mag, _slot=slot, _lm=lm_axis, _sign=sign, _base=dict(spec_rates), _rf=_rf):
            g = dict(_base)
            g[_slot] = _sign * mag
            return _closure_diverges(_lm, g, _rf)

        # 방향 판정은 f가 아니라 f_dir로 한다 — 탐색(f)은 종전 그대로 두고, "반대 부호가 낫다"는 단정만
        # 잰 모드끼리 비교하게 한다 (_direction_score 머리말의 실측). 롤 λ만 nan을 낸다 — 그 nan을 가르는
        # 발산 판정(f_div)은 롤 자리에만 넘긴다(감쇠 지표는 nan이 없어 쓰일 일이 없다)
        if _rate_sign_opposes(f_dir, abs(k_design), f_div if metric_key == "roll_lambda" else None):
            gains[slot] = 0.0
            achieved[f"{group}_rate"] = {
                "kind": "damping" if metric_key != "roll_lambda" else "bandwidth",
                "target": target, "reason": REASON_SIGN_MISMATCH,
            }
            notes.append(f"{slot}: {REASON_TEXT[REASON_SIGN_MISMATCH]}")
            continue

        k, entry = _search_rate(lm_axis, lm_prior, group, metric_key, target, sign, abs(k_design),
                                f, act_kw, others_gains=spec_rates, targets=targets)
        gains[slot] = k
        achieved[f"{group}_rate"] = entry
        pending.append((group, axis, metric_key, target, entry["reached"],
                        entry["bracket_growth"], entry["capped"], slot))

    pending = _retune_with_later_closed(axes, design, gains, achieved, notes, pending, act_kw, targets)
    _report_rates_on_final_composition(axes, gains, achieved, notes, pending,
                                       act_kw.get("rate_filters"), act_kw=act_kw, targets=targets)
    return gains, achieved, notes


def _search_rate(lm_axis, lm_prior, group, metric_key, target, sign, k_mag_design, f, act_kw, mag_min=0.0,
                 others_gains=None, targets=None):
    """레이트 자리 하나의 탐색 + 댐퍼 안정 캡 + 레이트 루프 마진 캡 — (k, achieved 레코드).

    f(|k|)는 탐색 조성에서 잰 지표, lm_prior는 그 조성에서 **이 자리만 뺀** 레이트를 접은 A′다(가드·교차 측정의
    플랜트). 1차 패스는 프리픽스 조성(앞 자리만 닫음), 2차 패스는 뒤 자리까지 닫은 조성을 넘긴다 — 탐색·캡·
    교차가 같은 조성을 본다는 규칙은 한 곳에만 적는다. others_gains는 그 조성에서 닫힌 다른 레이트 게인이다 — 마진
    캡(_cap_by_margins)은 A′로 접지 않고 그 루프들을 작동기·지연째 닫아 끊은 루프를 잰다(AS94900 조성). targets가
    None이면 마진 캡을 걸지 않는다.

    mag_min: 크기 하한(2차 패스의 고장 상태 하한 — _retune_with_later_closed). 목표에 처음 닿는 크기가 그보다
    작으면 두 요구를 다 채우는 최소 크기는 하한 쪽이다 — 도달 여부는 그 크기에서 다시 잰다(지표가 봉우리를 지나
    내려갈 수 있다). 캡은 그 뒤에 건다(가드가 하한 아래로 깎으면 호출자가 고장 상태를 다시 본다)."""
    mag, reached, grown = _first_reach_bisect(f, 0.0, 4.0 * k_mag_design, target)
    if mag < mag_min:
        mag = mag_min
        got = f(mag)
        reached = bool(got is not None and math.isfinite(got) and got >= target)
    k_search = sign * mag
    x_rate, u_in = next((x, u) for g, x, u in AXIS_SPECS[lm_axis.axis]["rates"] if g == group)
    k, capped = _cap_by_stability(lm_prior, group, x_rate, u_in, k_search, act_kw)
    # 안정 가드 다음에 마진 가드 — 안정 경계 아래 크기라도 AS94900 여유(설계 목표)를 지키는 크기로 더 줄인다. 이미
    # 지키면 손대지 않는다(가드가 없던 때와 같은 k). 마진이 묶었으면 cap_bound가 "margin"이다(다음 수가 다르다 — 작동기·
    # 지연 예산 또는 목표 지표를 낮춘다)
    others = {s: v for s, v in (others_gains or {}).items() if s != f"{group}.k_rate" and v != 0.0}
    margin_bound = False
    if k != 0.0 and targets is not None:
        k_m, m_cap = _cap_by_margins(lm_axis, group, k, others, act_kw, targets)
        if m_cap is not None:
            k, capped, margin_bound = k_m, m_cap, True
    verdict = (_damper_loop_verdict(lm_prior, group, x_rate, u_in, k, act_kw) if k != 0.0
               else {"spiral_t2_s": None})
    return k, {
        "kind": "damping" if metric_key != "roll_lambda" else "bandwidth",
        "target": target,
        # ωc는 프리픽스 조성에서 잰다 — 검증(schedmap)도 `prior`로 같게 잰다
        "wc": rate_loop_crossover(lm_prior, group, x_rate, u_in, k, **act_kw),
        "capped": capped,
        # 캡이 걸렸으면 **무엇이** 묶었나 — 탐색이 고른 크기에서의 가드 판정(작동기·지연 발산이냐, 나선
        # 기준이냐). 둘은 다음 수가 다르다: 앞은 작동기 예산, 뒤는 목표(나선은 자세 루프 몫)
        "cap_bound": ("margin" if margin_bound
                      else _damper_loop_verdict(lm_prior, group, x_rate, u_in, k_search, act_kw)["bound"]
                      if capped == "capped" else None),
        # 가드가 면제한 느린 나선의 배가시간 [s] — 댐퍼만 닫은 조성에 남는 발산(없으면 None)
        "spiral_t2_s": verdict["spiral_t2_s"],
        "reached": reached,
        # 확장 횟수 — 목표 미달을 보고할 때 "브래킷 탓이 아니다"의 증거가 된다
        "bracket_growth": grown,
    }


def _final_reason(got, target, capped) -> str:
    """최종 조성에서 잰 지표 → 레이트 자리 사유 — 보고와 2차 패스 비교가 같은 식을 쓴다."""
    # 허용오차: 탐색은 **프리픽스 조성**에서 target에 이분 수렴하는데 여기서는
    # **최종 조성**으로 다시 잰다. 조성이 다르므로 값이 목표선 양쪽에 임의로
    # 떨어진다 — 같은 조성에서 재던 시절의 1e-9는 동전 던지기가 된다 (실측:
    # 상대오차 6e-5 미달로 자리 status가 infeasible이 되는 자리가 12건 나왔다)
    # 캡이 걸렸어도 최종 조성에서 목표를 넘겼으면 결함이 아니다 (안정 경계 아래에서 목표 달성 = 정상)
    if got is not None and got >= target * (1.0 - _FINAL_METRIC_RTOL):
        return REASON_OK
    if capped == "no_stable_gain":
        return REASON_NO_STABLE_GAIN
    if capped == "capped":
        return REASON_CAPPED
    return REASON_TARGET_UNREACHED


def _final_reasons(lm_axis, gains, pending_axis, rate_filters) -> dict:
    """축 하나의 레이트 자리 사유를 최종 조성(그 축 레이트 전부 닫음)에서 — {자리: (사유, 지표)}."""
    final_all = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
                 for g, _, _ in AXIS_SPECS[lm_axis.axis]["rates"]}
    fm = axis_metrics(lm_axis, final_all, rate_filters)
    return {slot: (_final_reason(fm[mk], target, capped), fm[mk])
            for _g, _a, mk, target, _r, _gr, capped, slot in pending_axis}


def _failstate_dr(lm_axis, open_gains, rate_filters) -> dict:
    """고장 상태 조성(open_gains — 뒤 댐퍼를 0으로 둔 레이트 게인)의 더치롤 비행성 — {zeta_dr, wn_dr, level, ok}.

    ok = 수준이 _FAILSTATE_DR_LEVEL 이내. 진동 더치롤이 없으면(모드가 실근으로 교환 — lat_metrics가 ζ 1.0·wn None을
    낸다) 감쇠 요구가 걸릴 모드가 없으므로 통과다(level None)."""
    m = axis_metrics(lm_axis, open_gains, rate_filters)
    z, wn = m.get("zeta_dr"), m.get("wn_dr")
    if wn is None:
        return {"zeta_dr": z, "wn_dr": None, "level": None, "ok": True}
    level = FQCriteria().judge_dutch_roll({"zeta": z, "wn": wn})["level"]
    return {"zeta_dr": z, "wn_dr": wn, "level": level,
            "ok": level is not None and level <= _FAILSTATE_DR_LEVEL}


def _retune_with_later_closed(axes, design, gains, achieved, notes, pending, act_kw, targets=None) -> list:
    """2차 패스 — 앞 자리(요)를 **뒤 자리(롤)를 닫은 조성에서** 다시 찾는다.

    successive closure 순서(요 → 롤) 때문에 요 차례에는 롤이 아직 열려 있다. 저동압 델타는 롤 댐퍼 없이는
    더치롤 감쇠가 목표에 닿지 않아(쇼케이스 M0.094/h0: 롤 열림 ζ_dr 최대 0.36) 탐색이 argmax를 채택했고,
    그게 설계값의 4~5배(k 4.2 — 대표 오차 10 °/s에 러더 42°)였다. 롤을 닫은 최종 조성에서는 ζ_dr이 k 0.82
    근처에서 이미 0.5(당시 목표)에 닿는다 — argmax는 "롤 없는 조성에서의 최선"이지 출하 조성의 답이 아니다.

    **탐색 조성에서 닿은 자리에도** 돈다. 종전에는 못 닿은 자리에만 돌았고, 두 영역의 경계에서 표가 뛰었다 — 롤
    열림 봉우리가 목표를 막 넘는 점의 첫 도달 크기는 봉우리 옆이라 크고(그 점 최종 조성 ζ_dr 1.0 — 과감쇠), 바로
    아래 점은 롤을 닫고 다시 찾은 값이다(쇼케이스 표 모드 해면 M0.1263 0.93 → M0.1275 2.67, 마하 0.003 사이 2.9배 —
    접근 속도 42 m/s 바로 위. 쇼케이스 요 표 띠 비 3.00). 롤 열림 조성에서 목표를 내게 하는 것은 **고장 상태**
    (롤 댐퍼가 빠진 상태)에 정상 상태의 설계 목표를 거는 것이다 — 8785C는 고장 상태에 한 단계 낮은 수준을
    허용하고(나선 면제선과 같은 규칙), 그 요구를 과감쇠로 채우는 값은 러더 권한을 쓴다(위 점 k 2.67 — 10 °/s에
    러더 27°). 그래서 설계는 **정상 상태 목표 + 고장 상태 하한**으로 나눈다:
    - 정상 상태: 뒤 자리까지 닫은 최종 조성에서 목표에 처음 닿는 크기(아래 탐색).
    - 고장 상태: 뒤 자리를 연 1차 탐색 조성의 더치롤이 비행성 수준 _FAILSTATE_DR_LEVEL 이내 — 첫 도달 크기가
      그 아래면 하한에 처음 닿는 크기로 올린다(두 요구를 다 채우는 최소 크기). 요 댐퍼만으로 그 수준이 어떤
      크기에서도 안 서면 하한을 걸지 않는다(1차 값도 못 채운다 — 가를 근거가 없다).
    실측(목표 0.5 — F1 대안 측정과 같은 결과, 하한은 네 설정 어디서도 묶지 않는다): 요 표 띠 비 쇼케이스
    3.00 → 1.23 · 예제 기본 1.77 → 1.48 · 구 기체 1.51 → 1.37, 첫 정지 실패 수 불변(예제 기본 0 · 작은 설정 0 · 구
    기체 11 · 쇼케이스 0). 채택 앵커의 고장 상태는 전부 수준 1이다(최소 ζ 0.226). 그때의 대가: 요 자리가 정상 상태에서
    목표선에 붙었다(목표 0.5 = 판정 목표선 zeta_good — 여유 0). 표본을 뭉개는 표현(1축 표가 고도를 한 축에 겹친
    자리, 다항)의 검증점은 목표선 아래로 내려가 warn이 됐다 — 쇼케이스 기록 설정 요 warn 19 → 35(새로 생긴 16건은
    전부 3000 m 검증점, ζ 0.435~0.494 — 합격선 0.30 위). 종전에는 해면 과감쇠가 그 오차를 덮고 있었다. 그래서
    목표(TuneTargets.zeta_dr)를 목표선 위로 올렸다(0.6 — 근거·실측·러더 대가는 그 칸의 주석): warn 35 → 0,
    요 표 띠 비 쇼케이스 1.26 · 예제 기본 1.44 · 구 기체 1.35.

    뒤 자리(롤)의 게인은 1차 패스 값 그대로 닫는다. 그러면 이 자리의 탐색 조성이 곧 최종 조성이라 목표
    도달이 조성 차이로 흔들리지 않는다. 뒤 자리는 새 프리픽스(바뀐 요)에서 **댐퍼 가드를 다시 통과해야** 하고
    교차는 새 프리픽스에서 다시 잰다(자세 목표 교차가 그 값을 쓴다).

    **최종 조성을 개선할 때만** 채택한다: 그 축에서 1차 패스가 목표를 달성한 자리가 하나도 미달로 떨어지지
    않고, 이 자리가 최종 조성에서 목표를 달성하며, (1차 패스에서도 달성했다면) 더 작은 |k|로 달성할 것 —
    목표를 넘는 과감쇠(ζ_dr 1.0)는 개선이 아니라 조종면 권한의 낭비다. 목표 미달끼리는 최종 지표가 오를 때만.
    그리고 1차 값이 고장 상태 하한 안이었으면 채택 값도 하한 안일 것(캡이 하한 아래로 깎으면 불채택 — 비행성
    요구가 권한 절약보다 앞선다).
    반환: 채택 여부가 반영된 pending."""
    rf = act_kw.get("rate_filters")
    for i, (group, axis, metric_key, target, reached, grown, capped, slot) in enumerate(list(pending)):
        order = [g for g, _, _ in AXIS_SPECS[axis]["rates"]]
        later = order[order.index(group) + 1:]
        # 뒤 자리가 1차 패스에서 실제로 튜닝돼 닫혀 있어야 한다 (0 댐퍼면 조성이 프리픽스와 같다)
        if not later or not all(
                gains.get(f"{g}.k_rate", 0.0) != 0.0 and any(p[0] == g for p in pending) for g in later):
            continue
        lm_axis = axes[axis]
        base = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0) for g in order}
        base[slot] = 0.0
        lm_prior = close_rates(lm_axis, base, rf)
        sign = math.copysign(1.0, float(design[slot]))
        k_mag_design = abs(float(design[slot]))
        # 고장 상태 조성 = 1차 탐색 조성(앞 자리는 채택값, 뒤 자리는 열림) — 이 자리만 변수
        open_base = {f"{g}.k_rate": 0.0 if g in later else gains.get(f"{g}.k_rate", 0.0) for g in order}

        def f(mag, _slot=slot, _base=dict(base), _lm=lm_axis, _mk=metric_key, _sign=sign):
            g = dict(_base)
            g[_slot] = _sign * mag
            return _metric(_lm, g, _mk, rf)

        def fs(mag, _slot=slot, _base=dict(open_base), _lm=lm_axis, _sign=sign):
            return _failstate_dr(_lm, {**_base, _slot: _sign * mag}, rf)

        k2, entry2 = _search_rate(lm_axis, lm_prior, group, metric_key, target, sign, k_mag_design, f, act_kw,
                                  others_gains=base, targets=targets)
        fs2 = fs(abs(k2))
        floor_mag, floor_attainable = None, True
        if not fs2["ok"]:
            # 고장 상태 하한에 처음 닿는 크기 — 1차 탐색과 같은 브래킷·확장 규칙(첫 도달이라 봉우리 너머는 안 본다)
            m_fs, floor_attainable, _grown = _first_reach_bisect(
                lambda mag: 1.0 if fs(mag)["ok"] else 0.0, 0.0, 4.0 * k_mag_design, 1.0)
            if floor_attainable and m_fs > abs(k2):
                floor_mag = m_fs
                k2, entry2 = _search_rate(lm_axis, lm_prior, group, metric_key, target, sign, k_mag_design, f,
                                          act_kw, mag_min=m_fs, others_gains=base, targets=targets)
                fs2 = fs(abs(k2))
        # 고장 상태 조건은 "1차 값이 지키던 하한을 버리지 않는다"다 — 1차 값도 하한 밖이면(요 댐퍼만으로는 안 서는
        # 자리 포함) 2차 패스가 그 상태를 나쁘게 만드는 것이 아니다
        failstate_ok = fs2["ok"] or not fs(abs(gains[slot]))["ok"]
        cand = {**gains, slot: k2}
        pending_axis = [p for p in pending if p[1] == axis]
        cand_pending = [(p[0], p[1], p[2], p[3], entry2["reached"], entry2["bracket_growth"],
                         entry2["capped"], p[7]) if p[7] == slot else p for p in pending_axis]
        before = _final_reasons(lm_axis, gains, pending_axis, rf)
        after = _final_reasons(lm_axis, cand, cand_pending, rf)
        # 뒤 자리 — 바뀐 프리픽스에서 가드를 다시 통과하나, 교차는 얼마인가
        later_ok, later_meta = True, {}
        for g in later:
            prefix = {f"{h}.k_rate": cand.get(f"{h}.k_rate", 0.0) for h in order}
            for h in order[order.index(g):]:
                prefix[f"{h}.k_rate"] = 0.0
            lm_pre = close_rates(lm_axis, prefix, rf)
            x_rate, u_in = next((x, u) for h, x, u in AXIS_SPECS[axis]["rates"] if h == g)
            kg = cand[f"{g}.k_rate"]
            vg = _damper_loop_verdict(lm_pre, g, x_rate, u_in, kg, act_kw)
            if not vg["stable"]:
                later_ok = False
                break
            # 뒤 자리의 레이트 루프 마진 — 1차 값(바뀌기 전 앞 자리를 닫은 조성)에서 설계 목표를 지켰으면 바뀐 앞 자리를
            # 닫은 조성에서도 지켜야 한다. 뒤 자리는 1차 패스에서 이미 마진 가드를 거쳤다 — 2차 패스가 그 여유를 깎는
            # 앞 자리 값을 들여오면 가드가 막은 것을 되살린다
            if targets is not None and (
                    _rate_margin_verdict(rate_loop_margins(lm_axis, g, gains, act_kw), targets) != "short"
                    and _rate_margin_verdict(rate_loop_margins(lm_axis, g, cand, act_kw), targets) == "short"):
                later_ok = False
                break
            later_meta[g] = {"wc": rate_loop_crossover(lm_pre, g, x_rate, u_in, kg, **act_kw),
                             "spiral_t2_s": vg["spiral_t2_s"]}
        no_regress = all(not (before[s][0] == REASON_OK and after[s][0] != REASON_OK) for s in before)
        was_ok = before[slot][0] == REASON_OK
        if after[slot][0] == REASON_OK:
            better = (not was_ok) or abs(k2) < abs(gains[slot])
        else:
            better = (not was_ok) and after[slot][1] > before[slot][1]
        k1 = gains[slot]
        # 재탐색이 0을 냈다 = 뒤 댐퍼만으로 목표가 선다는 뜻이지만, 그 자리의 댐퍼를 끄는 해는 "다시 튜닝한 값"이
        # 아니다 — 표에 0이 박히면 실패 자리값과 구별이 안 된다(적합 제외 규칙이 막으려던 모양). 채택하지 않는다
        nonzero = k2 != 0.0
        failstate = {**fs2, "floor_level": _FAILSTATE_DR_LEVEL, "floor_mag": floor_mag,
                     "floor_attainable": floor_attainable}
        if later_ok and no_regress and better and nonzero and failstate_ok:
            gains[slot] = k2
            achieved[f"{group}_rate"] = {**entry2, "second_pass": {
                "adopted": True, "k_first": k1, "metric_first": before[slot][1], "reached_first": bool(reached),
                "failstate": failstate}}
            for g, meta in later_meta.items():
                achieved[f"{g}_rate"].update(meta)  # 뒤 자리의 교차·면제 나선은 바뀐 프리픽스의 값으로
            pending[i] = cand_pending[[p[7] for p in cand_pending].index(slot)]
            why_first = (f"탐색 조성(뒤 자리 열림)에서 목표 {target} 미달이라" if not reached
                         else f"탐색 조성(뒤 자리 열림)에서 목표 {target}에 닿은 k {k1:.4g}이 최종 조성에서"
                              f" {metric_key} {before[slot][1]:.4g}" + ("(과감쇠)라" if was_ok
                                                                         else "(뒤 댐퍼가 끌어내려 목표 미달)이라"))
            fs_text = ("진동 더치롤 없음" if fs2["wn_dr"] is None
                       else f"ζ_dr {fs2['zeta_dr']:.3g} · 수준 {fs2['level'] if fs2['level'] is not None else '밖'}")
            notes.append(
                f"{slot}: {why_first} 뒤 댐퍼({', '.join(later)})를 닫은 조성에서 다시 찾았다 — k {k1:.4g} → {k2:.4g},"
                f" 최종 조성 {metric_key} {before[slot][1]:.4g} → {after[slot][1]:.4g}. 뒤 댐퍼가 빠진 고장 상태"
                f" {fs_text}" + (f" (비행성 수준 {_FAILSTATE_DR_LEVEL} 하한이 크기를 {floor_mag:.4g}로 올렸다)"
                                 if floor_mag is not None else ""))
        else:
            why = ("재탐색이 댐퍼를 끄는 해(0)를 냈다" if not nonzero
                   else "뒤 댐퍼가 바뀐 프리픽스에서 가드(안정·레이트 루프 마진)를 넘지 못한다" if not later_ok
                   else "다른 자리가 목표 미달로 떨어진다" if not no_regress
                   else f"뒤 댐퍼가 빠진 고장 상태의 더치롤이 비행성 수준 {_FAILSTATE_DR_LEVEL} 밖이다"
                   if not failstate_ok
                   else "최종 조성이 나아지지 않는다")
            achieved[f"{group}_rate"]["second_pass"] = {"adopted": False, "k_second": k2,
                                                        "metric_second": after[slot][1], "why": why,
                                                        "reached_first": bool(reached), "failstate": failstate}
            notes.append(f"{slot}: 뒤 댐퍼를 닫은 조성의 재탐색(k {k2:.4g})은 불채택 — {why}")
        if not floor_attainable:
            notes.append(
                f"{slot}: 뒤 댐퍼가 빠진 고장 상태의 더치롤은 이 자리 크기로 비행성 수준 {_FAILSTATE_DR_LEVEL}에 어떤"
                f" 크기에서도 들지 못한다(ζ_dr {fs2['zeta_dr']:.3g}) — 고장 상태 하한은 걸지 않았다")
    return pending


def _report_rates_on_final_composition(axes, gains, achieved, notes, pending,
                                       rate_filters=None, act_kw=None, targets=None):
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
    무엇으로 판정하는가**뿐이다. 예외 하나 — 뒤 자리가 있는 앞 자리(요)는
    _retune_with_later_closed가 뒤 자리를 닫은 조성에서 다시 찾고, 최종 조성을 개선할 때만 그 값을 쓴다.

    레이트 루프 마진(rate_loop_margins — AS94900 끊은 루프)도 최종 조성에서 다시 재 싣는다(pm_deg·gm_db·loop_margins —
    검증 schedmap과 같은 조성·같은 자). act_kw가 없으면(작동기 인자를 모르는 호출) 싣지 않는다.
    """
    for group, axis, metric_key, target, reached, grown, capped, slot in pending:
        lm_axis = axes[axis]
        final_all = {f"{g}.k_rate": gains.get(f"{g}.k_rate", 0.0)
                     for g, _, _ in AXIS_SPECS[axis]["rates"]}
        fm = axis_metrics(lm_axis, final_all, rate_filters)
        got = fm[metric_key]
        # 사유는 **왜 목표에 못 갔나**를 가른다 (식은 _final_reason 한 곳 — 2차 패스 비교도 그것을 쓴다)
        reason = _final_reason(got, target, capped)
        achieved[f"{group}_rate"].update({
            metric_key: got,
            "reason": reason,
            # λ의 |Re|가 지운 부호와, 그 실근이 롤 상태를 얼마나 담았나 —
            # 발산근이면 수치와 무관하게 실패이고, 참여도가 낮으면 애초에 롤
            # 대역폭을 잰 게 아니다 (판정은 criteria.judge_bandwidth 소관)
            "unstable": bool(fm.get("roll_unstable", False)),
            "participation": fm.get("roll_participation"),
        })
        lm_rec = rate_loop_margins(lm_axis, group, final_all, act_kw) if act_kw is not None else None
        if lm_rec is not None:
            # 대표 지표 옆에 여유 두 수를 나란히 — criteria.shortfall·분류기(_tuned_judgement)가 같은 키로 읽는다
            achieved[f"{group}_rate"].update({"pm_deg": lm_rec["pm_deg"], "gm_db": lm_rec["gm_db"],
                                              "loop_margins": lm_rec})
            if targets is not None and _rate_margin_verdict(lm_rec, targets) == "short":
                # 가드는 탐색 조성에서 묶었다 — 뒤에 닫힌 자리·2차 패스가 조성을 바꿔 최종 조성에서 목표 아래로 내려간
                # 경우다. 조용히 넘기지 않는다(검증이 같은 자로 다시 판정한다)
                notes.append(
                    f"{slot}: 최종 조성의 레이트 루프 마진 {_rate_margin_text(lm_rec)}이 설계 목표"
                    f" PM {targets.pm_deg:g}°/GM {targets.gm_db:g} dB 아래다 — 탐색 조성에서 건 마진 가드 뒤에 조성이 바뀌었다")
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
        entry = achieved[f"{group}_rate"]
        if capped in ("capped", "no_stable_gain") and entry.get("cap_bound") == "margin":
            # 안정은 섰는데 여유가 모자랐다 — 작동기·지연 예산이 댐퍼 교차를 묶는다(목표 지표를 내려면 교차를 작동기
            # 대역 쪽으로 밀어야 하는데 거기서 AS94900 여유가 깎인다)
            fin = entry.get("loop_margins")
            notes.append(
                f"{slot}: 레이트 루프 마진 가드 적용 — AS94900 끊은 루프(같은 축 다른 레이트 루프 닫음, 작동기·지연 포함)"
                f" 여유가 설계 목표 PM {targets.pm_deg:g}°/GM {targets.gm_db:g} dB를 지키는 크기로 |k|를 묶었다"
                + (f" (최종 조성 {_rate_margin_text(fin)})" if fin else "")
                + f". 목표 {target}에 못 미치면 작동기 대역폭·지연 예산을 늘리거나 목표를 낮춘다")
        elif capped == "capped" and entry.get("cap_bound") == "spiral":
            # 작동기·지연 발산이 아니라 나선 기준이 묶었다 — 다음 수가 다르다(작동기 예산은 답이 아니다)
            notes.append(
                f"{slot}: 댐퍼 안정 캡 적용 — 댐퍼만 닫은 조성에서 나선 배가시간이 비행성 기준선"
                f"({_SPIRAL_T2_MIN_S:g} s) 아래로 내려가는 크기에서 묶었다 (작동기·지연 불안정이 아니다)."
                " 이 조건에서 목표를 내려면 나선을 자세 루프에 맡기는 판단이 필요하다 — 목표를 낮추거나"
                " 비행성 기준(수준)을 검토한다")
        elif capped == "capped":
            notes.append(f"{slot}: 댐퍼 안정 캡 적용 — 작동기·지연 포함 폐루프 안정 경계 아래로 축소")
        if entry.get("spiral_t2_s") is not None and entry.get("cap_bound") != "spiral":
            notes.append(
                f"{slot}: 댐퍼만 닫은 조성에 느린 나선 발산이 남는다(배가 {entry['spiral_t2_s']:.3g} s ≥"
                f" 비행성 기준선 {_SPIRAL_T2_MIN_S:g} s) — 댐퍼 가드는 면제한다. 나선은 자세 루프가 잡는다"
                " (자세까지 닫은 전체 폐루프를 따로 확인한다)")
        if capped == "no_stable_gain" and entry.get("cap_bound") != "margin":
            # 경계를 찾은 게 아니라 댐퍼를 끈 것이다 — 로그가 그렇게 말해야 한다
            notes.append(
                f"{slot}: 안정한 댐퍼 게인이 없다 — 어떤 |k|도 작동기·지연 포함 폐루프를"
                " 안정화하지 못해 0으로 두었다 (개루프 불안정 플랜트이거나 조건부 안정 구간)."
                " 이 축의 판정은 감쇠 미달로 흐르고 structural_limit 후보가 된다"
            )


def _rate_margin_text(m) -> str:
    """note용 레이트 루프 마진 표기 — "PM 47.2° @ 12.4 rad/s · GM 7.10 dB @ 18.9 rad/s"(교차가 없으면 ∞)."""
    def one(label, v, w, unit, fmt):
        if math.isnan(v):
            return f"{label} 판정 불가"
        if not math.isfinite(v):
            return f"{label} ∞"
        return f"{label} {v:{fmt}}{unit} @ {w:.3g} rad/s"
    txt = one("PM", m["pm_deg"], m["wcp"], "°", ".1f") + " · " + one("GM", m["gm_db"], m["wcg"], " dB", ".2f")
    return txt + (" (발산 — 여유 정의 안 됨)" if m.get("divergent") else "")


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

    m은 closure.att_margins의 결과다 — gm_db는 **경계까지의 거리**다. 공칭 폐루프가 안정인 루프의 이득 감소 쪽
    경계(control.margin이 고른 음의 dB)는 미달이 아니라 반대 방향의 여유라 |dB|로 바뀌어 온다
    (closure.gain_margin_sides — 개루프 불안정 A′, 나선 면제의 몫).
    """
    pm, gm = float(m["pm_deg"]), float(m["gm_db"])
    if math.isnan(pm) or math.isnan(gm):
        return "na"  # 판정 불가 — 통과도 미달도 아니다
    if pm < targets.pm_deg or gm < targets.gm_db:
        return "short"
    return "ok"


def _gm_text(ach) -> str:
    """note용 GM 표기 — 이득 감소 쪽 경계를 나눠 실었으면(closure.gain_margin_sides) 양쪽을 함께."""
    if "gm_down_db" not in ach:
        return f"GM {ach['gm_db']:.1f} dB"
    if not ach.get("gm_nominal_stable"):
        return f"GM {ach['gm_db']:.1f} dB(공칭 폐루프 불안정 — 감소 쪽 경계)"
    return (f"GM {ach['gm_db']:.1f} dB(감소 쪽 경계 {ach['gm_down_db']:.1f}·증가 쪽 {ach['gm_up_db']:.1f} dB"
            " 가운데 가까운 쪽)")


def _tune_att(lm_axis, group, rate_gains, rate_wc, design, targets, act_kw) -> tuple:
    """자세 PI 루프쉐이핑 + 마진 검증 백오프 — (kp, ki, achieved, reason, evals)."""
    kp_design = float(design[f"{group}.kp"])
    if kp_design == 0.0:
        # 부호를 +1로 짐작하지 않는다 — 틀린 부호도 oriented_margins가 뒤집어 건강해 보이게 만든다
        return 0.0, 0.0, {"target_pm_deg": targets.pm_deg, "target_gm_db": targets.gm_db,
                          "target_wc_frac": targets.wc_att_ok_frac}, REASON_SEED_REQUIRED, 0
    sign = math.copysign(1.0, kp_design)
    # rate_wc = 0이면(댐퍼가 0으로 캡됐거나 교차를 못 찾음) 목표 교차가 **다른 물리량**
    # 으로 바뀐다 — 개루프 최속 진동 wn. 조용히 갈아타지 않고 플래그로 남긴다
    wc_fallback = not (rate_wc > 0)
    wc0 = (rate_wc if rate_wc > 0 else wn_reference(lm_axis)) / targets.wc_ratio_att
    wc = wc0
    evals = 0
    best = None
    last_verdict = "na"
    inverted_ok = False  # 뒤집은 루프에서만 마진이 통과했다 — 끝까지 +방향 통과가 없으면 부호 결함
    unstable_ok = False  # 마진은 통과했는데 전체 폐루프가 발산한 후보가 있었다
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
        m, orient = att_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
        evals += 1
        # wc0(초기 목표 교차)을 함께 낸다 — 이게 없으면 "대역폭이 얼마나 무너졌나"가
        # 결과 밖에서 계산 불가능하다. 판정식 wc ≥ wc_att_ok_frac·wc0의 분모다
        verdict = _att_margin_verdict(m, targets)
        best = (kp, ki, {**m, "orientation": orient, "wc_att": wc, "wc0": wc0,
                         "wc_fallback": wc_fallback, "target_pm_deg": targets.pm_deg,
                         "target_gm_db": targets.gm_db,
                         "target_wc_frac": targets.wc_att_ok_frac})
        if orient != 1:
            # 루프를 뒤집어야만 PM>0 — 설계 부호가 이 플랜트와 반대(양의 되먹임)다. 뒤집은 루프의 마진은 통과가
            # 아니다. 백오프는 계속한다: 부호는 맞는데 이 교차에서만 +루프가 무너진 경우와 가르려고
            if verdict == "ok":
                inverted_ok = True
            last_verdict = "sign"
            wc *= targets.backoff
            continue
        if verdict == "ok" and not _full_loop_stable(lm_axis, rate_gains, kp, ki, orient, act_kw):
            # 보드 마진은 레이트를 **이상 폐쇄한** A′ 위의 SISO 판정이다 — 댐퍼 경로의 작동기·지연이 섞인 실제
            # 조성이나 개루프 불안정 플랜트에서는 폐루프 안정을 보장하지 않는다(구 기체 M0.61/h0: 피치 PM·GM
            # 통과인데 합친 루프가 17 rad/s에서 발산). 발산하는 해는 수용하지 않고 백오프를 계속한다
            unstable_ok = True
            last_verdict = "unstable"
            wc *= targets.backoff
            continue
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
    if inverted_ok:
        return kp, ki, ach, REASON_SIGN_MISMATCH, evals
    if unstable_ok:
        # 마진이 서는 교차는 있었으나 그 해들이 전부 발산했다 — "마진 미달"이 아니다
        return kp, ki, ach, REASON_LOOP_UNSTABLE, evals
    # 백오프를 다 쓰고도 **판정 불가로만** 끝났으면 "마진 미달"이 아니다 —
    # 교차가 없어 잴 수 없었던 것이고, 그 둘을 뭉개면 안내가 엉뚱한 예산을 가리킨다
    return kp, ki, ach, (REASON_NA_NO_CROSSOVER if last_verdict == "na"
                         else REASON_MARGIN_FLOOR), evals


def tune_point(
    lm_full, design, *, targets=None,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
    rate_filters=None, polish=False, max_evals=60,
) -> dict:
    """한 운영점의 SCAS **게인** 7자리 자동 튜닝 — {"gains", "achieved", "slots", ...}.

    slots: {자리 이름: {"status", "reason", "target", "achieved"}} — **판정의 단위**.
    **게인 자리(7)와 판정 자리(5)는 다른 것을 센다** — 손잡이가 7개고 그것으로 성형하는
    SISO 루프가 5개다. 판정 자리는 pitch_rate·yaw_rate·roll_rate·pitch_att·roll_att이고 이름은 검증
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
        # 부호 결함·부호 모름은 마무리로 구제하지 않는다 — 마무리도 PM>0인 방향을 골라 주므로 틀린 부호를 살려 낸다
        if st not in (REASON_OK, REASON_SIGN_MISMATCH, REASON_SEED_REQUIRED) and ach.get("wc0"):
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
            # 백오프와 같은 수용 조건 — 마진 + 대역폭 하한 + **전체 폐루프 안정**(마무리는 보드 마진만 보고
            # 게인을 밀므로 발산하는 해를 낼 수 있다: 지연 0.1 s 피치 구제 해가 10 rad/s에서 +0.21 발산)
            if ach2.get("polished") and ach2.get("orientation") == 1 \
                    and _att_margin_verdict(ach2, targets) == "ok" \
                    and _bandwidth_ok(ach2["wc_att"], ach["wc0"], targets) \
                    and _full_loop_stable(lm_axis, rate_gains, kp2, ki2, 1, act_kw):
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
                          f"{_gm_text(ach)}는 통과")
            elif st == REASON_MARGIN_FLOOR:
                detail = (f" — 최선 PM {ach['pm_deg']:.1f}°/{_gm_text(ach)},"
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
        _apply_closed_loop_check(lm_axis, group, gains, achieved, notes, act_kw)
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


# 전체 폐루프가 발산하면 loop_unstable로 **덮는** 자세 자리 사유 — 통과 사유와 대역폭 붕괴("PM/GM은 통과"라 적는
# 사유 — 그 루프가 실제로는 발산하면 안내가 거짓이 된다)다. 백오프·구제는 발산하는 해를 이미 수용하지 않으므로
# 여기 걸리는 것은 선택 마무리(polish=True)가 민 해 같은 나머지 경로다. 마진 바닥·교차 없음·부호 결함·시드 필요·
# 기저 무의미는 덮지 않는다 — 그 문구가 원인을 말하고, 발산 여부는 closed_loop 레코드에 그대로 남는다
_CLOSED_LOOP_OVERRIDES = _PASSING + (REASON_BANDWIDTH_COLLAPSE,)


def _apply_closed_loop_check(lm_axis, group, gains, achieved, notes, act_kw) -> None:
    """3단 — 자세 자리 레코드에 전체 폐루프 판정(closed_loop)을 싣고, 발산하면 사유를 loop_unstable로 바꾼다.

    덮는 사유는 _CLOSED_LOOP_OVERRIDES뿐이다. 판정 레코드는 어느 경우든 싣는다. 댐퍼만 닫은 조성(rates_only)이
    이미 발산하면(나선 면제 규칙으로 판정) 그 축에서 **마지막으로 닫힌 댐퍼** 자리도 loop_unstable이다 — 그 댐퍼의
    가드는 앞 댐퍼를 이상 폐쇄로 접은 프리픽스에서 쟀으므로, 앞 댐퍼 경로의 작동기·지연까지 넣은 합동 조성의
    발산은 그 가드가 못 본 것이다(지연 0.6 s 실측: 요·롤 각자 가드 통과, 둘을 함께 닫으면 3.5 rad/s에서 발산).
    그러면 적합 제외 규칙(orchestrator._fit_exclusions)이 그 댐퍼와 뒤 자리 표본을 함께 뺀다."""
    ach = achieved[f"{group}_att"]
    cl = _closed_loop_check(lm_axis, gains, ach.get("orientation", 1), act_kw)
    ach["closed_loop"] = cl
    if cl["stable"]:
        return
    only = cl["rates_only"]
    if not only["stable"]:
        closed = [g for g, _, _ in AXIS_SPECS[lm_axis.axis]["rates"] if gains.get(f"{g}.k_rate", 0.0) != 0.0]
        last = achieved.get(f"{closed[-1]}_rate") if closed else None
        if last is not None and last.get("reason") not in SLOT_DESIGN_FAILED:
            last["reason"] = REASON_LOOP_UNSTABLE
            notes.append(f"{closed[-1]}.k_rate: 댐퍼를 함께 닫은 조성(작동기·지연 포함)이 서지 않는다"
                         f" — {_closed_loop_text(only)}. 각 댐퍼 가드는 앞 댐퍼를 이상 폐쇄로 보고 통과했다")
    made = "작동기 대역 공진을" if cl["bound"] == "actuator_resonance" else "발산을"
    where = ("레이트 댐퍼만 닫아도 이미 서지 않는다 — 댐퍼 조성(작동기·지연 포함)이 먼저다" if not only["stable"]
             else f"레이트 댐퍼만 닫은 조성은 안정이다 — 자세 루프가 {made} 만든다")
    if ach.get("reason") == REASON_LOOP_UNSTABLE:
        # 백오프가 이미 loop_unstable로 끝냈다(마진이 서는 해가 전부 서지 않았다) — 사유 문구는 일반형뿐이라
        # 무엇이 걸렸는지(걸린 극)를 여기서 덧붙인다
        notes.append(f"{group}.kp/ki: 백오프 최선해의 전체 폐루프 — {_closed_loop_text(cl)}. {where}")
        return
    if ach.get("reason") not in _CLOSED_LOOP_OVERRIDES:
        return
    ach["reason"] = REASON_LOOP_UNSTABLE
    notes.append(f"{group}.kp/ki: {REASON_TEXT[REASON_LOOP_UNSTABLE]} — {_closed_loop_text(cl)}. {where}")


def _closed_loop_text(rec) -> str:
    """폐루프 판정 레코드(_closed_loop_check 또는 그 rates_only) → note용 한 구절 — 무엇이 걸렸고 **걸린 극**이 무엇인가.

    작동기 대역 공진은 극이 전부 안정한 채 걸리므로 실부 최대 극이 아니라 그 대역에서 ζ가 가장 작은 극을 적는다
    (_failing_pole)."""
    if rec.get("worst_pole") is None:
        return str(rec.get("bound"))
    re_, im = rec["worst_pole"]
    if rec["bound"] == "actuator_resonance":
        return (f"작동기 대역 공진 감쇠 부족, ζ {rec['worst_zeta']:.3g} < 하한 {_ZETA_ACT_MIN:g}"
                f" (극 {re_:+.3g} ± {im:.3g}j rad/s)")
    if rec["bound"] == "spiral" and rec.get("spiral_t2_s") is not None:
        return (f"느린 나선 발산, 배가 {rec['spiral_t2_s']:.3g} s < 비행성 기준선 {_SPIRAL_T2_MIN_S:g} s"
                f" (극 {re_:+.3g})")
    return f"발산, 최대 극 실부 {re_:+.3g} (허수부 {im:.3g} rad/s)"


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
        m, _ = att_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
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
        m, orient = att_margins(att_margin_loop(lm_axis, rate_gains, kp0, ki0, **act_kw))
        return kp0, ki0, _ach(m, orient), 1
    # 초기 simplex를 **명시**한다. x0 = [0, 0]이면 scipy는 0 성분에 zdelt = 0.00025를
    # 써서 변 길이가 0.025%인 simplex를 만든다 — 이 함수가 켜져 있어도 게인이
    # 사실상 안 움직였다 (실측 Δlog kp = 0.00025 그대로 종료).
    res = minimize(cost, [0.0, 0.0], method="Nelder-Mead",
                   options={"maxfev": max_evals, "xatol": 1e-3, "fatol": 1e-3,
                            "initial_simplex": _POLISH_SIMPLEX})
    kp, ki = kp0 * math.exp(res.x[0]), ki0 * math.exp(res.x[1])
    m, orient = att_margins(att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw))
    if math.isfinite(m["pm_deg"]) and m["pm_deg"] >= targets.pm_deg:
        return kp, ki, _ach(m, orient, {"polished": True}), int(res.nfev) + 1
    m0, o0 = att_margins(att_margin_loop(lm_axis, rate_gains, kp0, ki0, **act_kw))
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
