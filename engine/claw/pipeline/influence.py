"""영향성 해석 — 파라미터 하나가 제어법칙과 설계 지표에 미치는 영향 (02 §2.4, M15).

「어느 단계의 수치 변경이든 전체 출력에 미치는 영향을 정량 평가할 수 있어야 한다」가
02 §2.4의 요구고, 이 모듈은 그것을 **세 단(段)** 으로 답한다:

  1단 구조   `param_impacts` — 이 파라미터가 IR의 어느 노드를 건드리고 거기서 어느
             출력까지 도달하는가. 즉시. 추정이 아니라 사실이다
  2단 개루프 `openloop_delta` — 기록된 법칙 입력을 그대로 다시 흘려 노드별 |Δ|.
             피드백이 얼어 있으므로 **폐루프가 아니다**
  3단 폐루프 `closedloop_sweep` — 실제 6DOF 재시뮬로 설계 지표 Δ. 비싸다

**손으로 적은 매핑표를 두지 않는다.** "kp_alt는 ap_alt_pid를 건드린다"를 표로 적으면
그래프가 바뀔 때 조용히 낡는다 — 02 §5.5 중복 정의 금지가 정면으로 막는 것이 이것이다.
대신 파라미터를 흔들어 법칙을 **재조립하고 노드 서명을 diff** 한다. 구조 정본
(fcl/graphs.py)이 바뀌면 매핑도 따라 바뀐다.

조립은 언제나 M7 `make_demo_fcl` 한 경로를 지난다 (02 v0.24) — 여기서 FCL을 따로
조립하면 게인·타면 한계·마진이 또 한 곳에 적힌다.

**구조 도달성은 "영향이 있다"가 아니라 "영향이 있을 수 있다"이다.** 포화된 가지나
0 게인을 지나는 경로는 도달하지만 무력하다. 그 반증은 2단이 낸다 — 그리고 실제로
게인 스케줄이 붙은 SCAS 상수처럼 **1단은 잡는데 2단이 0인** 자리가 있다. 두 값이
갈리는 것이 오류가 아니라 발견이므로 `ParamImpact.overridden`으로 따로 낸다.
"""

from dataclasses import dataclass, field, replace

import numpy as np

import claw.fcl  # noqa: F401  — REGISTRY에 Autopilot·ScasAxis·Mixer 등재 (import 부작용)
import claw.guidance  # noqa: F401  — LOS
import claw.nav  # noqa: F401  — ErrorModel
import claw.plant  # noqa: F401  — SecondOrderActuator
from claw.fcl.demo import (
    DEMO_ALPHA_MARGIN,
    DEMO_K_DIFF_THR,
    DEMO_PITCH,
    DEMO_ROLL,
    DEMO_YAW,
    make_demo_fcl,
    make_demo_gain_tables,
)
from claw.fcl.scas import Scas
from claw.params.paramset import canonical_hash
from claw.params.registry import REGISTRY
from claw.tables import PolyTable, Table

SCAS_AXES = ("pitch", "roll", "yaw")
_SCAS_BASE = {"pitch": DEMO_PITCH, "roll": DEMO_ROLL, "yaw": DEMO_YAW}

# 파라미터 묶음(band) — 화면의 세로 그룹이자 "법칙 안/밖"의 판정 근거.
# in_law=False인 묶음은 IR 그래프 **바깥**이라 개루프 Δ가 구조적으로 0이다.
# 영향이 없어서가 아니라 개루프 재생이 볼 수 없는 자리다 (3단에서만 보인다) —
# 이 구분을 안 하면 화면이 "항법 오차는 영향 없음"이라고 정면으로 거짓말한다.
BANDS = {
    "ap": ("오토파일럿", True),
    "scas": ("SCAS", True),
    "mix": ("엘레본 믹서", True),
    "lim": ("α 리미터", True),
    "sched": ("게인 스케줄", True),
    "rate": ("제어 주기", True),
    "nav": ("항법 오차모델", False),
    "actuator": ("작동기", False),
    "guidance": ("유도", False),
}


@dataclass(frozen=True)
class ParamRef:
    """편집 가능한 설계 파라미터 하나 — 메타는 전부 엔진 ParamDef에서 읽어 온다."""

    id: str  # 'fcl/Autopilot.kp_alt' · 'fcl/ScasAxis.pitch.kp' · 'table.pitch.kp'
    band: str
    label: str
    unit: str
    desc: str
    value: float
    lo: float | None = None
    hi: float | None = None

    @property
    def in_law(self) -> bool:
        """제어법칙 IR 그래프 안의 파라미터인가 (= 개루프 Δ로 볼 수 있는가)."""
        return BANDS[self.band][1]

    def as_dict(self) -> dict:
        return {
            "id": self.id, "band": self.band, "label": self.label, "unit": self.unit,
            "desc": self.desc, "value": self.value, "lo": self.lo, "hi": self.hi,
            "in_law": self.in_law,
        }


@dataclass
class Shape:
    """편집 중인 설계 형상 — 파라미터를 흔드는 단위이자 조립 인자의 원본.

    빈 dict는 "사용자가 아무것도 안 정했다"는 뜻이고 그 자리는 엔진 기본값이 채운다
    (02 §5.5 — 웹도 해석도 엔진 기본값을 재기술하지 않는다).
    """

    control_hz: float = 100.0
    with_schedule: bool = True
    with_limiter: bool = True
    autopilot: dict = field(default_factory=dict)
    scas: dict = field(default_factory=dict)  # {'pitch': {'kp': …}, …}
    mixer: dict = field(default_factory=dict)
    alpha_margin: float | None = None
    gain_tables: dict | None = None  # 웹 게인 탭이 편집한 테이블 (없으면 설계 테이블)
    gain_scale: dict = field(default_factory=dict)  # {'pitch.kp': 1.1} — 곡선 배율
    nav: dict = field(default_factory=dict)
    actuators: dict = field(default_factory=dict)
    guidance: dict = field(default_factory=dict)

    @property
    def dt(self) -> float:
        return 1.0 / self.control_hz

    def copy(self) -> "Shape":
        return replace(
            self,
            autopilot=dict(self.autopilot),
            scas={k: dict(v) for k, v in self.scas.items()},
            mixer=dict(self.mixer),
            gain_tables=None if self.gain_tables is None else dict(self.gain_tables),
            gain_scale=dict(self.gain_scale),
            nav=dict(self.nav),
            actuators=dict(self.actuators),
            guidance=dict(self.guidance),
        )

    def fingerprint(self) -> str:
        """형상 지문 — 2·3단 결과가 어느 형상에서 나왔는지의 계보 키 (02 §2.4)."""
        return canonical_hash(
            {
                "control_hz": self.control_hz,
                "with_schedule": self.with_schedule,
                "with_limiter": self.with_limiter,
                "autopilot": dict(sorted(self.autopilot.items())),
                "scas": {a: dict(sorted(v.items())) for a, v in sorted(self.scas.items())},
                "mixer": dict(sorted(self.mixer.items())),
                "alpha_margin": self.alpha_margin,
                # 어느 자리에 테이블이 붙었는지가 구조를 바꾸므로 이름과 값 둘 다 지문에 든다
                "gain_tables": None if self.gain_tables is None else {
                    n: _norm(t) for n, t in sorted(self.gain_tables.items())
                },
                "gain_scale": dict(sorted(self.gain_scale.items())),
                "nav": dict(sorted(self.nav.items())),
                "actuators": dict(sorted(self.actuators.items())),
                "guidance": dict(sorted(self.guidance.items())),
            }
        )[:16]


def make_law(shape: Shape):
    """형상 → 조립된 FCL (`init(dt)`까지). 조립 정본은 M7 `make_demo_fcl` 하나다.

    부분 지정 보충: 사용자가 정한 키만 싣고 나머지는 엔진 기본값이 채운다. SCAS·믹서는
    설계 기본값(DEMO_*)에 덮어쓰기를 얹어 레지스트리로 구성한다 — 레지스트리를 지나야
    ParamDef 범위와 생성자 교차조건(theta_lo ≤ theta_hi 등)이 그대로 판정된다.
    """
    ap = REGISTRY.create("fcl", "Autopilot", shape.autopilot) if shape.autopilot else None
    scas = None
    if shape.scas:
        unknown = sorted(set(shape.scas) - set(SCAS_AXES))
        if unknown:  # 조용히 버리면 지문만 움직이고 그래프는 그대로다 — 무증상 거짓말
            raise ValueError(f"알 수 없는 SCAS 축 {unknown} — 허용: {list(SCAS_AXES)}")
        axes = {
            a: REGISTRY.create("fcl", "ScasAxis", {**_SCAS_BASE[a], **shape.scas.get(a, {})})
            for a in SCAS_AXES
        }
        scas = Scas(axes["pitch"], axes["roll"], axes["yaw"])
    mixer = None
    if shape.mixer:
        mixer = REGISTRY.create(
            "fcl", "Mixer", {"k_diff_thr": DEMO_K_DIFF_THR, **shape.mixer}
        )
    # `with_schedule=False`인데 테이블이 실려 오면 **조립 함수가 거부해야 한다**
    # (make_demo_fcl의 가드). and로 단락시키면 그 가드가 영영 안 울리고, 사용자가
    # 기술한 것과 **다른 법칙**을 분석해 놓고 지문은 맞다고 말하게 된다 —
    # 같은 본문에 codegen 라우트는 422, 이 라우트는 200이 되는 불일치
    gain_tables = shape.gain_tables if not shape.with_schedule else None
    if shape.with_schedule and (shape.gain_tables is not None or shape.gain_scale):
        gain_tables = dict(
            make_demo_gain_tables() if shape.gain_tables is None else shape.gain_tables
        )
        for name, scale in shape.gain_scale.items():
            if name not in gain_tables:
                raise ValueError(
                    f"배율을 걸 테이블이 없다: {name!r} — 스케줄 자리 {sorted(gain_tables)}"
                )
            t = gain_tables[name]
            # 다항 스케줄(PolyTable)은 격자 값이 없어 계수에 곱한다 — 같은 곡선 배율이다
            if isinstance(t, PolyTable):
                gain_tables[name] = t.scaled(scale)
            else:
                gain_tables[name] = Table(
                    {k: np.asarray(v) for k, v in zip(t.axis_names, t.axes)},
                    np.asarray(t.data) * float(scale),
                    name=name,
                    extrapolate=t.extrapolate,
                )
    return make_demo_fcl(
        with_schedule=shape.with_schedule,
        with_limiter=shape.with_limiter,
        autopilot=ap,
        gain_tables=gain_tables,
        scas=scas,
        mixer=mixer,
        alpha_margin=shape.alpha_margin,
    ).init(shape.dt)


# ── 파라미터 목록 ──────────────────────────────────────────────────────────
# 값은 조립된 법칙에서 읽고, 메타(단위·설명·범위)는 레지스트리 ParamDef에서 읽는다.
# 어느 쪽도 여기서 재기술하지 않는다 (02 §5.5).

_LAW_SOURCES = (
    # (band, 레지스트리 카테고리/이름, id 접두, 축 목록 or None)
    ("ap", ("fcl", "Autopilot"), "fcl/Autopilot", None),
    ("scas", ("fcl", "ScasAxis"), "fcl/ScasAxis", SCAS_AXES),
    ("mix", ("fcl", "Mixer"), "fcl/Mixer", None),
)
_OFFGRAPH_SOURCES = (
    ("nav", ("nav", "ErrorModel"), "nav/ErrorModel"),
    ("actuator", ("actuator", "SecondOrderActuator"), "actuator/SecondOrderActuator"),
    ("guidance", ("guidance", "LOS"), "guidance/LOS"),
)


def _defs_map(category, name):
    return {d.name: d for d in REGISTRY.param_defs(category, name)}


def param_universe(shape: Shape, *, include_offgraph: bool = True) -> list[ParamRef]:
    """이 형상에서 흔들 수 있는 설계 파라미터 전부.

    축 목록(SCAS 3축)·게인 테이블 이름은 **조립된 법칙에서** 읽는다 — 형상이 바꾸면
    목록도 따라 바뀐다. 스케줄이 꺼진 형상에는 sched 파라미터가 아예 없다.
    """
    law = make_law(shape)
    refs: list[ParamRef] = []

    for band, (cat, comp), prefix, axes in _LAW_SOURCES:
        defs = _defs_map(cat, comp)
        if axes is None:
            cfg = law.autopilot.cfg if band == "ap" else law.mixer.cfg
            for key, d in defs.items():
                refs.append(ParamRef(
                    id=f"{prefix}.{key}", band=band, label=key, unit=d.unit,
                    desc=d.desc, value=float(cfg[key]), lo=d.lo, hi=d.hi,
                ))
        else:
            for axis in axes:
                cfg = law.scas.cfg[axis]
                for key, d in defs.items():
                    refs.append(ParamRef(
                        id=f"{prefix}.{axis}.{key}", band=band, label=f"{axis}.{key}",
                        unit=d.unit, desc=d.desc, value=float(cfg[key]),
                        lo=d.lo, hi=d.hi,
                    ))

    if law.alpha_limiter is not None:
        refs.append(ParamRef(
            id="fcl/AlphaLimiter.margin", band="lim", label="margin", unit="rad",
            desc="실속 경계 대비 α 여유 (01 §3.6)",
            value=float(law.alpha_limiter.margin), lo=0.0, hi=None,
        ))

    if law.schedule is not None:
        for name in sorted(law.schedule.tables):
            # 테이블은 절점 17개짜리 곡선이다. 절점 하나하나를 파라미터로 세우면
            # 화면이 테이블 하나로 덮이므로(6×17=102) **곡선 전체 배율**을 탐침으로
            # 쓴다 — 실제 설계 수치가 아니라 곡선 수준을 흔드는 손잡이임을 label에 밝힌다
            refs.append(ParamRef(
                id=f"table.{name}", band="sched", label=f"{name} (곡선 배율)", unit="-",
                desc=f"게인 스케줄 곡선 {name} 전체 배율 — 절점 개별값이 아님",
                value=float(shape.gain_scale.get(name, 1.0)), lo=0.0, hi=None,
            ))

    refs.append(ParamRef(
        id="rate.control_hz", band="rate", label="control_hz", unit="Hz",
        desc="제어 주기 — 이산 계수가 여기서 나오므로 형상의 일부다 (02 §2.2)",
        value=float(shape.control_hz), lo=1.0, hi=1000.0,
    ))

    if include_offgraph:
        for band, (cat, comp), prefix in _OFFGRAPH_SOURCES:
            over = {"nav": shape.nav, "actuator": shape.actuators,
                    "guidance": shape.guidance}[band]
            for key, d in _defs_map(cat, comp).items():
                v = over.get(key, d.default)
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    continue  # 비수치 — 섭동 의미가 없다
                if key == "seed":
                    continue  # 재현성 손잡이지 설계값이 아니다. 시드를 흔든 결과는
                    # "영향"이 아니라 **잡음 바닥**이고, 3단 스윕의 대조군이 그 몫이다
                refs.append(ParamRef(
                    id=f"{prefix}.{key}", band=band, label=key, unit=d.unit,
                    desc=d.desc, value=float(v), lo=d.lo, hi=d.hi,
                ))
    return refs


def apply_param(shape: Shape, ref: ParamRef, value: float) -> Shape:
    """형상 사본에 파라미터 하나를 적용. id 문법이 곧 적용 경로다."""
    s = shape.copy()
    pid = ref.id
    if pid.startswith("fcl/Autopilot."):
        s.autopilot[pid.split(".", 1)[1]] = value
    elif pid.startswith("fcl/ScasAxis."):
        axis, key = pid.split(".")[1:3]
        s.scas.setdefault(axis, {})[key] = value
    elif pid.startswith("fcl/Mixer."):
        s.mixer[pid.split(".", 1)[1]] = value
    elif pid == "fcl/AlphaLimiter.margin":
        s.alpha_margin = value
    elif pid.startswith("table."):
        s.gain_scale[pid.split(".", 1)[1]] = value
    elif pid == "rate.control_hz":
        s.control_hz = value
    elif pid.startswith("nav/"):
        s.nav[pid.split(".", 1)[1]] = value
    elif pid.startswith("actuator/"):
        s.actuators[pid.split(".", 1)[1]] = value
    elif pid.startswith("guidance/"):
        s.guidance[pid.split(".", 1)[1]] = value
    else:
        raise ValueError(f"알 수 없는 파라미터 id: {pid!r}")
    return s


def probe_value(
    ref: ParamRef, rel: float = 0.01, *, zero_step: float = 0.01
) -> tuple[float | None, str | None]:
    """유한 섭동 탐침값 — (값, 클립 사유). 미분이 아니라 **유한 차분**이다.

    스텝은 **상대**(|v|·rel)다. 절대 바닥값을 섞으면 작은 값이 망가진다 — kp_alt는
    0.004라서 바닥값 0.01을 쓰면 250% 섭동이 되고, 그건 더 이상 국소 민감도가 아니다.
    값이 정확히 0인 자리(k_thr_turn·ki_hdg)만 상대 스텝이 성립하지 않으므로 그때만
    `zero_step`을 쓴다. 어느 쪽으로도 못 움직이면 (None, 사유) — 조용히 0을 내지 않는다.
    """
    v = float(ref.value)
    step = abs(v) * rel if v != 0.0 else zero_step
    for cand in (v + step, v - step):
        if ref.lo is not None and cand < ref.lo:
            continue
        if ref.hi is not None and cand > ref.hi:
            continue
        return cand, None
    return None, f"범위 [{ref.lo}, {ref.hi}]가 ±{step:g} 섭동을 허용하지 않음"


# ── 1단: 구조적 영향 (재조립 후 서명 diff) ─────────────────────────────────

def _norm(v):
    """서명용 정규화.

    Table·ndarray는 `__repr__`이 없거나 동일성 기반이라 그대로 두면 **모든 노드가
    바뀐 것처럼** 보인다 (실제로 겪었다: sched_*·lim_stall이 모든 파라미터에 딸려
    나왔다). 값으로 환원한다.
    """
    if isinstance(v, Table):
        return ("Table", tuple(v.axis_names), tuple(tuple(np.asarray(a).ravel().tolist())
                for a in v.axes), tuple(np.asarray(v.data).ravel().tolist()), v.extrapolate)
    if isinstance(v, PolyTable):
        # 다항은 격자 값이 아니라 구간 계수가 신원이다 — to_dict가 그 전부다
        return ("PolyTable", _norm(v.to_dict()))
    if isinstance(v, np.ndarray):
        return ("nd", v.shape, tuple(v.ravel().tolist()))
    if isinstance(v, dict):
        return tuple(sorted((k, _norm(x)) for k, x in v.items()))
    if isinstance(v, (list, tuple)):
        return tuple(_norm(x) for x in v)
    if isinstance(v, float):
        return repr(v)  # 0.1+0.2 를 0.3과 구분
    return v


def node_signature(node) -> tuple:
    """IR 노드의 신원 — 이 중 하나라도 바뀌면 그 파라미터가 이 노드를 건드린 것이다."""
    return (
        node.kind,
        getattr(node, "op", None) or node.block.__name__,
        tuple(node.inputs),
        _norm(node.params) if node.kind == "block" else _norm(getattr(node, "value", None)),
        tuple(sorted(node.gains.items())) if node.kind == "block" else (),
        node.enable,
        _norm(getattr(node, "on_disable", {})),
        getattr(node, "disabled_output", 0.0),
        node.group,
    )


def law_signature(law) -> dict:
    """노드 서명 + **러너 인스턴스 서명**.

    인스턴스까지 보는 이유: 제어주기(dt)는 `fcl_graph`의 인자가 아니라 `GraphRunner`의
    인자라서 노드 서명이 전혀 안 움직인다. 그런데 dt는 Washout·CommandFilter·적분기의
    이산 계수를 전부 바꾼다 (02 §2.2 — "dt는 형상의 일부"). 노드만 보면 "제어주기는
    아무것도 안 건드린다"는 거짓말이 나온다. init(dt) 직후 상태는 결정적이므로 그대로
    비교하면 된다.
    """
    runner = law.runner
    sig = {}
    for node in runner.graph.nodes:
        inst = runner.instances.get(node.id)
        sig[node.id] = (
            node_signature(node),
            tuple(sorted((k, _norm(v)) for k, v in vars(inst).items())) if inst else (),
        )
    sig["__outputs__"] = tuple(sorted(runner.graph.outputs.items()))
    sig["__inputs__"] = tuple(runner.graph.inputs)
    return sig


@dataclass
class ParamImpact:
    """파라미터 하나의 구조적 영향 — 씨앗 노드와 거기서 도달하는 전방 원뿔."""

    ref: ParamRef
    probe_to: float | None
    clipped_by: str | None
    changed: tuple = ()
    added: tuple = ()
    removed: tuple = ()
    overridden: tuple = ()  # 씨앗이지만 게인 포트가 매 스텝 덮어써 런타임 효과가 없는 노드
    added_meta: tuple = ()  # 생기는 노드의 신원 — 화면이 "올리면 뭐가 생기나"를 그릴 근거
    reach: tuple = ()  # 씨앗에서 전방 도달하는 노드 전부 (씨앗 포함)
    outputs: tuple = ()  # 도달하는 그래프 출력 이름
    error: str | None = None

    @property
    def seeds(self) -> tuple:
        return tuple(dict.fromkeys(self.changed + self.added + self.removed))

    @property
    def structural(self) -> bool:
        """노드가 생기거나 사라지는가 — 연속적인 민감도가 아니라 **위상 변경**이다."""
        return bool(self.added or self.removed)

    @property
    def inert(self) -> bool:
        """법칙 안인데 건드리는 노드가 하나도 없다 = 이 상수는 **그래프에 없다**.

        `overridden`(상수가 있지만 매 스텝 덮어써짐)과 다른 상태다. 스케줄된
        k_rate가 그렇다 — 스케줄 경로는 상수 대신 Product 노드를 쓰므로 생성자
        인자가 그래프에 방출되지조차 않는다. 편집해도 아무 일이 없는데 폼에는
        값이 보이는 자리라, 화면이 말해 주지 않으면 사용자가 혼자 알아내야 한다.
        """
        return self.ref.in_law and not self.seeds and self.error is None

    def as_dict(self) -> dict:
        return {
            **self.ref.as_dict(),
            "probe_to": self.probe_to, "clipped_by": self.clipped_by,
            "changed": list(self.changed), "added": list(self.added),
            "removed": list(self.removed), "overridden": list(self.overridden),
            "seeds": list(self.seeds), "reach": list(self.reach),
            "n_reach": len(self.reach), "outputs": list(self.outputs),
            "structural": self.structural, "inert": self.inert,
            "added_meta": [dict(m) for m in self.added_meta], "error": self.error,
        }


def node_depths(graph) -> dict:
    """입력=0, 노드=1+max(refs). 선언 순서가 위상 순서라 **전방 1회 주행**이면 끝난다.

    최단이 아니라 최장 경로다 — 그래야 "층 번호 = 이 노드가 실행될 수 있는 가장 이른
    단계"가 되고, 생성 C의 문장 순서와 층이 일치한다.
    """
    d = {name: 0 for name in graph.inputs}
    for node in graph.nodes:
        d[node.id] = 1 + max((d.get(r, 0) for r in node.refs), default=0)
    return d


def forward_reach(graph, seeds) -> set:
    """씨앗에서 전방으로 도달 가능한 노드 (`Graph._reachable()`의 전방판).

    선언 순서가 위상 순서라 한 번 훑으면 된다 — 노드는 자기보다 앞선 것만 참조한다.
    """
    hit = set(seeds)
    for node in graph.nodes:
        if node.id in hit or any(r in hit for r in node.refs):
            hit.add(node.id)
    return hit


def _overridden_nodes(g1, g2, changed) -> tuple:
    """바뀐 노드 중, **바뀐 생성자 인자가 전부 게인 포트에 가려지는** 노드.

    실행기는 매 스텝 `inst.step(u, **gains)`로 포트 값을 덮어쓰므로(ir_exec) 그런
    자리는 구조 diff에는 잡히지만 런타임 효과가 0이다.

    이름으로 맞추지 않는다 — 파라미터 이름과 포트 이름이 다르기 때문이다
    (AP의 `kp_alt`가 `ap_alt_pid`에서는 포트 `kp`다). **실제로 값이 달라진 키**를
    두 그래프에서 뽑아 그 키가 전부 게인 포트인지 본다. 그래서 SCAS든 AP든,
    스케줄 자리(`graphs.SCHEDULABLE` 16칸)가 어떻게 바뀌든 따라간다.
    """
    out = []
    for nid in changed:
        n1, n2 = g1.node(nid), g2.node(nid)
        gains = getattr(n1, "gains", {})
        if not gains:
            continue
        p1 = getattr(n1, "params", {}) or {}
        p2 = getattr(n2, "params", {}) or {}
        moved = [k for k in set(p1) | set(p2) if _norm(p1.get(k)) != _norm(p2.get(k))]
        # 인자가 하나도 안 움직였는데 서명이 바뀐 경우(배선·enable 변화)는 덮임이 아니다
        if moved and all(k in gains for k in moved):
            out.append(nid)
    return tuple(out)


def param_impacts(shape: Shape, refs=None, *, probe_rel: float = 0.01) -> dict:
    """파라미터별 구조적 영향 — 재조립 후 서명 diff + 전방 도달.

    법칙 밖 파라미터(항법·작동기·유도)는 재조립할 것이 없으므로 씨앗이 비고
    `in_law=False`로 남는다. **"영향 없음"이 아니라 "개루프가 볼 수 없음"이다.**
    """
    refs = list(param_universe(shape)) if refs is None else list(refs)
    base_law = make_law(shape)
    base_sig = law_signature(base_law)
    base_graph = base_law.runner.graph
    out = {}
    for ref in refs:
        if not ref.in_law:
            out[ref.id] = ParamImpact(ref, None, None)
            continue
        target, clipped = probe_value(ref, probe_rel)
        if target is None:
            out[ref.id] = ParamImpact(ref, None, clipped, error=clipped)
            continue
        try:
            law2 = make_law(apply_param(shape, ref, target))
        except (ValueError, TypeError) as e:  # 범위·교차조건 위반은 엔진이 판정
            out[ref.id] = ParamImpact(ref, target, None, error=str(e))
            continue
        sig2 = law_signature(law2)
        changed = tuple(k for k in base_sig if k in sig2 and not k.startswith("__")
                        and base_sig[k] != sig2[k])
        added = tuple(k for k in sig2 if k not in base_sig and not k.startswith("__"))
        removed = tuple(k for k in base_sig if k not in sig2 and not k.startswith("__"))
        graph2 = law2.runner.graph
        overridden = _overridden_nodes(base_graph, graph2, changed)
        seeds = tuple(dict.fromkeys(changed + added + removed))
        reach_graph = graph2 if added else base_graph
        reach = forward_reach(reach_graph, [s for s in seeds if any(n.id == s for n in reach_graph.nodes)])
        outputs = tuple(sorted(n for n, nid in reach_graph.outputs.items() if nid in reach))
        order = {n.id: i for i, n in enumerate(reach_graph.nodes)}
        added_meta = tuple(
            {
                "id": nid,
                "block": None if graph2.node(nid).kind == "op" else graph2.node(nid).block.__name__,
                "op": getattr(graph2.node(nid), "op", None),
                "group": graph2.node(nid).group,
                "refs": list(graph2.node(nid).refs),
            }
            for nid in added
        )
        out[ref.id] = ParamImpact(
            ref, target, clipped, changed=changed, added=added, removed=removed,
            overridden=overridden, added_meta=added_meta,
            reach=tuple(sorted(reach, key=lambda k: order.get(k, 1 << 30))),
            outputs=outputs,
        )
    return out


# ── 설계 지표 (3단이 재는 것) ──────────────────────────────────────────────
# `signals`가 이 지표가 읽는 신호의 **유일한 선언**이다 — 화면의 「법칙 밖 → 지표」
# 간선이 여기서 파생되므로 배선이 두 군데 적히지 않는다.
#
# 이 간선들은 **유도된 것이 아니라 선언된 것**이다. 폐루프는 IR 바깥에서 닫히므로
# 구조 도달성은 그래프 출력에서 멈춘다. 파라미터→지표의 정량 대응은 3단(실측)에만
# 있고, 1단에서는 "이 지표가 무엇을 읽는가"까지만 말할 수 있다.

@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    unit: str
    signals: tuple  # 이 지표가 읽는 SimResult 신호·엔벨로프 키
    better: str  # 'lower' | 'higher'
    desc: str

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "unit": self.unit,
            "signals": list(self.signals), "better": self.better, "desc": self.desc,
        }


METRICS = (
    MetricDef("worst_stall_margin", "최악 실속마진", "rad", ("alpha_margin",), "higher",
              "임무 전체에서 α_stall−α의 최솟값 (02 §6.1)"),
    MetricDef("envelope_flags", "엔벨로프 이탈 틱", "-", ("alpha", "beta", "mach", "h"),
              "lower", "공력 DB 유효범위·고도 하한 이탈 표본 수"),
    MetricDef("alt_rms", "고도 추종 RMS", "m", ("h", "cmd_alt"), "lower",
              "|h − cmd_alt|의 RMS"),
    MetricDef("spd_rms", "속도 추종 RMS", "m/s", ("V", "cmd_speed"), "lower",
              "|V − cmd_speed|의 RMS"),
    MetricDef("hdg_rms", "헤딩 추종 RMS", "rad", ("psi", "cmd_heading"), "lower",
              "각도 랩을 고려한 헤딩 오차 RMS"),
    MetricDef("surf_sat_frac", "타면 포화율", "-", ("de", "da", "dr"), "lower",
              "믹서 한계에 닿은 표본 비율 — 한계값은 법칙에서 읽는다"),
    MetricDef("limiter_frac", "α리미터 작동률", "-", ("limiter_active",), "lower",
              "리미터가 피치 명령을 잘라낸 표본 비율"),
    MetricDef("xtrack_rms", "경로오차 RMS", "m", ("pn", "pe"), "lower",
              "웨이포인트 폴리라인까지의 최근접 거리 RMS (사후 기하)"),
    # ── 이착륙 (01 §3.3.1) — 그 단계가 없는 런에서는 **None**이다.
    # 0으로 채우면 착륙하지 않은 런이 "접지 강하율 0 = 완벽한 착륙"으로 읽힌다.
    # 부호가 아니라 **크기**다 — better가 'lower'|'higher' 둘뿐이라 부호 있는 값으로는
    # 어느 쪽도 참이 아니다(위로 튄 접지가 소프트 랜딩보다 좋게 랭크된다).
    MetricDef("td_sink_rate", "접지 수직속도", "m/s",
              ("u", "v", "w", "phi", "theta", "wow"), "lower",
              "접지 순간 |ḣ| — 작을수록 부드럽다. 부호(오르는 중인지)가 필요하면 "
              "pipeline.metrics.climb_rate. 접지 없으면 없음"),
    MetricDef("td_speed", "접지 속도", "m/s", ("V", "wow"), "lower",
              "접지 순간의 대기속도. 접지 없으면 없음"),
    MetricDef("rollout_dist", "접지→정지 직선거리", "m", ("pn", "pe", "wow"), "lower",
              "접지점과 정지점의 직선거리(경로장 아님) — 활주로 길이 요구의 근거. "
              "정지 전이면 없음"),
    MetricDef("launch_gx", "사출 하중", "g", ("launch_gx", "on_rail"), "lower",
              "발사 레일 축 가속도 — 판정 기준(구조 한계 n_x_launch)은 아직 없다 [TBD]"),
)


# ── 1단 payload (서버가 그대로 회신) ───────────────────────────────────────

def _jsonable(v):
    """노드 인자를 JSON으로 — 테이블은 **요약만** 낸다 (곡선 전체는 게인 탭 몫)."""
    if isinstance(v, Table):
        return {"kind": "table", "name": v.name,
                "axes": {a: len(np.asarray(x)) for a, x in zip(v.axis_names, v.axes)}}
    if isinstance(v, PolyTable):
        # 다항 스케줄도 **요약만** — 빠뜨리면 노드 인자가 그대로 실려 응답 직렬화가 깨진다
        return {"kind": "poly", "name": v.name, "axis": v.axis_names[0],
                "segments": len(v.segments),
                "degrees": [s["degree"] for s in v.segments]}
    if isinstance(v, np.ndarray):
        return v.ravel().tolist()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, float) and not np.isfinite(v):
        return None  # 서버 직렬화 정책과 같음 (NaN→null)
    return v


def structural_payload(shape: Shape, *, include_offgraph: bool = True,
                       probe_rel: float = 0.01) -> dict:
    """1단 — 구조 + 도달성 한 덩이. 랭크(층 번호)는 **보내지 않는다**.

    랭크는 `refs`에서 전방 1회 주행이면 나오는 값이라, 서버와 화면이 각각 계산하면
    같은 수를 두 곳에서 정의하는 꼴이 된다. 선언 순서가 위상 순서라는 사실
    (`topological_order`)만 알려 주고 계산은 소비자에게 맡긴다.
    """
    law = make_law(shape)
    graph = law.runner.graph
    refs = param_universe(shape, include_offgraph=include_offgraph)
    impacts = param_impacts(shape, refs, probe_rel=probe_rel)

    nodes = [{"id": f"in:{n}", "kind": "input", "label": n, "band": "io"}
             for n in graph.inputs]
    edges = []
    for node in graph.nodes:
        nodes.append({
            "id": node.id, "kind": "ir", "label": node.id, "band": node.group or "top",
            "block": None if node.kind == "op" else node.block.__name__,
            "op": getattr(node, "op", None), "group": node.group,
            "enable": node.enable,
            "params": _jsonable(node.params) if node.kind == "block" else {},
            "gains": dict(node.gains) if node.kind == "block" else {},
        })
        seen = set()
        for ref_name in node.inputs:
            edges.append({"src": _sig_id(ref_name, graph), "dst": node.id,
                          "kind": "ir", "port": "input"})
            seen.add(ref_name)
        for port, src in getattr(node, "gains", {}).items():
            edges.append({"src": _sig_id(src, graph), "dst": node.id,
                          "kind": "ir", "port": f"gain:{port}"})
        if node.enable is not None:
            edges.append({"src": _sig_id(node.enable, graph), "dst": node.id,
                          "kind": "ir", "port": "enable"})
        for field_name, src in getattr(node, "on_disable", {}).items():
            if isinstance(src, str):
                edges.append({"src": _sig_id(src, graph), "dst": node.id,
                              "kind": "ir", "port": f"on_disable:{field_name}"})

    for name, nid in graph.outputs.items():
        nodes.append({"id": f"out:{name}", "kind": "output", "label": name, "band": "io",
                      "source": nid})
        edges.append({"src": nid, "dst": f"out:{name}", "kind": "ir", "port": "output"})
        edges.append({"src": f"out:{name}", "dst": "sys:plant", "kind": "boundary"})

    nodes.append({"id": "sys:plant", "kind": "plant", "label": "기체·작동기·항법", "band": "io",
                  "note": "폐루프는 IR 밖에서 닫힌다 — 구조 도달성은 그래프 출력에서 멈춘다"})

    for m in METRICS:
        nodes.append({"id": f"metric:{m.key}", "kind": "metric", "band": "metric", **m.as_dict()})
        edges.append({"src": "sys:plant", "dst": f"metric:{m.key}", "kind": "declared"})

    # 구조를 바꾸는 파라미터가 **생기게 할** 노드 — 지금 그래프엔 없다. 간선이 가리키는
    # 대상이 없으면 페이로드가 자기모순이 되므로, 숨기는 대신 유령으로 드러낸다:
    # "이 값을 올리면 여기 노드 4개가 새로 생기고 배선이 바뀐다"가 이 화면의 볼거리다
    ghosts, ghost_of = {}, {}
    for ref in refs:
        for m in impacts[ref.id].added_meta:
            ghosts.setdefault(m["id"], m)
            ghost_of.setdefault(m["id"], []).append(ref.id)
    existing = {n["id"] for n in nodes}
    for nid, m in ghosts.items():
        if nid in existing:
            continue
        nodes.append({"id": nid, "kind": "ghost", "label": nid, "band": m["group"] or "top",
                      "block": m["block"], "op": m["op"], "group": m["group"],
                      "appears_with": ghost_of[nid],
                      "note": "지금 형상엔 없는 노드 — 이 파라미터를 올리면 생긴다"})
    for nid, m in ghosts.items():
        for r in m["refs"]:
            src = _sig_id(r, graph)
            if src in existing or src in ghosts:
                edges.append({"src": src, "dst": nid, "kind": "ghost"})

    warn_overridden, warn_error, warn_inert = [], [], []
    for ref in refs:
        imp = impacts[ref.id]
        # 스프레드가 뒤에 오면 ParamRef.id가 노드 id를 덮어써 간선이 가리키는 대상이
        # 사라진다 (테스트가 잡았다) — 스프레드 먼저, 신원은 나중에 못박는다
        nodes.append({**imp.as_dict(), "id": f"param:{ref.id}", "kind": "param",
                      "param_id": ref.id})
        if imp.error:
            warn_error.append(ref.id)
        if not ref.in_law:
            edges.append({"src": f"param:{ref.id}", "dst": "sys:plant", "kind": "offgraph"})
            continue
        for nid in imp.seeds:
            effect = ("added" if nid in imp.added else
                      "removed" if nid in imp.removed else
                      "overridden" if nid in imp.overridden else "changed")
            edges.append({"src": f"param:{ref.id}", "dst": nid, "kind": "param",
                          "effect": effect})
        if imp.overridden:
            warn_overridden.append(ref.id)
        if imp.inert:
            warn_inert.append(ref.id)

    warnings = []
    if warn_overridden:
        warnings.append(
            f"게인 스케줄이 덮어써 실행에 반영되지 않는 상수 {len(warn_overridden)}개: "
            f"{', '.join(warn_overridden)} — 실효값은 게인 탭의 테이블이다"
        )
    if warn_inert:
        warnings.append(
            f"그래프에 방출되지 않는 상수 {len(warn_inert)}개: {', '.join(warn_inert)} — "
            f"스케줄 경로가 상수 대신 조회 노드를 쓰므로 편집해도 아무 일도 일어나지 않는다"
        )
    if warn_error:
        warnings.append(f"섭동을 구성할 수 없는 파라미터 {len(warn_error)}개: {', '.join(warn_error)}")

    return {
        "fingerprint": shape.fingerprint(),
        "dt": shape.dt,
        "control_hz": shape.control_hz,
        "topological_order": True,
        "probe_rel": probe_rel,
        "graph": {
            "name": graph.name, "n_nodes": len(graph.nodes), "n_inputs": len(graph.inputs),
            "n_outputs": len(graph.outputs), "enable": graph.enable,
            "groups": [g for g, _ in graph.partitions],
        },
        "bands": {k: {"label": v[0], "in_law": v[1]} for k, v in BANDS.items()},
        "nodes": nodes,
        "edges": edges,
        "metrics": [m.as_dict() for m in METRICS],
        "warnings": warnings,
    }


def _sig_id(name, graph):
    """신호 참조 → 노드 id. 그래프 입력이면 in: 접두를 붙인다."""
    return f"in:{name}" if name in graph.inputs else name
