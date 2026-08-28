"""블록별 부가 명세 — Python 백엔드와 C 백엔드가 **함께** 쓰는 표.

블록 파라미터는 이미 `ParamDef`가 갖고 있지만, 코드 생성에는 그것만으로 부족한
두 가지가 더 필요하다: 상태 필드의 논리 이름(비활성 시 무엇을 대입할지 IR이
가리켜야 한다)과 `step()` 호출 형태(모든 블록이 `step(u)`인 것은 아니다).

여기 한 곳에 두는 이유는 같다 — 두 백엔드가 서로 다른 표를 보면 그 순간 어긋난다.
"""

from claw.blocks.basic import Divide, Product, Sum, Switch
from claw.blocks.filters import CommandFilter

# step(u) 계약을 따르지 않는 블록. CommandFilter는 step(cmd, current)이라
# 입력 두 개를 시퀀스가 아니라 위치 인자로 받는다 (autopilot.py:60)
CALL_STYLE = {CommandFilter: "positional"}

# 가변 입력 블록 — 입력이 하나여도 **시퀀스**로 받는다 (basic.py:22).
# 입력 개수로 판별하면 단일 입력 Sum(부호 반전 −β 등)에서 조용히 깨진다.
SEQ_INPUT = frozenset({Sum, Product, Divide, Switch})


def set_state(inst, field, value) -> None:
    """비활성 스텝의 상태 대입 — 논리 필드명 → 인스턴스 사설 속성.

    CommandFilter에서 `x` 대입은 곧 시드 완료를 뜻한다(`_x`가 None이 아니게 되므로).
    C 쪽에서는 별도 `seeded` 플래그를 함께 세워야 같은 의미가 된다 —
    그 처리는 emit_c의 CommandFilter 에미터가 맡는다.
    """
    setattr(inst, f"_{field}", float(value))


def get_state(inst, field) -> float:
    """상태 읽기 — `set_state`의 read 대칭 (계측 전용, 법칙 경로 미사용).

    상태는 그래프 노드의 출력이 아니라 인스턴스 속성이라 `last_env`에 없다 —
    적분기 값(안티와인드업 진단의 근거)을 보려면 이 창구가 필요하다.
    """
    return float(getattr(inst, f"_{field}"))
