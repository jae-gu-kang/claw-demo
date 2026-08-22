"""IR의 C 백엔드 — FCC에 통합되어 그대로 실릴 제어법칙 코드를 생성한다 (02 §1·§2.2).

파일 구성은 MATLAB Embedded Coder를 따른다: 알고리즘(`.c`) / 파라미터 데이터
(`_data.c`, rtP 대응) / 상태 구조체(`_types.h`, rtDW 대응) / 진입점(`.h`).

**생성 코드는 사람이 읽는다** — FCC팀이 읽고 신뢰성 시험을 돌리고 일부 수정한다.
그래서 블록 id와 신호 이름을 그대로 살린다(`rtb_Sum_p_idx_1` 류를 만들지 않는다).
구조가 고정(02 §4)이라 자유 배선을 다루는 MATLAB보다 이 점이 유리하다.

**이산 계수는 여기서 계산하지 않는다.** `GraphRunner`가 `init(dt)`를 태운 블록
인스턴스에서 이미 계산된 값(예: `Washout._p = exp(-dt/tau)`)을 그대로 읽어 굽는다 —
이산화 공식이 Python과 C에 두 번 적히면 그 순간 어긋난다. 사설 속성(`_p`)을 읽는
것은 그 때문이며, 대신 dt는 런타임 파라미터가 아니라 `#define`으로 낸다:
계수가 그 dt로 구워졌으므로 dt만 바꾸면 조용히 틀린다.

생성은 **결정적**이다 — 같은 입력이면 바이트 단위로 같은 출력(생성 시각을 넣지
않는다). 산출물을 커밋해 두고 "재생성했더니 달라졌다"가 곧 실제 변경임을
보장하기 위해서다.

한계: 소스가 같아도 개발 머신 컴파일러 ≠ 타깃 컴파일러, 최적화 옵션, 부동소수 폭
차이는 남는다. 타깃에서의 확인(PIL 성격)은 여전히 필요하다.
"""

import math
import re

import claw
from claw.blocks.basic import Gain, Product, Saturation, Sum
from claw.blocks.controllers import PID
from claw.blocks.filters import Washout
from claw.params.paramset import canonical_hash

_EMITTERS = {}


def _emitter(cls):
    def deco(fn):
        _EMITTERS[cls] = fn
        return fn

    return deco


def _cnum(v):
    """C 배정밀도 리터럴 — 최단 왕복 표현(Python repr)에 소수점을 보장한다."""
    v = float(v)
    if not math.isfinite(v):
        raise ValueError(f"비유한 파라미터는 탑재 코드로 낼 수 없다: {v}")
    s = repr(v)
    return s if ("." in s or "e" in s or "E" in s) else s + ".0"


class _Ctx:
    """생성 중 누적 상태 — 파라미터·상태 필드·본문 줄·사용된 헬퍼.

    파라미터와 상태 필드는 **실제로 참조될 때만** 등록된다. 스케줄되는 게인처럼
    신호로 들어오는 값은 파라미터 구조체에 남지 않는다 (dead data 방지).
    """

    def __init__(self):
        self.params = []  # (field, c_literal, comment)
        self.state = []  # (field, c_literal, comment)
        self.body = []
        self.helpers = set()
        self._seen_param = {}

    def param(self, node_id, field, value, comment=""):
        name = f"{node_id}_{field}"
        lit = _cnum(value)
        if name in self._seen_param:
            if self._seen_param[name] != lit:
                raise ValueError(f"파라미터 {name} 중복 등록에 값 불일치")
        else:
            self._seen_param[name] = lit
            self.params.append((name, lit, comment))
        return f"p->{name}"

    def st(self, node_id, field, init, comment=""):
        name = f"{node_id}_{field}"
        if all(n != name for n, _, _ in self.state):
            self.state.append((name, _cnum(init), comment))
        return f"s->{name}"

    def line(self, text=""):
        self.body.append(text)

    def helper(self, name):
        self.helpers.add(name)
        return name


# ── 블록별 에미터 ────────────────────────────────────────────────────────
# 각 함수는 본문 줄을 ctx에 밀어 넣고 이 노드 출력의 C 식을 돌려준다.
# 연산 순서는 Python 구현과 **문자 그대로** 맞춘다 — 배정밀도끼리 비트 일치가
# 목표이므로 `a + b + c`의 결합 순서까지 어긋나면 안 된다.


@_emitter(PID)
def _emit_pid(ctx, node, inst, ins, gains, dt_macro):
    """controllers.py:46 — y = clip(kp·e + I + kd·d), I ← clip(I + dt·ki·e)."""
    nid, e = node.id, ins[0]
    kp = gains.get("kp") or ctx.param(nid, "kp", inst.kp, "비례 게인")
    ki = gains.get("ki") or ctx.param(nid, "ki", inst.ki, "적분 게인")
    lo = ctx.param(nid, "out_lo", inst.out_lo, "출력·적분기 클램프 하한 (안티와인드업)")
    hi = ctx.param(nid, "out_hi", inst.out_hi, "출력·적분기 클램프 상한 (안티와인드업)")
    i_st = ctx.st(nid, "i", 0.0, "적분기 상태")
    clip = ctx.helper("claw_clip")

    terms = f"{kp} * {e} + {i_st}"
    if "kd" in gains or inst.kd != 0.0:
        kd = gains.get("kd") or ctx.param(nid, "kd", inst.kd, "미분 게인")
        e_prev = ctx.st(nid, "e_prev", 0.0, "직전 오차 (미분항)")
        ctx.line(f"    const double {nid}_d = ({e} - {e_prev}) / {dt_macro};")
        terms += f" + {kd} * {nid}_d"
    else:
        # kd = 0 이고 스케줄도 아니면 미분항 전체가 죽은 코드다 — 상태(e_prev)와
        # 매 스텝 나눗셈까지 함께 사라진다 (0.0 곱은 합에 영향이 없다)
        ctx.line(f"    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */")

    out = f"{nid}_y"
    ctx.line(f"    const double {out} = {clip}({terms}, {lo}, {hi});")
    ctx.line(f"    {i_st} = {clip}({i_st} + {dt_macro} * {ki} * {e}, {lo}, {hi});")
    if "kd" in gains or inst.kd != 0.0:
        ctx.line(f"    {ctx.st(nid, 'e_prev', 0.0)} = {e};")
    return out


@_emitter(Washout)
def _emit_washout(ctx, node, inst, ins, gains, dt_macro):
    """filters.py:55 — y = u − x, x ← p·x + (1−p)·u.  p는 엔진이 구운 값."""
    nid, u = node.id, ins[0]
    p = ctx.param(nid, "p", inst._p, f"exp(-dt/tau), tau={inst.tau} s — {dt_macro}로 구움")
    omp = ctx.param(nid, "one_minus_p", 1.0 - inst._p, "1 − p")
    x = ctx.st(nid, "x", 0.0, "워시아웃 상태")
    out = f"{nid}_y"
    ctx.line(f"    const double {out} = {u} - {x};")
    ctx.line(f"    {x} = {p} * {x} + {omp} * {u};")
    return out


@_emitter(Saturation)
def _emit_saturation(ctx, node, inst, ins, gains, dt_macro):
    nid = node.id
    lo = ctx.param(nid, "lo", inst.lo, "하한")
    hi = ctx.param(nid, "hi", inst.hi, "상한")
    clip = ctx.helper("claw_clip")
    out = f"{nid}_y"
    ctx.line(f"    const double {out} = {clip}({ins[0]}, {lo}, {hi});")
    return out


@_emitter(Gain)
def _emit_gain(ctx, node, inst, ins, gains, dt_macro):
    nid = node.id
    k = ctx.param(nid, "k", inst.k, "게인")
    out = f"{nid}_y"
    ctx.line(f"    const double {out} = {k} * {ins[0]};")
    return out


@_emitter(Product)
def _emit_product(ctx, node, inst, ins, gains, dt_macro):
    out = f"{node.id}_y"
    ctx.line(f"    const double {out} = {' * '.join(ins)};")
    return out


@_emitter(Sum)
def _emit_sum(ctx, node, inst, ins, gains, dt_macro):
    parts = []
    for sign, expr in zip(inst.signs, ins, strict=True):
        if sign == 1.0:
            parts.append(expr if not parts else f"+ {expr}")
        elif sign == -1.0:
            parts.append(f"-{expr}" if not parts else f"- {expr}")
        else:
            term = f"{_cnum(sign)} * {expr}"
            parts.append(term if not parts else f"+ {term}")
    out = f"{node.id}_y"
    ctx.line(f"    const double {out} = {' '.join(parts)};")
    return out


# 순수 연산 — ir_exec._OP_FN의 C 짝. Python `%`는 나머지 부호가 제수를 따르고
# C `fmod`는 피제수를 따르므로 보정이 필요하다 (attitude.py:15와 같은 결과)
_OP_C = {
    "wrap_pi": (
        "claw_wrap_pi",
        "static double claw_wrap_pi(double a)\n"
        "{\n"
        "    double r = fmod(-a + CLAW_PI, 2.0 * CLAW_PI);\n"
        "    if (r < 0.0) { r += 2.0 * CLAW_PI; }\n"
        "    return -(r - CLAW_PI);\n"
        "}",
    ),
}

_HELPER_SRC = {
    "claw_clip": (
        "static double claw_clip(double x, double lo, double hi)\n"
        "{\n"
        "    const double y = (x < lo) ? lo : x;\n"
        "    return (y > hi) ? hi : y;\n"
        "}"
    ),
    "claw_wrap_pi": _OP_C["wrap_pi"][1],
}


def _fingerprint(graph, runner, ctx):
    """형상 지문 — 파라미터 값 + dt + 구조. 구조가 바뀌어도 지문이 바뀐다."""
    payload = {f"param.{n}": lit for n, lit, _ in ctx.params}
    payload["dt"] = runner.dt
    payload["structure"] = " ".join(
        f"{n.id}:{n.block.__name__ if n.kind == 'block' else n.op}"
        f"({','.join(n.inputs)})[{','.join(sorted(n.gains))}]"
        for n in graph.nodes
    )
    payload["output"] = graph.output
    payload["inputs"] = ",".join(graph.inputs)
    return canonical_hash(payload)


def emit_c(graph, runner):
    """IR + 초기화된 실행기 → {파일명: 내용}. 생성은 결정적(시각 미포함)."""
    if runner.graph is not graph:
        raise ValueError("runner가 다른 그래프로 만들어졌다")
    base = graph.name
    guard = base.upper()
    dt_macro = f"{guard}_DT"
    ctx = _Ctx()

    env = {u: u for u in graph.inputs}  # 그래프 입력은 C 함수 인자 이름 그대로
    for node in graph.nodes:
        ins = [env[r] for r in node.inputs]
        if node.kind == "op":
            fn, _src = _OP_C[node.op]
            ctx.helper(fn)
            out = f"{node.id}_y"
            ctx.line()
            ctx.line(f"    /* {node.id} — {node.op} */")
            ctx.line(f"    const double {out} = {fn}({', '.join(ins)});")
            env[node.id] = out
            continue
        inst = runner.instances[node.id]
        emit = _EMITTERS.get(type(inst))
        if emit is None:
            raise NotImplementedError(
                f"{type(inst).__name__} C 에미터 미구현 — 지원: "
                f"{sorted(c.__name__ for c in _EMITTERS)}"
            )
        gains = {port: env[ref] for port, ref in node.gains.items()}
        ctx.line()
        ctx.line(f"    /* {node.id} — {type(inst).__name__} */")
        env[node.id] = emit(ctx, node, inst, ins, gains, dt_macro)

    fp = _fingerprint(graph, runner, ctx)
    # 쓰이지 않는 인자는 -Wunused-parameter를 부른다. `\b`라 k_rate가 rate를 가리지 않는다
    body_text = "\n".join(ctx.body)
    unused_inputs = [u for u in graph.inputs if not re.search(rf"\b{u}\b", body_text)]

    args = ", ".join(f"double {u}" for u in graph.inputs)
    head = f"double {base}_step("  # 둘째 줄을 여는 괄호 뒤에 맞춘다
    sig = f"{head}const {base}_params_t *p, {base}_state_t *s,\n{' ' * len(head)}{args})"
    while ctx.body and not ctx.body[0].strip():
        ctx.body.pop(0)

    return {
        f"{base}_types.h": _types_h(base, guard, ctx, fp),
        f"{base}.h": _header_h(base, guard, dt_macro, runner, sig, fp),
        f"{base}_data.c": _data_c(base, ctx, fp),
        f"{base}.c": _impl_c(base, ctx, sig, env[graph.output], unused_inputs),
    }


def _banner(base, fp, extra=()):
    lines = [
        "/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).",
        f" * 그래프  : {base}",
        f" * 지문    : {fp}",
        f" * 엔진    : claw {claw.__version__}",
    ]
    lines += [f" * {t}" for t in extra]
    lines.append(" */")
    return lines


def _tail_align(rows):
    """`본문`과 `/* 설명 */`의 열을 맞춘다 — 생성 데이터도 리뷰 대상 문서다."""
    width = max((len(t) for t, c in rows if c), default=0)
    return [f"{t.ljust(width)}  /* {c} */" if c else t for t, c in rows]


def _align_init(rows):
    """지정 초기화자 `.이름 = 값,` 열 맞춤."""
    if not rows:
        return []
    wn = max(len(n) for n, _, _ in rows)
    return _tail_align([(f"    .{n.ljust(wn)} = {v},", c) for n, v, c in rows])


def _align_fields(rows, empty_note):
    """구조체 멤버 선언 열 맞춤."""
    if not rows:
        return [f"    char _unused;  /* {empty_note} */"]
    return _tail_align([(f"    double {n};", c) for n, _v, c in rows])


def _types_h(base, guard, ctx, fp):
    lines = _banner(base, fp, ["자료형 (MATLAB _types.h 대응)"])
    lines += [f"#ifndef CLAW_{guard}_TYPES_H", f"#define CLAW_{guard}_TYPES_H", ""]
    lines.append("/* 파라미터 (MATLAB rtP 대응) — 실제로 참조되는 것만 있다:")
    lines.append(" * 게인 스케줄로 신호가 된 값은 여기 남지 않는다. */")
    lines.append("typedef struct {")
    lines += _align_fields(ctx.params, "파라미터 없는 그래프")
    lines.append(f"}} {base}_params_t;")
    lines.append("")
    lines.append("/* 상태 (MATLAB rtDW 대응) — 범프리스 전환은 리셋 후 이 필드를 직접 쓴다. */")
    lines.append("typedef struct {")
    lines += _align_fields(ctx.state, "상태 없는 그래프")
    lines.append(f"}} {base}_state_t;")
    lines += ["", f"#endif /* CLAW_{guard}_TYPES_H */"]
    return "\n".join(lines) + "\n"


def _header_h(base, guard, dt_macro, runner, sig, fp):
    lines = _banner(base, fp)
    lines += [
        f"#ifndef CLAW_{guard}_H",
        f"#define CLAW_{guard}_H",
        "",
        f'#include "{base}_types.h"',
        "",
        "/* 빌드 요구 — 설계 시뮬과의 비트 일치는 아래 조건에서만 성립한다:",
        " *   · 부동소수 축약(FMA) 금지   예) -ffp-contract=off",
        " *   · 빠른 수학 최적화 금지     예) -ffast-math 를 쓰지 않는다",
        " * 측정: contract=fast로 빌드하면 곱셈-덧셈이 FMA로 합쳐져 중간 반올림이",
        " * 사라지고, 같은 입력에서 최대 2.8e-16 어긋난다 (clang 14, -O2).",
        " * 타깃 컴파일러·최적화 옵션 차이는 별도 확인(PIL)이 필요하다. */",
        "",
        "/* 이 주기로 이산 계수가 구워져 있다 — 주기를 바꾸려면 재생성해야 한다.",
        " * 이 값만 고치면 필터 계수가 조용히 틀린다. */",
        f"#define {dt_macro} {_cnum(runner.dt)}",
        "",
        f"extern const {base}_params_t {base}_params;",
        "",
        "/* 상태를 초기값으로 되돌린다. 이산 계수는 생성 시점에 구워졌으므로",
        " * 런타임 초기화는 이것뿐이다 (별도 init 없음). */",
        f"void {base}_reset({base}_state_t *s);",
        "",
        f"{sig};",
        "",
        f"#endif /* CLAW_{guard}_H */",
    ]
    return "\n".join(lines) + "\n"


def _data_c(base, ctx, fp):
    lines = _banner(base, fp, ["파라미터 데이터 (MATLAB _data.c 대응)"])
    lines += ["", f'#include "{base}.h"', "", f"const {base}_params_t {base}_params = {{"]
    lines += _align_init(ctx.params)
    lines.append("};")
    return "\n".join(lines) + "\n"


def _impl_c(base, ctx, sig, out_expr, unused_inputs):
    lines = ["/* CLAW 생성 코드 — 손으로 고치지 말 것 (알고리즘, MATLAB _step 대응). */"]
    lines += [f'#include "{base}.h"', ""]
    if any(h == "claw_wrap_pi" for h in ctx.helpers):
        lines += ["#include <math.h>", "", "#define CLAW_PI 3.141592653589793", ""]
    for name in sorted(ctx.helpers):
        lines += [_HELPER_SRC[name], ""]

    lines.append(f"void {base}_reset({base}_state_t *s)")
    lines.append("{")
    if ctx.state:
        for name, lit, _c in ctx.state:
            lines.append(f"    s->{name} = {lit};")
    else:
        lines.append("    (void)s;")
    lines += ["}", ""]

    lines.append(sig)
    lines.append("{")
    for u in unused_inputs:
        lines.append(f"    (void){u};  /* 이 형상에서는 쓰이지 않음 */")
    if not ctx.params:
        lines.append("    (void)p;")
    if not ctx.state:
        lines.append("    (void)s;")
    lines += ctx.body
    lines += ["", f"    return {out_expr};", "}"]
    return "\n".join(lines) + "\n"
