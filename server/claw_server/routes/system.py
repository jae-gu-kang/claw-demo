"""시스템 라우트 — 헬스체크 + 컴포넌트 레지스트리/스키마 (웹 폼 자동 생성 원천, 02 §2.3)."""

from fastapi import APIRouter, HTTPException, Request

from claw.params.registry import REGISTRY, RegistryError

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict:
    return {"status": "ok", "jobs": len(request.app.state.jobs.list())}


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
