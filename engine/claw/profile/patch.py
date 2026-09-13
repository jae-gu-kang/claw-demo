"""형상 변형 패치 — JSON Pointer(RFC 6901) 치환 맵 (02 §5.6).

변형은 `{"/mass/m_empty": 900.0, "/structural/q_max": null}`처럼 **경로 → 새 값**이다.
RFC 7386 merge patch를 쓰지 않는 이유: 거기서 null은 "키 삭제"인데 이 문서에서 null은
"없음"이라는 실제 값이다. 두 뜻이 한 기호에 겹치면 "q̄ 한계 없음"을 패치로 표현할 수 없다.

- 경로는 **이미 있는 자리**만 가리킨다 — 없는 경로는 오타이므로 거부한다
- 배열은 통째로 바꾸거나 인덱스로 한 칸을 바꾼다(끝에 붙이기 `-`는 없다)
- 식별 항목(schema_version·id·is_example)과 variants 자체는 변형이 못 바꾼다
"""

import copy
import re

from claw.profile.errors import ProfileError

FORBIDDEN_ROOTS = ("schema_version", "id", "is_example", "variants")


def parse_pointer(ptr) -> list:
    if not isinstance(ptr, str) or not ptr.startswith("/"):
        raise ProfileError(str(ptr), "JSON Pointer는 '/'로 시작해야 함")
    return [t.replace("~1", "/").replace("~0", "~") for t in ptr[1:].split("/")]


def _step(node, token, ptr):
    if isinstance(node, dict):
        if token not in node:
            raise ProfileError(ptr, "문서에 없는 경로")
        return token
    if isinstance(node, list):
        # RFC 6901 인덱스는 ASCII 숫자만, 앞자리 0 금지 — str.isdigit()는 '²'·'١'도 참이다
        if not re.fullmatch(r"0|[1-9][0-9]*", token):
            raise ProfileError(ptr, f"배열 인덱스가 아님: {token!r}")
        i = int(token)
        if i >= len(node):
            raise ProfileError(ptr, f"배열 범위 밖 인덱스 {i} (길이 {len(node)})")
        return i
    raise ProfileError(ptr, "값 안쪽으로는 경로를 이을 수 없음")


def get_pointer(doc, ptr):
    node = doc
    for token in parse_pointer(ptr):
        node = node[_step(node, token, ptr)]
    return node


def apply_patch(doc: dict, patch: dict) -> dict:
    """base 문서에 치환 맵을 적용한 **새 문서**(variants 제외). 원본은 바꾸지 않는다."""
    if not isinstance(patch, dict):
        raise ProfileError("/", "patch는 {경로: 값} 객체여야 함")
    out = copy.deepcopy({k: v for k, v in doc.items() if k != "variants"})
    for ptr, value in patch.items():
        tokens = parse_pointer(ptr)
        if tokens[0] in FORBIDDEN_ROOTS:
            raise ProfileError(ptr, f"형상 변형이 바꿀 수 없는 항목: {tokens[0]}")
        node = out
        for token in tokens[:-1]:
            node = node[_step(node, token, ptr)]
        node[_step(node, tokens[-1], ptr)] = copy.deepcopy(value)
    return out
