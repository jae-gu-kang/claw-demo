"""작업 라우트 — 조회·취소. 실행 제출은 도메인별 라우트(/trim 등)가 담당."""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["jobs"])


def _get_job(request: Request, job_id: str):
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"작업 없음: {job_id}")
    return job


@router.get("/jobs")
def list_jobs(request: Request) -> list:
    return [j.to_dict() for j in request.app.state.jobs.list()]


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict:
    return _get_job(request, job_id).to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict:
    """협조적 취소 요청 (멱등) — 엔진 진행 콜백이 다음 호출에서 감지."""
    job = _get_job(request, job_id)
    job.request_cancel()
    return job.to_dict()
