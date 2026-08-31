"""IR의 C 백엔드 — FCC에 통합되어 그대로 실릴 제어법칙 코드를 생성한다 (02 §1·§2.2).

파일 구성은 MATLAB Embedded Coder를 따라 **두 축**으로 나눈다.

역할축: 알고리즘(`.c`) / 파라미터 데이터(`_data.c`, rtP 대응) / 상태·출력 구조체
(`_types.h`, rtDW·rtY 대응) / 진입점(`.h`).

기능축: IR 노드에 `grouped()`로 이름표가 붙어 있으면 서브시스템마다 `{base}_{group}.c`
와 `.h`가 떨어져 나오고 `{base}.c`에는 조립부만 남는다 — Embedded Coder의
`Function packaging: Nonreusable function` + `File name options: Use subsystem name`에
해당한다. 경계를 넘는 신호는 함수 인자가 되며 **이름이 그대로 유지된다**(정의부
지역변수도 `ap_theta_out_y`, 호출부 지역변수도 `ap_theta_out_y`). 파라미터·상태
구조체는 쪼개지 않는다 — `{base}_reset`과 범프리스 웜스타트 계약이 그대로 남아야 한다.

공용 헬퍼(`claw_clip` 등)는 산출물마다 복제하지 않고 `claw_rt.c/.h` 하나로 낸다
(`emit_runtime`) — MATLAB의 `slprj/ert/_sharedutils/` 자리다.

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
from collections import namedtuple

import claw
from claw.blocks.basic import Gain, Product, Saturation, Sum, Switch
from claw.blocks.controllers import PID
from claw.blocks.filters import CommandFilter, Washout
from claw.blocks.lookup import LookupBlock, PolyBlock
from claw.params.paramset import canonical_hash

_EMITTERS = {}
_DISABLERS = {}

# 파일만 돌려주면 공용 런타임을 합집합으로 만들 수 없다 — 쓴 헬퍼를 함께 낸다.
# 지문은 배너 텍스트에도 있지만, 읽는 쪽이 주석을 파싱하게 두지 않는다
CModule = namedtuple("CModule", "files helpers fingerprint")


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

    기능축으로 쪼개도 `params`·`arrays`·`state`는 **그래프 전체로 공유**한다 —
    구조체는 여전히 `{base}_params_t`·`{base}_state_t` 하나이고 파티션 함수들이
    그 포인터를 함께 받는다. 본문·헬퍼·hoisted만 파티션별로 갈린다.
    """

    def __init__(self):
        self.params = []  # (field, c_literal, comment)
        self.arrays = []  # (field, [literal], comment)
        self.state = []  # (field, c_type, c_init, comment)
        self.body = []
        self.helpers = set()
        self.hoisted = set()  # enable 영역 안에서 대입되는(미리 선언된) 출력 변수
        self.indent = 1
        self.parts = []  # 떼어 낸 파티션들 — (group, 본문 줄, 헬퍼)
        self._seen_param = {}

    def flush_part(self, group):
        """지금까지 쌓인 본문을 파티션 하나로 떼어 낸다 (파라미터·상태는 그대로 둔다)."""
        while self.body and not self.body[0].strip():
            self.body.pop(0)
        self.parts.append((group, list(self.body), set(self.helpers)))
        self.body, self.helpers, self.hoisted = [], set(), set()

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


@_emitter(Switch)
def _emit_switch(ctx, node, inst, ins, gains, dt_macro):
    """Simulink Switch 관례 — (in1, ctrl, in3) → ctrl >= threshold면 in1, 아니면 in3.

    블록·IR·blockspec(SEQ_INPUT)에는 진작 있었는데 C 에미터만 비어 있었다 —
    그래프에 쓰는 순간 코드젠이 조용히가 아니라 미지원으로 터지던 자리다.
    """
    thr = ctx.param(node.id, "threshold", inst.threshold, "전환 임계값")
    in1, ctrl, in3 = ins
    return ctx.declare(f"{node.id}_y", f"(({ctrl}) >= {thr} ? ({in1}) : ({in3}))")


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


@_emitter(PolyBlock)
def _emit_poly(ctx, node, inst, ins, gains, dt_macro):
    """구간별 다항 게인 스케줄 (01 §3.4 다항 런타임) — knot·계수 배열을 구워 낸다.

    계수는 tables/poly.py와 같은 u-영역 오름차수이고, 구간별로 최고 차수(stride)에
    맞춰 0을 덧대 평평한 배열로 낸다 — 호너가 0 계수를 지나도 결과 비트가 같다
    (0.0·u + 0.0 = 0.0). 외삽은 clip 고정 (비행 중 예외 금지 원칙, Lookup과 동일).
    """
    pt = inst.table
    if pt.extrapolate != "clip":
        raise NotImplementedError(
            f"{node.id}: extrapolate='clip'만 지원 — 받음 {pt.extrapolate!r}"
        )
    nid, axis = node.id, inst.axis_order[0]
    nseg = len(pt.segments)
    stride = max(len(s["coeffs"]) for s in pt.segments)
    flat = []
    for s in pt.segments:
        flat.extend(list(s["coeffs"]) + [0.0] * (stride - len(s["coeffs"])))
    kn = ctx.array(nid, "kn", pt.knots, f"{axis} 구간 경계 (n_seg+1)")
    coef = ctx.array(nid, "coef", flat, f"{pt.name or nid} u-영역 계수 (오름차수, 0 패딩)")
    cs = ctx.array(nid, "c", [s["c"] for s in pt.segments], "구간 센터")
    hs = ctx.array(nid, "h", [s["h"] for s in pt.segments], "구간 스케일")
    fn = ctx.helper("claw_polyeval1d")
    return ctx.declare(
        f"{nid}_y", f"{fn}({kn}, {nseg}, {coef}, {stride}, {cs}, {hs}, {ins[0]})"
    )


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

# 공용 런타임 — 산출물마다 복제하지 않고 claw_rt.c/.h 한 벌로 낸다 (emit_runtime).
# "math"는 진짜 헬퍼가 아니라 <math.h>가 필요하다는 표시다. wrap_pi의 fmod 의존은
# claw_rt.c 안에서 끝나므로, wrap_pi를 **부르는** 파티션은 math.h가 필요 없다.
_HELPER_ORDER = ("claw_clip", "claw_wrap_pi", "claw_lookup1d", "claw_polyeval1d")
_HELPER_SIG = {
    "claw_clip": "double claw_clip(double x, double lo, double hi)",
    "claw_wrap_pi": "double claw_wrap_pi(double a)",
    "claw_lookup1d": (
        "double claw_lookup1d(const double *bp, const double *val, int n, double x)"
    ),
    "claw_polyeval1d": (
        "double claw_polyeval1d(const double *kn, int nseg, const double *coef,\n"
        "                       int stride, const double *cs, const double *hs, double x)"
    ),
}
_HELPER_DOC = {
    "claw_clip": "[lo, hi] 클램프",
    "claw_wrap_pi": "(-π, π] 래핑 — Python `%`는 나머지가 제수 부호를 따르므로 fmod 뒤 보정한다",
    "claw_lookup1d": "1D 선형 보간, 외삽 clip — tables/table.py:54 interp()와 같은 구간 선택",
    "claw_polyeval1d": (
        "구간별 다항 u-영역 호너, 외삽 clip — tables/poly.py interp()와 같은 구간 선택"
    ),
}
_HELPER_BODY = {
    "claw_clip": [
        "    const double y = (x < lo) ? lo : x;",
        "    return (y > hi) ? hi : y;",
    ],
    "claw_wrap_pi": [
        "    double r = fmod(-a + CLAW_PI, 2.0 * CLAW_PI);",
        "    if (r < 0.0) { r += 2.0 * CLAW_PI; }",
        "    return -(r - CLAW_PI);",
    ],
    "claw_lookup1d": [
        "    int i = 0;",
        "    while (i < n - 2 && x >= bp[i + 1]) { i++; }",
        "    const double t = claw_clip((x - bp[i]) / (bp[i + 1] - bp[i]), 0.0, 1.0);",
        "    return (1.0 - t) * val[i] + t * val[i + 1];",
    ],
    "claw_polyeval1d": [
        "    int i = 0;",
        "    int k;",
        "    double v = 0.0;",
        "    const double xc = claw_clip(x, kn[0], kn[nseg]);",
        "    while (i < nseg - 1 && xc >= kn[i + 1]) { i++; }",
        "    {",
        "        const double u = (xc - cs[i]) / hs[i];",
        "        for (k = stride - 1; k >= 0; k--) { v = v * u + coef[i * stride + k]; }",
        "    }",
        "    return v;",
    ],
}
_HELPER_NEEDS = {
    "claw_lookup1d": ("claw_clip",),
    "claw_wrap_pi": ("math",),
    "claw_polyeval1d": ("claw_clip",),
}


def _text(lines):
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def emit_runtime(helpers):
    """공용 헬퍼 → {claw_rt.h, claw_rt.c}. MATLAB의 `slprj/ert/_sharedutils/` 자리다.

    산출물이 여럿이면 **헬퍼 합집합으로 한 번** 불러야 한다 — 산출물마다 따로 내면
    헬퍼가 적은 쪽이 덮어써 링크가 조용히 깨진다 (`flight/generate.py::build`).

    필요한 것만 낸다. 안 쓰는 헬퍼를 탑재 코드에 두지 않는 것은 IR이 도달 불가
    노드를 막는 것과 같은 이유다(dead code — DO-178C 논점). 제어법칙 형상과
    무관하므로 지문을 갖지 않는다.
    """
    need = {h for h in helpers if h in _HELPER_SIG}
    for name in _HELPER_ORDER:
        if name in need:
            need.update(d for d in _HELPER_NEEDS.get(name, ()) if d in _HELPER_SIG)
    names = [n for n in _HELPER_ORDER if n in need]
    if not names:
        return {}

    head = [
        "/* CLAW 생성 코드 — 손으로 고치지 말 것.",
        " * 산출물 공용 런타임 (MATLAB _sharedutils 대응). 제어법칙 형상과 무관하므로",
        " * 지문을 갖지 않는다 — 산출물이 여럿이어도 이 한 벌을 함께 쓴다.",
        " */",
    ]
    h = head + ["#ifndef CLAW_RT_H", "#define CLAW_RT_H", ""]
    if "claw_wrap_pi" in names:
        h += ["#define CLAW_PI 3.141592653589793", ""]
    for name in names:
        h += [f"/* {_HELPER_DOC[name]} */", f"{_HELPER_SIG[name]};", ""]
    h += ["#endif /* CLAW_RT_H */"]

    c = head + ['#include "claw_rt.h"', ""]
    if any("math" in _HELPER_NEEDS.get(n, ()) for n in names):
        c += ["#include <math.h>", ""]
    for name in names:
        c += [f"/* {_HELPER_DOC[name]} */", _HELPER_SIG[name], "{"]
        c += _HELPER_BODY[name] + ["}", ""]

    return {"claw_rt.h": _text(h), "claw_rt.c": _text(c)}


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


def _emit_nodes(ctx, nodes, runner, env, dt_macro):
    """노드 목록 → 본문. 같은 enable을 가진 연속 노드는 if/else 한 덩이로 묶는다."""
    nodes = list(nodes)
    i = 0
    while i < len(nodes):
        enable = nodes[i].enable
        if enable is None:
            _emit_one(ctx, nodes[i], runner, env, dt_macro)
            i += 1
            continue
        j = i
        while j < len(nodes) and nodes[j].enable == enable:
            j += 1
        ctx.line()
        ctx.line(f"/* ── {enable} 영역 ({j - i}개 노드) ── */")
        _emit_region(ctx, nodes[i:j], enable, runner, env, dt_macro)
        i = j


def _interfaces(graph):
    """파티션별 인터페이스 — 방출된 텍스트가 아니라 IR에서 계산한다.

    imports: 이 파티션이 읽는 것 중 밖에서 온 것 (그래프 입력 또는 앞 파티션 산출)
    exports: 이 파티션이 만든 것 중 밖에서 읽는 것 (뒤 파티션 또는 그래프 출력)

    순서는 그래프 입력 순 → 정의 선언 순으로 못박는다. 인자 순서가 흔들리면 생성이
    결정적이지 않게 되고, 커밋된 산출물의 diff가 "실제 설계 변경"이라는 의미를 잃는다.
    """
    order = {n.id: k for k, n in enumerate(graph.nodes)}
    ins = list(graph.inputs)
    parts = []
    for group, nodes in graph.partitions:
        mine = {n.id for n in nodes}
        ext = {r for n in nodes for r in n.refs} - mine
        imports = [u for u in ins if u in ext]
        imports += sorted((r for r in ext if r not in set(ins)), key=order.__getitem__)
        parts.append({"group": group, "nodes": nodes, "imports": imports})
    for k, part in enumerate(parts):
        needed = set(graph.outputs.values())
        for later in parts[k + 1:]:
            needed.update(later["imports"])
        part["exports"] = [n.id for n in part["nodes"] if n.id in needed]
    return parts


def _unit_includes(helpers):
    """한 번역 단위가 필요로 하는 포함 — wrap_pi를 **부르는** 쪽은 math.h가 필요 없다."""
    lines = []
    if "math" in helpers:
        lines.append("#include <math.h>")
    if any(h in helpers for h in _HELPER_ORDER):
        lines.append('#include "claw_rt.h"')
    return lines + [""] if lines else []


def emit_c(graph, runner):
    """IR + 초기화된 실행기 → `CModule(파일, 이 그래프가 쓴 공용 헬퍼)`.

    헬퍼를 따로 돌려주는 이유: 공용 런타임(`claw_rt`)은 산출물 **전체의 합집합**으로
    한 번 만들어야 해서 그래프 하나만 보고는 낼 수 없다 (`emit_runtime`).

    노드에 `grouped()` 이름표가 붙어 있으면 서브시스템별 `.c/.h`가 함께 나오고
    `{base}.c`에는 조립부만 남는다. 이름표가 없으면 예전처럼 파일 하나다.
    생성은 결정적이다 (시각 미포함).
    """
    if runner.graph is not graph:
        raise ValueError("runner가 다른 그래프로 만들어졌다")
    base = graph.name
    guard = base.upper()
    dt_macro = f"{guard}_DT"
    ctx = _Ctx()
    single = len(graph.outputs) == 1

    parts = _interfaces(graph) or [
        # 이름표 없음 — 그래프 하나가 파일 하나. 그래프 입력이 곧 함수 인자다
        {"group": None, "nodes": graph.nodes, "imports": list(graph.inputs), "exports": []}
    ]
    for part in parts:
        # 경계를 넘어온 신호는 정의부와 **같은 이름**의 인자로 받는다
        env = {u: u for u in part["imports"] if u in set(graph.inputs)}
        env.update({r: f"{r}_y" for r in part["imports"] if r not in env})
        _emit_nodes(ctx, part["nodes"], runner, env, dt_macro)
        part["env"] = env
        ctx.flush_part(part["group"])

    fp = _fingerprint(graph, runner, ctx)
    # 그래프 enable은 본문이 아니라 함수 진입부에서 쓰이므로 미사용이 아니다
    read = {r for n in graph.nodes for r in n.refs}
    unused = [u for u in graph.inputs if u != graph.enable and u not in read]

    head = f"{'double' if single else 'void'} {base}_step("
    pad = " " * len(head)
    first = f"const {base}_params_t *prm, {base}_state_t *sta,"
    if not single:
        first += f" {base}_out_t *out,"
    sig = head + first + _wrap_args([f"double {u}" for u in graph.inputs], pad)

    files = {
        f"{base}_types.h": _types_h(base, guard, ctx, graph, fp, single, dt_macro, runner),
        f"{base}.h": _header_h(base, guard, sig, fp, graph),
        f"{base}_data.c": _data_c(base, ctx, fp),
    }
    helpers = set()
    for _group, _body, used in ctx.parts:
        helpers |= used

    if graph.partitions:
        top_env = {u: u for u in graph.inputs}
        for part in parts:
            top_env.update({e: f"{e}_y" for e in part["exports"]})
        for (group, body, used), part in zip(ctx.parts, parts):
            name = f"{base}_{group}"
            files[f"{name}.h"] = _part_h(base, name, fp, part)
            files[f"{name}.c"] = _part_c(base, name, fp, part, body, used)
        includes = [f'#include "{base}_{p["group"]}.h"' for p in parts] + [""]
        body = _assembly(base, parts, top_env)
    else:
        top_env = parts[0]["env"]
        includes = _unit_includes(helpers)
        body = ctx.parts[0][1]

    files[f"{base}.c"] = _impl_c(base, ctx, sig, graph, top_env, unused, single, includes, body)
    return CModule(files, helpers, fp)


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


def _types_h(base, guard, ctx, graph, fp, single, dt_macro, runner):
    lines = _banner(base, fp, ["자료형 (MATLAB _types.h 대응)"])
    lines += [f"#ifndef CLAW_{guard}_TYPES_H", f"#define CLAW_{guard}_TYPES_H", ""]
    # dt는 진입점이 아니라 여기 둔다 — 기능축 파티션 헤더가 이 파일만 의존하면 되고,
    # 포함 관계가 DAG로 남는다 (파티션 → _types.h ← 진입점 .h)
    lines += [
        "/* 이 주기로 이산 계수가 구워져 있다 — 주기를 바꾸려면 재생성해야 한다.",
        " * 이 값만 고치면 필터 계수가 조용히 틀린다. */",
        f"#define {dt_macro} {_cnum(runner.dt)}",
        "",
    ]
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


def _header_h(base, guard, sig, fp, graph):
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


def _void_unused(body, holds_output):
    """안 쓰는 인자를 -Wunused-parameter(-Wextra)로부터 막는다.

    ctx의 파라미터·상태 유무로 판정하면 기능축으로 쪼갠 뒤 틀린다 — 조립부는
    파라미터를 하나도 **읽지** 않지만 파티션에 그대로 넘기므로 prm을 쓴다.
    그래서 방출된 본문에 실제로 나오는지로 판정한다.
    """
    text = "\n".join(body)
    out = []
    if not re.search(r"\bprm\b", text):
        out.append("    (void)prm;  /* 파라미터를 참조하지 않는다 */")
    if not holds_output and not re.search(r"\bsta\b", text):
        out.append("    (void)sta;  /* 상태가 없다 */")
    return out


def _part_sig(base, name, part):
    """파티션 함수 시그니처 — 출력이 1개면 값을 반환한다 (그래프 단위 규칙과 같다)."""
    exports = part["exports"]
    head = f"{'double' if len(exports) == 1 else 'void'} {name}_step("
    pad = " " * len(head)
    # 인자 이름은 env가 정한다 — 그래프 입력은 그대로, 경계를 넘어온 신호는 `<id>_y`.
    # 본문이 쓰는 이름과 어긋나면 컴파일이 깨진다
    rest = [f"double {part['env'][u]}" for u in part["imports"]]
    if len(exports) != 1:
        # 이름을 그대로 살린다 — 호출부 지역변수도 정의부 지역변수도 `<id>_y`다
        rest += [f"double *out_{e}" for e in exports]
    first = f"const {base}_params_t *prm, {base}_state_t *sta,"
    if not rest:
        return head + first[:-1] + ")"
    return head + first + _wrap_args(rest, pad)


def _part_h(base, name, fp, part):
    guard = name.upper()
    lines = _banner(base, fp, [f"{part['group']} — 기능축 분할, {len(part['nodes'])}개 블록"])
    lines += [
        f"#ifndef CLAW_{guard}_H",
        f"#define CLAW_{guard}_H",
        "",
        f'#include "{base}_types.h"',
        "",
        f"/* {base}_step이 선언 순서대로 호출한다. 파라미터·상태 구조체는 {base} 전체와",
        " * 공유하므로 리셋·범프리스 웜스타트는 진입점 쪽 계약 그대로다. */",
        f"{_part_sig(base, name, part)};",
        "",
        f"#endif /* CLAW_{guard}_H */",
    ]
    return _text(lines)


def _part_c(base, name, fp, part, body, helpers):
    lines = _banner(base, fp, [f"{part['group']} — 기능축 분할, {len(part['nodes'])}개 블록"])
    lines += [f'#include "{name}.h"', ""]
    lines += _unit_includes(helpers)
    lines.append(_part_sig(base, name, part))
    lines.append("{")
    lines += _void_unused(body, False)
    lines += body
    lines.append("")
    exports = part["exports"]
    if len(exports) == 1:
        lines.append(f"    return {part['env'][exports[0]]};")
    else:
        for out_name in exports:
            lines.append(f"    *out_{out_name} = {part['env'][out_name]};")
    lines.append("}")
    return _text(lines)


def _assembly(base, parts, top_env):
    """조립부 — 파티션을 선언 순서대로 호출한다. 신호 이름이 경계를 넘어 유지된다."""
    lines = []
    for part in parts:
        name = f"{base}_{part['group']}"
        exports = part["exports"]
        lines.append("")
        lines.append(f"    /* ── {part['group']} — {len(part['nodes'])}개 블록 ── */")
        args = ["prm", "sta"] + [top_env[u] for u in part["imports"]]
        if len(exports) == 1:
            call = f"const double {exports[0]}_y = {name}_step({', '.join(args)});"
        else:
            for out_name in exports:
                lines.append(f"    double {out_name}_y;")
            args += [f"&{e}_y" for e in exports]
            call = f"{name}_step({', '.join(args)});"
        lines += _wrap_stmt("    " + call)
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def _impl_c(base, ctx, sig, graph, env, unused, single, includes, body):
    """진입점 — 기능축으로 쪼개면 여기 남는 것은 홀드 분기와 파티션 호출뿐이다."""
    lines = ["/* CLAW 생성 코드 — 손으로 고치지 말 것 (알고리즘, MATLAB _step 대응). */"]
    lines += [f'#include "{base}.h"', ""]
    lines += includes

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
    lines += _void_unused(body, graph.enable is not None)
    if graph.enable is not None:
        lines.append(f"    if ({graph.enable} == 0.0) {{  /* 직전 출력 유지, 상태 동결 */")
        lines.append("        " + ("return sta->hold;" if single else "*out = sta->hold;"))
        if not single:
            lines.append("        return;")
        lines.append("    }")
        lines.append("")
    lines += body
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
