"""탑재 제어법칙 C 생성 라우트 (02 §1 · 07 §4, M16).

웹의 기존 "코드 생성"(파라미터 표현)과 다른 물건이다 — 여기서 나오는 것은
**FCC에 통합되어 그대로 실릴 제어법칙 코드**이고, 구조·블록 로직·파라미터가
전부 들어 있다. 산출물 정본은 `flight/gen/`(커밋됨)이며 이 라우트는 같은
생성기를 **현재 편집 중인 형상**으로 돌려 보여 준다.

**구조와 값이 갈린다 (v1.12).** 생성 C에는 구조만 있고, 값은 파라미터 이미지(`param_image`)로 따로
나간다 — 같은 템플릿의 기체는 C 파일이 바이트 동일하고(구조 지문 하나) 이미지만 다르다(파라미터 지문).
응답에 이미지(base64)와 사람이 읽는 목록을 함께 싣는다.

**조립을 재현하지 않는다.** `assemble_law(standard=True)`(기체 프로파일) → `law.init(dt)` → `law.runner`가
`flight/generate.py`와 완전히 같은 경로다. 여기서 `fcl_graph(...)`를 따로
부르면 게인·타면 한계·마진이 또 한 곳에 적히고 한쪽만 고치면 조용히 어긋난다
(02 §5.5 중복 정의 금지 — 실제로 generate.py가 그 상태였다가 통합됨).
"""

import base64
import math

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from claw.codegen import emit_c, emit_runtime, param_image
from claw.fcl.assemble import assemble_law
from claw.profile import ProfileError
from claw_server.refs import ProfileRef, profile_echo, profile_error_detail, resolve_profile
from claw.params.registry import REGISTRY
from claw_server.routes.sim import PolyTableIn, TableIn, build_gain_tables, build_scas

router = APIRouter(tags=["codegen"])

# 파일 이름 → 역할. 읽는 순서를 서버가 정해 준다 — 생성물이 10개가 넘으면
# "어디부터 보나"가 곧 사용성이다 (역할축은 MATLAB Embedded Coder 대응).
ROLE_ENTRY = "진입점"
ROLE_TYPES = "자료형"
ROLE_LOADER = "파라미터 로더"
ROLE_TOP = "조립부"
ROLE_PART = "서브시스템"
ROLE_RT = "공용 런타임"


class FlightCodeIn(BaseModel):
    """탑재 C 생성 요청 — 시뮬 요청(SimRunIn)의 법칙 관련 필드만 추린 것."""

    profile: ProfileRef | None = None  # 기체 선택 — 없으면 예제 기체 (02 §5.6)
    control_hz: float = Field(100.0, gt=0, le=1000)
    with_schedule: bool = True
    with_limiter: bool = True
    autopilot: dict | None = None
    scas: dict | None = None  # {'pitch': ScasAxis kwargs, …} — SimRunIn과 같은 계약
    # 편집 테이블 또는 다항 스케줄 (kind='poly' 태그) — SimRunIn과 같은 계약
    gain_tables: dict[str, TableIn | PolyTableIn] | None = None

    @field_validator("scas")
    @classmethod
    def _axes_finite_leaves(cls, v):
        """축 dict 한 겹 아래의 유한성만 — 키·타입·범위는 build_scas의 ParamDef 몫."""
        if v is not None:
            for axis, kwargs in v.items():
                if not isinstance(kwargs, dict):
                    raise ValueError(f"scas.{axis}는 파라미터 dict여야 함: {kwargs!r}")
                for key, val in kwargs.items():
                    if isinstance(val, float) and not math.isfinite(val):
                        raise ValueError(f"비유한값 파라미터: scas.{axis}.{key}={val}")
        return v

    @field_validator("autopilot")
    @classmethod
    def _finite_leaves_only(cls, v):
        """타입·범위·키 판정은 엔진 ParamDef 몫(아래 REGISTRY.create) — 서버는
        경계 유한성만. NaN은 ParamDef 범위 비교를 조용히 통과한다 (sim.py와 동일 정책)."""
        if v is not None:
            for key, val in v.items():
                leaves = val if isinstance(val, (list, tuple)) else (val,)
                for x in leaves:
                    if isinstance(x, float) and not math.isfinite(x):
                        raise ValueError(f"비유한값 파라미터: {key}={val!r}")
        return v

    @field_validator("gain_tables")
    @classmethod
    def _tables_not_empty(cls, v):
        if v is not None and not v:
            raise ValueError("gain_tables가 빈 dict — 편집 없음이면 필드를 생략하세요")
        return v


def _role(name: str, base: str) -> str:
    if name.startswith("claw_rt."):
        return ROLE_RT
    stem = name.rsplit(".", 1)[0]
    if stem == f"{base}_types":
        return ROLE_TYPES
    if stem == f"{base}_params":
        return ROLE_LOADER
    if stem == base:
        return ROLE_ENTRY if name.endswith(".h") else ROLE_TOP
    return ROLE_PART


def _order_key(name: str, base: str, groups: list[str]) -> tuple:
    """읽는 순서: 진입점 → 자료형 → 조립부 → 서브시스템(실행 순서) → 파라미터 로더 → 공용."""
    role = _role(name, base)
    rank = {
        ROLE_ENTRY: 0, ROLE_TYPES: 1, ROLE_TOP: 2,
        ROLE_PART: 3, ROLE_LOADER: 4, ROLE_RT: 5,
    }[role]
    sub = 0
    if role == ROLE_PART:
        stem = name.rsplit(".", 1)[0]
        group = stem[len(base) + 1:]
        sub = groups.index(group) if group in groups else len(groups)
    # 같은 짝은 .h를 먼저 — 무엇을 받아 무엇을 내는지가 먼저 잡힌다
    return (rank, sub, 0 if name.endswith(".h") else 1, name)


def build_flight_law(req: FlightCodeIn, profile):
    """요청 형상 → 초기화된 법칙 — 이 라우트와 /verify/flight가 같은 조립을 쓴다.

    구성 오류(미정의 게인 키·범위 이탈 등)는 엔진이 ValueError로 내고 422가 된다.
    조립이 두 곳에 적히면 "화면에 보인 코드"와 "검증한 코드"가 갈라진다 (02 §5.5).
    표준 템플릿으로 조립한다(v1.12) — 템플릿으로 낼 수 없는 기체(배분 표 없음 등)는 TemplateError(ValueError)라 422다.
    """
    dt = 1.0 / req.control_hz
    try:
        gain_tables = build_gain_tables(req.gain_tables)  # 구간 검증도 엔진 → 422
        return assemble_law(
            profile,
            with_schedule=req.with_schedule,
            with_limiter=req.with_limiter,
            # 부분 지정은 이 기체의 설계값 위에 덧댄다 — ParamDef 기본값(구 합성 기체의 설계값)
            # 위가 아니다. 시뮬 라우트와 같은 규칙이라야 화면의 C와 날린 법칙이 같다
            autopilot=(
                REGISTRY.create("fcl", "Autopilot", {**profile.autopilot_params(), **req.autopilot})
                if req.autopilot else None
            ),
            scas=build_scas(req.scas),
            gain_tables=gain_tables,
            standard=True,
        ).init(dt)
    except ProfileError as e:  # 기체 문서가 짚는 오류(게인 미설계 등) — 경로 동봉 422, verify/flight도 이 길로 온다
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    except (ValueError, TypeError) as e:  # 엔진 구성 검증 → 422 (sim.py와 같은 정책)
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/codegen/flight")
def flight_code(req: FlightCodeIn, request: Request) -> dict:
    """현재 형상의 탑재 제어법칙 C — {파일명, 역할, 줄수, 본문} 목록 + 파라미터 이미지."""
    dt = 1.0 / req.control_hz
    profile = resolve_profile(request, req.profile)
    law = build_flight_law(req, profile)

    runner = law.runner
    module = emit_c(runner.graph, runner)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))
    try:
        image = param_image.pack(module, lineage=profile.fingerprint)
    except ValueError as e:  # 의미 검사 실패(lo > hi 등) — 이미지를 만들지 않는다
        raise HTTPException(status_code=422, detail=str(e))

    base = runner.graph.name
    groups = [g for g, _nodes in runner.graph.partitions]
    names = sorted(files, key=lambda n: _order_key(n, base, groups))
    stem = profile.id + (f"-{profile.variant}" if profile.variant else "")
    return {
        "artifact": base,
        "dt": dt,
        "structure_fingerprint": module.structure_fingerprint,
        "param_fingerprint": module.param_fingerprint,
        "template": law.template,
        "groups": groups,
        "profile": profile_echo(profile),
        "param_image": {
            "name": f"{stem}.bin",
            "bytes": len(image),
            "crc32": param_image.unpack(image, module)["crc32"],
            "checks": param_image.checks(module),
            "listing": param_image.listing(module, image, title=f"{base} — {profile.name} ({stem})"),
            "base64": base64.b64encode(image).decode("ascii"),
        },
        "files": [
            {
                "name": n,
                "role": _role(n, base),
                "lines": files[n].count("\n"),
                "text": files[n],
            }
            for n in names
        ],
    }
