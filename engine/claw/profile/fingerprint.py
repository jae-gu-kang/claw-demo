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

# 지문에서 빼는 자리 — 이름표와 자유 텍스트 출처, 그리고 계산에 쓰이지 않는 화면 기본값(미션 템플릿 —
# 결과는 실제로 보낸 요청을 싣는다)과 표시 모델(화면이 기체를 그리는 방법). 목록은 테스트가 고정한다
# (항목을 더하면 "같은 기체"의 정의가 넓어지므로 조용히 늘면 안 된다)
FP_EXCLUDED = (
    "/id",
    "/name",
    "/description",
    "/is_example",
    "/variants",
    "/law/design/provenance",
    "/law/alloc/de_trim/provenance",
    "/mission_template",
    "/display",
)


def _ordered_axes(aero: dict) -> dict:
    """공력 표 항의 축 순서를 해시 입력에 싣는다 — 축 객체를 [이름, 격자] 쌍 목록으로 바꾼다.

    canonical_hash는 객체 키를 정렬하는데, 공력 표는 axes 키 순서가 data 중첩 순서다. 그대로 두면 격자 점 수가 같은
    두 축을 맞바꾼 문서(검증도 통과한다)가 물리는 다른데 지문은 같다. 표 항이 없는 문서는 그대로 돌려준다(예제 지문 불변)."""
    coefs = aero["coefficients"]
    if not any(isinstance(t["k"], dict) for terms in coefs.values() for t in terms):
        return aero
    return {**aero, "coefficients": {
        name: [{**t, "k": {"table": {**t["k"]["table"], "axes": [[ax, g] for ax, g in t["k"]["table"]["axes"].items()]}}}
               if isinstance(t["k"], dict) else t for t in terms]
        for name, terms in coefs.items()}}


def plant_fingerprint(effective: dict) -> str:
    return canonical_hash({k: (_ordered_axes(effective[k]) if k == "aero" else effective[k]) for k in PLANT_SECTIONS})


def profile_fingerprint(effective: dict) -> str:
    doc = copy.deepcopy(effective)
    doc["aero"] = _ordered_axes(doc["aero"])
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
