"""탑재 C 신뢰성 검증 라우트 (검증 탭, M12) — 202 배치 작업.

Autocode 탭이 보여 주는 것과 **같은 조립**(`build_flight_law`)에서 생성한 C를
엔진 검증기(`claw.verify.verify_flight`)에 태운다: 정적 규율 → 엄격 컴파일 →
대조 미션 Python↔C 비트 대조 → 밟은 경로 단정 → 라인·분기 커버리지.

판정 문구·요약 행은 전부 엔진이 낸다 — 서버는 요청 검증·작업 실행·저장만.
컴파일러·커버리지 툴이 없는 배포(무료 데모 등)에서는 해당 검사가 사유와 함께
"생략"으로 남는 것까지가 엔진 리포트의 일부다.
"""

from fastapi import APIRouter, Request, Response
from pydantic import Field

from claw.verify import verify_flight
from claw_server.routes.codegen import FlightCodeIn, build_flight_law
from claw_server.serialize import to_jsonable

router = APIRouter(tags=["verify"])


class VerifyFlightIn(FlightCodeIn):
    """검증 요청 — 탑재 C 생성 요청과 같은 형상 필드 + 대조 미션 길이.

    t_end 기본 180 s = 패리티 테스트와 같은 정본 대조 미션이다. 줄이면 빨라지지만
    모드 전환·포화를 다 못 밟아 「밟은 경로」 검사가 그 사실을 fail로 말한다.
    """

    t_end: float = Field(180.0, gt=0, le=600)


@router.post("/verify/flight", status_code=202)
def submit_verify(req: VerifyFlightIn, request: Request, response: Response) -> dict:
    # 검증할 수 없는 형상은 수락하지 않는다 — 202 뒤 작업 오류보다 즉시 422가 낫다
    law = build_flight_law(req)
    store = request.app.state.store

    def work(job):
        report = verify_flight(
            law, t_end=req.t_end, control_hz=req.control_hz,
            on_progress=lambda done, total, message="": job.report(
                done, total, message=message),
        )
        if report is None:  # 협조적 취소 — 부분 리포트는 없다 (반쪽 판정은 판정이 아니다)
            return
        store.save(
            job.id,
            {"kind": "verify_flight", "report": to_jsonable(report)},
            meta={
                "kind": "verify_flight",
                "created": job.created,
                "fingerprint": report["fingerprint"],
                "verdict": report["verdict"],
                "steps": report.get("steps"),
            },
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("verify_flight", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()
