"""트림 저장소 — 수평비행 트림 해의 누적 계산 결과 (05 §11.8 「트림·모델 저장소」).

키는 (트림 지문, "level", r9(mach), r9(alt), r9(fuel)) — 트림 지문 = 플랜트 + 풀이 설정(solver)이라 판정선(기준
criteria.trim_margin)을 바꿔도 같은 키다. 저장하는 것은 **풀이 결과**(z = (α, δe, thr) · SLSQP 성공 · 비용 · 수렴 ·
시드 출처)뿐이고, 판정(flags·reserve·continuity_ok)은 재사용 때 지금 기준으로 다시 세운다(trim.assemble_level) —
판정선만 바뀐 점을 다시 풀지 않되 옛 판정을 들고 오지 않게.

- 수렴 여부와 무관하게 저장한다(계산 실패도 기록이다). 재사용 정책 "converged"는 수렴 기록만 꺼내 쓴다.
- 먼저 쓴 수렴 기록이 이긴다 — 서펜타인 인접 시드라 경로마다 해가 조금 다를 수 있어, 덮어쓰면 같은 키가 요청마다
  다른 해를 낸다. 미수렴 기록은 뒤의 수렴 기록이 대체한다.
- 프로세스 메모리 LRU(max_entries, 0 = 꺼짐) — 영속하지 않는다. 락은 dict 조작만 감싸고 풀이는 밖에서 한다.
- 분산(섭동) 기체·지상 평형은 대상이 아니다 — 트림 지문이 섭동을 모르고(trim_batch가 거부), 지상 평형은 다른 미지수다.
"""

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field


def _r(x: float) -> float:
    return round(float(x), 9)  # opspace.basegrid._r와 같은 반올림 — 기본 격자 좌표와 같은 키가 되게


def case_key(case) -> tuple | None:
    """조건 식별자 — 수평비행만. 다른 조건은 None(저장·조회 대상 아님)."""
    if str(case.condition) != "level":
        return None
    return ("level", _r(case.mach), _r(case.alt), _r(case.fuel))


@dataclass(frozen=True)
class TrimRecord:
    """풀이 결과 한 건. converged = 풀이 당시 trim_level의 수렴(SLSQP 성공 ∧ 잔차) — 잔차 허용치는 트림 지문 안이라
    같은 키에서는 다시 재도 같다. seed = {"kind": "cold"|"neighbour", "from": 시드 케이스 이름|None}."""

    z: tuple
    success: bool
    cost: float
    converged: bool
    seed: dict = field(default_factory=lambda: {"kind": "cold", "from": None})
    created: float = field(default_factory=time.time)


class TrimStore:
    """프로세스 전역 LRU. max_entries 0이면 꺼진 저장소(쓰지도 읽지도 않는다)."""

    def __init__(self, max_entries: int = 20000):
        if max_entries < 0:
            raise ValueError(f"max_entries는 0 이상: {max_entries}")
        self.max_entries = int(max_entries)
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def enabled(self) -> bool:
        return self.max_entries > 0

    def scope(self, trim_fingerprint: str) -> "TrimStoreScope":
        if not trim_fingerprint:
            raise ValueError("트림 지문 없이 저장소를 쓸 수 없다")  # 빈 지문이면 모든 기체가 한 키 공간을 나눠 쓴다
        return TrimStoreScope(self, trim_fingerprint)

    def _get(self, key):
        with self._lock:
            rec = self._d.get(key)
            if rec is None:
                self._misses += 1
                return None
            self._d.move_to_end(key)
            self._hits += 1
            return rec

    def _peek(self, key):
        with self._lock:
            return self._d.get(key)  # LRU 순서·통계를 건드리지 않는다(격자 표시용)

    def _put(self, key, record: TrimRecord) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            old = self._d.get(key)
            if old is not None and old.converged:
                self._d.move_to_end(key)
                return False  # 먼저 쓴 수렴 기록이 이긴다
            self._d[key] = record
            self._d.move_to_end(key)
            while len(self._d) > self.max_entries:
                self._d.popitem(last=False)
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._d), "max_entries": self.max_entries, "hits": self._hits,
                    "misses": self._misses}


class TrimStoreScope:
    """한 트림 지문의 창 — trim_batch는 이것만 받는다(지문을 섞을 길을 없앤다)."""

    def __init__(self, store: TrimStore, trim_fingerprint: str):
        self.store = store
        self.trim_fingerprint = trim_fingerprint

    def _key(self, case):
        k = case_key(case)
        return None if k is None else (self.trim_fingerprint, *k)

    def get(self, case) -> TrimRecord | None:
        k = self._key(case)
        return None if k is None or not self.store.enabled else self.store._get(k)

    def peek(self, case) -> TrimRecord | None:
        k = self._key(case)
        return None if k is None else self.store._peek(k)

    def put(self, case, record: TrimRecord) -> bool:
        k = self._key(case)
        return False if k is None else self.store._put(k, record)
