"""탑재 C 산출물 대조 — 설계 실행(Python 백엔드) ↔ 생성 C.

증분 C에서 `fcl/`이 IR 백엔드로 이관되면서 손으로 쓴 두 번째 구현은 사라졌다.
그래서 여기 남은 대조는 **같은 IR의 두 백엔드**다 — 이것이 이 저장소에서 유일하게
남은 진짜 이중 구현이고, 탑재 코드가 설계와 같은 답을 내는지의 근거다.

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
from generate import DT, GEN_DIR, build, fcl_demo_runner, manifest, scas_yaw_runner

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
    # 컴파일 단위는 생성기가 낸다 — 기능축 파티션이 늘어도 목록이 새지 않는다
    exe = tmp_path / f"harness_{name}"
    cmd = [
        CC, *CFLAGS, f"-I{GEN_DIR}", f"-D{macro}",
        str(GEN_DIR.parent / "tests" / "harness.c"),
        *(str(GEN_DIR / src) for src in manifest()[name]),
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
    runner = fcl_demo_runner()
    de0, th0, thr0 = warm
    # 손으로 쓴 법칙과 같은 트림 웜스타트 (law.py:61, autopilot.py:126, simulator.py:132)
    runner.reset(
        states={"scas_pitch_pid": de0, "ap_alt_pid": th0, "ap_spd_pid": thr0},
        hold={"elevon_l": de0, "elevon_r": de0, "rudder": 0.0,
              "throttle_l": thr0, "throttle_r": thr0},
    )
    return runner


def test_law_replays_deterministically(trace):
    """같은 입력·같은 웜스타트면 법칙이 같은 답을 낸다 — C 대조의 기준선.

    미션 중 기록한 출력과, 그 입력을 따로 세운 러너에 다시 흘린 출력이 같아야
    한다. 어댑터(항법→공학량)와 웜스타트 주입이 재현 가능한지를 여기서 잡는다.
    """
    inputs, refs, warm = trace
    runner = _ir_runner(warm)
    got = [runner.step(**row) for row in inputs]
    for i, name in enumerate(mission_trace.OUTPUT_ORDER):
        diff = _first_diff([r[i] for r in refs], [g[name] for g in got], name)
        assert diff is None, f"재생이 재현되지 않음 — {diff}"


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
            f"설계 실행 ≠ 생성 C — {_first_diff([r[i] for r in refs], c_vals, name)}"
        )
        assert _first_diff([g[name] for g in ir], c_vals, name) is None, (
            f"러너 ≠ 생성 C — {_first_diff([g[name] for g in ir], c_vals, name)}"
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
    runner = scas_yaw_runner()
    runner.reset()
    ref, ir, lines = [], [], []
    for att_err, rate in _yaw_sequence():
        ref.append(oracle.step(att_err, rate))
        ir.append(runner.step(att_err=att_err, rate=rate))
        lines.append(f"{att_err!r} {rate!r}")
    return ref, ir, "\n".join(lines) + "\n"


def test_yaw_axis_adapter_matches_graph():
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


# ── 기능축 분할 (증분 D′) ─────────────────────────────────────────────────
#
# 비트 일치는 위에서 이미 봤다. 여기서 보는 것은 **분할이 실제로 됐는가**다 —
# FCC팀이 서브시스템 하나만 떼어 읽고 검증할 수 있어야 분할한 값을 한다.

GROUPS = ("sched", "ap", "lim", "scas", "mix")


def _gen(name):
    return (GEN_DIR / name).read_text(encoding="utf-8")


def test_진입점에는_조립부만_남는다():
    # 상태 구조체는 쪼개지 않으므로 fcl_reset은 그대로 여기 남는다 — step 본문만 본다
    step = _gen("fcl.c").split("void fcl_step(", 1)[1]
    for group in GROUPS:
        assert f"fcl_{group}_step(" in step, f"{group} 호출이 없다"
    for token in ("claw_lookup1d", "claw_clip", "claw_wrap_pi", "prm->", "sta->ap_"):
        assert token not in step, f"조립부에 블록 계산이 남았다: {token}"
    assert len(_gen("fcl.c").splitlines()) < 120, "조립부가 다시 부풀었다"


def test_신호_이름이_파티션_경계를_넘어_유지된다():
    """`rtb_Sum_p_idx_1` 류를 만들지 않는다는 요구가 경계에서도 지켜지는지."""
    top, scas = _gen("fcl.c"), _gen("fcl_scas.c")
    for signal in ("ap_hdg_sat_y", "lim_theta_lim_y", "sched_pitch_kp_y"):
        assert signal in top, f"{signal}이 조립부에 없다"
        assert signal in scas, f"{signal}이 SCAS 인자에서 이름을 잃었다"


def test_공용_헬퍼는_한_벌만_있다():
    """산출물마다 static으로 복제되면 같은 코드를 산출물 수만큼 검증하게 된다."""
    assert "double claw_clip(" in _gen("claw_rt.c")
    for name in ("fcl", "fcl_ap", "fcl_lim", "fcl_scas", "fcl_sched", "fcl_mix", "scas_yaw"):
        assert "double claw_clip(" not in _gen(f"{name}.c"), f"{name}.c에 헬퍼가 복제됐다"


def test_파티션은_types_h만_의존한다():
    """파티션 헤더가 진입점을 물면 포함 관계가 순환처럼 읽힌다 — DAG로 남긴다."""
    for group in GROUPS:
        text = _gen(f"fcl_{group}.h")
        assert '#include "fcl_types.h"' in text
        assert '#include "fcl.h"' not in text


def test_분할해도_지문은_그대로다():
    """지문은 형상의 신원이다 — 파일 배치가 아니라 제어법칙이 바뀔 때만 움직인다."""
    fps = set()
    for name in ("fcl.h", "fcl_types.h", "fcl_data.c", *(f"fcl_{g}.h" for g in GROUPS)):
        line = next(ln for ln in _gen(name).splitlines() if "지문" in ln)
        fps.add(line.split(":")[1].strip())
    assert fps == {"c0f9af6f848059c4"}, f"형상 지문이 움직였다: {fps}"
