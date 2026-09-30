"""Persistent design alternatives and immutable revisions, separate from result retention."""

import copy
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


_ID = re.compile(r"[a-f0-9]{32}")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DesignEntityStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, entity_id):
        if not _ID.fullmatch(entity_id):
            raise ValueError("잘못된 설계안 ID")
        return self.root / f"{entity_id}.json"

    def get(self, entity_id):
        return json.loads(self._path(entity_id).read_text(encoding="utf-8"))

    def list(self, profile_id=None, variant=None):
        out = []
        for path in self.root.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if profile_id is not None and item.get("profile_id") != profile_id:
                continue
            if profile_id is not None and item.get("variant") != variant:
                continue
            out.append(item)
        return sorted(out, key=lambda item: item["updated_at"], reverse=True)

    def create(self, profile_id, variant, name, branch=None):
        with self._lock:
            entity_id = uuid.uuid4().hex
            item = {"id": entity_id, "profile_id": profile_id, "variant": variant,
                    "name": name, "branch": branch, "created_at": _now(),
                    "updated_at": _now(), "versions": []}
            self._write(item)
            return copy.deepcopy(item)

    def append_version(self, entity_id, expected_count, version):
        with self._lock:
            item = self.get(entity_id)
            if len(item["versions"]) != expected_count:
                raise RuntimeError("설계안이 그사이 바뀌었습니다. 다시 불러와 저장하세요")
            entry = {**copy.deepcopy(version), "number": expected_count + 1,
                     "created_at": _now(), "evaluations": [], "artifacts": []}
            item["versions"].append(entry)
            item["updated_at"] = _now()
            self._write(item)
            return copy.deepcopy(item)

    def attach_artifact(self, entity_id, number, artifact):
        with self._lock:
            item = self.get(entity_id)
            if not 1 <= number <= len(item["versions"]):
                raise ValueError("없는 설계 버전")
            version = item["versions"][number - 1]
            artifacts = version.setdefault("artifacts", [])
            if any(a["result_id"] == artifact["result_id"] for a in artifacts):
                return copy.deepcopy(item)
            artifacts.append({**artifact, "attached_at": _now()})
            item["updated_at"] = _now()
            self._write(item)
            return copy.deepcopy(item)

    def attach_evaluation(self, entity_id, number, evaluation):
        with self._lock:
            item = self.get(entity_id)
            if not 1 <= number <= len(item["versions"]):
                raise ValueError("없는 설계 버전")
            version = item["versions"][number - 1]
            if any(e["result_id"] == evaluation["result_id"] for e in version["evaluations"]):
                return copy.deepcopy(item)
            version["evaluations"].append({**evaluation, "attached_at": _now()})
            item["updated_at"] = _now()
            self._write(item)
            return copy.deepcopy(item)

    def mark_adopted(self, entity_id, number, revision):
        with self._lock:
            item = self.get(entity_id)
            item["versions"][number - 1]["adopted_revision"] = revision
            item["updated_at"] = _now()
            self._write(item)
            return copy.deepcopy(item)

    def _write(self, item):
        path = self._path(item["id"])
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(item, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        tmp.replace(path)
