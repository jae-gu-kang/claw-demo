"""탑재 C 신뢰성 검증 — DAL A 정렬 파이프라인 (M12).

문서가 아니라 **실행**으로 검증한다. 사용자 8단 파이프라인이 이 모듈의 목차다:

  Python 제어법칙 → 검증된 IR(생성 전 원천 차단) → C 생성
    ① 규칙 검사(static_c)  ② 정적 결함(엄격 컴파일 + IR 차단)  ③ 복잡도/결합
    ④ 유닛 시험(units — 파티션 단위, 스텁 불요 구조)  ⑤ 하네스 자동 생성
    ⑥ 구조적 커버리지 — 라인·분기(llvm-cov) + MC/DC(자체 계측, mcdc)
    ⑦ SIL: 호스트 대조(미션 + 보강 벡터, 비트 일치 — 파라미터 세트의 이미지마다) — PIL/타깃은 범위 밖 명시
    ⑧ 소스↔오브젝트 추적성 — 범위 밖 명시
  → 증적(report — DO-178C 목표 대응표 포함, 화면·보고서가 그대로 소비)

**못 잰 것은 잰 척하지 않는다.** 컴파일러·커버리지 툴이 없는 환경에서는 해당
검사가 사유와 함께 "생략"으로 남고, DO-178C 대응표에도 그 상태가 반영된다.
DO-330 도구 적격성 증거는 이 모듈의 주장 범위 밖이다.

패리티 테스트(flight/tests/test_parity.py)와의 관계: 저쪽이 **정본 검증**이다 —
손으로 쓴 하네스가 생성물끼리의 담합을 막는다. 여기 하네스는 형상 적응형으로
생성되므로 그 독립성은 없다. 대신 이쪽은 커밋된 데모 형상만이 아니라 **지금 편집
중인 형상**을 같은 강도로, 유닛 단위까지 검증한다.
"""

import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import claw
from claw.blocks.basic import Gain, Product, Saturation
from claw.blocks.controllers import PID
from claw.blocks.filters import Washout
from claw.blocks.lookup import LookupBlock, PolyBlock
from claw.codegen import emit_c, emit_runtime, param_image
from claw.verify import mcdc as mcdc_mod
from claw.verify import vectors
from claw.verify.static_c import analyze as static_analyze
from claw.verify.static_c import functions_of
from claw.verify.trace import record_mission
from claw.verify.units import (IMAGE_READER, load_params_c, make_params_harness, make_unit_harness, params_stdin,
                               run_unit_oracle, unit_specs, unit_stdin)

# test_parity.py CFLAGS와 같은 정신 — -Werror 대신 경고를 세어 근거로 남긴다.
# -ffp-contract=off는 장식이 아니다: FMA 축약은 중간 반올림을 없애 2.8e-16 어긋난다.
# 외부 도구 타임아웃 [s] — 협조적 취소는 subprocess **사이**에서만 듣는다.
# 툴이 멈추면 잡이 영구 블록되므로 상한을 둔다: 컴파일·판독은 넉넉히, 하네스
# 실행은 18,000스텝 재생이 로컬 1초 안쪽이라 여유를 크게 잡아도 충분하다.
TOOL_TIMEOUT = 300.0
STRICT_FLAGS = ["-std=c99", "-O2", "-Wall", "-Wextra", "-pedantic", "-ffp-contract=off"]
COVER_FLAGS = ["-std=c99", "-O0", "-ffp-contract=off",
               "-fprofile-instr-generate", "-fcoverage-mapping"]


def find_cc():
    return shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


def find_llvm_tool(name):
    """llvm-profdata·llvm-cov — PATH 우선, macOS는 xcrun 폴백."""
    path = shutil.which(name)
    if path:
        return path
    if sys.platform == "darwin" and shutil.which("xcrun"):
        r = subprocess.run(["xcrun", "-f", name], capture_output=True, text=True,
                           timeout=TOOL_TIMEOUT)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def warm_start_lines(runner) -> list:
    """트림 웜스타트 대입 줄 — 이 형상에 있는 축만.

    웜스타트 계약은 생성 코드와 같다(fcl.h 주석): 리셋 후 상태 필드 직접 대입. 적분기는 ki 값과 무관하게 항상
    방출되므로(v1.12 — emit_c `_emit_pid`) 축이 그래프에 있으면 필드도 있다. 조립이 달라 축 노드가 없으면 건너뛴다.
    """
    warm = {"scas_pitch_pid": ("de0", "scas.pitch 적분기 = 트림 δe"),
            "ap_alt_pid": ("th0", "AP 고도 적분기 = 트림 θ"),
            "ap_spd_pid": ("thr0", "AP 속도 적분기 = 트림 스로틀")}
    lines = []
    for nid, (var, note) in warm.items():
        try:
            runner.graph.node(nid)
        except KeyError:
            continue  # 이 형상에 없는 축 — 조립이 다르면 웜스타트도 다르다
        lines.append(f"    s.{nid}_i = {var};   /* law.py reset — {note} */")
    return lines


def make_harness(graph, runner) -> str:
    """통합(SIL) 하네스 — 입출력 목록을 그래프 선언에서 만든다. argv[1] = 파라미터 이미지.

    필드 이름은 데모 형상 조립 규약(law.py reset)에 매여 있고, 컴파일이 그 실존을
    검사한다 — 이름이 낡으면 조용히 틀리는 게 아니라 빌드가 깨진다. 같은 실행 파일이 파라미터 세트의 이미지마다
    돈다(v1.12).
    """
    base = graph.name
    n = len(graph.inputs)
    args = ", ".join(f"u[{i}]" for i in range(n))
    outs = list(graph.outputs)
    fmt = " ".join(["%.17g"] * len(outs))
    prints = ", ".join(f"out.{name}" for name in outs)
    warm = "\n".join(warm_start_lines(runner))
    return f"""/* CLAW 검증 하네스 — 표준입력 시퀀스를 생성 코드에 흘려 %.17g로 낸다 (왕복 무손실). */
#include <stdio.h>
#include <stdlib.h>
#include "{base}.h"

{IMAGE_READER}
int main(int argc, char **argv)
{{
    {base}_params_t prm;
    {base}_state_t s;
    {base}_out_t out;
    double de0, th0, thr0;
    double u[{n}];
    int k;
    size_t len, npool = 0;
    unsigned char *img;
    double *pool;

{load_params_c(base)}
    if (scanf("%lf %lf %lf", &de0, &th0, &thr0) != 3) {{ return 1; }}
    {base}_reset(&s);
{warm}
    s.hold.elevon_l = de0;
    s.hold.elevon_r = de0;
    s.hold.rudder = 0.0;
    s.hold.throttle_l = thr0;
    s.hold.throttle_r = thr0;

    for (;;) {{
        for (k = 0; k < {n}; k++) {{
            if (scanf("%lf", &u[k]) != 1) {{
#ifdef CLAW_MCDC_ENABLED
                claw_mcdc_dump();
#endif
                return 0;
            }}
        }}
        {base}_step(&prm, &s, &out, {args});
        printf("{fmt}\\n", {prints});
    }}
}}
"""


# ── 빌드·실행 잔손 ────────────────────────────────────────────────────────


def _write_tree(dirpath, files, harnesses):
    """소스 나무 하나 — {생성물} + {하네스 이름: 소스}. 컴파일 소스 목록을 돌려준다."""
    dirpath.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (dirpath / name).write_text(text, encoding="utf-8")
    for name, text in harnesses.items():
        (dirpath / name).write_text(text, encoding="utf-8")
    return sorted(n for n in files if n.endswith(".c"))


def _compile(cc, flags, sources, dirpath, exe_name):
    exe = dirpath / exe_name
    cmd = [cc, *flags, f"-I{dirpath}", *(str(dirpath / s) for s in sources),
           "-lm", "-o", str(exe)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_TIMEOUT)
    return exe, r


def _run(exe, stdin, env=None, args=()):
    return subprocess.run([str(exe), *args], input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, timeout=TOOL_TIMEOUT)


def _data_rows(stdout):
    """하네스 stdout에서 수치 행만 — MCDC 덤프 줄은 계측 빌드에만 있다."""
    return [ln for ln in stdout.splitlines() if not ln.startswith("MCDC ")]


def _stdin_for(rec):
    warm = " ".join(repr(v) for v in rec["warm"])
    rows = "\n".join(
        " ".join(repr(row[k]) for k in rec["input_order"]) for row in rec["inputs"]
    )
    return warm + "\n" + rows + "\n"


# ── 파라미터 세트 (v1.12) ─────────────────────────────────────────────────


def _zero_table(inst):
    """룩업·다항 블록의 표가 전부 0인가 — 스케줄 게인 신호가 늘 0이라는 뜻."""
    table = inst.table
    if isinstance(inst, PolyBlock):
        return all(c == 0.0 for s in table.segments for c in s["coeffs"])
    return bool(np.all(np.asarray(table.data, dtype=float) == 0.0))


def deactivated_paths(runner):
    """요청 이미지에서 **값으로 꺼진** 경로 [{node, kind, title}] — 비활성 코드 목록 (DO-178C 비활성 코드 개념).

    탑재 C는 구조가 고정이라 이 경로들도 코드에 있다(v1.12 — 값이 구조를 바꾸지 않는다). 이 이미지로는 실행되지 않거나
    결과에 기여하지 않을 뿐이고, 커버리지는 파라미터 세트 합산으로 잰다. 판정은 그래프·인스턴스에서 한다:
      · PID 적분 경로 — ki가 상수 0이거나 ki 포트의 표가 전부 0 (가드의 증분 조건이 늘 거짓)
      · 게인 0 항 — Gain k = 0, 또는 곱의 한 입력이 전부 0인 스케줄 표
      · 워시아웃 꺼짐 — tau = ∞ (p = 1), 선택이 원 신호를 고른다
      · 1점 표 — 룩업의 구간 탐색·보간을 쓰지 않는다
    """
    zero = {}
    out = []
    for node in runner.graph.nodes:
        if node.kind != "block":
            continue
        inst = runner.instances[node.id]
        if isinstance(inst, (LookupBlock, PolyBlock)):
            zero[node.id] = _zero_table(inst)
            if isinstance(inst, LookupBlock) and len(inst.table.axes[0]) == 1:
                out.append({"node": node.id, "kind": "point_table",
                            "title": "1점 표 — 구간 탐색·보간을 쓰지 않는다"})
        elif isinstance(inst, PID):
            off = zero.get(node.gains["ki"], False) if "ki" in node.gains else inst.ki == 0.0
            if off:
                out.append({"node": node.id, "kind": "integrator",
                            "title": "적분 경로 — ki = 0 (가드의 증분 조건이 늘 거짓)"})
        elif isinstance(inst, Gain) and inst.k == 0.0:
            out.append({"node": node.id, "kind": "zero_gain", "title": "게인 0 — 항이 ±0.0"})
        elif isinstance(inst, Product) and any(zero.get(r, False) for r in node.inputs):
            out.append({"node": node.id, "kind": "zero_gain", "title": "스케줄 게인 0 — 곱이 ±0.0"})
        elif isinstance(inst, Washout) and inst._p == 1.0:
            out.append({"node": node.id, "kind": "washout_bypass",
                        "title": "워시아웃 꺼짐 — 선택이 원 신호를 고른다 (tau = ∞)"})
    return out


def _coverage_law(law, module):
    """커버리지 이미지의 법칙 — 요청 법칙에서 **값으로 꺼진 경로를 켠** 합성 값 → (law, 바꾼 것, 사유).

    구조를 바꾸지 않는 값만 바꾼다(구조 지문이 같아야 한 실행 파일로 돈다 — 다르면 None과 사유). 분석 그래프(표준 템플릿이
    아닌 법칙)는 k_rate·워시아웃·선회 FF 계수가 0에서 벗어나면 노드가 생겨 구조가 바뀌므로 적분 게인만 켠다.
      · 적분 게인 0 → 같은 축 비례 게인 부호로 |kp|의 10% (kp도 0이면 0.1)
      · 차동추력 계수 0 → 0.4 (게인 노드라 두 그래프 모두 구조 불변)
      · 1점 표가 하나도 없으면 배분 표를 1점 표로 (공용 룩업 헬퍼의 n < 2 분기)
      · SCAS k_rate 0 → 0.1 · 워시아웃 켜짐↔꺼짐(tau 0 ↔ 2 s — 선택 양쪽 분기) · 선회 FF 계수 0 → 0.05 ·
        승강률 댐핑 0 → −0.01 (표준 템플릿만)
    스케줄 표가 전부 0이면 같은 격자·같은 길이의 상수 표로 바꾼다(표 길이는 구조가 아니지만 절점 표 대 다항 표는 구조다 —
    다항 표는 건드리지 않는다).
    """
    from claw.fcl.autopilot import Autopilot
    from claw.fcl.graphs import AP_PARAM
    from claw.fcl.law import FlightControlLaw
    from claw.fcl.mixer import Mixer
    from claw.fcl.scas import Scas, ScasAxis
    from claw.fcl.schedule import GainSchedule
    from claw.tables import PointTable, PolyTable, Table

    standard = bool(getattr(law, "standard", False))
    ap = dict(law.autopilot.cfg)
    mix = dict(law.mixer.cfg)
    axes = {ax: dict(cfg) for ax, cfg in law.scas.cfg.items()}
    tables = dict(law.schedule.tables) if law.schedule is not None else {}
    changes = []

    def first(tab):
        return float(np.asarray(tab.data, dtype=float).ravel()[0])

    def slot_get(group, key):
        tab = tables.get(f"{group}.{key}")
        if tab is not None:
            return None if isinstance(tab, PolyTable) else (tab, first(tab))
        cfg = axes[group] if group in axes else ap
        name = key if group in axes else AP_PARAM[(group, key)]
        return None, float(cfg[name])

    def activate(group, key, value, why):
        got = slot_get(group, key)
        if got is None:
            return
        tab, cur = got
        if tab is not None:
            if not np.all(np.asarray(tab.data, dtype=float) == 0.0):
                return
            tables[f"{group}.{key}"] = Table({tab.axis_names[0]: tab.axes[0]},
                                             np.full(len(tab.axes[0]), value),
                                             name=tab.name, extrapolate=tab.extrapolate)
        elif cur != 0.0:
            return
        elif group in axes:
            axes[group][key] = value
        else:
            ap[AP_PARAM[(group, key)]] = value
        changes.append({"slot": f"{group}.{key}", "value": value, "why": why})

    def like(ref, scale=0.1):
        return math.copysign(scale * abs(ref), ref) if ref != 0.0 else scale

    for group in ("pitch", "roll", "yaw", "speed", "alt", "heading"):
        kp = slot_get(group, "kp")
        activate(group, "ki", like(kp[1] if kp is not None else 0.0), "적분 경로를 켠다")
    if ap.get("ki_vs", 0.0) == 0.0:
        ap["ki_vs"] = like(float(ap.get("kp_vs", 0.0)))
        changes.append({"slot": "ki_vs", "value": ap["ki_vs"], "why": "적분 경로를 켠다"})
    if mix.get("k_diff_thr", 0.0) == 0.0:
        mix["k_diff_thr"] = 0.4  # 단발 기체 — 배분식이 ±0.0으로 무너진 경로 (게인 노드라 구조는 그대로)
        changes.append({"slot": "k_diff_thr", "value": 0.4, "why": "차동추력 배분을 켠다"})
    if standard:
        for group in ("pitch", "roll", "yaw"):
            activate(group, "k_rate", 0.1, "레이트 경로를 켠다")
            # 워시아웃은 선택(switch_param)이라 양쪽 분기가 다 필요하다 — 꺼진 축은 켜고 켜진 축은 끈다
            if axes[group]["washout_tau"] == 0.0:
                axes[group]["washout_tau"] = 2.0
                changes.append({"slot": f"{group}.washout_tau", "value": 2.0, "why": "워시아웃을 켠다"})
            else:
                axes[group]["washout_tau"] = 0.0
                changes.append({"slot": f"{group}.washout_tau", "value": 0.0,
                                "why": "워시아웃을 끈다 — 선택의 반대편 분기"})
        activate("alt", "k_rate", -0.01, "승강률 댐핑을 켠다")
        for name in ("k_pitch_turn", "k_thr_turn"):
            if ap[name] == 0.0:
                ap[name] = 0.05
                changes.append({"slot": name, "value": 0.05, "why": "선회 FF를 켠다"})
    # 1점 표 경로(claw_lookup1d의 n < 2)는 공용 헬퍼 분기다 — 요청 이미지에 1점 표가 하나도 없으면(분석 그래프) 배분 표를
    # 1점 표로 바꿔 그 분기를 켠다. 표 길이는 값이라 구조는 그대로다(룩업 노드·축 불변)
    alloc = law.alloc_trim_table
    has_point = any(isinstance(inst, LookupBlock) and len(inst.table.axes[0]) == 1
                    for inst in law.runner.instances.values())
    if not has_point and alloc is not None and len(alloc.axes[0]) >= 2:
        trim0 = float(np.asarray(alloc.data, dtype=float).ravel()[0])
        alloc = PointTable(alloc.axis_names[0], trim0, name=alloc.name, at=float(alloc.axes[0][0]))
        changes.append({"slot": "alloc.de_trim", "value": trim0, "why": "1점 표 경로(룩업 n < 2)를 켠다"})
    if not changes:
        return None, [], "요청 이미지에 값으로 꺼진 경로가 없다 — 커버리지 세트가 필요 없다"

    schedule = (GainSchedule(tables, filter_tau=law.schedule.filter_tau)
                if law.schedule is not None else None)
    cov = FlightControlLaw(
        Scas(*(ScasAxis(**axes[a]) for a in ("pitch", "roll", "yaw"))), Autopilot(**ap), Mixer(**mix),
        schedule=schedule, alpha_limiter=law.alpha_limiter, alloc_trim_table=alloc,
        alloc_resv_frac=law.alloc_resv_frac, theta_hi_table=law.theta_hi_table, standard=standard,
    ).init(law.dt)
    if emit_c(cov.runner.graph, cov.runner).structure_fingerprint != module.structure_fingerprint:
        return None, changes, "커버리지 값이 구조를 바꿨다 — 같은 실행 파일로 돌 수 없어 세트에서 뺐다"
    return cov, changes, None


def _warm_reset(runner, warm):
    """하네스와 같은 트림 웜스타트 — 적분기 셋과 홀드 출력 (make_harness가 C에서 같은 대입을 한다)."""
    de0, th0, thr0 = warm
    states = {k: v for k, v in (("scas_pitch_pid", de0), ("ap_alt_pid", th0), ("ap_spd_pid", thr0))
              if k in runner.instances}
    runner.reset(states=states, hold={"elevon_l": de0, "elevon_r": de0, "rudder": 0.0,
                                      "throttle_l": thr0, "throttle_r": thr0})


# ── ⑦ SIL 대조 (통합) ─────────────────────────────────────────────────────


def _same_bits(a, b):
    """비트 일치 — `==`는 −0.0과 +0.0을 같게 본다. 표준 템플릿의 동등 논거가 ±0.0 합에 기대므로(07 §6.2) 부호 있는 0까지
    가른다. NaN끼리는 같게 친다(하네스의 %.17g 왕복이 NaN 페이로드를 보존하지 않는다)."""
    return struct.pack("<d", a) == struct.pack("<d", b) or (a != a and b != b)


def _compare_stream(c_rows, refs, order, dt, spans):
    """C 출력 행 ↔ 기준 출력 — 출력별 전 구간 대조 + 케이스 구간별 판정.

    허용오차 없음 — 배정밀도·동일 연산 순서라 목표는 비트 일치다.
    """
    outs = []
    for i, name in enumerate(order):
        first, max_err, equal = None, 0.0, 0
        for k, (row, ref) in enumerate(zip(c_rows, refs)):
            c, py = row[i], ref[name]
            if _same_bits(c, py):
                equal += 1
                continue
            err = abs(c - py)
            if math.isfinite(err):
                max_err = max(max_err, err)
            if first is None:
                first = {"step": k, "t": k * dt, "c": c, "py": py}
        outs.append({"name": name, "steps": len(c_rows), "equal": equal,
                     "first_diff": first, "max_abs_err": max_err})
    cases = []
    for span in spans:
        s, n = span["start"], span["steps"]
        diff = None
        for k in range(s, min(s + n, len(c_rows))):
            for i, name in enumerate(order):
                if not _same_bits(c_rows[k][i], refs[k][name]):
                    diff = {"step": k - s, "output": name,
                            "c": c_rows[k][i], "py": refs[k][name]}
                    break
            if diff:
                break
        cases.append({"id": span["id"], "title": span["title"], "unit": "fcl",
                      "steps": n, "status": "pass" if diff is None else "fail",
                      "first_diff": diff})
    ok = all(o["first_diff"] is None for o in outs)
    return {"status": "pass" if ok else "fail", "outputs": outs, "note": ""}, cases


def _exercised(rec, law, mission_steps):
    """대조 입력(미션 + 보강 벡터 전체)이 밟은 경로 단정 — test_parity 검사의 산출물판."""
    inputs = rec["inputs"]
    aborted = rec["meta"].get("aborted")

    def row(key, title, ok, detail):
        return {"key": key, "title": title,
                "status": "pass" if ok else "fail", "detail": detail}

    rows = [row("sim", "대조 미션 완주", aborted is None,
                f"미션 {mission_steps:,}스텝 + 보강 {len(inputs) - mission_steps:,}스텝"
                + ("" if aborted is None else f" — 절단: {aborted}"))]
    n_hold = sum(1 for r in inputs if r["nav_valid"] == 0.0)
    rows.append(row("hold", "항법 무효(출력 홀드) 구간", n_hold > 0, f"{n_hold}스텝"))
    missing = [f for f in ("speed_on", "alt_on", "heading_on", "pitch_on", "hdot_on")
               if {r[f] for r in inputs} != {0.0, 1.0}]
    rows.append(row("modes", "모드 플래그 5종이 켜짐·꺼짐 양쪽을 밟음", not missing,
                    "전부 양쪽" if not missing else f"한쪽만: {', '.join(missing)}"))
    n_mach = len({r["mach"] for r in inputs})
    rows.append(row("sched", "게인 스케줄 입력(mach)이 움직임", n_mach > 100,
                    f"서로 다른 mach {n_mach}개"))
    hi = float(law.mixer.cfg["elevon_hi"])
    n_sat = sum(1 for o in rec["outputs"] if abs(o.get("elevon_l", 0.0)) >= hi - 1e-3)
    rows.append(row("sat", "엘레본 포화 도달", n_sat > 0, f"{n_sat}스텝 (한계 {hi} rad)"))
    return rows


# ── ⑥ 커버리지 판독 ──────────────────────────────────────────────────────

_SHOW_LINE = re.compile(r"^\s*(\d+)\|\s*([0-9.kMG]*)\|")


def _parse_count(text):
    """llvm-cov show의 실행 횟수 칸 — 빈 칸은 비실행문(None), 1.2k류 축약 허용."""
    text = text.strip()
    if not text:
        return None
    mult = {"k": 1e3, "M": 1e6, "G": 1e9}.get(text[-1], 1.0)
    num = text[:-1] if text[-1] in "kMG" else text
    return int(float(num) * mult)


def _line_counts(cov_tool, exe, prof, dirpath, names):
    """파일별 [줄, 실행수] 목록 — 커버리지 소스 뷰어의 재료."""
    out = {}
    for name in names:
        r = subprocess.run(
            [cov_tool, "show", str(exe), f"-instr-profile={prof}",
             str(dirpath / name)],
            capture_output=True, text=True, timeout=TOOL_TIMEOUT)
        if r.returncode != 0:
            continue
        rows = []
        for line in r.stdout.splitlines():
            m = _SHOW_LINE.match(line)
            if m:
                cnt = _parse_count(m.group(2))
                if cnt is not None:
                    rows.append([int(m.group(1)), cnt])
        out[name] = rows
    return out


def _parse_export(export_json, files):
    """llvm-cov export JSON → 파일별 요약 + 미달성 분기 (하네스·계측 런타임 제외)."""
    gen_names = set(files)
    per_file, uncovered = [], []
    tot = {"lines": [0, 0], "branches": [0, 0], "regions": [0, 0]}
    for f in export_json.get("files", []):
        name = Path(f.get("filename", "")).name
        if name not in gen_names:
            continue
        s = f.get("summary", {})
        row = {"name": name}
        for key in ("lines", "branches", "regions"):
            k = s.get(key, {})
            row[key] = {"count": k.get("count", 0), "covered": k.get("covered", 0),
                        "percent": k.get("percent")}
            tot[key][0] += k.get("count", 0)
            tot[key][1] += k.get("covered", 0)
        per_file.append(row)
        src_lines = files[name].split("\n")
        for br in f.get("branches", []):
            if not isinstance(br, list) or len(br) < 6:
                continue
            line, n_true, n_false = br[0], br[4], br[5]
            miss = ("양쪽" if n_true == 0 and n_false == 0
                    else "참측" if n_true == 0
                    else "거짓측" if n_false == 0 else None)
            if miss:
                text = src_lines[line - 1].strip() if 0 < line <= len(src_lines) else ""
                uncovered.append({"file": name, "line": line, "col": br[1],
                                  "missing": miss, "text": text[:120]})
    per_file.sort(key=lambda r: r["name"])
    totals = {k: {"count": c, "covered": v,
                  "percent": (100.0 * v / c) if c else None}
              for k, (c, v) in tot.items()}
    return per_file, totals, uncovered


def _function_rows(files, line_counts, uncovered, mcdc_report):
    """함수 단위 집계 — 유닛 그리드의 아랫단 (VectorCAST의 function coverage)."""
    unc_by = {}
    for u in uncovered:
        unc_by.setdefault(u["file"], []).append(u["line"])
    dec_by = {}
    if mcdc_report and mcdc_report.get("decisions"):
        for d in mcdc_report["decisions"]:
            dec_by.setdefault(d["file"], []).append(d)
    rows = []
    for name in sorted(n for n in files if n.endswith(".c")):
        counts = dict(line_counts.get(name, []))
        for fn in functions_of(files[name]):
            lo, hi = fn["line"], fn["line"] + fn["lines"] - 1
            execable = [ln for ln in counts if lo <= ln <= hi]
            covered = [ln for ln in execable if counts[ln] > 0]
            decs = [d for d in dec_by.get(name, []) if lo <= d["line"] <= hi]
            rows.append({
                "file": name, "name": fn["name"], "line": lo,
                "lines": {"count": len(execable), "covered": len(covered)},
                "uncovered_branch_lines": sorted(
                    {ln for ln in unc_by.get(name, []) if lo <= ln <= hi}),
                "mcdc": {
                    "total": sum(len(d["conditions"]) for d in decs),
                    "covered": sum(sum(d["covered"]) for d in decs),
                    "justified": sum(len(d.get("justified_cis", [])) for d in decs),
                },
            })
    return rows


# ── ④ 유닛 시험 ──────────────────────────────────────────────────────────


def _unit_compare(spec, cases, oracle, c_rows):
    """유닛 케이스별 비트 대조 — [{id, title, unit, steps, status, first_diff}]."""
    out, k = [], 0
    exports = spec["exports"]
    for case in cases:
        n = len(case["rows"])
        diff = None
        for j in range(n):
            row, ref = c_rows[k + j], oracle[k + j]
            for i, name in enumerate(exports):
                if not _same_bits(row[i], ref[name]):
                    diff = {"step": j, "output": name, "c": row[i], "py": ref[name]}
                    break
            if diff:
                break
        out.append({"id": case["id"], "title": case["title"],
                    "unit": spec["group"], "steps": n,
                    "status": "pass" if diff is None else "fail",
                    "first_diff": diff})
        k += n
    return out


# ── 증적 조립 ─────────────────────────────────────────────────────────────


def _pct(x):
    return "—" if x is None else f"{x:.1f}%"


def _unit_rows(specs, files, per_file, mcdc_report, case_rows):
    """유닛 그리드 행 — 파티션 5 + 통합/조립 + 파라미터 로더 + 공용 런타임."""
    cov_by = {r["name"]: r for r in per_file}
    dec_by = {}
    if mcdc_report and mcdc_report.get("decisions"):
        for d in mcdc_report["decisions"]:
            dec_by.setdefault(d["file"], []).append(d)
    base = "fcl"

    def agg(names):
        lines = [0, 0]
        branches = [0, 0]
        mc = [0, 0, 0]
        for n in names:
            r = cov_by.get(n)
            if r:
                lines[0] += r["lines"]["count"]
                lines[1] += r["lines"]["covered"]
                branches[0] += r["branches"]["count"]
                branches[1] += r["branches"]["covered"]
            for d in dec_by.get(n, []):
                mc[0] += len(d["conditions"])
                mc[1] += sum(d["covered"])
                mc[2] += len(d.get("justified_cis", []))
        def pack(c, v):
            return {"count": c, "covered": v,
                    "percent": (100.0 * v / c) if c else None}
        return {"lines": pack(*lines), "branches": pack(*branches),
                "mcdc": {"total": mc[0], "covered": mc[1], "justified": mc[2]}}

    rows = []
    for spec in specs:
        g = spec["group"]
        names = [f"{base}_{g}.c", f"{base}_{g}.h"]
        cases = [c for c in case_rows if c["unit"] == g]
        rows.append({
            "unit": g, "title": spec["title"], "files": names,
            "harness": True, "cases": {
                "total": len(cases),
                "passed": sum(1 for c in cases if c["status"] == "pass"),
                "skipped": sum(1 for c in cases if c["status"] == "skip"),
            },
            **agg(names),
        })
    int_cases = [c for c in case_rows if c["unit"] == base]
    rows.append({
        "unit": base, "title": "통합 — 조립부·전 법칙 (SIL)",
        "files": [f"{base}.c", f"{base}.h", f"{base}_types.h"],
        "harness": True, "cases": {
            "total": len(int_cases),
            "passed": sum(1 for c in int_cases if c["status"] == "pass"),
            "skipped": sum(1 for c in int_cases if c["status"] == "skip"),
        },
        **agg([f"{base}.c"]),
    })
    prm_cases = [c for c in case_rows if c["unit"] == "params"]
    rows.append({
        "unit": "params", "title": "파라미터 로더 — 이미지 적재·거부 경로",
        "files": [f"{base}_params.c", f"{base}_params.h"], "harness": bool(prm_cases),
        "cases": {
            "total": len(prm_cases),
            "passed": sum(1 for c in prm_cases if c["status"] == "pass"),
            "skipped": sum(1 for c in prm_cases if c["status"] == "skip"),
        },
        **agg([f"{base}_params.c"]),
    })
    rows.append({
        "unit": "claw_rt", "title": "공용 런타임 (헬퍼)",
        "files": ["claw_rt.c", "claw_rt.h"], "harness": False,
        "cases": {"total": 0, "passed": 0, "skipped": 0},
        **agg(["claw_rt.c"]),
    })
    return rows


def _dal_table(report):
    """DO-178C 목표 대응표 — 자동/부분/범위 밖을 엔진이 문구까지 낸다 (화면 정본)."""
    cov = report["coverage"]
    mc = report["mcdc"]
    measured = cov.get("status") == "measured"

    def r(ref, objective, status, evidence):
        return {"ref": ref, "objective": objective, "status": status,
                "evidence": evidence}

    auto = "auto" if measured else "skip"
    return [
        r("A-7 #5", "구조적 커버리지 — 문장/라인 (DAL C↑)", auto,
          "llvm-cov 라인 커버리지 — 통합 미션 + 보강 벡터 + 유닛 시험 합산"
          if measured else cov.get("reason", "측정 생략")),
        r("A-7 #6", "구조적 커버리지 — 결정/분기 (DAL B↑)", auto,
          "llvm-cov 분기 커버리지 — 단일 조건 결정의 MC/DC는 이것으로 충족"
          "(조건이 하나면 MC/DC ≡ 분기)" if measured else cov.get("reason", "측정 생략")),
        r("A-7 #5(A)", "구조적 커버리지 — MC/DC (DAL A)",
          "auto" if mc.get("status") == "measured" else "skip",
          "다조건 결정에 자체 계측(생성 C 프로브) — masking MC/DC, 계측 무해성 "
          "자기검사 포함" if mc.get("status") == "measured"
          else mc.get("reason", "측정 생략")),
        r("A-7 #8", "데이터·제어 결합 커버리지", "partial",
          "파티션 경계 신호는 IR이 자동 열거(함수 인자 = 결합 전부)하고 유닛·통합 "
          "실행이 전 신호를 태운다 — 결합 분석 문서 작성은 수동 몫"),
        r("A-7 #4", "저수준 요구 기반 시험", "partial",
          "저수준 요구 = Python 설계 모델(IR)로 두고 모델 대비 비트 대조 — 요구 "
          "문서 계층·추적 도구는 범위 밖"),
        r("A-7 #3", "고수준 요구 기반 시험", "out",
          "요구 관리 계층 부재 — 시스템 요구 문서와의 추적은 이 도구 밖"),
        r("A-7 obj.", "소스↔오브젝트 코드 추적성 (DAL A 추가)", "out",
          "타깃 컴파일러 산출물 분석·PIL은 FCC팀 몫 — 생성 헤더가 빌드 조건"
          "(FMA 금지 등)을 명시하는 데까지가 이 도구의 범위"),
        r("A-5", "소스 코드 검토 — 표준 부합·정확성", "partial",
          "생성 코드 규율 검사(금지 구문·재귀·가변 전역·복잡도) + 엄격 컴파일 경고 "
          "0 — MISRA 전 규칙 검토는 상용 정적분석기의 자리"),
        r("A-5 #8", "죽은 코드 없음 · 비활성 코드 식별", "auto",
          "죽은 코드: IR이 도달 불가 노드를 생성 시점에 거부한다. 비활성 코드: 구조가 고정이라 "
          "파라미터 값으로만 생기며(ki = 0 적분기·게인 0 항·tau = ∞ 워시아웃·1점 표) 목록화하고"
          f"(비활성 {len(report.get('deactivated', []))}건), 구조적 커버리지는 파라미터 세트"
          f"({len(report.get('param_sets', []))}개 이미지) 합산으로 잰다 — DO-178C 비활성 코드 개념"),
        r("PDI", "파라미터 데이터 항목 — 이미지 검증", "partial",
          "이미지 의미 검사(유한값·표 모양·한계 순서·이산 계수) + 생성 로더의 거부 경로 시험(구조 지문·"
          "dt·CRC·길이·표 모양·pool·NaN) + 세트 이미지마다 SIL 비트 대조 — 장입 매체·보관·BIT와 "
          "파라미터 데이터 항목 문서화는 FCC 몫(02 §1)"),
        r("DO-330", "도구 적격성 (TQL)", "out",
          "이 검증기 자체가 틀리지 않는다는 입증은 별개 사업 — 인증용 독립 검증은 "
          "적격성 키트를 갖춘 상용 도구(LDRA·VectorCAST류)의 자리"),
    ]


def _summary(report):
    """판정판 여섯 줄 — 화면이 다시 적지 않도록 문구까지 엔진이 낸다."""
    rows = []
    st = report["static"]
    n_fail = sum(1 for r in st["rules"] if r["status"] == "fail")
    rows.append({
        "key": "static", "label": "정적 — 생성 코드 규율",
        "status": "pass" if n_fail == 0 else "fail",
        "detail": f"규칙 {len(st['rules']) - n_fail}/{len(st['rules'])} 통과 · "
                  f"함수 {st['totals']['functions']}개 · "
                  f"최대 복잡도 {st['totals']['max_complexity']}",
    })
    comp = report["compile"]
    rows.append({
        "key": "compile", "label": "컴파일 — 엄격 플래그 경고 0",
        "status": comp["status"],
        "detail": (comp.get("reason", "") if comp["status"] == "skip"
                   else f"{comp['cc']} · 빌드 {comp['builds']}개 · "
                        f"경고 {comp['warnings']}건"
                        + ("" if comp["ok"] else " · 컴파일 실패")),
    })
    ex = report["exercised"]
    n_bad = sum(1 for r in ex if r["status"] == "fail")
    rows.append({
        "key": "paths", "label": "대조 입력 — 어려운 경로를 밟았나",
        "status": "pass" if n_bad == 0 else "fail",
        "detail": f"{len(ex) - n_bad}/{len(ex)} 경로" + (
            "" if n_bad == 0 else " — 안 밟은 경로의 일치는 검증이 아니다"),
    })
    eq = report["equivalence"]
    cases = report["cases"]
    if eq["status"] == "skip":
        detail = eq.get("reason", "")
        status = "skip"
    else:
        eq_cases = [c for c in cases if c["unit"] != "params"]  # 로더 거부 경로는 이미지 행이 판정한다
        n_fail_case = sum(1 for c in eq_cases if c["status"] == "fail")
        status = "pass" if (eq["status"] == "pass" and n_fail_case == 0) else "fail"
        n_unit = sum(1 for c in eq_cases if c["unit"] != report["artifact"])
        n_sets = len(report.get("param_sets") or [None])
        detail = (f"통합 {report['steps']:,}스텝 + 유닛 케이스 {n_unit}개 · 파라미터 세트 {n_sets}개 — "
                  + ("전 스텝 비트 일치" if status == "pass"
                     else f"불일치 케이스 {n_fail_case}개"))
    rows.append({"key": "equiv", "label": "동등성 — Python↔C 비트 일치 (SIL)",
                 "status": status, "detail": detail})
    img = report.get("param_image")
    if img is not None:
        bad = [c for c in img["checks"] if not c["ok"]]
        prm = [c for c in report.get("cases", []) if c["unit"] == "params"]
        n_pass = sum(1 for c in prm if c["status"] == "pass")
        if bad or any(c["status"] == "fail" for c in prm):
            st = "fail"
        elif prm and all(c["status"] == "skip" for c in prm):
            st = "skip"
        else:
            st = "pass"
        rows.append({
            "key": "params", "label": "파라미터 이미지 — 의미 검사·로더 거부 경로", "status": st,
            "detail": f"의미 검사 {len(img['checks']) - len(bad)}/{len(img['checks'])} · "
                      f"로더 상태 {n_pass}/{len(prm)} · {img['bytes']:,}바이트 CRC-32 0x{img['crc32']:08x}",
        })
    cov = report["coverage"]
    mc = report["mcdc"]
    if cov["status"] != "measured":
        rows.append({"key": "coverage", "label": "구조적 커버리지 — DAL A 목표",
                     "status": "skip", "detail": cov.get("reason", "측정 생략")})
    else:
        t = cov["totals"]
        n_jb = len(cov.get("justified", []))
        mc_ok = (mc.get("status") == "measured"
                 and mc.get("covered", 0) + mc.get("justified", 0)
                 == mc.get("total", 0))
        full = (t["lines"]["covered"] == t["lines"]["count"]
                and t["branches"]["covered"] + n_jb == t["branches"]["count"]
                and mc_ok)
        mc_txt = ("—" if mc.get("status") != "measured"
                  else f"{mc['covered']}"
                       + (f"+{mc['justified']}" if mc.get("justified") else "")
                       + f"/{mc['total']}")
        jus_txt = f" · 정당화 {n_jb + mc.get('justified', 0)}건" if (
            n_jb or mc.get("justified")) else ""
        rows.append({
            "key": "coverage", "label": "구조적 커버리지 — DAL A 목표 (100%)",
            "status": "pass" if full else "fail",
            "detail": f"라인 {_pct(t['lines']['percent'])} · "
                      f"분기 {t['branches']['covered']}"
                      + (f"+{n_jb}" if n_jb else "")
                      + f"/{t['branches']['count']} · "
                      f"MC/DC 조건 {mc_txt} · "
                      f"미달성 {len(cov['uncovered_branches'])}곳{jus_txt}",
        })
    return rows


# ── 오케스트레이터 ────────────────────────────────────────────────────────


def verify_flight(law, *, profile, t_end=180.0, control_hz=100.0, on_progress=None,
                  keep_dir=None, with_vectors=True):
    """초기화된 법칙(`law.init(dt)` 완료) → 검증 리포트 dict. 취소되면 None.

    on_progress(done, total, message) — truthy 반환 = 협조적 취소 (Job.report 계약).
    with_vectors=False는 테스트용 — 보강·유닛 벡터·커버리지 세트 없이 미션만 (커버리지 미달이
    정직하게 fail로 나오는지를 이걸로 고정한다).

    **파라미터 세트 (v1.12).** 실행 파일은 구조 하나로 한 번 빌드하고 이미지만 바꿔 돈다 — 요청 기체 이미지(미션 + 통합
    벡터 + 유닛)와 커버리지 세트(값으로 꺼진 경로를 켠 합성 이미지 — 통합 벡터 + 유닛). 이미지마다 SIL 비트 일치를 보고,
    라인·분기·MC/DC는 합산한다. 생성 로더의 거부 경로는 손상 이미지 유닛(`params`)이 태운다. 요청 이미지에서 값으로 꺼진
    경로는 `deactivated`로 목록화하고 어느 세트가 덮었는지를 함께 싣는다. 판정선은 그대로다(100%).
    """
    cancelled = []

    def tick(pct, msg):
        if on_progress is not None and on_progress(int(pct), 100, msg):
            cancelled.append(True)
        return bool(cancelled)

    runner = law.runner
    graph = runner.graph
    if len(graph.outputs) < 2:
        raise ValueError(f"{graph.name}: 다중 출력 그래프만 검증 대상 (fcl 계열)")

    # ── 생성 (① 앞) — 구조 한 벌 + 파라미터 세트의 이미지 ──
    if tick(2, "탑재 C·파라미터 이미지 생성"):
        return None
    module = emit_c(graph, runner)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))
    lineage = getattr(profile, "fingerprint", None)
    image = param_image.pack(module, lineage=lineage)  # 의미 검사 실패면 ValueError — 이미지를 만들지 않는다
    sets = [{"id": "request", "title": "요청 기체", "role": "request", "law": law,
             "module": module, "image": image, "changes": []}]
    cover_note = None
    if with_vectors:
        cov, changes, cover_note = _coverage_law(law, module)
        if cov is not None:
            cmod = emit_c(cov.runner.graph, cov.runner)
            sets.append({"id": "cover-1", "title": "커버리지 세트 — 값으로 꺼진 경로를 켠 합성 값",
                         "role": "coverage", "law": cov, "module": cmod,
                         "image": param_image.pack(cmod), "changes": changes})
    specs = unit_specs(graph) if with_vectors else []
    harnesses = {"verify_harness.c": make_harness(graph, runner)}
    for spec in specs:
        harnesses[f"unit_{spec['group']}.c"] = make_unit_harness(graph.name, spec)
    if with_vectors:
        harnesses["unit_params.c"] = make_params_harness(graph.name)

    # ── ①~③ 정적 ──
    if tick(4, "정적 규율 검사"):
        return None
    static = static_analyze(files)
    deactivated = deactivated_paths(runner)
    off_by_set = {s["id"]: {d["node"] for d in deactivated_paths(s["law"].runner)} for s in sets}
    multi_lookup = any(isinstance(inst, LookupBlock) and len(inst.table.axes[0]) >= 2
                       for inst in runner.instances.values())
    for d in deactivated:
        if d["kind"] == "point_table":
            # 1점 표의 구간 탐색·보간은 노드마다의 코드가 아니라 공용 헬퍼(claw_lookup1d) 경로다 — 같은 이미지의
            # 다점 표가 그 경로를 태운다
            d["covered_by"] = ["request"] if multi_lookup else []
        else:
            d["covered_by"] = [s["id"] for s in sets if s["role"] == "coverage"
                               and d["node"] not in off_by_set[s["id"]]]

    report = {
        "artifact": graph.name,
        "structure_fingerprint": module.structure_fingerprint,
        "param_fingerprint": module.param_fingerprint,
        "template": getattr(law, "template", None),
        "engine": claw.__version__,
        "dt": law.dt,
        "t_end": t_end,
        "files": [{"name": n, "lines": files[n].count("\n"), "text": files[n]}
                  for n in sorted(files)],
        "param_image": {"bytes": len(image), "crc32": param_image.unpack(image, module)["crc32"],
                        "lineage": lineage, "checks": param_image.checks(module)},
        "param_sets": [{"id": s["id"], "title": s["title"], "role": s["role"],
                        "param_fingerprint": s["module"].param_fingerprint, "changes": s["changes"]}
                       for s in sets],
        "deactivated": deactivated,
        "static": static,
        "stubs": {"needed": 0, "note":
                  "스텁·목이 필요 없는 구조다 — 생성 법칙은 외부 의존 0(플랜트·"
                  "항법·작동기는 법칙 밖, 수학은 libm뿐)이고, 파티션의 상류는 "
                  "스텁이 아니라 임포트 값 그 자체다."},
    }
    if cover_note:
        report["param_sets_note"] = cover_note

    cc = find_cc()
    report["toolchain"] = {
        "cc": cc,
        "llvm_cov": bool(find_llvm_tool("llvm-cov") and find_llvm_tool("llvm-profdata")),
    }

    with tempfile.TemporaryDirectory(prefix="claw-verify-") as tmp:
        root = Path(keep_dir) if keep_dir else Path(tmp)
        strict_dir = root / "strict"
        img_dir = root / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        for s in sets:
            s["path"] = img_dir / f"{s['id']}.bin"
            s["path"].write_bytes(s["image"])

        # ── ② 엄격 컴파일 (통합 + 유닛 하네스 전부 — 구조 하나라 한 번) ──
        exes = {}
        if cc is None:
            report["compile"] = {
                "status": "skip", "reason": "C 컴파일러 없음 (cc/gcc/clang) — "
                "정적·경로 검사만 수행, 대조·유닛·커버리지는 생략",
            }
        else:
            if tick(6, "엄격 컴파일"):
                return None
            sources = _write_tree(strict_dir, files, harnesses)
            warnings, ok, log = 0, True, []
            for hname in harnesses:
                exe, r = _compile(cc, STRICT_FLAGS, [hname, *sources], strict_dir,
                                  hname[:-2])
                warnings += len(re.findall(r"\bwarning:", r.stderr))
                if r.returncode != 0:
                    ok = False
                    log.append(r.stderr[-1500:])
                else:
                    exes[hname[:-2]] = exe
                if r.stderr and len(log) < 3:
                    log.append(r.stderr[-800:])
            report["compile"] = {
                "status": "pass" if (ok and warnings == 0) else "fail",
                "ok": ok, "cc": Path(cc).name, "flags": STRICT_FLAGS,
                "builds": len(harnesses), "warnings": warnings,
                "log": "\n".join(log)[-3000:],
            }

        # ── ⑦ 대조 미션 + 통합 보강 벡터 (요청 이미지) ──
        if tick(10, "대조 미션 기록"):
            return None
        rec = record_mission(
            law, profile=profile, t_end=t_end, control_hz=control_hz,
            on_progress=(lambda d, t: tick(10 + 36.0 * d / max(t, 1), "대조 미션 기록"))
            if on_progress is not None else None,
        )
        if cancelled or rec["meta"].get("aborted") == "cancelled":
            return None
        rec["input_order"] = tuple(graph.inputs)
        mission_steps = len(rec["inputs"])
        spans = [{"id": f"TC-MISSION-{int(t_end)}S",
                  "title": f"통합 — 폐루프 대조 미션 {t_end:g} s",
                  "start": 0, "steps": mission_steps}]
        if with_vectors and rec["meta"].get("aborted") is None:
            if tick(48, "통합 보강 벡터 실행"):
                return None
            for case in _integration_cases(law):
                start = len(rec["inputs"])
                for row in case["rows"]:
                    out = law.runner.step_all(**row)
                    rec["inputs"].append(row)
                    rec["outputs"].append({k: float(v) for k, v in out.items()})
                spans.append({"id": case["id"], "title": case["title"],
                              "start": start, "steps": len(case["rows"])})
        report["steps"] = len(rec["inputs"])
        report["trace"] = {"aborted": rec["meta"].get("aborted"),
                           "mission_steps": mission_steps,
                           "steps": len(rec["inputs"])}
        report["exercised"] = _exercised(rec, law, mission_steps)
        sets[0]["rec"], sets[0]["spans"] = rec, spans

        # 커버리지 세트는 미션 없이 통합 벡터만 — 합성 값으로 폐루프를 날리는 것은 의미가 없고, 벡터는 값과 무관하게 경로를 민다
        for s in sets[1:]:
            r = s["law"].runner
            _warm_reset(r, rec["warm"])
            crec = {"warm": rec["warm"], "inputs": [], "outputs": [],
                    "input_order": tuple(graph.inputs), "output_order": rec["output_order"]}
            s["spans"] = []
            for case in _integration_cases(s["law"]):
                start = len(crec["inputs"])
                for row in case["rows"]:
                    crec["inputs"].append(row)
                    crec["outputs"].append({k: float(v) for k, v in r.step_all(**row).items()})
                s["spans"].append({"id": f"{case['id']}@{s['id']}", "title": f"{case['title']} — {s['title']}",
                                   "start": start, "steps": len(case["rows"])})
            s["rec"] = crec

        # ── ⑦ SIL 대조 (통합, 이미지마다) ──
        strict_out = {}
        case_rows = []
        runs = []
        int_exe = exes.get("verify_harness")
        eq_sets = []
        for s in sets:
            tag = f"verify_harness@{s['id']}"
            runs.append({"tag": tag, "harness": "verify_harness", "stdin": _stdin_for(s["rec"]),
                         "args": [str(s["path"])]})
            if int_exe is None:
                reason = (report["compile"].get("reason")
                          or "엄격 컴파일 실패 — 실행 파일이 없다")
                eq = {"status": "skip", "reason": reason, "outputs": []}
                rows = [{**sp, "unit": graph.name, "status": "skip", "first_diff": None} for sp in s["spans"]]
                for row in rows:
                    row.pop("start", None)
            else:
                if tick(56, f"Python↔C 대조 (통합 — {s['title']})"):
                    return None
                run = _run(int_exe, runs[-1]["stdin"], args=runs[-1]["args"])
                rows = []
                if run.returncode != 0:
                    eq = {"status": "fail", "outputs": [],
                          "note": f"하네스 실행 실패 (rc {run.returncode}): {run.stderr[:500]}"}
                else:
                    strict_out[tag] = _data_rows(run.stdout)
                    c_rows = [[float(x) for x in ln.split()] for ln in strict_out[tag]]
                    if len(c_rows) != len(s["rec"]["inputs"]):
                        eq = {"status": "fail", "outputs": [],
                              "note": f"출력 {len(c_rows)}행 ≠ 입력 {len(s['rec']['inputs'])}행"}
                    else:
                        eq, rows = _compare_stream(c_rows, s["rec"]["outputs"], rec["output_order"],
                                                   law.dt, s["spans"])
            for row in rows:
                row["param_set"] = s["id"]
            case_rows += rows
            eq_sets.append({"id": s["id"], "title": s["title"], "status": eq["status"]})
            if s["role"] == "request":
                report["equivalence"] = eq
        if eq_sets and report["equivalence"]["status"] == "pass" and any(e["status"] == "fail" for e in eq_sets):
            report["equivalence"] = {**report["equivalence"], "status": "fail",
                                     "note": "커버리지 세트 이미지의 대조가 어긋났다"}
        report["equivalence"]["param_sets"] = eq_sets

        # ── ④ 유닛 시험 (이미지마다) ──
        for idx, spec in enumerate(specs):
            g = spec["group"]
            for s in sets:
                sspec = next(x for x in unit_specs(s["law"].runner.graph) if x["group"] == g)
                cases = vectors.unit_cases(g, spec["imports"])
                stdin = unit_stdin(spec, cases)
                sfx = "" if s["role"] == "request" else f"@{s['id']}"
                tag = f"unit_{g}@{s['id']}"
                runs.append({"tag": tag, "harness": f"unit_{g}", "stdin": stdin, "args": [str(s["path"])]})
                titled = [{"id": c["id"] + sfx, "title": c["title"] + ("" if not sfx else f" — {s['title']}"),
                           "rows": c["rows"]} for c in cases]
                if f"unit_{g}" not in exes:
                    case_rows += [{"id": c["id"], "title": c["title"], "unit": g, "param_set": s["id"],
                                   "steps": len(c["rows"]), "status": "skip", "first_diff": None}
                                  for c in titled]
                    continue
                if tick(58 + 3 * idx, f"유닛 시험 — {g} ({s['title']})"):
                    return None
                oracle = run_unit_oracle(sspec, law.dt, [r for c in cases for r in c["rows"]])
                run = _run(exes[f"unit_{g}"], stdin, args=[str(s["path"])])
                if run.returncode != 0:
                    case_rows += [{"id": c["id"], "title": c["title"], "unit": g, "param_set": s["id"],
                                   "steps": len(c["rows"]), "status": "fail",
                                   "first_diff": {"step": 0, "output": "(실행 실패)",
                                                  "c": 0.0, "py": 0.0}}
                                  for c in titled]
                    continue
                strict_out[tag] = _data_rows(run.stdout)
                c_rows = [[float(x) for x in ln.split()] for ln in strict_out[tag]]
                for row in _unit_compare(spec, titled, oracle, c_rows):
                    row["param_set"] = s["id"]
                    case_rows.append(row)

        # ── ④ 파라미터 로더 유닛 — 손상 이미지 → 상태 코드 ──
        if with_vectors:
            corrupt = param_image.corruptions(module, lineage=lineage)
            stdin = params_stdin(corrupt)
            runs.append({"tag": "unit_params", "harness": "unit_params", "stdin": stdin, "args": []})
            got = None
            if "unit_params" in exes:
                if tick(74, "유닛 시험 — 파라미터 로더"):
                    return None
                run = _run(exes["unit_params"], stdin)
                if run.returncode == 0:
                    strict_out["unit_params"] = _data_rows(run.stdout)
                    got = strict_out["unit_params"]
            for k, c in enumerate(corrupt):
                want = param_image.STATUS[c["status"]]
                if "unit_params" not in exes:
                    status, diff = "skip", None
                elif got is None or k >= len(got):
                    status, diff = "fail", {"step": 0, "output": "(실행 실패)", "c": 0.0, "py": float(want)}
                else:
                    ok = int(got[k].split()[0]) == want
                    status = "pass" if ok else "fail"
                    diff = None if ok else {"step": 0, "output": "status", "c": float(got[k].split()[0]),
                                            "py": float(want)}
                case_rows.append({"id": f"TC-PRM-{c['id']}", "unit": "params", "param_set": "request",
                                  "title": f"로더 — {c['title']} → {c['status']}", "steps": 1,
                                  "status": status, "first_diff": diff})
        report["cases"] = case_rows

        # ── ⑥ 커버리지 + MC/DC (전 이미지·전 하네스 합산) ──
        report["coverage"] = {"status": "skip",
                              "reason": "C 컴파일러 없음 — 계측 빌드 불가"}
        report["mcdc"] = {"status": "skip", "reason": "커버리지 빌드 없음"}
        if cc is not None:
            if tick(76, "커버리지·MC/DC 계측 빌드"):
                return None
            report["coverage"], report["mcdc"] = _measure_coverage(
                cc, files, harnesses, runs, strict_out,
                [s["law"].runner for s in sets], root / "cov", tick)
            # 커버리지 단계 **안에서** 취소되면 그 사유는 skip 문구로만 남는다 —
            # 그대로 반환하면 반쪽 판정이 완료 리포트로 저장된다 (서버는 None만
            # 취소로 읽는다). 취소는 결과를 내지 않는 것이 계약이다
            if cancelled:
                return None

        report["units"] = _unit_rows(specs, files, report["coverage"].get("files", []),
                                     report["mcdc"], case_rows)

    report["dal"] = _dal_table(report)
    report["summary"] = _summary(report)
    fails = [r for r in report["summary"] if r["status"] == "fail"]
    skips = [r for r in report["summary"] if r["status"] == "skip"]
    report["verdict"] = ("fail" if fails
                         else "pass_with_skips" if skips else "pass")
    if on_progress is not None:
        on_progress(100, 100, "완료")
    return report


def _integration_cases(law):
    """법칙의 통합 보강 케이스 — 게인에서 길이를 정하는 케이스(θ 상한 하강)까지 그 법칙 값으로."""
    ap_cfg = getattr(getattr(law, "autopilot", None), "cfg", None)
    theta_hi = getattr(law, "theta_hi_table", None) is not None
    return vectors.integration_cases(ap_cfg, law.runner.dt, theta_hi=theta_hi)


_COUPLED_REASON = (
    "구조적 종속 — 적분기 클램프 불변식(i ∈ [lo, hi])에서 raw > hi ⇒ kp·e > 0이고, "
    "ki·kp 동부호 상수라 inc > 0이 반드시 함께 참이다(하한 대칭). 감쇠항(u_ext)도 "
    "미분항(kd)도 없는 축이라 함의를 깨는 항이 없어 독립쌍이 수학적으로 존재하지 "
    "않는다 — 측정이 아니라 분석으로 정당화한다 (DO-178C 커버 대체)."
)


def _port_bound(graph, runner, ref, side):
    """한계 신호의 정적 경계 — 상수 `side` 한계를 가진 영역 밖 Saturation 출력이면 그 값, 아니면 ∓∞(보장 없음).

    fcl의 θ 상한 신호(`ap_theta_hi`)가 이 모양이다 — [theta_lo, theta_hi]로 묶여 고도·승강률 PID 하한(theta_lo) 아래로
    못 내려간다. 영역 안 노드는 비활성 스텝에 disabled_output(0.0)을 내므로 보장이 없다.
    """
    none = -math.inf if side == "lo" else math.inf
    try:
        src = graph.node(ref)
    except KeyError:
        return none  # 그래프 입력 — 무엇이든 들어온다
    if src.kind != "block" or src.block is not Saturation or side in src.gains or src.enable is not None:
        return none
    return float(getattr(runner.instances[ref], side))


def _gain_signs(graph, runner, node, inst, key):
    """게인의 정적 부호 집합 — 상수면 그 값, 스케줄 룩업 포트면 표의 전 값(선형 보간은 같은 부호끼리 섞여 부호가 유지된다).
    다항 표·다른 신호면 None(모른다)."""
    ref = node.gains.get(key)
    if ref is None:
        return {math.copysign(1.0, getattr(inst, key)) if getattr(inst, key) != 0.0 else 0.0}
    try:
        src = graph.node(ref)
    except KeyError:
        return None
    if src.kind != "block" or src.block is not LookupBlock:
        return None
    data = np.asarray(runner.instances[ref].table.data, dtype=float).ravel()
    return {math.copysign(1.0, v) if v != 0.0 else 0.0 for v in data}


def _coupled_guards(decisions, runners):
    """독립쌍이 수학적으로 부재한 가드 조건 — {결정 id: {cis, reason}}.

    대상: PID 가드의 c1·c3(`inc` 부호 조건). 근거는 그래프·인스턴스에서 직접
    판정한다 — 텍스트 추측이 아니라 조립 정본이 말하게 한다.

    **정당화는 값에 의존하므로 파라미터 세트의 모든 이미지에서 성립할 때만 인정한다**(v1.12). runners는 이미지마다의
    러너(구조가 같다)다 — 한 러너만 주면 그 하나로 본다.

    **정당화는 측정의 대체이므로 조건을 좁게 잡는다.** 하나라도 함의를 깰 수 있는
    항이 있으면 정당화하지 않고 미커버로 남긴다 — 거짓 정당화는 이 기능의 존재
    이유를 정면으로 거스르고, 놓친 정당화는 그저 fail 한 줄이다:
      · 감쇠항 u_ext가 있는 축(`_hi_x`·`_lo_x`형) — 판정량이 raw와 raw + u_ext 중 큰 쪽이라 kp·e > 0을 함의하지 않는다
      · kd ≠ 0이거나 kd가 포트 — 미분항이 raw를 밀어 e < 0에서도 hi를 넘을 수 있다
      · kp·ki의 부호 — 상수거나 **스케줄 룩업 포트면 표의 전 값**이 한 부호이고 둘의 곱이 양수여야 한다(v1.12 표준
        템플릿은 모든 자리가 룩업이다 — 1점 표 포함). 다항 표·다른 신호면 모른다고 보고 정당화하지 않는다
      · 한계는 **쪽마다** 본다: 포트인 쪽의 조건만 뺀다(v1.11). 상수 쪽도 반대편 신호가 그 상수를 못 넘는다는 그래프
        보장(상수 한계로 묶인 포화 출력 — `_port_bound`)이 있을 때만 인정한다.
        상한이 신호(θ_hi(M))면 스텝 사이에 상한이 내려갈 때
        적분기가 직전 상한에 남아 새 상한 위에 있을 수 있어 오차 ≤ 0에서도 raw > hi가 된다 — 독립쌍이 실재한다.
        상수인 하한 쪽은 적분기가 늘 하한 이상이라 raw < lo가 여전히 kp·e < 0을 함의한다
    """
    runners = list(runners) if isinstance(runners, (list, tuple)) else [runners]
    graph = runners[0].graph
    out = {}
    for d in decisions:
        if d["kind"] != "guard":
            continue
        atom = d["conditions"][0].split()[0]  # "<nid>_raw" 또는 "<nid>_hi_x"
        if not atom.endswith("_raw"):
            continue  # u_ext 있는 축 — 판정량이 max(raw, raw + u_ext)라 함의가 깨진다
        nid = atom[: -len("_raw")]
        try:
            node = graph.node(nid)
        except KeyError:
            continue
        if "kd" in node.gains:
            continue
        ok = True
        for r in runners:
            inst = r.instances.get(nid)
            if inst is None or inst.kd != 0.0:
                ok = False
                break
            kp, ki = (_gain_signs(r.graph, r, node, inst, k) for k in ("kp", "ki"))
            if kp is None or ki is None or len(kp) != 1 or len(ki) != 1 or next(iter(kp)) * next(iter(ki)) <= 0:
                ok = False
                break
        if not ok:
            continue
        # c1은 상한 쪽(raw > hi && inc > 0), c3은 하한 쪽 — 한계가 상수인 쪽만 정당화한다. 반대편이 신호면 그 신호가
        # 상수 쪽을 **넘지 않음이 그래프에서 보장될 때만** 인정한다: 신호 상한이 상수 하한 아래로 내려가는 스텝에는 적분기
        # 클램프가 상한으로 가 i < lo가 되고, 그러면 raw < lo가 kp·e < 0을 함의하지 않는다(상한 쪽도 대칭)
        lo_port, hi_port = node.gains.get("out_lo"), node.gains.get("out_hi")
        cis = []
        if hi_port is None and (lo_port is None or all(
                _port_bound(graph, r, lo_port, "hi") <= r.instances[nid].out_hi for r in runners)):
            cis.append(1)
        if lo_port is None and (hi_port is None or all(
                _port_bound(graph, r, hi_port, "lo") >= r.instances[nid].out_lo for r in runners)):
            cis.append(3)
        if cis:
            out[d["id"]] = {"cis": tuple(cis), "reason": _COUPLED_REASON}
    return out


def _justify_branches(uncovered, decisions, coupled, files):
    """정당화된 가드 조건의 분기 미달을 정당화 목록으로 옮긴다 (열 좌표로 대조).

    같은 사실이 두 측정에 두 번 나타나는 것뿐이다 — llvm 분기의 '거짓측 미실행'과
    MC/DC의 '독립쌍 부재'는 동일한 구조적 종속의 두 그림자다.
    """
    just_cols = {}
    by_id = {d["id"]: d for d in decisions}
    for did, info in coupled.items():
        d = by_id[did]
        line_text = files[d["file"]].split("\n")[d["line"] - 1]
        for ci in info["cis"]:
            col = line_text.find(d["conditions"][ci])
            if col >= 0:
                just_cols.setdefault((d["file"], d["line"]), set()).add(col + 1)
    remaining, justified = [], []
    for u in uncovered:
        cols = just_cols.get((u["file"], u["line"]), set())
        if u.get("col") in cols and u["missing"] == "거짓측":
            justified.append({**u, "reason": _COUPLED_REASON})
        else:
            remaining.append(u)
    return remaining, justified


def _measure_coverage(cc, files, harnesses, runs, strict_out, runners, dirpath, tick):
    """커버리지 두 빌드 → 전 시험 재생 → 판독.

    빌드를 **둘로 가른다**: 라인·분기는 평문 소스의 llvm 계측 빌드에서, MC/DC는
    프로브를 심은 빌드에서 잰다 — 프로브(함수 호출)로 감싼 조건은 llvm이 분기
    항목에서 빼 버려 한 빌드로는 두 측정이 서로를 망가뜨린다(실측).
    runs는 [{tag, harness, stdin, args}] — 통합·유닛·로더 실행 전부를 파라미터 세트의 이미지마다 담는다(v1.12).
    프로파일·벡터는 그 합산이다. runners는 이미지마다의 러너 — 가드 정당화가 전 이미지에서 성립해야 한다.
    """
    skip = lambda why: ({"status": "skip", "reason": why},
                        {"status": "skip", "reason": why})
    profdata_tool = find_llvm_tool("llvm-profdata")
    cov_tool = find_llvm_tool("llvm-cov")
    if not (profdata_tool and cov_tool):
        return skip("llvm-profdata·llvm-cov 없음 — 구조적 커버리지를 잴 수 없다")
    cov_cc = shutil.which("clang") or cc

    def build_and_run(subdir, tree, flags, extra_srcs, want_prof, label):
        """하네스별 빌드·전 시험 실행 → (exe dict, 실행 결과 dict) 또는 (None, 사유)."""
        d = dirpath / subdir
        sources = _write_tree(d, tree, harnesses)
        exes = {}
        for hname in harnesses:
            exe, r = _compile(cov_cc, flags(d), [hname, *extra_srcs, *sources],
                              d, f"x_{hname[:-2]}")
            if r.returncode != 0:
                return None, f"{label} 빌드 실패 ({Path(cov_cc).name}): {r.stderr[:400]}"
            exes[hname[:-2]] = exe
        outs = {}
        for i, job in enumerate(runs):
            if job["harness"] not in exes:
                continue
            if tick(78 + 10.0 * i / max(len(runs), 1), f"{label} 실행 — {job['tag']}"):
                return None, "취소됨"
            env = ({"LLVM_PROFILE_FILE": str(d / f"{_safe(job['tag'])}.profraw")}
                   if want_prof else None)
            run = _run(exes[job["harness"]], job["stdin"], env=env, args=job["args"])
            if run.returncode != 0:
                return None, f"{label} 실행 실패 ({job['tag']}): {run.stderr[:400]}"
            outs[job["tag"]] = run.stdout
            # 계측 무해성 — 계측이 결과를 한 비트라도 바꾸면 그 측정은 다른
            # 프로그램의 것이다. 엄격 빌드 출력과 문자 단위로 같아야 한다
            if job["tag"] in strict_out and _data_rows(run.stdout) != strict_out[job["tag"]]:
                return None, f"{label} 무해성 자기검사 실패 — {job['tag']} 출력이 엄격 빌드와 다르다"
        return {"dir": d, "exes": exes, "outs": outs}, None

    # ── 빌드 A: 라인·분기 (llvm 소스 계측, 평문 소스) ──
    cov_run, why = build_and_run("llvm", files, lambda d: COVER_FLAGS, [],
                                 True, "커버리지")
    if cov_run is None:
        return skip(why)
    d = cov_run["dir"]
    prof = d / "merged.profdata"
    m = subprocess.run(
        [profdata_tool, "merge", "-sparse",
         *(str(d / f"{_safe(tag)}.profraw") for tag in cov_run["outs"]), "-o", str(prof)],
        capture_output=True, text=True, timeout=TOOL_TIMEOUT)
    if m.returncode != 0:
        return skip(f"프로파일 병합 실패: {m.stderr[:400]}")
    int_exe = cov_run["exes"]["verify_harness"]
    # 통합 하네스 바이너리로 판독한다 — 파티션·로더·런타임 코드가 모두 링크돼 있다
    e = subprocess.run([cov_tool, "export", "-format=text", str(int_exe),
                        f"-instr-profile={prof}"], capture_output=True, text=True,
                       timeout=TOOL_TIMEOUT)
    if e.returncode != 0:
        return skip(f"커버리지 판독 실패: {e.stderr[:400]}")
    try:
        data = json.loads(e.stdout)["data"][0]
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        return skip(f"커버리지 JSON 해석 실패: {exc}")
    per_file, totals, uncovered = _parse_export(data, files)
    line_counts = _line_counts(cov_tool, int_exe, prof, d,
                               [n for n in sorted(files) if n.endswith(".c")])
    for row in per_file:
        row["line_counts"] = line_counts.get(row["name"], [])

    # ── 빌드 B: MC/DC 프로브 (llvm 계측 없음 — 분기 데이터를 안 건드린다) ──
    decisions = mcdc_mod.find_decisions(files)
    coupled = _coupled_guards(decisions, runners)
    mcdc_report = {"status": "skip", "reason": "다조건 결정 없음"}
    if decisions:
        inst_files = mcdc_mod.instrument(files, decisions)
        mcdc_dir = dirpath / "mcdc"
        mcdc_dir.mkdir(parents=True, exist_ok=True)
        (mcdc_dir / "claw_mcdc.h").write_text(mcdc_mod.RUNTIME_H, encoding="utf-8")
        (mcdc_dir / "claw_mcdc.c").write_text(mcdc_mod.RUNTIME_C, encoding="utf-8")
        probe_flags = ["-std=c99", "-O0", "-ffp-contract=off"]
        mc_run, why = build_and_run(
            "mcdc", inst_files,
            lambda d2: [*probe_flags, "-include", str(d2 / "claw_mcdc.h")],
            ["claw_mcdc.c"], False, "MC/DC 계측")
        if mc_run is None:
            mcdc_report = {"status": "skip", "reason": why}
        else:
            dumps = [mcdc_mod.parse_dump(out) for out in mc_run["outs"].values()]
            judged = mcdc_mod.judge(decisions, mcdc_mod.merge_dumps(dumps),
                                    justified=coupled)
            mcdc_report = {
                "status": "measured", "harmless": True, **judged,
                "note": "다조건 결정만 쌍 분석 대상 — 단일 조건 결정의 MC/DC는 분기 "
                        "커버리지와 동치라(조건이 하나면 홀로 결과를 바꿈) llvm 분기 "
                        "데이터가 충족을 판정한다. 진리 벡터는 파라미터 세트의 이미지 전부에서 "
                        "합산한다. 정당화 조건은 측정 불가의 분석 대체이고 세트의 모든 이미지에서 "
                        "성립할 때만 인정한다(사유는 결정별 기록).",
            }

    uncovered, justified = _justify_branches(uncovered, decisions, coupled, files)
    coverage = {
        "status": "measured", "tool": Path(cov_tool).name,
        "totals": totals, "files": per_file,
        "uncovered_branches": uncovered,
        "justified": justified,
        "functions": _function_rows(files, line_counts, uncovered, mcdc_report),
        "note": f"통합(미션+보강) + 유닛 + 로더 실행 합산 프로파일 — 파라미터 세트 {len(runners)}개 이미지.",
    }
    return coverage, mcdc_report


def _safe(tag):
    """실행 표식 → 파일 이름 조각 (`@`·`-`를 가리지 않게)."""
    return re.sub(r"[^A-Za-z0-9_]", "_", tag)
