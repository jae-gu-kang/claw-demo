"""ParamSet — 값 스냅샷 + 검증 + YAML 입출력 + 지문(fingerprint)·diff.

- 정의(ParamDef)는 코드가 소유, 값은 YAML 파일이 소유 (구현 문서 §5.4·§5.5)
- YAML은 점 네임스페이스를 중첩 맵으로 저장 (사람 편집·diff 친화)
- fingerprint()는 값 스냅샷의 SHA-256 지문 — 산출물 계보·무효화·영향성 평가(§2.4)의 키
"""

import hashlib
import json

import yaml

from claw.params.param import ParamError


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _unflatten(flat):
    root = {}
    for k, v in flat.items():
        parts = k.split(".")
        node = root
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return root


class ParamSet:
    def __init__(self, defs, values=None):
        self._defs = {}
        for d in defs:
            if d.name in self._defs:
                raise ParamError(f"중복 파라미터 정의: {d.name}")
            self._defs[d.name] = d
        self._values = {name: d.validate(d.default) for name, d in self._defs.items()}
        for k, v in (values or {}).items():
            self.set(k, v)

    @property
    def defs(self):
        return dict(self._defs)

    def get(self, name):
        if name not in self._values:
            raise ParamError(f"정의되지 않은 파라미터: {name}")
        return self._values[name]

    def set(self, name, value):
        if name not in self._defs:
            raise ParamError(f"정의되지 않은 파라미터: {name}")
        self._values[name] = self._defs[name].validate(value)

    __getitem__ = get
    __setitem__ = set

    def as_dict(self):
        return dict(self._values)

    def fingerprint(self):
        """값 스냅샷의 결정적 지문 (SHA-256 앞 16자리 hex)."""
        canon = json.dumps(self._values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]

    def diff(self, other):
        """다른 스냅샷과의 값 차이: {이름: (self 값, other 값)} — Δ리포트의 입력."""
        names = set(self._values) | set(other.as_dict())
        out = {}
        ov = other.as_dict()
        for n in sorted(names):
            a, b = self._values.get(n), ov.get(n)
            if a != b:
                out[n] = (a, b)
        return out

    def copy_with(self, changes):
        """일부 값만 바꾼 새 스냅샷 — 영향성 평가·민감도 스윕용."""
        merged = dict(self._values)
        merged.update(changes)
        return ParamSet(self._defs.values(), merged)

    def to_json_schema(self, title="params"):
        """전체 파라미터의 JSON 스키마 — 웹 편집·파일 편집이 공유 (구현 문서 §5.4)."""
        return {
            "title": title,
            "type": "object",
            "additionalProperties": False,
            "properties": {name: d.to_json_schema() for name, d in sorted(self._defs.items())},
        }

    def save_yaml(self, path):
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                _unflatten(self._values), f, sort_keys=True, allow_unicode=True, default_flow_style=False
            )

    @classmethod
    def load_yaml(cls, path, defs):
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls(defs, _flatten(raw))
