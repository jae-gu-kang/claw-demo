"""3단 폐루프 — 처방 부분공간 한정 스윕: 게인을 실제로 흔들어 6DOF 재시뮬하고
설계 지표(pipeline.metrics)의 Δ를 잰다. influence.py 머리말의 `closedloop_sweep`
이름 계약을 이 파일이 구현한다.

전 게인 공간이 아니라 **진단(pipeline.diagnose)이 처방한 손잡이만** 흔든다 —
케이스 × 런 비용은 곱이라, "무엇을"이 먼저 좁혀져야 "얼마나"가 감당된다.

표준 진단 기동(probe_mission)의 수치는 fcl/autopilot.py 설계 스캔 기동
(고도 +100 m · 속도 +10 m/s · 헤딩 0.5 rad)의 정본화다 — 재기술이 아니라
그 기동으로 재야 설계 성능 문구("오버슈트 8.3%")와 같은 자에 놓인다.

쌍(A, B, A+B) 3점의 비가산성 dAB − (dA + dB)가 "동시에 바꿔야 하는가"의 정량
답이다 — 0이면 독립(따로 튜닝 가능), 크면 상호작용(같이 움직여야 한다).

기준런(base)이 부수 산출물로 나온다 — 케이스 격자로 돌리면 그대로
diagnose_grid(규칙 4 국소성)의 입력이 된다.
"""

from dataclasses import dataclass

import numpy as np

from claw.guidance import Guidance, ModeSpec
from claw.nav import NavErrorModel
from claw.pipeline.influence import Shape, apply_param, make_law, param_universe
from claw.pipeline.metrics import metric_values
from claw.plant import make_demo_db_ranges, make_demo_stall_table
from claw.sim import Simulator

# 설계 스캔 기동 수치 (fcl/autopilot.py 머리말) — probe_mission 기본값
PROBE_DV = 10.0  # m/s
PROBE_DH = 100.0  # m
PROBE_DPSI = 0.5  # rad
DEFAULT_SPAN = (-0.2, -0.1, 0.1, 0.2)  # 상대 스팬 — ±10·20%
PAIR_STEP = 0.1  # 쌍 3점의 공통 스텝
ZERO_STEP = 0.01  # 기준값 0의 절대 스텝 (probe_value의 zero_step과 같은 이유)


@dataclass(frozen=True)
class RunSpec:
    """스윕 런 하나 — overrides는 {ParamRef id: 절대값} (apply_param 경로)."""

    label: str
    overrides: dict
    role: str  # 'base' | 'single' | 'pair'


def probe_mission(tr, *, dv=PROBE_DV, dh=PROBE_DH, dpsi=PROBE_DPSI,
                  t_settle=5.0, t_step=30.0):
    """표준 진단 기동 — 정착 → 고도 스텝 → 속도 스텝 → 헤딩 스텝 → (modes, t_end).

    시작점은 트림 케이스 그 자체(속도 V0·고도 alt0)라 케이스 격자 어디서든 같은
    모양의 스텝이 된다 — 케이스 간 지표 비교(국소성 판정)가 성립하는 전제다.
    """
    V0 = float(np.linalg.norm(tr.state.vel_b))
    alt0 = float(tr.case.alt)
    modes = [
        ModeSpec(name="settle", speed=V0, alt=alt0, heading=0.0,
                 exit_when=("time_ge", float(t_settle)), next="alt_step"),
        ModeSpec(name="alt_step", speed=V0, alt=alt0 + dh, heading=0.0,
                 exit_when=("time_ge", float(t_step)), next="spd_step"),
        ModeSpec(name="spd_step", speed=V0 + dv, alt=alt0 + dh, heading=0.0,
                 exit_when=("time_ge", float(t_step)), next="hdg_step"),
        ModeSpec(name="hdg_step", speed=V0 + dv, alt=alt0 + dh, heading=dpsi,
                 exit_when=("time_ge", 1e9)),
    ]
    return modes, float(t_settle) + 3.0 * float(t_step)


def _value_at(ref, s, notes):
    """기준값에서 상대 스팬 s만큼 움직인 절대값 — 0 기준은 절대 스텝, 범위는 클립.

    클립으로 기준값과 같아지면 None (무의미 런을 조용히 돌리지 않는다).
    """
    v0 = float(ref.value)
    v = v0 + (abs(v0) if v0 != 0.0 else ZERO_STEP) * float(s)
    if ref.lo is not None and v < ref.lo:
        notes.append(f"{ref.id}@{s:+g}: 하한 {ref.lo}로 클립")
        v = ref.lo
    if ref.hi is not None and v > ref.hi:
        notes.append(f"{ref.id}@{s:+g}: 상한 {ref.hi}로 클립")
        v = ref.hi
    if v == v0:
        notes.append(f"{ref.id}@{s:+g}: 범위가 섭동을 허용하지 않아 제외")
        return None
    return v


def sweep_plan(shape: Shape, knobs, pairs=(), *, span=DEFAULT_SPAN,
               pair_step=PAIR_STEP) -> dict:
    """처방 손잡이 → 스윕 계획: base + 단독 스팬 + 쌍(A, B, A+B) 3점.

    쌍의 단독 점이 스팬과 겹치면 라벨을 공유해 재실행하지 않는다 — 런 수가 곧
    비용이다. 반환: {"runs": [RunSpec], "pairs": [{a, b, ab, knobs}], "notes"}.
    """
    universe = {r.id: r for r in param_universe(shape)}
    wanted = list(dict.fromkeys([*knobs, *(k for p in pairs for k in p)]))
    unknown = [k for k in wanted if k not in universe]
    if unknown:
        raise ValueError(f"알 수 없는 파라미터 id: {unknown}")

    notes: list = []
    runs: dict[str, RunSpec] = {"base": RunSpec("base", {}, "base")}

    def single(pid, s, role):
        label = f"{pid}@{s:+g}"
        if label in runs:
            return label
        v = _value_at(universe[pid], s, notes)
        if v is None:
            return None
        runs[label] = RunSpec(label, {pid: v}, role)
        return label

    for pid in knobs:
        for s in span:
            single(pid, s, "single")

    pair_out = []
    for a, b in pairs:
        la = single(a, pair_step, "pair")
        lb = single(b, pair_step, "pair")
        if la is None or lb is None:
            notes.append(f"쌍 ({a}, {b}): 단독 점 구성 불가 — 제외")
            continue
        lab = f"{a}&{b}@{pair_step:+g}"
        if lab not in runs:
            runs[lab] = RunSpec(
                lab,
                {**runs[la].overrides, **runs[lb].overrides},
                "pair",
            )
        pair_out.append({"a": la, "b": lb, "ab": lab, "knobs": [a, b]})

    return {"runs": list(runs.values()), "pairs": pair_out, "notes": notes}


def nonadditivity(m0, mA, mB, mAB) -> dict:
    """지표별 dAB − (dA + dB) — 0이면 두 손잡이는 이 지표에 독립, 크면 상호작용.

    네 값 중 하나라도 없으면 None — 판정 불가를 0(독립)으로 위장하지 않는다.
    """
    out = {}
    for key in m0:
        vals = (m0.get(key), mA.get(key), mB.get(key), mAB.get(key))
        if any(v is None for v in vals):
            out[key] = None
            continue
        v0, va, vb, vab = (float(v) for v in vals)
        out[key] = (vab - v0) - ((va - v0) + (vb - v0))
    return out


def run_sweep(aircraft, trs, shape: Shape, plan, *, dt_plant=0.01,
              t_settle=5.0, t_step=30.0, dv=PROBE_DV, dh=PROBE_DH,
              dpsi=PROBE_DPSI, on_progress=None) -> dict:
    """스윕 실행 — 케이스별 트림해에서 (base + 처방 런)을 표준 기동으로 재시뮬.

    행마다 지표(metric_values)와 형상 지문(apply_param 반영본)이 실린다 — 어느
    형상의 수치인지가 계보다. on_progress(done, total): 런 단위, truthy 반환은
    협조적 취소로 완료 런을 보존한다 (margin-map 패턴).
    """
    universe = {r.id: r for r in param_universe(shape)}
    runs = list(plan["runs"])
    shapes = {}
    for spec in runs:
        s = shape
        for pid, v in spec.overrides.items():
            if pid not in universe:
                raise ValueError(f"알 수 없는 파라미터 id: {pid}")
            s = apply_param(s, universe[pid], float(v))
        shapes[spec.label] = s

    stall = make_demo_stall_table()
    db_ranges = make_demo_db_ranges()
    good = [tr for tr in trs if tr.converged]
    warnings = [f"미수렴 트림 케이스 건너뜀: {tr.case.name}"
                for tr in trs if not tr.converged]
    rows: list = []
    aborted = None
    total = len(good) * len(runs)
    done = 0
    for tr in good:
        modes, t_end = probe_mission(tr, dv=dv, dh=dh, dpsi=dpsi,
                                     t_settle=t_settle, t_step=t_step)
        for spec in runs:
            s = shapes[spec.label]
            sim = Simulator(
                aircraft=aircraft,
                fcl=make_law(s),
                guidance=Guidance([ModeSpec(**vars(m)) for m in modes]),
                nav_model=NavErrorModel(**s.nav) if s.nav else None,
                stall_table=stall,
                db_ranges=db_ranges,
                dt_plant=dt_plant,
                control_hz=s.control_hz,
                actuator_params=s.actuators or None,
            )
            res = sim.run(tr, t_end=t_end, fingerprint=s.fingerprint())
            rows.append({
                "case": tr.case.name,
                "label": spec.label,
                "role": spec.role,
                "overrides": dict(spec.overrides),
                "fingerprint": s.fingerprint(),
                "aborted": res.meta["aborted"],
                "metrics": metric_values(res.t, res.signals, res.envelope, res.meta),
            })
            done += 1
            if on_progress is not None and on_progress(done, total):
                aborted = "cancelled"
                break
        if aborted:
            break

    return {
        "fingerprint": shape.fingerprint(),
        "rows": rows,
        "pairs": list(plan.get("pairs") or ()),
        "notes": list(plan.get("notes") or ()),
        "warnings": warnings,
        "aborted": aborted,
    }
