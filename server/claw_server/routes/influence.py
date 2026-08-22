"""영향성 라우트 (02 §2.4, M15) — 파라미터 하나가 전체 시스템에 미치는 영향.

**도메인 로직은 없다.** 그래프 diff·도달성·섭동 판정은 전부 엔진
`claw.pipeline.influence`가 하고, 여기서는 요청 형상을 엔진 `Shape`로 옮기고
결과를 회신할 뿐이다 (02 §2.3 — 서버는 엔진 API 소비자).

요청 모델은 `codegen.py`의 `FlightCodeIn`을 **상속**한다. 같은 "현재 편집 형상"을
받는 자리라 필드와 유한성 검증을 다시 적으면 두 곳이 갈라진다 (02 §5.5). codegen이
sim에서 `TableIn`을 가져다 쓰는 것과 같은 선례다.
"""

import math
import time

from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator

from claw.pipeline.influence import Shape, structural_payload
from claw.tables import Table
from claw_server.routes.codegen import FlightCodeIn

router = APIRouter(tags=["influence"])


class InfluenceIn(FlightCodeIn):
    """형상(FlightCodeIn) + 법칙 밖 컴포넌트 + 탐침 설정.

    `scas`·`mixer`·`alpha_margin`은 `FlightCodeIn`에 없다 — 탑재 C 생성은 조립된
    형상만 있으면 되지만, 영향성은 **그 형상을 흔들어야** 하기 때문이다.
    """

    scas: dict | None = None  # {'pitch': {'kp': …}, …}
    mixer: dict | None = None
    alpha_margin: float | None = None
    nav: dict | None = None
    actuators: dict | None = None
    guidance: dict | None = None
    include_offgraph: bool = True
    probe_rel: float = Field(0.01, gt=0.0, le=0.5)

    @field_validator("scas", "mixer", "nav", "actuators", "guidance")
    @classmethod
    def _finite_leaves_only(cls, v):
        """타입·범위 판정은 엔진 ParamDef 몫 — 서버는 경계 유한성만 (sim·codegen과 동일).

        NaN은 ParamDef의 범위 비교(`v < lo`)를 조용히 통과하므로 여기서 막는다.
        """
        if v is not None:
            for key, val in v.items():
                leaves = val.values() if isinstance(val, dict) else (
                    val if isinstance(val, (list, tuple)) else (val,)
                )
                for x in leaves:
                    if isinstance(x, float) and not math.isfinite(x):
                        raise ValueError(f"비유한값 파라미터: {key}={val!r}")
        return v

    @field_validator("alpha_margin")
    @classmethod
    def _finite_margin(cls, v):
        if v is not None and not math.isfinite(v):
            raise ValueError("비유한값 alpha_margin")
        return v


def to_shape(req: InfluenceIn) -> Shape:
    """요청 → 엔진 형상. 지정하지 않은 자리는 비워 두어 **엔진 기본값이 채우게** 한다."""
    gain_tables = None
    if req.gain_tables is not None:
        gain_tables = {
            name: Table(spec.axes, spec.data, name=name, extrapolate=spec.extrapolate)
            for name, spec in req.gain_tables.items()
        }
    return Shape(
        control_hz=req.control_hz,
        with_schedule=req.with_schedule,
        with_limiter=req.with_limiter,
        autopilot=dict(req.autopilot or {}),
        scas={k: dict(v) for k, v in (req.scas or {}).items()},
        mixer=dict(req.mixer or {}),
        alpha_margin=req.alpha_margin,
        gain_tables=gain_tables,
        nav=dict(req.nav or {}),
        actuators=dict(req.actuators or {}),
        guidance=dict(req.guidance or {}),
    )


@router.post("/influence/structural")
def influence_structural(req: InfluenceIn) -> dict:
    """1단 — 구조 + 도달성. 파라미터 65개를 각각 재조립해 diff하고도 100 ms 안쪽이라 동기다.

    구성 오류(범위 이탈·스케줄 불가 자리 등)는 엔진이 ValueError로 내고 422가 된다.
    """
    t0 = time.perf_counter()
    try:
        payload = structural_payload(
            to_shape(req),
            include_offgraph=req.include_offgraph,
            probe_rel=req.probe_rel,
        )
    except (ValueError, TypeError) as e:  # 엔진 판정 → 422 (sim·codegen과 같은 정책)
        raise HTTPException(status_code=422, detail=str(e))
    payload["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return payload
