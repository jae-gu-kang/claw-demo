"""시스템 라우트 — 헬스체크 + 컴포넌트 레지스트리/스키마 (웹 폼 자동 생성 원천, 02 §2.3).

레지스트리 검증(validate)은 웹 코드 생성의 원천이기도 하다: 생성 코드가 명명할
파이썬 심볼을 이름 추론이 아니라 엔진 인스턴스에서 직접 얻고(nav/ErrorModel의
실제 클래스는 NavErrorModel — title로 추론 불가), 동시에 ParamDef 범위와 생성자
교차 조건(theta_lo ≤ theta_hi 등)을 실제 엔진으로 판정한다.
"""

import importlib
import math
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

import claw
from claw.params.registry import REGISTRY, RegistryError

from claw_server.routes.world import _terrain_packs

router = APIRouter(tags=["system"])


def deployed_commit() -> str | None:
    """배포된 형상의 커밋 SHA — 없으면 None (지어내지 않는다).

    `version`은 정적 문자열이라 "떠 있는 것이 어느 커밋인가"에 답하지 못한다.
    공개 데모는 /api/health만 무인증이라(auth.py) 그 답을 밖에서 얻을 방법이
    없었고, 배포 확인이 매번 "대시보드를 보세요"로 끝났다.

    CLAW_GIT_COMMIT이 먼저다 — 플랫폼 중립 오버라이드(폐쇄망 반입 등 Render가
    아닌 배포는 이 값을 직접 넣는다 — docs/deploy-airgap.md '운영' 절). Render는 배포마다
    RENDER_GIT_COMMIT을 자동 주입하므로 설정 없이 동작한다. 로컬 실행처럼 둘 다
    없으면 None: "모른다"를 빈 문자열이나 "unknown"으로 위장하면 소비자가
    그것을 SHA로 착각해 비교한다.
    """
    # 프로세스 수명 내내 상수인 값이지만 **요청마다 읽는다** — 모듈 상수로 올리면
    # 라우트가 이 값을 실제로 실어 나르는지 검사할 방법이 사라진다(앱 재생성 없이는
    # 환경을 못 바꾼다). 비용은 헬스 응답 한 번당 dict 조회 하나다
    for name in ("CLAW_GIT_COMMIT", "RENDER_GIT_COMMIT"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return None


@router.get("/health")
def health(request: Request) -> dict:
    # 버전은 생성 코드·리포트의 추적성 메타 (어느 엔진·서버로 뽑은 형상인지).
    # commit은 그 위의 배포 형상 — 이 응답은 **무인증 경로**라 공개된다.
    #
    # 리포가 공개(README의 GitHub 링크)라는 것만으로는 근거가 안 된다: 공개
    # 리포라도 "어느 커밋이 도는지"는 리포를 읽어서 알 수 없다. 실제로 하중을
    # 받는 것은 render.yaml의 autoDeploy — main push에서만 배포되므로 떠 있는
    # SHA가 GitHub에서 이미 보이는 공개 커밋임이 그것으로 보장된다. 배포가 main
    # 보다 뒤처진 동안에만 "여기서 멈춰 있다"가 새로 드러나는데, 그 신호가 곧
    # 이 필드의 값어치다.
    # **재검토 조건은 둘**: ① 리포가 비공개가 되면 (SHA가 안정적 지문이 되어
    # 공개 권고와 대조하면 탐침 없이 미패치 여부가 확정된다) ② 배포 원천이
    # 공개 main이 아니게 되면 (autoDeploy 해제·수동 배포 등)
    # 지형 팩도 같은 이유로 여기 낸다: 가상환경 탭은 인증 뒤에 있어 "지형이 실제로
    # 구워졌는가"가 배포 후에도 무인증으로 확인할 길이 없었다(2026-09-02, 빌드 단계에
    # 지형 생성을 추가한 뒤 실제로 이 질문에 답할 수가 없어서 겪었다). 이름만 내고
    # 바이트는 안 낸다 — 헬스체크가 지형 다운로드 엔드포인트가 될 이유는 없다.
    packs = [p["name"] for p in _terrain_packs()]
    return {
        "status": "ok",
        "version": request.app.version,
        "engine": claw.__version__,
        "commit": deployed_commit(),
        "jobs": len(request.app.state.jobs.list()),
        "world_terrain_packs": packs,
    }


@router.get("/registry")
def registry_index() -> dict:
    """카테고리 → 등록 컴포넌트 이름 목록 (교체 가능 컴포넌트 선택 UI용)."""
    return {c: REGISTRY.names(c) for c in REGISTRY.categories()}


@router.get("/registry/{category}/{name}/schema")
def registry_schema(category: str, name: str) -> dict:
    """컴포넌트 파라미터 JSON 스키마 — 단위·범위 메타 포함 (폼 자동 생성·입력 검증)."""
    try:
        return REGISTRY.schema(category, name)
    except RegistryError as e:
        raise HTTPException(status_code=404, detail=str(e))


class ValidateIn(BaseModel):
    values: dict = {}

    @field_validator("values")
    @classmethod
    def _finite_leaves(cls, v):
        """경계 유한성만 — 타입·범위·미정의 키는 레지스트리 ParamDef가 판정.
        NaN은 범위 비교(v < lo 등)를 조용히 통과하므로 여기서 차단해야 한다
        (sim.py::_finite_leaves_only와 동일 정책, 02 v0.11)."""
        for key, val in v.items():
            leaves = val if isinstance(val, (list, tuple)) else (val,)
            for x in leaves:
                if isinstance(x, float) and not math.isfinite(x):
                    raise ValueError(f"비유한값 파라미터: {key}={val!r}")
        return v


def _shortest_import(cls) -> str:
    """클래스를 재노출하는 가장 짧은 패키지 경로 — 생성 코드의 import 문.

    claw.fcl.autopilot.Autopilot → 부모 claw.fcl이 재노출하면 "claw.fcl".
    재노출 여부를 실제 임포트로 확인하므로 추측이 아니며, 없으면 정의 모듈로
    안전 폴백한다 (엔진 패키지 재구성에도 생성 코드가 계속 실행 가능)."""
    parts = cls.__module__.split(".")
    for depth in range(1, len(parts)):
        candidate = ".".join(parts[:depth])
        try:
            mod = importlib.import_module(candidate)
        except ImportError:
            continue
        if getattr(mod, cls.__name__, None) is cls:
            return candidate
    return cls.__module__


@router.post("/registry/{category}/{name}/validate")
def registry_validate(category: str, name: str, req: ValidateIn) -> dict:
    """편집값을 엔진으로 실제 구성해 검증 + 생성 코드가 명명할 심볼 회신 (웹 코드 생성).

    부분 지정은 ParamDef 기본값이 보충된다 — 구성이 서면 그 값 조합은 실행 가능."""
    try:
        obj = REGISTRY.create(category, name, req.values or None)
    except RegistryError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, TypeError) as e:  # ParamError ⊂ ValueError — sim.py와 동일 매핑
        raise HTTPException(status_code=422, detail=str(e))
    cls = type(obj)
    return {
        "ok": True,
        "py_class": cls.__name__,
        "py_module": cls.__module__,
        "py_import": _shortest_import(cls),
    }
