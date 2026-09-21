"""3단 폐루프 — 처방 부분공간 한정 스윕: 게인을 실제로 흔들어 6DOF 재시뮬하고
설계 지표(pipeline.metrics)의 Δ를 잰다. influence.py 머리말의 `closedloop_sweep`
이름 계약을 이 파일이 구현한다.

전 게인 공간이 아니라 **진단(pipeline.diagnose)이 처방한 설계변수만** 흔든다 —
케이스 × 런 비용은 곱이라, "무엇을"이 먼저 좁혀져야 "얼마나"가 감당된다.

표준 진단 기동(probe_mission)의 수치는 **더 이상 fcl/autopilot.py 설계 스캔 기동을
그대로 쓰지 않는다** (v0.72). 그 기동(고도 +100 m · 속도 +10 m/s · 헤딩 0.5 rad)으로
재야 설계 성능 문구("오버슈트 8.3%")와 같은 자에 놓인다는 것이 종전 근거였는데,
그 비교는 이미 깨져 있었다 — fcl/demo.py 머리말대로 프로펠러 추력 모델 이후 그
설계점은 엔벨로프 밖이고(스로틀 95.04 % > SAT_FRAC 0.95), 그 상태에서 재는 추종
RMS는 제어 품질이 아니라 물리 한계다. 현행 수치와 근거는 PROBE_* 상수 주석에 있다.

쌍(A, B, A+B) 3점의 비가산성 dAB − (dA + dB)가 "동시에 바꿔야 하는가"의 정량
답이다 — 0이면 독립(따로 튜닝 가능), 크면 상호작용(같이 움직여야 한다).

기준런(base)이 부수 산출물로 나온다 — 케이스 격자로 돌리면 그대로
diagnose_grid(규칙 4 국소성)의 입력이 된다.
"""

from dataclasses import dataclass

import numpy as np

from claw.guidance import Guidance, ModeSpec
from claw.nav import NavErrorModel
from claw.pipeline.influence import Shape, apply_param, make_law, param_universe, shape_profile
from claw.pipeline.metrics import metric_values
from claw.sim import Simulator

# 표준 진단 기동의 스텝 — 오차가 **물리 한계가 아니라 제어 품질**을 재도록 (v0.72).
#
# 계측(데모 기체 M0.6/h1000, t_settle 5 · t_step 30):
#
#   스텝            고도RMS  속도RMS  고도Ts  속도Ts  추력포화
#   dh100·dv10·0.5   22.17    7.95    70.4 s    ∞     93.6 %
#   dh 30·dv 3 ·0.3   6.65     1.28    71.0 s    ∞     76.4 %
#
# **이 표는 t_step 30에서 쟀고, 화면 기본값은 15다**(web lib/grid.js·stepIn).
# 간격이 짧으면 축이 더 겹쳐 값이 나빠진다 — 같은 스텝·t_step 15에서 고도 9.17 ·
# 속도 1.94(기준 2에 여유 3 %) · 포화 85.0 %다. 판정이 기본 경로에서 아슬한
# 자리이므로, 기준을 볼 때 어느 간격의 수인지 함께 봐야 한다
#
# 종전 값은 이 기체의 추력을 넘었다: 트림 스로틀 0.950(여유 5 %)에서 +10 m/s를
# 60초에 2.5 m/s밖에 못 따라가, 추종 RMS가 **제어 품질이 아니라 물리 한계**를 쟀다.
# 게인을 고쳐도 안 움직이고(포화 뒤에서 루프 게인은 무력하다) 처방은 "스팬 안에
# 교차 없음"이라고만 답한다. 스텝을 줄이면 오차 크기와 포화 비율이 함께 준다.
#
# **줄여서 통과시킨 것이 아니다.** 능력을 넘었다는 사실은 「추력 여유」 판정
# (CHECKS의 thr_margin)이 계속 보고한다 — 이 스텝에서도 여유 0으로 fail이다.
#
# **축 겹침은 이 변경으로 안 고쳐진다.** 고도 정착이 70.4 → 71.0 s로 그대로다
# (정착 시간은 스텝 크기가 아니라 이 기체의 상승 능력이 정한다). t_step 30 s는
# 그보다 짧아 다음 축이 정착 전에 온다. 간격을 90 s로 늘리면 속도가 처음으로
# 정착하고(Ts ∞ → 117.7 s) 포화도 32.8 %로 떨어지지만 런 길이가 95 → 275 s로
# 3배가 된다 — 비용 결정이라 [TBD]로 남긴다. 그때까지 "창 안에 정착하지 않는다"는
# 사실은 카드 5(과도응답)의 Ts가 ∞로 보고한다.
PROBE_DV = 3.0  # m/s
PROBE_DH = 30.0  # m
PROBE_DPSI = 0.3  # rad
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


def schedule_crossing_scenario(tables, cases):
    """게인 스케줄을 시간축으로 가로지르는 시나리오 좌표 — 표·격자에서만 유도 (04 §5.5).

    점 동결 평가(판정 10의 dK/dV·3단계 중간점)가 못 보는 것이 "게인이 보간으로
    움직이는 **동안**"이고, 표준 기동(probe_mission)의 스텝(dh 30 m·dv 3 m/s)은
    breakpoint 간격보다 작아 스케줄을 못 가로지른다. 여기서는 스케줄 표의
    breakpoint(Table.axes ∪ PolyTable.knots — 다항의 knot도 구간 전환점이다)를
    요청 케이스 격자 범위로 클립한 뒤, 범위 중앙에 가장 가까운 인접쌍 (b1, b2)를
    골라 b1−½Δ → b2+½Δ(범위 클립)의 통과 구간을 만든다 — 전 수치가 표·격자에서
    나온다 (특정 기체 전제 금지).

    mach 축은 가속, alt 축은 상승으로 가로지른다(둘 다 있으면 가속 → 상승 연쇄).
    fuel 축은 명령으로 움직일 수 없어(연료는 소모 상태) 시나리오가 없다 — notes에
    사유를 남긴다. 가로지를 축이 없으면 None — 호출자가 na + 사유로 낸다.

    **여유 없는 쌍은 그 축의 레그를 아예 안 낸다**(리뷰 지적). breakpoint가 범위 안에
    딱 둘뿐이고 그 상한이 격자 상한과 겹치면(작은 스케줄에서 자연스러운 형상) target을
    만들 여유가 없다 — 억지로 만들면 격자 밖을 명령하거나(검증 대상 밖) exit 문턱이
    명령 목표와 같아져(점근 접근으로 영영 발화 못 함) 둘 다 이 함수의 다른 불변식을
    깬다. 그 축은 `None`으로 두고, 다른 축에 레그가 있으면 그 축만으로 진행한다(둘 다
    없으면 위 문단대로 전체가 None).
    """
    machs = sorted({float(c.mach) for c in cases})
    alts = sorted({float(c.alt) for c in cases})
    fuels = sorted({float(c.fuel) for c in cases})
    if not machs or not alts or not fuels:
        return None

    def axis_bps(axis, lo, hi):
        bps = set()
        for tab in (tables or {}).values():
            names = tuple(tab.axis_names)
            if axis not in names:
                continue
            # 다축 Table도 그 축의 격자점은 전환점이다 — 1축만 보면 파라미터 장입 경로의
            # 다축 스케줄(blocks/lookup.py)이 "미장착"으로 오독된다 (리뷰 지적).
            # PolyTable은 1D뿐이라 knots는 names == (axis,)일 때만 온다
            coords = getattr(tab, "knots", None)
            if coords is None:
                coords = tab.axes[names.index(axis)]
            bps.update(float(x) for x in np.asarray(coords).ravel())
        return sorted(b for b in bps if lo <= b <= hi)

    def pick(bps, lo, hi):
        if len(bps) < 2:
            return None
        mid = 0.5 * (lo + hi)

        def key(k):
            # b2가 격자 상한이면 목표 초과 여유가 없어(target==b2) exit가 영영 발화
            # 못 한다 — 여유 있는 쌍이 있으면 그쪽을 우선한다 (리뷰 지적: 그 격자에선
            # mission_profile이 구조적으로 통과 판정을 못 내는 상태가 된다)
            return (1 if bps[k + 1] >= hi else 0,
                    abs(0.5 * (bps[k] + bps[k + 1]) - mid))

        i = min(range(len(bps) - 1), key=key)
        b1, b2 = bps[i], bps[i + 1]
        if b2 >= hi:
            # 여유 있는 쌍이 있으면 key()가 이미 그쪽을 골랐다 — 그런데도 b2가 여전히
            # 격자 상한이면 대안이 없었던 것이다(breakpoint가 딱 둘, 범위 양끝에 걸침 —
            # 작은 스케줄에서 자연스러운 형상이다). 그 상태로 target을 억지로 만들면
            # 격자 밖을 명령하게 되고(밖은 검증 대상이 아니다), 그렇다고 target==b2로
            # 두면 exit 문턱이 명령 목표와 같아져 점근 접근으로 영영 발화 못 한다
            # (exit_short_of 쪽에서 고치면 문턱이 명령 목표를 넘어서 버려 형태만 바뀐
            # 같은 증상이 된다 — 리뷰 지적, 실측 재현: 2-breakpoint 표가 케이스
            # 격자와 정확히 겹치는 최소 스케줄). 이 격자로는 이 축의 통과를 여유 있게
            # 확인할 수 없다는 뜻이므로 정직하게 레그를 안 낸다 — 다른 축에 레그가
            # 있으면 그 축만으로 진행하고, 없으면 호출자가 시나리오 자체를 없음으로
            # 받아 na + 사유로 낸다
            return None
        half = 0.5 * (b2 - b1)
        return {"pair": (b1, b2),
                "start": max(lo, b1 - half), "target": min(hi, b2 + half)}

    m = pick(axis_bps("mach", machs[0], machs[-1]), machs[0], machs[-1])
    a = pick(axis_bps("alt", alts[0], alts[-1]), alts[0], alts[-1])
    if m is None and a is None:
        return None
    notes = []
    if any("fuel" in tuple(tab.axis_names) for tab in (tables or {}).values()):
        notes.append("fuel 축 스케줄은 시간축 통과 시나리오가 없다 — "
                     "연료는 명령이 아니라 소모 상태다")
    return {
        "mach": m, "alt": a,
        # 시작점: 가로지르는 축은 그 축의 start, 아닌 축은 격자 중앙(대표 조건)
        "start": {
            "mach": m["start"] if m is not None else machs[len(machs) // 2],
            "alt": a["start"] if a is not None else alts[len(alts) // 2],
            "fuel": fuels[len(fuels) // 2],
        },
        "notes": notes,
    }


def schedule_crossing_mission(tr, scenario, *, t_settle=5.0, t_step=30.0,
                              t_mission=None):
    """시나리오 좌표 + 시작점 트림해 → (modes, t_end) — probe_mission의 형제.

    가속·상승 목표는 TAS로 명령한다(유도 speed 규약) — mach 목표는 그 페이즈 고도의
    ISA 음속으로 환산. 페이즈 exit는 상태 기반(speed_ge·alt_ge)이고 문턱은 마지막
    breakpoint 너머, **항상 b2보다 엄격히 위**다(`exit_short_of`, min(b2+¼Δ,
    b2+½(target−b2))). 격자 상한이 target 자체를 b2까지 눌러 버리는 극단(2-breakpoint
    표가 케이스 격자 상하한과 정확히 겹치는 최소 스케줄 등)에서는 target > b2가
    깨지므로 exit_short_of가 손댈 자리가 아니다 — 그 경우는 pick()이 애초에 그 축의
    레그를 None으로 걸러 이 함수까지 오지 않는다(리뷰 지적, 종전엔 exit_short_of 안에서
    무조건 문턱을 내리눌러 exit == target이 되는 자리가 뚫려 있었다).
    천장 t_end 안에 못 넘으면 시뮬은 거기서 끝날 뿐이고, 통과 여부는 호출자가
    mach/alt **시계열로 실측**한다 (Ts=∞ 패턴).

    t_end 천장 [기본값]: t_settle + 페이즈당 8×t_step + 정착 t_step — 실측(데모 기체
    1000 m, breakpoint 간격 0.05 mach): 한 구간 통과 가속이 표준 기동 스텝(dv 3 m/s)
    의 10배가 넘는 속도 변화라 3×t_step로는 반도 못 간다. t_mission이 천장을 덮는다.
    """
    from claw.env import isa_atmosphere

    V0 = float(np.linalg.norm(tr.state.vel_b))
    alt0 = float(tr.case.alt)
    m, a = scenario.get("mach"), scenario.get("alt")
    if m is None and a is None:
        raise ValueError("가로지를 레그가 없는 시나리오 — schedule_crossing_scenario가 "
                         "None을 낸 경우는 미션을 만들지 않는다")

    def exit_short_of(b1, b2, target):
        # 넘은 것을 확인할 문턱: b2보다 위, 명령 목표보다 엄격히 아래. target==b2인
        # 여유 없는 쌍은 pick()이 애초에 레그를 안 낸다(리뷰 지적 — 여기서 손대면
        # 문턱이 명령 목표 자체를 넘어서 버려 "역시 영영 발화 못 함"이 형태만 바뀐다.
        # 격자 밖을 명령하지 않는 한 이 함수 혼자서는 못 고치는 자리라, 여유가 있는
        # target(target > b2)만 이 함수에 들어온다는 것이 호출자 쪽 불변식이다)
        return b2 + min(0.25 * (b2 - b1), 0.5 * max(target - b2, 0.0))

    phases = []
    speed = V0
    if m is not None:
        b1, b2 = m["pair"]
        sos = isa_atmosphere(alt0).a  # 가속은 시작 고도에서 — 상승 전이다
        speed = float(m["target"] * sos)
        phases.append(("accel", {
            "speed": speed, "alt": alt0, "heading": 0.0,
            "exit_when": ("speed_ge", float(exit_short_of(b1, b2, m["target"]) * sos)),
        }))
    if a is not None:
        b1, b2 = a["pair"]
        phases.append(("climb", {
            "speed": speed, "alt": float(a["target"]), "heading": 0.0,
            "exit_when": ("alt_ge", float(exit_short_of(b1, b2, a["target"]))),
        }))

    modes = [ModeSpec(name="settle", speed=V0, alt=alt0, heading=0.0,
                      exit_when=("time_ge", float(t_settle)),
                      next=phases[0][0])]
    for i, (name, kw) in enumerate(phases):
        nxt = phases[i + 1][0] if i + 1 < len(phases) else "hold"
        modes.append(ModeSpec(name=name, next=nxt, **kw))
    last = phases[-1][1]
    modes.append(ModeSpec(name="hold", speed=last["speed"], alt=last["alt"],
                          heading=0.0, exit_when=("time_ge", 1e9)))
    t_end = (float(t_mission) if t_mission is not None
             else float(t_settle) + (8.0 * len(phases) + 1.0) * float(t_step))
    return modes, t_end


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
    """처방 설계변수 → 스윕 계획: base + 단독 스팬 + 쌍(A, B, A+B) 3점.

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
    """지표별 dAB − (dA + dB) — 0이면 두 설계변수는 이 지표에 독립, 크면 상호작용.

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


def plan_shapes(shape: Shape, plan) -> dict:
    """계획 → {런 라벨: 형상}. run_sweep이 실행 전에 쓰고, **서버가 제출 시점 검증에도 쓴다**.

    분리해 둔 이유: 잡 안에서 형상을 만들다 터지면 이미 돌린 런이 통째로 버려진다.
    파라미터 id 오타·기체와 안 맞는 형상은 202를 주기 전에 알 수 있어야 한다
    (routes/influence.py의 "무의미 구성은 제출 시점 422" 계약).
    """
    universe = {r.id: r for r in param_universe(shape)}
    shapes = {}
    for spec in plan["runs"]:
        s = shape
        for pid, v in spec.overrides.items():
            if pid not in universe:
                raise ValueError(f"알 수 없는 파라미터 id: {pid}")
            s = apply_param(s, universe[pid], float(v))
        shapes[spec.label] = s
    return shapes


def run_sweep(aircraft, trs, shape: Shape, plan, *, dt_plant=0.01,
              t_settle=5.0, t_step=30.0, dv=PROBE_DV, dh=PROBE_DH,
              dpsi=PROBE_DPSI, on_progress=None) -> dict:
    """스윕 실행 — 케이스별 트림해에서 (base + 처방 런)을 표준 기동으로 재시뮬.

    행마다 지표(metric_values)와 형상 지문(apply_param 반영본)이 실린다 — 어느
    형상의 수치인지가 계보다. on_progress(done, total): 런 단위, truthy 반환은
    협조적 취소로 완료 런을 보존한다 (margin-map 패턴).
    """
    runs = list(plan["runs"])
    shapes = plan_shapes(shape, plan)

    profile = shape_profile(shape)
    stall = profile.stall_table()
    db_ranges = profile.db_ranges()
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
