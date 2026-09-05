"""M12 verify — DAL A 파이프라인 (정적 규율·MC/DC·유닛·벡터·오케스트레이터).

정확성의 정본 검증은 flight/tests/test_parity.py다(손으로 쓴 하네스). 여기서
지키는 것은 검증 **장치** 자체다:
  ① 정적 스캐너·MC/DC 판정기가 위반·미커버를 실제로 잡는가 (변이 주입)
  ② 하네스·계측 변환이 산출물 계약(입출력 순서·줄 보존)을 지키는가
  ③ 벡터가 결정적인가 (같은 형상 = 같은 벡터 — 회귀 비교의 전제)
  ④ 파이프라인이 환경에 정직한가 — 벡터를 빼면 커버리지 미달이 fail로 드러나는가
  ⑤ 협조적 취소가 결과를 내지 않는가
"""

import pytest

from claw.fcl.demo import make_demo_fcl
from claw.fcl.graphs import FCL_INPUTS
from claw.verify import mcdc, vectors
from claw.verify.autocode import (
    _coupled_guards, find_cc, make_harness, verify_flight, warm_start_lines,
)
from claw.verify.static_c import analyze, cyclomatic, functions_of, strip_comments_strings
from claw.verify.units import make_unit_harness, run_unit_oracle, unit_specs

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
    """기본 형상: 가드 5(alt·vs·spd·roll·pitch — hdg·yaw는 ki=0 폴딩) + 룩업 루프."""
    decs = mcdc.find_decisions(demo_files)
    kinds = sorted((d["file"], d["kind"]) for d in decs)
    assert kinds.count(("fcl_ap.c", "guard")) == 3
    assert kinds.count(("fcl_scas.c", "guard")) == 2
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
    assert "fcl_ap_step(&fcl_params, &s," in src
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
    rep = verify_flight(demo_law, t_end=6.0, with_vectors=False)
    assert rep is not None
    by = {r["key"]: r for r in rep["summary"]}
    assert by["paths"]["status"] == "fail"
    if find_cc() and rep["coverage"]["status"] == "measured":
        assert by["coverage"]["status"] == "fail"
        assert rep["coverage"]["uncovered_branches"], "미달인데 근거 목록이 비었다"
    assert rep["verdict"] == "fail"
    # 유닛 시험이 없으니 유닛 행 케이스도 없다 — 통합·공용 행만
    assert [u["unit"] for u in rep["units"]] == ["fcl", "claw_rt"]


def test_전체_파이프라인은_기본_형상에서_DAL_A_목표를_닫는다(demo_law):
    """짧은 미션이어도 보강·유닛 벡터가 커버리지를 100%(정당화 포함)로 닫는다."""
    rep = verify_flight(demo_law, t_end=6.0)
    assert rep is not None
    keys = [r["key"] for r in rep["summary"]]
    assert keys == ["static", "compile", "paths", "equiv", "coverage"]
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
        "sched", "ap", "lim", "scas", "mix", "fcl", "claw_rt"}
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


def test_한계가_0을_품을_때만_적분기를_접는다():
    """ki=0이어도 Python은 매 스텝 무조건 클램프한다 — 0 ∉ [lo,hi]면 적분기가
    한계로 끌려가 출력에 실리므로, 접으면 비트 동등성이 깨진다."""
    assert "pid_i" not in _emit(_pid_graph())                  # 0 ∈ [-1, 1] → 접는다
    assert "pid_i" in _emit(_pid_graph(out_lo=0.5, out_hi=1.0))  # 0 ∉ [0.5, 1]
    assert "pid_i" in _emit(_pid_graph(out_lo=-1.0, out_hi=-0.5))
    assert "pid_i" in _emit(_pid_graph(ki=0.1))                  # ki ≠ 0

    # 실제로 값이 달라지는지 — 접었다면 여기서 Python↔C가 갈렸을 자리다
    r = _pid_graph(out_lo=0.5, out_hi=1.0)
    r.reset()
    assert r.step(e=0.0) == pytest.approx(0.5)  # i가 lo로 끌려가 출력에 실린다


def test_한계가_포트면_접지_않는다():
    """시변 한계는 0을 품는지 정적으로 알 수 없다 — 모르면 접지 않는 쪽이다."""
    from claw.blocks.basic import Gain
    from claw.blocks.controllers import PID
    from claw.codegen import GraphRunner
    from claw.codegen.ir import Graph, Node

    g = Graph("g", inputs=("e", "hi"),
              nodes=[Node("lo", Gain, inputs=("hi",), params={"k": -1.0}),
                     Node("pid", PID, inputs=("e",),
                          params=dict(kp=1.0, ki=0.0, out_lo=-1.0, out_hi=1.0),
                          gains={"out_lo": "lo", "out_hi": "hi"})],
              outputs={"y": "pid"})
    assert "pid_i" in _emit(GraphRunner(g, DT))


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


def test_웜스타트는_접힌_축을_건너뛴다(demo_law):
    """ki=0으로 편집한 형상이 '빌드 실패'로 뜨면 안 된다 — 없는 필드에 대입하면
    컴파일이 깨진다. 판정이 정체성인 탭에서 그건 틀린 판정이다."""
    from claw.fcl.autopilot import Autopilot
    from claw.fcl.demo import make_demo_fcl

    lines = "\n".join(warm_start_lines(demo_law.runner))
    assert "s.ap_alt_pid_i = th0;" in lines  # 기본 형상은 ki ≠ 0이라 그대로 대입

    off = make_demo_fcl(autopilot=Autopilot(ki_alt=0.0)).init(DT)
    off_lines = "\n".join(warm_start_lines(off.runner))
    assert "s.ap_alt_pid_i" not in off_lines
    assert "폴딩" in off_lines  # 침묵이 아니라 사유가 남는다
    if find_cc():
        rep = verify_flight(off, t_end=4.0, with_vectors=False)
        assert rep["compile"]["status"] == "pass", rep["compile"]["log"][:400]


def test_인벤토리는_못_잡은_다조건을_시끄럽게_거부한다(demo_files):
    """놓친 결정은 분모에서도 빠져 MC/DC가 100%로 남는다 — 최악의 실패다."""
    from claw.verify import mcdc

    assert mcdc.find_decisions(demo_files)  # 실제 산출물은 전부 잡힌다
    sneaky = dict(demo_files)
    sneaky["x.c"] = "void f(void)\n{\n    if (a > 0.0 && b < 1.0 && c) { g(); }\n}\n"
    with pytest.raises(ValueError, match="못 잡은 다조건"):
        mcdc.find_decisions(sneaky)


def test_취소는_결과를_내지_않는다(demo_law):
    assert verify_flight(demo_law, t_end=6.0,
                         on_progress=lambda d, t, m="": True) is None
