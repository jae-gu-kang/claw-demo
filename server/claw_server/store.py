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

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")  # fullmatch 사용 — '$'는 후행 개행 허용


class ResultStore:
    def __init__(self, root, limit: int | None = None):
        if limit is not None and limit < 1:  # 0·음수는 슬라이스가 뒤집혀 전량 삭제 사고
            raise ValueError(f"잘못된 보존 상한: {limit!r}")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.limit = limit  # 보존 개수 상한 (None = 무제한) — 휘발성 디스크 배포용

    def save(self, result_id: str, payload: dict, meta: dict | None = None) -> None:
        self._check_id(result_id)
        meta = dict(meta or {})
        meta["id"] = result_id
        self._write(self.root / f"{result_id}.json", payload)
        self._write(self.root / f"{result_id}.meta.json", meta)
        if self.limit is not None:
            for old in self.list()[self.limit :]:  # created 내림차순 → 초과분 = 오래된 것
                rid = str(old.get("id", ""))
                if not _ID_RE.fullmatch(rid):  # 외부 유입 메타 방어 — 경로 조작 불허 유지
                    continue
                # 메타 먼저 — 목록에서 사라진 뒤 본문 제거 (본문 없는 유령 목록 방지)
                (self.root / f"{rid}.meta.json").unlink(missing_ok=True)
                (self.root / f"{rid}.json").unlink(missing_ok=True)

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
        """저장 결과 메타 목록 — 최신(created 내림차순) 우선. 손상 메타는 건너뜀."""
        metas = []
        for p in self.root.glob("*.meta.json"):
            try:
                metas.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue  # 손상 파일 하나가 목록 전체를 죽이지 않도록
        return sorted(metas, key=lambda m: m.get("created", 0.0), reverse=True)

    @staticmethod
    def _check_id(result_id: str) -> None:
        if not _ID_RE.fullmatch(result_id):  # 경로 조작 차단 ('.' '/' 개행 등 불허)
            raise ValueError(f"잘못된 결과 id: {result_id!r}")

    @staticmethod
    def _write(path: Path, obj: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        tmp.replace(path)
