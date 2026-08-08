"""작업 라우트 — 조회·취소 + 웹소켓 진행률 푸시. 실행 제출은 도메인별 라우트가 담당."""

import asyncio

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from claw_server.jobs import TERMINAL_STATES

router = APIRouter(tags=["jobs"])

_WS_POLL_S = 0.1  # 단독 사용자 로컬 — 폴링 푸시로 충분 [기본값]


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


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str) -> None:
    """진행률 스트림 — 접속 즉시 현재 상태, 이후 변화 시 푸시, 종단 상태로 종료."""
    await websocket.accept()
    job = websocket.app.state.jobs.get(job_id)
    try:
        if job is None:
            await websocket.send_json({"error": f"작업 없음: {job_id}"})
            await websocket.close(code=4404)
            return
        last = None
        while True:
            d = job.to_dict()
            if d != last:
                await websocket.send_json(d)
                last = d
            if d["status"] in TERMINAL_STATES:
                break
            await asyncio.sleep(_WS_POLL_S)
        await websocket.close()
    except WebSocketDisconnect:
        return  # 클라이언트 이탈 — 작업은 계속 진행
