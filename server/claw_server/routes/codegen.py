"""탑재 제어법칙 C 생성 라우트 (02 §1·§2.2, M16).

웹의 기존 "코드 생성"(파라미터 표현)과 다른 물건이다 — 여기서 나오는 것은
**FCC에 통합되어 그대로 실릴 제어법칙 코드**이고, 구조·블록 로직·파라미터가
전부 들어 있다. 산출물 정본은 `flight/gen/`(커밋됨)이며 이 라우트는 같은
생성기를 **현재 편집 중인 형상**으로 돌려 보여 준다.

**조립을 재현하지 않는다.** `make_demo_fcl` → `law.init(dt)` → `law.runner`가
`flight/generate.py`와 완전히 같은 경로다. 여기서 `fcl_graph(...)`를 따로
부르면 게인·타면 한계·마진이 또 한 곳에 적히고 한쪽만 고치면 조용히 어긋난다
(02 §5.5 중복 정의 금지 — 실제로 generate.py가 그 상태였다가 통합됨).
"""

import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from claw.codegen import emit_c, emit_runtime
from claw.fcl.demo import make_demo_fcl
from claw.params.registry import REGISTRY
from claw.tables import Table
from claw_server.routes.sim import TableIn

router = APIRouter(tags=["codegen"])

# 파일 이름 → 역할. 읽는 순서를 서버가 정해 준다 — 생성물이 10개가 넘으면
# "어디부터 보나"가 곧 사용성이다 (역할축은 MATLAB Embedded Coder 대응).
ROLE_ENTRY = "진입점"
ROLE_TYPES = "자료형"
ROLE_DATA = "파라미터 데이터"
ROLE_TOP = "조립부"
ROLE_PART = "서브시스템"
ROLE_RT = "공용 런타임"


class FlightCodeIn(BaseModel):
    """탑재 C 생성 요청 — 시뮬 요청(SimRunIn)의 법칙 관련 필드만 추린 것."""

    control_hz: float = Field(100.0, gt=0, le=1000)
    with_schedule: bool = True
    with_limiter: bool = True
    autopilot: dict | None = None
    gain_tables: dict[str, TableIn] | None = None

    @field_validator("autopilot")
    @classmethod
    def _finite_leaves_only(cls, v):
        """타입·범위·키 판정은 엔진 ParamDef 몫(아래 REGISTRY.create) — 서버는
        경계 유한성만. NaN은 ParamDef 범위 비교를 조용히 통과한다 (sim.py와 동일 정책)."""
        if v is not None:
            for key, val in v.items():
                leaves = val if isinstance(val, (list, tuple)) else (val,)
                for x in leaves:
                    if isinstance(x, float) and not math.isfinite(x):
                        raise ValueError(f"비유한값 파라미터: {key}={val!r}")
        return v

    @field_validator("gain_tables")
    @classmethod
    def _tables_not_empty(cls, v):
        if v is not None and not v:
            raise ValueError("gain_tables가 빈 dict — 편집 없음이면 필드를 생략하세요")
        return v


def _role(name: str, base: str) -> str:
    if name.startswith("claw_rt."):
        return ROLE_RT
    stem = name.rsplit(".", 1)[0]
    if stem == f"{base}_types":
        return ROLE_TYPES
    if stem == f"{base}_data":
        return ROLE_DATA
    if stem == base:
        return ROLE_ENTRY if name.endswith(".h") else ROLE_TOP
    return ROLE_PART


def _order_key(name: str, base: str, groups: list[str]) -> tuple:
    """읽는 순서: 진입점 → 자료형 → 조립부 → 서브시스템(실행 순서) → 데이터 → 공용."""
    role = _role(name, base)
    rank = {
        ROLE_ENTRY: 0, ROLE_TYPES: 1, ROLE_TOP: 2,
        ROLE_PART: 3, ROLE_DATA: 4, ROLE_RT: 5,
    }[role]
    sub = 0
    if role == ROLE_PART:
        stem = name.rsplit(".", 1)[0]
        group = stem[len(base) + 1:]
        sub = groups.index(group) if group in groups else len(groups)
    # 같은 짝은 .h를 먼저 — 무엇을 받아 무엇을 내는지가 먼저 잡힌다
    return (rank, sub, 0 if name.endswith(".h") else 1, name)


@router.post("/codegen/flight")
def flight_code(req: FlightCodeIn) -> dict:
    """현재 형상의 탑재 제어법칙 C — {파일명, 역할, 줄수, 본문} 목록.

    구성 오류(미정의 게인 키·범위 이탈 등)는 엔진이 ValueError로 내고 422가 된다.
    """
    dt = 1.0 / req.control_hz
    gain_tables = None
    if req.gain_tables is not None:
        gain_tables = {
            name: Table(spec.axes, spec.data, name=name, extrapolate=spec.extrapolate)
            for name, spec in req.gain_tables.items()
        }
    try:
        law = make_demo_fcl(
            with_schedule=req.with_schedule,
            with_limiter=req.with_limiter,
            autopilot=(
                REGISTRY.create("fcl", "Autopilot", req.autopilot) if req.autopilot else None
            ),
            gain_tables=gain_tables,
        ).init(dt)
    except (ValueError, TypeError) as e:  # 엔진 구성 검증 → 422 (sim.py와 같은 정책)
        raise HTTPException(status_code=422, detail=str(e))

    runner = law.runner
    module = emit_c(runner.graph, runner)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))

    base = runner.graph.name
    groups = [g for g, _nodes in runner.graph.partitions]
    names = sorted(files, key=lambda n: _order_key(n, base, groups))
    return {
        "artifact": base,
        "dt": dt,
        "fingerprint": module.fingerprint,
        "groups": groups,
        "files": [
            {
                "name": n,
                "role": _role(n, base),
                "lines": files[n].count("\n"),
                "text": files[n],
            }
            for n in names
        ],
    }
