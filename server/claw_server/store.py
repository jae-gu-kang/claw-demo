"""M13 결과 저장소 — JSON 파일 저장·조회 (단독 사용자 로컬, 02 §4).

본문({id}.json)과 메타({id}.meta.json)를 분리 — 목록 조회가 대형 시계열
본문을 읽지 않게 한다. 본문을 먼저 쓰고 메타를 마지막에 쓰므로 목록에
보이는 결과는 본문 존재가 보장된다. 쓰기는 tmp→rename으로 원자적.
allow_nan=False — 비유한값은 serialize 정책(NaN→null 등)으로 정리된 뒤여야
하며, 위반은 저장 시점에 ValueError로 드러난다.
"""

import json
import re
from pathlib import Path

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ResultStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, result_id: str, payload: dict, meta: dict | None = None) -> None:
        self._check_id(result_id)
        meta = dict(meta or {})
        meta["id"] = result_id
        self._write(self.root / f"{result_id}.json", payload)
        self._write(self.root / f"{result_id}.meta.json", meta)

    def load(self, result_id: str) -> dict:
        self._check_id(result_id)
        path = self.root / f"{result_id}.json"
        if not path.exists():
            raise KeyError(result_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def exists(self, result_id: str) -> bool:
        self._check_id(result_id)
        return (self.root / f"{result_id}.json").exists()

    def list(self) -> list:
        """저장 결과 메타 목록 — 최신(created 내림차순) 우선."""
        metas = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in self.root.glob("*.meta.json")
        ]
        return sorted(metas, key=lambda m: m.get("created", 0.0), reverse=True)

    @staticmethod
    def _check_id(result_id: str) -> None:
        if not _ID_RE.match(result_id):  # 경로 조작 차단 ('.' '/' 등 불허)
            raise ValueError(f"잘못된 결과 id: {result_id!r}")

    @staticmethod
    def _write(path: Path, obj: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        tmp.replace(path)
