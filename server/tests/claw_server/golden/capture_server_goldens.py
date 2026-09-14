"""예제 기체 서버 응답 골든 캡처 — `.venv/bin/python server/tests/claw_server/golden/capture_server_goldens.py`

항목마다 새 임시 저장소의 앱으로 두 번 계산해 결정론을 확인한 뒤 저장한다.
"""

import argparse
import pathlib
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))  # server/ — tests.claw_server 패키지 루트
# 골든은 구 합성 기체(회귀 픽스처) 기준 — 서버 conftest와 같은 문서를 예제 자리에 둔다 (import 전에)
import os  # noqa: E402

from claw.profile.document import EXAMPLE_OVERRIDE_ENV, load_example  # noqa: E402 — 예제는 import 시점에 읽지 않는다

os.environ[EXAMPLE_OVERRIDE_ENV] = str(HERE.parents[3] / "engine" / "claw" / "tests" / "fixtures" / "delta_legacy.json")
# 변수 이름이 바뀌어 덮어쓰기가 조용히 빗나가면 제품 예제(200 kg급)로 골든을 굳히게 된다 — 캡처 전에 기체를 확인한다
assert load_example()["mass"]["m_empty"] == 800.0, "골든은 구 합성 기체(1200 kg) 기준이다"

from fastapi.testclient import TestClient  # noqa: E402

from claw_server import create_app  # noqa: E402
from tests.claw_server.golden import server_goldens  # noqa: E402

import golden_io  # noqa: E402  (server_goldens가 엔진 골든 폴더를 sys.path에 올린다)
import hexjson  # noqa: E402

TERMINAL = ("done", "error", "cancelled")


def _compute(fn):
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(create_app(data_dir=pathlib.Path(tmp) / "store")) as client:
            def wait(job_id, timeout=300.0):
                deadline = time.time() + timeout
                while time.time() < deadline:
                    j = client.get(f"/api/jobs/{job_id}").json()
                    if j["status"] in TERMINAL:
                        return j
                    time.sleep(0.02)
                raise AssertionError(f"작업 시간 초과: {job_id}")
            return server_goldens.shrink(fn(client, wait))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    out = HERE / "profile_example"
    out.mkdir(exist_ok=True)
    for name, fn in server_goldens.GOLDENS.items():
        if args.only and name not in args.only:
            continue
        a, b = _compute(fn), _compute(fn)
        ea, eb = hexjson.encode(a), hexjson.encode(b)
        if hexjson.dumps(ea) != hexjson.dumps(eb):
            sys.exit(f"{name}: 비결정적 — {hexjson.first_diff(ea, eb)}")
        golden_io.save(out / f"{name}.json", name, a, "full", force=args.force)
        print(f"captured {name}")


if __name__ == "__main__":
    main()
