"""시뮬 실행 라우트 (02 §8 워크플로우 5단계) — 미션 스펙 → 폐루프 시뮬 작업 + 재생.

서버는 JSON 미션 스펙을 엔진 계약(ModeSpec·LosPath·NavErrorModel·Simulator)으로
구성만 한다 — 조건 DSL·모드 테이블·주기비·항법 파라미터 검증은 전부 엔진이
수행하며(구성 시 ValueError/TypeError), 서버는 이를 422로 매핑한다.
엔벨로프 감시(실속 테이블·DB 유효범위)는 항상 장착 [확정 02 §6.1].
결과는 전 해상도로 저장, 재생은 stride 다운샘플 조회.
"""

import math
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from claw.fcl import Autopilot, make_demo_fcl
from claw.guidance import Guidance, LosPath, ModeSpec
from claw.nav import NavErrorModel
from claw.plant import make_demo_aircraft, make_demo_db_ranges, make_demo_stall_table
from claw.sim import Simulator
from claw.tables import Table
from claw.trim import trim_level
from claw_server.routes.trim import FiniteFloat, TrimCaseIn, build_cases
from claw_server.serialize import sim_result_dict

router = APIRouter(tags=["sim"])


class ModeIn(BaseModel):
    """비행모드 한 행 — 01 §3.1 선언적 모드 테이블의 JSON 표현."""

    name: str = Field(min_length=1)
    speed: FiniteFloat | None = None  # null = 축 off
    alt: FiniteFloat | None = None
    heading: FiniteFloat | str | None = None  # 숫자 | "path"(LOS) | null
    exit: list = Field(min_length=1)  # 조건 DSL ["kind", 인자...] — 엔진이 검증
    next: str | None = None

    @model_validator(mode="after")
    def _heading_str_only_path(self):
        if isinstance(self.heading, str) and self.heading != "path":
            raise ValueError(f'heading 문자열은 "path"만 허용: {self.heading!r}')
        return self

    @field_validator("exit")
    @classmethod
    def _exit_args_finite(cls, v):
        """조건 인자 비유한값 차단 — NaN 비교는 항상 False라 영원히 이탈하지
        않는 무증상 모드가 됨 (리뷰 S2)."""
        for item in v:
            if isinstance(item, bool) or not isinstance(item, (str, int, float)):
                raise ValueError(f"조건 인자는 문자열/수치만 허용: {item!r}")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError(f"비유한값 조건 인자: {item}")
        return v


class TableIn(BaseModel):
    """Table JSON 규격 (serialize.table_dict와 왕복) — 형상·축 검증은 엔진 Table."""

    axes: dict[str, list[FiniteFloat]] = Field(min_length=1)
    data: list = Field(min_length=1)  # 중첩 리스트 허용 — 형상은 엔진이 검증
    extrapolate: str = "clip"

    @field_validator("data")
    @classmethod
    def _numeric_finite_data(cls, v):
        def walk(x):
            if isinstance(x, list):
                for item in x:
                    walk(item)
            elif isinstance(x, bool) or not isinstance(x, (int, float)):
                raise ValueError(f"게인 테이블 데이터는 수치만 허용: {x!r}")
            elif isinstance(x, float) and not math.isfinite(x):
                raise ValueError(f"비유한값 게인: {x}")

        walk(v)
        return v


class SimRunIn(BaseModel):
    aircraft: Literal["demo"] = "demo"
    fingerprint: str = ""
    trim: TrimCaseIn  # 시작 트림점 (웜스타트 기준)
    modes: list[ModeIn] = Field(min_length=1)
    initial_mode: str | None = None
    waypoints: list[tuple[FiniteFloat, FiniteFloat]] | None = Field(
        default=None, min_length=1
    )  # (N, E) [m] — 빈 리스트는 무의미 구성이라 거부
    accept_radius: float = Field(default=200.0, gt=0.0, allow_inf_nan=False)
    t_end: float = Field(gt=0.0, le=3600.0)  # 상한 = 메모리 가드 [기본값]
    dt_plant: float = Field(default=0.01, gt=0.0, allow_inf_nan=False)
    control_hz: float = Field(default=100.0, gt=0.0, allow_inf_nan=False)
    nav: dict | None = None  # NavErrorModel kwargs — 파라미터 정의는 엔진이 정본
    actuators: dict | None = None  # SecondOrderActuator kwargs (wn·zeta·rate_max 등)
    fuel_flow: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    with_schedule: bool = True  # 데모 FCL 게인 스케줄 장착 여부
    with_limiter: bool = True  # α 리미터 장착 여부
    autopilot: dict | None = None  # Autopilot kwargs — 게인 이름은 엔진이 정본
    gain_tables: dict[str, TableIn] | None = None  # "그룹.게인" → 편집 테이블 (4단계)

    @field_validator("nav", "actuators", "autopilot")
    @classmethod
    def _finite_numeric_values(cls, v):
        """kwargs 통과 dict의 값 타입·유한성 검사 — 비수치·bool·NaN이 실행
        시점 TypeError로 새는 것 방지 (리뷰 S1; 키 검증은 엔진 소관)."""
        if v is not None:
            for key, val in v.items():
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise ValueError(f"파라미터 값은 수치만 허용: {key}={val!r}")
                if isinstance(val, float) and not math.isfinite(val):
                    raise ValueError(f"비유한값 파라미터: {key}={val}")
        return v

    @field_validator("gain_tables")
    @classmethod
    def _tables_not_empty(cls, v):
        # 빈 dict는 "스케줄 없음"과 동치가 되어버림 — 편집 없음이면 필드 생략 (리뷰 S2)
        if v is not None and not v:
            raise ValueError("gain_tables가 빈 dict — 편집 없음이면 필드를 생략하세요")
        return v


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
    # 빈 dict = 기본 파라미터 오차 모델 장착 (조용한 미장착 금지 — None만 이상 항법)
    nav_model = NavErrorModel(**req.nav) if req.nav is not None else None
    gain_tables = None
    if req.gain_tables is not None:
        gain_tables = {
            name: Table(spec.axes, spec.data, name=name, extrapolate=spec.extrapolate)
            for name, spec in req.gain_tables.items()
        }
    fcl = make_demo_fcl(
        with_schedule=req.with_schedule,
        with_limiter=req.with_limiter,
        autopilot=Autopilot(**req.autopilot) if req.autopilot else None,
        gain_tables=gain_tables,
    )
    sim = Simulator(
        aircraft=ac,
        fcl=fcl,
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
def submit_sim_run(req: SimRunIn, request: Request, response: Response) -> dict:
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

    job = request.app.state.jobs.submit("sim", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


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
