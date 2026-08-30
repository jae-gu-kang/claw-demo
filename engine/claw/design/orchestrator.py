"""자동 설계 루프 상태 머신 — COARSE → REFINE → TUNE → FIT → VERIFY → CLASSIFY 순환.

트림 자동화(grid·refine) → 게인 자동 튜닝(tune) → 스케줄 적합(fit) → 스케줄 인지
검증(schedmap) → 원인 분류(classify) → 처방 반영 후 재진입 — 사용자 요구의
이터레이션 전체가 이 한 세션이다.

- 기본 모드 gated (사용자 확정): CLASSIFY에서 처방이 나오면 status
  "awaiting_approval"로 멈추고, apply_actions(승인 id들) 후 run()을 다시 부르면
  이어서 돈다. mode="auto"는 escalate를 제외한 전 처방을 자동 반영. 에스컬레이션
  (상위 설계 변경)은 **어느 모드든 자동 적용 없이 보고만**.
- 종료 3겹: 점 예산(budget_points) + 승격 단방향 래칫(points.promote) +
  이터레이션 상한(budget_iters). 수렴 판정: 전 점 통과(converged) ∨ 남은 실패가
  전부 escalation(escalated) ∨ 예산 소진(budget_exhausted).
- 증분 재계산: 트림·선형모델은 (케이스, 지문) 캐시 재사용 — pipeline.Pipeline의
  DAG 캐시는 파라미터 지문 축이라 점집합 상태와 결이 달라 직접 채택하지 않는다
  (의도적 이탈). params_fingerprint 계보 스탬프는 동일하게 승계된다.
- to_dict/from_dict 완전 왕복 — 잡 취소·gated 재개·서버 저장(store)의 전제.
  진행 콜백 on_progress(done, total, message)가 truthy를 반환하면 현 스테이지
  완료분을 보존한 채 멈춘다 (JobManager 협조적 취소 패턴).
"""

from dataclasses import dataclass, field

import numpy as np

from claw.common.contracts import SurfaceCommand, TrimCase, TrimResult, VehicleState
from claw.common.attitude import euler_to_quat
from claw.design.classify import classify_failures
from claw.design.criteria import MarginCriteria
from claw.design.fit import fit_slots
from claw.design.grid import coarse_grid
from claw.design.linmodels import LinearModelSet
from claw.design.points import (
    ROLE_ANCHOR,
    ROLE_BREAKPOINT,
    ROLE_RANK,
    ROLE_VALIDATION,
    OperatingPoint,
    PointSet,
    case_name,
)
from claw.design.refine import refine_trim_points
from claw.design.schedmap import midpoint_validation_points, scheduled_margin_map
from claw.design.tune import TuneTargets, tune_points
from claw.env import isa_atmosphere
from claw.tables import PolyTable, Table

STAGES = ("COARSE", "REFINE", "TUNE", "FIT", "VERIFY", "CLASSIFY", "DONE")
MAX_ITERS = 10


@dataclass
class AutoDesignConfig:
    budget_points: int = 200
    budget_iters: int = 5
    budget_tune_evals: int = 60
    mode: str = "gated"  # "gated" [기본값 — 사용자 확정] | "auto"
    criteria: MarginCriteria = field(default_factory=MarginCriteria)
    targets: TuneTargets = field(default_factory=TuneTargets)
    refine_tol: float = 0.25  # classify tol_plant와 같은 값을 공유 (기준 이원화 금지)
    fit_tol: float = 0.02
    flat_tol: float = 0.02
    tol_gain: float = 0.10
    max_degree: int = 4
    max_segments: int = 4
    n_mach: int = 5
    alts: tuple | None = None
    fuels: tuple | None = None
    actuator_wn: float = 30.0
    actuator_zeta: float = 0.7
    delay_s: float = 0.035
    pade_order: int = 2

    def __post_init__(self):
        if self.mode not in ("gated", "auto"):
            raise ValueError(f"mode는 'gated'|'auto': {self.mode!r}")
        if not 1 <= self.budget_iters <= MAX_ITERS:
            raise ValueError(f"budget_iters는 1~{MAX_ITERS}: {self.budget_iters}")
        if self.budget_points < 4:
            raise ValueError(f"budget_points는 4 이상: {self.budget_points}")
        # 차수 상한 6 — 반출 다항이 서버 게인 스키마(구간 계수 8개, sim.PolySegmentIn)를
        # 넘으면 자동 설계 결과를 시뮬·코드젠에 되먹일 수 없다(422). 웹 수동 적합
        # (lib/polyfit.js)도 1~6이라 두 경로의 표현력을 같게 둔다
        if not 1 <= self.max_degree <= 6:
            raise ValueError(f"max_degree는 1~6: {self.max_degree}")
        if not 1 <= self.max_segments <= 8:
            raise ValueError(f"max_segments는 1~8: {self.max_segments}")
        if not 0.0 < self.refine_tol:
            raise ValueError(f"refine_tol은 양수: {self.refine_tol}")
        for name in ("fit_tol", "flat_tol", "tol_gain"):
            v = getattr(self, name)
            if not 0.0 < v < 1.0:
                raise ValueError(f"{name}은 (0, 1) 구간: {v}")
        if self.n_mach < 2:
            raise ValueError(f"n_mach는 2 이상: {self.n_mach}")
        if self.budget_tune_evals < 0:
            raise ValueError(f"budget_tune_evals는 음수 불가: {self.budget_tune_evals}")
        if self.actuator_wn <= 0 or self.actuator_zeta <= 0:
            raise ValueError("actuator_wn·actuator_zeta는 양수여야 함")
        if self.delay_s < 0 or self.pade_order < 1:
            raise ValueError("delay_s는 음수 불가, pade_order는 1 이상")
        self._check_targets_meet_criteria()

    def _check_targets_meet_criteria(self):
        """튜너 목표가 판정선을 넘는지 — warn/fail이 의미를 갖게 하는 유일한 불변식.

        criteria(판정)와 targets(튜닝)는 서로를 모른 채 각자 기본값을 들고 있어서
        조용히 어긋난다. 어긋나면 산출물이 거짓말을 한다:
        - targets.gm_db < criteria.gm_good_db  → 튜닝이 **성공한** 점이 전부 warn.
          실제로 8 dB vs 10 dB로 어긋나 있었고, 화면은 경고로 뒤덮였다.
        - targets.pm_deg < criteria.pm_min_deg → 튜닝 성공점이 곧바로 fail.
          그러면 분류기가 그 점을 structural_limit로 몰아 에스컬레이션을 양산한다
          (자유 게인 최적조차 fail이니 정의상 구조 한계로 보인다).
        둘 다 "판정이 틀렸다"가 아니라 **설정이 모순**인 것이라 제출 시점에 막는다
        (routes/design.py가 ValueError를 422로 낸다 — 워커를 돌린 뒤 알아채면 늦다).
        """
        cr, tg = self.criteria, self.targets
        if tg.pm_deg < cr.pm_min_deg:
            raise ValueError(
                f"targets.pm_deg({tg.pm_deg}°) ≥ criteria.pm_min_deg({cr.pm_min_deg}°) 필요 — "
                "튜닝 목표가 합격선보다 낮으면 성공한 점이 곧바로 fail로 찍힌다"
            )
        if tg.gm_db < cr.gm_good_db:
            raise ValueError(
                f"targets.gm_db({tg.gm_db} dB) ≥ criteria.gm_good_db({cr.gm_good_db} dB) 필요 — "
                "튜닝 목표가 목표선보다 낮으면 성공한 점이 전부 warn이 되어 warn이 무의미해진다"
            )
        for field_name in ("zeta_sp", "zeta_dr"):
            z = getattr(tg, field_name)
            if z < cr.zeta_good:
                raise ValueError(
                    f"targets.{field_name}({z}) ≥ criteria.zeta_good({cr.zeta_good}) 필요 — "
                    "감쇠 목표가 목표선보다 낮으면 성공한 댐퍼가 warn으로 찍힌다"
                )

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("criteria", "targets")}
        d["alts"] = list(self.alts) if self.alts is not None else None
        d["fuels"] = list(self.fuels) if self.fuels is not None else None
        d["criteria"] = self.criteria.to_dict()
        d["targets"] = self.targets.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AutoDesignConfig":
        d = dict(d)
        d["criteria"] = MarginCriteria.from_dict(d["criteria"])
        d["targets"] = TuneTargets.from_dict(d["targets"])
        for k in ("alts", "fuels"):
            if d.get(k) is not None:
                d[k] = tuple(d[k])
        return cls(**d)


# ── TrimResult 직렬화 (세션 왕복 최소 표현 — trim_level의 상태 구성과 동일) ──


def _trim_to_dict(tr: TrimResult) -> dict:
    cached = getattr(tr, "_design_dict", None)
    if cached is not None:
        # 역직렬화본 — 원본 dict를 그대로 낸다 (α의 쿼터니언↔오일러 재변환이
        # 마지막 비트를 흔들어 to_dict가 멱등이 아니게 되는 것을 막는다)
        return dict(cached)
    return {
        "name": tr.case.name, "mach": tr.case.mach, "alt": tr.case.alt,
        "fuel": tr.case.fuel,
        "alpha": float(tr.state.euler()[1]),
        "de": float(tr.control.elevon[0]),
        "thr": float(tr.control.throttle[0]),
        "converged": tr.converged, "cost": tr.cost, "flags": dict(tr.flags),
        "fingerprint": tr.params_fingerprint,
    }


def _trim_from_dict(d: dict) -> TrimResult:
    case = TrimCase(name=d["name"], mach=float(d["mach"]), alt=float(d["alt"]),
                    fuel=float(d["fuel"]))
    alpha, de, thr = float(d["alpha"]), float(d["de"]), float(d["thr"])
    v_true = case.mach * isa_atmosphere(case.alt).a
    state = VehicleState(
        t=0.0,
        pos_n=np.array([0.0, 0.0, -case.alt]),
        vel_b=np.array([v_true * np.cos(alpha), 0.0, v_true * np.sin(alpha)]),
        q_nb=euler_to_quat(0.0, alpha, 0.0),
        omega_b=np.zeros(3),
        fuel=case.fuel,
    )
    control = SurfaceCommand(
        elevon=np.full(4, de), rudder=0.0, throttle=np.array([thr, thr])
    )
    tr = TrimResult(case=case, state=state, control=control,
                    converged=bool(d["converged"]), cost=float(d["cost"]),
                    flags=dict(d["flags"]), params_fingerprint=d.get("fingerprint", ""))
    tr._design_dict = dict(d)  # 직렬화 멱등성 캐시 (_trim_to_dict 참조)
    return tr


def _table_to_dict(tab) -> dict:
    if isinstance(tab, PolyTable):
        return tab.to_dict()
    return {"kind": "table", "name": tab.name,
            "axes": {n: list(a) for n, a in zip(tab.axis_names, tab.axes)},
            "data": tab.data.tolist()}


def _table_from_dict(d: dict):
    if d.get("kind") == "poly":
        return PolyTable.from_dict(d)
    return Table(d["axes"], d["data"], name=d.get("name", ""), extrapolate="clip")


class _Cancelled(Exception):
    pass


class DesignSession:
    """자동 설계 세션 — 상태 전부가 이 객체이고 to_dict/from_dict로 왕복한다."""

    def __init__(self, config: AutoDesignConfig | None = None):
        self.config = config if config is not None else AutoDesignConfig()
        self.points = PointSet()
        self.lms = LinearModelSet()
        self.trims: dict = {}
        self.design: dict = {}
        self.gain_samples: dict = {}
        self.tune_meta: dict = {}
        self.promoted_gains: dict = {}  # {slot: {이름: 값}} — valley 승격 breakpoint의 게인
        self.fits: dict = {}
        self.sched_tables: dict = {}
        self.sched_constants: dict = {}
        self.margin_out: dict = {}
        self.actions: list = []
        self.escalations: list = []
        self.iterations: list = []
        self.stage = "COARSE"
        self.status = "running"
        self.iter_n = 0

    # ── 진행/취소 ──
    def _progress(self, on_progress, done, total, message):
        if on_progress is not None and on_progress(done, total, f"[{self.stage}] {message}"):
            raise _Cancelled()

    def _act_kw(self):
        c = self.config
        return dict(actuator_wn=c.actuator_wn, actuator_zeta=c.actuator_zeta,
                    delay_s=c.delay_s, pade_order=c.pade_order)

    # ── 스테이지 ──
    def _stage_coarse(self, aircraft, stall_table, limits, db_ranges, fingerprint, cb):
        c = self.config
        out = coarse_grid(
            aircraft, stall_table, limits, db_ranges,
            n_mach=c.n_mach, alts=c.alts, fuels=c.fuels,
            budget=c.budget_points, fingerprint=fingerprint,
            on_progress=lambda d, t, m: cb(d, t, m),
        )
        self.points, new_trims = out["points"], out["trims"]
        self.trims.update(new_trims)
        if out["aborted"]:
            raise _Cancelled()
        self.stage = "REFINE"

    def _stage_refine(self, aircraft, fingerprint, cb):
        c = self.config
        report = refine_trim_points(
            aircraft, self.points, self.lms, self.trims,
            tol=c.refine_tol, max_points=c.budget_points,
            fingerprint=fingerprint, on_progress=lambda d, t, m: cb(d, t, m),
        )
        self.iterations.append({"n": self.iter_n, "stage": "REFINE", "report": {
            k: report[k] for k in ("inserted", "gaps", "aborted", "max_d_remaining")
        }})
        if report["aborted"] == "cancelled":
            raise _Cancelled()
        self.stage = "TUNE"

    def _stage_tune(self, aircraft, cb):
        c = self.config
        out = tune_points(
            aircraft, self.points, self.lms, self.trims,
            design=self.design, targets=c.targets, max_evals=c.budget_tune_evals,
            on_progress=lambda d, t, m: cb(d, t, m), **self._act_kw(),
        )
        if out["aborted"]:
            raise _Cancelled()
        self.gain_samples = out["gains"]
        self.tune_meta = {
            "skipped": out["skipped"],
            "status": {n: r["status"] for n, r in out["results"].items()},
            "notes": {n: r["notes"] for n, r in out["results"].items() if r["notes"]},
        }
        self.stage = "FIT"

    def _stage_fit(self, cb):
        c = self.config
        # valley 승격 breakpoint의 최적 게인을 샘플에 합류 — 그 점 근방의 적합이
        # 승격 의도를 따라가게 한다 (knot 강제가 아니라 잔차 유도 — fit.py greedy)
        samples = {slot: dict(v) for slot, v in self.gain_samples.items()}
        for slot, extra in self.promoted_gains.items():
            target = samples.setdefault(slot, {})
            for name, value in extra.items():
                # **튜닝 샘플이 이긴다.** 승격 게인은 한 번 들어가면 지워지지 않으므로,
                # 그 점이 나중에 anchor로 올라가 실제로 튜닝되면 낡은 값이 최신 결과를
                # 덮어써 같은 점이 영원히 재분류된다 (이터 예산만 태운다)
                target.setdefault(name, value)
        out = fit_slots(
            samples, self.points, flat_tol=c.flat_tol, tol_fit=c.fit_tol,
            max_degree=c.max_degree, max_segments=c.max_segments,
        )
        self.sched_tables = out["tables"]
        self.sched_constants = out["constants"]
        self.fits = out["reports"]
        cb(1, 1, "fit")
        self.stage = "VERIFY"

    def _stage_verify(self, aircraft, fingerprint, cb):
        c = self.config
        for pt in midpoint_validation_points(self.points):
            if len(self.points) >= c.budget_points:
                break
            self.points.add(pt)
        design_eff = {**self.design, **self.sched_constants}
        out = scheduled_margin_map(
            aircraft, self.points, self.lms, self.sched_tables, design_eff,
            criteria=c.criteria, trims=self.trims, fingerprint=fingerprint,
            on_progress=lambda d, t, m: cb(d, t, m), **self._act_kw(),
        )
        if out["aborted"]:
            raise _Cancelled()
        self.margin_out = out
        self.stage = "CLASSIFY"

    def judged_count(self) -> int:
        """실제로 판정이 난 (점, 자리) 수 — "통과"와 "안 봤다"를 가르는 수치.

        미수렴 트림 점은 loops가 비어 있고(schedmap), 제로 개루프 자리는 status
        'na'다. 둘 다 실패 목록에 안 잡히므로, 판정 수를 세지 않으면 **아무것도
        검증하지 않은 실행이 converged로 보고된다** — 비행제어 설계툴에서 가장
        나쁜 실패 양식이다.

        엔벨로프 밖 점도 같은 이유로 뺀다: 그 점은 실패 목록에서 제외되므로
        (schedmap._worst_failures), 여기서 세면 "격자가 전부 엔벨로프 밖"인 실행이
        judged>0·failures=0으로 converged가 된다 — 가드가 막으려던 바로 그 형태다.
        """
        return sum(
            1
            for entry in self.margin_out.get("cases", {}).values()
            if not entry.get("outside_envelope")
            for m in entry.get("loops", {}).values()
            if m.get("status") in ("ok", "warn", "fail")
        )

    def outside_envelope_count(self) -> int:
        """마진은 냈으나 엔벨로프 밖이라 판정·처방에서 뺀 점 수 — 조용한 제외 금지."""
        return sum(1 for entry in self.margin_out.get("cases", {}).values()
                   if entry.get("outside_envelope"))

    def _stage_classify(self, aircraft, cb):
        c = self.config
        if not self.margin_out["failures"]:
            judged = self.judged_count()
            if judged == 0:
                # 실패가 없는 게 아니라 볼 것이 없었다 — 트림 전량 미수렴, 빈 격자,
                # 게인이 전부 0인 형상 등. 통과로 위장하지 않는다
                self.status = "nothing_verified"
                self.stage = "DONE"
                return
            self.status = "converged"
            self.stage = "DONE"
            return
        design_eff = {**self.design, **self.sched_constants}
        actions = classify_failures(
            aircraft, self.points, self.lms, self.trims, self.sched_tables,
            design_eff, self.margin_out,
            criteria=c.criteria, targets=c.targets,
            tol_plant=c.refine_tol, tol_gain=c.tol_gain, **self._act_kw(),
        )
        cb(1, 1, "classify")
        for a in actions:
            if a["action"]["type"] == "escalate" and all(
                e["id"] != a["id"] for e in self.escalations
            ):
                self.escalations.append(a)
        self.actions = actions
        applicable = [a for a in actions
                      if a["action"]["type"] != "escalate" and "superseded_by" not in a]
        self.iterations.append({
            "n": self.iter_n, "stage": "CLASSIFY",
            "failures": len(self.margin_out["failures"]),
            "actions": [{k: a[k] for k in ("id", "verdict")} for a in actions],
        })
        if not applicable:
            self.status = "escalated"
            self.stage = "DONE"
            return
        if self.iter_n + 1 >= c.budget_iters:
            self.status = "budget_exhausted"
            self.stage = "DONE"
            return
        if c.mode == "gated":
            self.status = "awaiting_approval"
            return
        self.apply_actions([a["id"] for a in applicable])

    # ── 승인/반영 ──
    def proposed_actions(self) -> list:
        """gated 일시정지 시의 처방 카드 목록 (supersede 제외, escalate는 참고용 포함)."""
        return [a for a in self.actions if "superseded_by" not in a]

    def apply_actions(self, approved_ids) -> dict:
        """승인된 처방만 반영하고 다음 스테이지를 정한다 — {"applied", "next_stage"}."""
        approved = set(approved_ids)
        applied = []
        need_refine = False
        by_id = {a["id"]: a for a in self.actions}
        for aid in approved_ids:
            a = by_id.get(aid)
            if a is None or "superseded_by" in a:
                continue
            act = a["action"]
            if act["type"] == "escalate":
                continue  # 상위 설계 변경은 자동 적용 금지 — 승인 목록에 있어도 무시
            if act["type"] == "promote":
                pt = self.points.get(act["point"])
                # 래칫 방어 — 이미 그 역할 이상이면 승격을 **건너뛴다**. 분류기가
                # 상위 역할 점에 승격을 내는 경로는 막아 두었지만(classify refit_at),
                # 여기서 터지면 run()이 못 잡아 세션 전량이 저장 없이 소실된다
                if ROLE_RANK[pt.role] < ROLE_RANK[act["to"]]:
                    self.points.promote(act["point"], act["to"], reason=a["verdict"])
                    if act["to"] == ROLE_ANCHOR:
                        need_refine = True
                else:
                    a["skipped"] = f"이미 {pt.role} — 승격 불필요"
                for slot, v in (act.get("gains") or {}).items():
                    self.promoted_gains.setdefault(slot, {})[act["point"]] = float(v)
            elif act["type"] == "refit_at":
                # 이미 breakpoint 이상인 점의 보간 괴리 — 역할은 그대로 두고 그 점의
                # 최적 게인만 적합 샘플에 고정한다
                for slot, v in (act.get("gains") or {}).items():
                    self.promoted_gains.setdefault(slot, {})[act["point"]] = float(v)
            elif act["type"] == "add_validation":
                self._add_validation_around(act["point"])
            applied.append(aid)
        # 감사 표식은 **실제로 반영한 것에만** — 거부한 에스컬레이션·supersede에 붙이면
        # 기록이 거짓말을 한다 (escalations가 같은 dict를 참조하므로 함께 오염된다)
        applied_set = set(applied)
        for a in self.actions:
            if a["id"] in applied_set:
                a["applied"] = True
        self.iter_n += 1
        self.stage = "REFINE" if need_refine else "TUNE"
        self.status = "running"
        return {"applied": applied, "next_stage": self.stage}

    def _add_validation_around(self, v_name):
        flank = self.points.flanking(v_name, ROLE_VALIDATION)
        if flank is None:
            return
        lo, hi, axis = flank
        for other in (lo, hi):
            if len(self.points) >= self.config.budget_points:
                return
            ca, cb_ = self.points.get(v_name).case, self.points.get(other).case
            mid = {"mach": (ca.mach + cb_.mach) / 2.0, "alt": (ca.alt + cb_.alt) / 2.0,
                   "fuel": (ca.fuel + cb_.fuel) / 2.0}
            name = case_name(mid["mach"], mid["alt"], mid["fuel"])
            if name in self.points:
                continue
            self.points.add(OperatingPoint(
                case=TrimCase(name=name, mach=mid["mach"], alt=mid["alt"],
                              fuel=mid["fuel"]),
                role=ROLE_VALIDATION, origin=f"add_validation:{v_name}",
            ))

    # ── 실행 ──
    def run(self, aircraft, stall_table, limits, db_ranges, design, *,
            fingerprint="", on_progress=None) -> dict:
        """현 스테이지부터 계속 실행 — DONE·awaiting_approval·취소에서 멈춘다."""
        self.design = dict(design)
        if self.status == "awaiting_approval":
            return self.report()  # 승인 없이 재호출 — 상태 유지 (apply_actions가 풀어 준다)
        self.status = "running"

        def cb(done, total, message):
            self._progress(on_progress, done, total, message)

        try:
            while self.stage != "DONE":
                if self.stage == "COARSE":
                    self._stage_coarse(aircraft, stall_table, limits, db_ranges,
                                       fingerprint, cb)
                elif self.stage == "REFINE":
                    self._stage_refine(aircraft, fingerprint, cb)
                elif self.stage == "TUNE":
                    self._stage_tune(aircraft, cb)
                elif self.stage == "FIT":
                    self._stage_fit(cb)
                elif self.stage == "VERIFY":
                    self._stage_verify(aircraft, fingerprint, cb)
                elif self.stage == "CLASSIFY":
                    self._stage_classify(aircraft, cb)
                    if self.status == "awaiting_approval":
                        break
        except _Cancelled:
            self.status = "cancelled"
        return self.report()

    def report(self) -> dict:
        c = self.config
        roles = {r: len(self.points.by_role(r))
                 for r in (ROLE_ANCHOR, ROLE_BREAKPOINT, ROLE_VALIDATION)}
        return {
            "status": self.status, "stage": self.stage, "iterations": self.iter_n,
            "points": roles, "n_points": len(self.points),
            "failures": len(self.margin_out.get("failures", ())),
            # 판정 수 — "실패 0"이 통과인지 미검증인지 화면이 구별할 수 있어야 한다
            "judged": self.judged_count(),
            # 판정·처방에서 뺀 엔벨로프 밖 점 수 — 제외했다는 사실 자체가 보고 대상이다
            "outside_envelope": self.outside_envelope_count(),
            "tuned": len(self.gain_samples.get(next(iter(self.gain_samples), ""), {}))
            if self.gain_samples else 0,
            "skipped": list(self.tune_meta.get("skipped", ())),
            "escalations": len(self.escalations),
            "criteria_fingerprint": c.criteria.fingerprint(),
        }

    # ── 직렬화 ──
    def to_dict(self) -> dict:
        return {
            "kind": "auto_design",
            "config": self.config.to_dict(),
            "points": self.points.to_dict(),
            "linmodels": self.lms.to_dict(),
            "trims": {n: _trim_to_dict(tr) for n, tr in self.trims.items()},
            "design": dict(self.design),
            "gain_samples": {s: dict(v) for s, v in self.gain_samples.items()},
            "tune_meta": self.tune_meta,
            "promoted_gains": {s: dict(v) for s, v in self.promoted_gains.items()},
            "fits": self.fits,
            "sched_tables": {s: _table_to_dict(t) for s, t in self.sched_tables.items()},
            "sched_constants": dict(self.sched_constants),
            "margin_out": self.margin_out,
            "actions": self.actions,
            "escalations": self.escalations,
            "iterations": self.iterations,
            "stage": self.stage, "status": self.status, "iter_n": self.iter_n,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DesignSession":
        s = cls(AutoDesignConfig.from_dict(d["config"]))
        s.points = PointSet.from_dict(d["points"])
        s.lms = LinearModelSet.from_dict(d["linmodels"])
        s.trims = {n: _trim_from_dict(td) for n, td in d["trims"].items()}
        s.design = dict(d.get("design", {}))
        s.gain_samples = {k: dict(v) for k, v in d.get("gain_samples", {}).items()}
        s.tune_meta = d.get("tune_meta", {})
        s.promoted_gains = {k: dict(v) for k, v in d.get("promoted_gains", {}).items()}
        s.fits = d.get("fits", {})
        s.sched_tables = {k: _table_from_dict(v)
                          for k, v in d.get("sched_tables", {}).items()}
        s.sched_constants = dict(d.get("sched_constants", {}))
        s.margin_out = d.get("margin_out", {})
        s.actions = list(d.get("actions", ()))
        s.escalations = list(d.get("escalations", ()))
        s.iterations = list(d.get("iterations", ()))
        s.stage = d["stage"]
        s.status = d["status"]
        s.iter_n = int(d.get("iter_n", 0))
        return s
