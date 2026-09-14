"""예제 기체 문서 로드 — 엔진 패키지 데이터 (02 §5.6).

예제는 코드가 아니라 **데이터**다. 구 데모 델타윙의 모든 값이 이 JSON 하나에 있고,
plant/demo.py·fcl/demo.py는 이 문서를 감싸는 얇은 호환 함수일 뿐이다. 수치와 그 근거
(측정 기록)는 문서 02 §5.6이 가리킨다.
"""

import copy
import functools
import json
import os
from importlib import resources
from pathlib import Path

from claw.profile.schema import validate_document

EXAMPLE_ID = "example-delta"
_EXAMPLE_FILE = "examples/delta_demo.json"
# 예제 자리에 다른 문서를 넣는 환경변수 — **회귀 테스트 전용**이다. 엔진·서버 테스트와 골든은 구 합성 기체(1200 kg,
# engine/claw/tests/fixtures/delta_legacy.json)의 비행 조건에 맞춰 수치를 고정해 두었으므로 conftest가 이 변수로 그
# 문서를 예제 자리에 둔다. 제품(서버·웹·flight/generate.py)은 설정하지 않아 패키지의 예제를 쓴다(02 §5.6).
EXAMPLE_OVERRIDE_ENV = "CLAW_EXAMPLE_DOCUMENT"


@functools.lru_cache(maxsize=4)
def _example_cached(override: str | None) -> dict:
    if override:
        text = Path(override).read_text(encoding="utf-8")
    else:
        text = resources.files("claw.profile").joinpath(_EXAMPLE_FILE).read_text(encoding="utf-8")
    return validate_document(json.loads(text))


def load_example() -> dict:
    """검증된 예제 문서의 **사본** — 호출자가 고쳐도 캐시가 오염되지 않는다."""
    return copy.deepcopy(_example_cached(os.environ.get(EXAMPLE_OVERRIDE_ENV) or None))


def load_shipped_example() -> dict:
    """패키지에 실린 예제 — 테스트가 예제 자리를 바꿔 둔 동안에도 **제품이 쓰는 그 문서**를 읽는다."""
    return copy.deepcopy(_example_cached(None))
