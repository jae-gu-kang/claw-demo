"""영향성 라우트 (02 §2.4, M15) — 파라미터 하나가 전체 시스템에 미치는 영향.

**도메인 로직은 없다.** 그래프 diff·도달성·섭동 판정은 전부 엔진
`claw.pipeline.influence`가 하고, 여기서는 요청 형상을 엔진 `Shape`로 옮기고
결과를 회신할 뿐이다 (02 §2.3 — 서버는 엔진 API 소비자).

요청 모델은 `codegen.py`의 `FlightCodeIn`을 **상속**한다. 같은 "현재 편집 형상"을
받는 자리라 필드와 유한성 검증을 다시 적으면 두 곳이 갈라진다 (02 §5.5). codegen이
sim에서 `TableIn`을 가져다 쓰는 것과 같은 선례다.
"""

import math
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, field_validator

from claw.pipeline.diagnose import diagnose_grid, diagnose_run
from claw.pipeline.influence import Shape, param_universe, structural_payload
from claw.pipeline.openloop import openloop_delta
from claw.pipeline.sweep import nonadditivity, run_sweep, sweep_plan
from claw.plant import make_demo_aircraft
from claw.tables import Table
from claw.trim import trim_batch
from claw_server.routes.codegen import FlightCodeIn
from claw_server.routes.sim import _load_sim
from claw_server.routes.trim import TrimCaseIn, build_cases
from claw_server.serialize import to_jsonable

router = APIRouter(tags=["influence"])

# 케이스 격자 상한 — 2·3단은 케이스마다 트림·시뮬 비용이 붙는 잡이라, 오타 격자
# (예: 간격 0.001) 하나가 단일 워커를 시간 단위로 점유하는 것을 제출 시점에 막는다
MAX_CASES = 200


class InfluenceIn(FlightCodeIn):
    """형상(FlightCodeIn) + 법칙 밖 컴포넌트 + 탐침 설정.

    `mixer`·`alpha_margin`은 `FlightCodeIn`에 없다 — 탑재 C 생성은 조립된 형상만
    있으면 되지만, 영향성은 **그 형상을 흔들어야** 하기 때문이다.

    `scas`는 이제 부모(`FlightCodeIn`)에도 있지만 **계약이 다르다.** 여기는
    설계 기본 위 덮어쓰기라 `{"pitch": {"kp": …}}` 같은 부분 지정이 통과하고
    (`pipeline/influence.py` _SCAS_BASE 병합 — 파라미터를 흔드는 자리의 자연스러운
    의미다), 시뮬·탑재 C는 "보낸 것이 곧 형상"이라 세 축 전부를 요구한다
    (`routes/sim.py` build_scas). 그래서 여기서 필드를 다시 선언해 부모의 유한성
    검사만 물려받고 조립은 엔진 Shape 경로로 보낸다.
    """

    scas: dict | None = None  # {'pitch': {'kp': …}, …}
    mixer: dict | None = None
    alpha_margin: float | None = None
    nav: dict | None = None
    actuators: dict | None = None
    guidance: dict | None = None
    include_offgraph: bool = True
    probe_rel: float = Field(0.01, gt=0.0, le=0.5)

    @field_validator("scas", "mixer", "nav", "actuators", "guidance")
    @classmethod
    def _finite_leaves_only(cls, v):
        """타입·범위 판정은 엔진 ParamDef 몫 — 서버는 경계 유한성만 (sim·codegen과 동일).

        NaN은 ParamDef의 범위 비교(`v < lo`)를 조용히 통과하므로 여기서 막는다.
        """
        if v is not None:
            for key, val in v.items():
                leaves = val.values() if isinstance(val, dict) else (
                    val if isinstance(val, (list, tuple)) else (val,)
                )
                for x in leaves:
                    if isinstance(x, float) and not math.isfinite(x):
                        raise ValueError(f"비유한값 파라미터: {key}={val!r}")
        return v

    @field_validator("alpha_margin")
    @classmethod
    def _finite_margin(cls, v):
        if v is not None and not math.isfinite(v):
            raise ValueError("비유한값 alpha_margin")
        return v


def to_shape(req: InfluenceIn) -> Shape:
    """요청 → 엔진 형상. 지정하지 않은 자리는 비워 두어 **엔진 기본값이 채우게** 한다."""
    gain_tables = None
    if req.gain_tables is not None:
        gain_tables = {
            name: Table(spec.axes, spec.data, name=name, extrapolate=spec.extrapolate)
            for name, spec in req.gain_tables.items()
        }
    return Shape(
        control_hz=req.control_hz,
        with_schedule=req.with_schedule,
        with_limiter=req.with_limiter,
        autopilot=dict(req.autopilot or {}),
        scas={k: dict(v) for k, v in (req.scas or {}).items()},
        mixer=dict(req.mixer or {}),
        alpha_margin=req.alpha_margin,
        gain_tables=gain_tables,
        nav=dict(req.nav or {}),
        actuators=dict(req.actuators or {}),
        guidance=dict(req.guidance or {}),
    )


@router.post("/influence/structural")
def influence_structural(req: InfluenceIn) -> dict:
    """1단 — 구조 + 도달성. 파라미터 65개를 각각 재조립해 diff하고도 100 ms 안쪽이라 동기다.

    구성 오류(범위 이탈·스케줄 불가 자리 등)는 엔진이 ValueError로 내고 422가 된다.
    """
    t0 = time.perf_counter()
    try:
        payload = structural_payload(
            to_shape(req),
            include_offgraph=req.include_offgraph,
            probe_rel=req.probe_rel,
        )
    except (ValueError, TypeError) as e:  # 엔진 판정 → 422 (sim·codegen과 같은 정책)
        raise HTTPException(status_code=422, detail=str(e))
    payload["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return payload


class DiagnoseIn(InfluenceIn):
    """진단 요청 — 형상(InfluenceIn) + 저장된 sim 결과 id."""

    result_id: str = Field(min_length=1)


@router.post("/influence/diagnose")
def influence_diagnose(req: DiagnoseIn, request: Request) -> dict:
    """진단 — 저장된 폐루프 런에서 "어떤 손잡이를 만질 것인가"의 처방 카드.

    duty와 같은 이유로 동기·서버 계산이다: 전 해상도 원본을 쥔 쪽이 집계해야
    짧은 포화·주차 구간이 다운샘플에 지워지지 않는다. 형상은 요청이 들고 온다
    (처방 승격 — 스케줄이 덮는 자리 판정 — 의 기준). 결과 지문과 형상 지문이
    다르면 **오류가 아니라 경고**다: 진단은 내되 계보가 다름을 화면이 알아야 한다.
    """
    t0 = time.perf_counter()
    payload = _load_sim(request, req.result_id)
    try:
        out = diagnose_run(payload, to_shape(req), probe_rel=req.probe_rel)
    except (ValueError, TypeError) as e:  # 엔진 판정 → 422 (structural과 같은 정책)
        raise HTTPException(status_code=422, detail=str(e))
    fp = payload.get("params_fingerprint") or ""
    if fp and fp != out["fingerprint"]:
        out["warnings"].append(
            f"계보 불일치: 결과 지문 {fp} ≠ 형상 지문 {out['fingerprint']} — "
            "처방 승격 판정이 실제 런 형상과 다를 수 있다"
        )
    out["result_id"] = req.result_id
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return to_jsonable(out)


class OpenloopIn(InfluenceIn):
    """2단 요청 — 형상 + 케이스 격자 + 볼 파라미터 (None = 루프 선언이 있는 전 자리)."""

    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1, max_length=MAX_CASES)
    params: list[str] | None = None


@router.post("/influence/openloop", status_code=202)
def submit_openloop(req: OpenloopIn, request: Request, response: Response) -> dict:
    """2단 — 케이스별 트림→선형화 후 게인 섭동의 개루프 마진 Δ (잡 기반 202).

    진행률은 margin-map과 같은 2n 패턴(트림 패스 + 해석 패스), 취소 시 완료
    케이스 보존. 파라미터 id 오타는 실행이 아니라 **제출 시점 422**로 잡는다 —
    잡이 돌고 나서 실패하면 오타 하나에 트림 배치 비용을 지불한다.
    """
    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    try:
        shape = to_shape(req)
        if req.params:
            universe = {r.id for r in param_universe(shape)}
            unknown = [p for p in req.params if p not in universe]
            if unknown:
                raise ValueError(f"알 수 없는 파라미터 id: {unknown}")
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    store = request.app.state.store
    n = len(cases)
    total = 2 * n

    def work(job):
        trs = trim_batch(
            ac, cases, fingerprint=req.fingerprint,
            on_progress=lambda done, _t, tr: job.report(
                done, total, message=f"트림: {tr.case.name}"
            ),
        )
        out = openloop_delta(
            ac, trs, shape, req.params, probe_rel=req.probe_rel,
            on_progress=lambda done, _t: job.report(
                n + done, total, message=f"개루프: {done}/{n}"
            ),
        )
        payload = to_jsonable(out)
        payload["kind"] = "influence_openloop"
        store.save(
            job.id, payload,
            meta={"kind": "influence_openloop", "created": job.created,
                  "n": len(out["cases"]), "fingerprint": req.fingerprint},
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("influence_openloop", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


class SweepIn(InfluenceIn):
    """3단 요청 — 형상 + 케이스 + 처방 손잡이(knobs)·동시 수정 쌍(pairs).

    knobs·pairs는 진단 응답의 처방 카드에서 그대로 온다 — 전 게인 공간이 아니라
    처방 부분공간만 흔드는 것이 3단의 비용 구조다.
    """

    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1, max_length=MAX_CASES)
    knobs: list[str] = []
    pairs: list[tuple[str, str]] = []
    span: list[float] | None = None
    t_settle: float = Field(default=5.0, gt=0.0, allow_inf_nan=False)
    t_step: float = Field(default=30.0, gt=0.0, allow_inf_nan=False)
    dt_plant: float = Field(default=0.01, gt=0.0, allow_inf_nan=False)

    @field_validator("span")
    @classmethod
    def _finite_nonzero_span(cls, v):
        if v is not None:
            if not v:
                raise ValueError("span이 비었음 — 기본 스팬이면 필드를 생략하세요")
            for s in v:
                if not math.isfinite(s) or s == 0.0:
                    raise ValueError(f"span은 0 아닌 유한값만 허용: {s}")
        return v


@router.post("/influence/sweep", status_code=202)
def submit_sweep(req: SweepIn, request: Request, response: Response) -> dict:
    """3단 — 처방 부분공간 폐루프 스윕 (잡 기반 202, 런 단위 진행률).

    행마다 지표 Δ(대 base), 쌍마다 비가산성 dAB−(dA+dB)을 실어 저장한다.
    knob 오타·무의미 구성은 제출 시점 422. 취소 시 완료 런 보존.
    """
    if not req.knobs and not req.pairs:
        raise HTTPException(status_code=422,
                            detail="흔들 것이 없다 — knobs 또는 pairs가 필요")
    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    try:
        shape = to_shape(req)
        plan = (
            sweep_plan(shape, req.knobs, [tuple(p) for p in req.pairs],
                       span=tuple(req.span))
            if req.span is not None
            else sweep_plan(shape, req.knobs, [tuple(p) for p in req.pairs])
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    store = request.app.state.store
    n = len(cases)
    n_runs = len(plan["runs"])
    total = n + n * n_runs

    def work(job):
        trs = trim_batch(
            ac, cases, fingerprint=req.fingerprint,
            on_progress=lambda done, _t, tr: job.report(
                done, total, message=f"트림: {tr.case.name}"
            ),
        )
        out = run_sweep(
            ac, trs, shape, plan,
            dt_plant=req.dt_plant, t_settle=req.t_settle, t_step=req.t_step,
            on_progress=lambda done, run_total: job.report(
                n + done, n + run_total, message=f"스윕: {done}/{run_total}"
            ),
        )
        # Δ(대 base)·쌍별 비가산성 — 저장된 결과만으로 화면이 표를 그리도록 동봉
        by_key = {(r["case"], r["label"]): r["metrics"] for r in out["rows"]}
        for r in out["rows"]:
            base = by_key.get((r["case"], "base"))
            if r["label"] == "base" or base is None:
                r["delta"] = None
                continue
            r["delta"] = {
                k: (None if base.get(k) is None or v is None else v - base[k])
                for k, v in r["metrics"].items()
            }
        nonadd = []
        for case_name in dict.fromkeys(r["case"] for r in out["rows"]):
            m0 = by_key.get((case_name, "base"))
            if m0 is None:
                continue
            for pair in out["pairs"]:
                ma = by_key.get((case_name, pair["a"]))
                mb = by_key.get((case_name, pair["b"]))
                mab = by_key.get((case_name, pair["ab"]))
                if ma is None or mb is None or mab is None:
                    continue  # 취소로 잘린 쌍 — 판정 불가는 내지 않는다
                nonadd.append({"case": case_name, "knobs": pair["knobs"],
                               "values": nonadditivity(m0, ma, mb, mab)})
        payload = to_jsonable(out)
        payload["kind"] = "influence_sweep"
        payload["nonadditivity"] = to_jsonable(nonadd)
        store.save(
            job.id, payload,
            meta={"kind": "influence_sweep", "created": job.created,
                  "n": len(out["rows"]), "fingerprint": req.fingerprint},
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("influence_sweep", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


class ScanIn(InfluenceIn):
    """3단 A 요청 — 형상 + 케이스 격자만. knobs·pairs가 없는 것이 정의다:

    케이스마다 base 런 하나로 현 형상의 지표를 재고, diagnose_grid(규칙 4)가
    결함의 국소성(스케줄 vs 게인 수준)을 판정한다 — 풀 스윕은 여기서 좁혀진
    케이스에만 간다 (케이스 × 런 비용은 곱이므로).
    """

    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1, max_length=MAX_CASES)
    t_settle: float = Field(default=5.0, gt=0.0, allow_inf_nan=False)
    t_step: float = Field(default=30.0, gt=0.0, allow_inf_nan=False)
    dt_plant: float = Field(default=0.01, gt=0.0, allow_inf_nan=False)


@router.post("/influence/scan", status_code=202)
def submit_scan(req: ScanIn, request: Request, response: Response) -> dict:
    """3단 A — 전 케이스 base 스캔 + 국소성 판정 (잡 기반 202).

    sweep_plan(shape, [], ())은 base 런 1개짜리 계획이라 run_sweep을 그대로
    재사용한다 — sweep.py 머리말의 "기준런이 diagnose_grid의 입력" 계약의
    소급 활성화다. 취소 시 완료 케이스의 행은 보존되고, 판정은 남은 케이스로만
    낸다 (n_cases가 계보다).
    """
    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    try:
        shape = to_shape(req)
        plan = sweep_plan(shape, [], ())
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    store = request.app.state.store
    n = len(cases)
    total = n + n  # 트림 패스 + 케이스당 base 런 1개

    def work(job):
        trs = trim_batch(
            ac, cases, fingerprint=req.fingerprint,
            on_progress=lambda done, _t, tr: job.report(
                done, total, message=f"트림: {tr.case.name}"
            ),
        )
        out = run_sweep(
            ac, trs, shape, plan,
            dt_plant=req.dt_plant, t_settle=req.t_settle, t_step=req.t_step,
            on_progress=lambda done, run_total: job.report(
                n + done, n + run_total, message=f"스캔: {done}/{run_total}"
            ),
        )
        # 잘린 런을 판정에서 뺄지는 엔진 판단이다 — 행을 그대로 넘긴다
        per_case = [{"case": r["case"], "metrics": r["metrics"],
                     "aborted": r["aborted"]}
                    for r in out["rows"]]
        n_aborted = sum(1 for r in out["rows"] if r["aborted"])
        if n_aborted:
            out["warnings"].append(
                f"발산으로 잘린 케이스 {n_aborted}건 — 국소성 판정에서 제외")
        payload = to_jsonable(out)
        payload["kind"] = "influence_scan"
        payload["grid"] = to_jsonable(diagnose_grid(per_case))
        store.save(
            job.id, payload,
            meta={"kind": "influence_scan", "created": job.created,
                  "n": len(out["rows"]), "fingerprint": req.fingerprint},
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("influence_scan", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()
