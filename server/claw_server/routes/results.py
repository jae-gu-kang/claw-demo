"""결과 라우트 — 저장 산출물 목록(메타만)·본문 조회."""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["results"])


@router.get("/results")
def list_results(request: Request) -> list:
    return request.app.state.store.list()


@router.get("/results/{result_id}")
def get_result(request: Request, result_id: str) -> dict:
    try:
        return request.app.state.store.load(result_id)
    except (KeyError, ValueError):
        # 부정 형식 id(ValueError)도 존재 여부를 구분하지 않고 404
        raise HTTPException(status_code=404, detail=f"결과 없음: {result_id}")
