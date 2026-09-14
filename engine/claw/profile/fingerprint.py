"""기체 프로파일 지문 둘 — 계보 도장과 플랜트 도장 (02 §5.6 · 02 §2.4).

- profile_fp: 적용된 문서(형상 변형 반영) 전체에서 **이름표만** 뺀 것. "어느 기체에서 나왔는가"를
  말하는 계보 지문이다 — 서버 결과 meta·응답의 `profile` 블록이 싣고, 스냅숏이 이 지문을 이름으로
  남는다. 이름을 바꿔도 같은 기체는 같은 지문이다(그래서 스냅숏의 이름표는 믿지 않는다).
- plant_fp: 트림·선형화가 보는 섹션만. δe_trim 도출 표가 낡았는지(플랜트가 바뀌었는지)를
  이것으로 판정한다 — 게인을 고쳤다고 표가 낡지는 않는다.

해시 규격은 `claw.params.paramset.canonical_hash` 하나다(M15와 공유).
"""

import copy

from claw.params.paramset import canonical_hash
from claw.profile.patch import parse_pointer

PLANT_SECTIONS = ("geometry", "aero", "stall", "mass", "propulsion", "ground", "trim", "surfaces")

# 지문에서 빼는 자리 — 이름표와 자유 텍스트 출처. 목록은 테스트가 고정한다
# (항목을 더하면 "같은 기체"의 정의가 넓어지므로 조용히 늘면 안 된다)
FP_EXCLUDED = (
    "/id",
    "/name",
    "/description",
    "/is_example",
    "/variants",
    "/law/design/provenance",
    "/law/alloc/de_trim/provenance",
)


def plant_fingerprint(effective: dict) -> str:
    return canonical_hash({k: effective[k] for k in PLANT_SECTIONS})


def profile_fingerprint(effective: dict) -> str:
    doc = copy.deepcopy(effective)
    for ptr in FP_EXCLUDED:
        tokens = parse_pointer(ptr)
        node = doc
        for t in tokens[:-1]:
            node = node.get(t) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(tokens[-1], None)
    return canonical_hash(doc)
