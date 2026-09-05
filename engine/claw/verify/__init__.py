"""M12 verify — 검증·리포트 (구현 문서 §7). Phase 2~ 지속 구축.

지금 있는 것:
  autocode  탑재 C 신뢰성 검증 — 생성·정적 규율·엄격 컴파일·미션 비트 대조·커버리지
            (서버 /verify/flight → 웹 검증 탭이 소비)
  trace     대조용 미션 기록 — flight/tests 패리티와 검증 탭이 **같은 미션**을 쓴다

남은 것(3층 툴 검증): F-16 벤치마크 재현·물리검증·Simulink 회귀 — 백로그.
"""

from claw.verify.autocode import verify_flight
from claw.verify.trace import record_mission

__all__ = ["record_mission", "verify_flight"]
