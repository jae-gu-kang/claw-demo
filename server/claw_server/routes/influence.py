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
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, field_validator

from claw.analysis.schedule import mach_midpoints
from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.diagnose import diagnose_grid, diagnose_run
from claw.pipeline.evaluate import (
    CARD_META, CARDS, CHECK_META, CHECKS, ITEMS, STAGE_ORDER, VERIFY_META,
    evaluate, verify,
)
from claw.pipeline.influence import Shape, make_law, param_universe, structural_payload
from claw.pipeline.openloop import openloop_delta
from claw.pipeline.prescribe import (
    _targets as prescribe_targets,
    nonadditivity_warnings,
    proposal_export,
    proposal_shape,
    solve_joint,
    solve_single_knob,
)
from claw.pipeline.sweep import nonadditivity, plan_shapes, run_sweep, sweep_plan
from claw.sim import check_law_plant_pairing
from claw.plant import make_demo_aircraft
from claw.trim import trim_batch
from claw_server.routes.codegen import FlightCodeIn
from claw_server.routes.sim import _load_sim, build_gain_tables
from claw_server.routes.trim import TrimCaseIn, build_cases
from claw_server.serialize import to_jsonable

router = APIRouter(tags=["influence"])

# 케이스 격자 상한 — 2·3단은 케이스마다 트림·시뮬 비용이 붙는 잡이라, 오타 격자
# (예: 간격 0.001) 하나가 단일 워커를 시간 단위로 점유하는 것을 제출 시점에 막는다
MAX_CASES = 200

# 하드 게이트 검사 이름 → 그 검사가 말하는 스윕 지표. 처방 승계가 "무엇을 풀지"를
# 정하는 표다 — 마진·ζ류는 선형 단계의 판정이라 스윕 지표로 대응이 없다(빈 튜플).
_HARD_CHECK_METRICS = {
    "envelope.stall_margin": ("worst_stall_margin",),
    "actuator.sat_frac": ("surf_sat_frac",),
    "coupling.stall_margin": ("worst_stall_margin",),
    "coupling.sat_frac": ("surf_sat_frac",),
}


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
    # 조립은 sim·codegen과 같은 빌더 하나로 — 여기만 손으로 짜 두면 게인 페이로드가
    # 넓어질 때(다항 kind='poly') 이 경로만 빠져 AttributeError → 500이 된다
    gain_tables = build_gain_tables(req.gain_tables)
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
    criteria: dict | None = None


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
        criteria = GainEvalCriteria.from_dict(req.criteria)
        out = diagnose_run(payload, to_shape(req), probe_rel=req.probe_rel,
                           thresholds=criteria.to_diagnose_thresholds())
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
        # 잡 안에서 터지면 이미 돌린 런이 통째로 버려진다 — 기체와 안 맞는 형상은
        # 202를 주기 전에 여기서 걸러 위 except가 422로 바꾼다 (독스트링의 계약)
        for s in plan_shapes(shape, plan).values():
            check_law_plant_pairing(ac, make_law(s))
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
    criteria: dict | None = None
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
        criteria = GainEvalCriteria.from_dict(req.criteria)
        plan = sweep_plan(shape, [], ())
        # 잡 안에서 터지면 이미 돌린 런이 통째로 버려진다 — 기체와 안 맞는 형상은
        # 202를 주기 전에 여기서 걸러 위 except가 422로 바꾼다 (독스트링의 계약)
        for s in plan_shapes(shape, plan).values():
            check_law_plant_pairing(ac, make_law(s))
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
        # 문턱은 평가 기준 정본에서 — 진단·평가·스캔이 각자 상수를 들면 같은 런이
        # 화면마다 다른 판정을 받는다 (02 §5.5)
        payload["grid"] = to_jsonable(diagnose_grid(
            per_case, thresholds=criteria.to_grid_thresholds(),
            local_frac=criteria.schedule.local_frac))
        store.save(
            job.id, payload,
            meta={"kind": "influence_scan", "created": job.created,
                  "n": len(out["rows"]), "fingerprint": req.fingerprint},
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("influence_scan", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


@router.get("/influence/criteria/defaults")
def criteria_defaults() -> dict:
    """평가기준 기본값 + A/B/C 어휘 — 웹이 이 값을 받아 그린다 (재기술 금지, 02 §5.5).

    `/design/defaults`와 분리한 이유: 소비자가 다르고(오토디자인 vs A/B/C 평가),
    그쪽 config에 얹으면 AutoDesignConfig.__post_init__의 목표-기준 정합 검사에
    또 얽힌다. 마진 판정선 자체는 둘 다 MarginCriteria 한 정의를 쓴다.

    cards/checks/verify가 화면 어휘의 정본이다 — 웹이 카드 이름·순서를 하드코딩하면
    엔진 재편 날 화면이 옛 순서를 말한다. items는 원자료(케이스 × 항목 격자)의 라벨.
    """
    c = GainEvalCriteria()
    return {
        "criteria": c.to_dict(),
        "fingerprint": c.fingerprint(),
        "cards": [{"key": k, "card": CARD_META[k][0], "label": CARD_META[k][1]}
                  for k in CARDS],
        "checks": [{"key": k, "label": CHECK_META[k]} for k in CHECKS],
        "verify": [{"key": k, "label": v} for k, v in VERIFY_META.items()],
        "items": [{"key": k, "item": ITEMS[k][0], "label": ITEMS[k][1]}
                  for k in STAGE_ORDER],
    }


class EvaluateIn(InfluenceIn):
    """A/B급 평가 요청 — 형상 + 케이스 격자 + 기준(없으면 기본값) + 깊이.

    depth="linear"는 트림+선형화만(시뮬 0 — 전 게인 후보에 돌리는 단계 1),
    "full"은 표준 기동 런 + 동시명령 런 포함(단계 2). B급 교차축이 필수라 full에서
    동시명령은 상시다. C급(강건성 코너·격자 중간점 등)은 `/influence/verify`가
    따로 받는다 — 요청 형상이 다르고, 사용자 확정 실행 단계 분리가 그 경계다.
    """

    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1, max_length=MAX_CASES)
    criteria: dict | None = None
    depth: Literal["linear", "full"] = "full"
    t_settle: float = Field(default=5.0, gt=0.0, allow_inf_nan=False)
    t_step: float = Field(default=30.0, gt=0.0, allow_inf_nan=False)
    t_hold: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    dt_plant: float = Field(default=0.01, gt=0.0, allow_inf_nan=False)


@router.post("/influence/evaluate", status_code=202)
def submit_evaluate(req: EvaluateIn, request: Request, response: Response) -> dict:
    """A급 카드 7 + B급 체크 9 + 원자료 — 잡 기반 202.

    케이스당 비용: 트림 + (depth=full일 때) 표준 기동 런·동시명령 런 + 선형화·마진.
    기준 오류·기체와 안 맞는 형상은 제출 시점 422 (sweep과 같은 계약). 결과에
    형상·기준 지문이 함께 실린다 — 무슨 기준으로 판정했는지가 계보다.
    """
    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    try:
        shape = to_shape(req)
        criteria = GainEvalCriteria.from_dict(req.criteria)
        check_law_plant_pairing(ac, make_law(shape))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    store = request.app.state.store
    n = len(cases)
    per_case = 1 if req.depth == "linear" else 3
    total = n + n * per_case

    def work(job):
        trs = trim_batch(
            ac, cases, fingerprint=req.fingerprint,
            on_progress=lambda done, _t, tr: job.report(
                done, total, message=f"트림: {tr.case.name}"
            ),
        )
        out = evaluate(
            ac, trs, shape, criteria,
            depth=req.depth, dt_plant=req.dt_plant,
            t_settle=req.t_settle, t_step=req.t_step, t_hold=req.t_hold,
            on_progress=lambda done, ev_total, msg: job.report(
                n + done, n + ev_total, message=msg
            ),
        )
        payload = to_jsonable(out)
        payload["kind"] = "influence_evaluate"
        store.save(
            job.id, payload,
            meta={"kind": "influence_evaluate", "created": job.created,
                  "n": len(out["cases"]), "fingerprint": req.fingerprint,
                  "criteria_fingerprint": out["criteria_fingerprint"]},
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("influence_evaluate", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


class VerifyIn(InfluenceIn):
    """C급 검증 요청 — 후보 게인 스케줄 확정 **후** 별도 실행 (실행 단계 3).

    강건성 코너(질량·Cmα·Cmq — 축·문턱은 criteria.robustness)와 격자 중간점을
    돌린다. 지연 섭동·MC·미션·worst-case 탐색은 어휘와 자리만 있다(엔진 verify
    참조). 코너마다 재트림하므로 비용이 코너 수 × 케이스로 곱해진다 — 제출 시점에
    총량을 상한으로 막는다.
    """

    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1, max_length=MAX_CASES)
    criteria: dict | None = None
    depth: Literal["linear", "full"] = "full"
    midpoints: bool = True
    t_settle: float = Field(default=5.0, gt=0.0, allow_inf_nan=False)
    t_step: float = Field(default=30.0, gt=0.0, allow_inf_nan=False)
    t_hold: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    dt_plant: float = Field(default=0.01, gt=0.0, allow_inf_nan=False)


@router.post("/influence/verify", status_code=202)
def submit_verify(req: VerifyIn, request: Request, response: Response) -> dict:
    """C급 검증 — 강건성 코너 + 격자 중간점 (잡 기반 202, kind influence_verify).

    중간점 케이스 이름은 mach·alt·fuel **전체**를 싣는다 — 연료만 다른 격자에서
    이름이 겹치면 귀속이 조용히 다른 케이스로 바뀐다(웹 nameCases와 같은 계약).
    "mid/"는 예약 접두사다: 사용자 케이스가 그 이름을 쓰면 중간점 집계에 섞인다.
    """
    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    reserved = [c.name for c in cases if c.name.startswith("mid/")]
    if reserved:
        raise HTTPException(
            status_code=422,
            detail=f"'mid/'는 중간점 예약 접두사다 — 케이스 이름 변경 필요: {reserved}")
    try:
        shape = to_shape(req)
        criteria = GainEvalCriteria.from_dict(req.criteria)
        check_law_plant_pairing(ac, make_law(shape))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 격자 중간점 부가 — 이름은 전체 정밀도 mach·alt·fuel (겹침 금지 계약)
    mids: list = []
    if req.midpoints and criteria.schedule.midpoints:
        law = make_law(shape)
        tables = law.schedule.tables if law.schedule is not None else {}
        if tables:
            machs = [c.mach for c in cases]
            mvals = mach_midpoints(tables, lo=min(machs), hi=max(machs))
            combos = list(dict.fromkeys((c.alt, c.fuel) for c in cases))
            mids = [type(cases[0])(name=f"mid/M{m:g}_h{alt:g}_f{fuel:g}",
                                   mach=m, alt=alt, fuel=fuel)
                    for m in mvals for alt, fuel in combos]

    from claw.pipeline.evaluate import _corner_dispersions

    n_corner = len(_corner_dispersions(criteria))
    expected = n_corner * len(cases) + len(mids)
    if expected > MAX_CASES:
        raise HTTPException(
            status_code=422,
            detail=f"검증 총량 {expected}케이스(코너 {n_corner}×{len(cases)} + "
                   f"중간점 {len(mids)})가 상한 {MAX_CASES}를 넘는다 — 격자를 "
                   "줄이거나 강건성 축을 좁히세요")

    store = request.app.state.store
    per_case = (1 if req.depth == "linear" else 3) + 1
    total = expected * per_case

    def work(job):
        out = verify(
            make_demo_aircraft, cases, shape, criteria,
            depth=req.depth, midpoint_cases=mids, dt_plant=req.dt_plant,
            t_settle=req.t_settle, t_step=req.t_step, t_hold=req.t_hold,
            on_progress=lambda done, v_total, msg: job.report(
                done, max(v_total, total), message=msg
            ),
        )
        payload = to_jsonable(out)
        payload["kind"] = "influence_verify"
        store.save(
            job.id, payload,
            meta={"kind": "influence_verify", "created": job.created,
                  "n": expected, "fingerprint": req.fingerprint,
                  "criteria_fingerprint": out["criteria_fingerprint"]},
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("influence_verify", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


class PrescribeIn(InfluenceIn):
    """정량 처방 요청 — 저장된 스윕(result_id)에서 "얼마나"를 풀고 확인 런까지.

    knobs가 없으면 스윕이 실제로 흔든 단독 손잡이 전부가 대상이다. cases는 확인
    런(evaluate)의 격자다 — 스윕 저장물에는 케이스 좌표가 없어(이름뿐) 클라이언트가
    같은 격자를 다시 싣는 계약(3단 B와 동일).
    """

    fingerprint: str = ""
    result_id: str = Field(min_length=1)
    # 평가 결과 id — 주면 실패 지표·손잡이를 **승계**한다(사용자가 다시 고르지 않는다).
    # 없으면 기준의 하드 지표 전부를 푼다(종전 동작)
    eval_result_id: str = ""
    knobs: list[str] | None = None
    cases: list[TrimCaseIn] = Field(min_length=1, max_length=MAX_CASES)
    criteria: dict | None = None
    confirm: Literal["none", "linear", "full"] = "full"
    t_settle: float = Field(default=5.0, gt=0.0, allow_inf_nan=False)
    t_step: float = Field(default=30.0, gt=0.0, allow_inf_nan=False)
    t_hold: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    dt_plant: float = Field(default=0.01, gt=0.0, allow_inf_nan=False)


@router.post("/influence/prescribe", status_code=202)
def submit_prescribe(req: PrescribeIn, request: Request, response: Response) -> dict:
    """정량 처방 — 단일 필요 변화량 + 복수 소폭 조합 + 확인 런 (잡 202).

    풀이는 저장 스윕의 순수 변환이라 즉시고, 비용은 확인 런(트림 + evaluate)뿐이다.
    확정은 실측이다: 제안이 좋아 보여도 confirm 결과의 하드 게이트가 판정자다.
    """
    store = request.app.state.store
    try:
        payload = store.load(req.result_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"결과 없음: {req.result_id}")
    if payload.get("kind") != "influence_sweep":
        raise HTTPException(
            status_code=409,
            detail=f"influence_sweep 결과가 아니다: kind={payload.get('kind')}")
    rows = payload.get("rows") or []

    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    try:
        shape = to_shape(req)
        criteria = GainEvalCriteria.from_dict(req.criteria)
        check_law_plant_pairing(ac, make_law(shape))
        # ── 승계 — 평가가 좁혀 준 것을 사용자가 다시 고르지 않는다 ──────────
        inherited = {"metrics": None, "knobs": None, "cases": None,
                     "from": req.eval_result_id or None}
        if req.eval_result_id:
            try:
                ev = store.load(req.eval_result_id)
            except KeyError:
                raise HTTPException(
                    status_code=404,
                    detail=f"평가 결과 없음: {req.eval_result_id}")
            if ev.get("kind") != "influence_evaluate":
                raise HTTPException(
                    status_code=409,
                    detail=f"influence_evaluate 결과가 아니다: kind={ev.get('kind')}")
            # 실패 지표 — 하드 위반이 지목한 지표 + 국소성 판정이 나쁜 지표
            metrics = set()
            for f in (ev.get("aggregate") or {}).get("hard_fails") or []:
                check = f.get("check") or ""
                metrics.update(_HARD_CHECK_METRICS.get(check, ()))
            for key, v in (((ev.get("aggregate") or {}).get("locality")
                            or {}).get("metrics") or {}).items():
                if v.get("verdict") in ("local", "global"):
                    metrics.add(key)
            # 귀속 손잡이 — 케이스별 소견의 처방 카드가 지목한 자리
            aknobs = []
            bad_cases = []
            for c in ev.get("cases") or []:
                if c.get("hard_fails"):
                    bad_cases.append(c["case"])
                for pr in ((c.get("attribution") or {}).get("prescriptions") or []):
                    aknobs.extend(pr.get("knobs") or [])
            inherited = {
                "metrics": sorted(metrics) or None,
                "knobs": sorted(dict.fromkeys(aknobs)) or None,
                "cases": sorted(dict.fromkeys(bad_cases)) or None,
                "from": req.eval_result_id,
            }

        knobs = req.knobs or inherited["knobs"]
        if knobs:
            # 승계 손잡이 중 이 스윕이 실제로 흔든 것만 — 감도가 없으면 못 푼다
            swept = {k for r in rows if r.get("role") == "single"
                     for k in (r.get("overrides") or {})}
            missing = [k for k in knobs if k not in swept]
            knobs = [k for k in knobs if k in swept]
            if missing and not knobs:
                raise ValueError(
                    f"승계한 손잡이를 이 스윕이 흔들지 않았다: {missing} — "
                    "그 손잡이로 스윕을 먼저 돌릴 것")
        if not knobs:
            knobs = sorted({k for r in rows
                            if r.get("role") == "single"
                            for k in (r.get("overrides") or {})})
        if not knobs:
            raise ValueError("이 스윕에는 단독 런이 없다 — 처방을 풀 손잡이가 없다")
        universe = {r.id for r in param_universe(shape)}
        unknown = [k for k in knobs if k not in universe]
        if unknown:
            raise ValueError(f"알 수 없는 파라미터 id: {unknown}")
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    n = len(cases)
    per_case = 0 if req.confirm == "none" else (1 if req.confirm == "linear" else 3)
    total = 1 + (n + n * per_case if per_case else 0)

    def work(job):
        job.report(0, total, message="처방 풀이(저장 스윕 재계산)")
        targets = prescribe_targets(criteria)
        want = inherited["metrics"]
        if want:
            # 평가가 실패라고 한 지표만 — 통과한 지표까지 풀면 표의 절반이
            # "이미 문턱 안"으로 채워져 답이 묻힌다
            focused = [t for t in targets if t[0] in set(want)]
            if focused:
                targets = focused
        singles = {}
        for knob in knobs:
            singles[knob] = {}
            for metric, limit, above in targets:
                singles[knob][metric] = solve_single_knob(
                    rows, knob, metric, limit, above_is_bad=above)
        joint = solve_joint(rows, knobs, criteria,
                            metrics=[t[0] for t in targets])
        warnings = list(nonadditivity_warnings(payload, knobs))
        sweep_fp = payload.get("fingerprint") or ""
        shape_fp = shape.fingerprint()
        if sweep_fp and sweep_fp != shape_fp:
            warnings.append(
                f"계보 불일치: 스윕 지문 {sweep_fp} ≠ 현재 형상 지문 {shape_fp} — "
                "필요 변화량이 다른 형상의 감도에서 나왔다. 스윕을 다시 돌릴 것")
        job.report(1, total, message="처방 풀이 완료")

        confirm_report = None
        gain_export = None
        proposal_notes: list = []
        spans = joint.get("spans") or {}
        # 제안 변화가 사실상 0이면 확인 런은 base 재평가일 뿐이다 — 돌리지 않고
        # 그 사실을 말한다 (조용한 낭비는 "확인했다"는 착각을 만든다)
        if all(abs(v) < 1e-6 for v in spans.values()) and spans:
            warnings.append("제안 변화가 0 — 확인 런 생략(확인할 새 형상이 없다)")
            spans = {}
        if req.confirm != "none" and spans:
            shape2, proposal_notes = proposal_shape(shape, spans)
            trs = trim_batch(
                ac, cases, fingerprint=req.fingerprint,
                on_progress=lambda done, _t, tr: job.report(
                    1 + done, total, message=f"확인 트림: {tr.case.name}"))
            confirm_report = evaluate(
                ac, trs, shape2, criteria, depth=req.confirm,
                dt_plant=req.dt_plant, t_settle=req.t_settle,
                t_step=req.t_step, t_hold=req.t_hold,
                on_progress=lambda done, ev_total, msg: job.report(
                    1 + n + done, 1 + n + ev_total, message=f"확인: {msg}"))
            gain_export = proposal_export(shape2)

        out = to_jsonable({
            "kind": "influence_prescribe",
            "sweep_result_id": req.result_id,
            "knobs": knobs,
            "inherited": inherited,
            "singles": singles,
            "joint": joint,
            "confirm": confirm_report,
            "gain_export": gain_export,
            "proposal_notes": proposal_notes,
            "fingerprint": shape_fp,
            "sweep_fingerprint": sweep_fp,
            "criteria_fingerprint": criteria.fingerprint(),
            "warnings": warnings,
        })
        store.save(job.id, out,
                   meta={"kind": "influence_prescribe", "created": job.created,
                         "n": len(knobs), "fingerprint": req.fingerprint,
                         "criteria_fingerprint": criteria.fingerprint()})
        job.result_id = job.id

    job = request.app.state.jobs.submit("influence_prescribe", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()
