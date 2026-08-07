"""M2 blocks 공통 프로토콜 — init(dt) → step(u)->y → reset(state) → schema() (구현 문서 §2.2·§2.3).

샘플레이트 최상위 파라미터화 원칙: 생성자는 연속시간 파라미터만 받고, 이산화 계수는
init(dt)가 주기로부터 자동 계산·캐시한다. 같은 인스턴스에 다른 dt로 init()을 다시
호출하면(예: 100→50 Hz 비교) 재이산화되고 상태가 초기화된다.

step()은 init() 이후에만 호출하는 계약 — 실시간 친화 스타일(02 §2.3)로 매 스텝
가드는 두지 않는다.
"""

from claw.params.paramset import ParamSet

UNBOUNDED = 1e30  # 안티와인드업 한계 미지정 시 사용하는 사실상 무한대 상수


class Block:
    NAME = ""
    PARAM_DEFS = ()

    def init(self, dt: float) -> "Block":
        """샘플 주기 dt[s]로 이산화 계수를 계산하고 내부상태를 초기화한다. 체이닝을 위해 self 반환."""
        if dt <= 0:
            raise ValueError(f"dt는 양수여야 함: {dt}")
        self.dt = dt
        self._discretize(dt)
        self.reset()
        return self

    def _discretize(self, dt: float) -> None:
        """연속시간 파라미터 → 이산 계수. 이산화가 불필요한 블록은 기본 no-op을 상속."""

    def step(self, u):
        raise NotImplementedError

    def reset(self, state=None) -> None:
        """state=None이면 초기 파라미터 상태로, 값이면 웜스타트(범프리스 전환 계약)."""

    @classmethod
    def schema(cls) -> dict:
        """이 블록의 파라미터 JSON 스키마 — 레지스트리+스키마 원칙(02 §2.3)."""
        return ParamSet(cls.PARAM_DEFS).to_json_schema(title=cls.NAME or cls.__name__)

    @classmethod
    def register(cls, registry, category: str = "blocks") -> None:
        """M1 ComponentRegistry에 factory(paramset) -> 인스턴스 형태로 등록.

        스키마 키 == 생성자 kwargs 이므로 create()가 cls(**values)로 직결된다.
        """
        registry.register(
            category, cls.NAME or cls.__name__, lambda ps: cls(**ps.as_dict()), cls.PARAM_DEFS
        )
