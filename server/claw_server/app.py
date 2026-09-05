"""M13 FastAPI 앱 팩토리 — REST 계층 (02 §2.3: 엔진 API 소비자, 도메인 로직 없음)."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import claw.blocks  # noqa: F401 — import 부수효과: 전역 REGISTRY "blocks" 등록
import claw.guidance  # noqa: F401 — "guidance" 카테고리 등록
import claw.plant  # noqa: F401 — "actuator" 카테고리 등록
from claw_server.auth import BasicAuthProtect
from claw_server.jobs import JobManager
from claw_server.routes import analysis as analysis_routes
from claw_server.routes import codegen as codegen_routes
from claw_server.routes import design as design_routes
from claw_server.routes import gains as gains_routes
from claw_server.routes import influence as influence_routes
from claw_server.routes import jobs as jobs_routes
from claw_server.routes import results as results_routes
from claw_server.routes import sim as sim_routes
from claw_server.routes import system as system_routes
from claw_server.routes import trim as trim_routes
from claw_server.routes import verify as verify_routes
from claw_server.routes import world as world_routes
from claw_server.store import ResultStore


class NoCacheStaticFiles(StaticFiles):
    """정적 파일에 Cache-Control: no-cache — 항상 재검증 강제.

    헤더 부재 시 브라우저 휴리스틱 캐시가 일반 새로고침(⌘R)에서 구버전 ES 모듈을
    재사용해 "파일을 고쳤는데 화면이 안 바뀌는" 함정이 생긴다 (02 §4 no-build 전제:
    정적 파일은 새로고침만으로 반영). no-cache는 미사용 금지가 아니라 ETag 재검증
    조건부 요청이므로 미변경 파일은 304로 비용이 거의 없다."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


async def _validation_error_handler(request, exc: RequestValidationError):
    """422 응답 소독 — 위반 입력값(inf/NaN 등)이 응답 인코딩(allow_nan=False)을
    죽이지 않도록 비유한값 정책 적용 + ctx 예외 객체 문자열화."""
    from claw_server.serialize import to_jsonable

    errors = []
    for e in exc.errors():
        e = dict(e)
        e.pop("url", None)
        if "ctx" in e:
            # 수치·문자열 등 직렬화 가능 값은 타입 보존, 예외 객체 등만 문자열화
            e["ctx"] = {
                k: to_jsonable(v)
                if isinstance(v, (int, float, str, bool, type(None)))
                else str(v)
                for k, v in e["ctx"].items()
            }
        if "input" in e:  # 원래 없던 오류에 input: null 주입 금지
            e["input"] = to_jsonable(e["input"])
        errors.append(e)
    return JSONResponse(status_code=422, content={"detail": errors})


def _default_web_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "web"  # 모노레포 루트/web (03 §5)


def create_app(data_dir=None, web_dir=None, access_password=None,
               result_limit=None) -> FastAPI:
    """앱 생성 — data_dir: 결과 저장 루트 (기본 $CLAW_SERVER_DATA 또는 ./server_data),
    web_dir: M14 정적 파일 루트 (기본 $CLAW_WEB_DIR 또는 모노레포 web/ — 없으면 API만),
    access_password: 공용 비밀번호 (기본 $CLAW_ACCESS_PASSWORD — 빈 값이면 무인증),
    result_limit: 결과 보존 개수 상한 (기본 $CLAW_RESULT_LIMIT — 0·미설정이면 무제한).

    네 인자 모두 **환경변수 기본값 + 명시 주입** 패턴이다 — 테스트가 환경을 건드리지
    않고 상한이 걸린 앱을 세울 수 있어야 보존 상한 관련 동작을 고정할 수 있다."""
    app = FastAPI(title="CLAW server", version="0.1.0")
    pw = (
        access_password
        if access_password is not None
        else os.environ.get("CLAW_ACCESS_PASSWORD", "")
    )
    if pw:  # add_middleware는 앞에 insert — 뒤의 CORS가 최외곽이라 프리플라이트는 인증 밖
        app.add_middleware(BasicAuthProtect, password=pw)
    # 단독 사용자 로컬 서버 (02 §4) — M14 dev 서버(다른 포트) 접속 허용 [기본값]
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.state.jobs = JobManager()
    app.state.store = ResultStore(
        data_dir
        if data_dir is not None
        else os.environ.get("CLAW_SERVER_DATA", "server_data"),
        # "" 포함 미설정·0 = 무제한 — 빈 값이 int()에서 기동 크래시 내지 않게
        limit=(result_limit if result_limit is not None
               else int(os.environ.get("CLAW_RESULT_LIMIT") or 0) or None),
    )
    for router in (
        system_routes.router,
        jobs_routes.router,
        results_routes.router,
        trim_routes.router,
        analysis_routes.router,
        sim_routes.router,
        gains_routes.router,
        codegen_routes.router,
        influence_routes.router,
        verify_routes.router,
        design_routes.router,
        world_routes.router,
    ):
        app.include_router(router, prefix="/api")

    # M14 정적 서빙 — no-build ESM (02 §4: 서버 1대 반입 = 배포 전체).
    # /api 라우트가 먼저 등록되어 우선하며, 마운트는 index.html 존재 시에만.
    wd = Path(
        web_dir
        if web_dir is not None
        else os.environ.get("CLAW_WEB_DIR", _default_web_dir())
    )
    if (wd / "index.html").is_file():
        app.mount("/", NoCacheStaticFiles(directory=wd, html=True), name="web")
    return app
