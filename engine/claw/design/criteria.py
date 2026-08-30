"""마진 합격기준 — 판정선의 엔진 이관 (01 §5 "합격기준 수치는 파라미터 관리 계층이 정본").

지금까지 판정선은 웹 표시 계층에만 있었다 (web/js/lib/plot.js marginColor,
views/margins.js gmColor — PM 30/45°, GM 6/10 dB). 자동 설계 루프는 판정을
기계가 하므로 기준이 엔진에 있어야 하고, 웹은 /api/design/defaults로 이 값을
받아 색칠한다 (하드코딩은 폴백).

의미 구분 — 합격선·목표선·표시 음영선의 세 층:
- 합격(pass) = pm_deg ≥ pm_min_deg ∧ gm_db ≥ gm_min_db  (관례 45° / 6 dB)
- pm_bad_deg(30°)는 표시용 심각선(30~45° 주의 음영) — 자동화에서는 45° 미만이 곧 fail
- gm_good_db·zeta_good은 **설계 목표선**이다 — 합격이되 목표 미달이면 warn

warn이 뜻하는 것: "합격선은 넘겼으나 튜너가 겨냥한 설계 목표에는 못 미친다".
그러려면 목표선이 튜너 목표(TuneTargets) **이하**여야 한다 — 그렇지 않으면 튜닝이
완벽히 성공한 점조차 warn으로 찍혀 warn이 아무 정보도 못 준다. 실제로 그랬다:
gm_good_db 10 dB > TuneTargets.gm_db 8 dB라 자유 게인 최적점이 구조적으로 warn이었고,
사용자에게는 "경고가 압도적으로 많다"로 보였다. 이 정합은 AutoDesignConfig.__post_init__이
강제한다 (기준과 목표가 만나는 유일한 자리 — 한쪽만 조정하면 거기서 걸린다).

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

from claw.params.paramset import canonical_hash

# 감쇠 지표가 entry에 실리는 키들 — 자리 종류마다 이름이 다르다 (schedmap은 "zeta",
# tune의 achieved는 지표 이름 그대로 "zeta_sp"/"zeta_dr"). 셋 다 같은 합격선을 쓴다.
_ZETA_KEYS = ("zeta", "zeta_sp", "zeta_dr")


def _one(required: float, achieved) -> dict:
    """지표 하나의 부족 레코드 — {required, achieved, deficit, deficit_frac}.

    deficit는 양수가 부족·음수가 여유. achieved가 nan이면 **None**이다 — 0.0으로
    두면 "교차 없음"과 "부족 없음"이 같은 수가 된다 (종전 deficit()의 결함).
    ±inf는 그대로 둔다: 직렬화 정책이 "inf" 문자열로 구분해 내보내므로(serialize.py)
    nan(=null, 판정 불가)과 섞이지 않는다.
    """
    a = float(achieved)
    if required <= 0.0:
        # 요구선이 0 이하면 비율이 정의되지 않는다. 판정 불가로 흘린다 —
        # 여기서 나누면 잡 스레드가 죽어 "202 뒤 원인 없는 실패"가 된다
        return {"required": required, "achieved": a if math.isfinite(a) else None,
                "deficit": None, "deficit_frac": None}
    if math.isnan(a):
        return {"required": required, "achieved": None, "deficit": None, "deficit_frac": None}
    d = required - a
    return {"required": required, "achieved": a, "deficit": d, "deficit_frac": d / required}


@dataclass(frozen=True)
class MarginCriteria:
    pm_min_deg: float = 45.0  # 위상여유 합격선 [deg]
    gm_min_db: float = 6.0  # 이득여유 합격선 [dB]
    pm_bad_deg: float = 30.0  # 표시용 심각선 [deg] (30~45 주의 음영)
    gm_good_db: float = 8.0  # 설계 목표선 [dB] — TuneTargets.gm_db와 같은 값 (6~8 warn)
    zeta_min: float = 0.30  # 레이트 댐퍼 폐쇄 모드 감쇠 합격선 (MIL-8785류 Level 관례 대역)
    zeta_good: float = 0.50  # 감쇠 목표선 — 합격이되 이 미만은 warn (TuneTargets.zeta_dr와 동치)
    # 롤 대역폭(λ)만 합격선이 **절대값이 아니라 목표 대비 비율**이다 [기본값]. λ는
    # 안정성 마진이 아니라 조종성 성능 지표라 관례적 절대 합격선이 없고, 요구 자체가
    # 그 실행의 튜닝 목표(TuneTargets.roll_lambda)로 주어진다. 비율은 폐쇄망 검증에서
    # 확정할 자리다 (docs -01 §7 "합격기준 허용오차 수치").
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
        """
        out = {}
        for key, required in (("pm_deg", self.pm_min_deg), ("gm_db", self.gm_min_db)):
            if entry.get(key) is not None:
                out[key] = _one(required, entry[key])
        for key in _ZETA_KEYS:
            if entry.get(key) is not None:
                out[key] = _one(self.zeta_min, entry[key])
        target = entry.get("target")
        if entry.get("roll_lambda") is not None and target is not None:
            t = float(target)
            if math.isfinite(t) and t > 0.0:
                out["roll_lambda"] = _one(self.lam_min_frac * t, entry["roll_lambda"])
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
