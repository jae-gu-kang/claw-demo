"""마진 맵 라우트 (02 §8 워크플로우 3단계) — 트림점별 선형화 → 안정성·마진 수치.

엔진 호출 연쇄: trim_batch → linearize → split_axes → damp/classify →
pi_loop+loop_margins. 루프 정의(축·입출력·PI 게인·부호)는 요청이 보유하고
서버는 엔진 축 이름으로 검증만 한다 — 마진 산출 자체는 전부 M10 소관.
격자 시각화는 M14(web) 소관 (01 §4.2).
"""

import math
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator

from claw.analysis import (
    aero_envelope,
    bode_data,
    classify_lat,
    classify_lon,
    damp,
    design_envelope,
    loop_margins,
    omega_covering,
    pi_loop,
    vn_envelope,
)
from claw.fcl.demo import demo_rate_filters
from claw.pipeline.openloop import GROUP_LOOPS
from claw.design.points import envelope_verdict
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_stall_table,
    make_demo_structural_limits,
)
from claw.trim.trim import ALPHA_BOUNDS
from claw.trim import trim_level
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


# 마진 탭 루프 → 스케줄 그룹. 대응 **선언의 정본은 pipeline.openloop.GROUP_LOOPS**
# ("유도가 아니라 선언이다" — 그 머리말이 레이트 루프 3개가 웹 마진 탭 DEFAULT_LOOPS와
# 정합임을 못박고 test_openloop이 핀한다). 여기서는 역인덱스만 만든다 — 대응을 다시
# 적으면 두 곳이 갈리고, 갈려도 화면에는 그럴듯한 곡선이 나와 티가 안 난다.
# **필터 선언은 그룹이 아니라 루프 자리에 달려 있다** — yaw_rate는 filter 항을
# 갖고 pitch_att는 안 갖는다(openloop._effective_filter도 sp.get("filter")를 읽는다).
# 그룹만 키로 쓰면 DEMO_PITCH에 washout_tau가 켜지는 날 **자세 루프**가 선언에 없는
# 레이트 워시아웃을 얻고, 그 사유 문장은 사실과 반대를 말하게 된다.
_LOOP_GROUP = {
    (d["axis"], d["x_out"], d["u_in"]): (group, d.get("filter"))
    for group, decls in GROUP_LOOPS.items()
    for d in decls
}


def _compose_loop(model, spec, actuator, delay_s, pade_order, rate_filter=None):
    """루프 스펙 + 작동기·지연 → 개루프 — 마진 맵과 보드선도의 **공용 조립**.

    두 곳이 따로 조립하면 곡선과 클릭한 칸의 수가 어긋난다. 어긋나도 화면에는
    둘 다 그럴듯하게 보이므로(값이 조금 다를 뿐) 조립은 한 곳에만 적는다.
    rate_filter는 **마진 맵 경로에서 항상 None**이다 — 히트맵이 법칙의 필터를 안
    본다는 01 §4.2 [한계]를 보드선도가 몰래 바꾸면 칸의 수와 곡선이 어긋난다.
    보드선도는 그 차이를 없애는 대신 **두 곡선으로 보여준다**(아래 bode_endpoint).
    """
    return pi_loop(
        model, x_out=spec.x_out, u_in=spec.u_in,
        kp=spec.kp, ki=spec.ki, sign=spec.sign,
        actuator_wn=actuator.wn if actuator else None,
        actuator_zeta=actuator.zeta if actuator else None,
        delay_s=delay_s, pade_order=pade_order,
        rate_filter=rate_filter,
    )


def _trim_only_entry(tr) -> dict:
    return {
        "trim": trim_result_dict(tr),
        "lon": None,
        "lat": None,
        "margins": {},
        "note": None,
    }


def _assemble_limits(
    n_limit_pos=None, n_limit_neg=None, safety_factor=None, mach_no=None, mach_d=None,
) -> tuple:
    """데모 구조 한계 + 사용자 오버라이드 조립 — (limits, source, overridden).

    기본값 재기술 금지(02 §5.5): None은 데모 프로파일이 채우고, 서버는 어느
    필드가 사용자 값인지(overridden)와 출처(source)만 echo. 값 검증(부호·서열)은
    엔진 _check_limits 몫 — 서버는 경계 유한성만 (allow_inf_nan).
    """
    limits = make_demo_structural_limits()
    overrides = {
        "n_limit_pos": n_limit_pos,
        "n_limit_neg": n_limit_neg,
        "safety_factor": safety_factor,
        "mach_no": mach_no,
        "mach_d": mach_d,
    }
    overridden = [k for k, v in overrides.items() if v is not None]
    limits.update({k: overrides[k] for k in overridden})
    source = "user-input" if overridden else "demo-placeholder"
    return limits, source, overridden


MAX_ISO_VALUES = 20  # 등고선 개수 상한 — MAX_SCAN_CASES와 같은 지위 (아래 참조)


def _num_list(raw, label) -> list | None:
    """콤마 구분 수 목록 → list[float]. None/빈 문자열이면 None (= 엔진 기본값).

    등고선 값처럼 개수가 정해지지 않은 입력의 쿼리 표현. 비유한값은 422 —
    다른 수치 파라미터의 allow_inf_nan=False와 같은 지위다.

    개수 상한은 MAX_SCAN_CASES·MAX_POINTS·MAX_CASES와 같은 이유다("오타 격자의
    단일 워커 점유 차단"): 값 하나가 표시 고도 41행마다 대기 계산을 돌리고 응답에
    41개 수를 더한다. 상한 없이는 15 KB 쿼리 하나가 2.4 MB 응답과 4배 처리시간이
    되어(실측) 단일 워커를 물고 늘어진다 — 공격이 아니라 CSV 한 열을 붙여넣는
    실수로 충분히 닿는다. 20이면 사람이 읽을 수 있는 곡선 수를 넉넉히 넘는다.
    """
    if raw is None or not raw.strip():
        return None
    toks = raw.split(",")
    if len(toks) > MAX_ISO_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"{label} 개수 상한 {MAX_ISO_VALUES} 초과: {len(toks)}개",
        )
    out = []
    for tok in toks:
        try:
            v = float(tok)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{label}가 숫자 목록이 아님: {tok.strip()!r}")
        if not math.isfinite(v):
            raise HTTPException(status_code=422, detail=f"{label}는 유한값이어야 함: {tok.strip()!r}")
        out.append(v)
    return out


@router.get("/analysis/vn-envelope")
def vn_envelope_endpoint(
    alt: float = Query(..., allow_inf_nan=False),
    fuel: float = Query(ge=0.0, allow_inf_nan=False),  # inf는 fuel_max로 조용히 잘려 거짓 echo가 된다
    alpha_margin: float = Query(default=0.05, ge=0.0, allow_inf_nan=False),  # α 리미터 [기본값]과 동일
    neg_alpha_ratio: float = Query(default=0.6, gt=0.0, le=1.0),  # 음의 실속 자리표시 비율
    # 구조 한계 오버라이드 — None = 데모 프로파일이 채움 (기본값 재기술 금지, 02 §5.5)
    n_limit_pos: float | None = Query(default=None, allow_inf_nan=False),
    n_limit_neg: float | None = Query(default=None, allow_inf_nan=False),
    safety_factor: float | None = Query(default=None, allow_inf_nan=False),
    mach_no: float | None = Query(default=None, allow_inf_nan=False),
    mach_d: float | None = Query(default=None, allow_inf_nan=False),
) -> dict:
    """V-n 선도 (01 §2.6·§3.6) — 실속·보호 곡선 + 구조 한계선 + 특성 속도 (동기 계산).

    구조 한계는 비행체 프로파일의 자리표시 [기본값](실기체 값 아님)에 사용자
    오버라이드를 얹는다(필요값 입력, 01 §2.6) — limits_source·limits_overridden
    echo. 음의 실속 곡선도 자리표시(−ratio×α_stall, 엔진이 ratio echo).
    표기는 웹 소관.
    """
    ac = make_demo_aircraft()
    limits, source, overridden = _assemble_limits(
        n_limit_pos, n_limit_neg, safety_factor, mach_no, mach_d
    )
    try:
        env = vn_envelope(
            ac,
            make_demo_stall_table(),
            limits,
            alt=alt,
            fuel=fuel,
            alpha_margin=alpha_margin,
            neg_alpha_ratio=neg_alpha_ratio,
        )
    except (ValueError, TypeError) as e:  # ISA 범위 밖 고도·한계 서열 위반 등 — 엔진 검증
        raise HTTPException(status_code=422, detail=str(e))
    env["alt"] = alt
    env["fuel"] = fuel
    env["alpha_margin"] = alpha_margin
    env["limits_source"] = source  # demo-placeholder = 실기체 값 아님 — 웹이 명기 표시
    env["limits_overridden"] = overridden
    return env


@router.get("/analysis/design-envelope")
def design_envelope_endpoint(
    fuel: float = Query(ge=0.0, allow_inf_nan=False),  # inf는 fuel_max로 조용히 잘려 거짓 echo가 된다
    q_max: float | None = Query(default=None, allow_inf_nan=False),
    alt_min: float | None = Query(default=None, allow_inf_nan=False),
    alt_max: float | None = Query(default=None, allow_inf_nan=False),
    mach_margin: float | None = Query(default=None, allow_inf_nan=False),
    alpha_margin: float = Query(default=0.05, ge=0.0, allow_inf_nan=False),  # 공력 보호선 — α 리미터 [기본값]과 동일
    nz: float | None = Query(default=None, gt=0.0, allow_inf_nan=False),  # 기동 엔벨로프 하중배수
    iso_qbar: str | None = Query(default=None),  # 콤마 구분 [Pa] — None이면 엔진 [기본값]
    iso_tas: str | None = Query(default=None),  # 콤마 구분 [m/s]
    # 구조 한계 오버라이드 — vn-envelope와 같은 계약 (None = 데모 프로파일)
    n_limit_pos: float | None = Query(default=None, allow_inf_nan=False),
    n_limit_neg: float | None = Query(default=None, allow_inf_nan=False),
    safety_factor: float | None = Query(default=None, allow_inf_nan=False),
    mach_no: float | None = Query(default=None, allow_inf_nan=False),
    mach_d: float | None = Query(default=None, allow_inf_nan=False),
) -> dict:
    """설계 엔벨로프 M-h 합성 + 공력 선도 데이터 (01 §2.6, 동기 계산).

    합성·귀속·좌표는 전부 엔진(design_envelope·aero_envelope) — 서버는 데모
    프로파일 조립과 비-None 전달만 (기본값 재기술 금지, 02 §5.5). q_max·운용
    고도는 실기체 값이라 미지정이면 경계 자체가 없다(엔진이 null echo).
    trim_alpha_bounds는 trim 상수 정본을 조립 시점에 주입 (같은 L4 계층이라
    엔진 analysis가 직접 import하지 않는다 — 03 §2 계층 규칙).

    nz·iso_qbar·iso_tas도 같은 계약 — 미지정이면 전달하지 않고 엔진이 정한다
    (기동 엔벨로프는 아예 없는 것, 등고선은 엔진 [기본값]).
    """
    ac = make_demo_aircraft()
    stall = make_demo_stall_table()
    db_ranges = make_demo_db_ranges()
    limits, source, overridden = _assemble_limits(
        n_limit_pos, n_limit_neg, safety_factor, mach_no, mach_d
    )
    kwargs = {
        k: v
        for k, v in dict(
            q_max=q_max, alt_min=alt_min, alt_max=alt_max, mach_margin=mach_margin,
            nz=nz, iso_qbar=_num_list(iso_qbar, "iso_qbar"),
            iso_tas=_num_list(iso_tas, "iso_tas"),
        ).items()
        if v is not None
    }
    try:
        env = design_envelope(ac, stall, limits, db_ranges, fuel=fuel, **kwargs)
        env["aero"] = aero_envelope(
            stall, db_ranges, alpha_margin=alpha_margin, trim_alpha_bounds=ALPHA_BOUNDS
        )
    except (ValueError, TypeError) as e:  # ISA 범위·서열 위반 등 — 엔진 검증
        raise HTTPException(status_code=422, detail=str(e))
    env["limits"] = limits
    env["limits_source"] = source
    env["limits_overridden"] = overridden
    return to_jsonable(env)


MAX_SCAN_CASES = 200  # 영향성 라우트 MAX_CASES와 같은 지위 — 오타 격자의 단일 워커 점유 차단


class EnvelopeScanIn(BaseModel):
    """제어 가능 영역 스캔 — 케이스 격자 트림 + envelope_ok 판정 (01 §2.6)."""

    aircraft: Literal["demo"] = "demo"
    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1, max_length=MAX_SCAN_CASES)


@router.post("/analysis/design-envelope-scan", status_code=202)
def submit_envelope_scan(req: EnvelopeScanIn, request: Request, response: Response) -> dict:
    """설계 엔벨로프의 제어 가능 영역 — 격자 트림 잡 (마진 맵과 같은 202 골격).

    점별 판정은 엔진 envelope_verdict(envelope_ok 정본 + 사유 귀속) —
    saturated_throttle_high가 추진 한계의 대리 지표 (전용 추력 모델 [TBD]).
    취소는 trim_batch 협조적 중단 — 완료분 보존.
    """
    ac = make_demo_aircraft()
    cases = build_cases(req.cases)
    store = request.app.state.store

    def work(job):
        trs = trim_batch(
            ac,
            cases,
            fingerprint=req.fingerprint,
            on_progress=lambda done, total, tr: job.report(
                done, total, message=f"트림: {tr.case.name}"
            ),
        )
        entries = [
            {"trim": trim_result_dict(tr), "verdict": to_jsonable(envelope_verdict(tr))}
            for tr in trs
        ]
        store.save(
            job.id,
            {"kind": "envelope_scan", "cases": entries, "n_requested": len(cases)},
            meta={
                "kind": "envelope_scan",
                "created": job.created,
                "n": len(entries),
                "fingerprint": req.fingerprint,
            },
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("envelope_scan", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


class BodeIn(BaseModel):
    """단일 케이스·단일 루프의 보드선도 — 마진 맵 칸을 클릭했을 때의 상세.

    작동기·지연을 마진 맵과 같은 계약으로 받는 이유: 조립이 다르면 곡선에서 읽는
    값과 클릭한 칸의 수가 어긋난다. 호출측(웹)이 결과의 `actuator`/`delay_s`를
    그대로 실어 보내는 것이 전제다.
    """

    aircraft: Literal["demo"] = "demo"
    fingerprint: str = ""
    case: TrimCaseIn
    loop: LoopIn
    actuator: ActuatorIn | None = None
    delay_s: FiniteFloat = Field(default=0.0, ge=0.0)
    # 상한을 두지 않는다 — MarginMapIn과 같은 계약이어야 마진 맵이 칠한 칸을 여기서
    # 거절하는 모순이 안 생긴다. 계수가 넘치는 조합은 엔진 pi_loop이 이름으로 거절한다
    pade_order: int = Field(default=2, ge=1)
    n_points: int = Field(default=400, ge=50, le=2000)  # 상한 — 교차 탐색 격자 폭주 차단
    # 마진 맵이 이미 푼 트림의 해 [α, δe, δt] — **선형화점을 같게 만드는 수단**이다.
    # 마진 맵은 trim_batch가 직전 수렴해로 웜스타트하는데(trim.py, z0=z_prev — 웹이
    # serpentine 순서를 쓰는 이유가 그것) 여기서 냉간으로 다시 풀면 다른 점에 앉는다.
    # 실측: 같은 격자에서 M0.75는 마진이 어긋나고 M0.85는 **칸은 수렴인데 여기서만
    # 미수렴**이 나 422가 된다 — 색칠된 칸이 안 열리는 모순.
    z0: list[FiniteFloat] | None = Field(default=None, min_length=3, max_length=3)


@router.post("/analysis/bode")
def bode_endpoint(req: BodeIn) -> dict:
    """개루프 보드선도 (01 §4.2) — 트림 1건이라 동기 계산.

    GM과 PM은 같은 곡선의 서로 다른 자리에서 읽는 수라 히트맵 두 장으로는 둘의
    주파수 관계가 안 보인다. 이 응답이 같은 주파수축의 이득·위상과 **교차점 전량**을
    줘서 화면이 "보고된 마진이 어느 교차의 것인가"까지 말하게 한다 (엔진 bode_data).
    """
    ac = make_demo_aircraft()
    (case,) = build_cases([req.case])
    tr = trim_level(ac, case, z0=req.z0, fingerprint=req.fingerprint)
    if not tr.converged:
        # 트림이 없으면 선형화할 점이 없다 — 빈 곡선을 그려 정상인 척하지 않는다.
        # z0를 안 받으면 냉간 트림이라 마진 맵이 웜스타트로 푼 칸에서도 여기서만
        # 미수렴이 날 수 있다 — 그래서 호출자가 칸의 해를 씨앗으로 넘긴다
        raise HTTPException(
            status_code=422,
            detail=f"트림 미수렴 ({case.name}) — 선형화점이 없어 보드선도를 낼 수 없습니다"
            + ("" if req.z0 else " (칸의 트림 해를 z0로 넘기면 같은 점에서 풀립니다)"),
        )
    # 법칙이 이 자리에 실제로 가진 레이트 필터 — 있으면 두 번째 곡선으로 겹친다.
    # 마진 맵은 이것을 정적 게인으로 보므로(01 §4.2 [한계]) 그 차이가 곧 한계의 크기다.
    group, fdecl = _LOOP_GROUP.get((req.loop.axis, req.loop.x_out, req.loop.u_in), (None, None))
    # 선언이 있는 자리만 법칙 값을 읽는다 — 선언이 정본이고 값은 프로파일이 준다
    fspec = demo_rate_filters().get(group) if fdecl else None
    if fspec is None:
        filtered_note = (
            # 선언이 있는데 값이 0인 것과 선언 자체가 없는 것은 다른 사실이다 —
            # 뭉치면 읽는 사람이 이미 있는 선언을 추가하러 간다
            (f"'{group}' 그룹의 이 자리({req.loop.x_out}←{req.loop.u_in})는 필터를"
             " 선언하지만 이 프로파일에서 꺼져 있습니다(값 0) — 두 조립이 같습니다"
             if fdecl else
             f"'{group}' 그룹의 이 자리({req.loop.x_out}←{req.loop.u_in})에는 레이트 필터"
             " 선언이 없습니다 — 두 조립이 같습니다")
            if group else
            f"이 루프({req.loop.axis} {req.loop.x_out}←{req.loop.u_in})에 대응하는 법칙 자리"
            " 선언이 없어(pipeline.openloop.GROUP_LOOPS) 필터 반영 곡선을 낼 수 없습니다"
        )
    else:
        filtered_note = None
    try:
        lon, lat = split_axes(linearize(ac, tr))
        model = lon if req.loop.axis == "lon" else lat
        loop = _compose_loop(model, req.loop, req.actuator, req.delay_s, req.pade_order)
        floop = (
            _compose_loop(model, req.loop, req.actuator, req.delay_s, req.pade_order,
                          rate_filter=fspec)
            if fspec else None
        )
        # 겹쳐 비교하려면 같은 축이어야 한다 — 워시아웃 코너처럼 한쪽에만 있는 극이
        # 다른 쪽 범위 밖으로 나가면 그 교차를 통째로 놓친다
        w = omega_covering(*( [loop, floop] if floop else [loop] ), n_points=req.n_points)
        data = bode_data(loop, w=w)
        filtered = {**bode_data(floop, w=w), "filter": fspec} if floop else None
    except (ValueError, ArithmeticError) as e:
        # LinAlgError는 ValueError지만 **ZeroDivisionError는 아니다** — 고차 Padé에서
        # 분모 선두 계수가 0으로 내려앉으면 control이 나눗셈을 하고, 그것이 그대로
        # 500으로 샌다(사유도 힌트도 없이). ArithmeticError로 함께 잡는다.
        # 날것의 numpy 문장("Array must not contain
        # infs or NaNs")을 그대로 내보내면 사용자가 자기 입력이 잘못됐다고 읽는다.
        # 실제 원인은 delay_s·pade_order 조합이 커서 근 계산이 넘친 것이고(실측:
        # 0.001 s·20차는 죽고 0.01 s·20차는 산다), 그 조합은 마진 맵도 못 푼다
        detail = str(e)
        if req.delay_s > 0.0 and req.pade_order > 8:
            detail += (
                f" — delay_s {req.delay_s} s와 pade_order {req.pade_order}의 조합이"
                " 커서 Padé 계수의 근 계산이 넘쳤을 수 있습니다 (차수를 낮춰 보세요)"
            )
        raise HTTPException(status_code=422, detail=detail)
    return to_jsonable({
        **data,
        "filtered": filtered,
        "filtered_note": filtered_note,
        "trim": trim_result_dict(tr),
        "loop": req.loop.model_dump(),
        "actuator": req.actuator.model_dump() if req.actuator else None,
        "delay_s": req.delay_s,
        "pade_order": req.pade_order,
    })


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
                        loop = _compose_loop(
                            model, spec, req.actuator, req.delay_s, req.pade_order)
                        entry["margins"][spec.name] = to_jsonable(loop_margins(loop))
                except (ValueError, ArithmeticError) as e:
                    # 케이스별 해석 실패 — 전량 소실 대신 데이터로. ArithmeticError는
                    # 고차 Padé의 ZeroDivisionError 몫이다(보드선도 라우트와 같은 이유)
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
