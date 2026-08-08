"""게인 스케줄 (01 §3.4) — Mach·고도·연료 [확정] 테이블 조회 + 변수 필터링.

- 테이블: M3 Table, 축은 스케줄 변수 {mach, alt, fuel}의 부분집합 (1D~3D)
- [기본값] 외삽 금지: extrapolate='clip' (경계값 고정) — 생성 시 강제 검증
- [기본값] 스케줄 변수 1차 필터링 — 게인 채터링 방지. 첫 스텝은 측정으로
  시드(무과도). filter_tau=0이면 통과
- 게인 이름은 점 네임스페이스 "그룹.게인"(예: "pitch.kp") → step()이
  {"pitch": {"kp": v}} 중첩 dict로 반환, Scas/Autopilot의 스텝 게인
  덮어쓰기 인자에 그대로 전달된다 (M7 조립 경로)
- 스케줄 검증 요구(01 §3.4 [확정]) 중 '게인 테이블 불연속 검출'은
  max_adjacent_jump() — 설계 시 점검용. 보간 구간 마진 재계산은 M10
  마진 맵 재사용 (분석 측)
"""

from claw.fcl.autopilot import CommandFilter
from claw.tables import Table

SCHED_VARS = ("mach", "alt", "fuel")


class GainSchedule:
    def __init__(self, tables: dict, filter_tau: float = 0.5):
        if filter_tau < 0:
            raise ValueError(f"filter_tau는 음수 불가: {filter_tau}")
        for name, tab in tables.items():
            if "." not in name:
                raise ValueError(f"게인 이름은 '그룹.게인' 형식 필요: {name!r}")
            if not isinstance(tab, Table):
                raise ValueError(f"{name}: Table 필요, {type(tab).__name__} 받음")
            extra = set(tab.axis_names) - set(SCHED_VARS)
            if extra:
                raise ValueError(f"{name}: 스케줄 변수 아님 {sorted(extra)} (허용: {SCHED_VARS})")
            if tab.extrapolate != "clip":
                raise ValueError(
                    f"{name}: 외삽 금지 원칙 — extrapolate='clip' 필요, {tab.extrapolate!r} 받음"
                )
        self.tables = dict(tables)
        self.filter_tau = filter_tau
        self._filters = {v: CommandFilter(filter_tau) for v in SCHED_VARS}

    def init(self, dt: float) -> "GainSchedule":
        self.dt = dt
        for f in self._filters.values():
            f.init(dt)
        return self

    def reset(self) -> None:
        for f in self._filters.values():
            f.reset()

    def step(self, mach, alt, fuel) -> dict:
        """필터링된 스케줄 변수로 전 테이블 조회 → 중첩 게인 dict."""
        raw = {"mach": mach, "alt": alt, "fuel": fuel}
        vals = {v: self._filters[v].step(raw[v], raw[v]) for v in SCHED_VARS}
        out: dict = {}
        for name, tab in self.tables.items():
            grp, key = name.split(".", 1)
            out.setdefault(grp, {})[key] = tab.interp(
                **{ax: vals[ax] for ax in tab.axis_names}
            )
        return out


def max_adjacent_jump(table: Table) -> dict:
    """축별 인접 격자점 간 최대 |Δ게인| — 게인 테이블 불연속 검출 (01 §3.4).

    임계값 판단은 호출자(설계자) 소관 — 여기서는 정량만 보고한다.
    """
    import numpy as np

    out = {}
    for i, name in enumerate(table.axis_names):
        out[name] = float(np.max(np.abs(np.diff(table.data, axis=i))))
    return out
