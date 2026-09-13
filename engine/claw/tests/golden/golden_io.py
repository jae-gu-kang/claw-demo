"""골든 저장·비교 공용 — 엔진·서버 골든이 같은 파일 형식을 쓴다."""

import json
import pathlib
import subprocess

import hexjson


def head_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render(value, mode):
    return hexjson.digest(value) if mode == "digest" else hexjson.encode(value)


def save(path: pathlib.Path, name, value, mode, force=False):
    if path.exists() and not force:
        raise FileExistsError(f"{path} 이미 있음 — 골든은 이관 전 HEAD에서만 굳힌다 (--force로 재생성)")
    doc = {"golden": name, "mode": mode, "captured_at": head_commit(), "value": render(value, mode)}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def compare(path: pathlib.Path, name, value, mode):
    """저장 골든과 비교 — 다르면 첫 차이 경로를 담은 AssertionError."""
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["mode"] == mode, f"{name}: 저장 mode {stored['mode']} ≠ {mode}"
    new = json.loads(hexjson.dumps(render(value, mode)))  # 저장본과 같은 JSON 왕복을 거친다
    old = stored["value"]
    if hexjson.dumps(new) != hexjson.dumps(old):
        raise AssertionError(f"{name} 골든 불일치 (저장 {stored['captured_at']}): "
                             f"{hexjson.first_diff(old, new)}")
