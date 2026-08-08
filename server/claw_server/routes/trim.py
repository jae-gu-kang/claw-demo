"""트림 배치 라우트 (02 §8 워크플로우 2단계) — 케이스 매트릭스 → 배치 작업.

엔진 trim_batch를 그대로 호출 — 인접 시드·연속성·자동 판정 플래그는 엔진 소관.
서버는 요청 검증·이름 자동 생성·직렬화·저장만 담당한다.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from claw.common.contracts import TrimCase
from claw.plant import make_demo_aircraft
from claw.trim import trim_batch
from claw_server.serialize import trim_result_dict

router = APIRouter(tags=["trim"])

# JSON은 Infinity/NaN 리터럴을 파서가 허용하므로 경계에서 유한성을 강제 —
# 202 수락 후 저장 시점(allow_nan=False)에 배치 전체가 죽는 것을 방지
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class TrimCaseIn(BaseModel):
    name: str = ""  # 빈 이름 → "M{mach}_h{alt}_f{fuel}" 자동 생성
    mach: float = Field(gt=0.0, allow_inf_nan=False)
    alt: float = Field(allow_inf_nan=False)
    fuel: float = Field(ge=0.0, allow_inf_nan=False)


class TrimBatchIn(BaseModel):
    aircraft: Literal["demo"] = "demo"  # 비행체 프로파일 교체 단위 (03 §7.2) — 데모만 등록
    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1)


def build_cases(case_inputs: list[TrimCaseIn]) -> list[TrimCase]:
    """요청 케이스 → 엔진 TrimCase — 빈 이름 자동 생성 (analysis 라우트와 공유)."""
    return [
        TrimCase(
            c.name or f"M{c.mach:.2f}_h{c.alt:.0f}_f{c.fuel:.0f}",
            mach=c.mach,
            alt=c.alt,
            fuel=c.fuel,
        )
        for c in case_inputs
    ]


@router.post("/trim/batch", status_code=202)
def submit_trim_batch(req: TrimBatchIn, request: Request, response: Response) -> dict:
    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    store = request.app.state.store

    def work(job):
        results = trim_batch(
            ac,
            cases,
            fingerprint=req.fingerprint,
            on_progress=lambda done, total, tr: job.report(
                done, total, message=tr.case.name
            ),
        )
        store.save(
            job.id,
            {"kind": "trim_batch", "results": [trim_result_dict(r) for r in results]},
            meta={
                "kind": "trim_batch",
                "created": job.created,
                "n": len(results),
                "fingerprint": req.fingerprint,
            },
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("trim_batch", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()
