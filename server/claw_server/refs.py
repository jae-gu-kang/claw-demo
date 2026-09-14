"""요청 → 기체 프로파일 해석 (02 §5.6) — 라우트는 기체를 여기서만 받는다.

지금은 예제 기체 하나를 돌려준다. 요청이 기체를 고르는 계약(ProfileRef)과 서버 저장소는 다음
단계에서 이 자리에 들어온다 — 라우트가 엔진의 예제 기체 호환 함수를 직접 부르지 않게 창구를 먼저
하나로 모았다(가드: engine/claw/tests/test_profile_guard.py).
"""

from claw.profile import example_profile


def current_profile():
    """이 요청이 쓰는 기체 프로파일(BuiltProfile) — 매번 새로 조립한다(호출자끼리 상태를 나누지 않는다)."""
    return example_profile()
