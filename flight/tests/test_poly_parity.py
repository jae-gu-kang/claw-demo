"""다항 게인 스케줄(claw_polyeval1d)의 Python↔C 대조 — 비트 일치 (test_parity.py 규약).

커밋된 gen/ 산출물(테이블 스케줄 형상)은 건드리지 않는다 — 다항 형상은 자동 설계
루프(M16)가 만들어내는 것이므로, 여기서 즉석 생성·즉석 컴파일로 두 백엔드를
대조한다. 덮는 경로: 구간 선택(knot 경계·경계 위 점), 정의역 밖 클램프, 차수
혼합(1차+4차, 0 패딩 호너), 스케줄 변수 1차 필터 상태.
"""

import re
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


def _mixed_poly():
    """구간마다 **차수가 다른** 다항 — 0 패딩이 어느 쪽에 붙는지를 고정한다.

    호너(claw_polyeval1d)는 `coef[i*stride + k]`를 k = stride-1 → 0으로 읽으므로
    **인덱스가 곧 차수**다(오름차수). 짧은 구간을 stride까지 채우는 0은 반드시
    **뒤**에 와야 하고, 앞에 붙이면 그 구간 다항에 u^pad가 곱해진다.

    적합(fit_gain_surface)이 만드는 표도 지금은 차수가 섞이지만 그건 **우연이다** —
    허용오차나 적합 알고리즘이 바뀌어 구간 차수가 같아지면 stride 패딩이 0개가
    되고, 패딩 경로가 조용히 대조에서 빠진다. 여기서는 구성으로 고정한다.
    """
    return PolyTable("mach", [
        # 1차 (계수 2개 → 뒤에 0 두 개가 붙는다)
        {"x0": 0.15, "x1": 0.5, "coeffs": [2.0, 3.0], "c": 0.325, "h": 0.175},
        # 3차 (계수 4개 = stride)
        {"x0": 0.5, "x1": 0.95, "coeffs": [1.0, -2.0, 0.5, 4.0], "c": 0.725, "h": 0.225},
    ], name="pitch.kp")


# 패딩 구간 **안쪽** 점을 쓴다. 구간 끝(u = ±1)은 u^pad = 1이라 뒤/앞 패딩이 같은
# 값을 내서, 거기만 재면 패딩 순서를 뒤집어도 대조에 안 걸린다 (실제로 적합 표
# 스윕에서는 0.15·0.05가 그 자리라 12점 중 1점만 순서를 구분했다).
PAD_SWEEP = [0.2, 0.25, 0.325, 0.4, 0.45, 0.5, 0.7, 0.95, 1.2, 0.05, 0.25]

_POLY_BY_NAME = {"sched_poly_disc": _disc_poly, "sched_poly_pad": _mixed_poly}


def _graph(name="sched_poly", filter_tau=0.5, poly=None):
    if poly is None:
        fit = fit_gain_surface(MACHS, -2.0 * DP, tol_fit=0.02, max_degree=4)
        poly = PolyTable("mach", fit["segments"], name="pitch.kp")
        assert len(poly.segments) >= 2  # 차수 혼합·구간 선택이 실제로 덮이는지 전제 확인
        assert max(s["degree"] for s in poly.segments) >= 2
        # 주석이 약속한 "차수 혼합"을 실제로 검사한다 — 구간 차수가 같아지면 stride
        # 패딩이 0개가 되어, 적합 기반 변이들이 패딩 경로를 통째로 안 밟는다
        lens = [len(s["coeffs"]) for s in poly.segments]
        assert min(lens) < max(lens), f"적합이 균일 차수를 냈다 {lens} — 패딩이 안 덮인다"
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


def _seg_and_u(poly, x):
    """C 쪽 구간 선택과 같은 규칙 — 클립 후 `xc >= kn[i+1]`로 전진 (claw_polyeval1d)."""
    kn = [float(v) for v in poly.knots]
    xc = min(max(float(x), kn[0]), kn[-1])
    i = 0
    while i < len(poly.segments) - 1 and xc >= kn[i + 1]:
        i += 1
    s = poly.segments[i]
    return i, (xc - s["c"]) / s["h"]


def _flatten(poly, trailing):
    """구간 계수를 stride로 채워 편다 — emit_c._emit_poly가 하는 그 일."""
    stride = max(len(s["coeffs"]) for s in poly.segments)
    flat = []
    for s in poly.segments:
        pad = [0.0] * (stride - len(s["coeffs"]))
        flat.extend(list(s["coeffs"]) + pad if trailing else pad + list(s["coeffs"]))
    return stride, flat


def _horner(flat, stride, i, u):
    """emit_c.py claw_polyeval1d 본문 그대로 — coef[i*stride + k], k = stride-1 → 0."""
    v = 0.0
    for k in range(stride - 1, -1, -1):
        v = v * u + flat[i * stride + k]
    return v


def test_pad_sweep_actually_distinguishes_padding_order():
    """이 대조가 무엇을 덮는지 자체를 고정한다 — 0 패딩의 **자리**.

    구간 끝(u = ±1)에서는 u^pad = 1이라 뒤 패딩과 앞 패딩이 **같은 값**을 낸다.
    적합 표 스윕이 딱 그 상태였다: 12점 중 패딩 구간을 밟는 점이 죄다 구간 끝이라
    순서를 뒤집어도 한 점에서만 갈렸다. 이 단정이 깨지면 아래 패리티 변이는
    통과해도 패딩 순서를 안 재는 상태로 조용히 되돌아간 것이다.
    """
    poly = _mixed_poly()
    stride, back = _flatten(poly, trailing=True)
    _, front = _flatten(poly, trailing=False)
    padded = {i for i, s in enumerate(poly.segments) if len(s["coeffs"]) < stride}
    assert padded, "패딩이 걸리는 구간이 없다 — 픽스처가 균일 차수가 됐다"

    seen = set()
    for x in PAD_SWEEP:
        i, u = _seg_and_u(poly, x)
        if i not in padded or abs(abs(u) - 1.0) < 1e-12:
            continue  # 패딩 없는 구간이거나 u = ±1 (두 순서가 수학적으로 같은 자리)
        seen.add(i)
        b, f = _horner(back, stride, i, u), _horner(front, stride, i, u)
        assert abs(b - f) > 1e-6, f"x={x}: 패딩 순서를 뒤집어도 값이 같다 ({b} vs {f})"
    assert seen == padded, f"스윕이 안 밟은 패딩 구간이 있다: {padded - seen}"


def test_emitted_padding_is_trailing():
    """생성된 계수 배열에서 0은 **뒤**에 온다 — 호너가 인덱스를 차수로 읽기 때문이다.

    패리티 대조는 컴파일러가 있어야 돌고(needs_cc) 값이 갈리는 점을 스윕이 밟아야
    걸린다. 배열 자체를 보는 이 단정은 둘 다 필요 없어서, 패딩 자리를 바꾸는 변경은
    컴파일러 없는 환경에서도 여기서 먼저 걸린다.
    """
    poly = _mixed_poly()
    graph = _graph("sched_poly_pad", 0.0, poly=poly)
    module = emit_c(graph, GraphRunner(graph, DT))
    body = re.search(r"\.pitch_kp_coef = \{(.*?)\n\s*\},",
                     module.files["sched_poly_pad_data.c"], re.S)
    assert body, "생성물에서 계수 배열을 못 찾았다 — 이름 규약이 바뀌었나"
    # 배열 머리에 붙는 주석("… 오름차수, 0 패딩")에도 숫자가 있다 — 먼저 지운다
    values = re.sub(r"/\*.*?\*/", "", body.group(1), flags=re.S)
    nums = [float(v) for v in re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", values)]
    stride = max(len(s["coeffs"]) for s in poly.segments)
    assert len(nums) == stride * len(poly.segments)
    for i, s in enumerate(poly.segments):
        block = nums[i * stride:(i + 1) * stride]
        n = len(s["coeffs"])
        assert block[:n] == pytest.approx(list(s["coeffs"])), f"구간 {i} 계수가 밀렸다: {block}"
        assert block[n:] == [0.0] * (stride - n), f"구간 {i}: 0 패딩이 뒤가 아니다 — {block}"


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
        # **차수 혼합** — 짧은 구간의 0 패딩이 뒤에 붙는지를 구간 안쪽에서 대조한다
        ("sched_poly_pad", 0.0, PAD_SWEEP),
    ],
)
def test_poly_schedule_parity(tmp_path, name, filter_tau, steps):
    make = _POLY_BY_NAME.get(name)
    graph = _graph(name, filter_tau, poly=make() if make else None)
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
