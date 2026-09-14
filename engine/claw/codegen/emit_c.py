"""IR의 C 백엔드 — FCC에 통합되어 그대로 실릴 제어법칙 코드를 생성한다 (02 §1 · 07 §4).

파일 구성은 MATLAB Embedded Coder를 따라 **두 축**으로 나눈다.

역할축: 알고리즘(`.c`) / 파라미터 로더(`_params.c/.h` — 이미지를 rtP 대응 구조체로 적재) /
파라미터·상태·출력 구조체(`_types.h`, rtP·rtDW·rtY 대응) / 진입점(`.h`).

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
구조가 고정(06 §1)이라 자유 배선을 다루는 MATLAB보다 이 점이 유리하다.

**이산 계수는 여기서 계산하지 않는다.** `GraphRunner`가 `init(dt)`를 태운 블록
인스턴스에서 이미 계산된 값(예: `Washout._p = exp(-dt/tau)`)을 그대로 읽어 굽는다 —
이산화 공식이 Python과 C에 두 번 적히면 그 순간 어긋난다. 사설 속성(`_p`)을 읽는
것은 그 때문이며, 대신 dt는 런타임 파라미터가 아니라 `#define`으로 낸다:
계수가 그 dt로 계산됐으므로 dt만 바꾸면 조용히 틀린다. 계수는 파라미터 이미지로 가고, 로더가 이미지
헤더의 dt를 매크로와 비트로 대조한다.

**구조와 값을 가른다 (v1.12, 07 §6).** 생성 C에는 구조만 있다 — 파라미터 값·표 크기는 C 텍스트에 없고
파라미터 이미지(`codegen/param_image.py`)에 있으며, 생성 로더(`{base}_params_load`)가 비행 전에 적재한다.
지문도 둘이다: 구조 지문은 생성 C 텍스트의 해시(같으면 바이트 동일), 파라미터 지문은 이미지 값의 해시.
표준 템플릿 그래프(`fcl/graphs.py` 머리말)와 함께 쓰면 같은 템플릿의 기체들이 C 한 벌을 나눈다.

생성은 **결정적**이다 — 같은 입력이면 바이트 단위로 같은 출력(생성 시각을 넣지
않는다). 산출물을 커밋해 두고 "재생성했더니 달라졌다"가 곧 실제 변경임을
보장하기 위해서다.

한계: 소스가 같아도 개발 머신 컴파일러 ≠ 타깃 컴파일러, 최적화 옵션, 부동소수 폭
차이는 남는다. 타깃에서의 확인(PIL 성격)은 여전히 필요하다.
"""

import math
import re
from collections import namedtuple

import numpy as np

import claw
from claw.blocks.basic import Gain, Product, Saturation, Sum, Switch
from claw.blocks.controllers import PID
from claw.blocks.filters import CommandFilter, Washout
from claw.blocks.lookup import LookupBlock, PolyBlock
from claw.codegen.ir import OPS
from claw.params.paramset import canonical_hash

_EMITTERS = {}
_DISABLERS = {}

# 파일만 돌려주면 공용 런타임을 합집합으로 만들 수 없다 — 쓴 헬퍼를 함께 낸다.
# 지문은 배너 텍스트에도 있지만, 읽는 쪽이 주석을 파싱하게 두지 않는다.
#
# 지문은 둘이다(v1.12, 07 §6): 구조 지문은 생성 C 텍스트의 신원(같으면 바이트 동일), 파라미터 지문은 이미지에 실리는
# 값의 신원이다. layout·values·dt는 파라미터 이미지(`codegen/param_image.py`)의 재료다.
CModule = namedtuple(
    "CModule", "files helpers structure_fingerprint param_fingerprint layout values dt"
)

# 생성 텍스트에 지문·엔진 버전을 넣을 자리 — 구조 지문은 **이 표식이 든 텍스트**를 해시한 뒤 채운다
_FP_TOKEN = "@@CLAW_STRUCTURE_FP@@"
_ENGINE_TOKEN = "@@CLAW_ENGINE@@"

# 파라미터 이미지 형식 — 정본은 07 §6.1이고 C 로더(여기서 생성)와 Python 팩커(param_image.py)가 이 상수를 함께 쓴다
IMAGE_MAGIC = b"CLAWPRM\0"
IMAGE_FORMAT = 1


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


def _cint(v):
    """C 정수 리터럴 — 정수가 아닌 값을 **조용히 절삭하지 않는다**.

    `str(int(3.7))`은 `3`을 내며 오설정을 통과시킨다. `_cnum`이 비유한 값을 거부하는
    것과 같은 자리다 — 리터럴 포매터는 못 내는 값을 만나면 죽어야 한다.
    """
    if isinstance(v, int):
        # float 왕복을 거치면 2^53 위에서 조용히 반올림된다. int()로 한 번 접는 것은
        # bool 때문이다 — isinstance(True, int)라 str(True)가 `True`를 낸다.
        return str(int(v))
    f = float(v)
    if not math.isfinite(f) or f != int(f):
        raise ValueError(f"정수 자료형에 정수가 아닌 값은 탑재 코드로 낼 수 없다: {v}")
    return str(int(f))


# 자료형 → C 리터럴. 지금은 둘뿐이지만 표로 두는 이유는, 타입이 늘 때 여기가 가장 먼저
# 깨지는 자리이기 때문이다 — 분기로 두면 새 타입이 조용히 double 취급을 받는다.
_CTYPE_LITERAL = {
    "double": _cnum,
    "int": _cint,
}


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
    """생성 중 누적 상태 — 파라미터·표·상태 필드·본문 줄·사용된 헬퍼.

    파라미터와 상태 필드는 **실제로 참조될 때만** 등록된다. 스케줄되는 게인처럼
    신호로 들어오는 값은 파라미터 구조체에 남지 않는다 (dead data 방지).

    기능축으로 쪼개도 `params`·`arrays`·`state`는 **그래프 전체로 공유**한다 —
    구조체는 여전히 `{base}_params_t`·`{base}_state_t` 하나이고 파티션 함수들이
    그 포인터를 함께 받는다. 본문·헬퍼·hoisted만 파티션별로 갈린다.

    **값은 C 텍스트에 들어가지 않는다**(v1.12). 등록 행은 (필드, 자료형, 리터럴, 주석) 4항이고 리터럴은 자료형 검사와
    이미지 목록을 위한 것이다. 값 자체는 `values`에 모여 파라미터 이미지가 된다. 표는 배열 몇 개의 묶음이라 `tables`가
    어느 배열이 한 표인지 적는다 — 생성 로더가 표 모양(길이·순증가·다항 정합)을 검사하는 단위다.
    """

    def __init__(self):
        self.params = []  # (field, c_type, c_literal, comment)
        self.arrays = []  # (field, c_type, [literal], comment) — C에는 포인터만 남는다
        self.tables = []  # {"kind": "lookup"|"poly", "id": 노드 id, 역할: 필드명, …}
        self.values = {}  # field → 값 또는 [값] — 파라미터 이미지의 재료 (등록 순서 = 이미지 순서)
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
    def param(self, node_id, field, value, comment="", ctype="double"):
        name = f"{node_id}_{field}"
        lit = _CTYPE_LITERAL[ctype](value)
        if name in self._seen_param:
            # 값뿐 아니라 자료형도 본다 — 타입만 다른 중복은 먼저 등록된 쪽이 조용히
            # 이기고, 그러면 구조체 레이아웃이 등록 순서에 달리게 된다
            if self._seen_param[name] != (ctype, lit):
                raise ValueError(f"파라미터 {name} 중복 등록에 값·자료형 불일치")
        else:
            self._seen_param[name] = (ctype, lit)
            self.params.append((name, ctype, lit, comment))
            self.values[name] = value
        return f"prm->{name}"

    def array(self, node_id, field, values, comment="", ctype="double"):
        """배열 파라미터 — C에는 포인터만 남고 길이는 이미지가 정한다.

        같은 이름에 **다른 값**이 오면 죽는다. 예전에는 이름만 보고 첫 등록을 조용히 남겼다 — 두 표가 한 이름을 나누면
        한쪽 값이 소리 없이 사라지는 자리였다.
        """
        name = f"{node_id}_{field}"
        lits = [_CTYPE_LITERAL[ctype](v) for v in values]
        for prev_name, prev_type, prev_lits, _c in self.arrays:
            if prev_name == name:
                if (prev_type, prev_lits) != (ctype, lits):
                    raise ValueError(f"배열 {name} 중복 등록에 값·자료형 불일치")
                return f"prm->{name}"
        self.arrays.append((name, ctype, lits, comment))
        self.values[name] = list(values)
        return f"prm->{name}"

    def table(self, kind, node_id, **arrays):
        """표 하나 = 배열 몇 개(역할=(값, 주석)) + 길이 정수 필드. → {역할: C 식}.

        길이 필드(`n`·`nseg`·`stride`)는 C 코드에 수로 박히지 않는다 — 로더가 이미지의 배열 길이에서 채운다.
        그래서 표 크기에 코드 상한이 없다(상한은 이미지 길이와 호출자 pool이다).
        """
        if any(t["id"] == node_id for t in self.tables):
            raise ValueError(f"표 {node_id} 중복 등록")
        entry, refs = {"kind": kind, "id": node_id}, {}
        for role, (vals, comment) in arrays.items():
            refs[role] = self.array(node_id, role, vals, comment)
            entry[role] = f"{node_id}_{role}"
        for role, _note in _TABLE_INTS[kind]:
            entry[role] = f"{node_id}_{role}"
            refs[role] = f"prm->{node_id}_{role}"
        self.tables.append(entry)
        return refs

    def st(self, node_id, field, init, comment="", ctype="double"):
        _CTYPE_LITERAL[ctype](init)  # 키·값 모두 등록 시점에 거른다 (init은 raw로 둔다)
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


# 표 종류 → 배열 역할 순서 (이미지의 배열 순서이기도 하다) · 길이 정수 필드
_TABLE_ARRAYS = {"lookup": ("bp", "val"), "poly": ("kn", "coef", "c", "h")}
_TABLE_INTS = {
    "lookup": (("n", "격자점 수 — 이미지의 배열 길이에서 적재"),),
    "poly": (("nseg", "구간 수 — 이미지의 배열 길이에서 적재"),
             ("stride", "구간당 계수 수 — 이미지의 배열 길이에서 적재")),
}


# ── 블록별 에미터 ────────────────────────────────────────────────────────
# 각 함수는 본문 줄을 ctx에 밀어 넣고 이 노드 출력의 C 식을 돌려준다.
# 연산 순서는 Python 구현과 **문자 그대로** 맞춘다 — 배정밀도끼리 비트 일치가
# 목표이므로 `a + b + c`의 결합 순서까지 어긋나면 안 된다.


@_emitter(PID)
def _emit_pid(ctx, node, inst, ins, gains, dt_macro):
    """controllers.py PID — y = clip(kp·e + I + kd·d), I ← 조건부 적분 + clip.

    입력이 둘이면 ins[1]은 축 외부항(감쇠)이고 **판정에만** 들어간다 — y에는 안 더한다.

    **적분 경로는 ki 값과 무관하게 항상 낸다**(v1.12). 예전에는 ki가 상수 0이면 적분기·증분·가드를 접었다 — 그러면 값이
    구조를 바꿔 기체마다 C가 달라진다. Python 정본은 원래 ki = 0이어도 매 스텝 `_i = clip(_i + inc, lo, hi)`를 하므로
    적분기를 두는 쪽이 정본 그대로다. ki = 0인 이미지에서 가드의 `inc > 0.0`·`inc < 0.0`은 **값으로 꺼진(비활성)
    분기**다 — 검증 탭이 목록화하고 커버리지는 파라미터 세트 합산으로 닫는다(verify/autocode.py). kd는 그래프가 0.0으로
    박는 템플릿 상수라 미분항 제거는 여전히 구조다.
    """
    nid, e = node.id, ins[0]
    # 둘째 입력이 있으면 축 외부항(감쇠) — 안티와인드업 **판정에만** 쓴다 (출력은 불변)
    u_ext = ins[1] if len(ins) > 1 else None
    kp = gains.get("kp") or ctx.param(nid, "kp", inst.kp, "비례 게인")
    # 한계도 게인과 같은 포트 규약이다 — 붙으면 신호, 안 붙으면 파라미터 상수.
    # 제어권한 배분이 축 한계를 스텝마다 바꾸는 자리에서 쓴다 (fcl/graphs.py)
    lo = gains.get("out_lo") or ctx.param(nid, "out_lo", inst.out_lo,
                                          "출력·적분기 클램프 하한 (안티와인드업)")
    hi = gains.get("out_hi") or ctx.param(nid, "out_hi", inst.out_hi,
                                          "출력·적분기 클램프 상한 (안티와인드업)")
    clip = ctx.helper("claw_clip")

    i_st = ctx.st(nid, "i", 0.0, "적분기 상태")
    terms = f"{kp} * {e} + {i_st}"
    has_d = "kd" in gains or inst.kd != 0.0
    if has_d:
        kd = gains.get("kd") or ctx.param(nid, "kd", inst.kd, "미분 게인")
        e_prev = ctx.st(nid, "e_prev", 0.0, "직전 오차 (미분항)")
        ctx.line(f"const double {nid}_d = ({e} - {e_prev}) / {dt_macro};")
        terms += f" + {kd} * {nid}_d"
    else:
        # kd = 0 이고 스케줄도 아니면 미분항 전체가 죽은 코드다 — 상태(e_prev)와
        # 매 스텝 나눗셈까지 함께 사라진다 (0.0 곱은 합에 영향이 없다). kd는 그래프가 박는 템플릿 상수다
        ctx.line(f"/* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */")

    raw = ctx.declare(f"{nid}_raw", terms)
    out = ctx.declare(f"{nid}_y", f"{clip}({raw}, {lo}, {hi})")
    ki = gains.get("ki") or ctx.param(nid, "ki", inst.ki, "적분 게인")
    # 조건부 적분 — 포화한 방향으로 더 미는 증분만 버린다. 클램프는 **무조건**이다
    # (범위 밖 웜스타트를 가두는 불변식 — controllers.py PID.step 주석 참조)
    ctx.line(f"double {nid}_inc = {dt_macro} * {ki} * {e};")
    # 판정 기준은 PID 출력이 아니라 축 출력이다 — 감쇠항이 PID 뒤에서 더해져 다시
    # clip되는 축에서 PID만 보면 포화를 절반쯤 놓친다 (controllers.py 실측 주석)
    # 외부항이 있으면 PID 출력(raw)과 축 출력(axis) 중 그 방향으로 더 나간 쪽으로 판정한다(v1.11 — PID 출력이 붙었는데
    # 감쇠가 축을 안쪽으로 끌어도 적분을 멈춘다). controllers.py와 같은 3항이라 NaN에서도 판정이 같고, 가드 줄은
    # 그대로 두 조건 쌍이라 MC/DC 판정 형태(verify/mcdc.py _GUARD)가 안 바뀐다
    if u_ext is None:
        hi_x = lo_x = raw
    else:
        axis = ctx.declare(f"{nid}_axis", f"{raw} + {u_ext}")
        hi_x = ctx.declare(f"{nid}_hi_x", f"({raw} > {axis}) ? {raw} : {axis}")
        lo_x = ctx.declare(f"{nid}_lo_x", f"({raw} < {axis}) ? {raw} : {axis}")
    ctx.line(f"if (({hi_x} > {hi} && {nid}_inc > 0.0) || ({lo_x} < {lo} && {nid}_inc < 0.0)) {{")
    ctx.line(f"    {nid}_inc = 0.0;")
    ctx.line("}")
    ctx.line(f"{i_st} = {clip}({i_st} + {nid}_inc, {lo}, {hi});")
    if has_d:
        ctx.line(f"{ctx.st(nid, 'e_prev', 0.0)} = {e};")
    return out


@_emitter(Washout)
def _emit_washout(ctx, node, inst, ins, gains, dt_macro):
    """filters.py:55 — y = u − x, x ← p·x + (1−p)·u.  p는 엔진이 구운 값."""
    nid, u = node.id, ins[0]
    # 주석에 tau 값을 적지 않는다 — 구조 파일은 기체와 무관하게 바이트 동일해야 한다(값은 이미지 목록에 보인다)
    p = ctx.param(nid, "p", inst._p, f"exp(-dt/tau) — {dt_macro}로 계산")
    omp = ctx.param(nid, "one_minus_p", 1.0 - inst._p, "1 − p")
    x = ctx.st(nid, "x", 0.0, "워시아웃 상태")
    out = ctx.declare(f"{nid}_y", f"{u} - {x}")
    ctx.line(f"{x} = {p} * {x} + {omp} * {u};")
    return out


@_emitter(CommandFilter)
def _emit_command_filter(ctx, node, inst, ins, gains, dt_macro):
    """autopilot.py:60 — 첫 스텝은 현재 측정으로 시드(캡처 거동), 이후 1차 램프."""
    nid, cmd, current = node.id, ins[0], ins[1]
    omp = ctx.param(nid, "one_minus_p", 1.0 - inst._p, "1 − exp(-dt/tau) (tau = 0이면 1 — 통과)")
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
    # 한계 포트 — 붙으면 신호, 안 붙으면 파라미터 상수 (PID와 같은 규약)
    lo = gains.get("lo") or ctx.param(nid, "lo", inst.lo, "하한")
    hi = gains.get("hi") or ctx.param(nid, "hi", inst.hi, "상한")
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
    """1D 테이블 — 격자점·값 배열은 이미지에, C에는 포인터와 점 수 필드만. 외삽은 clip 고정(01 §3.4 [기본값]).

    1점 표(`tables/point.py`)도 같은 경로다 — `claw_lookup1d`가 n < 2면 `val[0]`을 그대로 돌려준다(표준 템플릿의 빈 스케줄
    자리). 점 수가 코드에 없으므로 같은 C가 17점 표와 1점 표를 모두 받는다.
    """
    table = inst.table
    if len(inst.axis_order) != 1:
        raise NotImplementedError(f"{node.id}: 1D 테이블만 지원 (축 {inst.axis_order})")
    if table.extrapolate != "clip":
        raise NotImplementedError(
            f"{node.id}: extrapolate='clip'만 지원 — 받음 {table.extrapolate!r} "
            "(비행 중 예외를 낼 수 없으므로 외삽 금지가 원칙)"
        )
    nid, axis = node.id, inst.axis_order[0]
    ref = ctx.table(
        "lookup", nid,
        bp=([float(v) for v in table.axes[0]], f"{axis} 격자점 (순증가)"),
        val=([float(v) for v in np.asarray(table.data, dtype=float).ravel()], "값"),
    )
    lut = ctx.helper("claw_lookup1d")
    return ctx.declare(f"{nid}_y", f"{lut}({ref['bp']}, {ref['val']}, {ref['n']}, {ins[0]})")


@_emitter(PolyBlock)
def _emit_poly(ctx, node, inst, ins, gains, dt_macro):
    """구간별 다항 게인 스케줄 (01 §3.4 다항 런타임) — knot·계수 배열은 이미지에.

    계수는 tables/poly.py와 같은 u-영역 오름차수이고, 구간별로 최고 차수(stride)에
    맞춰 0을 덧대 평평한 배열로 낸다 — 호너가 0 계수를 지나도 결과 비트가 같다
    (0.0·u + 0.0 = 0.0). 외삽은 clip 고정 (비행 중 예외 금지 원칙, Lookup과 동일).
    구간 수·stride도 C에 수로 박히지 않는다 — 로더가 배열 길이에서 채운다.
    """
    pt = inst.table
    if pt.extrapolate != "clip":
        raise NotImplementedError(
            f"{node.id}: extrapolate='clip'만 지원 — 받음 {pt.extrapolate!r}"
        )
    nid = node.id
    stride = max(len(s["coeffs"]) for s in pt.segments)
    flat = []
    for s in pt.segments:
        flat.extend(list(s["coeffs"]) + [0.0] * (stride - len(s["coeffs"])))
    ref = ctx.table(
        "poly", nid,
        kn=([float(v) for v in pt.knots], "구간 경계 (nseg + 1, 순증가)"),
        coef=(flat, "u-영역 계수 (오름차수, 구간마다 stride개, 0 패딩)"),
        c=([s["c"] for s in pt.segments], "구간 센터 (nseg)"),
        h=([s["h"] for s in pt.segments], "구간 스케일 (nseg, 양수)"),
    )
    fn = ctx.helper("claw_polyeval1d")
    return ctx.declare(
        f"{nid}_y",
        f"{fn}({ref['kn']}, {ref['nseg']}, {ref['coef']}, {ref['stride']}, {ref['c']}, {ref['h']}, {ins[0]})",
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
    # 값이 이미지에 사는 편차(v1.12) — 둘째 인자는 값이 아니라 _emit_one이 등록한 prm 필드 참조다.
    # x + (−c)는 IEEE에서 x − c와 같은 비트라 add_const의 뺄셈 표기와 결과가 같다
    "add_param": lambda a, ref: (f"{a} + {ref}", ()),
    # 값이 이미지에 사는 선택 — Python `a if c != 0.0 else b`와 같은 판정(NaN 플래그는 첫 입력)
    "switch_param": lambda a, b, ref: (f"({ref} != 0.0) ? {a} : {b}", ()),
    # autopilot.py:161 — 1.0 / math.cos(φ) - 1.0
    "sec_minus_1": lambda a: (f"1.0 / cos({a}) - 1.0", ("math",)),
    # autopilot.py:170 — 1.0 / math.cos(φ) ** 2 - 1.0 (Python `**2`는 libm pow)
    "sec2_minus_1": lambda a: (f"1.0 / pow(cos({a}), 2.0) - 1.0", ("math",)),
}

# 값을 이미지에서 읽는 연산 — 이미지 필드 `{id}_c`의 주석
_OP_PARAM_NOTE = {"add_param": "상수 편차", "switch_param": "선택 — 0이 아니면 첫 입력, 0이면 둘째 입력"}

# 어휘가 늘면 여기서 죽는다 — ir_exec.py의 `assert set(_OP_FN) == set(OPS)`와 같은 가드다.
# 없으면 새 연산이 Python으로는 돌고 C 생성에서만 KeyError로 터진다.
assert set(_OP_C) == set(OPS), (
    f"IR 연산 어휘와 C 구현 목록이 어긋남: {sorted(set(OPS) ^ set(_OP_C))}"
)

# 공용 런타임 — 산출물마다 복제하지 않고 claw_rt.c/.h 한 벌로 낸다 (emit_runtime).
# "math"는 진짜 헬퍼가 아니라 <math.h>가 필요하다는 표시다. wrap_pi의 fmod 의존은
# claw_rt.c 안에서 끝나므로, wrap_pi를 **부르는** 파티션은 math.h가 필요 없다.
_HELPER_ORDER = (
    "claw_clip", "claw_wrap_pi", "claw_lookup1d", "claw_polyeval1d",
    # 파라미터 로더 몫(v1.12) — 이미지를 바이트로 읽고(엔디언·정렬 무관) 검사한다
    "claw_rd_u32", "claw_rd_u64", "claw_rd_f64", "claw_f64_bits", "claw_crc32",
    "claw_prm_lookup_bad", "claw_prm_poly_bad",
)
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
    "claw_rd_u32": "uint32_t claw_rd_u32(const unsigned char *p)",
    "claw_rd_u64": "uint64_t claw_rd_u64(const unsigned char *p)",
    "claw_rd_f64": "double claw_rd_f64(const unsigned char *p)",
    "claw_f64_bits": "uint64_t claw_f64_bits(double x)",
    "claw_crc32": "uint32_t claw_crc32(const unsigned char *p, size_t n)",
    "claw_prm_lookup_bad": (
        "int claw_prm_lookup_bad(const double *bp, uint32_t n_bp, uint32_t n_val)"
    ),
    "claw_prm_poly_bad": (
        "int claw_prm_poly_bad(const double *kn, uint32_t n_kn, uint32_t n_coef, uint32_t n_c,\n"
        "                      const double *h, uint32_t n_h)"
    ),
}
_HELPER_DOC = {
    "claw_clip": "[lo, hi] 클램프",
    "claw_wrap_pi": "(-π, π] 래핑 — Python `%`는 나머지가 제수 부호를 따르므로 fmod 뒤 보정한다",
    "claw_lookup1d": (
        "1D 선형 보간, 외삽 clip — tables/table.py:54 interp()와 같은 구간 선택. n < 2면 값 하나(1점 표)"
    ),
    "claw_polyeval1d": (
        "구간별 다항 u-영역 호너, 외삽 clip — tables/poly.py interp()와 같은 구간 선택"
    ),
    "claw_rd_u32": "리틀엔디언 u32 읽기 — 바이트 조립이라 호스트 엔디언·정렬과 무관하다",
    "claw_rd_u64": "리틀엔디언 u64 읽기",
    "claw_rd_f64": "리틀엔디언 IEEE-754 double 읽기 — 비트를 그대로 옮긴다(memcpy, 별칭 규칙 안전)",
    "claw_f64_bits": "double의 비트 표현 — 이미지 dt와 코드 DT 매크로를 비트로 대조한다",
    "claw_crc32": "CRC-32 (IEEE 802.3, zlib.crc32와 같은 값) — 분기 없는 비트 루프",
    "claw_prm_lookup_bad": "절점 표 모양 위반 여부 — 길이 ≥ 1, 격자점·값 길이 일치, 격자점 순증가 (분기 없음)",
    "claw_prm_poly_bad": (
        "다항 표 모양 위반 여부 — 구간 ≥ 1, 경계 = 구간 + 1, 계수 = 구간 × stride, 경계 순증가, 스케일 양수"
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
        "    if (n < 2) { return val[0]; }",
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
    "claw_rd_u32": [
        "    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16)",
        "           | ((uint32_t)p[3] << 24);",
    ],
    "claw_rd_u64": [
        "    return (uint64_t)claw_rd_u32(p) | ((uint64_t)claw_rd_u32(p + 4) << 32);",
    ],
    "claw_rd_f64": [
        "    const uint64_t b = claw_rd_u64(p);",
        "    double x;",
        "    memcpy(&x, &b, sizeof x);",
        "    return x;",
    ],
    "claw_f64_bits": [
        "    uint64_t b;",
        "    memcpy(&b, &x, sizeof b);",
        "    return b;",
    ],
    "claw_crc32": [
        "    uint32_t crc = 0xFFFFFFFFU;",
        "    size_t i;",
        "    int b;",
        "    for (i = 0U; i < n; i++) {",
        "        crc ^= (uint32_t)p[i];",
        "        for (b = 0; b < 8; b++) {",
        "            crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));",
        "        }",
        "    }",
        "    return crc ^ 0xFFFFFFFFU;",
    ],
    "claw_prm_lookup_bad": [
        "    int bad = (n_bp < 1U) | (n_bp != n_val) | (n_bp > 2147483647U);",
        "    uint32_t i;",
        "    for (i = 1U; i < n_bp; i++) {",
        "        bad = bad | (bp[i] <= bp[i - 1U]);",
        "    }",
        "    return bad;",
    ],
    "claw_prm_poly_bad": [
        "    const uint32_t nseg = n_c + (uint32_t)(n_c == 0U);  /* 0으로 나누지 않게 — 0 자체는 아래에서 걸린다 */",
        "    int bad = (n_c < 1U) | (n_c > 2147483647U) | (n_h != n_c) | (n_kn != n_c + 1U)",
        "              | (n_coef < n_c) | (n_coef % nseg != 0U) | (n_coef / nseg > 2147483647U);",
        "    uint32_t i;",
        "    for (i = 1U; i < n_kn; i++) {",
        "        bad = bad | (kn[i] <= kn[i - 1U]);",
        "    }",
        "    for (i = 0U; i < n_h; i++) {",
        "        bad = bad | (h[i] <= 0.0);",
        "    }",
        "    return bad;",
    ],
}
# 헬퍼 → 의존. "math"·"string"·"stdint"는 헬퍼가 아니라 표준 헤더가 필요하다는 표시다. wrap_pi의 fmod 의존은
# claw_rt.c 안에서 끝나므로 wrap_pi를 **부르는** 파티션은 math.h가 필요 없다
_HELPER_NEEDS = {
    "claw_lookup1d": ("claw_clip",),
    "claw_wrap_pi": ("math",),
    "claw_polyeval1d": ("claw_clip",),
    "claw_rd_u32": ("stdint",),
    "claw_rd_u64": ("claw_rd_u32", "stdint"),
    "claw_rd_f64": ("claw_rd_u64", "string", "stdint"),
    "claw_f64_bits": ("string", "stdint"),
    "claw_crc32": ("stdint",),
    "claw_prm_lookup_bad": ("stdint",),
    "claw_prm_poly_bad": ("stdint",),
}
# 로더가 부르는 헬퍼 — 표 종류에 따라 검사 헬퍼가 붙는다
_LOADER_HELPERS = ("claw_rd_u32", "claw_rd_u64", "claw_rd_f64", "claw_f64_bits", "claw_crc32")
_TABLE_CHECK = {"lookup": "claw_prm_lookup_bad", "poly": "claw_prm_poly_bad"}


def _text(lines):
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def _helper_closure(helpers):
    """헬퍼 집합 → 의존까지 닫은 **정해진 순서**의 목록 (표준 헤더 표시는 뺀다).

    한 번 훑기로는 안 닫힌다 — `claw_rd_f64 → claw_rd_u64 → claw_rd_u32`처럼 나중 헬퍼가 끌어온 헬퍼의 의존은 이미
    지나간 자리라 빠진다. 고정점까지 돈다.
    """
    need = {h for h in helpers if h in _HELPER_SIG}
    while True:
        more = {d for h in need for d in _HELPER_NEEDS.get(h, ()) if d in _HELPER_SIG} - need
        if not more:
            break
        need |= more
    return [n for n in _HELPER_ORDER if n in need]


def emit_runtime(helpers):
    """공용 헬퍼 → {claw_rt.h, claw_rt.c}. MATLAB의 `slprj/ert/_sharedutils/` 자리다.

    산출물이 여럿이면 **헬퍼 합집합으로 한 번** 불러야 한다 — 산출물마다 따로 내면
    헬퍼가 적은 쪽이 덮어써 링크가 조용히 깨진다 (`flight/generate.py::build`).

    필요한 것만 낸다. 안 쓰는 헬퍼를 탑재 코드에 두지 않는 것은 IR이 도달 불가
    노드를 막는 것과 같은 이유다(dead code — DO-178C 논점). 산출물의 구조 지문은 자기가 부르는 헬퍼 본문을 함께
    해시하므로(`_structure_fingerprint`) 이 파일에는 지문을 따로 두지 않는다.
    """
    names = _helper_closure(helpers)
    if not names:
        return {}

    def needs(marker):
        return any(marker in _HELPER_NEEDS.get(n, ()) for n in names)

    head = [
        "/* CLAW 생성 코드 — 손으로 고치지 말 것.",
        " * 산출물 공용 런타임 (MATLAB _sharedutils 대응). 산출물이 여럿이어도 이 한 벌을 함께 쓴다 —",
        " * 각 산출물의 구조 지문이 자기가 부르는 헬퍼 본문을 함께 해시한다.",
        " */",
    ]
    h = head + ["#ifndef CLAW_RT_H", "#define CLAW_RT_H", ""]
    if needs("stdint"):
        h += ["#include <stddef.h>", "#include <stdint.h>", ""]
    if "claw_wrap_pi" in names:
        h += ["#define CLAW_PI 3.141592653589793", ""]
    if "claw_crc32" in names:
        h += ["/* 파라미터 이미지 표식 \"CLAWPRM\\0\"을 리틀엔디언 u64로 읽은 값 (07 §6.1) */",
              f"#define CLAW_PRM_MAGIC 0x{int.from_bytes(IMAGE_MAGIC, 'little'):016X}ULL", ""]
    for name in names:
        h += [f"/* {_HELPER_DOC[name]} */", f"{_HELPER_SIG[name]};", ""]
    h += ["#endif /* CLAW_RT_H */"]

    c = head + ['#include "claw_rt.h"', ""]
    std = [inc for marker, inc in (("math", "#include <math.h>"), ("string", "#include <string.h>"))
           if needs(marker)]
    if std:
        c += std + [""]
    if "claw_rd_f64" in names:
        # 이미지는 8바이트 IEEE-754 double이다 — 크기가 다른 타깃은 여기서 컴파일이 깨진다(조용한 절반 읽기 대신)
        c += ["/* double이 8바이트가 아니면 컴파일 오류 — 이미지 형식의 전제 (07 §6.1) */",
              "typedef char claw_f64_is_8_bytes[(sizeof(double) == 8U) ? 1 : -1];", ""]
    for name in names:
        c += [f"/* {_HELPER_DOC[name]} */", _HELPER_SIG[name], "{"]
        c += _HELPER_BODY[name] + ["}", ""]

    return {"claw_rt.h": _text(h), "claw_rt.c": _text(c)}


def _structure_fingerprint(files, helpers):
    """구조 지문 — **생성 C 텍스트 자체**의 해시 (v1.12, 07 §6).

    예전 지문은 그래프·파라미터 값·dt를 해시해서 값만 바뀌어도 움직였고, 거꾸로 에미터 문장이 바뀌어도(v1.11 조건부
    적분 보강) 움직이지 않았다. 구조 지문은 생성된 파일 텍스트(지문·엔진 버전 자리는 표식인 채)와 이 산출물이 부르는
    공용 헬퍼 본문을 해시한다 — 그래서 "구조 지문이 같다"가 곧 "탑재 C가 바이트 단위로 같다"다. dt는 매크로로, 파일
    분할은 파일 목록으로 텍스트에 드러난다. 엔진 버전은 빼 둔다 — 같은 코드를 내는 버전 올림이 구조 변경으로 보이지 않게.
    """
    return canonical_hash({
        "files": dict(files),
        "helpers": {h: [_HELPER_SIG[h], *_HELPER_BODY[h]] for h in _helper_closure(helpers)},
    })


def _param_fingerprint(ctx):
    """파라미터 지문 — 이미지에 실리는 이름·값의 해시. 같은 구조 지문 아래에서 기체·설계값을 가른다.

    값은 `repr`(최단 왕복 표현)로 적는다 — 비트가 다른 두 double이 같은 문자열이 되지 않는다.
    """
    def rep(v):
        return [repr(x) for x in v] if isinstance(v, list) else repr(v)

    return canonical_hash({name: rep(v) for name, v in ctx.values.items()})


def header_bytes(n_arrays):
    """이미지 헤더 크기 — 고정 64바이트 + 배열 길이 u32 × n, 8바이트 경계로 올림 (07 §6.1)."""
    return 64 + (4 * n_arrays + 7) // 8 * 8


def _layout(ctx):
    """이미지 레이아웃 — 스칼라·배열 순서와 표 묶음. 구조에서만 나오므로 구조 지문이 같으면 같다."""
    return {
        "scalars": [{"name": n, "comment": c} for n, _t, _l, c in ctx.params],
        "arrays": [{"name": n, "comment": c} for n, _t, _l, c in ctx.arrays],
        "tables": [dict(t) for t in ctx.tables],
        "header_bytes": header_bytes(len(ctx.arrays)),
    }


def _emit_one(ctx, node, runner, env, dt_macro):
    ins = [env[r] for r in node.inputs]
    if node.kind == "op":
        if node.op in _OP_PARAM_NOTE:
            ref = ctx.param(node.id, "c", node.value, _OP_PARAM_NOTE[node.op])
            expr, needs = _OP_C[node.op](*ins, ref)
        else:
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
    """IR + 초기화된 실행기 → `CModule`.

    헬퍼를 따로 돌려주는 이유: 공용 런타임(`claw_rt`)은 산출물 **전체의 합집합**으로
    한 번 만들어야 해서 그래프 하나만 보고는 낼 수 없다 (`emit_runtime`).

    노드에 `grouped()` 이름표가 붙어 있으면 서브시스템별 `.c/.h`가 함께 나오고
    `{base}.c`에는 조립부만 남는다. 이름표가 없으면 예전처럼 파일 하나다.
    파라미터 값은 파일에 없다 — `{base}_params.c/.h`가 이미지를 적재하는 로더이고, 값은 `CModule.values`로 나가
    `codegen/param_image.py`가 이미지로 싼다. 생성은 결정적이다 (시각 미포함).
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
        f"{base}_types.h": _types_h(base, guard, ctx, graph, single, dt_macro, runner),
        f"{base}.h": _header_h(base, guard, sig, graph),
        f"{base}_params.h": _params_h(base, guard, ctx),
        f"{base}_params.c": _params_c(base, guard, ctx, dt_macro),
    }
    helpers = set(_LOADER_HELPERS) | {_TABLE_CHECK[t["kind"]] for t in ctx.tables}
    for _group, _body, used in ctx.parts:
        helpers |= used

    if graph.partitions:
        top_env = {u: u for u in graph.inputs}
        for part in parts:
            top_env.update({e: f"{e}_y" for e in part["exports"]})
        for (group, body, used), part in zip(ctx.parts, parts):
            name = f"{base}_{group}"
            files[f"{name}.h"] = _part_h(base, name, part)
            files[f"{name}.c"] = _part_c(base, name, part, body, used)
        includes = [f'#include "{base}_{p["group"]}.h"' for p in parts] + [""]
        body = _assembly(base, parts, top_env)
    else:
        top_env = parts[0]["env"]
        includes = _unit_includes(helpers - set(_LOADER_HELPERS) - set(_TABLE_CHECK.values()))
        body = ctx.parts[0][1]

    files[f"{base}.c"] = _impl_c(base, ctx, sig, graph, top_env, unused, single, includes, body)

    # 구조 지문은 표식이 든 텍스트에서 계산하고 나서 채운다 — 지문이 자기 자신을 해시할 수는 없다
    sfp = _structure_fingerprint(files, helpers)
    files = {n: t.replace(_FP_TOKEN, sfp).replace(_ENGINE_TOKEN, claw.__version__)
             for n, t in files.items()}
    return CModule(files, helpers, sfp, _param_fingerprint(ctx), _layout(ctx),
                   dict(ctx.values), runner.dt)


def _banner(base, extra=()):
    lines = [
        "/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).",
        f" * 그래프    : {base}",
        f" * 구조 지문 : {_FP_TOKEN}",
        f" * 엔진      : claw {_ENGINE_TOKEN}",
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


def _types_h(base, guard, ctx, graph, single, dt_macro, runner):
    lines = _banner(base, ["자료형 (MATLAB _types.h 대응)"])
    lines += [f"#ifndef CLAW_{guard}_TYPES_H", f"#define CLAW_{guard}_TYPES_H", ""]
    # dt는 진입점이 아니라 여기 둔다 — 기능축 파티션 헤더가 이 파일만 의존하면 되고,
    # 포함 관계가 DAG로 남는다 (파티션 → _types.h ← 진입점 .h)
    lines += [
        "/* 이 주기로 이산 계수(파라미터 이미지)가 계산되어 있다 — 이미지 헤더의 dt를 로더가",
        " * 이 매크로와 비트로 대조한다. 주기를 바꾸려면 재생성하고 이미지도 다시 만든다. */",
        f"#define {dt_macro} {_cnum(runner.dt)}",
        "",
    ]
    lines.append("/* 파라미터 (MATLAB rtP 대응) — 실제로 참조되는 것만 있다. 값은 코드에 없고 비행 전에")
    lines.append(f" * 파라미터 이미지에서 적재한다({base}_params.h). 표는 포인터와 점 수로 잡혀 크기가 코드에")
    lines.append(" * 박히지 않는다. 게인 스케줄로 신호가 된 값은 여기 남지 않는다. */")
    lines.append("typedef struct {")
    rows = [(f"    {t} {n};", c) for n, t, _l, c in ctx.params]
    comment_of = {n: c for n, _t, _l, c in ctx.arrays}
    type_of = {n: t for n, t, _l, _c in ctx.arrays}
    in_table = set()
    for tab in ctx.tables:
        for role in _TABLE_ARRAYS[tab["kind"]]:
            name = tab[role]
            in_table.add(name)
            rows.append((f"    const {type_of[name]} *{name};", comment_of[name]))
        for role, note in _TABLE_INTS[tab["kind"]]:
            rows.append((f"    int {tab[role]};", note))
    rows += [(f"    const {t} *{n};", c) for n, t, _l, c in ctx.arrays if n not in in_table]
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


def _header_h(base, guard, sig, graph):
    lines = _banner(base)
    lines += [
        f"#ifndef CLAW_{guard}_H",
        f"#define CLAW_{guard}_H",
        "",
        f'#include "{base}_types.h"',
        f'#include "{base}_params.h"',
        "",
        "/* 빌드 요구 — 설계 시뮬과의 비트 일치는 아래 조건에서만 성립한다:",
        " *   · 부동소수 축약(FMA) 금지   예) -ffp-contract=off",
        " *   · 빠른 수학 최적화 금지     예) -ffast-math 를 쓰지 않는다",
        " * 측정: contract=fast로 빌드하면 곱셈-덧셈이 FMA로 합쳐져 중간 반올림이",
        " * 사라지고, 같은 입력에서 최대 2.8e-16 어긋난다 (clang 14, -O2).",
        " * 타깃 컴파일러·최적화 옵션 차이는 별도 확인(PIL)이 필요하다. */",
        "",
        "/* 파라미터는 코드에 없다 — 비행 전에 파라미터 이미지를",
        f" * {base}_params_load로 적재한 구조체를 넘긴다. 구조 지문이 같은 이미지만 받으므로",
        " * 기체·설계값이 바뀌어도 이 코드는 그대로다 (07 §6). */",
        "",
        "/* 상태를 초기값으로 되돌린다. 이산 계수는 이미지에 계산되어 있으므로",
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


# 로더 상태 코드 — 순서가 곧 값이다(0 = 성공). param_image.py가 같은 표로 손상 이미지의 기대 코드를 만든다
PARAM_STATUS = (
    ("OK", "적재 성공"),
    ("E_SHORT", "길이가 헤더보다 짧다"),
    ("E_MAGIC", "CLAW 파라미터 이미지가 아니다"),
    ("E_FORMAT", "형식 버전이 다르다"),
    ("E_HEADER", "헤더 크기가 이 레이아웃과 다르다"),
    ("E_STRUCTURE", "구조 지문이 다르다 — 다른 C 코드용 이미지"),
    ("E_DT", "제어주기가 DT 매크로와 비트로 다르다"),
    ("E_LAYOUT", "스칼라·배열 개수 또는 double 총수가 어긋난다"),
    ("E_LENGTH", "전체 길이가 헤더와 어긋난다"),
    ("E_CRC", "CRC-32 불일치 — 손상"),
    ("E_POOL", "호출자 pool이 double 총수보다 작다"),
    ("E_NONFINITE", "NaN·Inf 값"),
    ("E_TABLE", "표 모양 위반 — 길이·순증가·다항 정합"),
)


def _params_h(base, guard, ctx):
    p = f"{guard}_PARAMS"
    n_arr = len(ctx.arrays)
    load = f"int {base}_params_load("
    lines = _banner(base, ["파라미터 로더 — 이미지 형식 v1 (07 §6.1)"])
    lines += [
        f"#ifndef CLAW_{guard}_PARAMS_H",
        f"#define CLAW_{guard}_PARAMS_H",
        "",
        "#include <stddef.h>",
        "",
        f'#include "{base}_types.h"',
        "",
        "/* 이 로더가 받는 이미지의 모양 — 전부 구조에서 나온다(값·표 길이는 이미지가 정한다). */",
        f"#define {guard}_STRUCTURE_FP 0x{_FP_TOKEN}ULL",
        f"#define {p}_FORMAT {IMAGE_FORMAT}U",
        f"#define {p}_N_SCALARS {len(ctx.params)}U",
        f"#define {p}_N_ARRAYS {n_arr}U",
        f"#define {p}_HEADER_BYTES {header_bytes(n_arr)}U",
        "",
        "/* 적재 상태 — 0이 아니면 *out은 건드리지 않는다 */",
    ]
    lines += _tail_align([(f"#define {p}_{name} {code}", note)
                          for code, (name, note) in enumerate(PARAM_STATUS)])
    lines += [
        "",
        "/* 이미지를 검사하고 double 총수를 낸다 — 호출자가 그만큼의 pool을 마련한다 (동적 할당 없음). */",
        f"int {base}_params_pool_size(const unsigned char *img, size_t len, size_t *n_double);",
        "",
        "/* 이미지 → pool에 값 복사 → *out 조립. 표 필드는 pool을 가리키므로 pool은 *out보다 오래",
        " * 살아야 한다. 이미지 버퍼는 반환 뒤 버려도 된다 (바이트로 읽어 복사 — 정렬·별칭 무관). */",
        f"{load}const unsigned char *img, size_t len, double *pool, size_t pool_n,",
        f"{' ' * len(load)}{base}_params_t *out);",
        "",
        f"#endif /* CLAW_{guard}_PARAMS_H */",
    ]
    return _text(lines)


def _params_c(base, guard, ctx, dt_macro):
    """생성 로더 — 검사는 전부 **단일 조건** if다(verify/mcdc.py 판정 형태 제한). 표 모양 검사는 분기 없는 헬퍼의
    비트 OR로 모아 한 번에 판정한다 — 표마다 if를 두면 표 수만큼 손상 이미지가 있어야 분기 커버리지가 닫힌다."""
    wrong = [(n, t) for n, t, _l, _c in ctx.params + ctx.arrays if t != "double"]
    if wrong:
        raise NotImplementedError(
            f"파라미터 이미지 형식 v{IMAGE_FORMAT}은 double 스칼라·배열만 싣는다 — 받음 {wrong}")
    p = f"{guard}_PARAMS"
    n_arr = len(ctx.arrays)
    index = {name: k for k, (name, _t, _l, _c) in enumerate(ctx.arrays)}

    def check(cond, status, indent="    "):
        return [f"{indent}if ({cond}) {{", f"{indent}    return {p}_{status};", f"{indent}}}"]

    lines = _banner(base, ["파라미터 로더 — 이미지 형식 v1 (07 §6.1)"])
    lines += ["", "#include <string.h>", "", f'#include "{base}_params.h"', '#include "claw_rt.h"', ""]

    # ── 헤더 검사 → double 총수 ──
    lines += [f"int {base}_params_pool_size(const unsigned char *img, size_t len, size_t *n_double)",
              "{", f"    uint64_t total = {p}_N_SCALARS;"]
    if n_arr:
        lines.append("    uint32_t k;")
    lines.append("")
    lines += check(f"len < (size_t){p}_HEADER_BYTES + 8U", "E_SHORT")
    lines += check("claw_rd_u64(img) != CLAW_PRM_MAGIC", "E_MAGIC")
    lines += check(f"claw_rd_u32(img + 8) != {p}_FORMAT", "E_FORMAT")
    lines += check(f"claw_rd_u32(img + 12) != {p}_HEADER_BYTES", "E_HEADER")
    lines += check("claw_rd_u32(img + 60) != 0U", "E_HEADER")  # 예약 — 0이어야 v2가 뜻을 붙일 수 있다
    lines += check(f"claw_rd_u64(img + 16) != {guard}_STRUCTURE_FP", "E_STRUCTURE")
    lines += check(f"claw_rd_u64(img + 40) != claw_f64_bits({dt_macro})", "E_DT")
    lines += check(f"claw_rd_u32(img + 48) != {p}_N_SCALARS", "E_LAYOUT")
    lines += check(f"claw_rd_u32(img + 52) != {p}_N_ARRAYS", "E_LAYOUT")
    if n_arr:
        lines += [f"    for (k = 0U; k < {p}_N_ARRAYS; k++) {{",
                  "        total += claw_rd_u32(img + 64U + 4U * k);",
                  "    }"]
    lines += check("(uint64_t)claw_rd_u32(img + 56) != total", "E_LAYOUT")
    lines += check(f"(uint64_t)len != (uint64_t){p}_HEADER_BYTES + 8U * total + 8U", "E_LENGTH")
    lines += check("claw_crc32(img, len - 8U) != claw_rd_u32(img + (len - 8U))", "E_CRC")
    lines += check("claw_rd_u32(img + (len - 4U)) != 0U", "E_CRC")  # CRC 레코드의 예약 칸
    lines += ["    *n_double = (size_t)total;", f"    return {p}_OK;", "}", ""]

    # ── 적재 ──
    load = f"int {base}_params_load("
    lines += [f"{load}const unsigned char *img, size_t len, double *pool, size_t pool_n,",
              f"{' ' * len(load)}{base}_params_t *out)",
              "{",
              f"    {base}_params_t v;",
              "    size_t total = 0U;",
              "    size_t k;"]
    if n_arr:
        lines += [f"    uint32_t alen[{p}_N_ARRAYS];", f"    size_t off = {p}_N_SCALARS;"]
    if ctx.tables:
        lines.append("    int bad = 0;")
    lines += [f"    const int st = {base}_params_pool_size(img, len, &total);", ""]
    lines += [f"    if (st != {p}_OK) {{", "        return st;", "    }"]
    lines += check("pool_n < total", "E_POOL")
    lines += ["    for (k = 0U; k < total; k++) {",
              f"        pool[k] = claw_rd_f64(img + {p}_HEADER_BYTES + 8U * k);",
              "    }",
              f"    /* NaN·Inf 거부 — x − x는 유한값에서만 0이다 (빠른 수학 금지 빌드 전제, {base}.h) */",
              "    for (k = 0U; k < total; k++) {"]
    lines += check("pool[k] - pool[k] != 0.0", "E_NONFINITE", indent="        ")
    lines += ["    }"]
    if n_arr:
        lines += [f"    for (k = 0U; k < {p}_N_ARRAYS; k++) {{",
                  "        alen[k] = claw_rd_u32(img + 64U + 4U * k);",
                  "    }"]
    lines += ["", "    memset(&v, 0, sizeof v);"]
    for k, (name, _t, _l, _c) in enumerate(ctx.params):
        lines.append(f"    v.{name} = pool[{k}];")
    for k, (name, _t, _l, _c) in enumerate(ctx.arrays):
        lines += [f"    v.{name} = &pool[off];", f"    off += alen[{k}];"]
    for tab in ctx.tables:
        i = {role: index[tab[role]] for role in _TABLE_ARRAYS[tab["kind"]]}
        if tab["kind"] == "lookup":
            lines.append(f"    v.{tab['n']} = (int)alen[{i['bp']}];")
            stmt = (f"bad = bad | claw_prm_lookup_bad(v.{tab['bp']}, alen[{i['bp']}], "
                    f"alen[{i['val']}]);")
        else:
            nseg = f"alen[{i['c']}]"
            lines.append(f"    v.{tab['nseg']} = (int){nseg};")
            lines += _wrap_stmt(f"    v.{tab['stride']} = (int)(alen[{i['coef']}] / "
                                f"({nseg} + (uint32_t)({nseg} == 0U)));")
            stmt = (f"bad = bad | claw_prm_poly_bad(v.{tab['kn']}, alen[{i['kn']}], alen[{i['coef']}], "
                    f"{nseg}, v.{tab['h']}, alen[{i['h']}]);")
        lines += _wrap_stmt("    " + stmt)
    if ctx.tables:
        lines += check("bad != 0", "E_TABLE")
    lines += ["    *out = v;", f"    return {p}_OK;", "}"]
    return _text(lines)


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


def _part_h(base, name, part):
    guard = name.upper()
    lines = _banner(base, [f"{part['group']} — 기능축 분할, {len(part['nodes'])}개 블록"])
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


def _part_c(base, name, part, body, helpers):
    lines = _banner(base, [f"{part['group']} — 기능축 분할, {len(part['nodes'])}개 블록"])
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
            lines.append(f"    sta->{name} = {_CTYPE_LITERAL[ctype](init)};")
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
