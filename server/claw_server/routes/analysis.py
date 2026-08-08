"""마진 맵 라우트 (02 §8 워크플로우 3단계) — 트림점별 선형화 → 안정성·마진 수치.

엔진 호출 연쇄: trim_batch → linearize → split_axes → damp/classify →
pi_loop+loop_margins. 루프 정의(축·입출력·PI 게인·부호)는 요청이 보유하고
서버는 엔진 축 이름으로 검증만 한다 — 마진 산출 자체는 전부 M10 소관.
격자 시각화는 M14(web) 소관 (01 §4.2).
"""

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, model_validator

from claw.analysis import classify_lat, classify_lon, damp, loop_margins, pi_loop
from claw.plant import make_demo_aircraft
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


class MarginMapIn(BaseModel):
    aircraft: Literal["demo"] = "demo"
    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1)
    loops: list[LoopIn] = []

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
