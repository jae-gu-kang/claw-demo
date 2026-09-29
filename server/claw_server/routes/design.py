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
import dataclasses
from datetime import datetime, timezone

from claw.design import AutoDesignConfig, DesignSession, design_inputs, resample_to_table
from claw.design.grid import DEFAULT_ALTS, DEFAULT_FUEL_FRACS
from claw.design.tune import REASON_TEXT
from claw.profile import ProfileError, build_profile
from claw.profile.fingerprint import gain_tables_basis_fingerprint
from claw_server.profiles import EXAMPLE_ID, ProfileConflict, ProfileReadOnly, ProfileUnreadable
from claw_server.refs import (REQUEST_CRITERIA_REJECTED, ProfileRef, criteria_echo, profile_echo, profile_error_detail, resolve_criteria,
                              resolve_profile, resolve_snapshot)
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
# 없음(null)이 뜻을 갖는 수치 — 작동기 동특성은 null이면 **기체 문서의 작동기**다(엔진
# AutoDesignConfig 주석). 수치를 주면 그 값이 이긴다(작동기 가정 연구). n_mach는 null이면 요구영역의 기본 격자
# 명세(operating_region.base_grid — 05 §11.13 이관 2단계), 요구영역이 없으면 엔진의 옛 격자 기본값이다
_NULLABLE_KEYS = ("actuator_wn", "actuator_zeta", "n_mach")


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


def _build_config(overrides: dict, profile_criteria=None) -> AutoDesignConfig:
    """요청 config(부분 덮어쓰기) → AutoDesignConfig.

    바탕은 엔진 기본값이되 **판정선(criteria)·튜닝 목표(targets)는 기체 프로파일의 기준**
    (`profile_criteria` = GainEvalCriteria — 그 margin·targets)이다 (기준 통합 ① S3a). 없으면
    (테스트 등) 엔진 기본값 그대로다. 요청의 criteria·targets는 거절한다(S3b, v1.54) — 재개는 저장된
    세션 설정을 그대로 쓰므로 이 함수를 거치지 않는다."""
    base = AutoDesignConfig().to_dict()
    if profile_criteria is not None:
        base["criteria"] = profile_criteria.margin.to_dict()
        base["targets"] = profile_criteria.targets.to_dict()
    unknown = sorted(set(overrides) - set(base))
    if unknown:
        raise ValueError(f"미정의 config 키 {unknown} — 허용: {sorted(base)}")
    if "criteria" in overrides or "targets" in overrides:
        # 라우트가 먼저 거절한다 — 여기 닿으면 새 호출 경로가 거절을 건너뛴 것이다(심층 방어)
        raise ValueError(REQUEST_CRITERIA_REJECTED)
    merged = {**base, **overrides}
    # 타입 검증 — 데이터클래스는 강제 변환을 하지 않으므로 여기서 걸러야 한다.
    # 안 걸리는 값은 잡 스레드 안에서 터져 202 뒤 원인 없는 실패가 된다
    for key, want in (("mode", str), ("fit_mode", str),
                      ("alts", (list, type(None))), ("fuels", (list, type(None))),
                      ("sched_axes", list)):
        if not isinstance(merged[key], want):
            raise ValueError(f"{key} 타입 오류: {type(merged[key]).__name__}")
    # 축 이름은 문자열이어야 한다 — 범위(허용 축·중복)는 엔진 __post_init__이 판정한다
    if not all(isinstance(a, str) for a in merged["sched_axes"]):
        raise ValueError(f"sched_axes는 축 이름(문자열) 목록이어야 함: {merged['sched_axes']!r}")
    for key, value in merged.items():
        # 문자열·목록 필드는 수치 검사 대상이 아니다 — 값의 허용 목록은 엔진 __post_init__이
        # 본다(ValueError → 422). 여기 목록에 새 문자열 필드를 빠뜨리면 _check_number가
        # "수치여야 함"으로 422를 내어, 멀쩡한 설정이 거부된다
        if key in ("mode", "fit_mode", "alts", "fuels", "sched_axes", "criteria", "targets"):
            continue
        if key in _NULLABLE_KEYS and value is None:
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

    **표 모드(config.fit_mode="table")에서는 전 자리가 그 비다항 경로**다 — 재양자화가
    없으니 게인 공간 오차도 0이고, 판정 공간도 세션 검증이 그대로 반출 표의 검증이다
    (엔진 `reverify_resampled`가 `_same_tables`로 짚어 사유와 함께 인용한다). 그래도
    두 필드를 계속 싣는다: 반출 계약의 형상이 표현에 따라 갈리면 화면·문서 provenance가
    표현별로 분기해야 하고, "오차 0"과 "필드 없음"은 읽는 사람에게 다른 말이다.
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


def _config_criteria_echo(profile, cfg: AutoDesignConfig, source: str) -> dict:
    """실제로 쓴 config의 기준 블록 — 프로파일 기준 한 벌에서 margin·targets만 config 것으로 바꿔 지문을 잰다.
    자동 설계가 판정·튜닝에 쓰는 것은 그 둘이고, 요청 덮어쓰기가 있었다면 지문이 그것을 반영해야 한다."""
    crit = dataclasses.replace(profile.eval_criteria, margin=cfg.criteria, targets=cfg.targets)
    return criteria_echo(crit, source)


def _save_session(store, job, session: DesignSession, fingerprint: str,
                  parent: str | None = None, *, profile, criteria: dict) -> None:
    """criteria — 기준 블록(criteria_echo). 부르는 쪽이 판정·튜닝에 **실제로 쓴** 설정에서 재 넘긴다(제출·재개가
    출처를 안다) — 여기서 기체 기준으로 다시 재면 재개 세션의 저장된 설정과 어긋날 수 있다."""
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
    # 어느 기준으로 판정·튜닝했나 — profile 블록과 따로 둔다(refs.criteria_echo 머리말)
    payload["criteria_echo"] = criteria
    store.save(
        job.id,
        to_jsonable(payload),
        meta={
            "kind": "auto_design",
            "profile": profile_echo(profile),
            "criteria_echo": criteria,
            "created": job.created,
            "status": session.status,
            "stage": session.stage,
            "fingerprint": fingerprint,
            "parent": parent,
        },
    )
    job.result_id = job.id


def _run_session_job(request, response, session: DesignSession, fingerprint: str,
                     parent: str | None = None, *, profile, criteria: dict) -> dict:
    store = request.app.state.store
    try:
        # 기체가 주는 값 전부 — 한 경로(엔진 design_inputs)에서 뽑는다:
        # - 게인 미설계 기체는 202 전에 422다 — 튜너 브래킷이 설계값에서 나오므로(05 §7.4) 잡을
        #   받아 봐야 전 자리 seed_required고, detail.path(/law/design)가 웹의 「기체 탭 → 초기
        #   게인」 안내 링크 근거가 된다. 종전에는 여기서 잡히지 않아 500이었다
        # - 법칙의 레이트 필터 — 안 넘기면 튜닝·검증이 출하되지 않는 조성(요축 워시아웃 없는
        #   A′)을 본다 (05 §6)
        # - 기체 작동기(wn·zeta) — 종전에는 넘기지 않아 config의 30·0.7이 늘 이겼다. 이제
        #   config가 없음(null)이면 기체 문서 값이다
        inp = design_inputs(profile)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    try:
        # COARSE 격자 사전 검사 — 행 끝점(요구 경계)이 COARSE 몫을 넘거나 명세 덮음이 기본 격자 상한을 넘으면 잡 안에서
        # 처음 터지던 ValueError를 202 전에 422로 낸다(엔진 grid.select_coarse 「제출 시점에 거부」). 재개는 건너뛴다
        session.preflight(inp["verdict_ctx"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    def work(job):
        # job.report의 반환값이 취소 요청 여부 — 엔진 협조적 취소 규약과 그대로 맞물린다
        session.run(
            inp["aircraft"], inp["stall_table"], inp["limits"], inp["db_ranges"], inp["design"],
            # 조건 판정 문맥(05 §11.3 · 이관 8단계) — 트림 탭과 같은 생성자로 만든 기체 값. 재개도 이 길이다
            verdict_ctx=inp["verdict_ctx"], rate_filters=inp["rate_filters"], actuator=inp["actuator"],
            fingerprint=fingerprint,
            on_progress=lambda done, total, msg: job.report(done, total, message=msg),
        )
        _save_session(store, job, session, fingerprint, parent=parent, profile=profile, criteria=criteria)

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
        # alts·fuels를 비웠을 때 coarse 격자가 실제로 쓰는 값 — 고도 목록과 연료 **비율**(× 기체
        # fuel_max). 비율로 내는 것은 기체 값이 여기 없기 때문이다(연료 kg은 웹이 문서에서 곱한다)
        "grid": {"alts": [float(a) for a in DEFAULT_ALTS],
                 "fuel_fracs": [float(f) for f in DEFAULT_FUEL_FRACS]},
    }


@router.post("/design/auto", status_code=202)
def submit_auto_design(req: AutoDesignIn, request: Request, response: Response) -> dict:
    # 기준은 기체 프로파일에서 온다 — 판정선·튜닝 목표의 바탕이 그 기체의 /criteria·/tuning이다
    profile = resolve_profile(request, req.profile)
    base_crit, source = resolve_criteria(profile)
    if "criteria" in req.config or "targets" in req.config:
        # 요청 판정선·목표는 거절한다(기준 통합 ① S3b) — 같은 기체의 설계가 요청마다 다른 기준이면 탭마다 판정이 갈린다
        raise HTTPException(status_code=422, detail=REQUEST_CRITERIA_REJECTED)
    try:
        cfg = _build_config(req.config, base_crit)
    except (ValueError, TypeError) as e:
        # 데이터클래스는 값을 강제 변환하지 않는다 — 타입이 틀린 스칼라는 __post_init__의
        # 비교에서 TypeError로 나온다. 형제 라우트(sim·codegen·influence)와 같은 정책으로
        # 422에 매핑한다 (놓치면 500)
        raise HTTPException(status_code=422, detail=str(e))
    return _run_session_job(request, response, DesignSession(cfg), req.fingerprint, profile=profile,
                            criteria=_config_criteria_echo(profile, cfg, source))


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


def _design_summary(rep: dict | None) -> dict:
    """자동 설계 보고 → provenance.design 요약 — 판정 개수와 **표현·적합에서 뺀 표본 수**.

    표 표현에서 뺀 표본(튜닝이 성립하지 않은 점)의 분할점 값은 튜닝값이 아니라 이웃 보간이고, 보류된 자리는 실패
    표본을 담은 채다 — 결과가 보존 상한에 밀려 사라져도 문서의 표가 그 사실을 들고 있어야 한다. 목록은 개수로
    접는다(_reverify_summary와 같은 이유 — 문서가 결과 저장물을 복제하지 않는다). 판정 칸 이름(status…
    escalations)은 생성기(claw.profile.showcase)가 적는 design 요약과 같다. 옛 결과라 칸이 없으면 None — 0으로
    위장하지 않는다."""
    rep = rep or {}
    excluded = rep.get("excluded_samples")
    withheld = rep.get("exclusion_withheld")
    return {
        "status": rep.get("status"), "iterations": rep.get("iterations"), "judged": rep.get("judged"),
        "failures": rep.get("failures"), "escalations": rep.get("escalations"),
        "fit_mode": rep.get("fit_mode"),
        "excluded_samples": len(excluded) if isinstance(excluded, list) else None,
        "exclusion_withheld": sorted(withheld) if isinstance(withheld, list) else None,
    }


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
    - 마하 아닌 축 표는 문서가 못 담는다(422, detail {message, off_axis} — 자리·축을 짚는다)
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
    # 문서 스키마 v2의 확정 게인 표는 **마하 축 표만** 보유한다(profile/schema.py `_table_mach`).
    # 자동 설계는 기본으로 마하로만 스케줄하지만(AutoDesignConfig.sched_axes — 적합 축 후보를
    # 좁힌다, 표현 fit_mode와 무관), 그 전에 저장된 결과(지배 축 자유 선택)나 API로 sched_axes를
    # 넓힌 결과는 고도·연료 축 표를 가질 수 있다. 그대로 저장을 시도해도 아래 ProfileError 매핑이
    # 받아 422이긴 하나, 그 사유는 스키마 경로(`/law/gain_tables/tables/…/axes` 키 불일치)뿐이라
    # **어느 자리가 왜 다른 축인지**를 말하지 않는다. detail은 {message, off_axis}다 — message가
    # 자리·축을 짚으므로 웹 errorText(profileErrorText → message)가 그대로 보이고, off_axis는
    # 기계 판독용 {자리: [축]}이다
    off_axis = {slot: sorted((spec.get("axes") or {}))
                for slot, spec in tables.items()
                if sorted((spec.get("axes") or {})) != ["mach"]}
    if off_axis:
        raise HTTPException(status_code=422, detail={
            "message": "문서의 확정 게인 표는 마하 축만 보유할 수 있다 — "
                       + " · ".join(f"{s}: {'+'.join(ax) or '축 없음'}"
                                    for s, ax in sorted(off_axis.items()))
                       + ". 그 자리는 마하가 아닌 축으로 스케줄됐다 — sched_axes를 마하로 두고(기본)"
                       " 자동 설계를 다시 돌린 뒤 반영한다 (다축 게인 표는 백로그 — 05 §9)."
                       " 막히는 것은 문서 반영이다: 시뮬·코드 생성은 그 축 표를 받고(런타임 스케줄"
                       " 변수는 mach·alt·fuel), 게인 탭 편집 표는 축이 어긋난다고 알린다",
            "off_axis": off_axis})
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
            # 이 표를 만든 설계의 요약 — 표현(fit_mode)과 적합에서 뺀 표본 수(그 점은 이웃 보간이다)
            "design": _design_summary(payload.get("report")),
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
    # 재개는 저장된 세션 config(판정선·목표 포함)를 그대로 쓴다 — 기준을 다시 풀지 않는다. 그래서 기준 블록도
    # 저장된 것을 그대로 잇는다(출처 보존). 블록이 없는 옛 결과는 저장 config로 재되 출처는 "snapshot"이다 —
    # 스냅숏 기체의 나머지 기준 그룹이 그 결과를 낸 기준이라는 보장이 없다(refs.resolve_criteria 머리말)
    profile = resolve_snapshot(request, payload.get("profile"))
    criteria = payload.get("criteria_echo") or _config_criteria_echo(profile, session.config, "snapshot")
    return _run_session_job(request, response, session, req.fingerprint,
                            parent=result_id, profile=profile, criteria=criteria)
