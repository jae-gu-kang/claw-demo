"""강건성 섭동 집합 (04 · 3단계 검증) — 기체 조립에 거는 결정적 배율 섭동.

plant/demo.py에서 옮겨 왔다: 섭동은 데모 기체의 성질이 아니라 **어느 기체 프로파일에나**
거는 검증 설계변수다(02 §5.6). 흔들 수 있는 축은 프로파일이 정한다 — 공력 항에 태그가
없는 축을 흔드는 것은 조용한 거짓 합격이라 조립이 거부한다(profile/build.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DispersionSet:
    """강건성 검증(3단계)용 결정적 섭동 — 비율 스케일 (0.2 = +20 %).

    조립 함수에 설계변수를 단다(M7 주입 인자와 같은 성격 — 해석 모듈이 정본을
    우회하지 않게). **CG는 여기 없다** — 모멘트 기준점 이전 [TBD]라(plant/mass.py
    FuelMass) CG를 흔들어도 동역학이 안 변한다. 흔드는 시늉을 하면 "CG ±20 % 통과"가
    조용한 거짓 합격이 된다.
    """

    mass: float = 0.0  # 공허중량 배율 Δ (연료는 케이스 변수라 그대로)
    cmalpha: float = 0.0  # 정적 안정 미계수 Cmα 배율 Δ
    cmq: float = 0.0  # 피치 댐핑 Cmq 배율 Δ

    def label(self) -> str:
        parts = [f"{n}{v:+.0%}" for n, v in
                 (("mass", self.mass), ("cmα", self.cmalpha), ("cmq", self.cmq))
                 if v != 0.0]
        return "·".join(parts) or "nominal"
