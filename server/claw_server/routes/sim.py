"""시뮬 실행 라우트 (02 §8 워크플로우 5단계) — 미션 스펙 → 폐루프 시뮬 작업 + 재생.

서버는 JSON 미션 스펙을 엔진 계약(ModeSpec·LosPath·NavErrorModel·Simulator)으로
구성만 한다 — 조건 DSL·모드 테이블·주기비·항법 파라미터 검증은 전부 엔진이
수행하며(구성 시 ValueError/TypeError), 서버는 이를 422로 매핑한다.
엔벨로프 감시(실속 테이블·DB 유효범위)는 항상 장착 [확정 02 §6.1].
결과는 전 해상도로 저장, 재생은 stride 다운샘플 조회.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from claw.fcl import make_demo_fcl
from claw.guidance import Guidance, LosPath, ModeSpec
from claw.nav import NavErrorModel
from claw.plant import make_demo_aircraft, make_demo_db_ranges, make_demo_stall_table
from claw.sim import Simulator
from claw.trim import trim_level
from claw_server.routes.trim import TrimCaseIn, build_cases
from claw_server.serialize import sim_result_dict

router = APIRouter(tags=["sim"])


class ModeIn(BaseModel):
    """비행모드 한 행 — 01 §3.1 선언적 모드 테이블의 JSON 표현."""

    name: str = Field(min_length=1)
    speed: float | None = None  # null = 축 off
    alt: float | None = None
    heading: float | str | None = None  # 숫자 | "path"(LOS) | null
    exit: list = Field(min_length=1)  # 조건 DSL ["kind", 인자...] — 엔진이 검증
    next: str | None = None

    @model_validator(mode="after")
    def _heading_str_only_path(self):
        if isinstance(self.heading, str) and self.heading != "path":
            raise ValueError(f'heading 문자열은 "path"만 허용: {self.heading!r}')
        return self


class SimRunIn(BaseModel):
    aircraft: Literal["demo"] = "demo"
    fingerprint: str = ""
    trim: TrimCaseIn  # 시작 트림점 (웜스타트 기준)
    modes: list[ModeIn] = Field(min_length=1)
    initial_mode: str | None = None
    waypoints: list[tuple[float, float]] | None = None  # (N, E) [m]
    accept_radius: float = Field(default=200.0, gt=0.0)
    t_end: float = Field(gt=0.0, le=3600.0)  # 상한 = 메모리 가드 [기본값]
    dt_plant: float = Field(default=0.01, gt=0.0)
    control_hz: float = Field(default=100.0, gt=0.0)
    nav: dict | None = None  # NavErrorModel kwargs — 파라미터 정의는 엔진이 정본
    actuators: dict | None = None  # SecondOrderActuator kwargs (wn·zeta·rate_max 등)
    fuel_flow: float = Field(default=0.0, ge=0.0)
    with_schedule: bool = True  # 데모 FCL 게인 스케줄 장착 여부
    with_limiter: bool = True  # α 리미터 장착 여부


def _build(req: SimRunIn):
    """미션 스펙 → (Simulator, TrimResult) — 구성 오류는 ValueError/TypeError."""
    ac = make_demo_aircraft()
    tr = trim_level(ac, build_cases([req.trim])[0])
    if not tr.converged:
        raise ValueError(f"시작 트림 미수렴: {req.trim.model_dump()}")
    path = None
    if req.waypoints is not None:
        path = LosPath(
            waypoints=tuple((float(n), float(e)) for n, e in req.waypoints),
            accept_radius=req.accept_radius,
        )
    modes = [
        ModeSpec(
            name=m.name, speed=m.speed, alt=m.alt, heading=m.heading,
            exit_when=tuple(m.exit), next=m.next,
        )
        for m in req.modes
    ]
    guidance = Guidance(modes, path=path, initial=req.initial_mode)
    nav_model = NavErrorModel(**req.nav) if req.nav else None
    sim = Simulator(
        aircraft=ac,
        fcl=make_demo_fcl(with_schedule=req.with_schedule, with_limiter=req.with_limiter),
        guidance=guidance,
        nav_model=nav_model,
        stall_table=make_demo_stall_table(),
        db_ranges=make_demo_db_ranges(),
        dt_plant=req.dt_plant,
        control_hz=req.control_hz,
        actuator_params=req.actuators,
        fuel_flow=req.fuel_flow,
    )
    return sim, tr


@router.post("/sim/run", status_code=202)
def submit_sim_run(req: SimRunIn, request: Request) -> dict:
    try:
        sim, tr = _build(req)
    except (ValueError, TypeError) as e:  # 엔진 구성 검증 → 제출 시점 422
        raise HTTPException(status_code=422, detail=str(e))
    store = request.app.state.store

    def work(job):
        res = sim.run(tr, t_end=req.t_end, fingerprint=req.fingerprint,
                      on_progress=job.report)
        payload = sim_result_dict(res)  # 전 해상도 저장 — 재생이 stride 조회
        payload["kind"] = "sim"
        store.save(
            job.id,
            payload,
            meta={
                "kind": "sim",
                "created": job.created,
                "n": len(res.t),
                "t_end": req.t_end,
                "aborted": res.meta["aborted"],
                "fingerprint": req.fingerprint,
            },
        )
        job.result_id = job.id

    return request.app.state.jobs.submit("sim", work).to_dict()


@router.get("/sim/{result_id}/replay")
def sim_replay(
    result_id: str, request: Request, stride: int = Query(default=1, ge=1)
) -> dict:
    """저장된 시뮬 결과의 stride 다운샘플 뷰 — 재생·플롯용 (요약 스칼라는 원본 유지)."""
    try:
        payload = request.app.state.store.load(result_id)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"결과 없음: {result_id}")
    if payload.get("kind") != "sim":
        raise HTTPException(status_code=409, detail=f"sim 결과가 아님: {result_id}")
    if stride == 1:
        return payload
    sl = slice(None, None, stride)
    out = dict(payload)
    out["t"] = payload["t"][sl]
    out["signals"] = {k: v[sl] for k, v in payload["signals"].items()}
    envelope = dict(payload["envelope"])
    if "stall_margin" in envelope:
        envelope["stall_margin"] = envelope["stall_margin"][sl]
    if "flags" in envelope:
        envelope["flags"] = {k: v[sl] for k, v in envelope["flags"].items()}
    out["envelope"] = envelope
    out["stride"] = stride
    return out
