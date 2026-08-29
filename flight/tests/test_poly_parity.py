"""다항 게인 스케줄(claw_polyeval1d)의 Python↔C 대조 — 비트 일치 (test_parity.py 규약).

커밋된 gen/ 산출물(테이블 스케줄 형상)은 건드리지 않는다 — 다항 형상은 자동 설계
루프(M16)가 만들어내는 것이므로, 여기서 즉석 생성·즉석 컴파일로 두 백엔드를
대조한다. 덮는 경로: 구간 선택(knot 경계·경계 위 점), 정의역 밖 클램프, 차수
혼합(1차+4차, 0 패딩 호너), 스케줄 변수 1차 필터 상태.
"""

import shutil
import subprocess

import numpy as np
import pytest
from generate import DT

from claw.codegen import GraphRunner, emit_c, emit_runtime
from claw.design import fit_gain_surface
from claw.fcl.graphs import gain_schedule_graph
from claw.tables import PolyTable, Table

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
needs_cc = pytest.mark.skipif(CC is None, reason="C 컴파일러 없음 — Python 경로만 검증")

CFLAGS = [
    "-std=c99", "-O2", "-Wall", "-Wextra", "-pedantic", "-Werror", "-ffp-contract=off",
]

MACHS = np.round(np.arange(0.15, 0.951, 0.05), 4)
DP = np.minimum((0.6 / MACHS) ** 2, 4.0)

HARNESS = """\
#include <stdio.h>
#include "{name}.h"

int main(void)
{{
    {name}_state_t s;
    {name}_out_t out;
    double mach;

    {name}_reset(&s);
    while (scanf("%lf", &mach) == 1) {{
        {name}_step(&{name}_params, &s, &out, mach);
        printf("%.17g %.17g\\n", out.pitch_kp, out.roll_kp);
    }}
    return 0;
}}
"""

# 구간 경계(0.3)·격자점·사이값·정의역 밖(클램프 양측)·왕복.
#
# **각 값을 DWELL 스텝 유지한다.** 스케줄 변수는 1차 필터(tau=0.5)를 지나므로
# dt=0.01에서 한 스텝에 간격의 2%만 움직인다 — 값마다 한 스텝씩만 주면 필터 출력이
# 첫 구간(여기서는 [0.15, 0.22])을 영영 못 벗어나고, 그러면 이 대조는 **구간 선택도
# 클램프도 건드리지 않는다**. 실제로 그 상태에서는 C 쪽 구간 탐색을 통째로 지우거나
# 경계 tie-break를 뒤집거나 클램프를 빼도 테스트가 통과했다.
DWELL = 300
SWEEP = [0.15, 0.2, 0.3, 0.30001, 0.62, 0.95, 1.4, 0.05, 0.3, 0.475, 0.95, 0.15]
STEPS = [v for v in SWEEP for _ in range(DWELL)]


def _disc_poly():
    """경계에서 **값이 튀는** 다항 — 구간 tie-break를 관측 가능하게 만든다.

    design/fit.py의 적합은 C0를 구성적으로 보장하므로 경계에서 두 구간이 같은 값을
    낸다 — 그래서 그 표로는 `>=`를 `>`로 뒤집어도 결과가 같아 대조에 안 걸린다.
    반면 PolyTable은 인접성만 검사하고 C0를 요구하지 않으므로, API로 직접 주입되는
    spec(gain_export.tables를 손으로 고친 경우 등)은 불연속일 수 있다. 그 경우에도
    Python과 C가 **같은 구간을 고르는지**를 여기서 고정한다.
    """
    return PolyTable("mach", [
        {"x0": 0.15, "x1": 0.5, "coeffs": [1.0], "c": 0.325, "h": 0.175},
        {"x0": 0.5, "x1": 0.95, "coeffs": [2.0], "c": 0.725, "h": 0.225},
    ], name="pitch.kp")


def _graph(name="sched_poly", filter_tau=0.5, poly=None):
    if poly is None:
        fit = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02, max_degree=4)
        poly = PolyTable("mach", fit["segments"], name="pitch.kp")
        assert len(poly.segments) >= 2  # 차수 혼합·구간 선택이 실제로 덮이는지 전제 확인
        assert max(s["degree"] for s in poly.segments) >= 2
    tab = Table({"mach": MACHS}, 1.0 * DP, name="roll.kp", extrapolate="clip")
    return gain_schedule_graph(
        name, tables={"pitch.kp": poly, "roll.kp": tab}, filter_tau=filter_tau
    )


def test_python_backend_covers_poly():
    """컴파일러가 없어도 Python 경로는 검증 — 그래프 출력이 테이블 조회와 일치한다.

    유한성만 보면 상수 0.0을 내는 구현도 통과한다 — 필터를 지난 실제 입력에서
    다항·테이블 양쪽을 값으로 대조한다.
    """
    graph = _graph()
    runner = GraphRunner(graph, DT)
    runner.reset()
    fit = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02, max_degree=4)
    poly = PolyTable("mach", fit["segments"], name="pitch.kp")
    tab = Table({"mach": MACHS}, 1.0 * DP, name="roll.kp", extrapolate="clip")
    filt = None
    for value in STEPS[:600]:
        out = runner.step_all(mach=value)
        # 그래프 안의 1차 필터를 밖에서 같은 식으로 따라간다 (첫 스텝은 측정 시드)
        filt = value if filt is None else filt + (1.0 - np.exp(-DT / 0.5)) * (value - filt)
        assert out["pitch_kp"] == pytest.approx(poly.interp(mach=filt), rel=1e-9, abs=1e-12)
        assert out["roll_kp"] == pytest.approx(tab.interp(mach=filt), rel=1e-9, abs=1e-12)


def test_sweep_actually_exercises_segments_and_clamp():
    """이 대조가 무엇을 덮는지 자체를 고정한다 — 구간 선택·양방향 클램프.

    이 단정이 깨지면 아래 패리티 테스트는 통과해도 의미가 없다 (첫 구간에서
    직선 하나만 재는 상태로 조용히 되돌아간 것이다).
    """
    graph = _graph()
    runner = GraphRunner(graph, DT)
    runner.reset()
    fit = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02, max_degree=4)
    poly = PolyTable("mach", fit["segments"], name="pitch.kp")
    seen, clamped = set(), set()
    filt = None
    for value in STEPS:
        runner.step_all(mach=value)
        filt = value if filt is None else filt + (1.0 - np.exp(-DT / 0.5)) * (value - filt)
        lo, hi = float(poly.knots[0]), float(poly.knots[-1])
        x = min(max(filt, lo), hi)
        if filt < lo:
            clamped.add("low")
        elif filt > hi:
            clamped.add("high")
        seen.add(int(np.clip(np.searchsorted(poly.knots, x, side="right") - 1,
                             0, len(poly.segments) - 1)))
    assert seen == set(range(len(poly.segments))), f"닿지 않은 구간이 있다: {seen}"
    assert clamped == {"low", "high"}, f"클램프 양방향을 못 덮었다: {clamped}"


@needs_cc
@pytest.mark.parametrize(
    ("name", "filter_tau", "steps"),
    [
        # 필터 있는 경로 — 구간 선택·양방향 클램프·필터 상태 (값마다 DWELL 유지)
        ("sched_poly", 0.5, STEPS),
        # **필터 없는 경로** — raw 값이 그대로 들어가 knot 위 점(0.15·0.3·0.95)에서
        # 경계 tie-break가 실제로 대조된다. 필터를 지나면 값이 knot에 정확히
        # 떨어지지 않아 `>=`를 `>`로 뒤집어도 양쪽이 같은 구간을 골라 안 걸린다
        ("sched_poly_raw", 0.0, SWEEP),
        # 불연속 다항 — 경계 위 점에서 tie-break가 실제로 값에 드러난다
        ("sched_poly_disc", 0.0, [0.15, 0.3, 0.5, 0.5, 0.7, 0.95, 1.2, 0.05]),
    ],
)
def test_poly_schedule_parity(tmp_path, name, filter_tau, steps):
    graph = _graph(name, filter_tau, poly=_disc_poly() if name.endswith("disc") else None)
    runner = GraphRunner(graph, DT)
    module = emit_c(graph, runner)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))
    for fname, text in files.items():  # 파라미터 name을 가리지 않게 (하네스가 그 이름을 쓴다)
        (tmp_path / fname).write_text(text)
    (tmp_path / "harness_poly.c").write_text(HARNESS.format(name=name))

    exe = tmp_path / "harness_poly"
    srcs = [str(tmp_path / f) for f in files if f.endswith(".c")]
    cmd = [CC, *CFLAGS, f"-I{tmp_path}", str(tmp_path / "harness_poly.c"), *srcs,
           "-lm", "-o", str(exe)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"컴파일 실패:\n{res.stderr}"

    stdin = "\n".join(f"{m!r}" for m in steps) + "\n"
    run = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True)
    assert run.returncode == 0

    runner.reset()
    expected = [runner.step_all(mach=m) for m in steps]
    got = [tuple(float(v) for v in line.split()) for line in run.stdout.strip().splitlines()]
    assert len(got) == len(expected)
    for k, (e, g) in enumerate(zip(expected, got)):
        assert g[0] == e["pitch_kp"], f"pitch_kp 스텝 {k}: {g[0]!r} vs {e['pitch_kp']!r}"
        assert g[1] == e["roll_kp"], f"roll_kp 스텝 {k}: {g[1]!r} vs {e['roll_kp']!r}"
