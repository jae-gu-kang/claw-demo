"""M12 verify — DAL A 파이프라인 (정적 규율·MC/DC·유닛·벡터·오케스트레이터).

정확성의 정본 검증은 flight/tests/test_parity.py다(손으로 쓴 하네스). 여기서
지키는 것은 검증 **장치** 자체다:
  ① 정적 스캐너·MC/DC 판정기가 위반·미커버를 실제로 잡는가 (변이 주입)
  ② 하네스·계측 변환이 산출물 계약(입출력 순서·줄 보존)을 지키는가
  ③ 벡터가 결정적인가 (같은 형상 = 같은 벡터 — 회귀 비교의 전제)
  ④ 파이프라인이 환경에 정직한가 — 벡터를 빼면 커버리지 미달이 fail로 드러나는가
  ⑤ 협조적 취소가 결과를 내지 않는가
"""

import re
from pathlib import Path

import pytest

from claw.fcl.demo import make_demo_fcl
from claw.fcl.graphs import FCL_INPUTS
from claw.verify import mcdc, vectors
from claw.verify.autocode import (
    _coverage_law, _coupled_guards, deactivated_paths, find_cc, make_harness, verify_flight, warm_start_lines,
)
from claw.verify.static_c import (
    _RETURN_TYPES,
    analyze,
    cyclomatic,
    functions_of,
    strip_comments_strings,
)
from claw.verify.units import make_unit_harness, run_unit_oracle, unit_specs
from claw.profile import example_profile

DT = 0.01


# ── 정적 스캐너 — 검출력을 변이 주입으로 단정 ────────────────────────────


def test_주석과_문자열은_규칙_스캔에_안_보인다():
    src = '/* goto malloc */\nvoid f(void)\n{\n    return;  /* float */\n}\n'
    clean = strip_comments_strings(src)
    assert "goto" not in clean and "float" not in clean
    assert clean.count("\n") == src.count("\n")  # 줄 보존 — 위치 보고의 전제


def test_금지_구문을_실제로_잡는다():
    bad = "void f(void)\n{\n    double *p = malloc(8);\n    goto out;\nout:\n    free(p);\n}\n"
    rules = {r["key"]: r for r in analyze({"bad.c": bad})["rules"]}
    assert rules["banned"]["status"] == "fail"
    joined = " ".join(rules["banned"]["hits"])
    assert "malloc" in joined and "goto" in joined and "L3" in joined


def test_재귀를_간접_사이클까지_잡는다():
    src = ("void a(void);\nvoid b(void);\n"
           "void a(void)\n{\n    b();\n}\n"
           "void b(void)\n{\n    a();\n}\n")
    rules = {r["key"]: r for r in analyze({"r.c": src})["rules"]}
    assert rules["recursion"]["status"] == "fail"
    assert "a → b → a" in " ".join(rules["recursion"]["hits"])


def test_가변_전역을_잡고_const는_통과시킨다():
    ok = "const double k = 1.0;\nvoid f(void)\n{\n    (void)k;\n}\n"
    bad = "double state = 0.0;\nvoid f(void)\n{\n    state = 1.0;\n}\n"
    assert {r["key"]: r["status"] for r in analyze({"ok.c": ok})["rules"]}["globals"] == "pass"
    rules = {r["key"]: r for r in analyze({"bad.c": bad})["rules"]}
    assert rules["globals"]["status"] == "fail" and "state" in rules["globals"]["hits"][0]


def test_복잡도는_판정_지점을_센다():
    body = "{ if (a && b) { x = c ? 1 : 2; } while (d) { } }"
    assert cyclomatic(body) == 5  # 1 + if + && + ? + while


def test_함수_추출은_프로토타입을_세지_않는다():
    src = "double f(double x);\ndouble f(double x)\n{\n    return x;\n}\n"
    fns = functions_of(src)
    assert [f["name"] for f in fns] == ["f"] and fns[0]["line"] == 2


def test_생성_산출물의_함수를_하나도_빠뜨리지_않는다():
    """반환형이 `_RETURN_TYPES`에 없으면 그 함수는 **인벤토리에서 조용히 사라진다**.

    사라지면 복잡도·재귀 콜그래프·커버리지 함수 행이 그 함수를 통째로 빼먹은 채
    검증 리포트가 통과한다 — 검사기가 조용히 틀리는 자리다. 그래서 방출된 정의 수와
    추출된 수를 맞대 둔다. Phase 3에서 `bool`이 붙으면 이 테스트가 먼저 죽는다.
    """
    gen = Path(__file__).resolve().parents[3] / "flight" / "gen"
    seen = 0
    for path in sorted(gen.glob("*.c")):
        src = path.read_text(encoding="utf-8")
        names = {f["name"] for f in functions_of(src)}
        # 정의부는 `타입 이름(` 로 시작하고 그 줄이 `;`로 끝나지 않는다 (프로토타입 제외)
        defined = {
            m.group(1)
            for m in re.finditer(r"(?m)^[A-Za-z_][\w ]*?\b(\w+)\s*\([^;]*$",
                                 strip_comments_strings(src))
        }
        assert names == defined, f"{path.name}: 추출 {sorted(names)} ≠ 정의 {sorted(defined)}"
        seen += len(names)
    assert seen >= 12, f"생성 산출물에서 함수를 {seen}개만 찾았다 — 너무 적다"

    # 산출물에 int 반환 함수가 없어서 위 대조만으로는 "int" 항목이 못박히지 않는다.
    # 세 형 중 둘만 지키면 나머지 하나가 조용히 빠져도 초록이다.
    for ctype in ("double", "void", "int", "uint32_t", "uint64_t"):
        assert ctype in _RETURN_TYPES, f"{ctype} 반환형이 인식 목록에서 빠졌다"
    assert functions_of("int f(void)\n{\n    return 0;\n}\n")[0]["name"] == "f"


# ── 공용 픽스처 ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def demo_law():
    return make_demo_fcl().init(DT)


@pytest.fixture(scope="module")
def demo_files(demo_law):
    from claw.codegen import emit_c, emit_runtime

    module = emit_c(demo_law.runner.graph, demo_law.runner)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))
    return files


def test_실제_생성물은_전_규칙_통과(demo_files):
    static = analyze(demo_files)
    assert all(r["status"] == "pass" for r in static["rules"]), static["rules"]
    assert static["totals"]["functions"] > 0


# ── MC/DC — 인벤토리·변환·판정 ────────────────────────────────────────────


def test_다조건_결정_인벤토리(demo_files):
    """기본 형상: 가드 7(alt·vs·spd·hdg·roll·pitch·yaw — v1.12부터 ki = 0이어도 적분기를 낸다) + 룩업 루프."""
    decs = mcdc.find_decisions(demo_files)
    kinds = sorted((d["file"], d["kind"]) for d in decs)
    assert kinds.count(("fcl_ap.c", "guard")) == 4
    assert kinds.count(("fcl_scas.c", "guard")) == 3
    assert ("claw_rt.c", "and2") in kinds
    assert [d["id"] for d in decs] == list(range(len(decs)))  # id = 결정적 첨자


def test_계측_변환은_줄을_보존하고_전_조건을_감싼다(demo_files):
    decs = mcdc.find_decisions(demo_files)
    inst = mcdc.instrument(demo_files, decs)
    for name in demo_files:
        assert inst[name].count("\n") == demo_files[name].count("\n"), name
    n_wrapped = sum(inst[n].count("CLAW_MCDC(") for n in inst)
    assert n_wrapped == sum(len(d["conditions"]) for d in decs)
    # 변환 대상 줄이 어긋나면 조용히 넘어가지 않는다
    broken = dict(demo_files)
    d0 = decs[-1]
    lines = broken[d0["file"]].split("\n")
    lines[d0["line"] - 1] = "    /* 다른 코드 */"
    broken[d0["file"]] = "\n".join(lines)
    with pytest.raises(ValueError):
        mcdc.instrument(broken, decs)


def _vec(kind, *cvals):
    """조건값 튜플(None=미평가) → 벡터 바이트."""
    mask = 0
    for ci, v in enumerate(cvals):
        if v is None:
            continue
        mask |= (1 if v else 0) << ci
        mask |= 1 << (ci + 4)
    return mask


def test_masking_판정_and2():
    dec = [{"id": 0, "file": "f.c", "line": 1, "kind": "and2",
            "conditions": ["a", "b"], "label": "x"}]
    # (F,–)→F, (T,T)→T, (T,F)→F : c0 쌍 = 1·2, c1 쌍 = 2·3 — 둘 다 커버
    seen = {0: {_vec("and2", False, None), _vec("and2", True, True),
                _vec("and2", True, False)}}
    j = mcdc.judge(dec, seen)
    assert j["covered"] == 2 and j["total"] == 2
    # (T,T)와 (F,–)만으로는 c1 독립쌍이 없다 — c1 미커버가 잡혀야 한다
    j2 = mcdc.judge(dec, {0: {_vec("and2", False, None), _vec("and2", True, True)}})
    assert j2["covered"] == 1
    assert j2["decisions"][0]["uncovered"][0]["ci"] == 1


def test_masking_판정_guard와_정당화():
    dec = [{"id": 0, "file": "f.c", "line": 1, "kind": "guard",
            "conditions": ["a", "b", "c", "d"], "label": "x"}]
    seen = {0: {
        _vec("g", True, True, None, None),    # (a&&b) 참 → T
        _vec("g", True, False, False, None),  # b 거짓, c 거짓 → F  (b 쌍)
        _vec("g", False, None, False, None),  # a 거짓, c 거짓 → F
        _vec("g", False, None, True, True),   # c&&d 참 → T        (c·d 재료)
        _vec("g", False, None, True, False),  # d 거짓 → F         (d 쌍)
    }}
    j = mcdc.judge(dec, seen)
    assert j["covered"] == 4 and j["total"] == 4
    # 벡터가 모자라면 미커버 — 정당화를 주면 그 조건만 분석 대체로 채워진다
    part = {0: {_vec("g", True, True, None, None), _vec("g", False, None, False, None)}}
    j2 = mcdc.judge(dec, part)
    assert j2["covered"] < 4 and j2["justified"] == 0
    j3 = mcdc.judge(dec, part, justified={0: {"cis": (1, 3), "reason": "구조적 종속"}})
    assert j3["justified"] == 2
    marked = [u for u in j3["decisions"][0]["uncovered"] if u["justified"]]
    assert {u["ci"] for u in marked} == {1, 3}


def test_dump_왕복():
    text = "1 2 3\nMCDC 0 11 21\n4 5 6\nMCDC 3 ff\n"
    seen = mcdc.parse_dump(text)
    assert seen == {0: {0x11, 0x21}, 3: {0xFF}}
    merged = mcdc.merge_dumps([seen, {0: {0x31}}])
    assert merged[0] == {0x11, 0x21, 0x31}


# ── 유닛·벡터 ─────────────────────────────────────────────────────────────


def test_유닛_명세는_파티션_다섯(demo_law):
    specs = unit_specs(demo_law.runner.graph)
    assert [s["group"] for s in specs] == ["sched", "ap", "lim", "scas", "mix"]
    for s in specs:
        assert s["imports"] and s["exports"]


def test_유닛_하네스가_인터페이스를_따른다(demo_law):
    spec = unit_specs(demo_law.runner.graph)[1]  # ap
    src = make_unit_harness("fcl", spec)
    assert f"double u[{len(spec['imports'])}]" in src
    assert "fcl_ap_step(&prm, &s," in src
    assert "fcl_params_load(img, len, pool, npool, &prm)" in src  # 파라미터는 argv[1] 이미지에서 (v1.12)
    assert src.count("&y[") == len(spec["exports"])


def test_유닛_오라클은_모자란_입력에_시끄럽다(demo_law):
    spec = unit_specs(demo_law.runner.graph)[0]  # sched — imports: mach
    rows = [{u: 0.4 for u in spec["imports"]}]
    outs = run_unit_oracle(spec, DT, rows)
    assert set(outs[0]) == set(spec["exports"])
    with pytest.raises(KeyError):
        run_unit_oracle(spec, DT, [{}])


def test_벡터는_결정적이고_키가_완전하다(demo_law):
    a, b = vectors.integration_cases(), vectors.integration_cases()
    assert [(c["id"], c["rows"]) for c in a] == [(c["id"], c["rows"]) for c in b]
    for c in a:
        for row in c["rows"]:
            assert set(row) == set(FCL_INPUTS), c["id"]
    spec = unit_specs(demo_law.runner.graph)[1]
    u1 = vectors.unit_cases("ap", spec["imports"])
    u2 = vectors.unit_cases("ap", spec["imports"])
    assert [(c["id"], c["rows"]) for c in u1] == [(c["id"], c["rows"]) for c in u2]
    assert all(set(r) == set(spec["imports"]) for c in u1 for r in c["rows"])


# ── 파이프라인 ────────────────────────────────────────────────────────────


def test_벡터를_빼면_커버리지_미달이_정직하게_드러난다(demo_law):
    """짧은 미션 + 벡터 없음 → DAL A 커버리지 목표는 fail이어야 한다.

    이것이 이 탭의 존재 이유다 — 시험이 모자라면 초록이 아니라 빨강이 선다.
    """
    rep = verify_flight(demo_law, profile=example_profile(), t_end=6.0, with_vectors=False)
    assert rep is not None
    by = {r["key"]: r for r in rep["summary"]}
    assert by["paths"]["status"] == "fail"
    if find_cc() and rep["coverage"]["status"] == "measured":
        assert by["coverage"]["status"] == "fail"
        assert rep["coverage"]["uncovered_branches"], "미달인데 근거 목록이 비었다"
    assert rep["verdict"] == "fail"
    # 유닛 시험이 없으니 유닛 행 케이스도 없다 — 통합·공용 행만
    assert [u["unit"] for u in rep["units"]] == ["fcl", "params", "claw_rt"]
    assert [s["id"] for s in rep["param_sets"]] == ["request"], "벡터를 뺐는데 커버리지 세트가 붙었다"


def test_전체_파이프라인은_기본_형상에서_DAL_A_목표를_닫는다(demo_law):
    """짧은 미션이어도 보강·유닛 벡터가 커버리지를 100%(정당화 포함)로 닫는다."""
    rep = verify_flight(demo_law, profile=example_profile(), t_end=6.0)
    assert rep is not None
    keys = [r["key"] for r in rep["summary"]]
    assert keys == ["static", "compile", "paths", "equiv", "params", "coverage"]
    by = {r["key"]: r for r in rep["summary"]}
    assert by["static"]["status"] == "pass"
    assert by["paths"]["status"] == "pass", by["paths"]  # 벡터가 모드·홀드를 채운다
    if not find_cc():
        assert by["compile"]["status"] == "skip"
        assert by["equiv"]["status"] == "skip"
        assert rep["coverage"]["status"] == "skip" and rep["coverage"]["reason"]
        return
    assert by["compile"]["status"] == "pass", rep["compile"]
    assert by["equiv"]["status"] == "pass", rep["equivalence"]
    assert all(c["status"] == "pass" for c in rep["cases"])
    assert {u["unit"] for u in rep["units"]} == {
        "sched", "ap", "lim", "scas", "mix", "fcl", "params", "claw_rt"}
    # 파라미터 세트 — 요청 이미지 + 값으로 꺼진 경로(헤딩·요 적분기 ki = 0, 단발 차동추력)를 켠 커버리지 이미지
    assert [s["id"] for s in rep["param_sets"]] == ["request", "cover-1"], rep.get("param_sets_note")
    assert {c["param_set"] for c in rep["cases"]} == {"request", "cover-1"}
    off = {d["node"]: d for d in rep["deactivated"]}
    assert off["ap_hdg_pid"]["kind"] == "integrator" and off["ap_hdg_pid"]["covered_by"] == ["cover-1"]
    assert off["scas_yaw_pid"]["covered_by"] == ["cover-1"]
    assert by["params"]["status"] == "pass", by["params"]
    assert all(c["status"] == "pass" for c in rep["cases"] if c["unit"] == "params")
    if rep["coverage"]["status"] == "measured":
        assert by["coverage"]["status"] == "pass", by["coverage"]
        mc = rep["mcdc"]
        assert mc["status"] == "measured"
        assert mc["covered"] + mc["justified"] == mc["total"]
        # 정당화는 근거 문구를 갖고, 측정 커버를 대체하지 장식하지 않는다
        for d in mc["decisions"]:
            for u in d["uncovered"]:
                assert u["justified"] and "구조적 종속" in u["reason"], u
    assert rep["verdict"] in ("pass", "pass_with_skips")
    # DO-178C 대응표 — 범위 밖 항목이 명시돼 있어야 한다 (조용한 누락 금지)
    dal = {r["ref"]: r["status"] for r in rep["dal"]}
    assert dal["DO-330"] == "out" and dal["A-7 obj."] == "out"
    assert dal["PDI"] == "partial"


# ── 리뷰 대응 — 폴딩 조건·정당화 조건·하네스·인벤토리 (거짓 통과 방지) ──


def _pid_graph(**kw):
    """PID 하나짜리 그래프 — 폴딩 판정을 형상별로 흔들어 보는 최소 단위."""
    from claw.blocks.controllers import PID
    from claw.codegen import GraphRunner
    from claw.codegen.ir import Graph, Node

    params = dict(kp=1.0, ki=0.0, out_lo=-1.0, out_hi=1.0)
    params.update(kw)
    g = Graph("g", inputs=("e",),
              nodes=[Node("pid", PID, inputs=("e",), params=params)],
              outputs={"y": "pid"})
    return GraphRunner(g, DT)


def _emit(runner):
    from claw.codegen import emit_c

    return emit_c(runner.graph, runner).files["g.c"]


def test_적분기는_ki와_한계에_무관하게_나온다():
    """v1.11까지는 ki = 0이고 한계가 0을 품으면 적분기를 접었다 — 값이 구조를 바꾸던 자리다. 이제 늘 낸다(v1.12)."""
    base = _emit(_pid_graph())
    for kw in ({"out_lo": 0.5, "out_hi": 1.0}, {"out_lo": -1.0, "out_hi": -0.5}, {"ki": 0.1}):
        assert _emit(_pid_graph(**kw)) == base, kw
    assert "pid_i" in base and "pid_inc > 0.0" in base

    # 0 ∉ [lo, hi]면 Python은 적분기를 한계로 끌어 출력에 싣는다 — C도 같은 적분기를 가지므로 대조가 그대로 선다
    r = _pid_graph(out_lo=0.5, out_hi=1.0)
    r.reset()
    assert r.step(e=0.0) == pytest.approx(0.5)


def test_정당화는_kd가_있으면_적용되지_않는다(demo_law):
    """kd ≠ 0이면 미분항이 raw를 밀어 e < 0에서도 hi를 넘는다 — 독립쌍이 실제로
    존재하므로 '수학적 부재' 정당화는 거짓이 된다 (MC/DC 거짓 100% 방지)."""
    from claw.verify.mcdc import find_decisions
    from claw.codegen import emit_c, emit_runtime

    def guards(runner):
        module = emit_c(runner.graph, runner)
        files = dict(module.files)
        files.update(emit_runtime(module.helpers))
        return _coupled_guards(find_decisions(files), runner)

    base = _pid_graph(ki=0.5)          # u_ext 없음·kd 0·ki·kp 동부호 → 정당화 대상
    assert guards(base), "정당화 대상이어야 할 형상이 안 잡혔다"
    assert guards(_pid_graph(ki=0.5, kd=0.2)) == {}, "kd가 있는데 정당화됐다"
    assert guards(_pid_graph(ki=-0.5)) == {}, "ki·kp 이부호인데 정당화됐다"


def test_정당화는_한계가_상수인_쪽만_인정한다():
    """상한이 신호(θ_hi(M) — v1.11)면 스텝 사이에 상한이 내려갈 때 적분기가 새 상한 위에 남아 오차 ≤ 0에서도 raw > hi가
    된다 — 상한 쪽 조건(c1)의 독립쌍이 실재하므로 정당화하면 거짓 100%다. 상수인 하한 쪽(c3)은 함의가 여전히 선다."""
    from claw.blocks.controllers import PID
    from claw.codegen import GraphRunner, emit_c, emit_runtime
    from claw.codegen.ir import Graph, Node
    from claw.verify.mcdc import find_decisions

    def guards(runner):
        module = emit_c(runner.graph, runner)
        files = dict(module.files)
        files.update(emit_runtime(module.helpers))
        return _coupled_guards(find_decisions(files), runner)

    params = dict(kp=1.0, ki=0.5, out_lo=-1.0, out_hi=1.0)
    both = guards(_pid_graph(ki=0.5))
    assert [v["cis"] for v in both.values()] == [(1, 3)]
    g = Graph("g", inputs=("e", "hi"),
              nodes=[Node("pid", PID, inputs=("e",), params=params, gains={"out_hi": "hi"})],
              outputs={"y": "pid"})
    # 신호 상한이 그래프에서 **상수 하한 이상으로 묶여 있지 않으면**(여기선 입력 그대로) 하한 쪽도 정당화하지 않는다 —
    # hi < lo가 되는 스텝에 적분기 클램프가 hi로 가 i < lo가 되고, 그러면 raw < lo가 kp·e < 0을 함의하지 않는다
    assert guards(GraphRunner(g, DT)) == {}
    from claw.blocks.basic import Saturation

    def bounded(lo_floor):
        return Graph("g", inputs=("e", "hi"),
                     nodes=[Node("hi_sat", Saturation, inputs=("hi",), params={"lo": lo_floor, "hi": 1.0}),
                            Node("pid", PID, inputs=("e",), params=params, gains={"out_hi": "hi_sat"})],
                     outputs={"y": "pid"})
    hi_port = guards(GraphRunner(bounded(-1.0), DT))  # fcl의 ap_theta_hi 모양 — 상수 하한 theta_lo로 묶인 포화 출력
    assert [v["cis"] for v in hi_port.values()] == [(3,)], hi_port
    assert guards(GraphRunner(bounded(-2.0), DT)) == {}  # 묶는 하한이 PID 하한보다 낮다 — 넘을 수 있다
    g2 = Graph("g", inputs=("e", "lo"),
               nodes=[Node("lo_sat", Saturation, inputs=("lo",), params={"lo": -1.0, "hi": 1.0}),
                      Node("pid", PID, inputs=("e",), params=params, gains={"out_lo": "lo_sat"})],
               outputs={"y": "pid"})
    assert [v["cis"] for v in guards(GraphRunner(g2, DT)).values()] == [(1,)]


def test_θ_상한_하강_벡터는_게인에서_길이를_정한다():
    """이름 기반 값 정책만으로는 승강률 적분기를 새 상한 위에 올릴 수 없다(큰 오차는 조건부 적분이 적분기를 멈춘다) —
    kp·e를 단계적으로 줄이는 시간이 kp/ki에 비례하므로 게인을 받아 길이를 정한다. 게인을 모르면 케이스를 붙이지 않는다."""
    base = vectors.integration_cases()
    assert all(c["id"] != "TC-INT-THETA-HI-DROP" for c in base)
    slow = vectors.integration_cases({"kp_vs": 0.08, "ki_vs": 0.02}, 0.01, theta_hi=True)
    fast = vectors.integration_cases({"kp_vs": 0.08, "ki_vs": 0.04}, 0.01, theta_hi=True)
    drop = {c["id"]: c for c in slow}["TC-INT-THETA-HI-DROP"]
    assert len(drop["rows"]) > len({c["id"]: c for c in fast}["TC-INT-THETA-HI-DROP"]["rows"])
    last = drop["rows"][-1]
    assert last["mach"] == 0.9 and last["hdot_on"] == 1.0 and 0.08 * (last["cmd_hdot"] - last["hdot"]) < 0.0
    # 적분 없음(가드가 없다)·표 없음(상한이 상수라 정당화된다)·길이 상한 초과(ki_vs를 아주 작게 편집)는 붙이지 않는다
    assert vectors.integration_cases({"kp_vs": 0.08, "ki_vs": 0.0}, 0.01, theta_hi=True) == base
    assert vectors.integration_cases({"kp_vs": 0.08, "ki_vs": 0.02}, 0.01) == base
    assert vectors.integration_cases({"kp_vs": 0.196, "ki_vs": 0.001}, 0.01, theta_hi=True) == base


def test_θ_상한_하강_벡터가_실제로_가드_상한_조건_거짓측을_만든다():
    """길이·마지막 행만 보면 램프를 (0.3, 0.3, 0.3)으로 망가뜨려도 통과한다(적분기가 hi − 0.3에서 멈춰 쌍이 안 생긴다) —
    법칙 러너에 벡터를 흘려 승강률 PID가 raw > hi인데 증분 ≤ 0인 스텝을 실제로 밟는지 본다."""
    from claw.fcl.demo import make_demo_fcl

    law = make_demo_fcl().init(DT)
    runner = law.runner
    cases = vectors.integration_cases(law.autopilot.cfg, DT, theta_hi=law.theta_hi_table is not None)
    drop = {c["id"]: c for c in cases}["TC-INT-THETA-HI-DROP"]
    pid = runner.instances["ap_vs_pid"]
    hits = 0
    for row in drop["rows"]:
        i_prev = pid._i
        runner.step_all(**row)
        env = runner.last_env
        e = env["ap_vs_err"]
        if pid.kp * e + i_prev > env["ap_theta_hi"] and DT * pid.ki * e <= 0.0:
            hits += 1
    assert hits >= 1, "θ 상한 하강 벡터가 가드 상한 조건의 (c0 참, c1 거짓) 스텝을 한 번도 못 만들었다"


def test_웜스타트는_형상에_있는_축에_늘_대입한다(demo_law):
    """ki = 0으로 편집해도 적분기 필드가 있다(v1.12) — 웜스타트 대입이 빠지거나 컴파일이 깨지지 않는다."""
    from claw.fcl.autopilot import Autopilot
    from claw.fcl.demo import make_demo_fcl

    lines = "\n".join(warm_start_lines(demo_law.runner))
    assert "s.ap_alt_pid_i = th0;" in lines
    off = make_demo_fcl(autopilot=Autopilot(ki_spd=0.0)).init(DT)
    assert "s.ap_spd_pid_i = thr0;" in "\n".join(warm_start_lines(off.runner))
    if find_cc():
        rep = verify_flight(off, profile=example_profile(), t_end=4.0, with_vectors=False)
        assert rep["compile"]["status"] == "pass", rep["compile"]["log"][:400]


def test_정당화는_파라미터_세트의_모든_이미지에서_성립해야_한다():
    """값에 기대는 분석 대체다 — 한 이미지라도 ki = 0이면 그 이미지에서 독립쌍이 실재하므로 정당화하지 않는다(v1.12)."""
    from claw.codegen import emit_c, emit_runtime
    from claw.verify.mcdc import find_decisions

    on, off = _pid_graph(ki=0.5), _pid_graph(ki=0.0)
    module = emit_c(on.graph, on)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))
    decs = find_decisions(files)
    assert [v["cis"] for v in _coupled_guards(decs, [on]).values()] == [(1, 3)]
    assert _coupled_guards(decs, [on, off]) == {}


def test_스케줄_포트_게인도_표_부호가_한결같으면_정당화한다():
    """표준 템플릿은 모든 게인 자리가 룩업 포트다(1점 표 포함) — 표의 전 값이 한 부호면 kp·ki 곱의 부호가 스텝과 무관하게
    정해져 함의가 선다. 속도축(감쇠항 없음·상수 한계)이 그 자리다."""
    from claw.codegen import emit_c, emit_runtime
    from claw.verify.mcdc import find_decisions

    law = make_demo_fcl(standard=True).init(DT)
    module = emit_c(law.runner.graph, law.runner)
    files = dict(module.files)
    files.update(emit_runtime(module.helpers))
    decs = find_decisions(files)
    got = _coupled_guards(decs, [law.runner])
    labels = {d["label"]: got.get(d["id"], {}).get("cis") for d in decs if d["kind"] == "guard"}
    assert labels["ap_spd_pid_raw"] == (1, 3), labels
    assert labels["ap_hdg_pid_raw"] is None  # ki = 0 — 곱이 0이라 함의가 없다(측정으로 덮는다)


def test_비활성_경로와_커버리지_세트(demo_law):
    """값으로 꺼진 경로를 목록화하고, 커버리지 세트가 구조를 바꾸지 않은 채 그 경로를 켠다(v1.12)."""
    from claw.codegen import emit_c

    std = make_demo_fcl(standard=True).init(DT)
    off = {d["node"]: d["kind"] for d in deactivated_paths(std.runner)}
    assert off["ap_hdg_pid"] == "integrator" and off["scas_yaw_pid"] == "integrator"
    assert off["scas_pitch_wo"] == "washout_bypass" and off["mix_diff"] == "zero_gain"
    assert off["sched_yaw_kp"] == "point_table"
    assert off.get("ap_ff_t") == "zero_gain"  # 선회 스로틀 FF 계수 0

    module = emit_c(std.runner.graph, std.runner)
    cov, changes, why = _coverage_law(std, module)
    assert cov is not None, why
    assert emit_c(cov.runner.graph, cov.runner).structure_fingerprint == module.structure_fingerprint
    slots = {c["slot"] for c in changes}
    assert {"heading.ki", "yaw.ki", "k_diff_thr", "pitch.washout_tau", "k_thr_turn"} <= slots, slots
    # 워시아웃은 선택이라 양쪽 분기가 필요하다 — 켜진 요축은 끈다
    assert {c["slot"]: c["value"] for c in changes}["yaw.washout_tau"] == 0.0
    still = {d["node"] for d in deactivated_paths(cov.runner)} - {n for n, k in off.items() if k == "point_table"}
    assert not still & {"ap_hdg_pid", "scas_yaw_pid", "scas_pitch_wo", "mix_diff", "ap_ff_t"}, still

    # 분석 그래프는 적분 게인·차동추력만 켠다 — k_rate·워시아웃·FF를 0에서 떼면 노드가 생겨 구조가 바뀐다
    module_a = emit_c(demo_law.runner.graph, demo_law.runner)
    cov_a, changes_a, why_a = _coverage_law(demo_law, module_a)
    assert cov_a is not None, why_a
    assert {c["slot"] for c in changes_a} <= {"heading.ki", "yaw.ki", "speed.ki", "alt.ki", "pitch.ki", "roll.ki",
                                              "ki_vs", "k_diff_thr", "alloc.de_trim"}
    assert "alloc.de_trim" in {c["slot"] for c in changes_a}  # 분석 그래프엔 1점 표가 없다 — 헬퍼 n < 2 분기를 켠다
    assert "alloc.de_trim" not in slots  # 표준 템플릿은 빈 스케줄 자리가 이미 1점 표다


def test_인벤토리는_못_잡은_다조건을_시끄럽게_거부한다(demo_files):
    """놓친 결정은 분모에서도 빠져 MC/DC가 100%로 남는다 — 최악의 실패다."""
    from claw.verify import mcdc

    assert mcdc.find_decisions(demo_files)  # 실제 산출물은 전부 잡힌다
    sneaky = dict(demo_files)
    sneaky["x.c"] = "void f(void)\n{\n    if (a > 0.0 && b < 1.0 && c) { g(); }\n}\n"
    with pytest.raises(ValueError, match="못 잡은 다조건"):
        mcdc.find_decisions(sneaky)


def test_취소는_결과를_내지_않는다(demo_law):
    assert verify_flight(demo_law, profile=example_profile(), t_end=6.0,
                         on_progress=lambda d, t, m="": True) is None
