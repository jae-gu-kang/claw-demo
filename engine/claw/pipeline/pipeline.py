"""M15 — 산출물 의존 DAG + 부분집합 지문 캐시·선택적 무효화 + Δ리포트 (구현 문서 §2.4).

각 노드는 자신이 소비하는 파라미터 접두사(uses)를 선언한다. 노드의 유효 키 =
hash(노드명 + 소비 부분집합 지문 + 의존 노드 유효 키들) — 무관한 파라미터 변경은
캐시를 유지하고(선택적 무효화), 상류 변경은 하류로 전파된다.

uses를 선언한 노드의 fn은 **선언 접두사로 제한된 뷰**를 받는다 — 선언 밖 파라미터
접근은 ParamError로 즉시 실패한다 (선언과 실소비의 불일치 → 조용한 낡은 캐시 방지).
uses 미선언(빈 튜플)이면 전체 스냅샷과 전체 지문을 쓴다 [기본값 — 보수적].
"""

import hashlib

from claw.params.param import ParamError
from claw.params.paramset import canonical_hash


def subset_fingerprint(params, prefixes):
    """접두사로 걸러낸 파라미터 부분집합의 지문. 빈 접두사 = 전체 지문과 동일."""
    values = params.as_dict()
    if prefixes:
        values = {k: v for k, v in values.items() if any(k.startswith(p) for p in prefixes)}
    return canonical_hash(values)


class _SubsetView:
    """uses 접두사로 제한된 읽기 전용 파라미터 뷰."""

    def __init__(self, params, prefixes):
        self._params = params
        self._prefixes = prefixes

    def get(self, name):
        if not any(name.startswith(p) for p in self._prefixes):
            raise ParamError(
                f"노드 uses 선언 밖 파라미터 접근: {name!r} (허용 접두사 {self._prefixes})"
            )
        return self._params.get(name)

    __getitem__ = get

    def as_dict(self):
        return {
            k: v
            for k, v in self._params.as_dict().items()
            if any(k.startswith(p) for p in self._prefixes)
        }

    def fingerprint(self):
        """이 노드가 소비하는 부분집합의 지문 — 산출물 계보용."""
        return canonical_hash(self.as_dict())


class Pipeline:
    def __init__(self):
        self._nodes = {}  # name -> (fn, deps, uses)
        self._cache = {}  # 유효 키 -> 산출물
        self.stats = {}  # name -> 실계산 횟수 (캐시 적중 제외)

    def add(self, name, fn, deps=(), uses=()):
        """fn(params_view, **{의존 노드명: 산출물}) -> 산출물."""
        if name in self._nodes:
            raise KeyError(f"중복 노드: {name}")
        self._nodes[name] = (fn, tuple(deps), tuple(uses))
        self.stats[name] = 0

    def key(self, name, params):
        """노드의 유효 캐시 키 — 소비 부분집합 지문과 의존 키의 합성 해시."""
        if name not in self._nodes:
            raise KeyError(f"미정의 노드: {name}")
        _fn, deps, uses = self._nodes[name]
        parts = [name, subset_fingerprint(params, uses)]
        parts += [self.key(d, params) for d in deps]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def run(self, name, params):
        """노드 실행 — 유효 키가 캐시에 있으면 재계산 없이 반환 (증분 재계산)."""
        k = self.key(name, params)
        if k in self._cache:
            return self._cache[k]
        fn, deps, uses = self._nodes[name]
        dep_results = {d: self.run(d, params) for d in deps}
        view = _SubsetView(params, uses) if uses else params
        result = fn(view, **dep_results)
        self._cache[k] = result
        self.stats[name] += 1
        return result


def delta_report(pipeline, name, params_a, params_b, metrics):
    """변경 전/후 스냅샷의 정량 Δ리포트 — metrics(산출물) -> {이름: 수치}."""
    ma = metrics(pipeline.run(name, params_a))
    mb = metrics(pipeline.run(name, params_b))
    return {
        "param_diff": params_a.diff(params_b),
        "a": ma,
        "b": mb,
        "delta": {key: mb[key] - ma[key] for key in ma},
    }
