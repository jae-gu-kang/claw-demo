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

import math
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
from claw.design.tune import REASON_TEXT, TuneTargets, tune_points
from claw.env import isa_atmosphere
from claw.tables import PolyTable, Table

STAGES = ("COARSE", "REFINE", "TUNE", "FIT", "VERIFY", "CLASSIFY", "DONE")
MAX_ITERS = 10
_FIT_TIGHTEN_FACTOR = 0.5  # tighten_fit 1회당 적합 허용치 배율
_FIT_TIGHTEN_MAX = 3  # 조이기 상한 (허용치 1/8, 구간 +3) — 래칫의 천장
_MAX_SEGMENTS_CAP = 8  # fit_slots 계약 상한 (AutoDesignConfig 검증과 동일)
# 처방을 반영한 뒤 판정이 이만큼도 안 움직이면 "안 바뀌었다"로 본다 (부족 비율)
_EFFECT_EPS = 1e-3
_SEAL_AFTER = 2  # 연속 무효 횟수 — 이 이상이면 그 (점, 자리, verdict)를 봉인한다
# 점 예산 중 **보간 구간 검증점 몫**. REFINE이 앵커로 예산을 다 태우면 VERIFY의
# 중점 검증점이 한 개도 못 들어가고, 그러면 "스케줄 인지 검증"이 이름만 남는다 —
# 판정된 자리가 전부 자기 게인이 직접 튜닝된 앵커가 되기 때문이다. 실측: 큰 격자
# (예산 60)에서 요구 60개 중 0개, 기본 테스트 설정(예산 24)에서도 21개 중 2개만
# 들어갔다. REFINE에 예산을 다 주지 않고 이 비율만큼 남긴다 [기본값]
_VALIDATION_RESERVE_FRAC = 0.25


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


def _seal_key(case, loop, verdict) -> str:
    """봉인 키 — 문자열이라야 세션 왕복(JSON)에서 살아남는다."""
    return f"{case}|{loop}|{verdict}"


def _effect_changed(before, after) -> bool:
    """처방 전후로 이 자리의 판정이 실제로 움직였나.

    볼 수 없으면(둘 중 하나가 없으면) **변화 없음이라 단정하지 않는다** — 모르는
    것을 무효로 세면 멀쩡한 처방이 봉인된다.
    """
    if before is None or after is None:
        return True
    if before.get("status") != after.get("status"):
        return True
    b, a = before.get("severity"), after.get("severity")
    if b is None or a is None:
        return True
    return abs(a - b) > _EFFECT_EPS


class DesignSession:
    """자동 설계 세션 — 상태 전부가 이 객체이고 to_dict/from_dict로 왕복한다."""

    def __init__(self, config: AutoDesignConfig | None = None):
        self.config = config if config is not None else AutoDesignConfig()
        self.points = PointSet()
        self.lms = LinearModelSet()
        self.trims: dict = {}
        self.design: dict = {}
        # 법칙의 레이트 경로 필터 {그룹: 스펙} — design과 같은 성격(프로파일이 주는 값)이라
        # 같은 자리에서 초기화·직렬화한다. 왕복에서 빠지면 재개한 세션이 조용히
        # 필터 없는 플랜트로 되돌아간다 (이 모듈 머리말의 '완전 왕복' 전제)
        self.rate_filters: dict = {}
        self.gain_samples: dict = {}
        self.tune_meta: dict = {}
        self.promoted_gains: dict = {}  # {slot: {이름: 값}} — valley 승격 breakpoint의 게인
        # refit_at으로 **명시 고정**된 게인. promoted를 이긴다 — 같은 점이 이터를 넘어
        # 다시 실패하면 새 최적이 들어와야 하는데, 한 겹 setdefault이던 동안에는
        # 처음 들어간 승격 값이 계속 이겨 새 처방이 아무것도 안 바꿨다
        self.refit_gains: dict = {}
        self.fit_tighten = 0  # tighten_fit 반영 횟수 — 단조 증가 래칫 (종료 보장)
        self.fits: dict = {}
        self.sched_tables: dict = {}
        self.sched_constants: dict = {}
        self.margin_out: dict = {}
        self.actions: list = []
        self.escalations: list = []
        self.iterations: list = []
        # 반영한 처방의 효과 기록 — "applied"만 찍고 결과를 안 보면 무효 처방이
        # 예산을 태우는 것을 아무도 모른다. ineffective는 {봉인키: 연속 무효 횟수}
        self.applied_log: list = []
        self.ineffective: dict = {}
        # 검증 커버리지 — "무엇을 안 봤는가". converged가 거짓말하지 않으려면
        # 실패 수만큼이나 이 수치가 보고에 있어야 한다
        self.refine_report: dict = {}
        self.validation_wanted = 0
        self.validation_added = 0
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
                    delay_s=c.delay_s, pade_order=c.pade_order,
                    rate_filters=dict(self.rate_filters))

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
        # 예산을 다 주지 않는다 — 보간 구간 검증점 몫을 남긴다 (위 상수 주석).
        # 하한은 현 점 수 + 1이라, 이미 예산 근처인 재개 경로에서도 음수가 안 된다
        refine_budget = max(len(self.points) + 1,
                            int(c.budget_points * (1.0 - _VALIDATION_RESERVE_FRAC)))
        report = refine_trim_points(
            aircraft, self.points, self.lms, self.trims,
            tol=c.refine_tol, max_points=refine_budget,
            fingerprint=fingerprint, on_progress=lambda d, t, m: cb(d, t, m),
        )
        self.refine_report = {k: report[k] for k in
                              ("inserted", "aborted", "max_d_remaining")}
        self.refine_report["budget"] = refine_budget
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
            # 자리별 판정 레코드 — 원장이 "튜닝이 설계 목표를 못 채운 자리"를 낼 수
            # 있으려면 이게 있어야 한다. 종전에는 점 단위 status와 산문 notes뿐이라,
            # **자동 튜닝이 무엇을 얼마나 달성했는지가 결과 JSON에 없었다**
            "slots": {n: r["slots"] for n, r in out["results"].items()},
            "notes": {n: r["notes"] for n, r in out["results"].items() if r["notes"]},
        }
        self.stage = "FIT"

    def _fit_params(self) -> dict:
        """이 이터레이션의 적합 파라미터 — tighten_fit 처방이 반영된 값.

        앵커에서의 보간 괴리(fit_residual)는 샘플을 고쳐서는 안 풀린다. 그 점의
        샘플은 이미 최적이고, 남은 손잡이는 **적합 자체**다. 조이는 방향으로만
        움직이는 래칫이라(허용치 ×0.5^n, 구간 +n, 상한 있음) 이터가 종료된다.
        """
        c = self.config
        n = min(self.fit_tighten, _FIT_TIGHTEN_MAX)
        return {
            "flat_tol": c.flat_tol,
            "tol_fit": c.fit_tol * (_FIT_TIGHTEN_FACTOR ** n),
            "max_degree": c.max_degree,
            "max_segments": min(_MAX_SEGMENTS_CAP, c.max_segments + n),
        }

    def _stage_fit(self, cb):
        # 승격·재적합 게인을 샘플에 합류 — 그 점 근방의 적합이 처방 의도를 따라가게
        # 한다 (knot 강제가 아니라 잔차 유도 — fit.py greedy)
        samples = {slot: dict(v) for slot, v in self.gain_samples.items()}
        extra: dict = {}
        for src in (self.promoted_gains, self.refit_gains):  # 뒤가 이긴다
            for slot, vals in src.items():
                extra.setdefault(slot, {}).update(vals)
        for slot, vals in extra.items():
            target = samples.setdefault(slot, {})
            for name, value in vals.items():
                # **튜닝 샘플이 이긴다.** 주입 게인은 한 번 들어가면 지워지지 않으므로,
                # 그 점이 나중에 anchor로 올라가 실제로 튜닝되면 낡은 값이 최신 결과를
                # 덮어써 같은 점이 영원히 재분류된다 (이터 예산만 태운다). 앵커에 대한
                # 주입 처방은 이제 분류기가 아예 안 낸다 — fit_residual로 간다
                target.setdefault(name, value)
        out = fit_slots(samples, self.points, **self._fit_params())
        self.sched_tables = out["tables"]
        self.sched_constants = out["constants"]
        self.fits = out["reports"]
        cb(1, 1, "fit")
        self.stage = "VERIFY"

    def _stage_verify(self, aircraft, fingerprint, cb):
        c = self.config
        wanted = midpoint_validation_points(self.points)
        self.validation_wanted = len(wanted)
        added = 0
        for pt in wanted:
            if len(self.points) >= c.budget_points:
                break  # 예산 소진 — 아래 coverage가 몇 개를 못 넣었는지 보고한다
            self.points.add(pt)
            added += 1
        self.validation_added = added
        design_eff = {**self.design, **self.sched_constants}
        out = scheduled_margin_map(
            aircraft, self.points, self.lms, self.sched_tables, design_eff,
            # targets는 λ 판정에만 쓴다 — 롤 대역폭 요구가 튜닝 목표에서 온다.
            # 튜닝과 검증이 **같은 목표**를 보게 하는 유일한 배선이다
            criteria=c.criteria, targets=c.targets, trims=self.trims,
            fingerprint=fingerprint,
            on_progress=lambda d, t, m: cb(d, t, m), **self._act_kw(),
        )
        if out["aborted"]:
            raise _Cancelled()
        self.margin_out = out
        # 새 판정이 나왔으니 직전에 반영한 처방들을 채점한다 — "applied"만 찍고
        # 결과를 안 보면 무효 처방이 예산을 태우는 것을 아무도 모른다
        self._score_applied_actions()
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

    def not_trimmed_count(self) -> int:
        """트림이 안 돼 아무것도 못 본 점 수 — loops가 빈 케이스.

        이 점들은 failures에도 judged에도 안 잡힌다. 유일한 흔적이 judged가 조용히
        줄어드는 것인데, 기대값을 모르면 그 수가 정상인지 못 본 것인지 구별할 수 없다.
        """
        return sum(1 for e in self.margin_out.get("cases", {}).values()
                   if not e.get("loops"))

    def coverage(self) -> dict:
        """이 실행이 **무엇을 안 봤는가** — 실패 수만큼 중요한 수치.

        판정 수(judged)가 커도 그 전량이 자기 게인이 직접 튜닝된 앵커면, 스케줄이
        breakpoint 사이에서 무너지는지는 한 번도 안 본 것이다. 그런데 종전 보고에는
        검증점 수도, REFINE이 남긴 플랜트 거리도, 트림 미수렴 수도 없었다.

        검증점 수는 **점집합 실물**로 센다 — 스테이지 카운터로 세면 VERIFY가 여러 번
        도는 이터레이션에서 마지막 패스 값만 남는다 (실측: 1차에서 15개를 넣고
        2차에서 예산 소진으로 0개를 넣었는데 보고가 0으로 나왔다). midpoint 유래
        점은 나중에 breakpoint·anchor로 승격돼도 그 구간을 검증한 사실은 그대로다.
        """
        rr = self.refine_report
        return {
            "validation_points": sum(
                1 for p in self.points if str(p.origin).startswith("midpoint:")),
            "validation_missing": max(0, self.validation_wanted - self.validation_added),
            "refine_remaining": rr.get("max_d_remaining"),
            "refine_tol": self.config.refine_tol,
            "refine_aborted": rr.get("aborted"),
            "not_trimmed": self.not_trimmed_count(),
        }

    def coverage_gaps(self) -> list:
        """커버리지 공백을 한국어 한 줄씩 — 비어 있지 않으면 "수렴"이 반쪽이다."""
        cov = self.coverage()
        out = []
        got, missing = cov["validation_points"], cov["validation_missing"]
        if got == 0 and missing:
            out.append(
                f"보간 구간 검증점이 한 개도 없다 (요구 {missing}개가 점 예산"
                f" {self.config.budget_points} 소진으로 못 들어갔다) — 판정된 자리가"
                " 전부 자기 게인이 직접 튜닝된 앵커다. 스케줄이 breakpoint 사이에서"
                " 무너지는지는 보지 않았다"
            )
        elif missing:
            out.append(
                f"보간 구간 {missing}개가 검증점 없이 남았다 (점 예산 소진, 검증된"
                f" 구간은 {got}개) — 그 구간의 스케줄은 보지 않았다"
            )
        rem, tol = cov["refine_remaining"], cov["refine_tol"]
        if rem is not None and tol and rem > tol:
            out.append(
                f"트림 격자 세분화가 허용치 전에 끊겼다 (남은 플랜트 거리 {rem:.3g} >"
                f" 허용 {tol:g}, 사유 {cov['refine_aborted'] or '미상'}) — 그 구간의"
                " 플랜트 변화는 격자가 담지 못한다"
            )
        if cov["not_trimmed"]:
            out.append(
                f"트림 미수렴 점 {cov['not_trimmed']}개는 아무것도 보지 못했다 —"
                " 실패 목록에도 판정 수에도 들어가지 않는다"
            )
        return out

    def shortfall_ledger(self) -> list:
        """미달 원장 — 이 실행이 **못 맞춘 것 전부**를 한 목록으로.

        종전에는 처방 카드가 붙은 실패만 화면에 나왔다. 그런데 실제로 못 맞춘 것의
        대부분은 처방이 안 나오는 것들이다: 자동 튜닝이 설계 목표를 못 채운 자리
        (합격선은 넘길 수 있어 실패가 아니다), 판정 불가(na), 엔벨로프 경계, 튜닝을
        건너뛴 점, 트림 미수렴 점, 그리고 **반영했는데 판정이 안 움직인 처방**.
        이것들이 한 표에 모여야 "무엇이 안 됐고 얼마나 모자라는가"를 볼 수 있다.

        정렬은 severity(요구선 대비 부족 비율) 내림차순이고 **측정 불가가 맨 앞**이다 —
        criteria.severity와 같은 규약("얼마나 나쁜지 모른다"가 목록 맨 앞).
        """
        cr = self.config.criteria
        cases = self.margin_out.get("cases", {})
        rows: list = []

        def add(point, loop, kind, note, *, entry=None, **extra):
            sev = cr.severity(entry) if entry else None
            row = {
                "point": point, "loop": loop, "kind": kind, "note": note,
                "status": (entry or {}).get("status"),
                "severity": None if sev is None or not math.isfinite(sev) else sev,
                "shortfall": cr.shortfall(entry) if entry else {},
                "target": (entry or {}).get("target"),
                "reason": None, "action": None,
            }
            row.update(extra)
            rows.append(row)

        # ① 검증에서 통과하지 못한 자리 (fail·warn·na 전부 — warn도 목표 미달이다)
        by_action = {(a.get("case"), a.get("loop")): a for a in self.actions}
        for name, case in cases.items():
            if not case.get("loops"):
                add(name, None, "not_trimmed",
                    case.get("note") or "트림 미수렴 — 이 점은 아무것도 보지 못했다")
                continue
            outside = bool(case.get("outside_envelope"))
            for loop, m in case["loops"].items():
                st = m.get("status")
                if st == "ok":
                    continue
                a = by_action.get((name, loop))
                add(name, loop,
                    "outside_envelope" if outside else
                    ("unjudged" if st in (None, "na") else "verify"),
                    case.get("note") if outside else m.get("note"),
                    entry=m,
                    action=None if a is None else {
                        "id": a.get("id"), "verdict": a.get("verdict"),
                        "type": a.get("action", {}).get("type"),
                        "applied": bool(a.get("applied")),
                        "changed": (a.get("effect") or {}).get("changed"),
                        "sealed": a.get("sealed"),
                    })

        # ② 자동 튜닝이 설계 목표를 못 채운 자리 — 검증에서 합격선을 넘기면 실패
        #    목록에 안 나오지만, "목표를 못 맞췄다"는 사실 자체가 보고 대상이다
        for name, slots in (self.tune_meta.get("slots") or {}).items():
            for loop, rec in slots.items():
                if rec.get("status") == "ok":
                    continue
                add(name, loop, "tune", REASON_TEXT.get(rec.get("reason")),
                    reason=rec.get("reason"), status=rec.get("status"),
                    target=rec.get("target"), achieved=rec.get("achieved"))
        for name in self.tune_meta.get("skipped", ()):
            add(name, None, "skipped",
                "튜닝을 건너뛴 점 — 트림 미수렴이거나 엔벨로프 경계다 (게인 샘플이 없다)")

        # ③ 반영했는데 판정이 안 움직인 처방
        for rec in self.applied_log:
            if rec["effect"].get("changed") is not False:
                continue
            add(rec["case"], rec["loop"], "ineffective",
                f"{rec['verdict']} 처방을 반영했으나 판정이 움직이지 않았다"
                f" (이터 {rec['iter']}) — 이 자리에서는 이 처방이 듣지 않는다",
                action={"id": rec["id"], "verdict": rec["verdict"],
                        "type": rec["type"], "applied": True, "changed": False,
                        "sealed": None})

        # 측정 불가(None)가 맨 앞, 그 뒤로 부족 비율 내림차순
        rows.sort(key=lambda r: (0 if r["severity"] is None else 1,
                                 -(r["severity"] or 0.0)))
        return rows

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
            # 튜너의 부호·브래킷은 **손설계 정본**에서 잡는다. design_eff(적합 상수가
            # 덮인 값)를 쓰면 자유 게인 최적이 적합 결과에 끌려가 g_opt가 틀린다
            criteria=c.criteria, design_base=self.design, targets=c.targets,
            tol_plant=c.refine_tol, tol_gain=c.tol_gain, **self._act_kw(),
        )
        cb(1, 1, "classify")
        # 두 번 반영해도 판정이 안 움직인 처방은 다시 내지 않는다 — 무효인 줄 알면서
        # 같은 카드를 다시 내미는 것은 이터 예산만 태우고 사용자를 속인다
        sealed = self.sealed_keys()
        for a in actions:
            if _seal_key(a["case"], a["loop"], a["verdict"]) in sealed:
                a["sealed"] = (f"{_SEAL_AFTER}회 반영해도 판정이 안 바뀌었다 —"
                               " 이 처방으로는 풀리지 않는다")
        for a in actions:
            if a["action"]["type"] == "escalate" and all(
                e["id"] != a["id"] for e in self.escalations
            ):
                self.escalations.append(a)
        self.actions = actions
        applicable = [a for a in actions
                      if a["action"]["type"] != "escalate" and "superseded_by" not in a
                      and "sealed" not in a]
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

    # ── 처방 효과 ──
    def _loop_snapshot(self, case, loop) -> dict | None:
        """(점, 자리)의 현재 판정·부족 비율 — 처방 전후 비교의 단위."""
        if not case or not loop:
            return None
        entry = self.margin_out.get("cases", {}).get(case, {}).get("loops", {}).get(loop)
        if entry is None:
            return None
        sev = self.config.criteria.severity(entry)
        return {"status": entry.get("status"),
                "severity": None if not math.isfinite(sev) else sev}

    def _score_applied_actions(self):
        """직전 VERIFY 결과로 반영한 처방의 효과를 채운다 — applied ≠ 고쳐짐.

        판정도 부족 비율도 안 움직였으면 그 처방은 이 자리에서 듣지 않은 것이다.
        연속 _SEAL_AFTER회 그러면 봉인해 다음 이터에서 다시 내지 않는다 — 종전에는
        무효 처방이 applied로 기록되며 예산 소진까지 같은 순환을 돌 수 있었다.
        """
        by_id = {a["id"]: a for a in self.actions}
        for rec in self.applied_log:
            eff = rec["effect"]
            if "after" in eff:
                continue  # 이미 채점됨
            after = self._loop_snapshot(rec["case"], rec["loop"])
            if after is None and eff["before"] is None:
                continue  # 잴 대상이 애초에 없는 처방
            eff["after"] = after
            eff["changed"] = _effect_changed(eff["before"], after)
            # 카드에도 **id로 찾아** 같은 값을 넣는다. 프로세스 안에서는 두 곳이 같은
            # dict를 참조하지만 그 성질은 **JSON 왕복에서 소리 없이 사라진다** —
            # gated 승인은 매번 store를 거치고(routes: load → from_dict → apply →
            # save), 취소 후 재개 경로에서는 저장된 카드가 before만 가진 채 영영
            # after를 못 받는다. 동일 객체에 기대지 않는다
            card = by_id.get(rec["id"])
            if card is not None:
                card["effect"] = dict(eff)
            key = _seal_key(rec["case"], rec["loop"], rec["verdict"])
            if eff["changed"]:
                self.ineffective.pop(key, None)
            else:
                self.ineffective[key] = self.ineffective.get(key, 0) + 1

    def sealed_keys(self) -> set:
        """연속 무효로 봉인된 (점, 자리, verdict) — 더 내지 않는다."""
        return {k for k, n in self.ineffective.items() if n >= _SEAL_AFTER}

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
                # breakpoint의 보간 괴리 — 역할은 그대로 두고 그 점의 최적 게인만
                # 적합 샘플에 고정한다. **승격 게인을 이긴다** (refit_gains)
                for slot, v in (act.get("gains") or {}).items():
                    self.refit_gains.setdefault(slot, {})[act["point"]] = float(v)
            elif act["type"] == "tighten_fit":
                # 앵커의 보간 괴리 — 샘플이 아니라 적합을 고친다 (단조 래칫).
                # 상한에 닿아도 **applied로 센다**: continue로 빠지면 effect 레코드가
                # 안 생겨 채점 대상에서 빠지고, 그러면 이 카드는 영원히 봉인되지
                # 않은 채 매 이터 applicable로 다시 잡혀 아무것도 안 바꾸는 순환을
                # 예산 소진까지 돈다. promote의 래칫 방어도 같은 규약이다
                # (skipped를 남기되 applied로 센다)
                if self.fit_tighten >= _FIT_TIGHTEN_MAX:
                    a["skipped"] = f"적합 조이기 상한({_FIT_TIGHTEN_MAX}회) 도달 — 더 조일 수 없다"
                else:
                    self.fit_tighten += 1
            elif act["type"] == "add_validation":
                self._add_validation_around(act["point"])
            applied.append(aid)
        # 감사 표식은 **실제로 반영한 것에만** — 거부한 에스컬레이션·supersede에 붙이면
        # 기록이 거짓말을 한다 (escalations가 같은 dict를 참조하므로 함께 오염된다)
        applied_set = set(applied)
        for a in self.actions:
            if a["id"] in applied_set:
                a["applied"] = True
                # 반영 전 상태를 찍어 둔다 — 다음 VERIFY가 after를 채우고 효과를 판정한다.
                # 이게 없으면 "반영됨"이 곧 "고쳐짐"으로 읽히는데, 둘은 다르다
                a["effect"] = {"before": self._loop_snapshot(a.get("case"), a.get("loop"))}
                self.applied_log.append({
                    "id": a["id"], "iter": self.iter_n, "case": a.get("case"),
                    "loop": a.get("loop"), "verdict": a.get("verdict"),
                    "type": a["action"]["type"], "effect": a["effect"],
                })
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
            rate_filters=None, fingerprint="", on_progress=None) -> dict:
        """현 스테이지부터 계속 실행 — DONE·awaiting_approval·취소에서 멈춘다.

        rate_filters: 법칙의 레이트 경로 필터 {그룹: 스펙}. `design`과 같이 **비행체
        프로파일이 주는 값**이지 사용자 요청 knob이 아니다 (데모는 fcl.demo
        demo_rate_filters — 요축 워시아웃 τ=2 s). 이것을 안 보고 도는 튜닝·검증은
        출하되지 않는 조성을 상대하게 된다 (01 §4.2).

        **None은 "안 바꾼다"**이지 "필터 없음"이 아니다 — 재개 호출이 인자를
        생략해도 저장된 값(from_dict가 복원한 것)을 이어간다. 필터를 실제로
        비우려면 빈 dict를 명시한다.
        """
        self.design = dict(design)
        # None은 "안 바꾼다" — 재개 호출이 인자를 안 주면 저장된 값을 이어간다.
        # dict(rate_filters or {})로 덮으면 재개가 조용히 필터 없는 플랜트로 돌아간다.
        if rate_filters is not None:
            self.rate_filters = dict(rate_filters)
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
            # 이 실행이 **무엇을 안 봤는가** — 실패 0이 곧 통과가 아닌 두 번째 이유다
            # (첫 번째는 judged: 아무것도 판정 안 한 실행). 공백이 있으면 "수렴"은
            # 앵커에서만 성립한 것이고, 화면이 그렇게 말해야 한다
            "coverage": self.coverage(),
            "coverage_gaps": self.coverage_gaps(),
            "ledger_size": len(self.shortfall_ledger()),
            # 반영했는데 판정이 안 움직인 처방 수 — "처방을 냈다"와 "고쳤다"는 다르다
            "ineffective_actions": sum(
                1 for r in self.applied_log if r["effect"].get("changed") is False),
            "sealed": len(self.sealed_keys()),
            "fit_tighten": self.fit_tighten,
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
            "rate_filters": {g: dict(f) for g, f in self.rate_filters.items()},
            "gain_samples": {s: dict(v) for s, v in self.gain_samples.items()},
            "tune_meta": self.tune_meta,
            "promoted_gains": {s: dict(v) for s, v in self.promoted_gains.items()},
            "refit_gains": {s: dict(v) for s, v in self.refit_gains.items()},
            "fit_tighten": self.fit_tighten,
            "applied_log": self.applied_log,
            "ineffective": dict(self.ineffective),
            "refine_report": dict(self.refine_report),
            "validation_wanted": self.validation_wanted,
            "validation_added": self.validation_added,
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
        s.rate_filters = {g: dict(f) for g, f in d.get("rate_filters", {}).items()}
        s.gain_samples = {k: dict(v) for k, v in d.get("gain_samples", {}).items()}
        s.tune_meta = d.get("tune_meta", {})
        s.promoted_gains = {k: dict(v) for k, v in d.get("promoted_gains", {}).items()}
        s.refit_gains = {k: dict(v) for k, v in d.get("refit_gains", {}).items()}
        s.fit_tighten = int(d.get("fit_tighten", 0))
        s.applied_log = list(d.get("applied_log", ()))
        s.ineffective = {k: int(v) for k, v in d.get("ineffective", {}).items()}
        s.refine_report = dict(d.get("refine_report", {}))
        s.validation_wanted = int(d.get("validation_wanted", 0))
        s.validation_added = int(d.get("validation_added", 0))
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
