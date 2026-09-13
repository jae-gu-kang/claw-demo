"""예제 기체 문서 로드 — 엔진 패키지 데이터 (02 §5.6).

예제는 코드가 아니라 **데이터**다. 구 데모 델타윙의 모든 값이 이 JSON 하나에 있고,
plant/demo.py·fcl/demo.py는 이 문서를 감싸는 얇은 호환 함수일 뿐이다. 수치와 그 근거
(측정 기록)는 문서 02 §5.6이 가리킨다.
"""

import copy
import functools
import json
from importlib import resources

from claw.profile.schema import validate_document

EXAMPLE_ID = "example-delta"
_EXAMPLE_FILE = "examples/delta_demo.json"


@functools.lru_cache(maxsize=1)
def _example_cached() -> dict:
    text = resources.files("claw.profile").joinpath(_EXAMPLE_FILE).read_text(encoding="utf-8")
    return validate_document(json.loads(text))


def load_example() -> dict:
    """검증된 예제 문서의 **사본** — 호출자가 고쳐도 캐시가 오염되지 않는다."""
    return copy.deepcopy(_example_cached())
