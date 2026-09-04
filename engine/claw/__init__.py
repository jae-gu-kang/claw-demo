"""CLAW 설계툴 엔진 — 비행제어/유도법칙 설계·해석·시뮬레이션 (MATLAB 대체).

모듈 구성·계층 규칙: docs/fcs-context-03-modules.md
규약: docs/conventions.md (구현체는 claw.common)
"""

# 0.2.0 — PID 안티와인드업이 **조건부 적분**으로 바뀌었다 (blocks/controllers.py).
# 이 버전을 올린 이유가 곧 이 필드의 존재 이유다: 형상 지문(그래프 구조·파라미터)은
# 안 움직였는데 블록의 **의미**가 바뀌었다. 지문만 보면 "같은 형상"이라 재검증이
# 필요 없다고 읽히므로, 생성 C 헤더의 "엔진 : claw X.Y.Z"가 그 구멍을 메운다.
__version__ = "0.2.0"
