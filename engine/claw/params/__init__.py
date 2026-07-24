"""M1 params — 파라미터 관리 계층 (Simulink Data Dictionary 대체, 구현 문서 §5.5)
+ 컴포넌트 레지스트리·JSON 스키마 (구현 문서 §2.3).

ParamSet.fingerprint()가 발급하는 지문이 산출물 계보(lineage)·영향성 평가(§2.4)의 키.
"""

from claw.params.param import ParamDef, ParamError
from claw.params.paramset import ParamSet
from claw.params.registry import REGISTRY, ComponentRegistry, RegistryError
