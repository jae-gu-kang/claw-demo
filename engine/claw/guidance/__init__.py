"""M8 guidance — 경로 생성·추종, 비행모드 테이블+실행기 (01 §3.3).

선언적 모드 테이블(ModeSpec)+실행기(ModeSequencer) [확정], LOS 경로추종
[기본값, 레지스트리 교체 가능]. NavOutput만 소비, GuidanceCommand 생산 —
M7과 상호 의존 없음 (03 §4 계약 연결).
"""

from claw.guidance.guidance import Guidance
from claw.guidance.modes import ModeSequencer, ModeSpec, eval_condition, validate_condition
from claw.guidance.path import LosPath
from claw.params.registry import REGISTRY

LosPath.register(REGISTRY, category="guidance")  # 교체 가능 컴포넌트 (02 §2.3)

__all__ = [
    "Guidance",
    "ModeSequencer",
    "ModeSpec",
    "eval_condition",
    "validate_condition",
    "LosPath",
]
