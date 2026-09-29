"""공통 운용공간 라우트 (05 §11) — 요구 운용영역 → 기본 모델 격자.

탭이 격자를 따로 만들지 않고 여기서 받는다(05 §11.12 「정의는 한 곳」). 점을 어디에 둘지와 트림 전 상태(미계산 ·
모델 부족)는 엔진 claw.opspace가 정하고, 서버는 기체 해석·요청 검증·직렬화만 한다. 동기 응답이다 — 트림을
풀지 않고 좌표만 만든다(상한 claw.opspace.basegrid.MAX_BASE_POINTS).
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from claw.opspace import STATE_LABEL, STATE_ORDER, base_grid, model_range_of, region_of
from claw_server.refs import ProfileRef, profile_echo, resolve_profile

router = APIRouter(tags=["grid"])

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]

NO_REGION = ("이 기체 문서에는 요구 운용영역(operating_region)도 미션 템플릿 격자(trim_grid)도 없어 기본 격자를 만들 수 "
             "없습니다 — 기체 문서에 요구 운용영역을 적습니다.")


class BaseGridIn(BaseModel):
    """기본 격자 명세 — 안 준 칸은 요구 운용영역의 기본 격자 명세(base_grid)를 쓴다."""

    profile: ProfileRef | None = None
    n_mach: int | None = Field(default=None, ge=2, le=50)
    alts: list[FiniteFloat] | None = Field(default=None, min_length=1, max_length=20)
    fuels: list[FiniteFloat] | None = Field(default=None, min_length=1, max_length=20)


def region_context(built) -> dict:
    """결과·응답에 싣는 요구영역 블록 — 초안(미확정)이면 그 사실이 결과에 남는다(05 §11.2)."""
    region = region_of(built.doc)
    return {"region": None if region is None else region.to_dict(), "model": model_range_of(built).to_dict()}


@router.post("/grid/base")
def post_base_grid(req: BaseGridIn, request: Request) -> dict:
    built = resolve_profile(request, req.profile)
    region = region_of(built.doc)
    ctx = region_context(built)
    echo = profile_echo(built)
    if region is None:
        return {**ctx, "reason": NO_REGION, "axis": [], "rows": [], "points": [], "counts": {},
                "labels": STATE_LABEL, "profile": echo}
    try:
        out = base_grid(region, model_range_of(built), n_mach=req.n_mach, alts=req.alts, fuels=req.fuels)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    counts = {s: 0 for s in STATE_ORDER}
    for p in out["points"]:
        counts[p["state"]] += 1
    return {**ctx, "reason": None, **out, "counts": {s: n for s, n in counts.items() if n},
            "labels": STATE_LABEL, "profile": echo}
