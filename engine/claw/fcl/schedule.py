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

from claw.codegen.ir_exec import GraphRunner
from claw.fcl.graphs import SCHEDULABLE, gain_schedule_graph
from claw.tables import Table

SCHED_VARS = ("mach", "alt", "fuel")

# AP 축의 설계 게인은 **이름이 다르다** — 그래프 조립(fcl/graphs.py autopilot_nodes)이
# kp=kp_alt, ki=ki_alt, k_rate=k_hdot으로 넘기는 그 대응이다. 특히 alt.k_rate는
# 승강률 댐핑 k_hdot 자리다. 이 표가 낡으면 웹이 엉뚱한 "고정값"을 보여 주므로
# test_fcl_schedule이 그래프가 실제로 방출한 상수와 대조해 핀한다.
AP_GAIN_FIELD = {
    ("speed", "kp"): "kp_spd", ("speed", "ki"): "ki_spd",
    ("alt", "kp"): "kp_alt", ("alt", "ki"): "ki_alt", ("alt", "k_rate"): "k_hdot",
    ("heading", "kp"): "kp_hdg", ("heading", "ki"): "ki_hdg",
}


def design_gains(scas_cfg: dict, ap_cfg: dict) -> dict:
    """스케줄 가능한 자리 → 설계점 상수 ("그룹.게인" → float).

    스케줄을 **끄면** 그 자리가 이 값으로 굳는다 — 생성 C에서 룩업이 사라지고
    상수로 접힌다. 그래서 "이 게인을 스케줄에서 빼면 뭐가 되나"의 답이 이 값이다.
    자리 목록은 `fcl/graphs.py` SCHEDULABLE이 정본 (선언 순서 유지).
    """
    out = {}
    for group, keys in SCHEDULABLE.items():
        for key in keys:
            out[f"{group}.{key}"] = float(
                scas_cfg[group][key] if group in scas_cfg else ap_cfg[AP_GAIN_FIELD[group, key]]
            )
    return out


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
        # 실제로 쓰이는 스케줄 변수만 필터를 갖는다 — 구조는 fcl/graphs.py가 정본
        self.used_vars = tuple(
            v for v in SCHED_VARS if any(v in t.axis_names for t in self.tables.values())
        )

    def init(self, dt: float) -> "GainSchedule":
        self.dt = dt
        self._runner = GraphRunner(
            gain_schedule_graph(tables=self.tables, filter_tau=self.filter_tau), dt
        )
        self.reset()
        return self

    def reset(self) -> None:
        self._runner.reset()

    def step(self, mach, alt, fuel) -> dict:
        """필터링된 스케줄 변수로 전 테이블 조회 → 중첩 게인 dict."""
        raw = {"mach": mach, "alt": alt, "fuel": fuel}
        flat = self._runner.step_all(**{v: float(raw[v]) for v in self.used_vars})
        out: dict = {}
        for name in self.tables:
            grp, _, key = name.partition(".")
            out.setdefault(grp, {})[key] = flat[f"{grp}_{key}"]
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
