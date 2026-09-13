"""M18 profile — 기체 프로파일 (02 §5.6 · 03 §7.2).

툴은 특정 기체를 전제하지 않는다. 기체 데이터(공력·실속·질량·추진·작동기·타면·구조/운용
한계·지상장치·트림 탐색 범위·법칙 설계값)는 전부 이 문서에 있고, 형상 변형은 문서 위의
JSON Pointer 치환이다. 구 데모 델타윙은 읽기 전용 예제 문서가 됐다.
"""

from claw.profile.build import BuiltProfile, build_profile
from claw.profile.document import EXAMPLE_ID, load_example
from claw.profile.errors import ProfileError
from claw.profile.fingerprint import FP_EXCLUDED, plant_fingerprint, profile_fingerprint
from claw.profile.patch import apply_patch, get_pointer
from claw.profile.schema import SCHEMA_VERSION, effective_document, validate_document


def example_profile(variant: str | None = None) -> BuiltProfile:
    """예제 기체 BuiltProfile — 테스트·예제·기본 선택용."""
    return build_profile(load_example(), variant, validated=True)


__all__ = [
    "BuiltProfile", "build_profile", "example_profile", "EXAMPLE_ID", "load_example",
    "ProfileError", "FP_EXCLUDED", "plant_fingerprint", "profile_fingerprint",
    "apply_patch", "get_pointer", "SCHEMA_VERSION", "effective_document", "validate_document",
]
