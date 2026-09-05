"""탑재 C 신뢰성 검증 — DAL A 정렬 파이프라인 (M12).

문서가 아니라 **실행**으로 검증한다. 사용자 8단 파이프라인이 이 모듈의 목차다:

  Python 제어법칙 → 검증된 IR(생성 전 원천 차단) → C 생성
    ① 규칙 검사(static_c)  ② 정적 결함(엄격 컴파일 + IR 차단)  ③ 복잡도/결합
    ④ 유닛 시험(units — 파티션 단위, 스텁 불요 구조)  ⑤ 하네스 자동 생성
    ⑥ 구조적 커버리지 — 라인·분기(llvm-cov) + MC/DC(자체 계측, mcdc)
    ⑦ SIL: 호스트 대조(미션 + 보강 벡터, 비트 일치) — PIL/타깃은 범위 밖 명시
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
import subprocess
import sys
import tempfile
from pathlib import Path

import claw
from claw.codegen import emit_c, emit_runtime
from claw.verify import mcdc as mcdc_mod
from claw.verify import vectors
from claw.verify.static_c import analyze as static_analyze
from claw.verify.static_c import functions_of
from claw.verify.trace import record_mission
from claw.verify.units import make_unit_harness, run_unit_oracle, unit_specs, unit_stdin

# test_parity.py CFLAGS와 같은 정신 — -Werror 대신 경고를 세어 근거로 남긴다.
# -ffp-contract=off는 장식이 아니다: FMA 축약은 중간 반올림을 없애 2.8e-16 어긋난다.
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
        r = subprocess.run(["xcrun", "-f", name], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def make_harness(graph) -> str:
    """통합(SIL) 하네스 — 입출력 목록을 그래프 선언에서 만든다.

    웜스타트 계약은 생성 코드와 같다(fcl.h 주석): 리셋 후 상태 필드 직접 대입.
    필드 이름은 데모 형상 조립 규약(law.py reset)에 매여 있고, 컴파일이 그 실존을
    검사한다 — 이름이 낡으면 조용히 틀리는 게 아니라 빌드가 깨진다.
    """
    base = graph.name
    n = len(graph.inputs)
    args = ", ".join(f"u[{i}]" for i in range(n))
    outs = list(graph.outputs)
    fmt = " ".join(["%.17g"] * len(outs))
    prints = ", ".join(f"out.{name}" for name in outs)
    return f"""/* CLAW 검증 하네스 — 표준입력 시퀀스를 생성 코드에 흘려 %.17g로 낸다 (왕복 무손실). */
#include <stdio.h>
#include "{base}.h"

int main(void)
{{
    {base}_state_t s;
    {base}_out_t out;
    double de0, th0, thr0;
    double u[{n}];
    int k;

    if (scanf("%lf %lf %lf", &de0, &th0, &thr0) != 3) {{ return 1; }}
    {base}_reset(&s);
    s.scas_pitch_pid_i = de0;   /* law.py reset — scas.pitch 적분기 = 트림 δe */
    s.ap_alt_pid_i = th0;       /* AP 고도 적분기 = 트림 θ */
    s.ap_spd_pid_i = thr0;      /* AP 속도 적분기 = 트림 스로틀 */
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
        {base}_step(&{base}_params, &s, &out, {args});
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
    r = subprocess.run(cmd, capture_output=True, text=True)
    return exe, r


def _run(exe, stdin, env=None):
    return subprocess.run([str(exe)], input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def _data_rows(stdout):
    """하네스 stdout에서 수치 행만 — MCDC 덤프 줄은 계측 빌드에만 있다."""
    return [ln for ln in stdout.splitlines() if not ln.startswith("MCDC ")]


def _stdin_for(rec):
    warm = " ".join(repr(v) for v in rec["warm"])
    rows = "\n".join(
        " ".join(repr(row[k]) for k in rec["input_order"]) for row in rec["inputs"]
    )
    return warm + "\n" + rows + "\n"


# ── ⑦ SIL 대조 (통합) ─────────────────────────────────────────────────────


def _compare_stream(c_rows, refs, order, dt, spans):
    """C 출력 행 ↔ 기준 출력 — 출력별 전 구간 대조 + 케이스 구간별 판정.

    허용오차 없음 — 배정밀도·동일 연산 순서라 목표는 비트 일치다.
    """
    outs = []
    for i, name in enumerate(order):
        first, max_err, equal = None, 0.0, 0
        for k, (row, ref) in enumerate(zip(c_rows, refs)):
            c, py = row[i], ref[name]
            if c == py:
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
                if c_rows[k][i] != refs[k][name]:
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
            capture_output=True, text=True)
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
                if row[i] != ref[name]:
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
    """유닛 그리드 행 — 파티션 5 + 통합/조립 + 공용 런타임."""
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
        "files": [f"{base}.c", f"{base}.h", f"{base}_types.h", f"{base}_data.c"],
        "harness": True, "cases": {
            "total": len(int_cases),
            "passed": sum(1 for c in int_cases if c["status"] == "pass"),
            "skipped": sum(1 for c in int_cases if c["status"] == "skip"),
        },
        **agg([f"{base}.c", f"{base}_data.c"]),
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
        r("A-5 #8", "죽은 코드·비활성 코드 없음", "auto",
          "IR이 도달 불가 노드를 생성 시점에 거부하고, ki/kd = 0 경로는 방출하지 "
          "않는다(도달 불가 분기 원천 제거) — 커버리지 실측이 이를 재확인"),
        r("DO-330", "도구 적격성 (TQL)", "out",
          "이 검증기 자체가 틀리지 않는다는 입증은 별개 사업 — 인증용 독립 검증은 "
          "적격성 키트를 갖춘 상용 도구(LDRA·VectorCAST류)의 자리"),
    ]


def _summary(report):
    """판정판 다섯 줄 — 화면이 다시 적지 않도록 문구까지 엔진이 낸다."""
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
        n_fail_case = sum(1 for c in cases if c["status"] == "fail")
        status = "pass" if (eq["status"] == "pass" and n_fail_case == 0) else "fail"
        n_unit = sum(1 for c in cases if c["unit"] != report["artifact"])
        detail = (f"통합 {report['steps']:,}스텝 + 유닛 케이스 {n_unit}개 — "
                  + ("전 스텝 비트 일치" if status == "pass"
                     else f"불일치 케이스 {n_fail_case}개"))
    rows.append({"key": "equiv", "label": "동등성 — Python↔C 비트 일치 (SIL)",
                 "status": status, "detail": detail})
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


def verify_flight(law, *, t_end=180.0, control_hz=100.0, on_progress=None,
                  keep_dir=None, with_vectors=True):
    """초기화된 법칙(`law.init(dt)` 완료) → 검증 리포트 dict. 취소되면 None.

    on_progress(done, total, message) — truthy 반환 = 협조적 취소 (Job.report 계약).
    with_vectors=False는 테스트용 — 보강·유닛 벡터 없이 미션만 (커버리지 미달이
    정직하게 fail로 나오는지를 이걸로 고정한다).
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

    # ── 생성 (① 앞) ──
    if tick(2, "탑재 C 생성"):
        return None
    module = emit_c(graph, runner)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))
    specs = unit_specs(graph) if with_vectors else []
    harnesses = {"verify_harness.c": make_harness(graph)}
    for spec in specs:
        harnesses[f"unit_{spec['group']}.c"] = make_unit_harness(graph.name, spec)

    # ── ①~③ 정적 ──
    if tick(4, "정적 규율 검사"):
        return None
    static = static_analyze(files)

    report = {
        "artifact": graph.name,
        "fingerprint": module.fingerprint,
        "engine": claw.__version__,
        "dt": law.dt,
        "t_end": t_end,
        "files": [{"name": n, "lines": files[n].count("\n"), "text": files[n]}
                  for n in sorted(files)],
        "static": static,
        "stubs": {"needed": 0, "note":
                  "스텁·목이 필요 없는 구조다 — 생성 법칙은 외부 의존 0(플랜트·"
                  "항법·작동기는 법칙 밖, 수학은 libm뿐)이고, 파티션의 상류는 "
                  "스텁이 아니라 임포트 값 그 자체다."},
    }

    cc = find_cc()
    report["toolchain"] = {
        "cc": cc,
        "llvm_cov": bool(find_llvm_tool("llvm-cov") and find_llvm_tool("llvm-profdata")),
    }

    with tempfile.TemporaryDirectory(prefix="claw-verify-") as tmp:
        root = Path(keep_dir) if keep_dir else Path(tmp)
        strict_dir = root / "strict"

        # ── ② 엄격 컴파일 (통합 + 유닛 하네스 전부) ──
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

        # ── ⑦ 대조 미션 + 통합 보강 벡터 ──
        if tick(10, "대조 미션 기록"):
            return None
        rec = record_mission(
            law, t_end=t_end, control_hz=control_hz,
            on_progress=(lambda d, t: tick(10 + 40.0 * d / max(t, 1), "대조 미션 기록"))
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
            if tick(52, "통합 보강 벡터 실행"):
                return None
            for case in vectors.integration_cases():
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

        # ── ⑦ SIL 대조 (통합) ──
        strict_out = {}
        case_rows = []
        int_exe = exes.get("verify_harness")
        if int_exe is None:
            reason = (report["compile"].get("reason")
                      or "엄격 컴파일 실패 — 실행 파일이 없다")
            report["equivalence"] = {"status": "skip", "reason": reason, "outputs": []}
            case_rows = [{**s, "unit": graph.name, "status": "skip",
                          "first_diff": None} for s in spans]
            for s in case_rows:
                s.pop("start", None)
        else:
            if tick(56, "Python↔C 대조 (통합)"):
                return None
            run = _run(int_exe, _stdin_for(rec))
            if run.returncode != 0:
                report["equivalence"] = {
                    "status": "fail", "outputs": [],
                    "note": f"하네스 실행 실패 (rc {run.returncode}): {run.stderr[:500]}"}
                case_rows = []
            else:
                strict_out["verify_harness"] = _data_rows(run.stdout)
                c_rows = [[float(x) for x in ln.split()]
                          for ln in strict_out["verify_harness"]]
                if len(c_rows) != len(rec["inputs"]):
                    report["equivalence"] = {
                        "status": "fail", "outputs": [],
                        "note": f"출력 {len(c_rows)}행 ≠ 입력 {len(rec['inputs'])}행"}
                else:
                    report["equivalence"], case_rows = _compare_stream(
                        c_rows, rec["outputs"], rec["output_order"], law.dt, spans)

        # ── ④ 유닛 시험 ──
        unit_stdins = {}
        for idx, spec in enumerate(specs):
            g = spec["group"]
            cases = vectors.unit_cases(g, spec["imports"])
            unit_stdins[g] = (cases, unit_stdin(spec, cases))
            if f"unit_{g}" not in exes:
                case_rows += [{"id": c["id"], "title": c["title"], "unit": g,
                               "steps": len(c["rows"]), "status": "skip",
                               "first_diff": None} for c in cases]
                continue
            if tick(58 + 3 * idx, f"유닛 시험 — {g}"):
                return None
            oracle = run_unit_oracle(
                spec, law.dt, [r for c in cases for r in c["rows"]])
            run = _run(exes[f"unit_{g}"], unit_stdins[g][1])
            if run.returncode != 0:
                case_rows += [{"id": c["id"], "title": c["title"], "unit": g,
                               "steps": len(c["rows"]), "status": "fail",
                               "first_diff": {"step": 0, "output": "(실행 실패)",
                                              "c": 0.0, "py": 0.0}}
                              for c in cases]
                continue
            strict_out[f"unit_{g}"] = _data_rows(run.stdout)
            c_rows = [[float(x) for x in ln.split()] for ln in strict_out[f"unit_{g}"]]
            case_rows += _unit_compare(spec, cases, oracle, c_rows)
        report["cases"] = case_rows

        # ── ⑥ 커버리지 + MC/DC ──
        report["coverage"] = {"status": "skip",
                              "reason": "C 컴파일러 없음 — 계측 빌드 불가"}
        report["mcdc"] = {"status": "skip", "reason": "커버리지 빌드 없음"}
        if cc is not None:
            if tick(76, "커버리지·MC/DC 계측 빌드"):
                return None
            report["coverage"], report["mcdc"] = _measure_coverage(
                cc, files, harnesses, specs, rec, unit_stdins, strict_out,
                runner, root / "cov", tick)

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


_COUPLED_REASON = (
    "구조적 종속 — 적분기 클램프 불변식(i ∈ [lo, hi])에서 raw > hi ⇒ kp·e > 0이고, "
    "ki·kp 동부호 상수라 inc > 0이 반드시 함께 참이다(하한 대칭). 감쇠항(u_ext)이 "
    "없는 축이라 함의를 깨는 항이 없어 독립쌍이 수학적으로 존재하지 않는다 — "
    "측정이 아니라 분석으로 정당화한다 (DO-178C 커버 대체)."
)


def _coupled_guards(decisions, runner):
    """독립쌍이 수학적으로 부재한 가드 조건 — {결정 id: {cis, reason}}.

    대상: u_ext(감쇠항) 없는 축의 PID 가드에서 c1·c3(`inc` 부호 조건).
    근거는 그래프·인스턴스에서 직접 판정한다 — 텍스트 추측이 아니라 조립 정본이
    말하게 한다. 게인·한계가 포트(신호)면 함의가 시변이라 대상에서 뺀다.
    """
    graph = runner.graph
    out = {}
    for d in decisions:
        if d["kind"] != "guard":
            continue
        atom = d["conditions"][0].split()[0]  # "<nid>_raw" 또는 "<nid>_axis"
        if not atom.endswith("_raw"):
            continue  # u_ext 있는 축 — axis = raw + u_ext라 함의가 깨진다
        nid = atom[: -len("_raw")]
        try:
            node = graph.node(nid)
        except KeyError:
            continue
        if {"ki", "kp", "out_lo", "out_hi"} & set(node.gains):
            continue
        inst = runner.instances.get(nid)
        if inst is None or inst.ki * inst.kp <= 0:
            continue
        out[d["id"]] = {"cis": (1, 3), "reason": _COUPLED_REASON}
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


def _measure_coverage(cc, files, harnesses, specs, rec, unit_stdins, strict_out,
                      runner, dirpath, tick):
    """커버리지 두 빌드 → 전 시험 재생 → 판독.

    빌드를 **둘로 가른다**: 라인·분기는 평문 소스의 llvm 계측 빌드에서, MC/DC는
    프로브를 심은 빌드에서 잰다 — 프로브(함수 호출)로 감싼 조건은 llvm이 분기
    항목에서 빼 버려 한 빌드로는 두 측정이 서로를 망가뜨린다(실측).
    프로파일·벡터는 통합 + 유닛 실행 전부의 합산이다.
    """
    skip = lambda why: ({"status": "skip", "reason": why},
                        {"status": "skip", "reason": why})
    profdata_tool = find_llvm_tool("llvm-profdata")
    cov_tool = find_llvm_tool("llvm-cov")
    if not (profdata_tool and cov_tool):
        return skip("llvm-profdata·llvm-cov 없음 — 구조적 커버리지를 잴 수 없다")
    cov_cc = shutil.which("clang") or cc

    runs = [("verify_harness", _stdin_for(rec))]
    runs += [(f"unit_{g}", unit_stdins[g][1]) for g in unit_stdins]

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
        for i, (name, stdin) in enumerate(runs):
            if name not in exes:
                continue
            if tick(78 + 10.0 * i / max(len(runs), 1), f"{label} 실행 — {name}"):
                return None, "취소됨"
            env = ({"LLVM_PROFILE_FILE": str(d / f"{name}.profraw")}
                   if want_prof else None)
            run = _run(exes[name], stdin, env=env)
            if run.returncode != 0:
                return None, f"{label} 실행 실패 ({name}): {run.stderr[:400]}"
            outs[name] = run.stdout
            # 계측 무해성 — 계측이 결과를 한 비트라도 바꾸면 그 측정은 다른
            # 프로그램의 것이다. 엄격 빌드 출력과 문자 단위로 같아야 한다
            if name in strict_out and _data_rows(run.stdout) != strict_out[name]:
                return None, f"{label} 무해성 자기검사 실패 — {name} 출력이 엄격 빌드와 다르다"
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
         *(str(d / f"{name}.profraw") for name, _ in runs
           if name in cov_run["outs"]), "-o", str(prof)],
        capture_output=True, text=True)
    if m.returncode != 0:
        return skip(f"프로파일 병합 실패: {m.stderr[:400]}")
    int_exe = cov_run["exes"]["verify_harness"]
    e = subprocess.run([cov_tool, "export", "-format=text", str(int_exe),
                        f"-instr-profile={prof}"], capture_output=True, text=True)
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
    coupled = _coupled_guards(decisions, runner)
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
                        "데이터가 충족을 판정한다. 정당화 조건은 측정 불가의 분석 "
                        "대체다(사유는 결정별 기록).",
            }

    uncovered, justified = _justify_branches(uncovered, decisions, coupled, files)
    coverage = {
        "status": "measured", "tool": Path(cov_tool).name,
        "totals": totals, "files": per_file,
        "uncovered_branches": uncovered,
        "justified": justified,
        "functions": _function_rows(files, line_counts, uncovered, mcdc_report),
        "note": "통합(미션+보강) + 유닛 실행 합산 프로파일.",
    }
    return coverage, mcdc_report
