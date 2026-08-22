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

import mission_trace
import pytest
from generate import DT, GEN_DIR, build, fcl_demo_graph, scas_yaw_graph

from claw.codegen import GraphRunner
from claw.fcl.demo import DEMO_YAW
from claw.fcl.scas import ScasAxis

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
needs_cc = pytest.mark.skipif(CC is None, reason="C 컴파일러 없음 — Python 경로만 검증")

# -ffp-contract=off 는 장식이 아니다 — 측정으로 확인됨: contract=fast로 빌드하면
# 컴파일러가 `a*b + c`를 FMA 하나로 합쳐 중간 반올림이 사라지고, 같은 입력에서
# 2.8e-16 어긋난다(clang 14, -O2). 탑재 빌드에도 같은 지정이 필요하며,
# 그래서 생성 헤더가 이 요구를 빌드 조건으로 명시한다.
CFLAGS = [
    "-std=c99", "-O2", "-Wall", "-Wextra", "-pedantic", "-Werror", "-ffp-contract=off",
]


@pytest.fixture(scope="module")
def trace():
    """실제 데모 미션 1회 — 모드 전환·게인 스케줄·리미터·항법 무효가 모두 들어 있다."""
    return mission_trace.run()


def _build(name, macro, tmp_path):
    exe = tmp_path / f"harness_{name}"
    cmd = [
        CC, *CFLAGS, f"-I{GEN_DIR}", f"-D{macro}",
        str(GEN_DIR.parent / "tests" / "harness.c"),
        str(GEN_DIR / f"{name}.c"), str(GEN_DIR / f"{name}_data.c"),
        "-lm", "-o", str(exe),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"{name} 컴파일 실패:\n{res.stderr}"
    return exe


def _first_diff(a, b, label):
    for k, (x, y) in enumerate(zip(a, b, strict=True)):
        if x is None:
            continue
        if x != y:
            return f"{label} 스텝 {k} (t={k * DT:.2f}s): {x!r} vs {y!r} (차 {x - y!r})"
    return None


# ── 최상위 제어법칙 ───────────────────────────────────────────────────────


def _ir_runner(warm):
    graph = fcl_demo_graph()
    runner = GraphRunner(graph, DT)
    de0, th0, thr0 = warm
    # 손으로 쓴 법칙과 같은 트림 웜스타트 (law.py:61, autopilot.py:126, simulator.py:132)
    runner.reset(
        states={"scas_pitch_pid": de0, "ap_alt_pid": th0, "ap_spd_pid": thr0},
        hold={"elevon_l": de0, "elevon_r": de0, "rudder": 0.0,
              "throttle_l": thr0, "throttle_r": thr0},
    )
    return runner


def test_ir_matches_handwritten_law(trace):
    """IR 실행이 손으로 쓴 FlightControlLaw와 비트 일치 — 구조를 옳게 옮겼는가."""
    inputs, refs, warm = trace
    runner = _ir_runner(warm)
    got = [runner.step(**row) for row in inputs]
    for i, name in enumerate(mission_trace.OUTPUT_ORDER):
        diff = _first_diff([r[i] for r in refs], [g[name] for g in got], name)
        assert diff is None, f"oracle ≠ IR — {diff}"


def test_trace_exercises_the_hard_paths(trace):
    """대조가 통과해도 그 경로를 안 밟았으면 의미가 없다 — 커버리지를 단정한다."""
    inputs, refs, _warm = trace
    assert any(row["nav_valid"] == 0.0 for row in inputs), "항법 무효(홀드) 구간 없음"
    for flag in ("speed_on", "alt_on", "heading_on"):
        vals = {row[flag] for row in inputs}
        assert vals == {0.0, 1.0}, f"{flag}가 두 상태를 모두 밟지 않음: {vals}"
    assert len({row["mach"] for row in inputs}) > 100, "게인 스케줄이 움직이지 않음"
    assert any(abs(r[0]) >= 0.349 for r in refs), "엘레본 포화를 밟지 않음"


@needs_cc
def test_generated_fcl_matches_ir(trace, tmp_path):
    """생성 C가 IR·oracle과 비트 일치. -Werror이므로 경고 0도 함께 보증한다."""
    inputs, refs, warm = trace
    exe = _build("fcl", "HARNESS_FCL", tmp_path)

    stdin = " ".join(repr(v) for v in warm) + "\n"
    stdin += "\n".join(
        " ".join(repr(row[k]) for k in mission_trace.INPUT_ORDER) for row in inputs
    ) + "\n"
    run = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True)
    assert run.returncode == 0, f"하네스 실행 실패:\n{run.stderr}"

    rows = [[float(x) for x in line.split()] for line in run.stdout.splitlines()]
    assert len(rows) == len(inputs), f"출력 {len(rows)}행 ≠ 입력 {len(inputs)}행"

    runner = _ir_runner(warm)
    ir = [runner.step(**row) for row in inputs]
    for i, name in enumerate(mission_trace.OUTPUT_ORDER):
        c_vals = [row[i] for row in rows]
        assert _first_diff([r[i] for r in refs], c_vals, name) is None, (
            f"oracle ≠ 생성 C — {_first_diff([r[i] for r in refs], c_vals, name)}"
        )
        assert _first_diff([g[name] for g in ir], c_vals, name) is None, (
            f"IR ≠ 생성 C — {_first_diff([g[name] for g in ir], c_vals, name)}"
        )


# ── SCAS 요축 (단일 출력 반환 경로) ───────────────────────────────────────


def _yaw_sequence(n=1200):
    """포화 진입·적분기 와인드업·워시아웃 정상상태를 반드시 밟는 입력."""
    for k in range(n):
        t = k * DT
        if t < 2.0:  # 오차·각속도를 같은 부호로 크게 → 출력 포화 + 적분기 클램프
            yield 0.5, 0.5
        elif t < 4.0:  # 반대 계단 → 반대편 포화, 적분기 언와인드
            yield -0.5, -0.5
        elif t < 7.0:  # 상수 각속도 → 워시아웃 정상상태(출력이 0으로 감쇠)
            yield 0.0, 0.3
        else:
            yield 0.2 * math.sin(2.0 * t), 0.15 * math.cos(3.0 * t)


def _yaw_reference():
    oracle = ScasAxis(**DEMO_YAW).init(DT)
    oracle.reset()
    runner = GraphRunner(scas_yaw_graph(), DT)
    runner.reset()
    ref, ir, lines = [], [], []
    for att_err, rate in _yaw_sequence():
        ref.append(oracle.step(att_err, rate))
        ir.append(runner.step(att_err=att_err, rate=rate))
        lines.append(f"{att_err!r} {rate!r}")
    return ref, ir, "\n".join(lines) + "\n"


def test_yaw_axis_ir_matches_handwritten():
    ref, ir, _ = _yaw_reference()
    assert _first_diff(ref, ir, "u") is None
    assert any(abs(v) >= DEMO_YAW["out_hi"] for v in ref), "포화를 한 번도 밟지 않음"


@needs_cc
def test_generated_yaw_axis_matches_ir(tmp_path):
    """단일 출력 그래프는 구조체가 아니라 값을 반환한다 — 그 경로도 대조한다."""
    exe = _build("scas_yaw", "HARNESS_SCAS_YAW", tmp_path)
    ref, ir, stdin = _yaw_reference()
    run = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    got = [float(x) for x in run.stdout.split()]
    assert _first_diff(ref, got, "u") is None
    assert _first_diff(ir, got, "u") is None


# ── 산출물 관리 ───────────────────────────────────────────────────────────


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
