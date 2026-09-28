"""결과 라우트 — 저장 산출물 목록(메타만)·본문 조회."""

from fastapi import APIRouter, Request

from claw_server.routes.sim import stream_result_body

router = APIRouter(tags=["results"])


@router.get("/results")
def list_results(request: Request) -> list:
    return request.app.state.store.list()


# 반환 주석 dict는 OpenAPI 계약(200 = JSON 객체)을 그대로 두려는 것이다 — 실제 반환은
# StreamingResponse이고, FastAPI는 Response를 검증·재직렬화 없이 그대로 보낸다.
@router.get("/results/{result_id}")
def get_result(request: Request, result_id: str) -> dict:
    """저장 본문 통째 — 파일을 **파싱 없이** 흘려보낸다(routes/sim.stream_result_body, 1 MB씩).

    dict로 돌려주면 파싱본과 응답 직렬화본이 함께 선다. sim 본문이면 uvicorn 단일 워커 RSS가
    S1 기본 미션(68.6 MB)에서 +195 MB, 예제 기체 750 s(106.9 MB)에서 +338 MB(정점 516 MB)라
    Render 무료 512 MB를 이 요청 하나가 넘겼다 — 웹 블록도 재생 오버레이·결과 탭 브리핑·
    원본 JSON 링크가 sim에도 부른다. 흘려보내면 크기와 무관하게 +8~12 MB다.
    파일 바이트가 곧 저장 본문의 JSON 문서라 값·키 순서는 예전 응답과 같고 글자 모양
    (줄 나눔·공백·수 표기 1e-05 ↔ 0.00001)만 다르다(줄 나눈 본문 — store.py 머리말).
    종류를 묻지 않는다 — 어느 종류든 같은 길이다.

    없음·부정 형식 id(ValueError)는 존재 여부를 구분하지 않고 404 그대로다. 파싱하지 않으므로
    손상 본문은 404가 아니라 그대로 나간다 — 저장이 tmp→rename 원자적이라 잘린 본문은
    생기지 않는다(재생 stride 1과 같은 규약)."""
    return stream_result_body(request, result_id)
