"""M6 nav — 항법 등가 오차 모델 (구현 문서 §3.1). EKF 미구현 [확정].

핵심 계약: 법칙(M7·M8)은 plant 참값을 직접 보지 않고 NavOutput만 소비한다 (03 M6).
레지스트리 "nav" 카테고리 등록 — 추후 항법팀 실제 EKF/비행SW 코드로 교체 가능
(인터페이스 개방, 02 §3.1).
"""

from claw.nav.error_model import NavErrorModel
from claw.params.registry import REGISTRY

REGISTRY.register(
    "nav", NavErrorModel.NAME, lambda ps: NavErrorModel(**ps.as_dict()), NavErrorModel.PARAM_DEFS
)

__all__ = ["NavErrorModel"]
