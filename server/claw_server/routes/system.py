"""시스템 라우트 — 헬스체크 + 컴포넌트 레지스트리/스키마 (웹 폼 자동 생성 원천, 02 §2.3).

레지스트리 검증(validate)은 웹 코드 생성의 원천이기도 하다: 생성 코드가 명명할
파이썬 심볼을 이름 추론이 아니라 엔진 인스턴스에서 직접 얻고(nav/ErrorModel의
실제 클래스는 NavErrorModel — title로 추론 불가), 동시에 ParamDef 범위와 생성자
교차 조건(theta_lo ≤ theta_hi 등)을 실제 엔진으로 판정한다.
"""

import importlib
import math

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

import claw
from claw.params.registry import REGISTRY, RegistryError

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict:
    # 버전은 생성 코드·리포트의 추적성 메타 (어느 엔진·서버로 뽑은 형상인지)
    return {
        "status": "ok",
        "version": request.app.version,
        "engine": claw.__version__,
        "jobs": len(request.app.state.jobs.list()),
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
