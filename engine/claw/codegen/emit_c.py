"""IR의 C 백엔드 — FCC에 통합되어 그대로 실릴 제어법칙 코드를 생성한다 (02 §1·§2.2).

파일 구성은 MATLAB Embedded Coder를 따른다: 알고리즘(`.c`) / 파라미터 데이터
(`_data.c`, rtP 대응) / 상태·출력 구조체(`_types.h`, rtDW·rtY 대응) / 진입점(`.h`).

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
from claw.blocks.lookup import LookupBlock
from claw.fcl.autopilot import CommandFilter
from claw.params.paramset import canonical_hash

_EMITTERS = {}
_DISABLERS = {}


def _emitter(cls):
    def deco(fn):
        _EMITTERS[cls] = fn
        return fn

    return deco


def _disabler(cls):
    def deco(fn):
        _DISABLERS[cls] = fn
        return fn

    return deco


def _cnum(v):
    """C 배정밀도 리터럴 — 최단 왕복 표현(Python repr)에 소수점을 보장한다."""
    v = float(v)
    if not math.isfinite(v):
        raise ValueError(f"비유한 파라미터는 탑재 코드로 낼 수 없다: {v}")
    s = repr(v)
    return s if ("." in s or "e" in s or "E" in s) else s + ".0"


def _wrap_stmt(text, width=98):
    """긴 문장을 바깥쪽 호출의 쉼표에서 접어 여는 괄호에 맞춘다.

    생성 코드는 리뷰 대상이라 가로 스크롤이 생기면 안 된다. 접을 자리가 없으면
    (긴 식 하나) 그대로 둔다 — 억지로 쪼개면 오히려 읽기 어려워진다.
    """
    if len(text) <= width:
        return [text]
    depth, open_col, splits = 0, None, []
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
            if depth == 1:
                open_col = i
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 1:
            splits.append(i)
    if open_col is None or not splits:
        return [text]
    pad = " " * (open_col + 1)
    pieces, prev = [], 0
    for pos in splits + [len(text)]:
        pieces.append(text[prev:pos + 1].strip() if prev else text[:pos + 1])
        prev = pos + 1
    out, cur = [], pieces[0]
    for piece in pieces[1:]:
        if len(cur) + 1 + len(piece) > width:
            out.append(cur)
            cur = pad + piece
        else:
            cur += " " + piece
    out.append(cur)
    return out


class _Ctx:
    """생성 중 누적 상태 — 파라미터·상태 필드·본문 줄·사용된 헬퍼.

    파라미터와 상태 필드는 **실제로 참조될 때만** 등록된다. 스케줄되는 게인처럼
    신호로 들어오는 값은 파라미터 구조체에 남지 않는다 (dead data 방지).
    """

    def __init__(self):
        self.params = []  # (field, c_literal, comment)
        self.arrays = []  # (field, [literal], comment)
        self.state = []  # (field, c_type, c_init, comment)
        self.body = []
        self.helpers = set()
        self.hoisted = set()  # enable 영역 안에서 대입되는(미리 선언된) 출력 변수
        self.indent = 1
        self._seen_param = {}

    # ── 등록 ──
    def param(self, node_id, field, value, comment=""):
        name = f"{node_id}_{field}"
        lit = _cnum(value)
        if name in self._seen_param:
            if self._seen_param[name] != lit:
                raise ValueError(f"파라미터 {name} 중복 등록에 값 불일치")
        else:
            self._seen_param[name] = lit
            self.params.append((name, lit, comment))
        return f"prm->{name}"

    def array(self, node_id, field, values, comment=""):
        name = f"{node_id}_{field}"
        if all(n != name for n, _, _ in self.arrays):
            self.arrays.append((name, [_cnum(v) for v in values], comment))
        return f"prm->{name}"

    def st(self, node_id, field, init, comment="", ctype="double"):
        name = f"{node_id}_{field}"
        if all(n != name for n, _, _, _ in self.state):
            self.state.append((name, ctype, init, comment))
        return f"sta->{name}"

    def helper(self, name):
        self.helpers.add(name)
        return name

    # ── 본문 ──
    def line(self, text=""):
        if not text:
            self.body.append("")
            return
        self.body.extend(_wrap_stmt("    " * self.indent + text))

    def declare(self, name, expr):
        """노드 출력 선언. enable 영역 안이면 미리 선언된 변수에 대입한다."""
        if name in self.hoisted:
            self.line(f"{name} = {expr};")
        else:
            self.line(f"const double {name} = {expr};")
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
    has_d = "kd" in gains or inst.kd != 0.0
    if has_d:
        kd = gains.get("kd") or ctx.param(nid, "kd", inst.kd, "미분 게인")
        e_prev = ctx.st(nid, "e_prev", 0.0, "직전 오차 (미분항)")
        ctx.line(f"const double {nid}_d = ({e} - {e_prev}) / {dt_macro};")
        terms += f" + {kd} * {nid}_d"
    else:
        # kd = 0 이고 스케줄도 아니면 미분항 전체가 죽은 코드다 — 상태(e_prev)와
        # 매 스텝 나눗셈까지 함께 사라진다 (0.0 곱은 합에 영향이 없다)
        ctx.line(f"/* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */")

    out = ctx.declare(f"{nid}_y", f"{clip}({terms}, {lo}, {hi})")
    ctx.line(f"{i_st} = {clip}({i_st} + {dt_macro} * {ki} * {e}, {lo}, {hi});")
    if has_d:
        ctx.line(f"{ctx.st(nid, 'e_prev', 0.0)} = {e};")
    return out


@_emitter(Washout)
def _emit_washout(ctx, node, inst, ins, gains, dt_macro):
    """filters.py:55 — y = u − x, x ← p·x + (1−p)·u.  p는 엔진이 구운 값."""
    nid, u = node.id, ins[0]
    p = ctx.param(nid, "p", inst._p, f"exp(-dt/tau), tau={inst.tau} s — {dt_macro}로 구움")
    omp = ctx.param(nid, "one_minus_p", 1.0 - inst._p, "1 − p")
    x = ctx.st(nid, "x", 0.0, "워시아웃 상태")
    out = ctx.declare(f"{nid}_y", f"{u} - {x}")
    ctx.line(f"{x} = {p} * {x} + {omp} * {u};")
    return out


@_emitter(CommandFilter)
def _emit_command_filter(ctx, node, inst, ins, gains, dt_macro):
    """autopilot.py:60 — 첫 스텝은 현재 측정으로 시드(캡처 거동), 이후 1차 램프."""
    nid, cmd, current = node.id, ins[0], ins[1]
    omp = ctx.param(
        nid, "one_minus_p", 1.0 - inst._p,
        f"1 − exp(-dt/tau), tau={inst.tau} s" + (" (0=통과)" if inst.tau == 0 else ""),
    )
    x = ctx.st(nid, "x", 0.0, "필터 상태(= 출력)")
    seeded = ctx.st(nid, "seeded", 0, "시드 완료 여부 — 첫 스텝은 측정에서 출발", ctype="int")
    ctx.line(f"if (!{seeded}) {{ {x} = {current}; {seeded} = 1; }}")
    diff = f"{cmd} - {x}"
    if inst.angle:
        wrap = ctx.helper("claw_wrap_pi")
        diff = f"{wrap}({diff})"  # 최단 경로 보간 — ±π 경계 통과
    ctx.line(f"const double {nid}_d = {diff};")
    ctx.line(f"{x} = {x} + {omp} * {nid}_d;")
    if inst.angle:
        ctx.line(f"{x} = {ctx.helper('claw_wrap_pi')}({x});")
    return ctx.declare(f"{nid}_y", x)


@_disabler(CommandFilter)
def _disable_command_filter(ctx, node, inst, field, value_expr):
    """`reset_to(v)`는 상태 대입이자 **시드 완료** 선언이다 (`_x`가 None이 아니게 됨)."""
    if field != "x":
        raise ValueError(f"{node.id}: CommandFilter 비활성 대입은 x만 지원 ({field})")
    ctx.line(f"sta->{node.id}_x = {value_expr};")
    ctx.line(f"sta->{node.id}_seeded = 1;")


@_emitter(Saturation)
def _emit_saturation(ctx, node, inst, ins, gains, dt_macro):
    nid = node.id
    lo = ctx.param(nid, "lo", inst.lo, "하한")
    hi = ctx.param(nid, "hi", inst.hi, "상한")
    clip = ctx.helper("claw_clip")
    return ctx.declare(f"{nid}_y", f"{clip}({ins[0]}, {lo}, {hi})")


@_emitter(Gain)
def _emit_gain(ctx, node, inst, ins, gains, dt_macro):
    k = ctx.param(node.id, "k", inst.k, "게인")
    return ctx.declare(f"{node.id}_y", f"{k} * {ins[0]}")


@_emitter(Product)
def _emit_product(ctx, node, inst, ins, gains, dt_macro):
    return ctx.declare(f"{node.id}_y", " * ".join(ins))


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
    return ctx.declare(f"{node.id}_y", " ".join(parts))


@_emitter(LookupBlock)
def _emit_lookup(ctx, node, inst, ins, gains, dt_macro):
    """1D 테이블 — 격자점·값 배열을 구워 낸다. 외삽은 clip 고정(01 §3.4 [기본값])."""
    table = inst.table
    if len(inst.axis_order) != 1:
        raise NotImplementedError(f"{node.id}: 1D 테이블만 지원 (축 {inst.axis_order})")
    if table.extrapolate != "clip":
        raise NotImplementedError(
            f"{node.id}: extrapolate='clip'만 지원 — 받음 {table.extrapolate!r} "
            "(비행 중 예외를 낼 수 없으므로 외삽 금지가 원칙)"
        )
    nid, axis = node.id, inst.axis_order[0]
    bp = ctx.array(nid, "bp", table.axes[0], f"{axis} 격자점")
    val = ctx.array(nid, "val", table.data, f"{table.name or nid} 값")
    lut = ctx.helper("claw_lookup1d")
    n = len(table.axes[0])
    return ctx.declare(f"{nid}_y", f"{lut}({bp}, {val}, {n}, {ins[0]})")


# 순수 연산 — ir_exec._OP_FN의 C 짝. 인라인 식이면 (템플릿, 필요 헬퍼) 형태.
# Python `%`는 나머지 부호가 제수를 따르고 C `fmod`는 피제수를 따르므로 wrap_pi에
# 보정이 필요하다. min2는 CPython min(a,b)의 `b if b < a else a`를 그대로 옮긴다.
_OP_C = {
    "wrap_pi": lambda a: ("claw_wrap_pi({0})".format(a), ("claw_wrap_pi",)),
    "min2": lambda a, b: (f"(({b}) < ({a}) ? ({b}) : ({a}))", ()),
    "gt": lambda a, b: (f"(({a}) > ({b}) ? 1.0 : 0.0)", ()),
    # 음수 상수는 `x + -0.05`가 아니라 `x - 0.05`로 (IEEE에서 동일, 읽기는 다르다)
    "add_const": lambda a, c: (
        (f"{a} - {_cnum(-c)}" if c < 0 else f"{a} + {_cnum(c)}"),
        (),
    ),
    # autopilot.py:161 — 1.0 / math.cos(φ) - 1.0
    "sec_minus_1": lambda a: (f"1.0 / cos({a}) - 1.0", ("math",)),
    # autopilot.py:170 — 1.0 / math.cos(φ) ** 2 - 1.0 (Python `**2`는 libm pow)
    "sec2_minus_1": lambda a: (f"1.0 / pow(cos({a}), 2.0) - 1.0", ("math",)),
}

_HELPER_ORDER = ("claw_clip", "claw_wrap_pi", "claw_lookup1d")
_HELPER_SRC = {
    "claw_clip": (
        "static double claw_clip(double x, double lo, double hi)\n"
        "{\n"
        "    const double y = (x < lo) ? lo : x;\n"
        "    return (y > hi) ? hi : y;\n"
        "}"
    ),
    "claw_wrap_pi": (
        "/* (-π, π] 래핑 — Python `%`는 나머지가 제수 부호를 따르므로 fmod 뒤 보정한다 */\n"
        "static double claw_wrap_pi(double a)\n"
        "{\n"
        "    double r = fmod(-a + CLAW_PI, 2.0 * CLAW_PI);\n"
        "    if (r < 0.0) { r += 2.0 * CLAW_PI; }\n"
        "    return -(r - CLAW_PI);\n"
        "}"
    ),
    "claw_lookup1d": (
        "/* 1D 다중선형 보간, 외삽 clip — tables/table.py:54 interp()와 같은 구간 선택 */\n"
        "static double claw_lookup1d(const double *bp, const double *val, int n, double x)\n"
        "{\n"
        "    int i = 0;\n"
        "    while (i < n - 2 && x >= bp[i + 1]) { i++; }\n"
        "    const double t = claw_clip((x - bp[i]) / (bp[i + 1] - bp[i]), 0.0, 1.0);\n"
        "    return (1.0 - t) * val[i] + t * val[i + 1];\n"
        "}"
    ),
}
_HELPER_NEEDS = {"claw_lookup1d": ("claw_clip",), "claw_wrap_pi": ("math",)}


def _fingerprint(graph, runner, ctx):
    """형상 지문 — 파라미터 값 + dt + 구조. 구조가 바뀌어도 지문이 바뀐다."""
    payload = {f"param.{n}": lit for n, lit, _ in ctx.params}
    payload.update({f"array.{n}": ",".join(v) for n, v, _ in ctx.arrays})
    payload["dt"] = runner.dt
    payload["structure"] = " ".join(
        f"{n.id}:{n.block.__name__ if n.kind == 'block' else n.op}"
        f"({','.join(n.inputs)})[{','.join(sorted(n.gains))}]"
        f"{'=' + repr(n.value) if getattr(n, 'value', None) is not None else ''}"
        f"{'@' + n.enable if getattr(n, 'enable', None) else ''}"
        for n in graph.nodes
    )
    payload["outputs"] = ",".join(f"{k}={v}" for k, v in graph.outputs.items())
    payload["inputs"] = ",".join(graph.inputs)
    payload["enable"] = graph.enable or ""
    return canonical_hash(payload)


def _emit_one(ctx, node, runner, env, dt_macro):
    ins = [env[r] for r in node.inputs]
    if node.kind == "op":
        expr, needs = _OP_C[node.op](*ins, *((node.value,) if node.value is not None else ()))
        for need in needs:
            ctx.helper(need)
        ctx.line()
        ctx.line(f"/* {node.id} — {node.op} */")
        env[node.id] = ctx.declare(f"{node.id}_y", expr)
        return
    inst = runner.instances[node.id]
    emit = _EMITTERS.get(type(inst))
    if emit is None:
        raise NotImplementedError(
            f"{type(inst).__name__} C 에미터 미구현 — 지원: "
            f"{sorted(c.__name__ for c in _EMITTERS)}"
        )
    gains = {port: env[ref] for port, ref in node.gains.items()}
    ctx.line()
    ctx.line(f"/* {node.id} — {type(inst).__name__} */")
    env[node.id] = emit(ctx, node, inst, ins, gains, dt_macro)


def _emit_region(ctx, nodes, enable, runner, env, dt_macro):
    """같은 enable을 가진 연속 노드 → if/else 한 덩이 (Simulink Enabled Subsystem)."""
    for node in nodes:
        name = f"{node.id}_y"
        ctx.hoisted.add(name)
        ctx.line(f"double {name} = {_cnum(node.disabled_output)};")
    ctx.line(f"if ({env[enable]} != 0.0) {{")
    ctx.indent += 1
    mark = len(ctx.body)
    for node in nodes:
        _emit_one(ctx, node, runner, env, dt_macro)
    if len(ctx.body) > mark and not ctx.body[mark].strip():
        ctx.body.pop(mark)  # 여는 중괄호 바로 뒤 빈 줄 제거
    ctx.indent -= 1
    ctx.line("} else {")
    ctx.indent += 1
    ctx.line(f"/* 비활성 — 상태만 정리한다 (실행하지 않는다) */")
    for node in nodes:
        for field, value in node.on_disable.items():
            inst = runner.instances[node.id]
            expr = env[value] if isinstance(value, str) else _cnum(value)
            disabler = _DISABLERS.get(type(inst))
            if disabler is not None:
                disabler(ctx, node, inst, field, expr)
            else:
                ctx.line(f"sta->{node.id}_{field} = {expr};")
    ctx.indent -= 1
    ctx.line("}")


def emit_c(graph, runner):
    """IR + 초기화된 실행기 → {파일명: 내용}. 생성은 결정적(시각 미포함)."""
    if runner.graph is not graph:
        raise ValueError("runner가 다른 그래프로 만들어졌다")
    base = graph.name
    guard = base.upper()
    dt_macro = f"{guard}_DT"
    ctx = _Ctx()
    single = len(graph.outputs) == 1

    env = {u: u for u in graph.inputs}  # 그래프 입력은 C 함수 인자 이름 그대로
    nodes = list(graph.nodes)
    i = 0
    while i < len(nodes):
        enable = getattr(nodes[i], "enable", None)
        if enable is None:
            _emit_one(ctx, nodes[i], runner, env, dt_macro)
            i += 1
            continue
        j = i
        while j < len(nodes) and getattr(nodes[j], "enable", None) == enable:
            j += 1
        ctx.line()
        ctx.line(f"/* ── {enable} 영역 ({j - i}개 노드) ── */")
        _emit_region(ctx, nodes[i:j], enable, runner, env, dt_macro)
        i = j

    while ctx.body and not ctx.body[0].strip():
        ctx.body.pop(0)

    fp = _fingerprint(graph, runner, ctx)
    # 그래프 enable은 본문이 아니라 함수 진입부에서 쓰이므로 미사용이 아니다
    body_text = "\n".join(ctx.body)
    unused = [
        u for u in graph.inputs
        if u != graph.enable and not re.search(rf"\b{u}\b", body_text)
    ]

    head = f"{'double' if single else 'void'} {base}_step("
    pad = " " * len(head)
    first = f"const {base}_params_t *prm, {base}_state_t *sta,"
    if not single:
        first += f" {base}_out_t *out,"
    sig = head + first + _wrap_args([f"double {u}" for u in graph.inputs], pad)

    return {
        f"{base}_types.h": _types_h(base, guard, ctx, graph, fp, single),
        f"{base}.h": _header_h(base, guard, dt_macro, runner, sig, fp, graph, single),
        f"{base}_data.c": _data_c(base, ctx, fp),
        f"{base}.c": _impl_c(base, ctx, sig, graph, env, unused, single),
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


def _wrap_args(args, pad, width=98):
    """인자 목록을 pad 열에 맞춰 줄바꿈 — 입력이 늘어도 시그니처가 읽힌다."""
    lines, cur = [], ""
    for k, arg in enumerate(args):
        piece = arg + ("," if k < len(args) - 1 else ")")
        if cur and len(pad) + len(cur) + len(piece) + 1 > width:
            lines.append(cur.rstrip())
            cur = ""
        cur += piece + " "
    lines.append(cur.rstrip())
    return "\n" + "\n".join(pad + ln for ln in lines)


def _wrap_array(name, literals, indent="        "):
    """긴 배열 초기화자를 줄바꿈 — 한 줄에 몰아 두면 리뷰가 불가능하다."""
    out, cur = [], indent
    for k, lit in enumerate(literals):
        piece = lit + ("," if k < len(literals) - 1 else "")
        if len(cur) + len(piece) + 1 > 92 and cur.strip():
            out.append(cur.rstrip())
            cur = indent
        cur += piece + " "
    if cur.strip():
        out.append(cur.rstrip())
    return out


def _types_h(base, guard, ctx, graph, fp, single):
    lines = _banner(base, fp, ["자료형 (MATLAB _types.h 대응)"])
    lines += [f"#ifndef CLAW_{guard}_TYPES_H", f"#define CLAW_{guard}_TYPES_H", ""]
    lines.append("/* 파라미터 (MATLAB rtP 대응) — 실제로 참조되는 것만 있다:")
    lines.append(" * 게인 스케줄로 신호가 된 값은 여기 남지 않는다. */")
    lines.append("typedef struct {")
    rows = [(f"    double {n};", c) for n, _v, c in ctx.params]
    rows += [(f"    double {n}[{len(v)}];", c) for n, v, c in ctx.arrays]
    lines += _tail_align(rows) if rows else ["    char _unused;  /* 파라미터 없는 그래프 */"]
    lines.append(f"}} {base}_params_t;")
    lines.append("")

    if not single:
        lines.append("/* 출력 (MATLAB rtY 대응) */")
        lines.append("typedef struct {")
        lines += _tail_align([(f"    double {n};", "") for n in graph.outputs])
        lines += [f"}} {base}_out_t;", ""]

    lines.append("/* 상태 (MATLAB rtDW 대응) — 범프리스 전환은 리셋 후 이 필드를 직접 쓴다. */")
    lines.append("typedef struct {")
    rows = [(f"    {t} {n};", c) for n, t, _v, c in ctx.state]
    if graph.enable is not None:
        held = "double hold;" if single else f"{base}_out_t hold;"
        rows.append((f"    {held}", f"{graph.enable}=0일 때 그대로 내보낼 직전 출력"))
    lines += _tail_align(rows) if rows else ["    char _unused;  /* 상태 없는 그래프 */"]
    lines.append(f"}} {base}_state_t;")
    lines += ["", f"#endif /* CLAW_{guard}_TYPES_H */"]
    return "\n".join(lines) + "\n"


def _header_h(base, guard, dt_macro, runner, sig, fp, graph, single):
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
        " * 런타임 초기화는 이것뿐이다 (별도 init 없음).",
        " * 트림 웜스타트·범프리스 전환은 리셋 후 상태 필드를 직접 대입한다. */",
        f"void {base}_reset({base}_state_t *sta);",
        "",
    ]
    if graph.enable is not None:
        lines += [
            f"/* {graph.enable} = 0 이면 아무것도 실행하지 않고 직전 출력을 그대로 낸다",
            " * (상태도 동결). 첫 스텝부터 비활성일 수 있으므로 hold 초기값은",
            " * 통합 계층이 트림 값으로 채운다. */",
        ]
    lines += [f"{sig};", "", f"#endif /* CLAW_{guard}_H */"]
    return "\n".join(lines) + "\n"


def _data_c(base, ctx, fp):
    lines = _banner(base, fp, ["파라미터 데이터 (MATLAB _data.c 대응)"])
    lines += ["", f'#include "{base}.h"', "", f"const {base}_params_t {base}_params = {{"]
    if ctx.params:
        wn = max(len(n) for n, _, _ in ctx.params)
        lines += _tail_align(
            [(f"    .{n.ljust(wn)} = {v},", c) for n, v, c in ctx.params]
        )
    for name, values, comment in ctx.arrays:
        lines.append(f"    .{name} = {{" + (f"  /* {comment} */" if comment else ""))
        lines += _wrap_array(name, values)
        lines.append("    },")
    lines.append("};")
    return "\n".join(lines) + "\n"


def _impl_c(base, ctx, sig, graph, env, unused, single):
    lines = ["/* CLAW 생성 코드 — 손으로 고치지 말 것 (알고리즘, MATLAB _step 대응). */"]
    lines += [f'#include "{base}.h"', ""]
    if "math" in ctx.helpers or any(
        h in ctx.helpers for h in ("claw_wrap_pi",)
    ):
        lines += ["#include <math.h>", "", "#define CLAW_PI 3.141592653589793", ""]
    for name in _HELPER_ORDER:
        if name in ctx.helpers:
            for need in _HELPER_NEEDS.get(name, ()):
                if need != "math":
                    ctx.helpers.add(need)
    for name in _HELPER_ORDER:
        if name in ctx.helpers:
            lines += [_HELPER_SRC[name], ""]

    lines.append(f"void {base}_reset({base}_state_t *sta)")
    lines.append("{")
    if ctx.state or graph.enable is not None:
        for name, ctype, init, _c in ctx.state:
            lines.append(f"    sta->{name} = {_cnum(init) if ctype == 'double' else int(init)};")
        if graph.enable is not None:
            if single:
                lines.append("    sta->hold = 0.0;")
            else:
                for out_name in graph.outputs:
                    lines.append(f"    sta->hold.{out_name} = 0.0;")
    else:
        lines.append("    (void)sta;")
    lines += ["}", ""]

    lines.append(sig)
    lines.append("{")
    for u in unused:
        lines.append(f"    (void){u};  /* 이 형상에서는 쓰이지 않음 */")
    if not ctx.params and not ctx.arrays:
        lines.append("    (void)prm;")
    if not ctx.state and graph.enable is None:
        lines.append("    (void)sta;  /* 상태 없는 그래프 */")
    if graph.enable is not None:
        lines.append(f"    if ({graph.enable} == 0.0) {{  /* 직전 출력 유지, 상태 동결 */")
        lines.append("        " + ("return sta->hold;" if single else "*out = sta->hold;"))
        if not single:
            lines.append("        return;")
        lines.append("    }")
        lines.append("")
    lines += ctx.body
    lines.append("")
    if single:
        expr = env[next(iter(graph.outputs.values()))]
        if graph.enable is not None:
            lines.append(f"    sta->hold = {expr};")
        lines.append(f"    return {expr};")
    else:
        for out_name, node_id in graph.outputs.items():
            lines.append(f"    out->{out_name} = {env[node_id]};")
        if graph.enable is not None:
            lines.append("    sta->hold = *out;")
    lines.append("}")
    return "\n".join(lines) + "\n"
