"""트림 배치 라우트 (02 §8 워크플로우 2단계) — 케이스 매트릭스 → 배치 작업.

엔진 trim_batch를 그대로 호출 — 인접 시드·연속성·자동 판정 플래그는 엔진 소관.
서버는 요청 검증·이름 자동 생성·직렬화·저장만 담당한다.
"""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from claw.common.contracts import TrimCase
from claw.plant import make_demo_aircraft
from claw.trim import trim_batch
from claw_server.serialize import trim_result_dict

router = APIRouter(tags=["trim"])


class TrimCaseIn(BaseModel):
    name: str = ""  # 빈 이름 → "M{mach}_h{alt}_f{fuel}" 자동 생성
    mach: float = Field(gt=0.0)
    alt: float
    fuel: float = Field(ge=0.0)


class TrimBatchIn(BaseModel):
    aircraft: Literal["demo"] = "demo"  # 비행체 프로파일 교체 단위 (03 §7.2) — 데모만 등록
    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1)


@router.post("/trim/batch", status_code=202)
def submit_trim_batch(req: TrimBatchIn, request: Request) -> dict:
    ac = make_demo_aircraft()
    cases = [
        TrimCase(
            c.name or f"M{c.mach:.2f}_h{c.alt:.0f}_f{c.fuel:.0f}",
            mach=c.mach,
            alt=c.alt,
            fuel=c.fuel,
        )
        for c in req.cases
    ]
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

    return request.app.state.jobs.submit("trim_batch", work).to_dict()
