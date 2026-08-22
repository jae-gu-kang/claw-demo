"""flight 테스트 공통 — 저장소의 `flight/generate.py`를 import 가능하게 한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
