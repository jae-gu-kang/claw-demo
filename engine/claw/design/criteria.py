"""마진 합격기준 — 판정선의 엔진 이관 (01 §5 "합격기준 수치는 파라미터 관리 계층이 정본").

지금까지 판정선은 웹 표시 계층에만 있었다 (web/js/lib/plot.js marginColor,
views/margins.js gmColor — PM 30/45°, GM 6/10 dB). 자동 설계 루프는 판정을
기계가 하므로 기준이 엔진에 있어야 하고, 웹은 /api/design/defaults로 이 값을
받아 색칠한다 (하드코딩은 폴백).

의미 구분 — 자동화 합격선과 표시 음영선은 다르다:
- 합격(pass) = pm_deg ≥ pm_min_deg ∧ gm_db ≥ gm_min_db  (관례 45° / 6 dB)
- pm_bad_deg(30°)는 표시용 심각선(30~45° 주의 음영) — 자동화에서는 45° 미만이 곧 fail
- gm_good_db(10 dB)는 표시용 양호선 — 합격이되 6~10 dB는 warn(얇은 여유)

판정 불가(nan — 교차 없음)는 "na"로 낸다. 무한 여유(inf)는 그 축 통과로 본다.
loop_margins가 nan을 nan으로 유지하는 이유(margins.py — 무한 여유 오인 금지)와
같은 원칙이다.
"""

import math
from dataclasses import asdict, dataclass

from claw.params.paramset import canonical_hash


@dataclass(frozen=True)
class MarginCriteria:
    pm_min_deg: float = 45.0  # 위상여유 합격선 [deg]
    gm_min_db: float = 6.0  # 이득여유 합격선 [dB]
    pm_bad_deg: float = 30.0  # 표시용 심각선 [deg] (30~45 주의 음영)
    gm_good_db: float = 10.0  # 표시용 양호선 [dB] (6~10 주의 음영)

    def __post_init__(self):
        if not self.pm_bad_deg <= self.pm_min_deg:
            raise ValueError(f"pm_bad_deg({self.pm_bad_deg}) ≤ pm_min_deg({self.pm_min_deg}) 필요")
        if not self.gm_min_db <= self.gm_good_db:
            raise ValueError(f"gm_min_db({self.gm_min_db}) ≤ gm_good_db({self.gm_good_db}) 필요")

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

    def deficit(self, margins: dict) -> dict:
        """합격선까지의 부족량 [양수=부족] — 분류기 히스테리시스 판정의 입력."""
        pm = float(margins["pm_deg"])
        gm = float(margins["gm_db"])
        return {
            "pm_deg": self.pm_min_deg - pm if math.isfinite(pm) else 0.0,
            "gm_db": self.gm_min_db - gm if math.isfinite(gm) else 0.0,
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MarginCriteria":
        return cls(**{k: float(v) for k, v in d.items()})

    def fingerprint(self) -> str:
        """판정 기준의 계보 지문 — 결과 저장물에 동봉해 '무슨 기준으로 판정했나'를 남긴다."""
        return canonical_hash(self.to_dict())
