"""비행모드 — 선언적 모드 테이블 + 실행기(sequencer) [확정 01 §3.3.1].

각 모드(ModeSpec)는 {활성 명령(speed/alt/heading), 이탈조건, next}를 선언한다.
Stateflow식 상태머신 없음 — 비행단계가 대부분 순차 진행이므로 테이블로 충분,
diff·웹 편집에 유리. 진입조건은 순차 체인(이전 모드의 이탈 → next)으로 대체
[기본값 — 진입·이탈 조건 상세는 01 §3.3.1 TBD].

이탈조건은 직렬화 가능한 튜플 DSL (웹 UI 편집 대상):
    ("always",) ("time_ge", s) ("alt_ge", m) ("alt_le", m)
    ("speed_ge", m/s) ("speed_le", m/s) ("path_done",)
time_ge는 모드 체류 시간(진입 시점부터), path_done은 웨이포인트 소진.
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
    "path_done": 0,
}


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
    """조건 튜플 평가. nav: NavOutput, ctx: {"t_mode": s, "path_done": bool}."""
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
    if kind == "path_done":
        return bool(ctx["path_done"])
    raise ValueError(f"미정의 조건: {cond!r}")


@dataclass(frozen=True)
class ModeSpec:
    """모드 선언 — 명령 None은 해당 축 비활성(오토파일럿 홀드), heading은
    수치[rad] 또는 "path"(경로추종 헤딩)."""

    name: str
    speed: float | None = None
    alt: float | None = None
    heading: object = None  # float | "path" | None
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

    def step(self, nav, t, path_done) -> ModeSpec:
        if self._entry_t is None:
            self._entry_t = float(t)
        ctx = {"t_mode": float(t) - self._entry_t, "path_done": path_done}
        cur = self._modes[self._name]
        if cur.next is not None and eval_condition(cur.exit_when, nav, ctx):
            self._name = cur.next
            self._entry_t = float(t)
            cur = self._modes[self._name]
        return cur
