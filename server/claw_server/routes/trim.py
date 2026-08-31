"""트림 배치 라우트 (02 §8 워크플로우 2단계) — 케이스 매트릭스 → 배치 작업.

엔진 trim_batch를 그대로 호출 — 인접 시드·연속성·자동 판정 플래그는 엔진 소관.
서버는 요청 검증·이름 자동 생성·직렬화·저장만 담당한다.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, model_validator

from claw.common.contracts import TrimCase
from claw.plant import make_demo_aircraft
from claw.trim import trim_batch
from claw_server.serialize import trim_result_dict

router = APIRouter(tags=["trim"])

# JSON은 Infinity/NaN 리터럴을 파서가 허용하므로 경계에서 유한성을 강제 —
# 202 수락 후 저장 시점(allow_nan=False)에 배치 전체가 죽는 것을 방지
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class TrimCaseIn(BaseModel):
    """트림 케이스 — condition이 무엇을 푸는지 고른다 (엔진 trim.trim 디스패처).

    "level"  : 수평정상비행. mach > 0, alt는 비행 고도.
    "ground" : 지상 정지 평형(01 §3.3.1 이륙·착륙). **mach는 0이어야 하고**
               alt는 비행 고도가 아니라 **활주로 표고**다.
    """

    name: str = ""  # 빈 이름 → "M{mach}_h{alt}_f{fuel}" 자동 생성
    # mach 하한이 조건별로 갈리므로 필드 제약이 아니라 아래 검증기가 판정한다
    mach: float = Field(ge=0.0, allow_inf_nan=False)
    alt: float = Field(allow_inf_nan=False)
    fuel: float = Field(ge=0.0, allow_inf_nan=False)
    condition: Literal["level", "ground"] = "level"

    @model_validator(mode="after")
    def _mach_matches_the_condition(self):
        # 지상 평형에서 mach는 쓰이지 않는다 — 조용히 무시하지 않고 0을 요구한다.
        # 반대로 수평비행에 mach=0은 해가 없다(양력 0으로 중력을 못 맞춘다).
        if self.condition == "ground" and self.mach != 0.0:
            raise ValueError(f"condition='ground'는 정지 상태 — mach는 0이어야 함: {self.mach}")
        if self.condition == "level" and self.mach <= 0.0:
            raise ValueError(f"condition='level'은 mach > 0이 필요함: {self.mach}")
        return self


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
            condition=c.condition,
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
