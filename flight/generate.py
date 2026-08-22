"""flight/gen/ 재생성 — 탑재 제어법칙 C 산출물의 정본 생성 경로.

    python flight/generate.py

산출물은 **커밋한다**. FCC팀에 넘어가 신뢰성 시험을 거치고 그대로 실리는 물건이라
리뷰 이력이 남아야 하고, "재생성했더니 달라졌다"가 곧 실제 설계 변경이어야 하기
때문이다. 생성은 결정적이라(시각 미포함) 변경이 없으면 바이트 단위로 동일하다 —
`tests/test_parity.py`가 커밋본과 즉석 생성본이 같은지 검사한다.

증분 A 범위: SCAS 두 축만. 나머지 제어법칙(오토파일럿·리미터·믹서·스케줄·최상위
조립)은 IR로 표현한 뒤 여기 추가된다 (플랜 증분 B).
"""

import sys
from pathlib import Path

from claw.codegen import GraphRunner, emit_c, scas_axis_graph
from claw.fcl.demo import DEMO_PITCH, DEMO_YAW

GEN_DIR = Path(__file__).resolve().parent / "gen"

# 제어 주기 — 시뮬 기본값 control_hz=100 Hz(simulator.py:42)와 같아야 한다.
# 이산 계수가 이 주기로 구워지므로 dt는 형상의 일부다 (지문에 포함).
DT = 0.01

# 데모 게인 스케줄이 실제로 덮어쓰는 게인만 신호(포트)가 된다.
# make_demo_gain_tables()는 pitch.kp·ki·k_rate와 roll.*만 낸다 — 요축은 없다
# (demo.py:36). 그래서 피치는 게인이 포트, 요는 상수 파라미터가 된다.
ARTIFACTS = (
    ("scas_pitch", DEMO_PITCH, ("kp", "ki", "k_rate")),
    ("scas_yaw", DEMO_YAW, ()),
)


def build() -> dict:
    """{파일명: 내용} — 디스크를 건드리지 않는다 (테스트가 커밋본과 대조할 때 쓴다)."""
    files = {}
    for name, cfg, scheduled in ARTIFACTS:
        graph = scas_axis_graph(name, scheduled=scheduled, **cfg)
        runner = GraphRunner(graph, DT)
        files.update(emit_c(graph, runner))
    return files


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
