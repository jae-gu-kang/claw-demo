"""예제 기체 서버 응답 골든 — 라우트의 프로파일 이관이 응답을 바이트 단위로 보존함을 증명한다.

저장본은 이관 전 HEAD의 응답이다(golden/capture_server_goldens.py). 이관 중 바뀌는 것은
라우트 내부뿐이고, 요청(프로파일 미지정 = 예제)과 저장본은 그대로다.
"""

import pathlib
import sys

import pytest

# 공용 골든 부호화는 엔진 쪽 폴더에 있다 — import 순서에 기대지 않고 여기서 직접 올린다
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "engine/claw/tests/golden"))

import golden_io  # noqa: E402
from tests.claw_server.golden import server_goldens  # noqa: E402

STORE = pathlib.Path(__file__).resolve().parent / "golden" / "profile_example"


@pytest.mark.parametrize("name", list(server_goldens.GOLDENS))
def test_example_profile_server_golden(name, client, wait_job):
    value = server_goldens.shrink(server_goldens.GOLDENS[name](client, wait_job))
    golden_io.compare(STORE / f"{name}.json", name, value, "full")
