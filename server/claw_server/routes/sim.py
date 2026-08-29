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

from claw.analysis.duty import duty_report
from claw.fcl import Scas, make_demo_fcl
from claw.guidance import Guidance, LosPath, ModeSpec
from claw.nav import NavErrorModel
from claw.params.registry import REGISTRY
from claw.pipeline.influence import SCAS_AXES
from claw.plant import make_demo_aircraft, make_demo_db_ranges, make_demo_stall_table
from claw.sim import Simulator
from claw.tables import PolyTable, Table
from claw.trim import trim_level
from claw_server.routes.trim import FiniteFloat, TrimCaseIn, build_cases
from claw_server.serialize import sim_result_dict, to_jsonable

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


class PolySegmentIn(BaseModel):
    """구간별 다항 한 구간 — tables/poly.py PolyTable 규격 (u-영역 오름차수 계수)."""

    x0: FiniteFloat
    x1: FiniteFloat
    coeffs: list[FiniteFloat] = Field(min_length=1, max_length=8)
    c: FiniteFloat
    h: FiniteFloat
    degree: int | None = None  # 생략 시 len(coeffs)-1 — 명시하면 엔진이 일치 검증


class PolyTableIn(BaseModel):
    """다항 게인 스케줄 JSON 규격 (01 §3.4 다항 런타임) — 구간 검증은 엔진 PolyTable.

    kind='poly' 태그로 TableIn과 구분한다 — 기존 테이블 페이로드(kind 없음)는
    TableIn이 먼저 맞아 무변경 호환이다.
    """

    kind: Literal["poly"]
    axis: str = Field(min_length=1)
    segments: list[PolySegmentIn] = Field(min_length=1)


def build_gain_tables(spec: dict | None) -> dict | None:
    """요청 게인 페이로드 → {이름: Table|PolyTable} — sim·codegen 공용 조립.

    구간 인접성·차수 일치 등은 엔진(TableError ⊂ ValueError → 422)이 검증한다.
    """
    if spec is None:
        return None
    out = {}
    for name, item in spec.items():
        if isinstance(item, PolyTableIn):
            out[name] = PolyTable(
                item.axis,
                [s.model_dump(exclude_none=True) for s in item.segments],
                name=name,
            )
        else:
            out[name] = Table(item.axes, item.data, name=name,
                              extrapolate=item.extrapolate)
    return out


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
    scas: dict | None = None  # {'pitch': ScasAxis kwargs, 'roll': …, 'yaw': …} — 세 축 전부
    # "그룹.게인" → 편집 테이블 또는 다항 스케줄 (kind='poly' 태그, 4단계)
    gain_tables: dict[str, TableIn | PolyTableIn] | None = None

    @field_validator("nav", "actuators")
    @classmethod
    def _finite_numeric_values(cls, v):
        """kwargs 통과 dict의 값 타입·유한성 검사 — 비수치·bool·NaN이 실행
        시점 TypeError로 새는 것 방지 (리뷰 S1; 키 검증은 엔진 소관).
        nav·actuators는 엔진 생성자/프로브 직결이라 수치 한정이 계약 —
        editable 확장 시 autopilot처럼 레지스트리 ParamDef 판정으로 승격할 것."""
        if v is not None:
            for key, val in v.items():
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise ValueError(f"파라미터 값은 수치만 허용: {key}={val!r}")
                if isinstance(val, float) and not math.isfinite(val):
                    raise ValueError(f"비유한값 파라미터: {key}={val}")
        return v

    @field_validator("autopilot")
    @classmethod
    def _finite_leaves_only(cls, v):
        """AP는 타입·범위·키를 레지스트리 ParamDef가 판정(_build의 REGISTRY.create)
        — bool·enum 파라미터 컴포넌트도 수용 가능. 서버는 경계 유한성만: NaN은
        ParamDef 범위 비교(v<lo 등)를 조용히 통과하므로 여기서 차단해야 저장
        시점 직렬화(allow_nan=False) 전멸을 막는다 (02 v0.11 정책)."""
        if v is not None:
            for key, val in v.items():
                leaves = val if isinstance(val, (list, tuple)) else (val,)
                for x in leaves:
                    if isinstance(x, float) and not math.isfinite(x):
                        raise ValueError(f"비유한값 파라미터: {key}={val!r}")
        return v

    @field_validator("scas")
    @classmethod
    def _axes_finite_leaves(cls, v):
        """SCAS는 축 dict가 한 겹 더 있다 — 축별 kwargs의 유한성만 본다.

        타입·범위·미정의 키 판정은 autopilot과 같이 레지스트리 ParamDef 몫
        (`build_scas`의 REGISTRY.create). 축 이름·누락 검사도 거기서 한다 —
        조립 시점에 한 곳에서 걸려야 시뮬·탑재 C가 같은 사유로 422가 된다."""
        if v is not None:
            for axis, kwargs in v.items():
                if not isinstance(kwargs, dict):
                    raise ValueError(f"scas.{axis}는 파라미터 dict여야 함: {kwargs!r}")
                for key, val in kwargs.items():
                    if isinstance(val, float) and not math.isfinite(val):
                        raise ValueError(f"비유한값 파라미터: scas.{axis}.{key}={val}")
        return v

    @field_validator("gain_tables")
    @classmethod
    def _tables_not_empty(cls, v):
        # 빈 dict는 "스케줄 없음"과 동치가 되어버림 — 편집 없음이면 필드 생략 (리뷰 S2)
        if v is not None and not v:
            raise ValueError("gain_tables가 빈 dict — 편집 없음이면 필드를 생략하세요")
        return v


def build_scas(spec: dict | None):
    """{'pitch': kwargs, 'roll': …, 'yaw': …} → Scas — None이면 설계 기본값.

    **부분 주입은 막는다.** 한 축만 보내면 나머지 축이 조용히 데모 설계값으로 남아
    "내가 보낸 형상"과 다른 것이 돌아간다 (make_demo_fcl의 gain_tables 전체 교체
    계약과 같은 이유). 축별 kwargs 판정은 레지스트리 ParamDef가 한다 —
    미정의 키·타입·범위는 ParamError ⊂ ValueError → 422.

    시뮬·탑재 C 두 라우트가 이 함수 하나를 쓴다: 조립 규칙이 두 곳에 적히면
    같은 형상이 라우트마다 다르게 서는 순간이 온다 (02 §5.5).

    **영향성(`/influence/*`)과는 계약이 다르다.** 거기는 파라미터를 흔드는 자리라
    설계 기본 위 덮어쓰기이고(`pipeline/influence.py` _SCAS_BASE 병합), 같은
    `{"pitch": {"kp": …}}`가 통과한다. 여기는 "보낸 것이 곧 형상"이라 부분을 거부한다
    — 웹이 축 하나를 빠뜨렸을 때 나머지가 조용히 설계값으로 남는 것과, 요청이
    거부되는 것 중 후자가 낫다는 판단이다. 축 **안쪽** kwargs는 이 판단이 닿지
    않는다 (ParamDef 기본값이 채운다) — 그래서 웹이 축 kwargs 전량을 보낸다
    (/gains/catalog scas_design).
    """
    if spec is None:
        return None
    extra = sorted(set(spec) - set(SCAS_AXES))
    if extra:
        raise ValueError(f"미정의 SCAS 축 {extra} — 허용: {list(SCAS_AXES)}")
    missing = [a for a in SCAS_AXES if a not in spec]
    if missing:
        raise ValueError(f"scas는 세 축 전부 필요 — 누락: {missing} (부분 주입 금지)")
    return Scas(*(REGISTRY.create("fcl", "ScasAxis", spec[a]) for a in SCAS_AXES))


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
    gain_tables = build_gain_tables(req.gain_tables)
    fcl = make_demo_fcl(
        with_schedule=req.with_schedule,
        with_limiter=req.with_limiter,
        # 레지스트리 경유 = ParamDef 판정(미정의 키·타입·범위·choices → ParamError
        # ⊂ ValueError → 422). 부분 지정은 ParamDef 기본값 보충 — 생성자 기본값과
        # 동일함은 엔진 defaults-match 테스트가 보증
        autopilot=REGISTRY.create("fcl", "Autopilot", req.autopilot) if req.autopilot else None,
        scas=build_scas(req.scas),
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
        # 웨이포인트 동봉 — 경로오차 지표(pipeline.metrics xtrack_rms)·진단이
        # 저장된 결과만으로 계산되도록 (meta["limits"]·["clamps"]와 같은
        # "기준선은 결과와 함께 다닌다" 규약). 없으면 None — 경로 없는 미션이다
        payload["meta"]["waypoints"] = (
            None if req.waypoints is None
            else [[float(n), float(e)] for n, e in req.waypoints]
        )
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


def _load_sim(request: Request, result_id: str) -> dict:
    """저장된 sim 결과 본문 — 없으면 404, 다른 종류면 409 (조회 경로 공통 규약)."""
    try:
        payload = request.app.state.store.load(result_id)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"결과 없음: {result_id}")
    if payload.get("kind") != "sim":
        raise HTTPException(status_code=409, detail=f"sim 결과가 아님: {result_id}")
    return payload


@router.get("/sim/{result_id}/replay")
def sim_replay(
    result_id: str, request: Request, stride: int = Query(default=1, ge=1)
) -> dict:
    """저장된 시뮬 결과의 stride 다운샘플 뷰 — 재생·플롯용 (요약 스칼라는 원본 유지)."""
    payload = _load_sim(request, result_id)
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


@router.get("/sim/{result_id}/duty")
def sim_duty(
    result_id: str,
    request: Request,
    bins: int = Query(default=32, ge=4, le=256),
    rate_bins: int = Query(default=24, ge=4, le=128),
) -> dict:
    """타면 사용 통계 — 타각 범위별 체류 시간·포화·타율 (엔진 analysis.duty).

    **stride를 받지 않는다.** 다운샘플본으로 집계하면 최대 타율과 짧은 포화
    구간이 통째로 사라져 조용히 낙관적인 수치가 나온다 — 재생(/replay)과 달리
    여기서는 저장된 전 해상도가 유일하게 옳은 입력이다. 그래서 원본을 쥔 서버가
    집계까지 끝내 웹에 요약만 보낸다 (표본 수와 무관하게 응답 크기 유계).
    """
    payload = _load_sim(request, result_id)
    report = duty_report(
        payload["t"], payload["signals"], payload.get("meta") or {},
        bins=bins, rate_bins=rate_bins,
    )
    report["result_id"] = result_id
    return to_jsonable(report)
