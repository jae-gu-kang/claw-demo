"""트림 배치 라우트 (02 §8 워크플로우 3단계) — 케이스 매트릭스 → 배치 작업.

엔진 trim_batch를 그대로 호출 — 인접 시드·연속성·자동 판정 플래그는 엔진 소관.
서버는 요청 검증·이름 자동 생성·직렬화·저장만 담당한다.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, model_validator

from claw.common.contracts import TrimCase
from claw_server.refs import ProfileRef, profile_echo, resolve_profile
from claw.opspace import model_range_of, pre_state, region_of, trim_assessment
from claw.opspace.verdict import VerdictContext, condition_verdict
from claw.trim import trim_batch
from claw_server.routes.grid import region_context
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
    profile: ProfileRef | None = None  # 기체 선택 — 없으면 예제 기체 (02 §5.6)
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
    profile = resolve_profile(request, req.profile)
    ac = profile.aircraft()
    echo = profile_echo(profile)
    cases = build_cases(req.cases)
    store = request.app.state.store

    # 근거 계산이 기체를 다시 조립하지 않게 이미 만든 것을 넘긴다(opspace/states.py 캐시 키 "aircraft")
    region, model = region_of(profile.doc), model_range_of(profile)
    # 조건 판정 문맥(05 §11.3 · 이관 8단계)은 작업당 한 번 — 점마다 기체 문서를 다시 읽지 않는다. 근거 계산 캐시도 그
    # 문맥의 것을 같이 쓴다(자동 설계와 같은 캐시 규약)
    vctx = VerdictContext.from_profile(profile, cache={"aircraft": ac})

    def with_state(tr) -> dict:
        """트림 해 + 조건 상태(05 §11.3) — 계산 실패·제약 도달·물리적 불가를 가른다. 여유 판정(margin)은 상태와 따로
        싣고, 물리 한계에 붙은 미수렴의 판정 근거(state_evidence — 한계 고정 평형 해들)도 싣는다. 요구영역 판정
        (region_state)도 따로다: 손으로 더한 케이스는 영역 밖일 수 있고, 그래도 사용자가 요청했으니 푼다.

        verdict는 항목별 조건 판정(trim·model·limits·margin·채택) — 자동 설계와 같은 규칙(opspace/verdict.py)이라
        트림 탭과 자동 설계 표가 같은 조건에 같은 말을 한다. 트림 항목은 방금 잰 조건 상태를 그대로 넘긴다."""
        out = trim_result_dict(tr)
        if tr.case.condition != "level":
            return {**out, "state": None, "state_reasons": [], "margin": None, "state_evidence": None,
                    "region_state": None, "verdict": None}
        a = trim_assessment(tr, profile, model, cache=vctx.cache)
        rs = None if region is None else pre_state(region, model, tr.case.mach, tr.case.alt, tr.case.fuel)
        rs = None if rs == "not_run" else rs
        # 요구영역 항목은 문맥이 요구영역으로 분류한다(region_state와 달리 모델 부족을 섞지 않는다)
        verdict = condition_verdict(tr, vctx, trim=(a["state"], a["reasons"]))
        return {**out, "state": a["state"], "state_reasons": a["reasons"], "margin": a["margin"],
                "state_evidence": a["evidence"], "region_state": rs, "verdict": verdict}

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
            {"kind": "trim_batch", "results": [with_state(r) for r in results],
             "profile": echo, **region_context(profile)},
            meta={
                "kind": "trim_batch",
                "created": job.created,
                "n": len(results),
                "fingerprint": req.fingerprint,
                "profile": echo,
            },
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("trim_batch", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()
