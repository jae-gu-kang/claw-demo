"""M13 FastAPI 앱 팩토리 — REST 계층 (02 §2.3: 엔진 API 소비자, 도메인 로직 없음)."""

import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import claw.blocks  # noqa: F401 — import 부수효과: 전역 REGISTRY "blocks" 등록
import claw.guidance  # noqa: F401 — "guidance" 카테고리 등록
import claw.plant  # noqa: F401 — "actuator" 카테고리 등록
from claw_server.jobs import JobManager
from claw_server.routes import analysis as analysis_routes
from claw_server.routes import gains as gains_routes
from claw_server.routes import jobs as jobs_routes
from claw_server.routes import results as results_routes
from claw_server.routes import sim as sim_routes
from claw_server.routes import system as system_routes
from claw_server.routes import trim as trim_routes
from claw_server.store import ResultStore


async def _validation_error_handler(request, exc: RequestValidationError):
    """422 응답 소독 — 위반 입력값(inf/NaN 등)이 응답 인코딩(allow_nan=False)을
    죽이지 않도록 비유한값 정책 적용 + ctx 예외 객체 문자열화."""
    from claw_server.serialize import to_jsonable

    errors = []
    for e in exc.errors():
        e = dict(e)
        e.pop("url", None)
        if "ctx" in e:
            e["ctx"] = {k: str(v) for k, v in e["ctx"].items()}
        e["input"] = to_jsonable(e.get("input"))
        errors.append(e)
    return JSONResponse(status_code=422, content={"detail": errors})


def create_app(data_dir=None) -> FastAPI:
    """앱 생성 — data_dir: 결과 저장 루트 (기본 $CLAW_SERVER_DATA 또는 ./server_data)."""
    app = FastAPI(title="CLAW server", version="0.1.0")
    # 단독 사용자 로컬 서버 (02 §4) — M14 dev 서버(다른 포트) 접속 허용 [기본값]
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.state.jobs = JobManager()
    app.state.store = ResultStore(
        data_dir
        if data_dir is not None
        else os.environ.get("CLAW_SERVER_DATA", "server_data")
    )
    for router in (
        system_routes.router,
        jobs_routes.router,
        results_routes.router,
        trim_routes.router,
        analysis_routes.router,
        sim_routes.router,
        gains_routes.router,
    ):
        app.include_router(router, prefix="/api")
    return app
