"""M0 common — 규약·단위·자세·좌표변환·인터페이스 계약 (docs/conventions.md 구현체).

의존성 없음(L0). 다른 모듈은 규약 관련 수치·변환을 반드시 이 패키지로만 다룬다.
"""

from claw.common import units
from claw.common.constants import G0
from claw.common.contracts import (
    GuidanceCommand,
    LinearModel,
    NavOutput,
    SimResult,
    SurfaceCommand,
    TrimCase,
    TrimResult,
    VehicleState,
)
