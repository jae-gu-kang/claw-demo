"""자동 설계 루프 라우트 (M17) — 트림 자동화→튜닝→적합→검증→분류 이터레이션 잡.

서버는 얇다: 설정 병합·예산 상한·잡 배선만 하고, 스테이지·처방·수렴 판정은 전부
엔진 DesignSession 소관. gated 흐름: 잡이 awaiting_approval로 끝나면 결과에 처방
카드가 들어 있고, /design/{id}/resume에 승인 id를 보내면 세션을 복원해 이어 돈다
(새 result id, meta.parent로 계보). 에스컬레이션은 승인 목록에 있어도 엔진이
적용을 거부한다 (상위 설계 변경 자동 적용 금지).

기본값의 정본은 엔진 AutoDesignConfig — /design/defaults가 그대로 내려 주고 웹은
수치를 재기술하지 않는다 (합격기준 하드코딩 이관, 01 §5).
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from claw.design import AutoDesignConfig, DesignSession, resample_to_table
from claw.fcl.demo import demo_design_gains
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_stall_table,
    make_demo_structural_limits,
)
from claw.tables import PolyTable
from claw_server.serialize import to_jsonable

router = APIRouter(tags=["design"])

MAX_POINTS = 200  # influence.py MAX_CASES 정합 — 단일 워커 점유 상한


class AutoDesignIn(BaseModel):
    aircraft: Literal["demo"] = "demo"
    fingerprint: str = ""
    config: dict = Field(default_factory=dict)  # 기본값 위 부분 덮어쓰기 — 정본은 엔진


class ResumeIn(BaseModel):
    approved: list[str] = Field(min_length=1)  # 전부 기각이면 재개할 것이 없다 — 422
    fingerprint: str = ""


def _build_config(overrides: dict) -> AutoDesignConfig:
    base = AutoDesignConfig().to_dict()
    unknown = sorted(set(overrides) - set(base))
    if unknown:
        raise ValueError(f"미정의 config 키 {unknown} — 허용: {sorted(base)}")
    merged = {**base, **overrides}
    for nested in ("criteria", "targets"):
        if nested in overrides:
            if not isinstance(overrides[nested], dict):
                raise ValueError(f"{nested}는 dict여야 함")
            bad = sorted(set(overrides[nested]) - set(base[nested]))
            if bad:
                raise ValueError(f"미정의 {nested} 키 {bad}")
            merged[nested] = {**base[nested], **overrides[nested]}
    cfg = AutoDesignConfig.from_dict(merged)
    if cfg.budget_points > MAX_POINTS:
        raise ValueError(f"budget_points 상한 {MAX_POINTS} 초과: {cfg.budget_points}")
    return cfg


def _gain_export(session: DesignSession) -> dict:
    """확정 게인 반출 — sched_spec(정본, 다항 포함) + 테이블 호환 재샘플.

    tables 항목은 sim/codegen 게인 페이로드(TableIn|PolyTableIn 태그드 유니언)에
    그대로 주입 가능한 형상이다 — 웹 "게인 확정" 버튼의 소비 계약.
    """
    tables = {}
    tables_resampled = {}
    for slot, tab in session.sched_tables.items():
        if isinstance(tab, PolyTable):
            tables[slot] = tab.to_dict()
            rt = resample_to_table(tab)
            tables_resampled[slot] = {
                "axes": {rt.axis_names[0]: rt.axes[0].tolist()},
                "data": rt.data.tolist(),
                "extrapolate": "clip",
            }
        else:
            tables[slot] = {
                "axes": {n: a.tolist() for n, a in zip(tab.axis_names, tab.axes)},
                "data": tab.data.tolist(), "extrapolate": tab.extrapolate,
            }
            tables_resampled[slot] = tables[slot]
    return {
        "tables": tables,
        "tables_resampled": tables_resampled,
        "constants": dict(session.sched_constants),
    }


def _save_session(store, job, session: DesignSession, fingerprint: str,
                  parent: str | None = None) -> None:
    payload = session.to_dict()
    payload["report"] = session.report()
    payload["proposed_actions"] = session.proposed_actions()
    payload["gain_export"] = _gain_export(session)
    store.save(
        job.id,
        to_jsonable(payload),
        meta={
            "kind": "auto_design",
            "created": job.created,
            "status": session.status,
            "stage": session.stage,
            "fingerprint": fingerprint,
            "parent": parent,
        },
    )
    job.result_id = job.id


def _run_session_job(request, response, session: DesignSession, fingerprint: str,
                     parent: str | None = None) -> dict:
    store = request.app.state.store
    ac = make_demo_aircraft()
    stall = make_demo_stall_table()
    limits = make_demo_structural_limits()
    db = make_demo_db_ranges()
    design = demo_design_gains()

    def work(job):
        # job.report의 반환값이 취소 요청 여부 — 엔진 협조적 취소 규약과 그대로 맞물린다
        session.run(
            ac, stall, limits, db, design, fingerprint=fingerprint,
            on_progress=lambda done, total, msg: job.report(done, total, message=msg),
        )
        _save_session(store, job, session, fingerprint, parent=parent)

    job = request.app.state.jobs.submit("auto_design", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


@router.get("/design/defaults")
def design_defaults() -> dict:
    """엔진 기본값 그대로 — 합격기준·목표·허용치·예산. 웹은 수치를 재기술하지 않는다."""
    return {"config": AutoDesignConfig().to_dict(), "max_points": MAX_POINTS}


@router.post("/design/auto", status_code=202)
def submit_auto_design(req: AutoDesignIn, request: Request, response: Response) -> dict:
    try:
        cfg = _build_config(req.config)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _run_session_job(request, response, DesignSession(cfg), req.fingerprint)


@router.post("/design/{result_id}/resume", status_code=202)
def resume_auto_design(result_id: str, req: ResumeIn, request: Request,
                       response: Response) -> dict:
    store = request.app.state.store
    try:
        payload = store.load(result_id)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"결과 없음: {result_id}")
    if payload.get("kind") != "auto_design":
        raise HTTPException(status_code=409, detail=f"auto_design 결과가 아님: {result_id}")
    session = DesignSession.from_dict(payload)
    if session.status == "awaiting_approval":
        session.apply_actions(req.approved)
    elif session.status == "cancelled":
        pass  # 취소 재개 — 남은 스테이지부터 (승인 목록은 무시된다)
    else:
        raise HTTPException(
            status_code=409,
            detail=f"재개 불가 상태: {session.status} (awaiting_approval·cancelled만 재개)",
        )
    return _run_session_job(request, response, session, req.fingerprint,
                            parent=result_id)
