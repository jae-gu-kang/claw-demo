"""탑재 C 산출물 3자 대조 — 손으로 쓴 제어법칙(oracle) ↔ IR 실행 ↔ 생성 C.

셋을 모두 비교하는 이유는 어긋났을 때 **어느 단계에서 깨졌는지** 바로 나오기
때문이다: oracle ≠ IR이면 구조를 잘못 옮긴 것이고, IR ≠ C면 에미터가 틀린 것이다.

전부 배정밀도이고 연산 순서를 문자 그대로 맞췄으므로 목표는 근사가 아니라
**비트 일치**다. 허용오차를 두면 진짜 어긋남이 그 아래 숨는다.

컴파일러가 없으면 C 대조만 건너뛴다 — 폐쇄망·최소 환경에서도 Python 경로는
그대로 검증된다 (02 §1 의존성 최소화).
"""

import math
import shutil
import subprocess

import pytest
from generate import ARTIFACTS, DT, GEN_DIR, build

from claw.codegen import GraphRunner, scas_axis_graph
from claw.fcl.scas import ScasAxis

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
needs_cc = pytest.mark.skipif(CC is None, reason="C 컴파일러 없음 — Python 경로만 검증")

# -ffp-contract=off 는 장식이 아니다 — 측정으로 확인됨: contract=fast로 빌드하면
# 컴파일러가 `a*b + c`를 FMA 하나로 합쳐 중간 반올림이 사라지고, 같은 입력에서
# scas_yaw가 2.8e-16 어긋난다(clang 14, -O2). 탑재 빌드에도 같은 지정이 필요하며,
# 그래서 생성 헤더가 이 요구를 빌드 조건으로 명시한다.
CFLAGS = [
    "-std=c99", "-O2", "-Wall", "-Wextra", "-pedantic", "-Werror", "-ffp-contract=off",
]


def _sequence(n_steps=1200):
    """포화 진입·적분기 와인드업·워시아웃 정상상태를 반드시 밟는 입력.

    부드러운 신호만 넣으면 클램프도 워시아웃 감쇠도 실행되지 않아, 대조가
    통과해도 그 경로는 검증되지 않은 채로 남는다.
    """
    for k in range(n_steps):
        t = k * DT
        if t < 2.0:
            # 자세오차·각속도를 같은 부호로 크게 → 두 축 모두 출력 포화.
            # 요축은 게인이 작아(kp 0.5) 오차만으로는 한계에 닿지 않으므로
            # rate 항(k_rate 0.8)까지 함께 실어야 포화 경로가 실제로 실행된다.
            att_err, rate = 0.5, 0.5
        elif t < 4.0:  # 반대 계단 → 반대편 포화, 적분기 언와인드
            att_err, rate = -0.5, -0.5
        elif t < 7.0:  # 상수 각속도 → 워시아웃 정상상태(출력이 0으로 감쇠)
            att_err, rate = 0.0, 0.3
        else:  # 통상 기동
            att_err, rate = 0.2 * math.sin(2.0 * t), 0.15 * math.cos(3.0 * t)
        yield t, att_err, rate


def _gains(cfg, scheduled, t):
    """스케줄된 게인만 시간에 따라 흔든다 — 동압 스케일(demo.py:31) 흉내."""
    scale = 1.0 + 0.5 * math.sin(0.7 * t)
    return {g: cfg[g] * scale for g in scheduled}


def _reference(name, cfg, scheduled):
    """(oracle 출력, IR 출력, 하네스 입력 줄) — 한 번의 주행으로 셋을 모은다."""
    oracle = ScasAxis(**cfg).init(DT)
    oracle.reset()
    runner = GraphRunner(scas_axis_graph(name, scheduled=scheduled, **cfg), DT)
    runner.reset()

    ref, ir, lines = [], [], []
    for t, att_err, rate in _sequence():
        gains = _gains(cfg, scheduled, t)
        ref.append(oracle.step(att_err, rate, **gains))
        ir.append(runner.step(att_err=att_err, rate=rate, **gains))
        full = {g: cfg[g] * (1.0 + 0.5 * math.sin(0.7 * t)) for g in ("kp", "ki", "k_rate")}
        lines.append(f"{att_err!r} {rate!r} {full['kp']!r} {full['ki']!r} {full['k_rate']!r}")
    return ref, ir, "\n".join(lines) + "\n"


def _first_diff(a, b):
    for k, (x, y) in enumerate(zip(a, b, strict=True)):
        if x != y:
            return f"스텝 {k} (t={k * DT:.3f}s): {x!r} vs {y!r}, 차 {x - y!r}"
    return None


@pytest.mark.parametrize(("name", "cfg", "scheduled"), ARTIFACTS)
def test_ir_matches_handwritten_law(name, cfg, scheduled):
    """IR 실행이 손으로 쓴 ScasAxis와 비트 일치 — IR이 구조를 옳게 옮겼는가."""
    ref, ir, _ = _reference(name, cfg, scheduled)
    assert _first_diff(ref, ir) is None, f"{name}: oracle ≠ IR — {_first_diff(ref, ir)}"
    assert any(abs(v) >= cfg["out_hi"] for v in ref), f"{name}: 포화를 한 번도 밟지 않음"


@needs_cc
@pytest.mark.parametrize(("name", "cfg", "scheduled"), ARTIFACTS)
def test_generated_c_matches_ir(name, cfg, scheduled, tmp_path):
    """생성 C가 IR·oracle과 비트 일치 — 에미터가 구조를 옳게 옮겼는가.

    -Werror이므로 이 테스트는 생성 코드의 경고 0도 함께 보증한다.
    """
    exe = tmp_path / f"harness_{name}"
    cmd = [
        CC, *CFLAGS, f"-I{GEN_DIR}", f"-DHARNESS_{name.upper()}",
        str(GEN_DIR.parent / "tests" / "harness.c"),
        str(GEN_DIR / f"{name}.c"), str(GEN_DIR / f"{name}_data.c"),
        "-lm", "-o", str(exe),
    ]
    build_res = subprocess.run(cmd, capture_output=True, text=True)
    assert build_res.returncode == 0, f"{name} 컴파일 실패:\n{build_res.stderr}"

    ref, ir, stdin_text = _reference(name, cfg, scheduled)
    run = subprocess.run([str(exe)], input=stdin_text, capture_output=True, text=True)
    assert run.returncode == 0, f"{name} 하네스 실행 실패:\n{run.stderr}"
    got = [float(x) for x in run.stdout.split()]

    assert len(got) == len(ref), f"{name}: 출력 개수 {len(got)} ≠ 입력 {len(ref)}"
    assert _first_diff(ref, got) is None, f"{name}: oracle ≠ 생성 C — {_first_diff(ref, got)}"
    assert _first_diff(ir, got) is None, f"{name}: IR ≠ 생성 C — {_first_diff(ir, got)}"


def test_committed_artifacts_match_generator():
    """커밋된 gen/이 즉석 생성본과 동일 — 산출물과 생성기가 어긋난 채 배포되지 않게.

    생성은 결정적(시각 미포함)이므로 차이가 나면 곧 실제 설계 변경이다.
    """
    for name, text in sorted(build().items()):
        path = GEN_DIR / name
        assert path.exists(), f"{name} 미커밋 — `python flight/generate.py` 실행 필요"
        assert path.read_text(encoding="utf-8") == text, (
            f"{name}이 생성기 출력과 다름 — 손으로 고쳤거나 재생성이 필요하다"
        )


def test_generation_is_deterministic():
    assert build() == build()
