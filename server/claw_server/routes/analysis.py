"""마진 맵 라우트 (02 §8 워크플로우 3단계) — 트림점별 선형화 → 안정성·마진 수치.

엔진 호출 연쇄: trim_batch → linearize → split_axes → damp/classify →
pi_loop+loop_margins. 루프 정의(축·입출력·PI 게인·부호)는 요청이 보유하고
서버는 엔진 축 이름으로 검증만 한다 — 마진 산출 자체는 전부 M10 소관.
격자 시각화는 M14(web) 소관 (01 §4.2).
"""

from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator

from claw.analysis import (
    classify_lat,
    classify_lon,
    damp,
    loop_margins,
    pi_loop,
    vn_envelope,
)
from claw.plant import (
    make_demo_aircraft,
    make_demo_stall_table,
    make_demo_structural_limits,
)
from claw.trim import (
    LAT_INPUTS,
    LAT_STATES,
    LON_INPUTS,
    LON_STATES,
    linearize,
    split_axes,
    trim_batch,
)
from claw_server.routes.trim import FiniteFloat, TrimCaseIn, build_cases
from claw_server.serialize import to_jsonable, trim_result_dict

router = APIRouter(tags=["analysis"])

_AXIS_NAMES = {
    "lon": (LON_STATES, LON_INPUTS),
    "lat": (LAT_STATES, LAT_INPUTS),
}


class LoopIn(BaseModel):
    """PI 개루프 스펙 — 마진 맵의 루프 정의 (설계값은 요청이 보유)."""

    name: str = Field(min_length=1)
    axis: Literal["lon", "lat"] = "lon"
    x_out: str = "q"
    u_in: str = "de"
    kp: FiniteFloat
    ki: FiniteFloat = 0.0
    sign: FiniteFloat = -1.0

    @model_validator(mode="after")
    def _check_axis_names(self):
        states, inputs = _AXIS_NAMES[self.axis]
        if self.x_out not in states:
            raise ValueError(f"{self.axis}축에 없는 상태: {self.x_out} (허용: {states})")
        if self.u_in not in inputs:
            raise ValueError(f"{self.axis}축에 없는 입력: {self.u_in} (허용: {inputs})")
        if self.sign == 0.0 or (self.kp == 0.0 and self.ki == 0.0):
            raise ValueError("무의미 루프 (제로 개루프): sign=0 또는 kp=ki=0")
        return self


class ActuatorIn(BaseModel):
    """마진 계산용 작동기 동특성 (01 §4.2 [기본값] — plant.actuator.SecondOrderActuator와
    동일 2차계 wn²/(s²+2ζωn·s+wn²) 재사용, 레이트/위치 한계는 소신호 해석 제외)."""

    wn: FiniteFloat = Field(gt=0.0)
    zeta: FiniteFloat = Field(gt=0.0)


class MarginMapIn(BaseModel):
    aircraft: Literal["demo"] = "demo"
    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1)
    loops: list[LoopIn] = []
    # 작동기·지연 포함은 [기본값] 미포함(하위호환) — 포함이 01 §4.2 문서 기본값이지만
    # 그건 웹 폼 초기 상태의 몫이고 서버 계약은 중립 유지 (엔진 pi_loop과 동일 원칙)
    actuator: ActuatorIn | None = None
    delay_s: FiniteFloat = Field(default=0.0, ge=0.0)
    pade_order: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def _unique_loop_names(self):
        names = [lp.name for lp in self.loops]
        if len(names) != len(set(names)):
            raise ValueError(f"루프 이름 중복: {names}")
        return self


def _axis_block(model, classify_fn) -> dict:
    """축 부분모델 → 고유치 원자료 + 자동 분류 (비정형 구조는 note로 보고)."""
    block = {"modes": to_jsonable(damp(model.A))}
    try:
        block["classified"] = to_jsonable(classify_fn(model))
        block["note"] = None
    except ValueError as e:  # 실근 분리 등 비정형 — 데이터이지 실패가 아님
        block["classified"] = None
        block["note"] = str(e)
    return block


def _trim_only_entry(tr) -> dict:
    return {
        "trim": trim_result_dict(tr),
        "lon": None,
        "lat": None,
        "margins": {},
        "note": None,
    }


@router.get("/analysis/vn-envelope")
def vn_envelope_endpoint(
    alt: float = Query(...),
    fuel: float = Query(ge=0.0),
    alpha_margin: float = Query(default=0.05, ge=0.0),  # α 리미터 [기본값]과 동일
    neg_alpha_ratio: float = Query(default=0.6, gt=0.0, le=1.0),  # 음의 실속 자리표시 비율
) -> dict:
    """V-n 선도 (01 §3.6) — 실속·보호 곡선 + 구조 한계선 + 특성 속도 (동기 계산).

    구조 한계는 비행체 프로파일의 자리표시 [기본값](실기체 값 아님) — 정본
    확보 시 프로파일 교체. 음의 실속 곡선도 자리표시(−ratio×α_stall, 엔진이
    ratio echo). 표기는 웹 소관.
    """
    ac = make_demo_aircraft()
    try:
        env = vn_envelope(
            ac,
            make_demo_stall_table(),
            make_demo_structural_limits(),
            alt=alt,
            fuel=fuel,
            alpha_margin=alpha_margin,
            neg_alpha_ratio=neg_alpha_ratio,
        )
    except (ValueError, TypeError) as e:  # ISA 범위 밖 고도 등 — 엔진 검증
        raise HTTPException(status_code=422, detail=str(e))
    env["alt"] = alt
    env["fuel"] = fuel
    env["alpha_margin"] = alpha_margin
    env["limits_source"] = "demo-placeholder"  # 실기체 값 아님 — 웹이 명기 표시
    return env


@router.post("/analysis/margin-map", status_code=202)
def submit_margin_map(req: MarginMapIn, request: Request, response: Response) -> dict:
    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    store = request.app.state.store
    n = len(cases)
    total = 2 * n  # 트림 패스 + 해석 패스

    def work(job):
        trs = trim_batch(
            ac,
            cases,
            fingerprint=req.fingerprint,
            on_progress=lambda done, _t, tr: job.report(
                done, total, message=f"트림: {tr.case.name}"
            ),
        )
        entries = []
        for i, tr in enumerate(trs):
            if job.cancel_requested:
                # 취소 — 계산 완료된 나머지 트림 결과를 해석 생략 entry로
                # 전량 보존 (리뷰 S1: 유실 금지)
                entries.extend(_trim_only_entry(t) for t in trs[i:])
                break
            entry = _trim_only_entry(tr)
            if tr.converged:
                try:
                    lon, lat = split_axes(linearize(ac, tr))
                    entry["lon"] = _axis_block(lon, classify_lon)
                    entry["lat"] = _axis_block(lat, classify_lat)
                    for spec in req.loops:
                        model = lon if spec.axis == "lon" else lat
                        loop = pi_loop(
                            model, x_out=spec.x_out, u_in=spec.u_in,
                            kp=spec.kp, ki=spec.ki, sign=spec.sign,
                            actuator_wn=req.actuator.wn if req.actuator else None,
                            actuator_zeta=req.actuator.zeta if req.actuator else None,
                            delay_s=req.delay_s, pade_order=req.pade_order,
                        )
                        entry["margins"][spec.name] = to_jsonable(loop_margins(loop))
                except ValueError as e:  # 케이스별 해석 실패 — 전량 소실 대신 데이터로
                    entry["note"] = str(e)
            entries.append(entry)
            job.report(n + i + 1, total, message=f"해석: {tr.case.name}")
        store.save(
            job.id,
            {
                "kind": "margin_map",
                "cases": entries,
                "loops": [lp.model_dump() for lp in req.loops],
                "actuator": req.actuator.model_dump() if req.actuator else None,
                "delay_s": req.delay_s,
                "pade_order": req.pade_order,
                "n_requested": n,
            },
            meta={
                "kind": "margin_map",
                "created": job.created,
                "n": len(entries),
                "fingerprint": req.fingerprint,
            },
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("margin_map", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()
