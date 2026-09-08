"""IR 신호의 **semantic 타입** 어휘 — 의미·단위·기대 범위 (07 §8).

**타입은 검증을 강화할 뿐, IR에 명시되지 않은 실행 연산을 만들지 않는다.** 이 IR의 성질
("선언 순서 = 실행 순서 = 생성 C 문장 순서")을 보존하기 위한 절대 원칙이다. 그래서 이
모듈은 **두 백엔드가 import하지 않는다** — `ir_exec`도 `emit_c`도 타입을 못 읽으므로
조용히 쓸 수도 없고, 그 사실을 테스트가 `ast`로 단정한다.

**표현형(float32·고정소수점)은 이 축이 아니다.** 여기 있는 것은 "이 신호가 각도인가
각속도인가"이고, "메모리에서 몇 비트인가"는 backend lowering의 몫이다 [백로그 07 §10].
처음부터 float32로 박으면 나중에 DSP/MCU의 Q15로 못 간다.

**미지정(top)은 하나다.** `desc`는 비교에서 빠지므로 이유를 적어 둔 미지정과 안 적은
미지정이 같은 타입이다 — 통일이 `==`로 구현돼도 전제가 안 깨진다 [07 §10].

`unit`을 필드가 아니라 **파생 property**로 둔 것이 이 모듈의 핵심 결정이다. 필드로 두면
`quantity="angle", unit="deg"` 같은 자기모순을 만들 수 있고 그걸 막는 검사가 또 하나
생긴다. `QUANTITY_UNIT` 한 표가 정본이면 그 모순이 **표현 불가능**해진다.

단위 철자는 `conventions.md` §3(내부 계산 SI + rad)의 기계 판독본이고 `ParamDef.unit`과
같은 철자를 쓴다 — 갈라지면 테스트가 시끄럽게 죽는다.
"""

from dataclasses import dataclass, field

KINDS = ("real", "bool", "enum", "vector")

# 물리량 → SI 단위 철자. 이 표가 단위의 정본이다 (conventions §3).
QUANTITY_UNIT = {
    "dimensionless": "-",
    "angle": "rad",
    "angular_rate": "rad/s",
    "airspeed": "m/s",
    "altitude": "m",
    "climb_rate": "m/s",
    "mach": "-",
    "normalized": "-",
    "time": "s",
}


@dataclass(frozen=True)
class Type:
    """신호 하나의 semantic 타입.

    kind      real | bool | enum | vector
    quantity  real 전용 도메인 태그. **None은 미지정(top)** — 무엇과도 통일된다.
              Gain·Lookup·PID는 물리량을 바꾸고 그 변환은 파라미터 단위에 사는데,
              거기까지 추론하려면 완전한 차원해석이 필요하다. 확신하는 것만 거부한다.
    lo, hi    기대 범위 — **분석·계약 검사용 메타데이터일 뿐 아무 힘이 없다.**
              실제 포화는 설계 요소인 Saturation 블록으로만 표현한다. 여기에 힘을
              주는 순간(clamp를 낳는 순간) 그 값은 설계 의도가 아니라 런타임 동작이
              되고, 나중에 고정소수점이 이 값을 스케일 근거로 쓸 수 없게 된다.
    n         vector 길이
    choices   enum 멤버
    """

    kind: str = "real"
    quantity: str | None = None
    lo: float | None = None
    hi: float | None = None
    # **비교에서 뺀다.** frozen dataclass는 전 필드를 `__eq__`/`__hash__`에 넣으므로,
    # 이유를 적어 둔 미지정과 안 적은 미지정이 **서로 다른 타입**이 된다. 그러면 07 §10이
    # 다음 단계의 전제로 세운 "미지정은 무엇과도 통일된다"가 첫 구현(== · dict 키)에서
    # 바로 깨진다 — 게인 포트와 연료가 서로, 그리고 `REAL`과 불일치로 잡힌다.
    # 설명은 사람이 읽는 것이지 타입의 신원이 아니다.
    desc: str = field(default="", compare=False)
    n: int | None = None
    choices: tuple = ()

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"모르는 kind {self.kind!r} — 아는 것: {list(KINDS)}")
        if self.quantity is not None:
            if self.kind != "real":
                raise ValueError(f"quantity는 real 전용인데 kind={self.kind!r}")
            if self.quantity not in QUANTITY_UNIT:
                raise ValueError(
                    f"모르는 물리량 {self.quantity!r} — 아는 것: {sorted(QUANTITY_UNIT)}"
                )
        if self.kind == "enum" and not self.choices:
            raise ValueError("enum은 choices가 있어야 한다")
        if self.choices and self.kind != "enum":
            raise ValueError(f"choices는 enum 전용인데 kind={self.kind!r}")
        if self.kind == "vector" and not (isinstance(self.n, int) and self.n > 0):
            raise ValueError(f"vector는 양의 길이 n이 있어야 한다: {self.n!r}")
        if self.n is not None and self.kind != "vector":
            # 이게 없으면 `Type(kind="real", n=4)`가 vector 금지를 그대로 통과해
            # 길이를 들고 다닌다 — 검사기가 받아 준 거짓 선언이 된다
            raise ValueError(f"n은 vector 전용인데 kind={self.kind!r}")
        # 조건 없이 본다 — 아래 tuple() 강제가 무조건이므로 여기만 조건부면 falsy가
        # 그 사이로 샌다. `choices=None`은 이 저장소의 「미지정」 관용이라 실제로 온다
        if not isinstance(self.choices, (list, tuple)):
            # 문자열은 iterable이라 choices="hold"가 4멤버 enum으로 **조용히** 굳고,
            # 집합은 순회 순서가 불안정해 같은 멤버가 다른 해시를 갖는다 — 튜플 강제가
            # 지키려던 값 의미론이 거기서 깨진다
            raise ValueError(f"choices는 list나 tuple이어야 한다: {self.choices!r}")
        # frozen이라 대입은 이 형태로. 리스트로 주면 해시 불가라 값 의미론이 조용히 깨진다
        object.__setattr__(self, "choices", tuple(self.choices))
        if (self.lo is not None or self.hi is not None) and self.kind not in ("real", "vector"):
            raise ValueError(f"기대 범위는 수치 신호 전용인데 kind={self.kind!r}")
        if self.lo is not None and self.hi is not None and self.lo > self.hi:
            raise ValueError(f"기대 범위가 뒤집혔다: [{self.lo}, {self.hi}]")

    @property
    def unit(self):
        """단위는 **저장하지 않고 물리량에서 파생한다** — 둘이 어긋날 길을 없앤다."""
        return QUANTITY_UNIT[self.quantity] if self.quantity else None

    def __str__(self):
        if self.kind != "real":
            return self.kind
        return self.quantity or "real"


def enum_of(*choices, desc=""):
    return Type(kind="enum", choices=tuple(choices), desc=desc)


def vector_of(n, desc=""):
    return Type(kind="vector", n=n, desc=desc)


# ── 도메인 카탈로그 ──────────────────────────────────────────────────────
# **의도적으로 거칠다.** ANGLE을 자세각/공력각/타면각으로 쪼개고 싶은 유혹이 있지만
# `lim_cap = Sum(theta, a_margin)`(자세각 + α 마진)이 정당한 반례다 — 잘못 쪼개면
# 서버가 편집 형상마다 거부를 낸다. 세분화는 그 반례와 함께 [백로그]다 (07 §10).
#
# **GAIN 타입은 만들지 않는다.** 스케줄 게인은 자리마다 단위가 다르고(kp: -, ki: 1/s,
# k_rate: s) 하나로 묶으면 거짓이 된다. 게인 신호는 REAL(미지정)이고 그게 정직하다.
REAL = Type()  # 물리량 미지정 — top
DIMENSIONLESS = Type(quantity="dimensionless")
ANGLE = Type(quantity="angle")
ANGULAR_RATE = Type(quantity="angular_rate")
AIRSPEED = Type(quantity="airspeed")
ALTITUDE = Type(quantity="altitude")
CLIMB_RATE = Type(quantity="climb_rate")
MACH = Type(quantity="mach")
NORMALIZED = Type(quantity="normalized", lo=0.0, hi=1.0)
BOOL = Type(kind="bool")


def check_declarations(name, signal_types, known):
    """선언의 **형식**만 본다 — 규칙 검사(타입 전파)는 이 단계가 아니다 (07 §10).

    known: 그 그래프가 아는 신호 이름(그래프 입력 + 노드 id). 없는 이름에 타입을 달면
    오타가 조용히 무시되므로 거부한다 — 선언했는데 아무도 안 보는 것이 가장 나쁘다.

    vector는 **어휘에는 있고 백엔드에는 없다.** 선언은 되는데 방출 깊은 곳에서
    터지는 것보다, 선언 시점에 "벡터 백엔드가 없다"고 말하는 쪽이 정직하다.
    """
    for signal, t in signal_types.items():
        if not isinstance(t, Type):
            raise TypeError(f"{name}: {signal!r}의 타입이 Type이 아니다: {t!r}")
        if signal not in known:
            raise ValueError(
                f"{name}: 타입을 선언한 {signal!r}이 그래프 입력도 노드 id도 아니다 "
                "— 출력명이면 그 출력이 가리키는 노드 id에 붙인다"
            )
        if t.kind == "vector":
            raise ValueError(
                f"{name}.{signal}: vector는 아직 백엔드가 없다 — 전 신호가 스칼라다 (07 §10)"
            )
