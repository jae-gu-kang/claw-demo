"""비행모드 — 선언적 모드 테이블 + 실행기(sequencer) [확정 01 §3.3.1].

각 모드(ModeSpec)는 {활성 명령(speed/alt|pitch|hdot/heading), 이탈조건, next}를
선언한다. Stateflow식 상태머신 없음 — 비행단계가 대부분 순차 진행이므로 테이블로
충분, diff·웹 편집에 유리. 진입조건은 순차 체인(이전 모드의 이탈 → next)으로 대체
[기본값 — 진입·이탈 조건 상세는 01 §3.3.1 TBD].

이탈조건은 직렬화 가능한 튜플 DSL (웹 UI 편집 대상):
    ("always",) ("time_ge", s) ("alt_ge", m) ("alt_le", m)
    ("speed_ge", m/s) ("speed_le", m/s) ("hdot_ge", m/s) ("hdot_le", m/s)
    ("path_done",) ("on_ground",) ("airborne",) ("off_rail",)
time_ge는 모드 체류 시간(진입 시점부터), path_done은 웨이포인트 소진,
on_ground/airborne은 착륙장치 접지 여부, off_rail은 발사 레일 이탈 —
셋 다 항법에 없는 정보라 시뮬이 ctx로 주입한다. **airborne은 레일 이탈이 아니다**:
레일 위에서는 레일이 받치고 기어는 닿지 않으므로 airborne이 t=0부터 참이다.
hdot은 승강률(상승 +)이라 강하 −4 m/s보다 가파른 것은 ("hdot_le", -4.0)이다.
전환은 스텝당 1회 [기본값] (100 Hz에서 충분). next=None은 종단 모드(유지).
"""

from dataclasses import dataclass

import numpy as np

# kind → 인자 개수 — 구성 시 검증과 평가가 같은 테이블 공유 (드리프트 방지)
_COND_ARITY = {
    "always": 0,
    "time_ge": 1,
    "alt_ge": 1,
    "alt_le": 1,
    "speed_ge": 1,
    "speed_le": 1,
    "hdot_ge": 1,
    "hdot_le": 1,
    "path_done": 0,
    "on_ground": 0,
    "airborne": 0,
    "off_rail": 0,
}

# 종방향 지령 축 — 셋 다 θ_cmd로 가므로 **동시에 켤 수 없다**
LON_AXES = ("alt", "pitch", "hdot")


def validate_condition(cond) -> None:
    """조건 튜플의 kind·인자 개수·인자 타입 검증 — 웹 편집 입력의 방어선.

    구성 시 호출 — 잘못된 조건이 배치 시뮬 도중 IndexError/TypeError로
    터지지 않도록 여기서 시끄럽게 거부한다.
    """
    if not cond or cond[0] not in _COND_ARITY:
        raise ValueError(f"미정의 조건: {cond!r} (허용: {sorted(_COND_ARITY)})")
    n = _COND_ARITY[cond[0]]
    if len(cond) != n + 1:
        raise ValueError(f"조건 {cond[0]!r}: 인자 {n}개 필요, {len(cond) - 1}개 받음")
    for v in cond[1:]:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"조건 {cond[0]!r}: 수치 인자 필요, {v!r} 받음")


def eval_condition(cond, nav, ctx) -> bool:
    """조건 튜플 평가.

    nav: NavOutput, ctx: {"t_mode", "path_done", "on_ground", "on_rail"}.
    ctx의 on_ground·on_rail은 **None이 곧 판정 불가**다 — 그 형상이 아니면 시뮬이
    None을 넣고, 조건은 False로 눙치는 대신 RuntimeError로 멈춘다.
    """
    kind = cond[0]
    if kind == "always":
        return True
    if kind == "time_ge":
        return ctx["t_mode"] >= cond[1]
    if kind == "alt_ge":
        return -float(nav.pos_n[2]) >= cond[1]
    if kind == "alt_le":
        return -float(nav.pos_n[2]) <= cond[1]
    if kind == "speed_ge":
        return float(np.linalg.norm(nav.vel_n)) >= cond[1]
    if kind == "speed_le":
        return float(np.linalg.norm(nav.vel_n)) <= cond[1]
    # 승강률은 NED 하방 +를 뒤집은 값 — 상승이 +다 (지령 hdot과 같은 부호 규약)
    if kind == "hdot_ge":
        return -float(nav.vel_n[2]) >= cond[1]
    if kind == "hdot_le":
        return -float(nav.vel_n[2]) <= cond[1]
    if kind == "path_done":
        return bool(ctx["path_done"])
    if kind == "off_rail":
        # 레일 이탈 — 발사 구성이 아니면 판정 불가다. False로 눙치면 "아직 레일 위"라는
        # 없는 사실을 주장하며 모드가 그 자리에 영원히 멈춘다.
        rail = ctx.get("on_rail")
        if rail is None:
            raise RuntimeError(
                "조건 'off_rail': 발사 레일이 없다 — launch 없이 실행됐는지 확인"
            )
        return not bool(rail)
    if kind in ("on_ground", "airborne"):
        # 접지는 항법 출력에 없는 정보다 — 시뮬이 착륙장치에서 읽어 ctx로 넣는다.
        # 미장착이면 None이고, 그때 이 조건은 **판정 불가**라 절대 참이 되지 않는다:
        # False로 눙치면 "접지하지 않았다"는 없는 사실을 주장하게 되고, 모드 체인이
        # 조용히 그 자리에 멈춘다. 구성 시점 가드(Guidance)가 이 상황을 먼저 막는다.
        wow = ctx.get("on_ground")
        if wow is None:
            raise RuntimeError(
                f"조건 {kind!r}: 접지 정보가 없다 — 착륙장치 없는 기체로 실행됐는지 확인"
            )
        return bool(wow) if kind == "on_ground" else not bool(wow)
    raise ValueError(f"미정의 조건: {cond!r}")


def validate_longitudinal(mode) -> None:
    """종방향 축 배타 검증 — alt·pitch·hdot 중 최대 하나.

    셋 다 θ_cmd로 흘러가므로 둘을 켜면 누가 이기는지를 어딘가에 정해야 하고, 그
    순간 화면은 "무엇이 먹었는지"를 말할 수 없게 된다. 우선순위를 두는 대신
    구성 시점에 거부한다 — heading·alt가 "path" 문자열로 축마다 출처를 고르는
    기존 규약(guidance.py)과 같은 정신이고, 이번엔 그것을 검증으로 못박는다.
    """
    on = [ax for ax in LON_AXES if getattr(mode, ax) is not None]
    if len(on) > 1:
        raise ValueError(
            f"모드 {mode.name!r}: 종방향 축은 하나만 — {on}이 동시에 켜졌다 "
            f"(셋 다 θ_cmd로 간다)"
        )


@dataclass(frozen=True)
class ModeSpec:
    """모드 선언 — 명령 None은 해당 축 비활성(오토파일럿 홀드).

    heading·alt는 수치 또는 "path" — "path"면 그 축의 명령을 경로추종기가 낸다
    (guidance.py). 두 축이 같은 규약을 쓰므로 "경로와 모드 중 누가 이기나"라는
    우선순위 규칙이 따로 없다: 모드 테이블이 축마다 출처를 고르는 쪽이다.

    종방향은 alt·pitch·hdot 셋이 같은 자리(θ_cmd)를 놓고 겨루므로 **최대 하나만**
    켤 수 있다(validate_longitudinal). pitch는 발사 이탈 자세·지상 자세처럼 고도
    루프를 거칠 이유가 없는 구간에, hdot은 접근 강하율·플레어처럼 고도가 아니라
    내려가는 속도를 잡아야 하는 구간에 쓴다.
    """

    name: str
    speed: float | None = None
    alt: object = None  # float | "path"(경로추종 고도) | None
    heading: object = None  # float | "path"(경로추종 헤딩) | None
    pitch: float | None = None  # [rad] θ 직접 지령
    hdot: float | None = None  # [m/s] 승강률 지령 (상승 +)
    exit_when: tuple = ("always",)
    next: str | None = None


class ModeSequencer:
    """모드 테이블 실행기 — 이탈조건 충족 시 next로 전환 (스텝당 1회)."""

    def __init__(self, modes, initial: str | None = None):
        if not modes:
            raise ValueError("모드 테이블이 비었음")
        self._modes = {m.name: m for m in modes}
        if len(self._modes) != len(modes):
            raise ValueError("모드 이름 중복")
        for m in modes:
            if m.next is not None and m.next not in self._modes:
                raise ValueError(f"모드 {m.name!r}의 next {m.next!r} 미정의")
            validate_condition(m.exit_when)
            validate_longitudinal(m)
        self._initial = initial if initial is not None else modes[0].name
        if self._initial not in self._modes:
            raise ValueError(f"초기 모드 {self._initial!r} 미정의")
        self.reset()

    def reset(self) -> None:
        self._name = self._initial
        self._entry_t = None  # 첫 스텝의 t가 초기 모드 진입 시각

    @property
    def mode(self) -> str:
        return self._name

    def step(self, nav, t, path_done, on_ground=None, on_rail=None) -> ModeSpec:
        if self._entry_t is None:
            self._entry_t = float(t)
        ctx = {
            "t_mode": float(t) - self._entry_t,
            "path_done": path_done,
            "on_ground": on_ground,
            "on_rail": on_rail,
        }
        cur = self._modes[self._name]
        if cur.next is not None and eval_condition(cur.exit_when, nav, ctx):
            self._name = cur.next
            self._entry_t = float(t)
            cur = self._modes[self._name]
        return cur
