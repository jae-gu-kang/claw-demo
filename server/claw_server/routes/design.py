"""자동 설계 루프 라우트 (M17) — 트림 자동화→튜닝→적합→검증→분류 이터레이션 잡.

서버는 얇다: 설정 병합·예산 상한·잡 배선만 하고, 스테이지·처방·수렴 판정은 전부
엔진 DesignSession 소관. gated 흐름: 잡이 awaiting_approval로 끝나면 결과에 처방
카드가 들어 있고, /design/{id}/resume에 승인 id를 보내면 세션을 복원해 이어 돈다
(새 result id, meta.parent로 계보). 에스컬레이션은 승인 목록에 있어도 엔진이
적용을 거부한다 (상위 설계 변경 자동 적용 금지).

기본값의 정본은 엔진 AutoDesignConfig — /design/defaults가 그대로 내려 주고 웹은
수치를 재기술하지 않는다 (합격기준 하드코딩 이관, 04 §1).

저장물에는 세션 직렬화 외에 report·proposed_actions·gain_export와 **미달 원장**
(`ledger`, 상한 초과 시 `ledger_truncated`)이 함께 실린다 — 엔진이 계산하고 정렬한
것을 그대로 옮기며, 라우트가 더하는 것은 저장 크기 상한과 그 고지뿐이다.
"""

import math
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

import copy
from datetime import datetime, timezone

from claw.design import AutoDesignConfig, DesignSession, resample_to_table
from claw.design.tune import REASON_TEXT
from claw.profile import ProfileError, build_profile
from claw.profile.fingerprint import gain_tables_basis_fingerprint
from claw_server.profiles import EXAMPLE_ID, ProfileConflict, ProfileReadOnly, ProfileUnreadable
from claw_server.refs import ProfileRef, profile_echo, profile_error_detail, resolve_profile, resolve_snapshot
from claw.tables import PolyTable
from claw_server.serialize import to_jsonable

router = APIRouter(tags=["design"])

MAX_POINTS = 200  # influence.py MAX_CASES 정합 — 단일 워커 점유 상한

# 저장물에 싣는 미달 원장 행 수 상한. 원장은 **(점 × 자리)** 규모라 MAX_POINTS 격자에
# 판정 자리 5개면(게인 자리 7이 아니다 — tune.py) 1000행을 넘고, 거기에 튜닝·무효 처방 행이 더 붙는다. 저장물은 한 덩어리
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
    profile: ProfileRef | None = None  # 기체 선택 — 없으면 예제 기체 (02 §5.6)
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
             "n_validation_between", "max_degree", "max_segments", "pade_order")


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


def _gain_export(session: DesignSession, aircraft, on_progress=None) -> dict:
    """확정 게인 반출 — sched_spec(정본, 다항 포함) + 테이블 호환 재샘플 + 그 오차 + 재검증.

    tables 항목은 sim/codegen 게인 페이로드(TableIn|PolyTableIn 태그드 유니언)에
    그대로 주입 가능한 형상이다 — 웹 "게인 확정" 버튼의 소비 계약.

    그런데 그 버튼이 실제로 주입하는 것은 `tables_resampled`이고, 그것은 다항을
    선형 격자로 **재양자화한 근사**다 — 세션이 검증한(margin_out) 형상이 아니다.
    차이를 어디에도 안 적으면 "확정"이 검증 결과를 그대로 물려받는 것처럼 보인다.
    그래서 둘을 함께 낸다:
    - `resample_tol`·`resample_error` — **게인 공간**의 어긋남 (얼마나 다른 표인가)
    - `reverify` — **판정 공간**의 재검증 (그 표로 다시 판정하면 무엇이 움직이나 —
      session.reverify_resampled, 검증점·트림 재사용이라 점당 선형 계산뿐).
      게인 오차가 허용치 안이어도 판정 마진이 그보다 얇으면 등급이 움직일 수 있다 —
      그때 "확정하면 이 자리가 fail이 된다"를 말하는 것은 이쪽이다.
    비다항 자리는 재샘플이 곧 원본이라 오차가 정의상 0이다.
    """
    tables = {}
    tables_resampled = {}
    resample_error = {}
    export_tables = {}  # 재검증용 Table 실물 — 직렬화한 것과 같은 객체여야 한다
    for slot, tab in session.sched_tables.items():
        if isinstance(tab, PolyTable):
            tables[slot] = tab.to_dict()
            rt = resample_to_table(tab, tol_interp=_RESAMPLE_TOL)
            export_tables[slot] = rt
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
            export_tables[slot] = tab
            tables_resampled[slot] = tables[slot]
            resample_error[slot] = {"max_abs": 0.0, "max_frac": 0.0, "at": None,
                                    "n_points": int(tab.data.size)}
    return {
        "tables": tables,
        "tables_resampled": tables_resampled,
        "resample_tol": _RESAMPLE_TOL,
        "resample_error": resample_error,
        "reverify": session.reverify_resampled(aircraft, export_tables,
                                               on_progress=on_progress),
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
                  parent: str | None = None, *, profile) -> None:
    payload = session.to_dict()
    payload["report"] = session.report()
    payload["proposed_actions"] = session.proposed_actions()
    # 재검증(반출 표 재판정)도 잡 스레드 몫이다 — job.report 배선으로 취소가 통한다
    payload["gain_export"] = _gain_export(
        session, profile.aircraft(),
        on_progress=lambda d, t, m: job.report(d, t, message=f"reverify {m}"))
    # 마지막에 얹는다 — to_jsonable 봉투 **안**이어야 원장의 inf/nan이 정책을 탄다
    payload.update(_ledger_payload(session))
    # 이 세션이 설계한 기체 — 재개는 이 지문의 스냅숏으로 같은 기체를 되살린다 (02 §5.6)
    payload["profile"] = profile_echo(profile)
    store.save(
        job.id,
        to_jsonable(payload),
        meta={
            "kind": "auto_design",
            "profile": profile_echo(profile),
            "created": job.created,
            "status": session.status,
            "stage": session.stage,
            "fingerprint": fingerprint,
            "parent": parent,
        },
    )
    job.result_id = job.id


def _run_session_job(request, response, session: DesignSession, fingerprint: str,
                     parent: str | None = None, *, profile) -> dict:
    store = request.app.state.store
    try:
        ac = profile.aircraft()
        stall = profile.stall_table()
        limits = profile.structural_limits()
        db = profile.db_ranges()
        # 게인 미설계 기체는 202 전에 422다 — 튜너 브래킷이 설계값에서 나오므로(05 §7.4) 잡을
        # 받아 봐야 전 자리 seed_required고, detail.path(/law/design)가 웹의 「기체 탭 → 초기
        # 게인」 안내 링크 근거가 된다. 종전에는 여기서 잡히지 않아 500이었다
        design = profile.design_gains()
        # 법칙의 레이트 필터도 프로파일이 준다 — 안 넘기면 튜닝·검증이 출하되지 않는
        # 조성(요축 워시아웃 없는 A′)을 본다 (05 §6)
        rate_filters = profile.rate_filters()
        # 운용 고도 범위도 프로파일이 준다 — coarse 격자 고도 자동 유도의 범위(05 §3)
        op = profile.doc["operating"]
        alt_range = (op["alt_min"], op["alt_max"])
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))

    def work(job):
        # job.report의 반환값이 취소 요청 여부 — 엔진 협조적 취소 규약과 그대로 맞물린다
        session.run(
            ac, stall, limits, db, design, rate_filters=rate_filters, alt_range=alt_range,
            fingerprint=fingerprint,
            on_progress=lambda done, total, msg: job.report(done, total, message=msg),
        )
        _save_session(store, job, session, fingerprint, parent=parent, profile=profile)

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
    return _run_session_job(request, response, DesignSession(cfg), req.fingerprint,
                            profile=resolve_profile(request, req.profile))


class ApplyGainsIn(BaseModel):
    base_revision: int = Field(ge=1)


def _reverify_summary(rv: dict | None) -> dict:
    """재검증 결과 → provenance 요약 — 수치 목록(changed·failures)은 개수로 접는다.

    provenance는 문서에 영속하는 자리라 행 목록을 통째로 실으면 문서가 결과 저장물을
    복제하게 된다. 없으면(옛 결과) None 필드로 — 0으로 위장하지 않는다.
    """
    if not rv:
        return {"n_judged": None, "worse": None, "better": None, "changed": None,
                "note": "재검증 없음 — 이 결과가 반출될 때는 재검증이 없었다"}
    out = {"n_judged": rv.get("n_judged"), "worse": rv.get("worse"),
           "better": rv.get("better"), "changed": len(rv.get("changed") or [])}
    if rv.get("note"):
        out["note"] = rv["note"]
    return out


@router.post("/design/{result_id}/apply-gains")
def apply_gains_to_profile(result_id: str, req: ApplyGainsIn, request: Request) -> dict:
    """자동 설계 확정 게인을 그 기체 문서에 반영 — law.gain_tables 새 리비전 (정본 되쓰기, 스키마 v2).

    반영 후의 모든 계산(시뮬·마진·코드)이 문서의 이 표로 조립된다(assemble_law 우선순위). 표는 웹
    「채택」(작업본 주입)과 같은 `tables_resampled`다 — 다항은 재양자화 근사이고 그 오차 고지
    (resample_tol·resample_error)를 provenance에 함께 적는다. 가드:
    - 결과의 기체·지문과 지금 문서가 같아야 한다(409) — 다른 문서에 설계를 이식하지 않고, 같은
      결과의 재반영도 막힌다(반영 자체가 지문을 바꾼다 — 재설계 후 다시 반영한다)
    - 형상 변형 위에서 돈 설계는 기본 문서에 반영하지 않는다(422) · 예제 403 · 기준 리비전 충돌
      409 (quick-seed와 같은 규칙)
    """
    store = request.app.state.store
    try:
        payload = store.load(result_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"잘못된 결과 id 형식: {e}")
    except KeyError:
        raise HTTPException(status_code=404,
                            detail=f"결과 없음(보존 상한에 밀려 사라졌을 수 있음): {result_id}")
    if payload.get("kind") != "auto_design":
        raise HTTPException(status_code=422, detail=f"자동 설계 결과가 아니다: {payload.get('kind')!r}")
    echo = payload.get("profile") or {}
    pid = echo.get("id")
    if not pid or echo.get("source") == "default-example" or pid == EXAMPLE_ID:
        raise HTTPException(status_code=403, detail="예제 기체는 고칠 수 없다 — 복제한 기체에서 설계하고 반영한다")
    if echo.get("variant"):
        raise HTTPException(status_code=422,
                            detail="형상 변형 위에서 돈 설계는 기본 문서에 반영할 수 없다 — 기본 형상으로 다시 돌린다")
    export = payload.get("gain_export") or {}
    tables = export.get("tables_resampled") or {}
    if not tables:
        raise HTTPException(status_code=422, detail="반출 게인 표가 없는 결과 — 반영할 것이 없다")
    profiles = request.app.state.profiles
    try:
        doc, rev = profiles.get(pid)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {pid}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    if req.base_revision != rev:
        raise HTTPException(status_code=409, detail={
            "message": f"기준 리비전 {req.base_revision}이 최신 {rev}와 다르다 — 최신을 불러온 뒤 반영한다",
            "head": rev})
    built = build_profile(doc, validated=True)
    if built.fingerprint != echo.get("fingerprint"):
        raise HTTPException(status_code=409, detail=
                            "설계가 잰 문서와 지금 문서가 다르다(지문 불일치) — 자동 설계를 다시 돌린 뒤 반영한다")
    new = copy.deepcopy(doc)
    new["law"]["gain_tables"] = {
        "tables": copy.deepcopy(tables),
        "provenance": {
            # result_id는 휘발 결과 저장소를 가리킨다(보존 상한에 밀릴 수 있음) — 시각이 함께 있어야
            # 결과가 사라진 뒤에도 표의 시간 앵커가 남는다
            "source": "auto_design", "result_id": result_id, "base_revision": rev,
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "resample_tol": export.get("resample_tol"),
            "resample_error": copy.deepcopy(export.get("resample_error") or {}),
            # 판정 공간의 재검증 요약 — 게인 공간 오차(위)와 나란히. 결과가 보존 상한에
            # 밀려 사라져도 "채택 표로 재판정했더니 몇 곳이 움직였나"는 문서에 남는다
            "reverify": _reverify_summary(export.get("reverify")),
            # 낡음 판정의 기준 — 표 절을 뺀 지금 문서의 지문 (build.gain_tables_stale이 대조)
            "basis_fingerprint": gain_tables_basis_fingerprint(built.doc),
        },
    }
    try:
        _, new_rev = profiles.update(pid, new, rev)
    except ProfileReadOnly as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ProfileConflict as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "head": e.head})
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    return {"written": True, "revision": new_rev, "profile_id": pid, "slots": sorted(tables)}


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
                            parent=result_id, profile=resolve_snapshot(request, payload.get("profile")))
