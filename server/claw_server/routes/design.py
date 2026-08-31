"""자동 설계 루프 라우트 (M17) — 트림 자동화→튜닝→적합→검증→분류 이터레이션 잡.

서버는 얇다: 설정 병합·예산 상한·잡 배선만 하고, 스테이지·처방·수렴 판정은 전부
엔진 DesignSession 소관. gated 흐름: 잡이 awaiting_approval로 끝나면 결과에 처방
카드가 들어 있고, /design/{id}/resume에 승인 id를 보내면 세션을 복원해 이어 돈다
(새 result id, meta.parent로 계보). 에스컬레이션은 승인 목록에 있어도 엔진이
적용을 거부한다 (상위 설계 변경 자동 적용 금지).

기본값의 정본은 엔진 AutoDesignConfig — /design/defaults가 그대로 내려 주고 웹은
수치를 재기술하지 않는다 (합격기준 하드코딩 이관, 01 §5).

저장물에는 세션 직렬화 외에 report·proposed_actions·gain_export와 **미달 원장**
(`ledger`, 상한 초과 시 `ledger_truncated`)이 함께 실린다 — 엔진이 계산하고 정렬한
것을 그대로 옮기며, 라우트가 더하는 것은 저장 크기 상한과 그 고지뿐이다.
"""

import math
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from claw.design import AutoDesignConfig, DesignSession, resample_to_table
from claw.design.tune import REASON_TEXT
from claw.fcl.demo import demo_design_gains, demo_rate_filters
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

# 저장물에 싣는 미달 원장 행 수 상한. 원장은 **(점 × 자리)** 규모라 MAX_POINTS 격자에
# 자리 5개면 1000행을 넘고, 거기에 튜닝·무효 처방 행이 더 붙는다. 저장물은 한 덩어리
# JSON이고 재개(/design/{id}/resume)는 그것을 통째로 읽어 세션을 복원하므로, 원장이
# 커지면 조회와 재개가 함께 무거워진다. 상한은 엔진이 아니라 여기 있다 — 엔진 원장은
# 판정의 전량 목록이어야 하고(report의 ledger_size가 그 전량 수다), 줄이는 것은 저장·
# 전송 사정이지 판정 사정이 아니다. 자를 때는 severity 상위부터 남긴다.
MAX_LEDGER_ROWS = 500

# 재샘플 허용치 — resample_to_table의 기본값과 같은 값을 **명시로** 넘긴다. 반출에
# 이 수치를 함께 싣기 때문이다: 엔진 기본값이 바뀌어도 보고한 값과 실제로 쓴 값이
# 갈리지 않아야 한다 (기본값에 기대면 보고가 조용히 거짓말이 된다).
_RESAMPLE_TOL = 0.01
# 재샘플 오차 재측정 격자 — resample_to_table은 구간 중점만 보며 이분하므로
# knot 사이 최악점이 중점이 아닐 수 있다. 다시 재는 쪽은 촘촘해야 한다.
_RESAMPLE_PROBE = 401


class AutoDesignIn(BaseModel):
    aircraft: Literal["demo"] = "demo"
    fingerprint: str = ""
    config: dict = Field(default_factory=dict)  # 기본값 위 부분 덮어쓰기 — 정본은 엔진


class ResumeIn(BaseModel):
    # 취소된 세션은 승인할 처방이 없다(스테이지 도중에 멈춘 것) — 빈 목록을 허용하고,
    # 승인 대기 상태에서만 최소 1건을 요구한다(그때는 빈 목록이 곧 무의미한 재개다)
    approved: list[str] = Field(default_factory=list)
    fingerprint: str = ""


# 정수로만 뜻이 있는 필드 — 격자 개수·차수·예산. float을 넣으면 엔진 범위 비교는
# 통과하고 np.linspace·Padé 차수에서 터져 **202 뒤 원인 없는 실패**가 된다
_INT_KEYS = ("budget_points", "budget_iters", "budget_tune_evals", "n_mach",
             "max_degree", "max_segments", "pade_order")


def _check_number(where: str, v) -> None:
    """수치 + double 표현 가능성 — 범위 판정은 엔진 몫이고 서버는 이 경계만 진다.

    두 가지를 막는다. ① NaN은 엔진의 범위 비교(`v < lo`)를 조용히 통과한다.
    통과한 NaN은 작동기·기준값을 오염시켜 마진이 전부 NaN이 되고, 문턱 비교가
    모조리 False라 **계산한 적 없는 판정이 합격으로 보고된다** — 202 잡이라
    화면에는 정상으로 보인다. ② double 범위를 넘는 정수.

    ②가 새는 방식은 자리마다 다르다. AutoDesignConfig.from_dict는 **중첩 dict만**
    float()으로 바꾸고 top-level 스칼라는 그대로 넘긴다:
      - criteria·targets → from_dict의 float()에서 OverflowError. ArithmeticError
        하위라 라우트의 except (ValueError, TypeError)에 안 잡혀 **500**.
      - actuator_wn 같은 top-level·alts/fuels 항목 → config 층에 변환하는 자리가
        없어 **조용히 수용(202)**된다. 뒷일은 잡 스레드로 밀리고(grid.py의
        float(a) 등) 자리마다 다르다 — 요청은 이미 성공으로 답해진 뒤라 어느
        쪽이든 사용자는 제출 시점에 알 방법이 없다.
      - budget_points·budget_iters → 다른 상한에 먼저 걸려 이미 422다. 단 전자의
        상한은 **이 파일의 MAX_POINTS**이고 엔진엔 하한뿐이다(후자만 엔진 MAX_ITERS).
    그래서 이 검사는 엔진 안이 아니라 **여기**여야 한다. 엔진 from_dict 두 곳을
    고쳐도 top-level 경로는 그대로 샌다 — 네 갈래를 다 보는 층은 서버뿐이다.
    형제 라우트(sim·codegen·influence)는 유한성만 보는데 여기가 float() 선변환까지
    하는 것은, config가 임의 정밀도 int를 그대로 담아 오는 생 dict이기 때문이다.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"수치여야 함 — {where}: {v!r}")
    try:
        f = float(v)
    except OverflowError:
        raise ValueError(f"double 범위 초과 — {where}: {v!r}")
    if not math.isfinite(f):
        raise ValueError(f"비유한값 config — {where}: {v!r}")


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
    # 타입 검증 — 데이터클래스는 강제 변환을 하지 않으므로 여기서 걸러야 한다.
    # 안 걸리는 값은 잡 스레드 안에서 터져 202 뒤 원인 없는 실패가 된다
    for key, want in (("mode", str), ("alts", (list, type(None))), ("fuels", (list, type(None)))):
        if not isinstance(merged[key], want):
            raise ValueError(f"{key} 타입 오류: {type(merged[key]).__name__}")
    for key, value in merged.items():
        if key in ("mode", "alts", "fuels", "criteria", "targets"):
            continue
        _check_number(key, value)
        if key in _INT_KEYS and isinstance(value, float) and not value.is_integer():
            raise ValueError(f"{key}는 정수여야 함: {value}")
    for key in ("alts", "fuels"):
        for v in merged[key] or ():
            _check_number(f"{key} 항목", v)
    for nested in ("criteria", "targets"):
        for k, v in merged[nested].items():
            _check_number(f"{nested}.{k}", v)
    cfg = AutoDesignConfig.from_dict(merged)
    if cfg.budget_points > MAX_POINTS:
        raise ValueError(f"budget_points 상한 {MAX_POINTS} 초과: {cfg.budget_points}")
    return cfg


def _resample_error(poly: PolyTable, tab) -> dict:
    """다항 정본 대비 재샘플 테이블의 어긋남 — {max_abs, max_frac, at, n_points}.

    `max_frac`은 곡선 진폭(구간 내 최대 |값|) 대비 비율이라 `resample_tol`과 같은
    자다 — 둘을 나란히 놓으면 "허용치 안에 들었나"가 바로 읽힌다. 절대값도 함께
    내는 것은 게인 자리마다 크기가 달라 비율만으로는 감이 안 오기 때문이다.

    다시 재는 이유: resample_to_table의 tol_interp는 **목표치이지 보장이 아니다**.
    구간 중점만 보며 이분하고 max_pts·depth 상한에서 멈추므로, 최악점이 중점이
    아니거나 상한에 먼저 걸리면 허용치를 넘은 채 끝난다.
    """
    axis = poly.axis_names[0]
    xs = np.linspace(float(poly.knots[0]), float(poly.knots[-1]), _RESAMPLE_PROBE)
    p = np.asarray(poly.interp(**{axis: xs}), dtype=float)
    err = np.abs(p - np.asarray(tab.interp(**{axis: xs}), dtype=float))
    i = int(np.argmax(err))
    scale = float(np.max(np.abs(p))) or 1.0  # resample_to_table의 scale과 같은 정의
    return {"max_abs": float(err[i]), "max_frac": float(err[i]) / scale,
            "at": float(xs[i]), "n_points": int(tab.data.size)}


def _gain_export(session: DesignSession) -> dict:
    """확정 게인 반출 — sched_spec(정본, 다항 포함) + 테이블 호환 재샘플 + 그 오차.

    tables 항목은 sim/codegen 게인 페이로드(TableIn|PolyTableIn 태그드 유니언)에
    그대로 주입 가능한 형상이다 — 웹 "게인 확정" 버튼의 소비 계약.

    그런데 그 버튼이 실제로 주입하는 것은 `tables_resampled`이고, 그것은 다항을
    선형 격자로 **재양자화한 근사**다 — 세션이 검증한(margin_out) 형상이 아니다.
    차이를 어디에도 안 적으면 "확정"이 검증 결과를 그대로 물려받는 것처럼 보인다.
    그래서 실제로 쓴 허용치(`resample_tol`)와 자리별 최대 어긋남(`resample_error`)을
    함께 낸다 — 웹이 "확정하면 이만큼 어긋난다"를 말할 수 있어야 한다.
    비다항 자리는 재샘플이 곧 원본이라 오차가 정의상 0이다.
    """
    tables = {}
    tables_resampled = {}
    resample_error = {}
    for slot, tab in session.sched_tables.items():
        if isinstance(tab, PolyTable):
            tables[slot] = tab.to_dict()
            rt = resample_to_table(tab, tol_interp=_RESAMPLE_TOL)
            tables_resampled[slot] = {
                "axes": {rt.axis_names[0]: rt.axes[0].tolist()},
                "data": rt.data.tolist(),
                "extrapolate": "clip",
            }
            resample_error[slot] = _resample_error(tab, rt)
        else:
            tables[slot] = {
                "axes": {n: a.tolist() for n, a in zip(tab.axis_names, tab.axes)},
                "data": tab.data.tolist(), "extrapolate": tab.extrapolate,
            }
            tables_resampled[slot] = tables[slot]
            resample_error[slot] = {"max_abs": 0.0, "max_frac": 0.0, "at": None,
                                    "n_points": int(tab.data.size)}
    return {
        "tables": tables,
        "tables_resampled": tables_resampled,
        "resample_tol": _RESAMPLE_TOL,
        "resample_error": resample_error,
        "constants": dict(session.sched_constants),
    }


def _ledger_payload(session: DesignSession) -> dict:
    """미달 원장 조각 — {ledger} 또는 {ledger, ledger_truncated}.

    행을 만드는 것도 정렬하는 것도 엔진 몫이다(severity 내림차순, 측정 불가가 맨 앞
    — criteria.severity와 같은 규약). 라우트는 **앞에서 자르기만** 한다: 여기서 행을
    조립하거나 다시 정렬하면 화면이 읽는 순서가 엔진 규약과 갈리고, 갈린 쪽이 화면이라
    사용자는 "가장 심각한 것"으로 엉뚱한 행을 본다.

    자른 사실은 `ledger_truncated`로 반드시 남긴다. 원장은 "이 실행이 못 맞춘 것
    전부"를 뜻하는 목록이라, 조용히 잘린 원장은 **못 맞춘 것이 그것뿐이라고 말하는
    목록**이 된다 — 실패 0을 통과로 위장하지 않으려고 judged·outside_envelope·
    not_trimmed를 함께 세는 것과 같은 이유다. total은 report의 ledger_size(엔진 전량
    기준)와 같은 수이므로, 화면은 둘 중 어느 쪽을 봐도 "몇 개를 안 보여주는가"를 안다.

    비유한값은 여기서 손대지 않는다 — 행의 severity·shortfall(deficit·achieved 등)은
    ±inf·nan일 수 있고, 그 정리는 _save_session의 to_jsonable 봉투가 일괄로 한다.
    """
    rows = list(session.shortfall_ledger())
    if len(rows) <= MAX_LEDGER_ROWS:
        return {"ledger": rows}
    return {
        "ledger": rows[:MAX_LEDGER_ROWS],
        "ledger_truncated": {"kept": MAX_LEDGER_ROWS, "total": len(rows)},
    }


def _save_session(store, job, session: DesignSession, fingerprint: str,
                  parent: str | None = None) -> None:
    payload = session.to_dict()
    payload["report"] = session.report()
    payload["proposed_actions"] = session.proposed_actions()
    payload["gain_export"] = _gain_export(session)
    # 마지막에 얹는다 — to_jsonable 봉투 **안**이어야 원장의 inf/nan이 정책을 탄다
    payload.update(_ledger_payload(session))
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
    # 법칙의 레이트 필터도 프로파일이 준다 — 안 넘기면 튜닝·검증이 출하되지 않는
    # 조성(요축 워시아웃 없는 A′)을 본다 (01 §4.2)
    rate_filters = demo_rate_filters()

    def work(job):
        # job.report의 반환값이 취소 요청 여부 — 엔진 협조적 취소 규약과 그대로 맞물린다
        session.run(
            ac, stall, limits, db, design, rate_filters=rate_filters,
            fingerprint=fingerprint,
            on_progress=lambda done, total, msg: job.report(done, total, message=msg),
        )
        _save_session(store, job, session, fingerprint, parent=parent)

    job = request.app.state.jobs.submit("auto_design", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


@router.get("/design/defaults")
def design_defaults() -> dict:
    """엔진 기본값 그대로 — 합격기준·목표·허용치·예산. 웹은 수치를 재기술하지 않는다.

    reason_text(튜닝 포기 사유 → 한 줄 설명 + 다음 수)도 같은 원칙으로 내려 준다.
    사유 코드는 엔진이 만들고 뜻도 엔진이 안다 — 웹이 문구를 다시 적으면 두 곳이
    갈리고, 갈린 쪽이 화면이라 사용자는 **엔진이 뜻하지 않은 안내**를 읽는다
    (실제로 그런 사고가 있었다: 마진은 통과했는데 "마진 미달"이라 적혔다 —
    tune.py REASON_* 머리말). criteria 기본값을 웹이 재기술하지 않는 것과 같은 이유다.
    """
    return {
        "config": AutoDesignConfig().to_dict(),
        "max_points": MAX_POINTS,
        "reason_text": dict(REASON_TEXT),
    }


@router.post("/design/auto", status_code=202)
def submit_auto_design(req: AutoDesignIn, request: Request, response: Response) -> dict:
    try:
        cfg = _build_config(req.config)
    except (ValueError, TypeError) as e:
        # 데이터클래스는 값을 강제 변환하지 않는다 — 타입이 틀린 스칼라는 __post_init__의
        # 비교에서 TypeError로 나온다. 형제 라우트(sim·codegen·influence)와 같은 정책으로
        # 422에 매핑한다 (놓치면 500)
        raise HTTPException(status_code=422, detail=str(e))
    return _run_session_job(request, response, DesignSession(cfg), req.fingerprint)


@router.post("/design/{result_id}/resume", status_code=202)
def resume_auto_design(result_id: str, req: ResumeIn, request: Request,
                       response: Response) -> dict:
    store = request.app.state.store
    try:
        payload = store.load(result_id)
    except ValueError as e:
        # 저장될 수 없는 형식의 id — 밀려난 것이 아니므로 보존 상한 힌트를 붙이면
        # 정확히 반대로 안내하게 된다 (잘린 id·확장자 붙은 id가 여기로 온다)
        raise HTTPException(status_code=422, detail=f"잘못된 결과 id 형식: {e}")
    except KeyError:
        # 승인 대기 세션은 **저장소 보존 상한에 밀려 사라질 수 있다** — 그 경우와
        # 오타를 구별해 주지 않으면 사용자가 없는 id를 계속 찾는다
        limit = getattr(store, "limit", None)
        hint = (f" (보존 상한 {limit}건 — 이후 저장이 그만큼 쌓였다면 밀려났을 수 있다)"
                if limit else "")
        raise HTTPException(status_code=404, detail=f"결과 없음: {result_id}{hint}")
    if payload.get("kind") != "auto_design":
        raise HTTPException(status_code=409, detail=f"auto_design 결과가 아님: {result_id}")
    try:
        session = DesignSession.from_dict(payload)
    except (KeyError, ValueError, TypeError) as e:
        # 저장된 세션이 지금 엔진 스키마와 안 맞는다(배포 사이 필드 변경 등) —
        # 형제 라우트가 엔진 예외를 4xx로 매핑하는 것과 같은 정책. 놓치면 500이다
        raise HTTPException(
            status_code=409,
            detail=f"재개 불가 — 저장된 세션이 현재 엔진 스키마와 맞지 않음: {e}",
        )
    if session.status == "awaiting_approval":
        if not req.approved:
            raise HTTPException(
                status_code=422,
                detail="승인한 처방이 없다 — 최소 1건을 승인하거나 세션을 그대로 두세요",
            )
        session.apply_actions(req.approved)
    elif session.status == "cancelled":
        pass  # 취소 재개 — 남은 스테이지부터 (승인 목록은 비어 있는 것이 정상)
    else:
        raise HTTPException(
            status_code=409,
            detail=f"재개 불가 상태: {session.status} (awaiting_approval·cancelled만 재개)",
        )
    return _run_session_job(request, response, session, req.fingerprint,
                            parent=result_id)
