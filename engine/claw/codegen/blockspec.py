"""블록별 부가 명세 — Python 백엔드와 C 백엔드가 **함께** 쓰는 표.

블록 파라미터는 이미 `ParamDef`가 갖고 있지만, 코드 생성에는 그것만으로 부족한
두 가지가 더 필요하다: 상태 필드의 논리 이름(비활성 시 무엇을 대입할지 IR이
가리켜야 한다)과 `step()` 호출 형태(모든 블록이 `step(u)`인 것은 아니다).

여기 한 곳에 두는 이유는 같다 — 두 백엔드가 서로 다른 표를 보면 그 순간 어긋난다.
"""

from claw.blocks.basic import Divide, Product, Sum, Switch
from claw.blocks.controllers import PID
from claw.blocks.filters import CommandFilter

# step(u) 계약을 따르지 않는 블록. CommandFilter는 step(cmd, current)이라
# 입력 두 개를 시퀀스가 아니라 위치 인자로 받는다 (autopilot.py:60)
# PID는 위치 인자(오차, 축 외부항)와 게인 키워드를 **함께** 받는다 — 외부항은
# 출력이 아니라 안티와인드업 판정에만 쓰인다 (controllers.py PID.step)
CALL_STYLE = {CommandFilter: "positional", PID: "positional+gains"}

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


# 추월 동기화(IR `Node.resync`)를 지원하는 블록 — 블록 → 동기화하는 상태 필드.
# 입력 자리는 IR이 정한다: 첫째가 명령(목표), 둘째가 측정이다(CommandFilter.step(cmd, current)).
# 표에 없는 블록에 resync를 달면 실행기(GraphRunner)와 생성기(emit_c)가 조립 시점에 거부한다.
RESYNC = {CommandFilter: "x"}


def resync_state(inst, cmd, meas) -> None:
    """추월 동기화 — 측정이 상태를 앞질러 명령 쪽에 있으면 상태를 측정으로 다시 시드한다.

    판정은 `(meas − x)·(cmd − meas) > 0` 하나다 — 두 차가 같은 부호일 때(x < meas < cmd 또는
    x > meas > cmd)만 참이다. 같거나(0) NaN이면 거짓이라 아무것도 안 한다. 부등식 둘을 &&로 잇지 않고
    곱 하나로 두는 것은 생성 C에서 **단일 조건 결정**이 되게 하려는 것이다(분기 커버리지 = MC/DC,
    verify/mcdc.py 머리말). C는 같은 식을 문자 그대로 낸다(emit_c의 CommandFilter 에미터).

    미시드(`_x`가 None)면 건너뛴다 — 첫 step이 측정으로 시드하므로 그 스텝의 판정은 어차피 거짓이다
    (C는 시드 뒤에 같은 판정을 하므로 결과가 같다).
    """
    field = RESYNC[type(inst)]
    x = getattr(inst, f"_{field}")
    if x is not None and (meas - x) * (cmd - meas) > 0.0:
        setattr(inst, f"_{field}", float(meas))


def get_state(inst, field) -> float:
    """상태 읽기 — `set_state`의 read 대칭 (계측 전용, 법칙 경로 미사용).

    상태는 그래프 노드의 출력이 아니라 인스턴스 속성이라 `last_env`에 없다 —
    적분기 값(안티와인드업 진단의 근거)을 보려면 이 창구가 필요하다.
    """
    return float(getattr(inst, f"_{field}"))
