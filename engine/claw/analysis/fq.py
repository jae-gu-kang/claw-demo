"""비행성 수준(Flying Qualities Level) 판정 — 무증강 기체 모드의 1/2/3 등급 (01 §4.2).

모드 수치(damp/classify)는 있었지만 판정이 없었다 — 실제로 v1.10에서 나선 배가
시간 14 s(< 20 s 관례)를 사람이 손으로 발견해 기본 격자를 옮겨 피했다. 이 모듈이
그 관례를 데이터로 정본화한다: 판정선은 MIL-F-8785C의 소형기(Class I)·순항
(Category B) 표를 따른 [기본값]이고, 다른 급·비행단계로 판정하려면 필드를 바꾼다.

판정 대상은 **선형화된 무증강(개루프) 기체 모드**다 — classify_lon/classify_lat이
분류한 그 모드. SCAS를 닫은 모드가 아니므로 "수준 미달"은 결함이 아니라 "비행제어
보완 필요"라는 사실이다(더치롤 미달 → 요 댐퍼가 메꿀 몫). 폐루프 판정은 마진
합격기준(design/criteria.py MarginCriteria)의 몫이고 서로 대체하지 않는다.

[한계] 단주기는 감쇠비 대역만 본다 — 8785C의 ωn·CAP(n/α) 요구는 트림점의 n/α가
필요해 아직 없다. 장주기 ζ는 켤레쌍일 때만 정의된다(실근 분리는 classify가 비정형
으로 보고).

수준의 의미(8785C §1.5): 1 = 임무에 적합 · 2 = 임무 수행 가능하나 조종사 부담 증가
· 3 = 안전히 조종 가능하나 임무 부적합 · None(수준 밖) = 그 아래.
"""

import math
from dataclasses import asdict, dataclass

from claw.params.paramset import canonical_hash

LN2 = math.log(2.0)


def _t2(re: float) -> float:
    """발산 실부 → 배가 시간 [s] — T₂ = ln2 / Re(λ). Re ≤ 0이면 발산이 아니다."""
    return LN2 / re


@dataclass(frozen=True)
class FQCriteria:
    """비행성 수준 판정선 — MIL-F-8785C Class I·Category B [기본값].

    필드가 곧 표다: *_l1이 수준 1의 요구, *_l2·*_l3이 그 아래 수준의 요구.
    fingerprint()가 판정 기준의 계보 키다(MarginCriteria와 같은 규약) — 결과
    저장물에 동봉해 "무슨 기준으로 판정했나"를 남긴다.
    """

    # 단주기 감쇠비 대역 (Cat B) — 수준 3은 하한만 있다 (8785C 표 IV)
    sp_zeta_l1_lo: float = 0.30
    sp_zeta_l1_hi: float = 2.00
    sp_zeta_l2_lo: float = 0.20
    sp_zeta_l2_hi: float = 2.00
    sp_zeta_l3_lo: float = 0.15
    # 장주기 — 수준 1 ζ ≥ 0.04, 수준 2 ζ ≥ 0(안정), 수준 3 발산이어도 T₂ ≥ 55 s
    ph_zeta_l1: float = 0.04
    ph_t2_l3: float = 55.0
    # 더치롤 최소 (Cat B — 전 Class 공통) — ζ와 ζωn과 ωn 셋 다 넘어야 그 수준
    dr_zeta_l1: float = 0.08
    dr_zwn_l1: float = 0.15  # ζ·ωn [rad/s]
    dr_wn_l1: float = 0.4  # [rad/s]
    dr_zeta_l2: float = 0.02
    dr_zwn_l2: float = 0.05
    dr_wn_l2: float = 0.4
    dr_zeta_l3: float = 0.0
    dr_wn_l3: float = 0.4
    # 롤 수렴 시정수 상한 [s] (Cat B)
    roll_tau_l1: float = 1.4
    roll_tau_l2: float = 3.0
    roll_tau_l3: float = 10.0
    # 나선 최소 배가 시간 [s] — 수준 1이 Cat B의 20 s (Cat A·C는 12 s), 안정 나선은 수준 1
    spiral_t2_l1: float = 20.0
    spiral_t2_l2: float = 8.0
    spiral_t2_l3: float = 4.0

    def __post_init__(self):
        # 수준 서열 — 아래 수준의 요구가 위 수준보다 느슨해야 판정이 단조롭다.
        # 서버가 기준을 통째로 받게 되는 날(MarginCriteria 선례) 0·역서열이 들어오면
        # "수준 2인데 수준 1"이 조용히 나온다 — 생성 시점에 막는다
        if not 0.0 < self.sp_zeta_l3_lo <= self.sp_zeta_l2_lo <= self.sp_zeta_l1_lo:
            raise ValueError("단주기 ζ 하한 서열 위반: l3 ≤ l2 ≤ l1, 양수")
        if not self.sp_zeta_l1_hi <= self.sp_zeta_l2_hi:
            raise ValueError("단주기 ζ 상한 서열 위반: l1 ≤ l2")
        if not (self.sp_zeta_l1_lo < self.sp_zeta_l1_hi and self.sp_zeta_l2_lo < self.sp_zeta_l2_hi):
            raise ValueError("단주기 ζ 대역은 하한 < 상한")
        if not 0.0 <= self.dr_zeta_l3 <= self.dr_zeta_l2 <= self.dr_zeta_l1:
            raise ValueError("더치롤 ζ 서열 위반: l3 ≤ l2 ≤ l1")
        if not 0.0 <= self.dr_zwn_l2 <= self.dr_zwn_l1:
            raise ValueError("더치롤 ζωn 서열 위반: l2 ≤ l1")
        if not 0.0 < self.dr_wn_l3 <= self.dr_wn_l2 <= self.dr_wn_l1:
            raise ValueError("더치롤 ωn 서열 위반: l3 ≤ l2 ≤ l1, 양수")
        if not 0.0 < self.roll_tau_l1 <= self.roll_tau_l2 <= self.roll_tau_l3:
            raise ValueError("롤 시정수 서열 위반: l1 ≤ l2 ≤ l3, 양수")
        if not 0.0 < self.spiral_t2_l3 <= self.spiral_t2_l2 <= self.spiral_t2_l1:
            raise ValueError("나선 배가 시간 서열 위반: l3 ≤ l2 ≤ l1, 양수")
        if not (self.ph_zeta_l1 > 0.0 and self.ph_t2_l3 > 0.0):
            raise ValueError("장주기 판정선은 양수")

    def judge_short_period(self, mode: dict) -> dict:
        """단주기 켤레쌍 {zeta} → {level, zeta}. 대역 밖(과감쇠 포함)은 수준 밖(None)."""
        z = float(mode["zeta"])
        if self.sp_zeta_l1_lo <= z <= self.sp_zeta_l1_hi:
            level = 1
        elif self.sp_zeta_l2_lo <= z <= self.sp_zeta_l2_hi:
            level = 2
        elif z >= self.sp_zeta_l3_lo:
            level = 3
        else:
            level = None
        return {"level": level, "zeta": z}

    def judge_phugoid(self, mode: dict) -> dict:
        """장주기 켤레쌍 {zeta, eig} → {level, zeta, t2_s}.

        t2_s는 발산일 때만 수치다 — 안정 모드에 0을 적으면 "즉시 배가"로 읽힌다.
        그리고 t2_s의 null 여부는 수준과 일치해야 한다(수준 1·2는 항상 null, 수준 3·밖은
        항상 수치) — 웹 fq.js worseness의 동률 비교가 같은 수준 안에서 축이 섞이지
        않는다는 이 사실에 기댄다."""
        z = float(mode["zeta"])
        re = float(mode["eig"].real)
        if z >= self.ph_zeta_l1:
            return {"level": 1, "zeta": z, "t2_s": None}
        if re <= 0.0:
            return {"level": 2, "zeta": z, "t2_s": None}
        t2 = _t2(re)
        return {"level": 3 if t2 >= self.ph_t2_l3 else None, "zeta": z, "t2_s": t2}

    def judge_dutch_roll(self, mode: dict) -> dict:
        """더치롤 켤레쌍 {zeta, wn} → {level, zeta, wn, zwn} — ζ·ζωn·ωn 셋 다 요구."""
        z = float(mode["zeta"])
        wn = float(mode["wn"])
        zwn = z * wn
        if z >= self.dr_zeta_l1 and zwn >= self.dr_zwn_l1 and wn >= self.dr_wn_l1:
            level = 1
        elif z >= self.dr_zeta_l2 and zwn >= self.dr_zwn_l2 and wn >= self.dr_wn_l2:
            level = 2
        elif z >= self.dr_zeta_l3 and wn >= self.dr_wn_l3:
            level = 3
        else:
            level = None
        return {"level": level, "zeta": z, "wn": wn, "zwn": zwn}

    def judge_roll(self, mode: dict) -> dict:
        """롤 실근 {eig} → {level, tau_s}. 발산 실근은 τ가 정의되지 않는다 → 수준 밖."""
        re = float(mode["eig"].real)
        if re >= 0.0:
            return {"level": None, "tau_s": None}
        tau = -1.0 / re
        if tau <= self.roll_tau_l1:
            level = 1
        elif tau <= self.roll_tau_l2:
            level = 2
        elif tau <= self.roll_tau_l3:
            level = 3
        else:
            level = None
        return {"level": level, "tau_s": tau}

    def judge_spiral(self, mode: dict) -> dict:
        """나선 실근 {eig} → {level, stable, t2_s}. 안정 나선은 수준 1 (요구는 발산 한정)."""
        re = float(mode["eig"].real)
        if re <= 0.0:
            return {"level": 1, "stable": True, "t2_s": None}
        t2 = _t2(re)
        if t2 >= self.spiral_t2_l1:
            level = 1
        elif t2 >= self.spiral_t2_l2:
            level = 2
        elif t2 >= self.spiral_t2_l3:
            level = 3
        else:
            level = None
        return {"level": level, "stable": False, "t2_s": t2}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FQCriteria":
        # 서버가 결과에 동봉하는 형태는 {**to_dict(), "fingerprint": …}다 — 그 dict를
        # 그대로 받아도 서야 한다. fingerprint만 걸러내고 나머지 모르는 키는 TypeError로
        # 드러난다(모르는 키를 조용히 버리면 오타 판정선이 기본값으로 위장된다)
        return cls(**{k: float(v) for k, v in d.items() if k != "fingerprint"})

    def fingerprint(self) -> str:
        """판정 기준의 계보 지문 — MarginCriteria.fingerprint와 같은 규약."""
        return canonical_hash(self.to_dict())


def fq_lon(classified: dict, criteria: FQCriteria) -> dict:
    """classify_lon 결과 → {short_period, phugoid} 판정."""
    return {
        "short_period": criteria.judge_short_period(classified["short_period"]),
        "phugoid": criteria.judge_phugoid(classified["phugoid"]),
    }


def fq_lat(classified: dict, criteria: FQCriteria) -> dict:
    """classify_lat 결과 → {dutch_roll, roll, spiral} 판정."""
    return {
        "dutch_roll": criteria.judge_dutch_roll(classified["dutch_roll"]),
        "roll": criteria.judge_roll(classified["roll"]),
        "spiral": criteria.judge_spiral(classified["spiral"]),
    }
