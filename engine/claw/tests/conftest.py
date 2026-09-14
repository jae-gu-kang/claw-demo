"""엔진 테스트 공통 — 예제 자리에 **구 합성 기체**(1200 kg 회귀 픽스처)를 둔다.

제품 예제는 200 kg급으로 바뀌었지만(02 §5.6.1), 엔진 테스트와 골든은 구 기체의 비행 조건(M0.2~0.6·연료 0~400 kg)에
맞춰 알고리즘을 고정해 왔다. 기체가 바뀌었다고 알고리즘 회귀 기준까지 다시 쓰지 않도록 여기서 예제 자리를 바꾼다.
제품 예제 자체의 검사는 `test_profile_shipped_example.py`가 `load_shipped_example()`로 한다.
"""

import os
from pathlib import Path

from claw.profile.document import EXAMPLE_OVERRIDE_ENV

LEGACY_EXAMPLE = Path(__file__).resolve().parent / "fixtures" / "delta_legacy.json"
os.environ[EXAMPLE_OVERRIDE_ENV] = str(LEGACY_EXAMPLE)
