"""M13 FastAPI 앱 팩토리 — REST 계층 (02 §2.3: 엔진 API 소비자, 도메인 로직 없음)."""

import os

from fastapi import FastAPI

import claw.blocks  # noqa: F401 — import 부수효과: 전역 REGISTRY "blocks" 등록
import claw.guidance  # noqa: F401 — "guidance" 카테고리 등록
import claw.plant  # noqa: F401 — "actuator" 카테고리 등록
from claw_server.jobs import JobManager
from claw_server.routes import analysis as analysis_routes
from claw_server.routes import jobs as jobs_routes
from claw_server.routes import results as results_routes
from claw_server.routes import sim as sim_routes
from claw_server.routes import system as system_routes
from claw_server.routes import trim as trim_routes
from claw_server.store import ResultStore


def create_app(data_dir=None) -> FastAPI:
    """앱 생성 — data_dir: 결과 저장 루트 (기본 $CLAW_SERVER_DATA 또는 ./server_data)."""
    app = FastAPI(title="CLAW server", version="0.1.0")
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
    ):
        app.include_router(router, prefix="/api")
    return app
