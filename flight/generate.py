"""flight/gen/ 재생성 — 탑재 제어법칙 C 산출물의 정본 생성 경로.

    python flight/generate.py

산출물은 **커밋한다**. FCC팀에 넘어가 신뢰성 시험을 거치고 그대로 실리는 물건이라
리뷰 이력이 남아야 하고, "재생성했더니 달라졌다"가 곧 실제 설계 변경이어야 하기
때문이다. 생성은 결정적이라(시각 미포함) 변경이 없으면 바이트 단위로 동일하다 —
`tests/test_parity.py`가 커밋본과 즉석 생성본이 같은지 검사한다.

산출물 둘:
  fcl       **표준 템플릿 제어법칙 전체**(v1.12) — 게인 스케줄·오토파일럿·α 리미터·SCAS
            3축·엘레본 믹싱. 항법 무효 시 직전 출력 유지까지 포함한다. 이것이
            FCC에 넘어가는 물건이고, 같은 템플릿의 기체는 이 C 한 벌을 나눈다
  scas_yaw  SCAS 요축 하나 — 단일 출력 반환 경로와 워시아웃을 덮는 최소 단위.
            fcl이 다중 출력·구조체 경로만 쓰므로 두 경로 모두 대조되도록 남긴다

값은 C에 없다 — `gen/{산출물}_params.c`가 파라미터 이미지를 적재하는 로더다. 예제 기체의 이미지와 사람이
읽는 목록을 `params/`에 함께 커밋한다(`example-delta.bin`·`.txt`). 다른 기체의 이미지는 같은 C로 즉석에서
만든다(`image_for`) — 구 기체·EO/IR형 패리티가 그렇게 돈다(tests/test_parity.py).
"""

import sys
from pathlib import Path

from claw.codegen import GraphRunner, emit_c, emit_runtime, param_image
from claw.fcl.assemble import assemble_law
from claw.profile import example_profile
from claw.fcl.graphs import scas_axis_graph

GEN_DIR = Path(__file__).resolve().parent / "gen"
PARAMS_DIR = Path(__file__).resolve().parent / "params"
EXAMPLE_IMAGE = "example-delta"  # 제품 예제 기체 id (profile/document.py EXAMPLE_ID)와 같은 이름

# 제어 주기 — 시뮬 기본값 control_hz=100 Hz(simulator.py:42)와 같아야 한다.
# 이산 계수가 이 주기로 구워지므로 dt는 형상의 일부다 (지문에 포함).
DT = 0.01


def fcl_demo_law(profile=None):
    """기체 형상의 **표준 템플릿** 제어법칙 전체 — **조립은 `assemble_law`가 정본**이다.

    여기서 `fcl_graph(...)`를 다시 부르면 게인·타면 한계·마진이 두 곳에 적히고,
    한쪽만 고치면 산출물이 조용히 설계와 달라진다 (02 §5.5 중복 정의 금지).
    서버의 탑재 C 응답도 같은 이유로 이 경로를 쓴다. 기본은 제품 예제 기체다.
    """
    return assemble_law(profile if profile is not None else example_profile(), standard=True).init(DT)


def fcl_demo_runner(profile=None):
    return fcl_demo_law(profile).runner


def scas_yaw_runner():
    return GraphRunner(scas_axis_graph("scas_yaw", **example_profile().scas_axis_params("yaw")), DT)


ARTIFACTS = {"fcl": fcl_demo_runner, "scas_yaw": scas_yaw_runner}


def _emit_all():
    """(파일, 산출물별 컴파일 단위, 산출물별 CModule) — 공용 런타임은 **헬퍼 합집합으로 한 번** 만든다.

    산출물마다 claw_rt를 따로 내면 나중에 나온 쪽(헬퍼가 적은 scas_yaw)이 덮어써
    fcl 링크가 조용히 깨진다. 합집합이 아니면 안 되는 자리다.
    """
    files, sources, helpers, modules = {}, {}, set(), {}
    for name, build_runner in ARTIFACTS.items():
        runner = build_runner()
        module = emit_c(runner.graph, runner)
        modules[name] = module
        files.update(module.files)
        helpers |= module.helpers
        sources[name] = sorted(f for f in module.files if f.endswith(".c"))
    runtime = emit_runtime(helpers)
    files.update(runtime)
    shared = sorted(f for f in runtime if f.endswith(".c"))
    return files, {n: srcs + shared for n, srcs in sources.items()}, modules


def build() -> dict:
    """{파일명: 내용} — 디스크를 건드리지 않는다 (테스트가 커밋본과 대조할 때 쓴다)."""
    return _emit_all()[0]


def manifest() -> dict:
    """{산출물: 컴파일할 .c 목록} — 대조 하네스 빌드가 쓴다.

    기능축 분할로 파일이 늘어나므로 목록을 손으로 적으면 새 파티션이 조용히 빠진다.
    """
    return _emit_all()[1]


def modules() -> dict:
    """{산출물: CModule} — 이미지 레이아웃·값·지문이 필요한 테스트가 쓴다."""
    return _emit_all()[2]


def image_for(profile):
    """기체 프로파일 → (CModule, 파라미터 이미지) — 표준 법칙으로 만들고 계보 칸에 프로파일 지문을 싣는다.

    C 파일은 프로파일과 무관하게 같다(구조 지문 하나) — 기체가 바꾸는 것은 이 이미지뿐이다.
    """
    law = fcl_demo_law(profile)
    module = emit_c(law.runner.graph, law.runner)
    return module, param_image.pack(module, lineage=profile.fingerprint)


def params() -> dict:
    """{파일명: bytes 또는 str} — 커밋하는 제품 예제 기체 이미지와 사람이 읽는 목록."""
    profile = example_profile()
    module, image = image_for(profile)
    title = f"fcl — {profile.name} ({profile.id})"
    return {f"{EXAMPLE_IMAGE}.bin": image,
            f"{EXAMPLE_IMAGE}.txt": param_image.listing(module, image, title=title)}


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

    PARAMS_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in sorted(params().items()):
        path = PARAMS_DIR / name
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
            print(f"파라미터 {name} 갱신")
    return 0


if __name__ == "__main__":
    sys.exit(main())
