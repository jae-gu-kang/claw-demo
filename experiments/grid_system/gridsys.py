"""격자 체계 첫 실험의 최소 구현 (05 §11.10) — **실험 코드다. 제품 패키지(claw)에 두지 않는다.**

05 §11의 목표 구조(운용영역 · 조건 상태 · 설계점 · 표별 절점 · 검증점 · 트림 저장소 · 결과 요약)를
임시 데이터 형식으로 세워, 튜닝 방식을 건드리지 않고 **격자 연결**이 맞는지만 확인한다. 게인은
기체 문서의 스케줄 표에서 절점 값을 뽑은 **샘플 표**다 — 튜닝 결과가 아니다.

엔진에서 빌려 쓰는 것은 트림(`trim_level`) · 선형화(`LinearModelSet`) · 스케줄 인지 판정
(`schedmap.scheduled_margin_point`) · 표(`Table`)뿐이다. 판정선은 기체 프로파일 기준(04)을 그대로
참조하고 이 모듈은 수치를 갖지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# ── 조건 상태 (05 §11.3) — 위에서부터 판정 ────────────────────────────────────
OUT_OF_REGION = "out_of_region"  # 요구영역 밖
UNDEFINED = "undefined"  # 요구 미정의 — 경계표가 덮지 않음
MODEL_GAP = "model_gap"  # 모델 부족
CALC_FAILED = "calc_failed"  # 계산 실패 (트림 미수렴)
INFEASIBLE = "infeasible"  # 물리적 불가 (α 여유·포화 — 사유 전량)
COMPUTABLE = "computable"  # 계산 가능 (계산 완료)
NOT_RUN = "not_run"  # 미계산
STATE_LABEL = {
    OUT_OF_REGION: "요구영역 밖", UNDEFINED: "요구 미정의", MODEL_GAP: "모델 부족",
    CALC_FAILED: "계산 실패", INFEASIBLE: "물리적 불가", COMPUTABLE: "완료", NOT_RUN: "미계산",
}

# ── 성능 판정 어휘 (04 판정 상태 — 기준 통합 ①) ────────────────────────────────
FAIL, CAUTION, GOOD, NA = "불합격", "합격·주의", "합격·권장 충족", "판정 불가"
_STATUS_TO_VERDICT = {"fail": FAIL, "warn": CAUTION, "ok": GOOD}
_VERDICT_RANK = {FAIL: 3, NA: 2, CAUTION: 1, GOOD: 0}

_EPS = 1e-9


# ── 비행조건 (05 §11.3) ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class Condition:
    mach: float
    alt: float  # [m]
    fuel: float  # [kg] — 식별자는 kg (% 입력은 호출자가 fuel_max로 환산)
    config: str = "base"  # 형상 모드 — 첫 구현은 하나, 자리만
    steady: str = "level_1g"  # 정상비행 상태

    @property
    def name(self) -> str:
        # 값 그대로 문자열화 (웹 nameCases 원칙 — 반올림 이름은 정밀 격자에서 겹친다)
        base = f"M{self.mach!r}_h{self.alt!r}_f{self.fuel!r}"
        extra = [s for s, d in ((self.config, "base"), (self.steady, "level_1g")) if s != d]
        return "_".join([base, *extra])


# ── 운용영역 (05 §11.2) ───────────────────────────────────────────────────────
@dataclass
class Region:
    """요구 운용영역 — 기본 범위 + 선택적 조건별 경계표.

    boundary: {fuel_kg: [(alt, mach_lo, mach_hi), ...]} — 연료 층마다 고도 행. 행 사이·층 사이는
    선형 보간. 표가 덮지 않는 (alt, fuel)은 요구 미정의다 — 가까운 행으로 늘리지 않는다.
    """

    mach: tuple
    alt: tuple
    fuel: tuple
    boundary: dict | None = None
    confirmed: bool = True  # 초안(trim_grid에서 제안)은 False — 판정에 쓰지 않는다
    source: str = "user"

    def mach_bounds(self, alt: float, fuel: float):
        """(lo, hi) 또는 None(요구 미정의)."""
        if not self.boundary:
            return tuple(self.mach)
        layers = sorted(self.boundary)
        if not (layers[0] - _EPS <= fuel <= layers[-1] + _EPS):
            return None

        def layer_bounds(f):
            rows = sorted(self.boundary[f])
            alts = [r[0] for r in rows]
            if not (alts[0] - _EPS <= alt <= alts[-1] + _EPS):
                return None
            return (float(np.interp(alt, alts, [r[1] for r in rows])),
                    float(np.interp(alt, alts, [r[2] for r in rows])))

        # 층 값 그대로의 연료는 그 층만 본다 — 이웃 층까지 요구하면 이웃이 안 덮는 고도가 미정의로 둔갑한다
        on = [f for f in layers if abs(fuel - f) <= _EPS]
        if on:
            return layer_bounds(on[0])
        j = int(np.searchsorted(layers, fuel, side="right")) - 1
        j = min(max(j, 0), len(layers) - 2)
        f0, f1 = layers[j], layers[j + 1]
        b0, b1 = layer_bounds(f0), layer_bounds(f1)
        if b0 is None or b1 is None:
            return None
        t = (fuel - f0) / (f1 - f0)
        return (b0[0] + t * (b1[0] - b0[0]), b0[1] + t * (b1[1] - b0[1]))

    def classify(self, c: Condition) -> str | None:
        """요구영역 판정 — OUT_OF_REGION | UNDEFINED | None(안)."""
        for v, (lo, hi) in ((c.mach, self.mach), (c.alt, self.alt), (c.fuel, self.fuel)):
            if v < lo - _EPS or v > hi + _EPS:
                return OUT_OF_REGION
        b = self.mach_bounds(c.alt, c.fuel)
        if b is None:
            return UNDEFINED
        if c.mach < b[0] - _EPS or c.mach > b[1] + _EPS:
            return OUT_OF_REGION
        return None


def region_draft_from_trim_grid(trim_grid: dict) -> Region:
    """기존 trim_grid(계산할 점 목록)에서 요구영역 **초안** — 미확정이라 판정에 쓰지 않는다 (05 §11.2)."""
    m = trim_grid["mach"]
    return Region(mach=(float(m["from"]), float(m["to"])),
                  alt=(float(min(trim_grid["alt"])), float(max(trim_grid["alt"]))),
                  fuel=(float(min(trim_grid["fuel"])), float(max(trim_grid["fuel"]))),
                  confirmed=False, source="draft:trim_grid")


@dataclass
class ModelRange:
    """모델 유효영역 — 요구영역과 따로 보관한다 (05 §11.2)."""

    mach: tuple  # aero.db_ranges.mach
    fuel: tuple  # 질량 모델 범위 [0, fuel_max]

    def covers(self, c: Condition) -> bool:
        return (self.mach[0] - _EPS <= c.mach <= self.mach[1] + _EPS
                and self.fuel[0] - _EPS <= c.fuel <= self.fuel[1] + _EPS)


# ── 설계점 (05 §11.4) ─────────────────────────────────────────────────────────
@dataclass
class DesignPoint:
    cond: Condition
    origin: str  # user | auto:grid | auto:plant_distance | promoted:<검증점>
    pinned: bool = False


def auto_design_points(region: Region, *, n_mach: int, alts, fuels) -> list:
    """요구영역에서 설계점 자동 생성 — 행마다 그 행의 요구 마하 범위를 n_mach 등분 (편의 규칙)."""
    out = []
    for fuel in fuels:
        for alt in alts:
            b = region.mach_bounds(alt, fuel)
            if b is None:
                continue
            for m in np.linspace(b[0], b[1], n_mach):
                out.append(DesignPoint(Condition(float(m), float(alt), float(fuel)), "auto:grid"))
    return out


def design_links(design_points, bp_union) -> dict:
    """설계점 → 절점·구간 열 연결 개수 — 저장하지 않는 파생값 (05 §11.4). 열 이름은 요약 격자와 같다."""
    out: dict = {}
    for d in design_points:
        k = column_of(d.cond.mach, bp_union)
        out[k] = out.get(k, 0) + 1
    return out


# ── 스케줄 절점과 표 (05 §11.5) ───────────────────────────────────────────────
@dataclass
class BreakpointSet:
    name: str
    axis: str  # 첫 적용은 "mach"
    coords: tuple

    def __post_init__(self):
        c = tuple(float(x) for x in self.coords)
        if len(c) < 2 or any(b <= a for a, b in zip(c, c[1:])):
            raise ValueError(f"절점 집합 {self.name}: 순증가 2점 이상 필요 {c}")
        self.coords = c


@dataclass
class Schedule:
    """표별 절점 참조 — bp_sets {이름: BreakpointSet}, refs {게인: 집합 이름}, values {게인: 절점별 값}."""

    bp_sets: dict
    refs: dict
    values: dict

    def sharing(self) -> dict:
        """게인마다 공유/독립 — 같은 집합을 다른 게인도 참조하면 공유."""
        users: dict = {}
        for g, s in self.refs.items():
            users.setdefault(s, []).append(g)
        return {g: ("shared" if len(users[s]) > 1 else "independent") for g, s in self.refs.items()}

    def tables(self) -> dict:
        from claw.tables import Table

        return {g: Table({self.bp_sets[s].axis: self.bp_sets[s].coords}, self.values[g],
                         name=g, extrapolate="clip")
                for g, s in self.refs.items()}

    def union_coords(self, gains=None) -> tuple:
        """평가 대상 표들의 절점 합집합 — 검증 마하 구간의 경계 (05 §11.6 ①)."""
        gains = self.refs if gains is None else gains
        return tuple(sorted({x for g in gains for x in self.bp_sets[self.refs[g]].coords}))


def sample_schedule(built, bp_sets: dict, refs: dict) -> Schedule:
    """샘플 게인 표 — 기체 문서의 스케줄 표를 각 절점에서 평가한 값 (튜닝 결과가 아니다)."""
    src = built.gain_tables(names=tuple(refs))
    values = {g: [float(src[g].interp(mach=x)) for x in bp_sets[s].coords] for g, s in refs.items()}
    return Schedule(bp_sets=bp_sets, refs=dict(refs), values=values)


# ── 검증점 (05 §11.6) ─────────────────────────────────────────────────────────
@dataclass
class ValidationPoint:
    cond: Condition
    kind: str  # breakpoint | midpoint | clip | boundary | extra
    row: tuple | None  # (alt, fuel) 검증 조합 — 경계·추가는 None
    origin: str


@dataclass
class ValidationSpec:
    alts: tuple
    fuels: tuple  # kg
    n_between: int = 1
    mode: str = "full"  # full | representative
    extras: tuple = ()  # ((Condition, 출처), ...)


def _interior(a, b, n):
    ks = sorted(range(1, n + 1), key=lambda k: abs(2 * k - (n + 1)))  # 중점 우선
    return [a + (b - a) * k / (n + 1.0) for k in ks]


def validation_machs(bp_union, region_mach, n_between=1):
    """[(마하, kind)] — 절점 · 구간 내분점 · clip 구간(요구영역이 첫·끝 절점 밖으로 뻗은 부분)."""
    out = [(x, "breakpoint") for x in bp_union]
    for a, b in zip(bp_union, bp_union[1:]):
        out += [(m, "midpoint") for m in _interior(a, b, n_between)]
    lo, hi = region_mach
    if lo < bp_union[0] - _EPS:
        out.append(((lo + bp_union[0]) / 2.0, "clip"))
    if hi > bp_union[-1] + _EPS:
        out.append(((bp_union[-1] + hi) / 2.0, "clip"))
    return out


def _representative(vals):
    s = sorted(set(vals))
    return sorted({s[0], s[-1], s[(len(s) - 1) // 2]})


def generate_validation(region: Region, schedule: Schedule, spec: ValidationSpec, gains=None) -> dict:
    """검증점 후보 + 생략 목록 — {"points", "omitted", "union"}. 상태 판정은 evaluate가 한다."""
    union = schedule.union_coords(gains)
    machs = validation_machs(union, region.mach, spec.n_between)
    rows = [(float(a), float(f)) for f in spec.fuels for a in spec.alts]
    omitted = []
    if spec.mode == "representative":
        keep_a, keep_f = _representative(spec.alts), _representative(spec.fuels)
        omitted = [r for r in rows if not (r[0] in keep_a and r[1] in keep_f)]
        rows = [r for r in rows if r not in omitted]
    pts, seen = [], set()

    def add(vp):
        if vp.cond.name not in seen:
            seen.add(vp.cond.name)
            pts.append(vp)

    for alt, fuel in rows:
        for m, kind in machs:
            add(ValidationPoint(Condition(float(m), alt, fuel), kind, (alt, fuel), kind))
    # 요구영역 경계점 — 행별 마하 하한·상한 (05 §11.6 ⑥). 행 = 기본 범위 끝값 + 경계표의 층·행
    # (끝값만 쓰면 경계표가 끝값까지 안 닿을 때 정의된 가장 높은 행이 경계점을 못 받는다)
    b_fuels = set(region.fuel) | set(region.boundary or {})
    b_alts = set(region.alt) | {r[0] for rows in (region.boundary or {}).values() for r in rows}
    for fuel in sorted(b_fuels):
        for alt in sorted(b_alts):
            b = region.mach_bounds(alt, fuel)
            if b is None:
                continue
            for m in b:
                add(ValidationPoint(Condition(float(m), float(alt), float(fuel)), "boundary", None,
                                    "boundary:region"))
    for c, src in spec.extras:
        add(ValidationPoint(c, "extra", None, f"extra:{src}"))
    return {"points": pts, "omitted": omitted, "union": union}


# ── 트림·모델 저장소 (05 §11.8) ───────────────────────────────────────────────
class TrimStore:
    """키 = 플랜트 지문 + 조건 식별자 + 트림 설정. 실패한 해도 보존한다."""

    def __init__(self):
        self._d: dict = {}
        self.computed = 0
        self.reused = 0

    def get(self, aircraft, c: Condition, *, plant_fp: str, trim_fp: str) -> dict:
        from claw.common.contracts import TrimCase
        from claw.trim import trim_level

        key = (plant_fp, c.name, trim_fp)
        if key in self._d:
            self.reused += 1
            return self._d[key]
        tr = trim_level(aircraft, TrimCase(name=c.name, mach=c.mach, alt=c.alt, fuel=c.fuel),
                        fingerprint=plant_fp)
        self._d[key] = {"tr": tr, "seed": "default"}
        self.computed += 1
        return self._d[key]

    def __len__(self):
        return len(self._d)


# ── 평가 ──────────────────────────────────────────────────────────────────────
_D_METRIC = {  # 보강 지표 d에 쓰는 자리별 대표 지표 (05 §11.7)
    "pitch_rate": "zeta", "yaw_rate": "zeta", "roll_rate": "roll_lambda",
    "pitch_att": "pm_deg", "roll_att": "pm_deg",
}


def d_scales(crit) -> dict:
    """자리별 척도 s = 목표선 − 합격선 (04 참조 — 이 모듈은 값을 갖지 않는다)."""
    m, t = crit.margin, crit.targets
    return {
        "pitch_rate": t.zeta_sp - m.zeta_min, "yaw_rate": t.zeta_dr - m.zeta_min,
        "roll_rate": t.roll_lambda * (m.lam_good_frac - m.lam_min_frac),
        "pitch_att": t.pm_deg - m.pm_min_deg, "roll_att": t.pm_deg - m.pm_min_deg,
    }


@dataclass
class Evaluator:
    built: object
    store: TrimStore
    delay_s: float = 0.035
    pade_order: int = 2
    lms: object = None
    trim_fp: str = ""
    _ctx: dict = field(default_factory=dict)

    def __post_init__(self):
        from claw.design.linmodels import LinearModelSet

        self.lms = LinearModelSet() if self.lms is None else self.lms
        b = self.built
        self.trim_fp = f"alpha_margin={b.trim_alpha_margin!r}"
        act = b.actuator_params()
        self._ctx = dict(aircraft=b.aircraft(), crit=b.eval_criteria, design=b.design_gains(),
                         act=dict(actuator_wn=act["wn"], actuator_zeta=act["zeta"], delay_s=self.delay_s,
                                  pade_order=self.pade_order, rate_filters=b.rate_filters()))

    @property
    def criteria(self):
        return self._ctx["crit"]

    def state(self, c: Condition, region: Region, model: ModelRange):
        """(조건 상태, 트림 레코드 | None, 사유). 계산 안 되는 상태는 트림을 돌리지 않는다."""
        rs = region.classify(c)
        if rs is not None:
            return rs, None, []
        if not model.covers(c):
            return MODEL_GAP, None, []
        rec = self.store.get(self._ctx["aircraft"], c, plant_fp=self.built.plant_fingerprint,
                             trim_fp=self.trim_fp)
        tr = rec["tr"]
        # 미수렴이어도 조종량·받음각이 한계에 붙어 잔차가 남았으면 물리적 불가다(추력 부족·양력 부족) — 계산 실패와
        # 가른다(05 §11.3). 한계에 안 붙었는데 미수렴이면 그때가 계산 실패다
        from claw.trim.trim import saturation_detail

        tb = self.built.trim_bounds
        sat = [ch for ch, on in saturation_detail(tr, tb["de"]).items() if on]
        # 받음각이 트림 탐색 한계에 붙은 것도 같은 뜻이다 — 양력(저속)·음의 양력 한계
        alpha = math.atan2(float(tr.state.vel_b[2]), float(tr.state.vel_b[0]))
        a_lo, a_hi = tb["alpha"]
        if alpha >= a_hi - 1e-6 or alpha <= a_lo + 1e-6:
            sat.append("alpha_limit")
        if not tr.converged:
            return (INFEASIBLE, rec, [*sat, "not_converged"]) if sat else (CALC_FAILED, rec, ["not_converged"])
        why = sat + (["alpha_margin"] if not tr.flags.get("alpha_margin_ok") else [])
        if why:
            return INFEASIBLE, rec, why
        return COMPUTABLE, rec, []

    def judge(self, c: Condition, rec, schedule: Schedule, tables=None):
        """실제 스케줄 평가 게인으로 자리별 판정 — (verdict, slots, gains)."""
        from claw.common.contracts import TrimCase
        from claw.design.schedmap import scheduled_gains, scheduled_margin_point

        x = self._ctx
        tables = schedule.tables() if tables is None else tables
        case = TrimCase(name=c.name, mach=c.mach, alt=c.alt, fuel=c.fuel)
        lm = self.lms.get(x["aircraft"], rec["tr"])
        out = scheduled_margin_point(lm, tables, x["design"], case, criteria=x["crit"].margin,
                                     targets=x["crit"].targets, **x["act"])
        gains = scheduled_gains(tables, x["design"], case)
        # 대표 지표만 실으면 원인을 가린다 — 롤 레이트는 λ가 목표를 넘어도 루프 GM 가드로 불합격한다
        slots = {slot: {"verdict": _STATUS_TO_VERDICT.get(e.get("status"), NA),
                        "metric": e.get(_D_METRIC.get(slot, "")),
                        "pm_deg": e.get("pm_deg"), "gm_db": e.get("gm_db")}
                 for slot, e in out.items()}
        verdict = max((s["verdict"] for s in slots.values()), key=_VERDICT_RANK.get) if slots else NA
        return verdict, slots, gains


def evaluate(ev: Evaluator, region: Region, model: ModelRange, schedule: Schedule, vpoints, *,
             run=True) -> list:
    """검증점 전부의 레코드 — 계산 못 한 점도 남긴다 (05 §11.8 「사라지지 않는다」)."""
    if not region.confirmed:
        raise ValueError(f"요구영역이 미확정({region.source}) — 초안은 판정에 쓰지 않는다 (05 §11.2)")
    tables = schedule.tables()
    recs = []
    for vp in vpoints:
        r = {"name": vp.cond.name, "cond": vp.cond, "kind": vp.kind, "row": vp.row, "origin": vp.origin,
             "verdict": None, "reasons": []}
        if not run:
            r["state"] = NOT_RUN
        else:
            st, rec, why = ev.state(vp.cond, region, model)
            r.update(state=st, reasons=why)
            if st == COMPUTABLE:
                r["verdict"], r["slots"], r["gains"] = ev.judge(vp.cond, rec, schedule, tables)
        recs.append(r)
    return recs


# ── 결과 요약 (05 §11.8) ──────────────────────────────────────────────────────
EXTRA_ROW = "경계·추가"


def column_of(mach: float, union) -> str:
    if mach < union[0] - _EPS:
        return "clip<"
    if mach > union[-1] + _EPS:
        return "clip>"
    for i, x in enumerate(union):
        if abs(mach - x) <= _EPS:
            return f"bp{i + 1}"
    i = int(np.searchsorted(union, mach)) - 1
    return f"iv{i + 1}-{i + 2}"


def columns(union) -> list:
    cols = ["clip<"]
    for i in range(len(union)):
        cols.append(f"bp{i + 1}")
        if i + 1 < len(union):
            cols.append(f"iv{i + 1}-{i + 2}")
    return cols + ["clip>"]


def summarize(recs, union) -> dict:
    """열 = clip·절점·구간 교대, 행 = 검증 조합 + 「경계·추가」. 분모는 요청 점 전부(요구영역 밖만 뺌)."""
    cells: dict = {}
    out_of_region = 0
    for r in recs:
        if r["state"] == OUT_OF_REGION:
            out_of_region += 1
            continue
        row = EXTRA_ROW if r["row"] is None else r["row"]
        cell = cells.setdefault((row, column_of(r["cond"].mach, union)),
                                {"n": 0, "done": 0, "states": {}, "verdicts": {}})
        cell["n"] += 1
        cell["states"][r["state"]] = cell["states"].get(r["state"], 0) + 1
        if r["state"] == COMPUTABLE:
            cell["done"] += 1
            cell["verdicts"][r["verdict"]] = cell["verdicts"].get(r["verdict"], 0) + 1
    for cell in cells.values():
        cell["headline"] = headline(cell)
        cell["text"] = cell_text(cell)
    return {"cells": cells, "columns": columns(union), "out_of_region": out_of_region}


def headline(cell) -> str:
    """대표 문구 — 불합격 → 미완료 → 「검사한 점 모두 충족」. 「구간 합격」이라 쓰지 않는다."""
    if cell["verdicts"].get(FAIL):
        return "불합격"
    if cell["done"] < cell["n"]:
        return "미완료"
    if cell["verdicts"].get(NA):
        return "판정 불가 포함"
    return "검사한 점 모두 충족"


def cell_text(cell) -> str:
    parts = []
    if cell["verdicts"].get(FAIL):
        parts.append(f"{FAIL} {cell['verdicts'][FAIL]}")
    parts.append(f"완료 {cell['done']}/{cell['n']}")
    parts += [f"{STATE_LABEL[st]} {k}" for st, k in cell["states"].items() if st != COMPUTABLE]
    return " · ".join(parts)


def d_values(recs, union, scales) -> list:
    """구간 중간점의 보강 지표 d — 양끝 절점 점이 같은 행에서 계산됐을 때만 (05 §11.7)."""
    by = {(r["row"], r["cond"].mach): r for r in recs if r["row"] is not None and r["state"] == COMPUTABLE}
    out = []
    for r in recs:
        if r["kind"] != "midpoint" or r["state"] != COMPUTABLE:
            continue
        i = int(np.searchsorted(union, r["cond"].mach)) - 1
        a, b = union[i], union[i + 1]
        ra, rb = by.get((r["row"], a)), by.get((r["row"], b))
        if ra is None or rb is None:
            continue
        t = (r["cond"].mach - a) / (b - a)
        for slot, s in scales.items():
            m, ma, mb = (x["slots"].get(slot, {}).get("metric") for x in (r, ra, rb))
            if s <= 0 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (m, ma, mb)):
                continue
            out.append({"interval": f"iv{i + 1}-{i + 2}", "row": r["row"], "slot": slot,
                        "d": abs(m - (ma + t * (mb - ma))) / s})
    return out
