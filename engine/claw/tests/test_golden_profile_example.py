"""예제 기체 골든 — 프로파일 이관(02 §5.6)이 산출을 비트 단위로 보존함을 증명한다.

저장본은 이관 전 HEAD의 데모 기체 산출이다(golden/capture_profile_goldens.py). 이관 중에는
golden/engine_goldens.py의 **호출 경로만** 새 API로 바뀌고 저장본은 그대로다.
"""

import pathlib
import sys

import pytest

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"
sys.path.insert(0, str(GOLDEN))

import engine_goldens  # noqa: E402
import golden_io  # noqa: E402


@pytest.mark.parametrize("name", list(engine_goldens.GOLDENS))
def test_example_profile_matches_golden(name):
    fn, mode = engine_goldens.GOLDENS[name]
    golden_io.compare(GOLDEN / "profile_example" / f"{name}.json", name, fn(), mode)
