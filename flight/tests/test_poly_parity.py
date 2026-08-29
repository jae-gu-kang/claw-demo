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
#include "sched_poly.h"

int main(void)
{
    sched_poly_state_t s;
    sched_poly_out_t out;
    double mach;

    sched_poly_reset(&s);
    while (scanf("%lf", &mach) == 1) {
        sched_poly_step(&sched_poly_params, &s, &out, mach);
        printf("%.17g %.17g\\n", out.pitch_kp, out.roll_kp);
    }
    return 0;
}
"""

# 구간 경계(0.3)·격자점·사이값·정의역 밖(클램프 양측)·왕복 — 필터 상태도 함께 구른다
SWEEP = [0.15, 0.2, 0.3, 0.30001, 0.62, 0.95, 1.4, 0.05, 0.3, 0.475, 0.95, 0.15]


def _graph():
    fit = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02, max_degree=4)
    poly = PolyTable("mach", fit["segments"], name="pitch.kp")
    assert len(poly.segments) >= 2  # 차수 혼합·구간 선택이 실제로 덮이는지 전제 확인
    assert max(s["degree"] for s in poly.segments) >= 2
    tab = Table({"mach": MACHS}, 1.0 * DP, name="roll.kp", extrapolate="clip")
    return gain_schedule_graph(
        "sched_poly", tables={"pitch.kp": poly, "roll.kp": tab}, filter_tau=0.5
    )


def test_python_backend_covers_poly():
    """컴파일러가 없어도 Python 경로는 검증 — 다항 노드가 그래프에서 평가된다."""
    graph = _graph()
    runner = GraphRunner(graph, DT)
    runner.reset()
    out = runner.step_all(mach=0.62)
    assert np.isfinite(out["pitch_kp"]) and np.isfinite(out["roll_kp"])


@needs_cc
def test_poly_schedule_parity(tmp_path):
    graph = _graph()
    runner = GraphRunner(graph, DT)
    module = emit_c(graph, runner)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "harness_poly.c").write_text(HARNESS)

    exe = tmp_path / "harness_poly"
    srcs = [str(tmp_path / f) for f in files if f.endswith(".c")]
    cmd = [CC, *CFLAGS, f"-I{tmp_path}", str(tmp_path / "harness_poly.c"), *srcs,
           "-lm", "-o", str(exe)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"컴파일 실패:\n{res.stderr}"

    stdin = "\n".join(f"{m!r}" for m in SWEEP) + "\n"
    run = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True)
    assert run.returncode == 0

    runner.reset()
    expected = [runner.step_all(mach=m) for m in SWEEP]
    got = [tuple(float(v) for v in line.split()) for line in run.stdout.strip().splitlines()]
    assert len(got) == len(expected)
    for k, (e, g) in enumerate(zip(expected, got)):
        assert g[0] == e["pitch_kp"], f"pitch_kp 스텝 {k}: {g[0]!r} vs {e['pitch_kp']!r}"
        assert g[1] == e["roll_kp"], f"roll_kp 스텝 {k}: {g[1]!r} vs {e['roll_kp']!r}"
