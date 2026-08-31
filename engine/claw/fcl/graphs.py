"""**제어법칙 구조의 정본** — 이 파일이 제어법칙의 구조 그 자체다 (02 §2.2).

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

    # 적분기 클램프가 곧 축 출력 한계 — 안티와인드업은 PID 내부 클램프(scas.py:11)
    nodes.append(
        Node(
            nm("pid"),
            PID,
            inputs=(err_src,),
            params={"kp": kp, "ki": ki, "kd": 0.0, "out_lo": out_lo, "out_hi": out_hi},
            gains={g: ports[g] for g in ("kp", "ki") if g in ports},
            on_disable=pid_on_disable,
            **common,
        )
    )
    last = nm("pid")

    if has_rate:
        damp = damp_src
        if damp is None:
            damp = nm("damp")
            if "k_rate" in ports:
                nodes.append(Node(damp, Product, inputs=(ports["k_rate"], rate_ref), **common))
            else:
                nodes.append(Node(damp, Gain, inputs=(rate_ref,), params={"k": k_rate}, **common))
        # rate 항은 PID 클램프 밖에서 더해지므로 축 출력을 한 번 더 제한한다 (scas.py:11)
        nodes.append(
            Node(nm("sum"), Sum, inputs=(nm("pid"), damp),
                 params={"signs": (1.0, 1.0)}, **common)
        )
        last = nm("sum")

    nodes.append(
        Node(nm("sat"), Saturation, inputs=(last,),
             params={"lo": out_lo, "hi": out_hi}, **common)
    )
    return nodes, nm("sat")


def scas_axis_graph(name, *, kp, ki, k_rate, out_lo, out_hi, washout_tau=0.0, scheduled=()):
    """SCAS 한 축을 단독 그래프로 — 증분 A의 수직 슬라이스."""
    sched = tuple(g for g in _SCHEDULABLE if g in scheduled)
    nodes, out = scas_axis_nodes(
        "",  # 단독 그래프라 접두사 없이 wo·pid·damp·sum·sat 그대로
        kp=kp, ki=ki, k_rate=k_rate, out_lo=out_lo, out_hi=out_hi,
        washout_tau=washout_tau, err_src="att_err", rate_src="rate",
        gain_ports={g: g for g in sched},
    )
    return Graph(name, inputs=("att_err", "rate") + sched, nodes=nodes, outputs={"u": out})


# ── SCAS 3축 ──────────────────────────────────────────────────────────────


def scas3_nodes(prefix, *, pitch, roll, yaw, srcs, gain_ports=None):
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
    outs = {}
    for group, cfg, err, rate in (
        ("pitch", pitch, nm("pitch_err"), srcs["q"]),
        ("roll", roll, nm("roll_err"), srcs["p"]),
        ("yaw", yaw, nm("yaw_err"), srcs["r"]),
    ):
        axis_nodes, out = scas_axis_nodes(
            nm(group), err_src=err, rate_src=rate,
            gain_ports=ports.get(group), **cfg,
        )
        nodes += axis_nodes
        outs[group] = out
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
    return Graph(name, inputs=inputs, nodes=nodes, outputs=outs)


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
    return Graph(name, inputs=inputs, nodes=nodes,
                 outputs={"de": outs["pitch"], "da": outs["roll"], "dr": outs["yaw"]})


def gain_schedule_graph(name="gain_schedule", *, tables, filter_tau):
    """게인 스케줄 단독 그래프 — 실제로 쓰이는 스케줄 변수만 입력이 된다."""
    used = sorted({ax for tab in tables.values() for ax in tab.axis_names})
    nodes, groups = gain_schedule_nodes(
        "", tables=tables, filter_tau=filter_tau, srcs={ax: ax for ax in used}
    )
    outputs = {f"{g}_{k}": nid for g, keys in groups.items() for k, nid in keys.items()}
    return Graph(name, inputs=tuple(used), nodes=nodes, outputs=outputs)


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


def alpha_limiter_graph(name="alpha_limiter", *, stall_table, margin):
    nodes, outs = alpha_limiter_nodes(
        "", stall_table=stall_table, margin=margin, srcs={u: u for u in LIMITER_INPUTS}
    )
    return Graph(name, inputs=LIMITER_INPUTS, nodes=nodes, outputs=outs)


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


def mixer_graph(name="mixer", **params):
    nodes, outs = mixer_nodes("", srcs={u: u for u in MIXER_INPUTS}, **params)
    return Graph(name, inputs=MIXER_INPUTS, nodes=nodes, outputs=outs)


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

    scas_nodes, scas_out = scas3_nodes(
        "scas",
        srcs={**src, "theta_cmd": theta_cmd, "phi_cmd": ap_out["phi_cmd"]},
        gain_ports=scas_ports,
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

    return Graph(name, inputs=FCL_INPUTS, nodes=nodes, outputs=outputs, enable="nav_valid")
