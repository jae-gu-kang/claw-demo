"""**제어법칙 구조의 정본** — 이 파일이 제어법칙의 구조 그 자체다 (07 §1).

같은 패키지의 클래스들(`Autopilot`·`Scas`·`Mixer`…)은 파라미터를 들고 여기서
그래프를 만들어 실행할 뿐, 구조를 따로 갖지 않는다. 탑재 C도 같은 그래프에서
나온다. 그래서 Python과 C가 어긋날 수 없고, "둘 다 운용할지"는 나중에 정해도
되는 **백엔드 선택**으로 남는다.

여기 있는 것은 구조뿐이고 계산은 없다. 블록 로직은 M2 `claw.blocks`가, 실행은
`codegen.ir_exec`가, C 생성은 `codegen.emit_c`가 맡는다.

**입력 경계** — 그래프는 쿼터니언·항법속도 같은 원시 상태가 아니라 **이미 계산된
공학량**(θ·φ·ψ·p·q·r·V·α·β·h·ḣ·mach)을 받는다. 실기 FCC에서 오일러각과
에어데이터는 항법·ADC가 주는 값이고, 손으로 쓴 `law.py:89`·`scas.py:104`가 이를
계산하는 것은 우리 시뮬레이터가 원시 상태를 넘기기 때문이다. 그 변환은 통합
계층(우리 쪽 Python)에 남는다.

각 부분은 `*_nodes(prefix, ...)`로 노드 목록을 내고 `*_graph(...)`가 단독 그래프로
감싼다. 최상위 `fcl_graph`는 이들을 **평탄하게 인라인**하되 묶음마다 `grouped()`로
기능축 이름표를 찍는다. IR은 평탄한 채로 남으므로(선언 순서 = 실행 순서) 서브그래프
호출 규약이 생기지 않고 Python 실행에는 아무 영향이 없다. 반면 탑재 C는 그 이름표
경계에서 `fcl_ap.c`·`fcl_scas.c`처럼 서브시스템별로 쪼개져 나온다 — Embedded Coder의
`Function packaging: Nonreusable function`에 해당한다.
"""

from claw.blocks.basic import Gain, Product, Saturation, Sum, Switch
from claw.blocks.controllers import PID
from claw.blocks.filters import CommandFilter, Washout
from claw.blocks.lookup import LookupBlock, PolyBlock
from claw.blocks.base import Block
from claw.codegen import irtypes as it
from claw.codegen.ir import Graph, Node, Op, grouped
from claw.tables import PolyTable
from claw.codegen.ir_exec import GraphRunner

_SCHEDULABLE = ("kp", "ki", "k_rate")
_SCAS_GROUPS = ("pitch", "roll", "yaw")
_AP_GROUPS = ("speed", "alt", "heading")

# 게인 스케줄을 붙일 수 있는 **자리** — 그룹 → 키. 6그룹 × 3키 = 18이 아니라 16이다:
# 속도·헤딩 축은 rate 입력이 상수 0이라 rate 경로 자체가 없어(scas_axis_nodes 참조)
# 그 자리의 k_rate 스케줄은 아무 효과가 없다.
#
# **이 표가 스케줄 자리의 정본이다.** autopilot_nodes의 거부도, law.py의 조립 검증도,
# 서버의 자리 목록(/gains/catalog)도 전부 여기를 읽는다 — 규칙이 여러 군데 적히면
# 반드시 어긋나고, 어긋나는 순간 웹이 "켤 수 있다"고 보여 준 자리가 실행 시점에
# 터진다.
SCHEDULABLE = {
    "pitch": _SCHEDULABLE, "roll": _SCHEDULABLE, "yaw": _SCHEDULABLE,
    "alt": _SCHEDULABLE,  # k_rate는 승강률 댐핑 k_hdot 자리다 (autopilot_nodes)
    "speed": ("kp", "ki"), "heading": ("kp", "ki"),
}


# ── 신호 타입 정본 ────────────────────────────────────────────────────────
# **이름 하나에 타입 하나.** 그래프별 표를 손으로 따로 적으면 같은 `theta`가 그래프마다
# 다른 타입을 갖는 것이 표현 가능해진다 — 일곱 그래프가 이 표를 부분집합으로 뽑아 쓴다.
# 사람 주석에만 있던 단위 지식을 기계가 읽을 수 있게 옮긴 것이고, 단위 철자 자체는
# `irtypes.QUANTITY_UNIT`이 정본이라 여기 다시 적지 않는다 (07 §8).
SIGNAL_TYPES = {
    "nav_valid": it.BOOL,
    # 자세·공력각. 셋을 각도 하나로 묶는 것은 의도적이다 — `lim_cap = Sum(theta,
    # a_margin)`처럼 자세각과 공력 마진을 더하는 정당한 자리가 있다 (07 §10)
    "theta": it.ANGLE, "phi": it.ANGLE, "psi": it.ANGLE,
    "alpha": it.ANGLE, "beta": it.ANGLE,
    "p": it.ANGULAR_RATE, "q": it.ANGULAR_RATE, "r": it.ANGULAR_RATE,
    "V": it.AIRSPEED, "h": it.ALTITUDE, "hdot": it.CLIMB_RATE, "mach": it.MACH,
    # 스케줄 변수 — `schedule.SCHED_VARS`가 축으로 허용하는 셋이다. 여기 빠지면 그 축을
    # 쓴 **정당한 설계**가 그래프 조립에서 죽는다(거짓 양성 = 화면의 500). `alt`는 `h`와
    # 같은 물리량이고 이름만 다르다. `fuel`은 질량인데 질량은 아직 어휘에 없다 — 지어내지
    # 않고 미지정으로 두되 그 이유를 선언에 남긴다
    "alt": it.ALTITUDE,
    "fuel": it.Type(desc="연료 질량 [kg] — 질량 물리량이 아직 어휘에 없다"),
    # 명령은 그것이 명령하는 양과 같은 타입이다 — 오토파일럿이 실제로 빼는 짝이다
    "cmd_speed": it.AIRSPEED, "cmd_alt": it.ALTITUDE, "cmd_heading": it.ANGLE,
    "cmd_pitch": it.ANGLE, "cmd_hdot": it.CLIMB_RATE,
    "speed_on": it.BOOL, "alt_on": it.BOOL, "heading_on": it.BOOL,
    "pitch_on": it.BOOL, "hdot_on": it.BOOL,
    # 축 내부 신호 — 상위 그래프에서는 노드지만 단독 그래프에서는 입력이 된다
    "theta_cmd": it.ANGLE, "phi_cmd": it.ANGLE,
    "att_err": it.ANGLE, "rate": it.ANGULAR_RATE,
    # 타면 명령은 각도, 스로틀은 0~1 정규화 (conventions §5)
    "de": it.ANGLE, "da": it.ANGLE, "dr": it.ANGLE, "thr": it.NORMALIZED,
}


# 게인은 **물리량 미지정(top)이 정답이다** — 하나로 묶으면 거짓이 되기 때문이다.
# 자리마다 차원이 다르고, `kp` 하나만 봐도 셋이다(오차→출력의 비이므로 축이 결정한다):
#
#     축              오차     출력      kp        ki           rate 항
#     SCAS 자세 3축   rad      rad       -         1/s          k_rate: s
#     속도            m/s      0~1       s/m       1/m          (경로 없음)
#     고도            m        rad       rad/m     rad/(m·s)    k_hdot: rad·s/m
#     헤딩            rad      rad       -         1/s          (경로 없음)
#
# 그렇다고 **미선언으로 두면 "아무도 안 봤다"와 구분이 안 된다.** 그래서 물리량 없는
# 실수라고 명시적으로 적는다 — 미지정은 누락이 아니라 결론이라는 것이 선언에 남는다.
# top이라 무엇과도 통일되므로 검사에 거짓 양성을 만들지 않는다 (07 §8).
SCHEDULED_GAIN = it.Type(desc="스케줄 게인 — 자리마다 차원이 달라 물리량을 정할 수 없다")

# 이름은 **`SCHEDULABLE` 정본에서 파생한다** — 자리 목록을 두 벌 적지 않는다.
# 단독 축 그래프는 접두 없이 `kp`·`ki`·`k_rate`를 그대로 포트로 쓴다.
GAIN_PORT_TYPES = (
    {f"g_{g}_{k}": SCHEDULED_GAIN for g, keys in SCHEDULABLE.items() for k in keys}
    | {k: SCHEDULED_GAIN for k in _SCHEDULABLE}
)


def _types_for(names):
    """**그래프 입력은 빠짐없이 선언된다** — 빠지면 이름을 대며 죽는다.

    조용히 건너뛰면 오타 하나가 「선언했는데 아무도 안 보는」 상태로 굳는다. 새 신호를
    들일 때 여기서 막히는 것이 그 앞을 통과해 검사만 반쪽이 되는 것보다 낫다.

    이것은 이 파일의 일곱 그래프에만 거는 규칙이다. **모든** 그래프의 경계를 필수로
    승격하는 것(= `Graph.__init__`이 미선언 입력을 거부)은 저장소 전체가 걸리는 별건이다.
    """
    table = SIGNAL_TYPES | GAIN_PORT_TYPES
    missing = [n for n in names if n not in table]
    if missing:
        raise KeyError(
            f"타입 선언이 없는 신호 {missing} — 정당한 신호면 SIGNAL_TYPES에 적고, "
            "아니면 그래프 입력 쪽이 틀렸다(스케줄 축은 schedule.SCHED_VARS가 정본)"
        )
    return {n: table[n] for n in names}


def _pre(prefix, suffix):
    return f"{prefix}_{suffix}" if prefix else suffix


def stateless_runner(graph):
    """이산화가 필요 없는 그래프의 러너 — dt를 받지 않는 컴포넌트(α 리미터)용.

    dt가 쓰이지 않는다는 것을 **검증한다**. 나중에 필터라도 하나 끼면 여기서
    시끄럽게 터지고, 조용히 잘못된 주기로 이산화되는 일이 없다.
    """
    runner = GraphRunner(graph, 1.0)
    for node_id, inst in runner.instances.items():
        if type(inst)._discretize is not Block._discretize:
            raise AssertionError(
                f"{graph.name}.{node_id}: 이산화가 필요한 블록 — 이 그래프는 dt를 받아야 한다"
            )
    runner.reset()
    return runner


# ── SCAS 한 축 ────────────────────────────────────────────────────────────


def scas_axis_nodes(
    prefix,
    *,
    kp,
    ki,
    k_rate,
    out_lo,
    out_hi,
    err_src,
    rate_src=None,
    damp_src=None,
    washout_tau=0.0,
    gain_ports=None,
    enable=None,
    pid_on_disable=None,
    limit_ports=None,
):
    """SCAS 한 축(`fcl/scas.py:26`)의 노드 목록 → (nodes, 출력 노드 id).

        u = clip( PID(자세오차) + k_rate·rate' , out_lo, out_hi )
        rate' = washout(rate)   (washout_tau > 0일 때 — 요축 댐퍼, 01 §3.1)

    `gain_ports`에 든 게인은 **신호**(스텝마다 주입되는 포트)가 되고 나머지는 상수
    파라미터가 된다 — 게인 스케줄 유무가 구조에 그대로 드러난다.
    `k_rate`가 0이고 스케줄도 아니면 **rate 경로 자체가 생기지 않는다**
    (오토파일럿의 속도·헤딩 축이 그렇다 — 죽은 곱셈을 탑재 코드에 내지 않는다).
    `damp_src`는 rate 항을 바깥에서 이미 계산한 경우 — 고도 축은 그 항이 모드
    영역 안에 있어야 해서(비활성 시 0) 축 밖에서 만들어 넣는다.
    """
    ports = dict(gain_ports or {})
    bad = set(ports) - set(_SCHEDULABLE)
    if bad:
        raise ValueError(f"{prefix}: 스케줄 불가 게인 {sorted(bad)} — 허용 {list(_SCHEDULABLE)}")
    if washout_tau < 0:
        raise ValueError(f"{prefix}: washout_tau는 음수 불가: {washout_tau}")
    if damp_src is not None and rate_src is not None:
        raise ValueError(f"{prefix}: rate_src와 damp_src는 함께 줄 수 없다")

    def nm(suffix):
        return _pre(prefix, suffix)

    common = {"enable": enable} if enable is not None else {}
    nodes = []
    has_rate = damp_src is not None or "k_rate" in ports or k_rate != 0.0
    if has_rate and damp_src is None and rate_src is None:
        raise ValueError(f"{prefix}: rate 경로가 있는데 rate_src가 없다")

    rate_ref = rate_src
    if has_rate and damp_src is None and washout_tau > 0:
        nodes.append(
            Node(nm("wo"), Washout, inputs=(rate_src,), params={"tau": washout_tau}, **common)
        )
        rate_ref = nm("wo")

    # 감쇠항을 **PID보다 먼저** 만든다 — PID가 안티와인드업 판정에 쓸 수 있어야 한다.
    damp = None
    if has_rate:
        damp = damp_src
        if damp is None:
            damp = nm("damp")
            if "k_rate" in ports:
                nodes.append(Node(damp, Product, inputs=(ports["k_rate"], rate_ref), **common))
            else:
                nodes.append(Node(damp, Gain, inputs=(rate_ref,), params={"k": k_rate}, **common))

    # PID의 out_lo/hi와 축 Saturation은 **같은 수치**이고, 이제 __같은 사건__이다.
    #
    # 종전에는 갈렸다: 감쇠항이 PID 뒤에서 더해져 다시 clip되므로 축이 한계에 붙어도
    # PID는 안쪽일 수 있었고, 조건부 적분이 PID 출력만 봐서 그 구간을 통째로 놓쳤다.
    # 데모 미션 실측으로 **전 스텝의 50.2%**가 그 상태였다 — 안티와인드업을 넣고도
    # 절반은 종전대로 와인드업했다. 그래서 감쇠항을 PID의 둘째 입력으로 넣는다.
    # 그 입력은 **판정에만** 쓰인다(controllers.py: y는 그대로 clip(raw)) — 출력이
    # 바뀌면 제어법칙이 바뀌고 기록된 폐루프 수치가 전부 이동하기 때문이다.
    # k_rate가 없는 축(속도·헤딩·승강률)은 외부항이 없어 종전과 완전히 같다.
    nodes.append(
        Node(
            nm("pid"),
            PID,
            inputs=(err_src,) if damp is None else (err_src, damp),
            params={"kp": kp, "ki": ki, "kd": 0.0, "out_lo": out_lo, "out_hi": out_hi},
            gains={**{g: ports[g] for g in ("kp", "ki") if g in ports},
                   **(limit_ports or {})},
            on_disable=pid_on_disable,
            **common,
        )
    )
    last = nm("pid")

    if has_rate:
        # rate 항은 PID 클램프 밖에서 더해지므로 축 출력을 한 번 더 제한한다 (scas.py:11)
        nodes.append(
            Node(nm("sum"), Sum, inputs=(nm("pid"), damp),
                 params={"signs": (1.0, 1.0)}, **common)
        )
        last = nm("sum")

    # 축 최종 클립. 한계 포트가 붙으면 PID와 **같은 값**을 받는다 — 한쪽만 동적이면
    # 출력은 배분을 따르는데 적분 판정은 안 따라, 고치려던 와인드업이 되살아난다
    nodes.append(
        Node(nm("sat"), Saturation, inputs=(last,),
             params={"lo": out_lo, "hi": out_hi},
             gains={"lo": limit_ports["out_lo"], "hi": limit_ports["out_hi"]}
             if limit_ports else {},
             **common)
    )
    return nodes, nm("sat")


# 범용인 것은 **노드 함수**(`scas_axis_nodes`)지 이 빌더가 아니다 — 오토파일럿 속도축은
# 노드 함수를 직접 쓰고 여기를 지나지 않는다. 이 빌더의 생산 소비자는 `fcl/scas.py`의
# `ScasAxis`뿐이고, 그 `PARAM_DEFS`의 `out_lo`·`out_hi` 단위가 **rad**다. 그래서 산출물은
# 타면각이다 — 같은 그래프의 입력 둘을 이미 각도·각속도로 적어 놓고 출력만 비우면
# 앞뒤가 안 맞는다.
AXIS_OUTPUT_TYPES = {"u": it.ANGLE}


def scas_axis_graph(name, *, kp, ki, k_rate, out_lo, out_hi, washout_tau=0.0, scheduled=()):
    """SCAS 한 축을 단독 그래프로 — 증분 A의 수직 슬라이스."""
    sched = tuple(g for g in _SCHEDULABLE if g in scheduled)
    nodes, out = scas_axis_nodes(
        "",  # 단독 그래프라 접두사 없이 wo·pid·damp·sum·sat 그대로
        kp=kp, ki=ki, k_rate=k_rate, out_lo=out_lo, out_hi=out_hi,
        washout_tau=washout_tau, err_src="att_err", rate_src="rate",
        gain_ports={g: g for g in sched},
    )
    outputs = {"u": out}
    return Graph(name, inputs=("att_err", "rate") + sched, nodes=nodes, outputs=outputs,
                 signal_types=_types_for(("att_err", "rate") + sched)
                 | _typed_outputs(outputs, AXIS_OUTPUT_TYPES))


# ── SCAS 3축 ──────────────────────────────────────────────────────────────


# ── 엘레본 제어권한 배분 ──────────────────────────────────────────────────
#
# 델타윙은 피치와 롤이 **같은 네 면을 나눠 쓴다**. 배분이 없으면 믹서가 δe ± δa를
# 자르고, 잘린 사실을 두 축 모두 모른 채 적분한다 — 명령이 기체에 안 닿는데 적분기는
# 계속 찬다. 실측(스트레스 트레이스): 클립 12254건이 **전부 한쪽 면만** 잘렸고
# (좌우 동시 0건), 그때 |δe| 평균 19.93°(한계 20.05°)에 |δa| 평균 1.39°였다.
# 대등한 경합이 아니라 피치가 예산을 다 쓰고 롤의 1.4°가 밀려나는 모양이다.
#
# 배분 원칙은 **실속방지 몫을 먼저, 남은 것을 롤 수요에 따라**:
#
#     R        = clip(k · n(φ_cmd), 0, f·B)       피치 몫을 먼저 뗀다 (n = 1/cos φ_cmd)
#     δa_eff   = clip(δa, ±(B − R))               롤은 그 몫을 못 건드린다
#     δe_lim   = B − |δa_eff|                     피치는 롤이 **실제로 쓴** 나머지 전부
#
# 이 배분 뒤에는 |δe_eff| + |δa_eff| ≤ B가 항상 성립해 믹서 클립이 구조적으로 안
# 걸린다. 믹서의 Saturation은 최종 가드로 남긴다 — 죽은 코드가 되는 것이 곧 배분이
# 제 일을 했다는 뜻이다.
#
# **실속 마진으로 재지 않는다.** 마진은 이미 닿고 나서 움직이는 늦은 지표다 —
# 마진 기반으로 뒀더니 선회 순간 롤이 19°를 가져가 피치에 1°만 남았고, 마진이
# 음수(−0.88°)가 된 뒤에야 되찾아 순항 중 59 m까지 내려갔다(test_landing 회귀).
# 뱅크 **명령**은 하중이 실제로 걸리기 전에 알 수 있어 늦지 않다.
#
# **하중 증분(n−1)이 아니라 하중(n)에 비례한다.** 증분으로 뒀을 때 R은 φ_cmd에
# 대해 2차라 선회 진입(φ_cmd가 아직 작을 때 롤 수요가 최대)에서 사실상 0이었다.
# 실측: 데모 미션에서 최악 스텝의 피치 권한이 0.192°였고 롤이 19.862°를 가져갔다
# — 배분을 넣기 전 믹서 클립이 부족분을 반반 나누던 것(10.03° / 10.03°)보다도
# 피치에 나쁘다. 원칙("실속방지 몫을 **먼저**")과 반대로 동작한 것이다.
# 수평비행의 하중은 0이 아니라 1이므로 n으로 재면 바닥이 저절로 생긴다.
#
# abs·max 연산이 IR에 없지만 필요 없다 — |a| = −min2(a, −a)로 기존 연산만 쓴다.


def _roll_budget_nodes(prefix, *, phi_cmd_src, mach_src, elevon_hi, trim_table,
                       resv_frac):
    """선회 하중 → 피치 몫(R)을 먼저 떼고 남은 것이 롤 예산 [rad].

    R = clip(δe_trim(mach) · n, 0, resv_frac · B),  n = 1/cos φ_cmd (선회 하중배수)

    **하중으로 잰다 — 마진이 아니라.** 마진은 닿고 나서 움직이는 늦은 지표다
    (모듈 주석의 59 m 회귀).

    **증분(n−1)이 아니라 하중(n)이다.** 수평비행의 하중은 0이 아니라 1이다.
    증분으로 두면 R이 φ_cmd에 2차라 선회 진입에서 0이 되는데, 롤 수요가 최대인
    지점이 바로 거기다 — 실측 최악값이 피치 0.192° / 롤 19.862°였다.

    **1g 몫은 상수가 아니라 mach 테이블이다.** 트림 승강타 요구는 동압에 반비례해
    포락선 안에서 0.68°(M0.6) ~ 14.88°(M0.23)로 22배 움직인다. 어떤 상수도
    양 끝을 동시에 못 만족한다 — 저속을 덮으면 M0.6에서 피치가 0.68°만 쓰는데
    14.66°를 묶어 롤 권한 12.2°를 버리고, 고속에 맞추면 저속에서 1g를 못 버틴다.
    표는 α 리미터의 실속 테이블과 같은 취급이다(도메인 표, 게인 슬롯 아님) —
    `SCHEDULABLE`은 손대지 않는다.

    mach는 **필터 없는 원신호**를 쓴다. 게인 스케줄의 필터된 mach를 쓰면 스케줄을
    껐을 때 배분 거동까지 달라진다 — 두 기능이 조용히 엮인다. α 리미터가 실속
    테이블에 원 mach를 쓰는 것과 같은 이유다.

    resv_frac = 예산 중 R이 가져갈 수 있는 최대 비율. 롤에 (1 − resv_frac)·B가
    **항상** 남는다. 이게 없으면 R이 예산 전체를 먹어 롤 권한이 0이 되고, 뱅크를
    되돌릴 수도 없어 하중이 유지되는 자기지속 상태가 된다 — φ_cmd가 크면(예:
    phi_max = 1.2 rad, 생성자가 허용하는 값) 실제로 닿는다.

    φ_cmd는 ±phi_max로 잘려 있고 그 한계가 π/2 미만으로 강제되므로 sec가 발산하지
    않는다 (autopilot_nodes 선회 FF가 기대는 같은 가드).
    """
    def nm(s):
        return _pre(prefix, s)

    if not elevon_hi > 0.0:
        raise ValueError(f"elevon_hi는 양수여야 한다: {elevon_hi}")
    if not 0.0 < resv_frac < 1.0:
        raise ValueError(f"resv_frac은 (0, 1) 필요 — 1이면 롤 권한이 0이 된다: {resv_frac}")
    nodes = [
        Op(nm("load"), "sec_minus_1", inputs=(phi_cmd_src,)),
        Op(nm("n"), "add_const", inputs=(nm("load"),), value=1.0),
        Node(nm("trim"), LookupBlock, inputs=(mach_src,), params={"table": trim_table}),
        Node(nm("resv_raw"), Product, inputs=(nm("trim"), nm("n"))),
        Node(nm("resv"), Saturation, inputs=(nm("resv_raw"),),
             params={"lo": 0.0, "hi": resv_frac * elevon_hi}),
        Node(nm("resv_neg"), Gain, inputs=(nm("resv"),), params={"k": -1.0}),
        Op(nm("roll_hi"), "add_const", inputs=(nm("resv_neg"),), value=elevon_hi),
        Node(nm("roll_lo"), Gain, inputs=(nm("roll_hi"),), params={"k": -1.0}),
    ]
    return nodes, {"out_lo": nm("roll_lo"), "out_hi": nm("roll_hi")}


def _pitch_budget_nodes(prefix, *, da_src, elevon_hi):
    """롤이 **실제로 쓴** δa → 피치에 남는 권한 = elevon_hi − |δa|.

    수요(δa 명령)가 아니라 배분 후 값을 쓴다 — 롤이 못 쓴 몫까지 피치가 갖는다.
    """
    def nm(s):
        return _pre(prefix, s)

    nodes = [
        Node(nm("da_neg"), Gain, inputs=(da_src,), params={"k": -1.0}),
        # −|δa| = min(δa, −δa) — IR에 abs가 없어 min2로 만든다
        Op(nm("da_nabs"), "min2", inputs=(da_src, nm("da_neg"))),
        Op(nm("pitch_hi"), "add_const", inputs=(nm("da_nabs"),), value=elevon_hi),
        Node(nm("pitch_lo"), Gain, inputs=(nm("pitch_hi"),), params={"k": -1.0}),
    ]
    return nodes, {"out_lo": nm("pitch_lo"), "out_hi": nm("pitch_hi")}


def scas3_nodes(prefix, *, pitch, roll, yaw, srcs, gain_ports=None, alloc=None):
    """`fcl/scas.py:102` — (θ_cmd, φ_cmd, 측정) → 믹싱 전 축 명령 (de, da, dr).

    피치는 θ 오차 + q, 롤은 wrap(φ 오차) + p, 요는 **−β** + washout(r)이다
    (요축 입력은 자세 명령이 아니라 선회조화 — scas.py:15).
    """
    ports = gain_ports or {}

    def nm(s):
        return _pre(prefix, s)

    nodes = [
        Node(nm("pitch_err"), Sum, inputs=(srcs["theta_cmd"], srcs["theta"]),
             params={"signs": (1.0, -1.0)}),
        Node(nm("roll_diff"), Sum, inputs=(srcs["phi_cmd"], srcs["phi"]),
             params={"signs": (1.0, -1.0)}),
        # 롤 오차는 ±π 경계(배면 통과)에서 2π 점프하지 않도록 wrap (scas.py:109)
        Op(nm("roll_err"), "wrap_pi", inputs=(nm("roll_diff"),)),
        Node(nm("yaw_err"), Sum, inputs=(srcs["beta"],), params={"signs": (-1.0,)}),
    ]
    # 배분이 붙으면 **롤을 피치보다 먼저** 선언한다 — 피치 한계가 롤이 실제로 쓴 δa에서
    # 나오는데 IR이 전방 참조를 금지하므로, 순서를 바꾸는 것이 루프 없이 그 값을 얻는
    # 유일한 길이다. 축끼리는 독립이라 순서가 결과를 바꾸지 않는다(배분 자체를 빼면).
    limits = {}
    if alloc is not None:
        budget_nodes, limits["roll"] = _roll_budget_nodes(nm("alloc"), **alloc)
        nodes += budget_nodes
    order = (("roll", roll, nm("roll_err"), srcs["p"]),
             ("pitch", pitch, nm("pitch_err"), srcs["q"]),
             ("yaw", yaw, nm("yaw_err"), srcs["r"]))
    if alloc is None:
        order = (order[1], order[0], order[2])  # 종전 순서 (피치·롤·요)

    outs = {}
    for group, cfg, err, rate in order:
        axis_nodes, out = scas_axis_nodes(
            nm(group), err_src=err, rate_src=rate,
            gain_ports=ports.get(group), limit_ports=limits.get(group), **cfg,
        )
        nodes += axis_nodes
        outs[group] = out
        if group == "roll" and alloc is not None:
            pitch_nodes, limits["pitch"] = _pitch_budget_nodes(
                nm("alloc"), da_src=out, elevon_hi=alloc["elevon_hi"])
            nodes += pitch_nodes
    return nodes, outs


# ── 게인 스케줄 ───────────────────────────────────────────────────────────


def gain_schedule_nodes(prefix, *, tables, filter_tau, srcs):
    """`fcl/schedule.py:51` — 스케줄 변수 1차 필터링 후 전 테이블 조회.

    손으로 쓴 코드는 mach·alt·fuel 필터를 **항상 셋 다** 돌리지만, 실제로 쓰이는 축의
    필터만 만든다 — 아무도 읽지 않는 상태를 탑재 코드에 두지 않는다. 출력은 같다.
    게인 이름 "그룹.게인"의 점은 C 식별자가 아니므로 밑줄로 바꾼다.
    """
    def nm(s):
        return _pre(prefix, s)

    used = sorted({ax for tab in tables.values() for ax in tab.axis_names})
    missing = [ax for ax in used if ax not in srcs]
    if missing:
        raise ValueError(f"{prefix}: 스케줄 변수 소스 없음 {missing}")

    nodes = []
    filt = {}
    for axis in used:
        # step(v, v) — 명령과 측정이 같은 신호다(첫 스텝 무과도 시드, schedule.py:53)
        node_id = nm(f"f_{axis}")
        nodes.append(
            Node(node_id, CommandFilter, inputs=(srcs[axis], srcs[axis]),
                 params={"tau": filter_tau})
        )
        filt[axis] = node_id

    outs = {}
    for name, tab in sorted(tables.items()):
        group, _, key = name.partition(".")
        node_id = nm(f"{group}_{key}")
        # 다항 테이블은 구간 다항 평가 블록으로 — 격자 보간과 C 헬퍼가 다르다
        # (claw_lookup1d vs claw_polyeval1d). 같은 자리에 어느 표현이든 올 수 있고,
        # 선택이 곧 형상이다 (01 §3.4 다항 채택).
        #
        # 판정은 **타입으로** 한다. 속성 이름(kind)으로 고르면 오탈자·미태깅 표가
        # 조용히 LookupBlock으로 흘러 Python에서는 돌다가 C 생성 시점에 맨
        # AttributeError로 죽는다 — 무엇이 잘못됐는지가 안 보이는 자리다
        # (fcl/schedule.py의 GainSchedule 타입 검사와 같은 좁기).
        block = PolyBlock if isinstance(tab, PolyTable) else LookupBlock
        nodes.append(
            Node(node_id, block, inputs=(filt[tab.axis_names[0]],),
                 params={"table": tab})
        )
        outs.setdefault(group, {})[key] = node_id
    return nodes, outs


# ── 오토파일럿 ────────────────────────────────────────────────────────────


def autopilot_nodes(
    prefix,
    *,
    srcs,
    gain_ports=None,
    kp_spd, ki_spd, tau_spd,
    kp_alt, ki_alt, k_hdot, tau_alt,
    kp_hdg, ki_hdg, tau_hdg,
    kp_vs, ki_vs, tau_vs,
    theta_lo, theta_hi, phi_max,
    k_pitch_turn, k_thr_turn,
):
    """`fcl/autopilot.py:136` — 속도·고도·헤딩 PI + 명령필터 + 선회 피드포워드.

    **모드 on/off가 enable 영역으로 드러난다.** 축이 꺼지면 명령필터는 측정을
    추적하고(`reset_to`), 헤딩 적분기는 소거된다(재관여 시 잔존 뱅크 킥 방지).
    반면 고도·속도 축의 PI는 **꺼져도 계속 돈다** — 오차 0을 물려 적분기를 유지하는
    것이 트림 홀드이기 때문이다(autopilot.py:160·169). 그래서 그 두 축은 PI가
    영역 밖에 있고, 영역 안의 오차·댐핑 노드가 비활성 시 0을 내보낸다.

    선회 FF 계수가 0이면 항과 그 뒤 재클램프가 통째로 사라진다 — 축 포화가 이미
    같은 한계로 잘라 두었으므로 결과가 같고, 죽은 항을 탑재 코드에 내지 않는다.
    """
    ports = gain_ports or {}

    # 스케줄 불가 자리는 조용히 무시하지 않고 **여기서** 거부한다 — 축을 조립하다
    # 걸리면 "rate 경로가 있는데 rate_src가 없다" 같은 내부 사정으로 터져서, 무엇을
    # 잘못 골랐는지가 안 보인다. 허용 자리는 SCHEDULABLE이 정본이다.
    for group in _AP_GROUPS:
        bad = sorted(set(ports.get(group) or ()) - set(SCHEDULABLE[group]))
        if bad:
            raise ValueError(
                f"{prefix or 'autopilot'}: {group} 축에 스케줄 불가 게인 {bad} — "
                f"허용 {list(SCHEDULABLE[group])} (rate 입력이 없는 축이다)"
            )

    def nm(s):
        return _pre(prefix, s)

    nodes = []

    # ── 헤딩: 축 전체가 영역 안 (꺼지면 φ_cmd = 0, 수평 유지) ──
    hdg_en = {"enable": srcs["heading_on"]}
    nodes += [
        Node(nm("fpsi"), CommandFilter, inputs=(srcs["cmd_heading"], srcs["psi"]),
             params={"tau": tau_hdg, "angle": True},
             on_disable={"x": srcs["psi"]}, **hdg_en),
        Node(nm("psi_diff"), Sum, inputs=(nm("fpsi"), srcs["psi"]),
             params={"signs": (1.0, -1.0)}, **hdg_en),
        Op(nm("hdg_err"), "wrap_pi", inputs=(nm("psi_diff"),), **hdg_en),
    ]
    hdg_nodes, phi_cmd = scas_axis_nodes(
        nm("hdg"), kp=kp_hdg, ki=ki_hdg, k_rate=0.0, out_lo=-phi_max, out_hi=phi_max,
        err_src=nm("hdg_err"), gain_ports=ports.get("heading"),
        enable=srcs["heading_on"],
        pid_on_disable={"i": 0.0},  # 재관여 시 잔존 뱅크 킥 방지 (autopilot.py:152)
    )
    nodes += hdg_nodes

    # ── 고도: 필터·오차·댐핑만 영역 안, PI는 밖(적분기 유지 = 트림 θ 홀드) ──
    alt_en = {"enable": srcs["alt_on"]}
    alt_kr = (ports.get("alt") or {}).get("k_rate")
    nodes += [
        Node(nm("fh"), CommandFilter, inputs=(srcs["cmd_alt"], srcs["h"]),
             params={"tau": tau_alt}, on_disable={"x": srcs["h"]}, **alt_en),
        Node(nm("alt_err"), Sum, inputs=(nm("fh"), srcs["h"]),
             params={"signs": (1.0, -1.0)}, **alt_en),
        # 승강률 댐핑은 모드 영역 안에 있어야 한다 — 축이 꺼지면 rate 항이 0이어야
        # 적분기 홀드가 성립한다(autopilot.py:160의 `_alt.step(0.0, 0.0)`)
        Node(nm("alt_damp"), Product, inputs=(alt_kr, srcs["hdot"]), **alt_en)
        if alt_kr
        else Node(nm("alt_damp"), Gain, inputs=(srcs["hdot"],),
                  params={"k": k_hdot}, **alt_en),
    ]
    alt_nodes, theta_axis = scas_axis_nodes(
        nm("alt"), kp=kp_alt, ki=ki_alt, k_rate=k_hdot, out_lo=theta_lo, out_hi=theta_hi,
        err_src=nm("alt_err"), damp_src=nm("alt_damp"), gain_ports=ports.get("alt"),
    )
    nodes += alt_nodes

    # ── 승강률 축: 고도와 같은 구조, 물리량만 다르다 (ḣ_ref − ḣ) PI → θ ──
    # 접근 강하율·플레어처럼 "어느 고도"가 아니라 "얼마나 빨리 내려가는가"를 잡아야
    # 하는 구간용이다. 고도축과 같은 θ 한계로 포화한다.
    vs_en = {"enable": srcs["hdot_on"]}
    nodes += [
        Node(nm("fvs"), CommandFilter, inputs=(srcs["cmd_hdot"], srcs["hdot"]),
             params={"tau": tau_vs}, on_disable={"x": srcs["hdot"]}, **vs_en),
        Node(nm("vs_err"), Sum, inputs=(nm("fvs"), srcs["hdot"]),
             params={"signs": (1.0, -1.0)}, **vs_en),
    ]
    # 승강률 축은 게인 스케줄 자리로 열지 않는다 — SCHEDULABLE을 늘리면 서버
    # 자리 목록·웹 UI·탑재 코드까지 파급된다. 필요해지면 그때 한 번에 연다.
    vs_nodes, vs_axis = scas_axis_nodes(
        nm("vs"), kp=kp_vs, ki=ki_vs, k_rate=0.0, out_lo=theta_lo, out_hi=theta_hi,
        err_src=nm("vs_err"),
    )
    nodes += vs_nodes

    # ── θ 출처 선택: pitch > hdot > alt ──
    # 셋은 **배타**라(모드 구성 시 validate_longitudinal이 거부) 순서가 우선순위가
    # 아니라 단순 선택이다. 셋 다 꺼지면 고도축이 남아 오차 0을 물고 트림 θ를
    # 유지한다 — 종전 alt_on=False 거동 그대로다.
    # 피치 축은 PI가 없다: θ를 직접 지령하는 것이라 통과시키고 축 한계로만 자른다.
    nodes += [
        Node(nm("pitch_sat"), Saturation, inputs=(srcs["cmd_pitch"],),
             params={"lo": theta_lo, "hi": theta_hi}),
        Node(nm("theta_vs"), Switch, inputs=(vs_axis, srcs["hdot_on"], theta_axis),
             params={"threshold": 0.5}),
        Node(nm("theta_src"), Switch,
             inputs=(nm("pitch_sat"), srcs["pitch_on"], nm("theta_vs")),
             params={"threshold": 0.5}),
    ]
    theta_axis = nm("theta_src")

    theta_out = theta_axis
    if k_pitch_turn != 0.0:  # 01 §3.3.1 델타윙 선회 고도손실 보상
        nodes += [
            Op(nm("ff_p_raw"), "sec_minus_1", inputs=(phi_cmd,)),
            Node(nm("ff_p"), Gain, inputs=(nm("ff_p_raw"),), params={"k": k_pitch_turn}),
            Node(nm("theta_ff"), Sum, inputs=(theta_axis, nm("ff_p")),
                 params={"signs": (1.0, 1.0)}),
            Node(nm("theta_out"), Saturation, inputs=(nm("theta_ff"),),
                 params={"lo": theta_lo, "hi": theta_hi}),
        ]
        theta_out = nm("theta_out")

    # ── 속도: 고도와 같은 구조 (적분기 유지 = 트림 스로틀 홀드) ──
    spd_en = {"enable": srcs["speed_on"]}
    nodes += [
        Node(nm("fv"), CommandFilter, inputs=(srcs["cmd_speed"], srcs["V"]),
             params={"tau": tau_spd}, on_disable={"x": srcs["V"]}, **spd_en),
        Node(nm("spd_err"), Sum, inputs=(nm("fv"), srcs["V"]),
             params={"signs": (1.0, -1.0)}, **spd_en),
    ]
    spd_nodes, thr_axis = scas_axis_nodes(
        nm("spd"), kp=kp_spd, ki=ki_spd, k_rate=0.0, out_lo=0.0, out_hi=1.0,
        err_src=nm("spd_err"), gain_ports=ports.get("speed"),
    )
    nodes += spd_nodes

    thr_out = thr_axis
    if k_thr_turn != 0.0:
        nodes += [
            Op(nm("ff_t_raw"), "sec2_minus_1", inputs=(phi_cmd,)),
            Node(nm("ff_t"), Gain, inputs=(nm("ff_t_raw"),), params={"k": k_thr_turn}),
            Node(nm("thr_ff"), Sum, inputs=(thr_axis, nm("ff_t")),
                 params={"signs": (1.0, 1.0)}),
            Node(nm("thr_out"), Saturation, inputs=(nm("thr_ff"),),
                 params={"lo": 0.0, "hi": 1.0}),
        ]
        thr_out = nm("thr_out")

    return nodes, {"theta_cmd": theta_out, "phi_cmd": phi_cmd, "throttle": thr_out}


AP_INPUTS = ("psi", "h", "hdot", "V", "cmd_heading", "cmd_alt", "cmd_speed",
             "cmd_pitch", "cmd_hdot",
             "heading_on", "alt_on", "speed_on", "pitch_on", "hdot_on")

# 단독 실행 그래프가 게인 포트를 갖는 이유: `Autopilot.step(gains=…)`이 스텝마다
# 임의 조합을 덮어쓸 수 있어서다. 조합마다 그래프를 새로 만들 수는 없으므로 전부
# 포트로 두고, 덮어쓰기가 없으면 인스턴스 값을 그대로 흘려보낸다 — 값이 같으므로
# 결과도 같다. 반면 **최상위 조립**은 스케줄 테이블이 실제로 있는 게인만 포트로
# 두므로(그 외는 상수) 탑재 코드에 죽은 신호가 생기지 않는다.
AP_PORTS = {"speed": ("kp", "ki"), "alt": ("kp", "ki", "k_rate"), "heading": ("kp", "ki")}
# 그룹·게인 → Autopilot 파라미터 이름 (속도 축의 kp는 kp_spd)
AP_PARAM = {
    ("speed", "kp"): "kp_spd", ("speed", "ki"): "ki_spd",
    ("alt", "kp"): "kp_alt", ("alt", "ki"): "ki_alt", ("alt", "k_rate"): "k_hdot",
    ("heading", "kp"): "kp_hdg", ("heading", "ki"): "ki_hdg",
}


def ap_port_inputs():
    return tuple(f"g_{g}_{k}" for g, keys in AP_PORTS.items() for k in keys)


# 오토파일럿·SCAS3의 산출물도 그래프 밖으로 나가는 값이다 — 게인에서 없앤 「낳는
# 자리에선 무명, 받는 자리에선 유명」을 여기서도 닫는다.
#
# **값은 정본에서 파생한다.** 출력명은 신호명의 별칭일 뿐이라 타입을 다시 적으면 같은
# `de`가 그래프마다 다른 타입을 갖는 것이 도로 표현 가능해진다 — 이 파일 머리말이
# 금지한 바로 그 상태다. 표가 하는 일은 **철자가 어긋나는 자리를 잇는 것**뿐이다
# (출력명 `throttle` ↔ 신호명 `thr`).
AP_OUTPUT_TYPES = {"theta_cmd": SIGNAL_TYPES["theta_cmd"],
                   "phi_cmd": SIGNAL_TYPES["phi_cmd"],
                   "throttle": SIGNAL_TYPES["thr"]}
SCAS3_OUTPUT_TYPES = {k: SIGNAL_TYPES[k] for k in ("de", "da", "dr")}


def autopilot_graph(name="autopilot", *, ports=False, **params):
    """오토파일럿 단독 그래프. ports=True면 게인이 신호(스텝별 덮어쓰기 가능)."""
    inputs = AP_INPUTS + (ap_port_inputs() if ports else ())
    gain_ports = (
        {g: {k: f"g_{g}_{k}" for k in keys} for g, keys in AP_PORTS.items()}
        if ports
        else None
    )
    nodes, outs = autopilot_nodes(
        "", srcs={u: u for u in inputs}, gain_ports=gain_ports, **params
    )
    return Graph(name, inputs=inputs, nodes=nodes, outputs=outs,
                 signal_types=_types_for(inputs) | _typed_outputs(outs, AP_OUTPUT_TYPES))


SCAS3_INPUTS = ("theta_cmd", "phi_cmd", "theta", "phi", "beta", "p", "q", "r")


def scas3_port_inputs():
    return tuple(f"g_{g}_{k}" for g in _SCAS_GROUPS for k in _SCHEDULABLE)


def scas3_graph(name="scas", *, pitch, roll, yaw, ports=False):
    """SCAS 3축 단독 그래프 — 게인 포트 이유는 `autopilot_graph`와 같다."""
    inputs = SCAS3_INPUTS + (scas3_port_inputs() if ports else ())
    gain_ports = (
        {g: {k: f"g_{g}_{k}" for k in _SCHEDULABLE} for g in _SCAS_GROUPS}
        if ports
        else None
    )
    nodes, outs = scas3_nodes(
        "", pitch=pitch, roll=roll, yaw=yaw,
        srcs={u: u for u in inputs}, gain_ports=gain_ports,
    )
    outputs = {"de": outs["pitch"], "da": outs["roll"], "dr": outs["yaw"]}
    return Graph(name, inputs=inputs, nodes=nodes, outputs=outputs,
                 signal_types=_types_for(inputs)
                 | _typed_outputs(outputs, SCAS3_OUTPUT_TYPES))


def _sched_gain_types(groups):
    """스케줄이 낳은 게인 노드 — 받는 포트와 같은 `SCHEDULED_GAIN`이다."""
    return {nid: SCHEDULED_GAIN for keys in groups.values() for nid in keys.values()}


def gain_schedule_graph(name="gain_schedule", *, tables, filter_tau):
    """게인 스케줄 단독 그래프 — 실제로 쓰이는 스케줄 변수만 입력이 된다."""
    used = sorted({ax for tab in tables.values() for ax in tab.axis_names})
    nodes, groups = gain_schedule_nodes(
        "", tables=tables, filter_tau=filter_tau, srcs={ax: ax for ax in used}
    )
    outputs = {f"{g}_{k}": nid for g, keys in groups.items() for k, nid in keys.items()}
    # 게인을 **낳는 쪽**도 받는 쪽(`GAIN_PORT_TYPES`)과 같은 타입이다 — 안 붙이면 같은
    # 게인이 낳는 자리에선 무명, 받는 자리에선 유명해진다
    return Graph(name, inputs=tuple(used), nodes=nodes, outputs=outputs,
                 signal_types=_types_for(used) | _sched_gain_types(groups))


# ── α 리미터 ──────────────────────────────────────────────────────────────


def alpha_limiter_nodes(prefix, *, stall_table, margin, srcs):
    """`fcl/limiter.py:44` — θ_cmd ≤ θ + (α_max − α), α_max = α_stall(mach) − margin.

    실속 마진(α_max − α)은 엔벨로프 감시(02 §6.1)가 소비하므로 함께 낸다.
    """
    def nm(s):
        return _pre(prefix, s)

    nodes = [
        Node(nm("stall"), LookupBlock, inputs=(srcs["mach"],), params={"table": stall_table}),
        Op(nm("alpha_max"), "add_const", inputs=(nm("stall"),), value=-margin),
        Node(nm("a_margin"), Sum, inputs=(nm("alpha_max"), srcs["alpha"]),
             params={"signs": (1.0, -1.0)}),
        Node(nm("cap"), Sum, inputs=(srcs["theta"], nm("a_margin")),
             params={"signs": (1.0, 1.0)}),
        Op(nm("theta_lim"), "min2", inputs=(srcs["theta_cmd"], nm("cap"))),
        Op(nm("active"), "gt", inputs=(srcs["theta_cmd"], nm("cap"))),
    ]
    return nodes, {
        "theta_cmd": nm("theta_lim"),
        "active": nm("active"),
        "alpha_margin": nm("a_margin"),
    }


LIMITER_INPUTS = ("theta_cmd", "theta", "alpha", "mach")


def _limiter_types(prefix):
    """α 리미터 **내부** 신호 — 전부 각도이고 `active` 하나만 불리언이다.

    두 가지를 선언으로 못박는 자리다.

    첫째, `cap = Sum(theta, a_margin)`는 **자세각 + 공력 마진**이다. ANGLE을
    자세각/공력각/타면각으로 쪼개고 싶은 유혹의 정당한 반례이고(07 §10), 쪼개는
    순간 이 한 줄이 거부된다 — 카탈로그가 거친 이유가 주석이 아니라 선언이 된다.

    둘째, `active`는 `gt`가 낳은 **진짜 불리언**인데 `limiter_active` 출력으로
    `double`에 실려 나간다(07 §7). Phase 3에서 native 타입으로 내릴 때 어느 신호를
    내리는지가 여기 이미 적혀 있다 — 그때 찾아다니지 않는다.
    """
    angles = ("stall", "alpha_max", "a_margin", "cap", "theta_lim")
    return {_pre(prefix, s): it.ANGLE for s in angles} | {_pre(prefix, "active"): it.BOOL}


def alpha_limiter_graph(name="alpha_limiter", *, stall_table, margin):
    nodes, outs = alpha_limiter_nodes(
        "", stall_table=stall_table, margin=margin, srcs={u: u for u in LIMITER_INPUTS}
    )
    return Graph(name, inputs=LIMITER_INPUTS, nodes=nodes, outputs=outs,
                 signal_types=_types_for(LIMITER_INPUTS) | _limiter_types(""))


# ── 엘레본 믹싱 (순수·무상태) ────────────────────────────────────────────


def mixer_nodes(prefix, *, elevon_lo, elevon_hi, rudder_lo, rudder_hi, k_diff_thr, srcs):
    """`fcl/mixer.py:44` — 축 명령 + 집합 스로틀 → 타면·추력 명령.

    SurfaceCommand의 elevon 4면은 [내좌, 외좌, 내우, 외우]이고 내/외측이 1:1 고정
    믹싱이라 좌·우 두 값이면 재구성된다 — 배열을 나르는 대신 좌우만 낸다.
    차동추력은 **클램프된 실 러더** 기준이다(mixer.py:49) — 러더가 내지 못하는
    명령에 추력이 반응하지 않도록.
    """
    def nm(s):
        return _pre(prefix, s)

    lim = {"lo": elevon_lo, "hi": elevon_hi}
    de, da, dr, thr = srcs["de"], srcs["da"], srcs["dr"], srcs["thr"]
    nodes = [
        Node(nm("sum_l"), Sum, inputs=(de, da), params={"signs": (1.0, 1.0)}),
        Node(nm("elevon_l"), Saturation, inputs=(nm("sum_l"),), params=lim),
        Node(nm("sum_r"), Sum, inputs=(de, da), params={"signs": (1.0, -1.0)}),
        Node(nm("elevon_r"), Saturation, inputs=(nm("sum_r"),), params=lim),
        Node(nm("rudder"), Saturation, inputs=(dr,),
             params={"lo": rudder_lo, "hi": rudder_hi}),
        Node(nm("diff"), Gain, inputs=(nm("rudder"),), params={"k": k_diff_thr}),
        Node(nm("thr_l_raw"), Sum, inputs=(thr, nm("diff")), params={"signs": (1.0, -1.0)}),
        Node(nm("thr_l"), Saturation, inputs=(nm("thr_l_raw"),), params={"lo": 0.0, "hi": 1.0}),
        Node(nm("thr_r_raw"), Sum, inputs=(thr, nm("diff")), params={"signs": (1.0, 1.0)}),
        Node(nm("thr_r"), Saturation, inputs=(nm("thr_r_raw"),), params={"lo": 0.0, "hi": 1.0}),
    ]
    return nodes, {
        "elevon_l": nm("elevon_l"), "elevon_r": nm("elevon_r"), "rudder": nm("rudder"),
        "throttle_l": nm("thr_l"), "throttle_r": nm("thr_r"),
    }


MIXER_INPUTS = ("de", "da", "dr", "thr")


# 믹서 산출물은 **그래프 밖으로 나가는 값**이다(`SurfaceCommand`, 07 §7). 내부 노드와
# 달리 추론으로 얻는 것보다 선언으로 못박는 쪽이 맞다 — 그리고 여기가 `verify/units.py`가
# 기록한 사고 자리다: 믹서 인자 순서가 뒤집혔는데 "전부 double이라" 컴파일이 통과해
# δe·δa를 맞바꾼 채 대조했다. 타입 시스템을 만든 동기가 된 경계가 미선언이면 앞뒤가 안 맞는다.
MIXER_OUTPUT_TYPES = {
    "elevon_l": it.ANGLE, "elevon_r": it.ANGLE, "rudder": it.ANGLE,
    "throttle_l": it.NORMALIZED, "throttle_r": it.NORMALIZED,
}


def _typed_outputs(out_map, types):
    """출력 이름표를 **노드 id 선언**으로 옮긴다 — 접두가 붙어도 그대로 따라간다.

    선언은 노드 id에 붙는다(출력명은 별칭일 뿐이다). 그래서 이름표 하나를 두고
    단독 그래프와 최상위 조립이 함께 쓴다 — 접두마다 표를 새로 적지 않는다.

    입력(`_types_for`)과 **같은 규약으로 죽는다**. 관대하게 두면 경계 출력이 하나
    늘었을 때 아무도 말하지 않고 조용히 미선언으로 남는다 — 오늘은 거를 것이 없지만
    다음 확장이 바로 그 구멍을 밟는다(출력명 `throttle` vs 표의 `thr`처럼).
    """
    missing = [n for n in out_map if n not in types]
    if missing:
        raise KeyError(f"타입 선언이 없는 경계 출력 {missing} — 그 그래프의 출력표에 적는다")
    return {nid: types[name] for name, nid in out_map.items()}


def mixer_graph(name="mixer", **params):
    nodes, outs = mixer_nodes("", srcs={u: u for u in MIXER_INPUTS}, **params)
    return Graph(name, inputs=MIXER_INPUTS, nodes=nodes, outputs=outs,
                 signal_types=_types_for(MIXER_INPUTS) | _typed_outputs(outs, MIXER_OUTPUT_TYPES))


# ── 최상위 조립 ───────────────────────────────────────────────────────────

FCL_INPUTS = (
    "nav_valid",
    "theta", "phi", "psi", "p", "q", "r", "V", "alpha", "beta", "h", "hdot", "mach",
    "cmd_speed", "cmd_alt", "cmd_heading", "cmd_pitch", "cmd_hdot",
    "speed_on", "alt_on", "heading_on", "pitch_on", "hdot_on",
)


def fcl_graph(
    name="fcl",
    *,
    autopilot,
    scas_axes,
    mixer,
    stall_table=None,
    alpha_margin=0.05,
    alloc_trim_table=None,
    alloc_resv_frac=0.7,
    gain_tables=None,
    filter_tau=0.5,
):
    """`fcl/law.py:85` 최상위 — 게인 스케줄 → 오토파일럿 → α 리미터 → SCAS → 믹서.

    **`nav_valid`는 그래프 enable이다** — 0이면 아무것도 실행하지 않고 직전 출력을
    그대로 낸다(상태도 동결). 손으로 쓴 법칙의 "마지막 유효 SurfaceCommand 유지"
    [기본값]가 이 형태다(law.py:86). 첫 유효 항법 이전의 홀드 값은 트림 웜스타트로
    구성되는데, 생성 코드에서는 상태 필드와 마찬가지로 통합 계층이 채운다.

    게인 스케줄·α 리미터는 옵션이며 없으면 그 경로가 아예 생기지 않는다
    (`with_schedule`·`with_limiter` 조합이 구조 분기가 아니라 그래프 차이가 된다).
    """
    src = {u: u for u in FCL_INPUTS}
    nodes = []

    ap_ports, scas_ports = {}, {}
    if gain_tables:
        sched_nodes, gains = gain_schedule_nodes(
            "sched", tables=gain_tables, filter_tau=filter_tau,
            srcs={"mach": "mach", "alt": "h", "fuel": "fuel"},
        )
        nodes += grouped(sched_nodes, "sched")
        ap_ports = {g: v for g, v in gains.items() if g in _AP_GROUPS}
        scas_ports = {g: v for g, v in gains.items() if g in _SCAS_GROUPS}
        unknown = set(gains) - set(_AP_GROUPS) - set(_SCAS_GROUPS)
        if unknown:
            raise ValueError(f"{name}: 미정의 게인 그룹 {sorted(unknown)}")

    ap_nodes, ap_out = autopilot_nodes("ap", srcs=src, gain_ports=ap_ports, **autopilot)
    nodes += grouped(ap_nodes, "ap")

    theta_cmd = ap_out["theta_cmd"]
    if stall_table is not None:
        lim_nodes, lim_out = alpha_limiter_nodes(
            "lim", stall_table=stall_table, margin=alpha_margin,
            srcs={"theta_cmd": theta_cmd, "theta": "theta", "alpha": "alpha", "mach": "mach"},
        )
        nodes += grouped(lim_nodes, "lim")
        theta_cmd = lim_out["theta_cmd"]

    # 엘레본 제어권한 배분 — 선회 하중만큼 피치 몫을 먼저 떼고 나머지를 롤에.
    # alloc_trim_table = None이면 배분이 없다(종전 구조 그대로)
    alloc = None
    if alloc_trim_table is not None:
        # 배분은 예산을 **크기 하나**로 나눈다(하한은 Gain(−1)로 만든다). 그래서
        # 형상이 비대칭이면 그 하나를 어느 쪽에 맞출지가 문제가 된다. 가장 좁은
        # 쪽으로 맞춘다 — 그러면 넘겨준 한계가 어느 축의 설정 한계도 넘지 않고
        # (권한이 조용히 늘어나지 않는다), |δe|+|δa| ≤ B ≤ min(|lo|, hi)라서
        # 믹서 클립도 여전히 구조적으로 안 걸린다. 대칭 형상(현행 ±0.35)에서는
        # B = elevon_hi라 거동이 그대로다.
        #
        # 비대칭을 거부하지 않는 이유: 영향성 해석은 out_hi 하나만 흔들어 보는데
        # (pipeline/influence.py), 거부하면 그 정당한 사용이 조립 예외로 죽는다.
        # 엘레본 축에만 붙는다 — 러더·스로틀은 전용 효과기라 이 배분과 무관하다.
        budget = min(mixer["elevon_hi"], -mixer["elevon_lo"],
                     *(scas_axes[ax]["out_hi"] for ax in ("pitch", "roll")),
                     *(-scas_axes[ax]["out_lo"] for ax in ("pitch", "roll")))
        if not budget > 0.0:
            raise ValueError(
                f"{name}: 배분 예산이 0 이하다 ({budget}) — 엘레본·SCAS 한계를 확인하라")
        alloc = {"phi_cmd_src": ap_out["phi_cmd"], "mach_src": src["mach"],
                 "elevon_hi": budget, "trim_table": alloc_trim_table,
                 "resv_frac": alloc_resv_frac}

    scas_nodes, scas_out = scas3_nodes(
        "scas",
        srcs={**src, "theta_cmd": theta_cmd, "phi_cmd": ap_out["phi_cmd"]},
        gain_ports=scas_ports,
        alloc=alloc,
        **scas_axes,
    )
    nodes += grouped(scas_nodes, "scas")

    mix_nodes, mix_out = mixer_nodes(
        "mix",
        srcs={"de": scas_out["pitch"], "da": scas_out["roll"],
              "dr": scas_out["yaw"], "thr": ap_out["throttle"]},
        **mixer,
    )
    nodes += grouped(mix_nodes, "mix")

    outputs = dict(mix_out)
    if stall_table is not None:
        # 엔벨로프 감시(02 §6.1)가 소비 — 항법 무효 시 함께 홀드되는 것도 원본과 같다
        outputs["limiter_active"] = lim_out["active"]
        outputs["alpha_margin"] = lim_out["alpha_margin"]

    # 리미터가 없으면 그 노드도 없다 — 없는 신호에 타입을 달면 `Graph`가 거부한다
    types = _types_for(FCL_INPUTS) | _typed_outputs(mix_out, MIXER_OUTPUT_TYPES)
    if stall_table is not None:
        types |= _limiter_types("lim")
    if gain_tables:
        types |= _sched_gain_types(gains)

    return Graph(name, inputs=FCL_INPUTS, nodes=nodes, outputs=outputs, enable="nav_valid",
                 signal_types=types)
