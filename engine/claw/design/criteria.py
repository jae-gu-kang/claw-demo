"""마진 합격기준 — 판정선의 엔진 이관 (04 §2 · 합격기준 수치는 파라미터 관리 계층이 정본 — 02 §5.5).

지금까지 판정선은 웹 표시 계층에만 있었다 (web/js/lib/plot.js marginColor,
views/margins.js gmColor — PM 30/45°, GM 6/10 dB). 자동 설계 루프는 판정을
기계가 하므로 기준이 엔진에 있어야 하고, 웹은 /api/design/defaults로 이 값을
받아 색칠한다 (하드코딩은 폴백).

의미 구분 — 합격선·목표선·표시 음영선의 세 층:
- 합격(pass) = pm_deg ≥ pm_min_deg ∧ gm_db ≥ gm_min_db  (관례 45° / 6 dB)
  자세 자리의 gm_db는 **안정 경계까지의 거리**다(closure.att_margins — 공칭 폐루프가 안정인 루프의 이득 감소
  쪽 경계는 |dB|로 바뀌어 온다. 개루프 불안정 A′의 음의 GM을 미달로 읽지 않는다)
- pm_bad_deg(30°)는 표시용 심각선(30~45° 주의 음영) — 자동화에서는 45° 미만이 곧 fail
- gm_good_db·zeta_good은 **설계 목표선**이다 — 합격이되 목표 미달이면 warn
- 레이트 자리도 같은 PM·GM 선으로 판다 — AS94900 끊은 루프 여유(tune.rate_loop_margins, 같은 축 다른 레이트 루프
  닫음·작동기+Padé)를 모드 지표 판정과 합친다(judge_rate_loop). 종전에는 레이트 자리가 ζ·λ로만 판정돼 여유 미달이
  드러나지 않았다

warn이 뜻하는 것: "합격선은 넘겼으나 튜너가 겨냥한 설계 목표에는 못 미친다".
그러려면 목표선이 튜너 목표(TuneTargets) **이하**여야 한다 — 그렇지 않으면 튜닝이
완벽히 성공한 점조차 warn으로 찍혀 warn이 아무 정보도 못 준다. 실제로 그랬다:
gm_good_db 10 dB > TuneTargets.gm_db 8 dB라 자유 게인 최적점이 구조적으로 warn이었고,
사용자에게는 "경고가 압도적으로 많다"로 보였다. 이 정합은 AutoDesignConfig.__post_init__이
강제한다 (기준과 목표가 만나는 유일한 자리 — 한쪽만 조정하면 거기서 걸린다).
감쇠는 같기만 해도 모자라다 — 튜너는 앵커에서 목표를 맞추고 출하되는 스케줄은 검증점에서 그보다
내려가므로, 여유 0이면 표현 손실이 곧 warn이다. 그래서 감쇠 목표는 목표선 위에 잰 표현 손실만큼
여유를 둔다 (TuneTargets.zeta_dr 주석 — 요 목표를 목표선과 같던 0.5에서 0.6으로 올린 근거).

판정 불가(nan — 교차 없음)는 "na"로 낸다. 무한 여유(inf)는 그 축 통과로 본다.
loop_margins가 nan을 nan으로 유지하는 이유(margins.py — 무한 여유 오인 금지)와
같은 원칙이다.

판정어(ok/warn/fail) 옆에 **얼마나**를 낸다 — `shortfall`은 자리 하나의 지표별
{요구, 달성, 부족, 부족 비율}이고 `severity`는 그 비율의 최대값이다. 비율로 재는
이유: PM(도)·GM(dB)·ζ(무차원)·λ(rad/s)는 단위가 달라 절대값으로는 한 줄에 못
세운다. 종전 정렬 축(PM은 도 그대로, ζ는 ×90)이 그걸 근사로 뭉갰고, ×90이라는
환산이 감쇠 부족을 과대평가했다 — PM 35°(합격선 45° 대비 22% 부족, 축에서 35.0)가
ζ 0.28(0.30 대비 6.7% 부족, 축에서 25.2)보다 **덜 심각하게** 정렬됐다. 그 정렬이
곧 분류기의 작업 목록 순서라, 예산이 끊기면 더 급한 자리가 남는다.
"""

import math
from dataclasses import asdict, dataclass

import numpy as np

from claw.analysis.fq import LN2, FQCriteria
from claw.design.closure import _WN_FLOOR_FRAC, wn_reference
from claw.params.paramset import canonical_hash

# 감쇠 지표가 entry에 실리는 키들 — 자리 종류마다 이름이 다르다 (schedmap은 "zeta",
# tune의 achieved는 지표 이름 그대로 "zeta_sp"/"zeta_dr"). 셋 다 같은 합격선을 쓴다.
_ZETA_KEYS = ("zeta", "zeta_sp", "zeta_dr")


def _one(required: float, achieved, goal=None) -> dict:
    """지표 하나의 부족 레코드 — {required, achieved, deficit, deficit_frac, goal, deficit_goal}.

    deficit는 양수가 부족·음수가 여유. achieved가 nan이면 **None**이다 — 0.0으로
    두면 "교차 없음"과 "부족 없음"이 같은 수가 된다 (종전 deficit()의 결함).
    ±inf는 그대로 둔다: 직렬화 정책이 "inf" 문자열로 구분해 내보내므로(serialize.py)
    nan(=null, 판정 불가)과 섞이지 않는다.

    `goal`은 **목표선**이다 (있는 지표만 — gm_good_db·zeta_good·λ의 lam_good_frac).
    warn은 "합격선은 넘겼으나 목표선 미달"이라는 뜻인데, 부족을 합격선으로만 재면
    warn 행이 **자기가 넘긴 선에 대한 여유**를 보여 준다 — "미달 원장"이라는 표에
    "GM 요구 6 dB · 달성 7.22 dB · 여유 1.22 dB"가 뜨고, 정작 못 넘긴 선(8 dB)은
    이름조차 안 나온다. 화면이 warn을 설명하려면 이 값이 있어야 한다.
    정렬 키(severity)는 종전대로 **합격선** 기준이다 — 그래야 fail이 warn보다 앞선다.
    """
    a = float(achieved)
    base = {"goal": None if goal is None else float(goal), "deficit_goal": None}
    if required <= 0.0:
        # 요구선이 0 이하면 비율이 정의되지 않는다. 판정 불가로 흘린다 —
        # 여기서 나누면 잡 스레드가 죽어 "202 뒤 원인 없는 실패"가 된다
        return {**base, "required": required,
                "achieved": a if math.isfinite(a) else None,
                "deficit": None, "deficit_frac": None}
    if math.isnan(a):
        return {**base, "required": required, "achieved": None,
                "deficit": None, "deficit_frac": None}
    d = required - a
    if goal is not None:
        base["deficit_goal"] = float(goal) - a
    return {**base, "required": required, "achieved": a,
            "deficit": d, "deficit_frac": d / required}


@dataclass(frozen=True)
class MarginCriteria:
    pm_min_deg: float = 45.0  # 위상여유 합격선 [deg]
    gm_min_db: float = 6.0  # 이득여유 합격선 [dB]
    pm_bad_deg: float = 30.0  # 표시용 심각선 [deg] (30~45 주의 음영)
    gm_good_db: float = 8.0  # 설계 목표선 [dB] — TuneTargets.gm_db와 같은 값 (6~8 warn)
    zeta_min: float = 0.30  # 레이트 댐퍼 폐쇄 모드 감쇠 합격선 (MIL-8785류 Level 관례 대역)
    # 감쇠 목표선 — 합격이되 이 미만은 warn. 튜너 목표(TuneTargets.zeta_sp·zeta_dr)보다 **아래**에 둔다: 튜너는 앵커에서
    # 목표에 처음 닿는 크기를 골라 앵커 지표가 곧 목표이고, 스케줄 표현(1축 표의 고도 교차·다항)은 검증점에서 그보다
    # 내려간다 — 목표와 같은 선이면 그 표현 손실이 전부 warn이 된다(요 목표가 이 값과 같던 때 쇼케이스 요 warn 35건)
    zeta_good: float = 0.50
    # 롤 대역폭(λ)만 합격선이 **절대값이 아니라 목표 대비 비율**이다 [기본값]. λ는
    # 안정성 마진이 아니라 조종성 성능 지표라 관례적 절대 합격선이 없고, 요구 자체가
    # 그 실행의 튜닝 목표(TuneTargets.roll_lambda)로 주어진다. 비율은 폐쇄망 검증에서
    # 확정할 자리다 (docs -04 §10 "합격기준 허용오차 수치" · "롤 대역폭 비율 문턱").
    lam_min_frac: float = 0.5  # 합격선 = 목표 × 이 값
    lam_good_frac: float = 0.8  # 목표선 = 목표 × 이 값 (이 사이는 warn)
    # λ를 잰 실근이 롤 상태를 이만큼도 안 담고 있으면 **롤 대역폭을 잰 게 아니다**
    # → na. 댐퍼가 약하면 롤 모드가 더치롤·나선과 합쳐져 실근으로 존재하지 않는데,
    # 그때 남은 실근의 |Re|를 롤 대역폭이라 부르면 조용한 오답이 된다 [기본값].
    # 상한은 두지 않는다 — participation factor는 **1을 넘을 수 있다**. 모드별 상태
    # 합이 1인 것은 부호 있는 합이고, 개별 |V[p,k]·V⁻¹[k,p]|는 비정규 행렬에서 1을
    # 넘는다 (데모 실측 1.002~1.009). 1로 막으면 더 엄한 설정이 막힌다
    lam_part_min: float = 0.5

    def __post_init__(self):
        # 합격선의 양수성 — shortfall이 요구선으로 나눈다. 종전 deficit()은 나눗셈이
        # 없어 이 노출이 없었는데, 서버가 criteria를 통째로 덮어쓸 수 있으므로
        # (routes/design.py config.criteria) 0을 넣으면 첫 VERIFY에서 잡이 죽는다
        for name in ("pm_min_deg", "gm_min_db"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name}은 양수여야 함: {getattr(self, name)}")
        if not self.pm_bad_deg <= self.pm_min_deg:
            raise ValueError(f"pm_bad_deg({self.pm_bad_deg}) ≤ pm_min_deg({self.pm_min_deg}) 필요")
        if not self.gm_min_db <= self.gm_good_db:
            raise ValueError(f"gm_min_db({self.gm_min_db}) ≤ gm_good_db({self.gm_good_db}) 필요")
        if not 0.0 < self.zeta_min <= self.zeta_good:
            raise ValueError(f"0 < zeta_min({self.zeta_min}) ≤ zeta_good({self.zeta_good}) 필요")
        if not self.lam_part_min > 0.0:
            raise ValueError(f"lam_part_min은 양수: {self.lam_part_min}")
        if not 0.0 < self.lam_min_frac <= self.lam_good_frac <= 1.0:
            raise ValueError(
                f"0 < lam_min_frac({self.lam_min_frac}) ≤ lam_good_frac"
                f"({self.lam_good_frac}) ≤ 1 필요"
            )

    def judge_damping(self, zeta: float) -> str:
        """폐쇄 모드 감쇠비 → 'ok' | 'warn' | 'fail' — 레이트 댐퍼 자리의 판정.

        순수 P 레이트 루프는 SISO 마진이 병리적(DC 0·장주기 교차 아티팩트)이라
        고전 판정 기준인 모드 감쇠로 본다 (closure.py 머리말).
        """
        z = float(zeta)
        if math.isnan(z):
            return "na"
        if z < self.zeta_min:
            return "fail"
        if z < self.zeta_good:
            return "warn"
        return "ok"

    def judge(self, margins: dict) -> str:
        """{pm_deg, gm_db} → 'ok' | 'warn' | 'fail' | 'na'.

        na: 어느 한쪽이 nan(교차 없음 — 판정 불가). fail로 뭉개면 분류기가
        엉뚱한 처방을 내므로 별도 상태로 남긴다.
        """
        pm = float(margins["pm_deg"])
        gm = float(margins["gm_db"])
        if math.isnan(pm) or math.isnan(gm):
            return "na"
        if pm < self.pm_min_deg or gm < self.gm_min_db:
            return "fail"
        if gm < self.gm_good_db:
            return "warn"
        return "ok"

    def judge_pm(self, pm_deg: float) -> str:
        """PM 한 축 → 'ok' | 'fail' | 'na'. PM에는 목표선이 없다(합격 아니면 fail — judge와 같은 선).

        마진 지도처럼 PM·GM을 칸마다 따로 칠하는 화면이 판정을 다시 짜지 않게 축별로 낸다 —
        judge()는 두 축의 합산이고, 그 합산이 `combine_margin_status(judge_pm, judge_gm)`와 같다(테스트가 묶는다).
        """
        pm = float(pm_deg)
        if math.isnan(pm):
            return "na"
        return "fail" if pm < self.pm_min_deg else "ok"

    def judge_gm(self, gm_db: float) -> str:
        """GM 한 축 → 'ok' | 'warn' | 'fail' | 'na' (합격선 gm_min_db, 목표선 gm_good_db)."""
        gm = float(gm_db)
        if math.isnan(gm):
            return "na"
        if gm < self.gm_min_db:
            return "fail"
        if gm < self.gm_good_db:
            return "warn"
        return "ok"

    def judge_cell(self, margins: dict, closed_loop=None, lm_axis=None) -> dict:
        """마진 맵 칸 하나의 판정 — {"pm_status", "gm_status", "status"}. 칸 판정의 **유일한 출처**다(화면은 색만 칠한다).

        margins는 nyquist_margins 결과({pm_deg, gm_db, …}), closed_loop은 그 결과의 `closed_loop`(이 루프를 닫은
        폐루프가 발산할 때만 있다 — {"stable": False, "unstable": [[Re, Im≥0], …]}), lm_axis는 그 루프를 조립한 축
        모델(나선 면제의 축·느림 문턱을 정한다).

        발산은 자동 설계와 **같은 규칙**(spiral_exempt_verdict — 튜너 댐퍼 가드·rate_loop_margins가 쓰는 것)으로 가른다:
        - 횡축의 느린 나선 실근 하나(배가시간과 무관 — 나선 판정은 가드·전체 폐루프 확인의 몫, rate_loop_margins와
          같다)는 발산으로 치지 않는다 — 여유를 잰 그대로 판정한다(judge_pm·judge_gm·judge).
        - 그 밖의 발산(진동 발산·빠른 실근·둘 이상의 발산극·종축 발산)은 **status "fail"**이다 — 안정 여유가 정의되지
          않는다(judge_rate_loop의 divergent와 같다). pm_status·gm_status는 **잰 그대로** 둔다: 불안정 칸의 PM·GM은
          루프 교차의 부호 있는 고전 판독(nyquist_margins)이라 축별 색은 그 판독의 판정이고, 칸 합산만 발산이 이긴다.
        - lm_axis가 없으면 면제를 가를 수 없다 — 발산은 전부 fail(모르는 것을 통과로 만들지 않는다).
        closed_loop이 없거나 stable이면 judge()와 같다(pm_status·gm_status는 judge_pm·judge_gm)."""
        out = {
            "pm_status": self.judge_pm(margins["pm_deg"]),
            "gm_status": self.judge_gm(margins["gm_db"]),
            "status": self.judge({"pm_deg": margins["pm_deg"], "gm_db": margins["gm_db"]}),
        }
        if closed_loop is None or closed_loop.get("stable", True):
            return out
        poles = np.array([complex(re, im) for re, im in closed_loop.get("unstable") or []])
        exempt = (lm_axis is not None and poles.size > 0
                  and spiral_exempt_verdict(poles, lm_axis)["bound"] != "unstable")
        if not exempt:
            out["status"] = "fail"
        return out

    def judge_rate_loop(self, metric_status: str, margins) -> str:
        """레이트 자리의 합산 판정 — 모드 지표 판정(judge_damping·judge_bandwidth) + AS94900 끊은 루프 여유.

        margins는 tune.rate_loop_margins 결과({pm_deg, gm_db, divergent} — 없으면 None: 잴 루프가 없다)다. 여유는 자세
        자리와 **같은 선**으로 판다(judge — PM·GM 합격선 미만 fail, GM 목표선 미만 warn). 레이트 자리는 종전에 모드
        지표만 봤다 — 쇼케이스 기체 roll_p가 GM 4.1~5.1 dB(합격선 6 dB 미만)인데 λ가 목표라 전부 통과였다.
        발산(divergent — 이 루프를 닫은 폐루프가 느린 나선 밖으로 발산)은 fail이다.

        합산: 어느 쪽이든 fail이면 fail. 모드 지표가 na(롤 모드를 못 잼 등)면 여유가 통과여도 na로 둔다 — 여유 판정이
        "지표를 못 잰 자리"를 판정한 자리로 바꾸면 judged 수가 조용히 는다. 여유가 na(nan)면 모드 지표 판정 그대로.
        나머지는 둘 중 나쁜 쪽(ok < warn < fail)."""
        rank = {"ok": 0, "warn": 1, "fail": 2}
        if margins is None:
            return metric_status
        m_status = "fail" if margins.get("divergent") else self.judge(margins)
        if metric_status == "fail" or m_status == "fail":
            return "fail"
        if metric_status not in rank:
            return metric_status
        if m_status not in rank:
            return metric_status
        return max(metric_status, m_status, key=rank.__getitem__)

    def judge_bandwidth(self, lam: float, target: float, *, unstable: bool = False,
                        participation=None) -> str:
        """롤 수렴 대역폭 λ → 'ok' | 'warn' | 'fail' | 'na' — 목표 대비 비율로 잰다.

        `unstable`은 λ를 만든 실근이 **발산근**이라는 표시다. |Re|는 부호를 지우므로
        (closure.roll_real_mode) 발산근 +12 rad/s가 "목표 12 달성"으로 보인다 —
        수치와 무관하게 fail이다. 튜너 쪽은 댐퍼 안정 캡이 걸러 주지만 검증 쪽에는
        그 게이트가 없어서, 이 인자가 유일한 방어다.

        `participation`은 그 실근이 롤 상태를 얼마나 담았나(≈1이 온전한 지목이고
        비정규 행렬에서는 1을 조금 넘는다 — 실측 1.002~1.009). `lam_part_min`
        미만이면 **롤 대역폭을 잰 게 아니므로** na다 — 통과도 실패도 아니다.
        데모 M0.6에서 롤 게인을 설계값의 0.2배로 줄이면 롤 모드가 실근에서 사라지고
        남은 실근의 참여도가 0.08이 된다. 그 근의 |Re|(6.58)를 "롤 대역폭 목표 12의
        0.55배"라 판정하는 것이 종전 지표가 하던 일이다.
        """
        z = float(lam)
        t = float(target)
        if math.isnan(z) or not math.isfinite(t) or t <= 0.0:
            return "na"
        # 발산근을 **먼저** 본다. 참여도가 낮다고 na로 흘리면, 그 실근이 발산근일 때
        # 아무 데서도 보고되지 않는다 — ζ_dr은 진동쌍만 보고, na는 실패 목록에도
        # judged에도 안 들어간다. "롤 대역폭을 못 쟀다"가 "발산극을 잠자코 넘긴다"의
        # 이유가 될 수는 없다 (검증 쪽에는 댐퍼 안정 캡이 없어 이 인자가 유일한 방어다)
        if unstable:
            return "fail"
        if participation is not None and float(participation) < self.lam_part_min:
            return "na"
        if z < self.lam_min_frac * t:
            return "fail"
        if z < self.lam_good_frac * t:
            return "warn"
        return "ok"

    def shortfall(self, entry: dict) -> dict:
        """자리 하나의 요구 대비 부족 — {지표: {required, achieved, deficit, deficit_frac}}.

        `deficit_frac = deficit / required`라 **요구선 대비 비율**이다. 자리 종류가
        섞여도(PM 45° · GM 6 dB · ζ 0.30 · λ 12 rad/s) 한 축에서 비교되므로 정렬 키가
        되고, 화면에는 "얼마나 모자란가"가 된다.

        어느 지표를 보는지는 entry가 정한다 — 자리 종류마다 담는 키가 다르고
        (마진 자리는 pm_deg·gm_db, 감쇠 자리는 zeta류, 롤은 roll_lambda), 없는 키는
        건너뛴다. λ의 요구선만 criteria 절대값이 아니라 `entry["target"]×lam_min_frac`
        이다 (판정 관례가 없는 성능 지표 — judge_bandwidth와 같은 근거).

        **목표선(goal)도 함께 낸다** — warn은 "합격선은 넘겼으나 목표선 미달"인데,
        부족을 합격선으로만 재면 warn 행이 자기가 넘긴 선에 대한 여유를 보여 주고
        정작 못 넘긴 선은 이름조차 안 나온다 (`_one` 주석의 실측 예).
        """
        out = {}
        # PM에는 목표선이 없다 — judge()가 PM으로 warn을 내지 않는다 (합격 아니면 fail).
        # 없는 선을 지어내면 화면이 통과한 자리를 "목표 미달"이라 부르게 된다
        for key, required, goal in (("pm_deg", self.pm_min_deg, None),
                                    ("gm_db", self.gm_min_db, self.gm_good_db)):
            if entry.get(key) is not None:
                out[key] = _one(required, entry[key], goal)
        for key in _ZETA_KEYS:
            if entry.get(key) is not None:
                out[key] = _one(self.zeta_min, entry[key], self.zeta_good)
        target = entry.get("target")
        if entry.get("roll_lambda") is not None and target is not None:
            t = float(target)
            if math.isfinite(t) and t > 0.0:
                out["roll_lambda"] = _one(self.lam_min_frac * t, entry["roll_lambda"],
                                          self.lam_good_frac * t)
        return out

    def severity(self, entry: dict) -> float:
        """실패 정렬 키 — **클수록 심각**. 부족 비율의 최대값.

        측정 불가(볼 지표가 없거나 전부 nan)는 +inf다 — "얼마나 나쁜지 모른다"가
        목록 맨 앞이어야 한다.

        종전 schedmap._severity는 PM을 도 그대로, ζ를 ×90으로 섞은 절대 축이었다.
        그 환산이 감쇠 부족을 과대평가해 순서를 뒤집는다: PM 35°(22% 부족 → 축에서
        35.0)가 ζ 0.28(6.7% 부족 → 25.2)보다 덜 심각하게 정렬됐다.
        """
        fracs = [v["deficit_frac"] for v in self.shortfall(entry).values()
                 if v["deficit_frac"] is not None]
        return max(fracs) if fracs else math.inf

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MarginCriteria":
        return cls(**{k: float(v) for k, v in d.items()})

    def fingerprint(self) -> str:
        """판정 기준의 계보 지문 — 결과 저장물에 동봉해 '무슨 기준으로 판정했나'를 남긴다."""
        return canonical_hash(self.to_dict())


# ── 판정 상태 합산 · 판정선 표 · 목표 ↔ 판정선 정합 (공용) ─────────────────────────
#
# 기준 통합 ①(v1.50~): 같은 조건·지표·기준 버전이면 어느 탭에서도 판정이 같아야 한다. 그러려면
# 값만이 아니라 **판정 함수와 그 판정선의 뜻**이 한 자리에 있어야 한다 — 방향(큰 쪽이 엄격한가
# 작은 쪽이 엄격한가)이 호출하는 자리마다 다시 적히면 오버슈트·정착시간 같은 상한 지표에서 부등호가
# 조용히 뒤집힌다. 이 표가 그 뜻의 정본이고, 목표 검사(target_conflicts)·기준 편집 화면·판정 표시가
# 여기서 읽는다. 상태 넷의 화면 이름: fail 불합격 · warn 합격·주의 · ok 합격·권장 충족 · na 판정 불가.

STATUSES = ("fail", "warn", "ok", "na")

# 합산 순위 — na가 fail보다 앞선다(judge()와 같은 규칙: 한 축이라도 못 재면 판정 불가다.
# fail로 뭉개면 분류기가 엉뚱한 처방을 낸다)
_COMBINE_RANK = {"na": 3, "fail": 2, "warn": 1, "ok": 0}


# 나선 면제선 [s] — 기체 비행성 기준(analysis.fq.FQCriteria — MIL-F-8785C Class I·Cat B [기본값])의
# 나선 **수준 2** 최소 배가시간을 그대로 쓴다(8 s). 새 수를 만들지 않는다 — 기준을 바꾸면(다른 급·비행단계) 따라간다.
# 수준을 가르는 것은 **어느 상태를 재는가**다. 8785C의 나선 요구는 비행제어계를 켠 채 조종간을 놓은 기체에 걸리고,
# 이 SCAS에서 그 정상 상태는 자세 루프까지 닫힌 조성이다 — tune_point 3단이 그 조성을 극 전부 안정(나선 안정 —
# 수준 1보다 강하다)으로 따로 확인한다. 댐퍼만 닫힌 조성은 자세 루프가 빠진 **고장 상태**이고, 8785C는 고장
# 상태에 한 단계 낮은 수준을 허용한다. 수준 1을 여기 걸면 고장 상태의 나선 요구가 정상 상태의 롤 댐퍼를 깎는다 —
# 예제 기체 기본 설정 실측: 앵커 135점 중 41점에서 롤 댐퍼가 나선 20 s 선에 묶여(λ 2.7~8.6, 목표 12) 검증 실패
# 37건이 남았고, 수준 2 선에서는 0건(전 점 전체 폐루프 안정)이다. (tune._SPIRAL_T2_MIN_S가 이 값이다)
SPIRAL_T2_MIN_S = FQCriteria().spiral_t2_l2


def spiral_exempt_verdict(poles, lm_axis, t2_min_s: float = SPIRAL_T2_MIN_S) -> dict:
    """극 집합 → 나선 면제를 적용한 안정 판정 {"stable", "bound", "spiral_t2_s", "max_re"} — 발산 판정의 한 자리.

    자동 설계(tune — 댐퍼 가드 _damper_loop_verdict, 레이트 루프 여유 rate_loop_margins, 방향 판정 _closure_diverges)와
    마진 맵 칸 판정(MarginCriteria.judge_cell)이 같은 규칙을 쓴다 — 같은 루프를 두 곳이 다르게 판정하지 않게.

    발산극(Re ≥ −1e-9)이 없으면 안정. 횡축에서 발산극이 정확히 하나이고 느린 실근(|Re| < _WN_FLOOR_FRAC ×
    기준 wn — 모드 지표가 장주기·나선으로 보고 빼는 저주파 문턱)이면 그것이 나선이다: 배가시간이 비행성 기준
    선(t2_min_s — 기본 SPIRAL_T2_MIN_S) 이상이면 안정(면제), 아니면 bound "spiral". 나머지 발산은 전부 bound "unstable"."""
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
    if t2 < t2_min_s:
        return {"stable": False, "bound": "spiral", "spiral_t2_s": t2, "max_re": max_re}
    return {"stable": True, "bound": None, "spiral_t2_s": t2, "max_re": max_re}


def combine_margin_status(*statuses: str) -> str:
    """축별 판정 → 합산 판정. judge(margins) == combine_margin_status(judge_pm, judge_gm)."""
    return max(statuses, key=lambda s: _COMBINE_RANK[s])


MIN, MAX = "min", "max"  # min = 값이 클수록 엄격(하한선) · max = 값이 작을수록 엄격(상한선)


@dataclass(frozen=True)
class Line:
    """판정선 하나의 뜻 — 어느 지표를, 어느 방향으로, 어느 필드가 합격·권장선인가.

    pass_key·rec_key는 MarginCriteria 필드 이름(없으면 None — PM에는 권장선이 없다),
    target_key는 TuneTargets 필드 이름(자동 설계가 겨냥하는 목표가 없으면 None).
    ratio_of_target이면 판정선이 **목표의 비율**이다(λ_roll — lam_min_frac × roll_lambda):
    목표 자체가 선을 정하므로 목표 ↔ 판정선 정합 검사 대상이 아니다.
    """

    metric: str
    label: str
    unit: str
    direction: str
    pass_key: str | None
    rec_key: str | None
    target_key: str | None = None
    ratio_of_target: bool = False


# 튜닝 목표가 있는 판정선 — 자동 설계와 영향성 평가가 같은 MarginCriteria·TuneTargets를 쓰는 자리.
# 나머지 평가 항목(권한·작동기·회복·스케줄 — pipeline/criteria.py)의 방향은 기준 편집 화면을
# 세우는 단계(기준 통합 ① S2)에서 이 표에 더한다: 그 항목들은 튜닝 목표가 없어 정합 검사에는 안 걸린다
LINES = (
    Line("pm_deg", "위상여유 PM", "°", MIN, "pm_min_deg", None, "pm_deg"),
    Line("gm_db", "이득여유 GM", "dB", MIN, "gm_min_db", "gm_good_db", "gm_db"),
    Line("zeta_sp", "단주기 감쇠 ζ_sp", "", MIN, "zeta_min", "zeta_good", "zeta_sp"),
    Line("zeta_dr", "더치롤 감쇠 ζ_dr", "", MIN, "zeta_min", "zeta_good", "zeta_dr"),
    Line("roll_lambda", "롤 수렴 대역폭 λ_roll", "rad/s", MIN,
         "lam_min_frac", "lam_good_frac", "roll_lambda", ratio_of_target=True),
)


def at_least_as_strict(direction: str, value: float, line: float) -> bool:
    """value가 line과 같거나 더 엄격한가 — min이면 value ≥ line, max면 value ≤ line."""
    if direction == MIN:
        return value >= line
    if direction == MAX:
        return value <= line
    raise ValueError(f"판정선 방향은 {MIN!r}|{MAX!r}: {direction!r}")


def target_conflicts(criteria: "MarginCriteria", targets) -> list:
    """튜닝 목표가 판정선보다 느슨한 자리 — [{metric, level, target_key, target, line_key, line, direction}].

    level "pass" = 목표가 **합격선**보다 느슨하다(튜닝에 성공한 점이 곧바로 fail — 설정 모순),
    level "rec" = 합격선은 지키되 **권장선**보다 느슨하다(성공한 점이 전부 warn — warn이 무의미).
    한 지표는 더 심한 쪽 하나만 낸다. 거절할지 경고할지는 호출측 정책이다 — 판정은 여기서만 한다.
    targets는 TuneTargets(또는 같은 필드를 가진 것) — 이 모듈은 tune을 import하지 않는다(tune이 이 모듈을 쓴다).
    """
    out = []
    for ln in LINES:
        if ln.target_key is None or ln.ratio_of_target:
            continue
        t = float(getattr(targets, ln.target_key))
        if math.isnan(t):
            # 잴 수 없는 목표는 충돌로 판정하지 않는다 — 종전 검사(`t < line`)가 nan을 통과시켰고
            # S1은 동작 불변이다. nan 목표를 막는 것은 목표 값 검증(TuneTargets)의 몫이다
            continue
        for level, key in (("pass", ln.pass_key), ("rec", ln.rec_key)):
            if key is None:
                continue
            v = float(getattr(criteria, key))
            if not at_least_as_strict(ln.direction, t, v):
                out.append({"metric": ln.metric, "level": level,
                            "target_key": ln.target_key, "target": t,
                            "line_key": key, "line": v, "direction": ln.direction})
                break
    return out
