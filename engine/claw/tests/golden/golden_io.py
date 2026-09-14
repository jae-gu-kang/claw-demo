"""골든 저장·비교 공용 — 엔진·서버 골든이 같은 파일 형식을 쓴다."""

import json
import pathlib
import subprocess

import hexjson


def head_commit() -> str:
    """캡처 기준 커밋 — 추적 파일이 고쳐진 트리에서 굳혔으면 `+dirty`를 붙인다.

    그 커밋만으로는 골든을 재현할 수 없다는 뜻이다. 표시가 없으면 사람이 그 커밋을 체크아웃해
    재현을 시도하다 헤맨다.
    """
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return f"{head}+dirty" if dirty else head
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
