"""flight/gen/ 재생성 — 탑재 제어법칙 C 산출물의 정본 생성 경로.

    python flight/generate.py

산출물은 **커밋한다**. FCC팀에 넘어가 신뢰성 시험을 거치고 그대로 실리는 물건이라
리뷰 이력이 남아야 하고, "재생성했더니 달라졌다"가 곧 실제 설계 변경이어야 하기
때문이다. 생성은 결정적이라(시각 미포함) 변경이 없으면 바이트 단위로 동일하다 —
`tests/test_parity.py`가 커밋본과 즉석 생성본이 같은지 검사한다.

산출물 둘:
  fcl       데모 형상의 **제어법칙 전체** — 게인 스케줄·오토파일럿·α 리미터·SCAS
            3축·엘레본 믹싱. 항법 무효 시 직전 출력 유지까지 포함한다. 이것이
            FCC에 넘어가는 물건이다
  scas_yaw  SCAS 요축 하나 — 단일 출력 반환 경로와 워시아웃을 덮는 최소 단위.
            fcl이 다중 출력·구조체 경로만 쓰므로 두 경로 모두 대조되도록 남긴다
"""

import sys
from pathlib import Path

from claw.codegen import GraphRunner, emit_c, emit_runtime
from claw.fcl.graphs import fcl_graph, scas_axis_graph
from claw.fcl.autopilot import Autopilot
from claw.fcl.demo import DEMO_PITCH, DEMO_ROLL, DEMO_YAW, make_demo_gain_tables
from claw.plant import make_demo_stall_table

GEN_DIR = Path(__file__).resolve().parent / "gen"

# 제어 주기 — 시뮬 기본값 control_hz=100 Hz(simulator.py:42)와 같아야 한다.
# 이산 계수가 이 주기로 구워지므로 dt는 형상의 일부다 (지문에 포함).
DT = 0.01

# 데모 믹서 — make_demo_fcl(demo.py:70)의 Mixer(k_diff_thr=0.1) + 타면 한계 기본값
DEMO_MIXER = dict(
    elevon_lo=-0.35, elevon_hi=0.35, rudder_lo=-0.35, rudder_hi=0.35, k_diff_thr=0.1
)
ALPHA_MARGIN = 0.05  # limiter.py — 실속 보호마진 [기본값] 01 §3.6


def fcl_demo_graph():
    """데모 기체 형상의 제어법칙 전체 — `fcl/demo.py:52 make_demo_fcl()`과 1:1."""
    return fcl_graph(
        autopilot={d.name: d.default for d in Autopilot.PARAM_DEFS},
        scas_axes={"pitch": dict(DEMO_PITCH), "roll": dict(DEMO_ROLL), "yaw": dict(DEMO_YAW)},
        mixer=DEMO_MIXER,
        stall_table=make_demo_stall_table(),
        alpha_margin=ALPHA_MARGIN,
        gain_tables=make_demo_gain_tables(),
        filter_tau=0.5,
    )


def scas_yaw_graph():
    return scas_axis_graph("scas_yaw", **DEMO_YAW)


ARTIFACTS = {"fcl": fcl_demo_graph, "scas_yaw": scas_yaw_graph}


def _emit_all():
    """(파일, 산출물별 컴파일 단위) — 공용 런타임은 **헬퍼 합집합으로 한 번** 만든다.

    산출물마다 claw_rt를 따로 내면 나중에 나온 쪽(헬퍼가 적은 scas_yaw)이 덮어써
    fcl 링크가 조용히 깨진다. 합집합이 아니면 안 되는 자리다.
    """
    files, sources, helpers = {}, {}, set()
    for name, build_graph in ARTIFACTS.items():
        graph = build_graph()
        module = emit_c(graph, GraphRunner(graph, DT))
        files.update(module.files)
        helpers |= module.helpers
        sources[name] = sorted(f for f in module.files if f.endswith(".c"))
    runtime = emit_runtime(helpers)
    files.update(runtime)
    shared = sorted(f for f in runtime if f.endswith(".c"))
    return files, {n: srcs + shared for n, srcs in sources.items()}


def build() -> dict:
    """{파일명: 내용} — 디스크를 건드리지 않는다 (테스트가 커밋본과 대조할 때 쓴다)."""
    return _emit_all()[0]


def manifest() -> dict:
    """{산출물: 컴파일할 .c 목록} — 대조 하네스 빌드가 쓴다.

    기능축 분할로 파일이 늘어나므로 목록을 손으로 적으면 새 파티션이 조용히 빠진다.
    """
    return _emit_all()[1]


def main() -> int:
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    files = build()
    changed = []
    for name, text in sorted(files.items()):
        path = GEN_DIR / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            changed.append(name)
    stale = sorted(p.name for p in GEN_DIR.glob("*.[ch]") if p.name not in files)
    for name in stale:
        print(f"남은 산출물(그래프에서 사라짐): {name} — 확인 후 삭제할 것")
    print(f"{len(files)}개 중 {len(changed)}개 갱신" + (f": {changed}" if changed else " (변경 없음)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
