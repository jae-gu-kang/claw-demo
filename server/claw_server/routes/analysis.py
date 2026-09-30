"""마진 맵 라우트 (02 §8 워크플로우 5단계) — 트림점별 선형화 → 안정성·마진 수치.

엔진 호출 연쇄: trim_batch → linearize → split_axes → damp/classify →
broken_loop+nyquist_margins. 루프 정의(축·입출력·PI 게인·부호)는 요청이 보유하고
서버는 엔진 축 이름으로 검증만 한다 — 마진 산출 자체는 전부 M10 소관.
격자 시각화는 M14(web) 소관 (01 §4.2).

루프 게인은 요청이 적은 kp·ki가 기본이고, 루프가 `gain_source: "profile"`이면 고른 기체의 **조립 법칙이
그 칸의 운용점에서 쓰는 게인**이다(케이스마다 다르다 — 스케줄 표@칸). 스케줄 산식은 여기 다시 적지 않는다:
조립은 assemble_law, 칸의 실효 게인은 pipeline.openloop.effective_gain(2단 개루프와 같은 자)이다.
"""

import math
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator

from claw.analysis import (
    FQCriteria,
    aero_envelope,
    bode_data,
    classify_lat,
    classify_lon,
    damp,
    design_envelope,
    fq_lat,
    fq_lon,
    broken_loop,
    nyquist_margins,
    omega_covering,
    vn_envelope,
)
from claw.fcl.assemble import assemble_law
from claw.pipeline.openloop import GROUP_LOOPS, effective_gain
from claw.profile import ProfileError
from claw.design.points import envelope_verdict
from claw.opspace import region_of
from claw.opspace.verdict import VerdictContext
from claw.trim import trim_level
from claw.trim import (
    DEFAULT_RETRY,
    LAT_INPUTS,
    LAT_STATES,
    LON_INPUTS,
    LON_STATES,
    linearize,
    split_axes,
    trim_batch,
)
from claw_server.routes.trim import FiniteFloat, TrimCaseIn, build_cases
from claw_server.refs import (
    ProfileRef, ReusePolicy, criteria_echo, profile_echo, profile_error_detail, profile_query, resolve_criteria,
    resolve_profile, reuse_counts, reuse_echo, retried_states, retry_counts, retry_echo, stored_failures, trim_scope,
)
from claw_server.serialize import to_jsonable, trim_result_dict

router = APIRouter(tags=["analysis"])

_AXIS_NAMES = {
    "lon": (LON_STATES, LON_INPUTS),
    "lat": (LAT_STATES, LAT_INPUTS),
}


# 루프 자리 (축, 출력 상태, 입력) → (스케줄 그룹, 선언). 선언의 정본은 pipeline.openloop.GROUP_LOOPS이고 여기는
# 역인덱스다(아래 _LOOP_GROUP 주석 참조). 자리가 겹치면 dict가 뒤 선언으로 조용히 덮어 **다른 그룹의 게인**을
# 읽게 되므로 import 시점에 막는다(analysis/margins.py _FILTER_TF 단정문과 같은 가드)
_LOOP_DECL = {
    (d["axis"], d["x_out"], d["u_in"]): (group, d)
    for group, decls in GROUP_LOOPS.items()
    for d in decls
}
assert len(_LOOP_DECL) == sum(len(v) for v in GROUP_LOOPS.values()), "GROUP_LOOPS 루프 자리 중복"


class LoopIn(BaseModel):
    """PI 개루프 스펙 — 마진 맵의 루프 정의 (설계값은 요청이 보유).

    게인은 둘 중 하나다. 기본은 요청이 적은 kp·ki — 전 칸에 같은 값이다. `gain_source: "profile"`이면 kp·ki를
    싣지 않고 고른 기체의 조립 법칙이 **칸마다 그 운용점에서** 쓰는 게인을 서버가 읽는다(스케줄 표@칸 — 기체가
    실제로 나는 게인). 루프 한 개가 kp 하나라서 스케줄 게인을 한 마하에서 읽어 전 칸에 쓰면 그 마하 열 밖은
    판정까지 뒤집힐 수 있는 근사였다 — 그것을 없애는 자리다. 법칙 자리 대응은 GROUP_LOOPS 선언뿐이라 선언이
    없는 루프(예: v←dr)는 이 방식을 쓸 수 없다. 부호(sign)는 루프 구조라 요청이 계속 보유한다.
    """

    name: str = Field(min_length=1)
    axis: Literal["lon", "lat"] = "lon"
    x_out: str = "q"
    u_in: str = "de"
    kp: FiniteFloat | None = None  # 요청 게인 루프에서만 — 필수 여부는 아래 검증이 gain_source로 가른다
    ki: FiniteFloat = 0.0
    sign: FiniteFloat = -1.0
    gain_source: Literal["profile"] | None = None

    @model_validator(mode="after")
    def _check_axis_names(self):
        states, inputs = _AXIS_NAMES[self.axis]
        if self.x_out not in states:
            raise ValueError(f"{self.axis}축에 없는 상태: {self.x_out} (허용: {states})")
        if self.u_in not in inputs:
            raise ValueError(f"{self.axis}축에 없는 입력: {self.u_in} (허용: {inputs})")
        if self.gain_source == "profile":
            # 게인을 두 곳에서 받으면 어느 쪽으로 쟀는지가 결과에서 흐려진다 — 법칙 게인 루프는 kp·ki를 싣지 않는다
            given = sorted({"kp", "ki"} & self.model_fields_set)
            if given:
                raise ValueError(f"gain_source \"profile\" 루프는 {', '.join(given)}를 싣지 않는다 — 게인은 법칙이 칸마다 준다")
            if (self.axis, self.x_out, self.u_in) not in _LOOP_DECL:
                raise ValueError(
                    f"법칙 자리 선언이 없는 루프({self.axis} {self.x_out}←{self.u_in}) — gain_source \"profile\"은 "
                    "pipeline.openloop.GROUP_LOOPS에 선언된 자리만 (kp·ki를 직접 적는다)")
            if self.sign == 0.0:
                raise ValueError("무의미 루프 (제로 개루프): sign=0")
            return self
        if self.kp is None:
            raise ValueError("kp 필요 — 또는 gain_source \"profile\"(고른 기체의 법칙 게인을 칸마다)")
        if self.sign == 0.0 or (self.kp == 0.0 and self.ki == 0.0):
            raise ValueError("무의미 루프 (제로 개루프): sign=0 또는 kp=ki=0")
        return self


def _loop_echo(spec) -> dict:
    """결과·보드선도 응답에 싣는 루프 스펙 — 요청 게인 루프는 종전 모양 그대로(서버 골든 margin_map의 loops가
    바이트로 지킨다), 법칙 게인 루프는 kp·ki 없이 gain_source만. 웹은 이 echo를 보드선도 요청에 그대로 되실으므로
    법칙 게인 루프의 echo가 kp·ki를 가지면 위 검증이 그 요청을 거절한다."""
    if spec.gain_source is None:
        return spec.model_dump(exclude={"gain_source"})
    return spec.model_dump(exclude={"kp", "ki"})


class ActuatorIn(BaseModel):
    """마진 계산용 작동기 동특성 (01 §4.2 [기본값] — plant.actuator.SecondOrderActuator와
    동일 2차계 wn²/(s²+2ζωn·s+wn²) 재사용, 레이트/위치 한계는 소신호 해석 제외)."""

    wn: FiniteFloat = Field(gt=0.0)
    zeta: FiniteFloat = Field(gt=0.0)


class MarginMapIn(BaseModel):
    profile: ProfileRef | None = None  # 기체 선택 — 없으면 예제 기체 (02 §5.6)
    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1)
    reuse: ReusePolicy = "converged"  # 트림 저장소(05 §11.8) — 수렴 기록 재사용 / "none" 다시 풂
    loops: list[LoopIn] = []
    # 작동기·지연 포함은 [기본값] 미포함(하위호환) — 포함이 01 §4.2 문서 기본값이지만
    # 그건 웹 폼 초기 상태의 몫이고 서버 계약은 중립 유지 (엔진 pi_loop과 동일 원칙)
    actuator: ActuatorIn | None = None
    delay_s: FiniteFloat = Field(default=0.0, ge=0.0)
    pade_order: int = Field(default=2, ge=1)
    # 루프 하나를 끊을 때 같은 축의 나머지 요청 루프를 닫아 둔다(AS94900의 끊는 자리 — 엔진 broken_loop). 끄면 종전처럼
    # 루프마다 그 루프 하나만 있는 축에서 잰다(비교용). 루프가 축마다 하나면 두 방식이 같다(서버 골든 margin_map)
    close_others: bool = True

    @model_validator(mode="after")
    def _unique_loop_names(self):
        names = [lp.name for lp in self.loops]
        if len(names) != len(set(names)):
            raise ValueError(f"루프 이름 중복: {names}")
        return self


# 비행성 수준 판정선 — 엔진 [기본값](MIL-F-8785C Class I·Cat B). 결과에 fq_criteria로
# 동봉해 화면이 판정선을 재기술하지 않게 한다 (MarginCriteria /design/defaults와 같은 원칙)
_FQ_CRITERIA = FQCriteria()


def _axis_block(model, classify_fn, fq_fn) -> dict:
    """축 부분모델 → 고유치 원자료 + 자동 분류 + 비행성 수준 (비정형 구조는 note로 보고).

    fq는 분류가 선 모드에만 선다 — 분류 불가(실근 분리 등)면 판정할 모드 자체가
    없으므로 함께 None이다. 판정은 무증강 기체 모드의 것이다(engine analysis/fq.py).
    """
    block = {"modes": to_jsonable(damp(model.A))}
    try:
        classified = classify_fn(model)
    except ValueError as e:  # 실근 분리 등 비정형 — 데이터이지 실패가 아님
        return {**block, "classified": None, "fq": None, "note": str(e)}
    block["classified"] = to_jsonable(classified)
    block["fq"] = to_jsonable(fq_fn(classified, _FQ_CRITERIA))
    block["note"] = None
    return block


# 마진 탭 루프 → 스케줄 그룹. 대응 **선언의 정본은 pipeline.openloop.GROUP_LOOPS**
# ("유도가 아니라 선언이다" — 그 머리말이 레이트 루프 3개가 웹 마진 탭 DEFAULT_LOOPS와
# 정합임을 못박고 test_openloop이 핀한다). 여기서는 역인덱스만 만든다 — 대응을 다시
# 적으면 두 곳이 갈리고, 갈려도 화면에는 그럴듯한 곡선이 나와 티가 안 난다.
# **필터 선언은 그룹이 아니라 루프 자리에 달려 있다** — yaw_rate는 filter 항을
# 갖고 pitch_att는 안 갖는다(openloop._effective_filter도 sp.get("filter")를 읽는다).
# 그룹만 키로 쓰면 피치 축에 washout_tau가 켜지는 날 **자세 루프**가 선언에 없는
# 레이트 워시아웃을 얻고, 그 사유 문장은 사실과 반대를 말하게 된다.
_LOOP_GROUP = {key: (group, d.get("filter")) for key, (group, d) in _LOOP_DECL.items()}


class _LawGains:
    """고른 기체의 조립 법칙 → 법칙 게인 루프(gain_source "profile")의 칸별 {kp, ki}.

    조립은 assemble_law 한 경로(시뮬·코드와 같은 표 우선순위: 문서 확정 표 > 규칙 스케줄), 칸의 실효 게인은
    openloop.effective_gain(표@칸, 스케줄 안 한 자리는 설계 상수) — 스케줄 산식을 여기 다시 적지 않는다.
    조립이 서지 않는 문서(확정 표 낡음·게인 미설계·δe_trim 낡음 등)는 422다: 기체가 날 게인이 없는데 다른
    게인으로 재서 그 기체의 마진인 척하지 않는다.
    """

    def __init__(self, profile, loops):
        self.loops = [lp for lp in loops if lp.gain_source == "profile"]
        self.law = None
        if not self.loops:
            return
        try:
            self.law = assemble_law(profile)
        except ProfileError as e:
            raise HTTPException(status_code=422, detail=profile_error_detail(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"법칙 조립 실패 — 칸별 게인을 읽을 수 없다: {e}")

    def at(self, spec, case) -> dict:
        """이 루프의 이 칸 게인 {kp, ki} — 선언이 안 가진 PI 인자는 0 (레이트 루프는 kp = k_rate뿐)."""
        group, decl = _LOOP_DECL[(spec.axis, spec.x_out, spec.u_in)]
        g = {arg: effective_gain(self.law, group, key, case) for arg, key in decl["gains"].items()}
        return {"kp": g.get("kp", 0.0), "ki": g.get("ki", 0.0)}

    def case_gains(self, case) -> dict:
        return {lp.name: self.at(lp, case) for lp in self.loops}

    def provenance(self, profile) -> dict:
        """어느 표에서 읽었나 — basis(확정 표 | 규칙 스케줄)와 루프 인자별 자리·스케줄 여부. 결과를 결과 탭에서
        다시 열어도 그 마진을 잰 게인의 출처를 말할 수 있게 결과와 함께 저장한다."""
        tables = self.law.schedule.tables if self.law.schedule is not None else {}
        loops = {}
        for lp in self.loops:
            group, decl = _LOOP_DECL[(lp.axis, lp.x_out, lp.u_in)]
            loops[lp.name] = {arg: {"slot": f"{group}.{key}", "scheduled": f"{group}.{key}" in tables}
                              for arg, key in decl["gains"].items()}
        # 조립이 섰으므로 문서의 확정 표는 낡지 않았다 — 있으면 조립이 그 표를 썼다(assemble_law 우선순위)
        basis = "confirmed" if profile.doc["law"]["gain_tables"] is not None else "rule"
        return {"basis": basis, "loops": loops}


def _zero(g) -> bool:
    return g["kp"] == 0.0 and g["ki"] == 0.0


def _closed_others(spec, loops, gains_of):
    """이 루프를 끊을 때 닫아 둘 루프 — 같은 축·**다른 자리**(출력·입력 쌍)의 요청 루프 중 이 칸 게인이 0이 아닌 것.

    같은 자리의 다른 루프(예: kp만 다른 비교용 pitch_q 사본)는 닫지 않는다 — 한 센서·한 타면 경로에 되먹임이 둘인
    법칙이 아니라 같은 루프의 대안이다. gains_of(spec) → 그 칸의 {kp, ki}(법칙 게인 루프) 또는 None(요청 게인).
    반환 [(spec, gains | None)]."""
    out = []
    for o in loops:
        if o is spec or o.axis != spec.axis or (o.x_out, o.u_in) == (spec.x_out, spec.u_in):
            continue
        g = gains_of(o)
        if g is not None and _zero(g):
            continue  # 이 칸에서 법칙 게인 0 — 닫을 루프가 없다
        out.append((o, g))
    return out


def _compose_loop(model, spec, actuator, delay_s, pade_order, rate_filter=None, gains=None, others=()):
    """루프 스펙 + 작동기·지연 → 개루프 — 마진 맵과 보드선도의 **공용 조립**.

    두 곳이 따로 조립하면 곡선과 클릭한 칸의 수가 어긋난다. 어긋나도 화면에는
    둘 다 그럴듯하게 보이므로(값이 조금 다를 뿐) 조립은 한 곳에만 적는다.
    rate_filter는 **마진 맵 경로에서 항상 None**이다 — 히트맵이 법칙의 필터를 안
    본다는 01 §4.2 [한계]를 보드선도가 몰래 바꾸면 칸의 수와 곡선이 어긋난다.
    보드선도는 그 차이를 없애는 대신 **두 곡선으로 보여준다**(아래 bode_endpoint).
    gains는 법칙 게인 루프의 이 칸 {kp, ki}(_LawGains.at) — None이면 요청이 적은 kp·ki다.
    others는 닫아 둘 루프 [(spec, gains | None)](_closed_others) — 비면 엔진 broken_loop이 pi_loop 그대로다(골든).
    """
    def pi_of(s, g):
        return (s.kp, s.ki) if g is None else (g["kp"], g["ki"])

    kp, ki = pi_of(spec, gains)
    closed = []
    for o, g in others:
        okp, oki = pi_of(o, g)
        closed.append({"x_out": o.x_out, "u_in": o.u_in, "kp": okp, "ki": oki, "sign": o.sign})
    return broken_loop(
        model, x_out=spec.x_out, u_in=spec.u_in,
        kp=kp, ki=ki, sign=spec.sign, others=closed,
        actuator_wn=actuator.wn if actuator else None,
        actuator_zeta=actuator.zeta if actuator else None,
        delay_s=delay_s, pade_order=pade_order,
        rate_filter=rate_filter,
    )


def _with_closed(margins, others) -> dict:
    """마진 dict + 닫아 둔 루프 이름(closed_with) — 닫은 루프가 없으면 종전 dict 그대로(골든)."""
    if not others:
        return margins
    return {**margins, "closed_with": [o.name for o, _g in others]}


def _with_status(margins: dict, mc, lm_axis=None) -> dict:
    """칸의 마진 dict + 엔진 판정(프로파일 기준) — 화면이 PM·GM 색을 다시 짜지 않게 판정을 싣는다.
    판정은 엔진 MarginCriteria.judge_cell 한 자리다: 폐루프 발산(margins["closed_loop"])을 자동 설계와 같은 나선 면제
    규칙(spiral_exempt_verdict)으로 접어 넣는다 — 느린 나선 실근 하나가 아닌 발산이면 status fail(pm·gm_status는 잰
    그대로). 면제에 필요한 축·기준 wn은 페이로드에 없으므로 이 칸을 조립한 축 모델(lm_axis)을 넘긴다.
    발산이 없으면 pm_status = judge_pm, gm_status = judge_gm, status = judge (= 둘의 합산). nan이면 na.
    to_jsonable 전의 날 수치로 판정한다(nan·inf가 JSON 표현으로 바뀌기 전)."""
    return {**margins, **mc.judge_cell(margins, margins.get("closed_loop"), lm_axis)}


def _trim_only_entry(tr) -> dict:
    return {
        "trim": trim_result_dict(tr),
        "lon": None,
        "lat": None,
        "margins": {},
        "note": None,
    }


def _assemble_limits(
    profile, n_limit_pos=None, n_limit_neg=None, safety_factor=None, mach_no=None, mach_d=None,
) -> tuple:
    """데모 구조 한계 + 사용자 오버라이드 조립 — (limits, source, overridden).

    기본값 재기술 금지(02 §5.5): None은 데모 프로파일이 채우고, 서버는 어느
    필드가 사용자 값인지(overridden)와 출처(source)만 echo. 값 검증(부호·서열)은
    엔진 _check_limits 몫 — 서버는 경계 유한성만 (allow_inf_nan).
    """
    limits = profile.structural_limits()
    overrides = {
        "n_limit_pos": n_limit_pos,
        "n_limit_neg": n_limit_neg,
        "safety_factor": safety_factor,
        "mach_no": mach_no,
        "mach_d": mach_d,
    }
    overridden = [k for k, v in overrides.items() if v is not None]
    limits.update({k: overrides[k] for k in overridden})
    # 예제 기체의 한계는 자리표시라 종전 문구를 유지한다(웹이 이 값으로 자리표시를 표시한다)
    source = "user-input" if overridden else ("demo-placeholder" if profile.is_example else "profile")
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
    request: Request,
    profile_ref: ProfileRef | None = Depends(profile_query),
    alt: float = Query(..., allow_inf_nan=False),
    fuel: float = Query(ge=0.0, allow_inf_nan=False),  # inf는 fuel_max로 조용히 잘려 거짓 echo가 된다
    # None = 기체 프로파일 값 (α 리미터 마진·음의 실속 자리표시 비율) — 서버가 수를 재기술하지 않는다
    alpha_margin: float | None = Query(default=None, ge=0.0, allow_inf_nan=False),
    neg_alpha_ratio: float | None = Query(default=None, gt=0.0, le=1.0),
    # 구조 한계 오버라이드 — None = 데모 프로파일이 채움 (기본값 재기술 금지, 02 §5.5)
    n_limit_pos: float | None = Query(default=None, allow_inf_nan=False),
    n_limit_neg: float | None = Query(default=None, allow_inf_nan=False),
    safety_factor: float | None = Query(default=None, allow_inf_nan=False),
    mach_no: float | None = Query(default=None, allow_inf_nan=False),
    mach_d: float | None = Query(default=None, allow_inf_nan=False),
) -> dict:
    """V-n 선도 (01 §2.6 · 01 §3.6) — 실속·보호 곡선 + 구조 한계선 + 특성 속도 (동기 계산).

    구조 한계는 비행체 프로파일의 자리표시 [기본값](실기체 값 아님)에 사용자
    오버라이드를 얹는다(필요값 입력, 01 §2.6) — limits_source·limits_overridden
    echo. 음의 실속 곡선도 자리표시(−ratio×α_stall, 엔진이 ratio echo).
    표기는 웹 소관.
    """
    profile = resolve_profile(request, profile_ref)
    alpha_margin = profile.law["alpha_margin"] if alpha_margin is None else alpha_margin
    neg_alpha_ratio = profile.neg_alpha_ratio if neg_alpha_ratio is None else neg_alpha_ratio
    ac = profile.aircraft()
    limits, source, overridden = _assemble_limits(
        profile, n_limit_pos, n_limit_neg, safety_factor, mach_no, mach_d
    )
    try:
        env = vn_envelope(
            ac,
            profile.stall_table(),
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
    env["profile"] = profile_echo(profile)
    return env


@router.get("/analysis/design-envelope")
def design_envelope_endpoint(
    request: Request,
    profile_ref: ProfileRef | None = Depends(profile_query),
    fuel: float = Query(ge=0.0, allow_inf_nan=False),  # inf는 fuel_max로 조용히 잘려 거짓 echo가 된다
    q_max: float | None = Query(default=None, allow_inf_nan=False),
    alt_min: float | None = Query(default=None, allow_inf_nan=False),
    alt_max: float | None = Query(default=None, allow_inf_nan=False),
    mach_margin: float | None = Query(default=None, allow_inf_nan=False),
    alpha_margin: float | None = Query(default=None, ge=0.0, allow_inf_nan=False),  # None = 기체 α 리미터 마진
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
    프로파일 조립과 비-None 전달만 (기본값 재기술 금지, 02 §5.5). q_max는 실기체
    값이라 질의에도 기체 문서에도 없으면 경계 자체가 없다(엔진이 null echo).
    trim_alpha_bounds는 기체 문서의 트림 풀이 설정(solver.trim_alpha_bounds — 스키마 v3)을
    조립 시점에 주입 (엔진 analysis가 기체 조립을 직접 import하지 않는다 — 03 §2 계층 규칙).

    nz·iso_qbar·iso_tas도 같은 계약 — 미지정이면 전달하지 않고 엔진이 정한다
    (기동 엔벨로프는 아예 없는 것, 등고선은 엔진 [기본값]).

    q_max를 질의가 주지 않으면 **기체 문서 값**(structural.q_max)을 쓴다 — 실기체 값이 문서에 있는데 폼이
    비었다고 경계를 빼면 그 기체의 엔벨로프가 아니다. 문서에도 없으면(null) 종전대로 경계가 없다. 운용 고도는
    스키마 v3에서 문서 절(operating)이 없어지고 요구영역 고도(operating_region.alt)가 됐다(05 §11.13 이관 11단계) —
    문서에서 채우지 않는다: 질의가 없으면 엔진이 requirement의 고도 끝을 선도 끝으로 그린다(bounds.alt_*_source
    "region"). 같은 값을 alt_min·alt_max로도 넘기면 요구영역 끝이 「운용 입력」으로 두 번 그려진다. 질의 운용 고도는
    연구용 덮어쓰기로 남는다. 어느 값이 어디서 왔는지는 bounds_source({q_max·alt_min·alt_max: "query"|"profile"|
    null} — 고도 칸은 "query"|null뿐)로 말하되, 문서 값을 하나라도 쓴 응답에만 싣는다 — 문서 값이 전부 null인
    예제 기체의 응답은 종전과 바이트 단위로 같아야 한다(서버 골든).
    """
    profile = resolve_profile(request, profile_ref)
    alpha_margin = profile.law["alpha_margin"] if alpha_margin is None else alpha_margin
    ac = profile.aircraft()
    stall = profile.stall_table()
    db_ranges = profile.db_ranges()
    limits, source, overridden = _assemble_limits(
        profile, n_limit_pos, n_limit_neg, safety_factor, mach_no, mach_d
    )
    # 동압 한계 — 질의 > 기체 문서 > 없음(경계 없음). 운용 고도 — 질의 > 없음(엔진이 요구영역 고도 끝을 쓴다)
    query = {"q_max": q_max, "alt_min": alt_min, "alt_max": alt_max}
    doc_bounds = {"q_max": profile.q_max}
    bounds = {k: v if v is not None else doc_bounds.get(k) for k, v in query.items()}
    bounds_source = {k: "query" if query[k] is not None else ("profile" if bounds[k] is not None else None)
                     for k in query}
    q_max, alt_min, alt_max = bounds["q_max"], bounds["alt_min"], bounds["alt_max"]
    from_profile = [k for k, s in bounds_source.items() if s == "profile"]
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
        # 선도의 주인은 요구 운용영역(05 §11.13 이관 9단계) — 없으면 엔진이 requirement null + requirement_undefined로
        # 말한다. 구조·공력 교집합(region)은 「현재 분석 가능한 영역」으로 뜻이 좁아졌다(추력 미포함)
        env = design_envelope(ac, stall, limits, db_ranges, fuel=fuel, requirement=region_of(profile.doc), **kwargs)
        env["aero"] = aero_envelope(
            stall, db_ranges, alpha_margin=alpha_margin, trim_alpha_bounds=profile.trim_alpha_bounds
        )
    except (ValueError, TypeError) as e:  # ISA 범위·서열 위반 등 — 엔진 검증
        # 질의 값과 문서 값이 섞여 서열이 어긋나면 사용자가 넣지 않은 수가 사유에 나온다 — 그 출처를 붙인다
        used = ", ".join(f"{k}={bounds[k]:g}" for k in from_profile)
        raise HTTPException(status_code=422, detail=str(e) + (f" (기체 문서 값: {used})" if used else ""))
    env["limits"] = limits
    env["limits_source"] = source
    env["limits_overridden"] = overridden
    if from_profile:
        env["bounds_source"] = bounds_source
    env["profile"] = profile_echo(profile)
    return to_jsonable(env)


MAX_SCAN_CASES = 200  # 영향성 라우트 MAX_CASES와 같은 지위 — 오타 격자의 단일 워커 점유 차단


class EnvelopeScanIn(BaseModel):
    """제어 가능 영역 스캔 — 케이스 격자 트림 + 조건 판정 채택 (01 §2.6 · 05 §11.3)."""

    profile: ProfileRef | None = None
    fingerprint: str = ""
    cases: list[TrimCaseIn] = Field(min_length=1, max_length=MAX_SCAN_CASES)
    reuse: ReusePolicy = "converged"  # 트림 저장소(05 §11.8) — 수렴 기록 재사용 / "none" 다시 풂


@router.post("/analysis/design-envelope-scan", status_code=202)
def submit_envelope_scan(req: EnvelopeScanIn, request: Request, response: Response) -> dict:
    """설계 엔벨로프의 제어 가능 영역 — 격자 트림 잡 (마진 맵과 같은 202 골격).

    점별 판정은 엔진 envelope_verdict(조건 판정 condition_verdict의 채택 + 사유 귀속, 판정 전체는 verdict) —
    saturated_throttle_high는 대리 지표가 아니라 추진 한계 자체다 (plant/prop.py PropEngine).
    취소는 trim_batch 협조적 중단 — 완료분 보존.
    """
    profile = resolve_profile(request, req.profile)
    ac = profile.aircraft()
    cases = build_cases(req.cases)
    store = request.app.state.store
    # 조건 판정 문맥(05 §11.3 · 이관 8단계) — 트림 탭·자동 설계와 같은 기체 값으로 판정한다
    vctx = VerdictContext.from_profile(profile)
    # 점별 판정의 여유 사유(트림 여유 미달 등)가 기준 criteria.trim_margin으로 난다(이관 12단계) — 결과가 그 기준을 싣는다
    crit, crit_source = resolve_criteria(profile)
    crit_block = criteria_echo(crit, crit_source)
    scope = trim_scope(request, profile)

    def work(job):
        failed = stored_failures(scope, cases)
        trs = trim_batch(
            ac,
            cases,
            fingerprint=req.fingerprint,
            on_progress=lambda done, total, tr: job.report(
                done, total, message=f"트림: {tr.case.name}"
            ),
            store=scope,
            reuse=req.reuse,
            retry=DEFAULT_RETRY,
        )
        reuse = reuse_echo(trs, scope, req.reuse, failed, trim_fingerprint=profile.trim_fingerprint)
        verdicts = [envelope_verdict(tr, vctx) for tr in trs]
        # 되울림은 점별 판정이 이미 잰 트림 상태로 센다(다시 재지 않는다)
        retried = retry_echo(trs, [v["verdict"]["trim"]["status"] for v in verdicts], DEFAULT_RETRY)
        entries = [
            {"trim": trim_result_dict(tr), "verdict": to_jsonable(v)}
            for tr, v in zip(trs, verdicts)
        ]
        store.save(
            job.id,
            {"kind": "envelope_scan", "cases": entries, "n_requested": len(cases),
             "profile": profile_echo(profile), "criteria_echo": crit_block, "trim_reuse": reuse,
             "trim_retry": retried},
            meta={
                "kind": "envelope_scan",
                "profile": profile_echo(profile),
                "criteria_echo": crit_block,
                "created": job.created,
                "n": len(entries),
                "fingerprint": req.fingerprint,
                "trim_reuse_counts": reuse_counts(reuse),
                "trim_retry_counts": retry_counts(retried),
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

    profile: ProfileRef | None = None
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
    # 닫아 둘 루프 — 마진 맵 칸의 closed_with(같은 축의 나머지 요청 루프)를 그 결과의 loops echo에서 그대로 싣는다.
    # 칸과 곡선이 같은 조립이어야 한다(엔진 broken_loop). 비면 이 루프 하나만 있는 축(종전)
    others: list[LoopIn] = []

    @model_validator(mode="after")
    def _others_same_axis(self):
        names = [self.loop.name] + [o.name for o in self.others]
        if len(names) != len(set(names)):
            raise ValueError(f"루프 이름 중복: {names}")
        stray = [o.name for o in self.others if o.axis != self.loop.axis]
        if stray:
            raise ValueError(f"닫아 둘 루프는 끊는 루프와 같은 축({self.loop.axis})이어야 한다: {stray}")
        return self


@router.post("/analysis/bode")
def bode_endpoint(req: BodeIn, request: Request) -> dict:
    """개루프 보드선도 (01 §4.2) — 트림 1건이라 동기 계산.

    GM과 PM은 같은 곡선의 서로 다른 자리에서 읽는 수라 히트맵 두 장으로는 둘의
    주파수 관계가 안 보인다. 이 응답이 같은 주파수축의 이득·위상과 **교차점 전량**을
    줘서 화면이 "보고된 마진이 어느 교차의 것인가"까지 말하게 한다 (엔진 bode_data).
    """
    profile = resolve_profile(request, req.profile)
    ac = profile.aircraft()
    (case,) = build_cases([req.case])
    # 법칙 게인 루프면 이 칸의 게인 — 마진 맵이 그 칸에서 쓴 것과 같은 조립·같은 조회다(칸과 곡선이 같은 게인)
    law_gains = _LawGains(profile, [req.loop, *req.others])
    gains = law_gains.at(req.loop, case) if req.loop.gain_source == "profile" else None
    if gains is not None and _zero(gains):
        raise HTTPException(status_code=422, detail=(
            f"이 칸({case.name})에서 법칙 게인이 0이다(제로 개루프) — 보드선도를 낼 루프가 없습니다"))
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
    fspec = profile.rate_filters().get(group) if fdecl else None
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
        others = _closed_others(
            req.loop, [req.loop, *req.others],
            lambda o: law_gains.at(o, case) if o.gain_source == "profile" else None)
        loop = _compose_loop(model, req.loop, req.actuator, req.delay_s, req.pade_order, gains=gains, others=others)
        floop = (
            _compose_loop(model, req.loop, req.actuator, req.delay_s, req.pade_order,
                          rate_filter=fspec, gains=gains, others=others)
            if fspec else None
        )
        # 겹쳐 비교하려면 같은 축이어야 한다 — 워시아웃 코너처럼 한쪽에만 있는 극이
        # 다른 쪽 범위 밖으로 나가면 그 교차를 통째로 놓친다
        w = omega_covering(*( [loop, floop] if floop else [loop] ), n_points=req.n_points)
        data = bode_data(loop, w=w)
        data["margins"] = _with_closed(data["margins"], others)  # 칸의 마진 dict와 같은 모양
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
        "loop": _loop_echo(req.loop),
        "actuator": req.actuator.model_dump() if req.actuator else None,
        "delay_s": req.delay_s,
        "pade_order": req.pade_order,
        "profile": profile_echo(profile),
        # 법칙 게인 루프만 — 이 곡선을 그린 이 칸의 게인과 그 출처(요청 게인 루프의 응답은 종전 모양 그대로)
        **({"gains": gains, "profile_gains": law_gains.provenance(profile)} if gains is not None else {}),
    })


@router.post("/analysis/margin-map", status_code=202)
def submit_margin_map(req: MarginMapIn, request: Request, response: Response) -> dict:
    profile = resolve_profile(request, req.profile)
    ac = profile.aircraft()
    cases = build_cases(req.cases)
    store = request.app.state.store
    n = len(cases)
    total = 2 * n  # 트림 패스 + 해석 패스
    # 법칙 게인 루프 — 조립 실패는 잡을 걸기 전에 422. 게인은 트림과 무관하게 칸(마하·고도·연료)만으로 정해지므로
    # 격자 전 칸에서 0인 루프도 여기서 거절한다(요청 게인 kp=ki=0 루프의 422와 같은 판정). 일부 칸만 0이면 그 칸만
    # 마진 없이 사유(note)를 단다
    # 칸의 판정은 프로파일 기준 한 벌로(기준 통합 ① S3a) — 마진 맵은 요청 기준을 받지 않는다
    crit, crit_source = resolve_criteria(profile)
    crit_block = criteria_echo(crit, crit_source)
    law_gains = _LawGains(profile, req.loops)
    for lp in law_gains.loops:
        if all(_zero(law_gains.at(lp, c)) for c in cases):
            raise HTTPException(status_code=422, detail=(
                f"무의미 루프 (제로 개루프): {lp.name}의 법칙 게인이 격자 전 칸에서 0이다"))
    scope = trim_scope(request, profile)

    def work(job):
        failed = stored_failures(scope, cases)
        trs = trim_batch(
            ac,
            cases,
            fingerprint=req.fingerprint,
            on_progress=lambda done, _t, tr: job.report(
                done, total, message=f"트림: {tr.case.name}"
            ),
            store=scope,
            reuse=req.reuse,
            retry=DEFAULT_RETRY,
        )
        reuse = reuse_echo(trs, scope, req.reuse, failed, trim_fingerprint=profile.trim_fingerprint)
        # 마진 맵은 조건 판정을 싣지 않는다 — 다시 푼 점만 상태를 재 되울림이 트림 탭과 같은 말을 하게
        retried = retry_echo(trs, retried_states(trs, profile, {"aircraft": ac}), DEFAULT_RETRY)
        def trim_entry(t):
            # 이 칸의 법칙 게인 — 트림 수렴·취소와 무관하게 싣는다(칸의 기록). 법칙 게인 루프가 없으면 키도 없다(골든)
            e = _trim_only_entry(t)
            if law_gains.loops:
                e["gains"] = law_gains.case_gains(t.case)
            return e

        entries = []
        for i, tr in enumerate(trs):
            if job.cancel_requested:
                # 취소 — 계산 완료된 나머지 트림 결과를 해석 생략 entry로
                # 전량 보존 (리뷰 S1: 유실 금지)
                entries.extend(trim_entry(t) for t in trs[i:])
                break
            entry = trim_entry(tr)
            case_gains = entry.get("gains")
            if tr.converged:
                try:
                    lon, lat = split_axes(linearize(ac, tr))
                    entry["lon"] = _axis_block(lon, classify_lon, fq_lon)
                    entry["lat"] = _axis_block(lat, classify_lat, fq_lat)
                    zero = []
                    for spec in req.loops:
                        model = lon if spec.axis == "lon" else lat
                        g = case_gains.get(spec.name) if case_gains is not None else None
                        if g is not None and _zero(g):
                            zero.append(spec.name)  # 이 칸만 게인 0 — 재면 무의미한 inf 마진이 칠해진다
                            continue
                        others = (_closed_others(
                            spec, req.loops,
                            lambda o: case_gains.get(o.name) if case_gains is not None else None)
                            if req.close_others else [])
                        loop = _compose_loop(
                            model, spec, req.actuator, req.delay_s, req.pade_order, gains=g, others=others)
                        # 칸의 마진은 나이퀴스트에 맞는 여유다(엔진 nyquist_margins — 보드선도와 같은 정의). control.margin
                        # 부호를 그대로 칠하면 다중 교차 레이트 루프가 안정인데도 "음수"로 칠해졌다(e2e D2). 같은 축의 나머지
                        # 루프는 닫고 끊는다(broken_loop) — 연 채로 재면 기체가 실제로 나는 폐루프가 아니다(요 댐퍼를 연
                        # roll_p의 나선 발산). 루프가 축마다 하나이고 교차가 하나씩이며 폐루프가 안정이면 종전과 비트 같다(골든)
                        entry["margins"][spec.name] = to_jsonable(
                            _with_status(_with_closed(nyquist_margins(loop), others), crit.margin, model))
                    if zero:
                        entry["note"] = f"법칙 게인이 이 칸에서 0 — 제로 개루프라 마진 없음: {', '.join(zero)}"
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
                # 판정선 동봉 — 화면은 이 값을 읽어 범례를 쓴다 (판정선 재기술 금지)
                "fq_criteria": {**_FQ_CRITERIA.to_dict(), "fingerprint": _FQ_CRITERIA.fingerprint()},
                "loops": [_loop_echo(lp) for lp in req.loops],
                "actuator": req.actuator.model_dump() if req.actuator else None,
                "delay_s": req.delay_s,
                "pade_order": req.pade_order,
                "n_requested": n,
                "profile": profile_echo(profile),
                # 칸의 status 필드를 낸 기준 — profile 블록과 따로(profile 블록은 골든이 바이트로 못박는다)
                "criteria_echo": crit_block,
                # 법칙 게인 루프가 있을 때만 — 칸별 게인(entry.gains)을 어느 표에서 읽었나
                **({"profile_gains": law_gains.provenance(profile)} if law_gains.loops else {}),
                "trim_reuse": reuse,
                "trim_retry": retried,
            },
            meta={
                "kind": "margin_map",
                "profile": profile_echo(profile),
                "criteria_echo": crit_block,
                "created": job.created,
                "n": len(entries),
                "fingerprint": req.fingerprint,
                "trim_reuse_counts": reuse_counts(reuse),
                "trim_retry_counts": retry_counts(retried),
            },
        )
        job.result_id = job.id

    job = request.app.state.jobs.submit("margin_map", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()
