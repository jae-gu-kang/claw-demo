"""컴포넌트 레지스트리 (구현 문서 §2.3) — 교체 가능 컴포넌트의 등록·생성·스키마 노출.

경로추종 알고리즘, 항법 모델, 적분기 등 대안 구현을 카테고리별로 등록한다.
UI는 schema()로부터 폼을 자동 생성 — 새 컴포넌트 추가 시 UI 코드 수정 불필요.
"""

from claw.params.paramset import ParamSet


class RegistryError(KeyError):
    """레지스트리 등록·조회 오류."""


class ComponentRegistry:
    def __init__(self):
        self._entries = {}  # category -> {name: (factory, param_defs)}

    def register(self, category, name, factory, param_defs=()):
        """factory(paramset) -> 컴포넌트 인스턴스."""
        cat = self._entries.setdefault(category, {})
        if name in cat:
            raise RegistryError(f"이미 등록됨: {category}/{name}")
        cat[name] = (factory, tuple(param_defs))

    def categories(self):
        return sorted(self._entries)

    def names(self, category):
        return sorted(self._entries.get(category, {}))

    def create(self, category, name, values=None):
        factory, defs = self._lookup(category, name)
        return factory(ParamSet(defs, values))

    def schema(self, category, name):
        _, defs = self._lookup(category, name)
        return ParamSet(defs).to_json_schema(title=f"{category}/{name}")

    def param_defs(self, category, name):
        """등록된 ParamDef 튜플 — 단위·설명·범위를 JSON 스키마로 굽기 전 형태로.

        schema()는 desc와 unit을 "설명 [단위]" 한 문자열로 합쳐 놓는다. 그걸 다시
        갈라 쓰는 소비자(M15 영향성 해석)가 생겨서, 되파싱 대신 원본을 낸다.
        """
        _, defs = self._lookup(category, name)
        return defs

    def _lookup(self, category, name):
        try:
            return self._entries[category][name]
        except KeyError:
            raise RegistryError(f"미등록 컴포넌트: {category}/{name}") from None


REGISTRY = ComponentRegistry()  # 전역 기본 레지스트리
