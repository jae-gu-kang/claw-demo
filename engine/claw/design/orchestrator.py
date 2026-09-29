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
from claw.design.criteria import MIN, MarginCriteria, target_conflicts
from claw.design.fit import fit_quality, fit_slots
from claw.design.grid import coarse_grid
from claw.design.linmodels import LinearModelSet
from claw.design.points import (
    AXES,
    ROLE_ANCHOR,
    ROLE_BREAKPOINT,
    ROLE_RANK,
    ROLE_VALIDATION,
    OperatingPoint,
    PointSet,
    case_name,
)
from claw.design.refine import refine_trim_points
from claw.design.schedmap import margin_delta, midpoint_validation_points, scheduled_margin_map
from claw.design.tune import REASON_TEXT, TuneTargets, failed_gain_slots, tune_points
from claw.env import isa_atmosphere
from claw.opspace.verdict import VerdictContext
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
# 작동기 동특성의 마지막 폴백 — config도 기체 작동기도 없을 때(프로파일 없이 엔진을 직접
# 부르는 경우)만 쓴다. 서버 경로는 늘 기체 문서의 actuator를 넘긴다(design_inputs). 값은
# 마진 조성 기본값(pipeline.criteria.MarginComposition)과 같다 — 두 화면이 같은 점에서
# 다른 마진을 말하지 않게(드리프트는 test_eval_criteria가 지킨다). 어느 값을 썼는지는
# report의 actuator.source가 말한다 — 폴백을 기체 값인 척하지 않는다
ACTUATOR_FALLBACK = {"wn": 30.0, "zeta": 0.7}
# 스케줄 적합 축 [기본값] — 산출 표가 가는 곳(기체 문서 law.gain_tables·게인 탭)이 마하 1축
# 표만 받는다(profile/schema.py _table_mach). 고도 변동이 지배적인 자리를 고도 표로 적합하면
# apply-gains가 422로 거부됐다(실측: 고도 2개 설정에서 pitch.kp가 alt 표). 제한 밖 축의
# 변동은 적합 보고(axes_excluded)에 남고, 그 변동이 마진을 깨는지는 VERIFY가 반출될 마하
# 표로 판정한다. 런타임 스케줄은 mach·alt·fuel을 다 받으므로 API로 넓힐 수는 있으나,
# 그 결과는 문서에 반영할 수 없다(apply-gains 422). 표현(fit_mode)과 직교한다 — 지배 축
# 선택(v1.47 "1축 = 지배 축")은 이 축 안에서 한다. 표 모드에서 제한 밖 변동은 마하 분할점
# 값의 톱니·cross_axis_residual로 드러나고(fit_quality가 잰다), 반출 표는 그대로 검증한 표다
DEFAULT_SCHED_AXES = ("mach",)


@dataclass
class AutoDesignConfig:
    budget_points: int = 200
    budget_iters: int = 5
    budget_tune_evals: int = 60
    mode: str = "gated"  # "gated" [기본값 — 사용자 확정] | "auto"
    criteria: MarginCriteria = field(default_factory=MarginCriteria)
    targets: TuneTargets = field(default_factory=TuneTargets)
    refine_tol: float = 0.25  # classify tol_plant와 같은 값을 공유 (기준 이원화 금지)
    # 게인 스케줄 표현 [기본값 "table" — 사용자 확정 2026-09-26]. "table"은 튜닝값을
    # 그대로 분할점에 놓고(적합 없음) 검증은 지금처럼 점마다 선형화해서 마진을 본다.
    # 바꾼 근거는 예제 기체 실측이다: 다항은 부호 보호에 걸려 roll.k_rate 스케줄을
    # 통째로 상수로 굳혔고, 조이기 2회부터 yaw.k_rate도 상수가 됐다. 대가는 1축 붕괴의
    # 톱니이고 fit.py가 지표로 보고한다. "poly"(다항 런타임 [확정] — PolyTable →
    # PolyBlock → C claw_polyeval1d 비트 일치)는 **지우지 않고 설정으로 남긴다**:
    # 매끄러움·계수 수가 필요한 자리의 선택지이고, 01 §3.4의 확정 사항이다
    fit_mode: str = "table"
    # fit_tol 0.02 [기본값] = "적합 잔차는 그 자리 게인 스케일의 2%까지" — 웹 수동 적합
    # (lib/polyfit.js)과 같은 자리의 관례값이고 실측 근거는 없다(폐쇄망 확정 대상, 04 §10).
    # flat_tol 0.02 [기본값] = "축 방향 변동이 스케일의 2% 미만이면 그 축은 실질 무변동" —
    # fit_tol과 같은 자(둘 다 스케일 대비 비율)라 같은 수를 쓴다. 정의는 fit.py가 정본
    fit_tol: float = 0.02
    flat_tol: float = 0.02
    # tol_gain 0.10 [기본값] = "보간 게인이 그 점 자유 최적 대비 10% 넘게 어긋나면
    # 보간이 범인(valley)" — refine.tol 0.25(플랜트 변화)보다 조인 것은 게인 어긋남이
    # 마진으로 직결되기 때문인데, 10%라는 수 자체는 실측 근거 없는 잠정값이다(04 §10)
    tol_gain: float = 0.10
    # 적합 품질 문턱 (fit.fit_quality의 무차원 지표와 같은 자) — **0.0 = 판정 끔(보고만)**
    # [기본값]. 억지 기본값 금지(04 §10): 합격선 수치의 근거가 아직 없어, 켜는 것은
    # 사용자 몫이고 끈 채로도 지표·원장·화면 보고는 나간다. None 기본값을 못 쓰는
    # 것은 서버 config 검증(_check_number)이 None을 거부하기 때문이다
    fit_slope_jump_max: float = 0.0
    fit_cross_axis_max: float = 0.0
    max_degree: int = 4
    max_segments: int = 4
    n_mach: int = 5
    # 보간 구간당 검증점 수 [기본값 1 = 중점] — 05 §3. 상한 4: MAX_POINTS 200에서
    # breakpoint 인접쌍이 수십 개면 4점만으로도 검증점이 예산 몫(_VALIDATION_RESERVE_FRAC)
    # 을 다 쓴다 — 더 촘촘한 탐색은 밀도가 아니라 worst_case_search(04 §5.5 [자리])의 몫
    n_validation_between: int = 1
    alts: tuple | None = None
    fuels: tuple | None = None
    # 스케줄 적합 축 — 위 DEFAULT_SCHED_AXES 주석. AXES(mach·alt·fuel)의 부분집합
    sched_axes: tuple = DEFAULT_SCHED_AXES
    # 작동기 동특성 — None = **기체 문서의 작동기**(run(actuator=…) — 서버는 선택 기체의
    # actuator.params를 넘긴다). 수치를 주면 그 값이 이긴다(작동기 가정 연구). 종전에는
    # 30·0.7 고정이라 기체 작동기가 달라도 설계·검증이 그 값을 봤다
    actuator_wn: float | None = None
    actuator_zeta: float | None = None
    delay_s: float = 0.035
    pade_order: int = 2

    def __post_init__(self):
        if self.mode not in ("gated", "auto"):
            raise ValueError(f"mode는 'gated'|'auto': {self.mode!r}")
        if self.fit_mode not in ("poly", "table"):
            raise ValueError(f"fit_mode는 'poly'|'table': {self.fit_mode!r}")
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
        for name in ("fit_slope_jump_max", "fit_cross_axis_max"):
            v = getattr(self, name)
            if v < 0.0:
                raise ValueError(f"{name}은 0(끔) 이상: {v}")
        if self.n_mach < 2:
            raise ValueError(f"n_mach는 2 이상: {self.n_mach}")
        if not 1 <= self.n_validation_between <= 4:
            raise ValueError(f"n_validation_between은 1~4: {self.n_validation_between}")
        if self.budget_tune_evals < 0:
            raise ValueError(f"budget_tune_evals는 음수 불가: {self.budget_tune_evals}")
        for name in ("actuator_wn", "actuator_zeta"):
            v = getattr(self, name)
            if v is not None and not v > 0:
                raise ValueError(f"{name}은 양수 또는 없음(기체 작동기)이어야 함: {v}")
        axes = tuple(self.sched_axes)
        if not axes or len(set(axes)) != len(axes) or any(a not in AXES for a in axes):
            raise ValueError(f"sched_axes는 {list(AXES)}의 중복 없는 비어 있지 않은 부분집합: {list(axes)}")
        self.sched_axes = axes
        if self.delay_s < 0 or self.pade_order < 1:
            raise ValueError("delay_s는 음수 불가, pade_order는 1 이상")
        self._check_targets_meet_criteria()

    # 충돌 수준별 사유 — 합격선 충돌은 거절(ValueError)의 사유, 권장선 충돌은 경고 문구의 꼬리다
    _CONFLICT_WHY = {
        "pass": "튜닝 목표가 합격선보다 느슨하면 성공한 점이 곧바로 fail로 찍힌다",
        "rec": "튜닝에 성공한 점이 합격·주의(warn)로 찍힌다",
    }

    def _check_targets_meet_criteria(self):
        """튜너 목표가 판정선을 넘는지 — warn/fail이 의미를 갖게 하는 불변식.

        criteria(판정)와 targets(튜닝)는 서로를 모른 채 각자 기본값을 들고 있어서
        조용히 어긋난다. 어긋나면 산출물이 거짓말을 한다:
        - targets.pm_deg < criteria.pm_min_deg → 튜닝 성공점이 곧바로 fail.
          그러면 분류기가 그 점을 structural_limit로 몰아 에스컬레이션을 양산한다
          (자유 게인 최적조차 fail이니 정의상 구조 한계로 보인다).
          이것은 **설정 모순**이라 제출 시점에 막는다 (routes/design.py가 ValueError를
          422로 낸다 — 워커를 돌린 뒤 알아채면 늦다).
        - targets.gm_db < criteria.gm_good_db  → 튜닝이 **성공한** 점이 전부 warn.
          실제로 8 dB vs 10 dB로 어긋나 있었고, 화면은 경고로 뒤덮였다. 다만 합격선은
          지킨 설정이라 모순은 아니다 — 권장선보다 느슨한 목표를 일부러 고를 수도 있다.
          그래서 거절하지 않고 **경고**로 남긴다(기준 통합 ⑤ S5 — 사용자 승인 동작 변경):
          target_warnings()가 문구를 내고 DesignSession.report()["target_warnings"]가 싣는다.

        판정은 공용 함수(criteria.target_conflicts — 판정선 방향까지 아는 한 자리)가 하고, 여기는
        **정책**만 쥔다: 합격선 충돌은 거절, 권장선 충돌은 경고.
        """
        for c in target_conflicts(self.criteria, self.targets):
            if c["level"] != "pass":
                continue
            raise ValueError(
                f"targets.{c['target_key']}({c['target']:g}) {'≥' if c['direction'] == MIN else '≤'} "
                f"criteria.{c['line_key']}({c['line']:g}) 필요 — "
                + self._CONFLICT_WHY[c["level"]]
            )

    def target_warnings(self) -> list:
        """권장선보다 느슨한 튜닝 목표 — 사람이 읽는 경고 문구 목록 (없으면 빈 목록).

        저장하지 않고 매번 criteria·targets에서 다시 계산한다 — 직렬화 필드를 늘리지 않으니
        to_dict/from_dict 왕복이 그대로이고, 옛 세션을 다시 열어도 같은 경고가 나온다.
        """
        return [
            f"튜닝 목표 {c['target_key']} {c['target']:g}이 권장선 {c['line_key']} {c['line']:g}보다 "
            f"느슨하다 — " + self._CONFLICT_WHY["rec"]
            for c in target_conflicts(self.criteria, self.targets) if c["level"] == "rec"
        ]

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("criteria", "targets")}
        d["alts"] = list(self.alts) if self.alts is not None else None
        d["fuels"] = list(self.fuels) if self.fuels is not None else None
        d["sched_axes"] = list(self.sched_axes)
        d["criteria"] = self.criteria.to_dict()
        d["targets"] = self.targets.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AutoDesignConfig":
        d = dict(d)
        d["criteria"] = MarginCriteria.from_dict(d["criteria"])
        d["targets"] = TuneTargets.from_dict(d["targets"])
        for k in ("alts", "fuels", "sched_axes"):
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
        # 트림 여유 수치(01 §4.1) — 저장·재개 뒤에도 "미계산"으로 바뀌지 않게 싣는다
        "reserve": dict(getattr(tr, "reserve", None) or {}),
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
                    flags=dict(d["flags"]), params_fingerprint=d.get("fingerprint", ""),
                    reserve=dict(d.get("reserve") or {}))  # 옛 세션 저장물에는 없다 — 미계산(빈 dict)
    tr._design_dict = dict(d)  # 직렬화 멱등성 캐시 (_trim_to_dict 참조)
    return tr


def _same_tables(a: dict, b: dict) -> bool:
    """두 스케줄 표 묶음이 같은 표인가 — 재검증을 생략해도 되는 유일한 조건.

    같은 객체인지가 아니라 **값이 같은지**를 본다: 반출 경로가 표를 새로 만들어 넘길 수도
    있고(routes/design.py `_gain_export`의 다항 자리·세션 왕복 복원본), 객체 동일성에
    기대면 그 경로에서 조용히 재검증을 돌게 된다. 다항은 여기서 항상 다르다고 보고 실제
    재검증을 돌린다 — 재양자화 근사가 끼기 때문이다.
    """
    if set(a) != set(b):
        return False
    for name, ta in a.items():
        tb = b[name]
        if isinstance(ta, PolyTable) or isinstance(tb, PolyTable):
            return False
        if ta.axis_names != tb.axis_names:
            return False
        if not all(np.array_equal(x, y) for x, y in zip(ta.axes, tb.axes)):
            return False
        if not np.array_equal(ta.data, tb.data):
            return False
    return True


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


def design_inputs(built) -> dict:
    """BuiltProfile → DesignSession.run의 기체 인자 묶음 — 서버 라우트·생성 스크립트의 한 경로.

    {aircraft, stall_table, limits, db_ranges, design, rate_filters, actuator, verdict_ctx}. 기체가 주는 값은
    **전부 여기서** 뽑는다 — 호출자마다 따로 뽑으면 한 곳이 빠뜨린다(종전에는 작동기가 빠져 설계·
    검증이 늘 config의 30·0.7을 봤다). 게인 미설계 등 문서 문제는 ProfileError로 그대로 올린다
    (서버가 202 전에 422로 낸다). 작동기는 wn·zeta 두 칸만 싣는다 — 위치·속도 한계는 선형 마진
    조성에 들어가지 않는다(선형 모델은 포화를 모른다). verdict_ctx는 조건 판정 문맥 — 트림 탭과 **같은 생성자**
    (VerdictContext.from_profile)라야 같은 조건에 같은 채택·제외 사유가 선다(이관 8단계 완료 기준)."""
    act = built.actuator_params()
    return {
        "aircraft": built.aircraft(),
        "stall_table": built.stall_table(),
        "limits": built.structural_limits(),
        "db_ranges": built.db_ranges(),
        "design": built.design_gains(),
        "rate_filters": built.rate_filters(),
        "actuator": {k: act.get(k) for k in ("wn", "zeta")},
        "verdict_ctx": VerdictContext.from_profile(built),
    }


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


# 점을 판정하는 스테이지 — 조건 판정 문맥(verdict_ctx)이 있어야 시작한다
_JUDGING_STAGES = ("COARSE", "REFINE", "VERIFY")


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
        # 기체 작동기 {wn, zeta} — rate_filters와 같은 성격(프로파일이 주는 값)이라 같은
        # 규약으로 초기화·직렬화한다. config.actuator_wn·zeta가 수치면 그쪽이 이긴다(_act_kw)
        self.actuator: dict = {}
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
        # 조건 판정 문맥(VerdictContext) — run()이 받는 기체 값이라 직렬화하지 않는다(재개 호출이 다시 넘긴다).
        # 없으면 점을 판정하는 스테이지(_JUDGING_STAGES)가 시작 전에 ValueError로 멈춘다 — 옛 한 비트 판정으로 되돌아가지 않는다
        self.verdict_ctx = None

    # ── 진행/취소 ──
    def _progress(self, on_progress, done, total, message):
        if on_progress is not None and on_progress(done, total, f"[{self.stage}] {message}"):
            raise _Cancelled()

    def actuator_used(self) -> dict:
        """이 세션이 튜닝·검증·분류에 쓰는 작동기 — {wn, zeta, source: {wn, zeta}, delay_s, pade_order}.

        우선순위: config 수치(명시 — 작동기 가정 연구) > 기체 작동기(run(actuator=…)) >
        ACTUATOR_FALLBACK(엔진 직접 호출용). source가 어느 쪽인지 말한다 — 폴백을 기체 값인
        척하지 않는다."""
        c = self.config
        out = {"source": {}}
        for key, cfg_v in (("wn", c.actuator_wn), ("zeta", c.actuator_zeta)):
            prof_v = self.actuator.get(key)
            if cfg_v is not None:
                out[key], out["source"][key] = float(cfg_v), "config"
            elif prof_v is not None:
                out[key], out["source"][key] = float(prof_v), "profile"
            else:
                out[key], out["source"][key] = float(ACTUATOR_FALLBACK[key]), "default"
        out["delay_s"], out["pade_order"] = float(c.delay_s), int(c.pade_order)
        return out

    def _act_kw(self):
        act = self.actuator_used()
        return dict(actuator_wn=act["wn"], actuator_zeta=act["zeta"],
                    delay_s=act["delay_s"], pade_order=act["pade_order"],
                    rate_filters=dict(self.rate_filters))

    # ── 스테이지 ──
    def _stage_coarse(self, aircraft, stall_table, limits, db_ranges, fingerprint, cb):
        c = self.config
        out = coarse_grid(
            aircraft, stall_table, limits, db_ranges, ctx=self.verdict_ctx,
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
            aircraft, self.points, self.lms, self.trims, ctx=self.verdict_ctx,
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
        샘플은 이미 최적이고, 남은 설계변수는 **적합 자체**다. 조이는 방향으로만
        움직이는 래칫이라(허용치 ×0.5^n, 구간 +n, 상한 있음) 이터가 종료된다.
        """
        c = self.config
        n = min(self.fit_tighten, _FIT_TIGHTEN_MAX)
        return {
            "flat_tol": c.flat_tol,
            "tol_fit": c.fit_tol * (_FIT_TIGHTEN_FACTOR ** n),
            "max_degree": c.max_degree,
            "max_segments": min(_MAX_SEGMENTS_CAP, c.max_segments + n),
            # 표 모드에서는 위 세 개가 쓰이지 않는다 (fit.fit_slots 머리말) — 값을 계속
            # 넘기는 것은 왕복·저장물의 형상을 표현에 따라 갈리지 않게 두려는 것이다
            "mode": c.fit_mode,
            # 스케줄 축 제한은 표현과 직교한다 — 두 표현 모두 이 축 안에서 지배 축을 고른다
            "axes": c.sched_axes,
        }

    def _fit_exclusions(self) -> dict:
        """적합에서 뺄 표본 — {게인 자리: {점 이름: {loop, reason, basis}}} (fit.fit_slots의 exclude).

        규칙은 tune.failed_gain_slots 한 곳이다(분류기의 게인 주입·시드 중앙값도 같은 규칙을 쓴다). 두 겹이다
        (사용자 합의 규칙 2026-09-27):
        - basis "own" — 그 자리의 튜닝이 **성립하지 않았다**(tune.SLOT_DESIGN_FAILED). 실패한 튜닝이 남기는
          게인은 자리값이다(댐퍼를 끈 0, 뒤집힌 루프의 백오프 해) — 표본이 아니다.
        - basis "rate_loop" — 실패한 레이트 루프 **뒤에 닫히는** 같은 축 자리(요 실패 → 롤 댐퍼·롤 자세, 롤
          댐퍼 실패 → 롤 자세, 피치 댐퍼 실패 → 피치 자세)는 그 실패한 조성 위에서 튜닝됐다 — S1 표 모드 실측:
          롤 댐퍼 0 위의 roll.kp 0.32·ki 0.035(M0.1077/h0, 이웃 2.1·0.9), M0.113/h3000에서는 ki 0.0056(이웃 약
          1.2 — 216배 튐). 요 실패 점의 롤 댐퍼는 요 = 0인 프리픽스에서 찾은 값이라 같은 이유로 뺀다.
        target_unreached·capped는 빼지 않는다 — 목표엔 못 갔어도 **작동하는 댐퍼를 냈다**(tune 머리말).
        """
        out: dict = {}
        for name, slots in (self.tune_meta.get("slots") or {}).items():
            for gslot, rec in failed_gain_slots(slots).items():
                out.setdefault(gslot, {})[name] = rec
        return out

    def excluded_samples(self) -> list:
        """적합에서 뺀 튜닝 표본 전부 — [{slot, point, value, loop, reason, basis}] (fits 보고에서 모은다).

        보고·화면이 "이 표의 어느 점이 튜닝값이 아니라 이웃 보간인가"를 말할 수 있게 한다. 뺀 점도 VERIFY는
        그대로 판정한다 — 판정 대상은 그 점의 **보간 게인**이다."""
        rows = []
        for slot, rep in sorted(self.fits.items()):
            for r in rep.get("excluded_samples") or ():
                rows.append({"slot": slot, **r})
        return rows

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
        out = fit_slots(samples, self.points, exclude=self._fit_exclusions(), **self._fit_params())
        self.sched_tables = out["tables"]
        self.sched_constants = out["constants"]
        self.fits = out["reports"]
        self._judge_fit_quality()
        cb(1, 1, "fit")
        self.stage = "VERIFY"

    def _judge_fit_quality(self):
        """적합 품질 판정 — fits[slot]["quality"] 부착 (04 §10 갭의 소비자).

        지표(fit.fit_quality)는 항상 붙고, 문턱이 켜진(> 0) 지표만 판정한다 —
        warn까지다(verdict·자동 처방 신설 안 함: tighten_fit이 구간을 늘려 관절을
        오히려 보탤 수 있어 처방 방향이 확정되지 않았다. 04 §10 [TBD] 유지).
        """
        c = self.config
        for rep in self.fits.values():
            q = fit_quality(rep)
            checks = []
            if q["slope_jump_norm_max"] is not None:
                if c.fit_slope_jump_max > 0.0:
                    checks.append(q["slope_jump_norm_max"] <= c.fit_slope_jump_max)
                if c.fit_cross_axis_max > 0.0:
                    checks.append(q["cross_axis_frac"] <= c.fit_cross_axis_max)
            q["status"] = "na" if not checks else ("ok" if all(checks) else "warn")
            if not checks:
                q["note"] = ("상수 자리 — 관절·교차축이 없다"
                             if q["slope_jump_norm_max"] is None else
                             "문턱 미설정(0 = 끔) — 보고만 한다 [기본값]")
            rep["quality"] = q

    def _stage_verify(self, aircraft, fingerprint, cb):
        c = self.config
        wanted = midpoint_validation_points(self.points, n_between=c.n_validation_between)
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
            ctx=self.verdict_ctx, fingerprint=fingerprint,
            on_progress=lambda d, t, m: cb(d, t, m), **self._act_kw(),
        )
        if out["aborted"]:
            raise _Cancelled()
        self.margin_out = out
        # 새 판정이 나왔으니 직전에 반영한 처방들을 채점한다 — "applied"만 찍고
        # 결과를 안 보면 무효 처방이 예산을 태우는 것을 아무도 모른다
        self._score_applied_actions()
        self.stage = "CLASSIFY"

    def reverify_resampled(self, aircraft, tables: dict, *, on_progress=None) -> dict:
        """반출 표(재양자화 Table)로 검증을 다시 판정한다 — 채택되는 표현이 검증받게.

        **다항 모드의 이야기다**: 세션 검증(margin_out)은 다항 기준인데, 웹 「채택」·
        apply-gains가 주입하는 것은 resample_to_table의 근사 표다(routes/design.py
        `_gain_export`). 표 모드(fit_mode="table")에서는 반출 표가 검증한 표 그 자체라
        재계산할 것이 없다 — `_same_tables`가 그것을 짚어 사유와 함께 인용한다. 근사 오차 고지
        (resample_error — 게인 공간)만으로는 "판정이 갈렸는가"에 답하지 못하므로, 같은
        점·같은 트림·같은 기준으로 그 표를 재판정해 다항 판정과의 차이를 센다(05 §5.1).
        trims·lms 재사용이라 비용은 점당 선형 마진 계산뿐이다 — 트림·시뮬 0.

        반환: margin_delta(n_judged·changed·worse·better) + 재양자화 기준 failures
        (_worst_failures 형식 — 분류기 형식과 같아 화면이 재사용한다). 재료가 없으면
        n_judged 0 + 사유 — 조용히 통과로 위장하지 않는다.
        """
        c = self.config
        if not self.margin_out.get("cases"):
            return {"n_judged": 0, "changed": [], "worse": 0, "better": 0, "dropped": 0,
                    "failures": [], "note": "재검증 생략 — 세션에 검증 결과가 없다"}
        if not tables:
            return {"n_judged": 0, "changed": [], "worse": 0, "better": 0, "dropped": 0,
                    "failures": [], "note": "재검증 생략 — 스케줄 표가 없다(전 자리 상수)"}
        if _same_tables(self.sched_tables, tables):
            # 표 모드의 정상 경로다 — 반출 표가 세션이 검증한 그 표다(재양자화가 없다).
            # 같은 점·같은 트림·같은 기준으로 다시 돌리면 정의상 같은 결과가 나오므로
            # 계산을 생략하고 **세션 검증을 그대로 인용한다**. n_judged를 0으로 두면
            # "아무것도 안 봤다"로 읽히는데 그건 사실이 아니다 — 사유를 함께 낸다
            return {"n_judged": self.judged_count(), "changed": [], "worse": 0,
                    "better": 0, "dropped": 0,
                    "failures": list(self.margin_out.get("failures", ())),
                    "identical": True,
                    "note": "반출 표가 세션이 검증한 표와 동일 — 재양자화가 없어"
                            " 세션 검증이 곧 이 표의 검증이다 (재계산 생략)"}
        design_eff = {**self.design, **self.sched_constants}
        out = scheduled_margin_map(
            aircraft, self.points, self.lms, tables, design_eff,
            criteria=c.criteria, targets=c.targets, trims=self.trims, ctx=self.verdict_ctx,
            on_progress=on_progress, **self._act_kw(),
        )
        if out["aborted"]:
            return {"n_judged": 0, "changed": [], "worse": 0, "better": 0, "dropped": 0,
                    "failures": [], "aborted": out["aborted"], "note": "재검증 취소"}
        delta = margin_delta(self.margin_out["cases"], out["cases"], c.criteria)
        return {**delta, "failures": out["failures"]}

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
        dropped = self.excluded_samples()
        if dropped:
            by_slot: dict = {}
            for r in dropped:
                by_slot[r["slot"]] = by_slot.get(r["slot"], 0) + 1
            pts = len({r["point"] for r in dropped})
            out.append(
                f"튜닝이 성립하지 않은 표본 {len(dropped)}개(점 {pts}곳 · "
                + " · ".join(f"{k} {n}" for k, n in sorted(by_slot.items()))
                + ")를 적합에서 뺐다 — 그 점의 스케줄 값은 튜닝값이 아니라 이웃 보간이고, 검증은 그 보간값으로 했다"
            )
        for slot, rep in sorted(self.fits.items()):
            held = rep.get("exclusion_withheld")
            if held:
                # 규칙이 못 지켜진 자리다 — 표가 튜닝 실패 표본(자리값)을 담고 있다. 조용히 두면 "실패 표본은
                # 표에 안 들어간다"는 보장이 거짓이 된다
                out.append(
                    f"{slot}: 튜닝 실패 표본 {len(held['samples'])}개를 빼면 {held['kept_would_be']}개만 남아"
                    " 제외를 보류했다 — 이 자리의 표는 실패 표본을 담고 있다"
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
        #    적합에서 뺀 게인 자리를 행에 붙인다 — 그 점의 스케줄 값은 튜닝값이 아니라 이웃 보간이다
        excluded: dict = {}
        for r in self.excluded_samples():
            excluded.setdefault((r["point"], r["loop"]), []).append(r["slot"])
        for name, slots in (self.tune_meta.get("slots") or {}).items():
            for loop, rec in slots.items():
                if rec.get("status") == "ok":
                    continue
                add(name, loop, "tune", REASON_TEXT.get(rec.get("reason")),
                    reason=rec.get("reason"), status=rec.get("status"),
                    target=rec.get("target"), achieved=rec.get("achieved"),
                    fit_excluded=sorted(excluded.get((name, loop), ())))
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

        # ④ 적합 품질 문턱을 넘은 자리 (04 §10 부분 해소) — 점이 아니라 자리(slot)의
        #    속성이라 point는 None이다. severity는 문턱 대비 초과 비율(엔진 severity와
        #    같은 축 — 요구선 대비 비율)로 실어 정렬에 낀다
        for slot, rep in self.fits.items():
            q = rep.get("quality") or {}
            if q.get("status") != "warn":
                continue
            over = []
            sev = 0.0
            for key, cap in (("slope_jump_norm_max", self.config.fit_slope_jump_max),
                             ("cross_axis_frac", self.config.fit_cross_axis_max)):
                v = q.get(key)
                if cap > 0.0 and v is not None and v > cap:
                    over.append(f"{key} {v:.3g} > {cap:.3g}")
                    sev = max(sev, v / cap - 1.0)
            add(None, slot, "fit_quality",
                "적합 품질 문턱 초과 — " + " · ".join(over)
                + " (급한 관절·교차축 잔차는 스케줄 전이 채터링 소지다)",
                status="warn", severity=sev, quality=dict(q))

        # 측정 불가(None)가 맨 앞, 그 뒤로 부족 비율 내림차순
        rows.sort(key=lambda r: (0 if r["severity"] is None else 1,
                                 -(r["severity"] or 0.0)))
        return rows

    def failures_by_role(self) -> dict:
        """실패를 점 역할별로 — 같은 "실패 N"이 표현에 따라 다른 뜻을 갖기 때문이다.

        표 모드(기본)에서는 앵커의 실효 게인이 **그 점의 튜닝값 자체**인 경우가 많다
        (지배 축 좌표가 그 점 하나뿐이면 평균이 아니라 그 값이 그대로 들어간다). 그런
        앵커가 통과하는 것은 "튜닝이 성립했다"는 말에 가깝고, 스케줄이 성립하는지를
        말하는 것은 **점 사이(검증점)** 판정이다. 두 수를 합쳐만 내면 그 구별이 사라진다
        — 다항 모드에서도 적합 괴리(앵커)와 보간 괴리(검증점)는 다른 처방으로 간다(§7).
        """
        out: dict = {}
        for f in self.margin_out.get("failures", ()):
            pt = self.points.get(f.get("case")) if f.get("case") in self.points else None
            role = pt.role if pt is not None else "unknown"
            out[role] = out.get(role, 0) + 1
        return out

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
            # 실패마다 진행 보고 — 여기가 한 실행에서 가장 긴 구간일 수 있다(실측: 실패
            # 56개 ≈ 25 s, 325개 ≈ 100 s). cb는 취소 요청이면 _Cancelled를 던진다 — 상태를
            # 아직 안 바꿨으므로 CLASSIFY부터 그대로 재개된다
            on_progress=lambda d, t, m: cb(d, t, m),
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
                if self.config.fit_mode != "poly":
                    # 표 모드에는 조일 적합이 없다. 남은 어긋남은 **1축 붕괴**(같은 축값의
                    # 다른 축 샘플을 평균) 탓이라 조이기로는 안 풀린다 — 사유를 달아
                    # 건너뛰되 applied로는 센다(위 상한 분기와 같은 규약: effect 레코드가
                    # 안 생기면 채점·봉인에서 빠져 매 이터 다시 잡힌다)
                    a["skipped"] = ("표 모드 — 조일 적합이 없다. 이 어긋남은 스케줄 축(sched_axes"
                                    " — 기본 마하) 하나로 펴면서 다른 축 샘플을 평균한 대가이고, 다축 표가"
                                    " 있어야 풀린다 [백로그 05 §9]")
                elif self.fit_tighten >= _FIT_TIGHTEN_MAX:
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
    def run(self, aircraft, stall_table, limits, db_ranges, design, *, verdict_ctx,
            rate_filters=None, actuator=None, fingerprint="", on_progress=None) -> dict:
        """현 스테이지부터 계속 실행 — DONE·awaiting_approval·취소에서 멈춘다.

        rate_filters: 법칙의 레이트 경로 필터 {그룹: 스펙}. `design`과 같이 **비행체
        프로파일이 주는 값**이지 사용자 요청 knob이 아니다 (예제 기체는
        BuiltProfile.rate_filters() — 요축 워시아웃 τ=2 s). 이것을 안 보고 도는 튜닝·검증은
        출하되지 않는 조성을 상대하게 된다 (05 §4.1).

        **None은 "안 바꾼다"**이지 "필터 없음"이 아니다 — 재개 호출이 인자를
        생략해도 저장된 값(from_dict가 복원한 것)을 이어간다. 필터를 실제로
        비우려면 빈 dict를 명시한다.

        actuator: 기체 작동기 {wn, zeta}(BuiltProfile.actuator_params()의 그 두 칸) —
        rate_filters와 같은 규약(None = 안 바꾼다). config.actuator_wn·zeta가 수치면
        그쪽이 이긴다(actuator_used).

        verdict_ctx: 조건 판정 문맥(VerdictContext — design_inputs가 BuiltProfile에서 만든다). 격자·보강·검증점의
        채택이 이것으로 정해진다 — 트림 탭과 같은 판정이다(opspace/verdict.py). 필수다: 기체 값이라 재개 호출도 넘긴다.
        점을 판정하는 스테이지(COARSE·REFINE·VERIFY)가 문맥 없이 시작되면 이름으로 멈춘다. 문맥이 오면 판정 없이 저장된
        옛 점(v1.65 전 세션)을 지금 정책으로 다시 판정한다 — 한 세션 안에 두 채택 정책이 섞이지 않게.
        """
        # 승인 대기는 아래에서 판정 없이 바로 돌아간다 — 그 경로는 문맥이 없어도 된다
        if verdict_ctx is None and self.stage in _JUDGING_STAGES and self.status != "awaiting_approval":
            raise ValueError(f"verdict_ctx가 없다 — {self.stage} 스테이지는 점을 판정한다(design_inputs의 verdict_ctx를 넘긴다)")
        self.design = dict(design)
        self.verdict_ctx = verdict_ctx
        if verdict_ctx is not None:
            self._rejudge_legacy_points()
        # None은 "안 바꾼다" — 재개 호출이 인자를 안 주면 저장된 값을 이어간다.
        # dict(rate_filters or {})로 덮으면 재개가 조용히 필터 없는 플랜트로 돌아간다.
        if rate_filters is not None:
            self.rate_filters = dict(rate_filters)
        if actuator is not None:
            self.actuator = {k: float(actuator[k]) for k in ("wn", "zeta")
                             if actuator.get(k) is not None}
        if self.status == "awaiting_approval":
            return self.report()  # 승인 없이 재호출 — 상태 유지 (apply_actions가 풀어 준다)
        self.status = "running"

        def cb(done, total, message):
            self._progress(on_progress, done, total, message)

        try:
            while self.stage != "DONE":
                if self.verdict_ctx is None and self.stage in _JUDGING_STAGES:
                    raise ValueError(f"verdict_ctx가 없다 — {self.stage} 스테이지는 점을 판정한다")
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

    def _rejudge_legacy_points(self):
        """판정(verdict) 없이 저장된 점을 지금 정책으로 다시 판정한다 — 트림이 남아 있는 점만(없으면 미판정 그대로)."""
        from claw.opspace.verdict import condition_verdict

        for pt in self.points:
            tr = self.trims.get(pt.name)
            if pt.verdict is None and tr is not None:
                pt.verdict = condition_verdict(tr, self.verdict_ctx)
                pt.trimmable = pt.verdict["adopted"]

    def report(self) -> dict:
        c = self.config
        roles = {r: len(self.points.by_role(r))
                 for r in (ROLE_ANCHOR, ROLE_BREAKPOINT, ROLE_VALIDATION)}
        return {
            "status": self.status, "stage": self.stage, "iterations": self.iter_n,
            "points": roles, "n_points": len(self.points),
            "failures": len(self.margin_out.get("failures", ())),
            # 실패가 앵커인지 점 사이인지 — 표 모드에서 앵커 통과는 튜닝 성립에 가깝고
            # 스케줄 성립을 말하는 것은 검증점이다 (failures_by_role 머리말)
            "failures_by_role": self.failures_by_role(),
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
            # 어느 표현으로 검증한 결과인가 — 화면·저장물이 표와 다항을 구별해야 한다
            # (표 모드는 재양자화가 없어 반출 표가 검증받은 표 그 자체다)
            "fit_mode": c.fit_mode,
            "fit_tighten": self.fit_tighten,
            # 튜닝이 성립하지 않아 적합에서 뺀 표본 — 그 점의 게인은 이웃 보간이다(표에 자리값 0이 안 박힌다).
            # 보류(표본이 2개 미만으로 남아 못 뺀 자리)는 따로 센다 — 그 자리의 표는 실패 표본을 담고 있다
            "excluded_samples": self.excluded_samples(),
            "exclusion_withheld": sorted(slot for slot, rep in self.fits.items()
                                         if rep.get("exclusion_withheld")),
            # 적합 품질 경고 수 — 문턱을 켠 실행에서만 0이 아닐 수 있다 (04 §10)
            "fit_quality_warns": sum(
                1 for rep in self.fits.values()
                if (rep.get("quality") or {}).get("status") == "warn"),
            "criteria_fingerprint": c.criteria.fingerprint(),
            # 권장선보다 느슨한 튜닝 목표 — 거절하지 않고 여기서 말한다(AutoDesignConfig.target_warnings).
            # 이게 있으면 warn 판정은 "목표 미달"이 아니라 설정이 예고한 결과다
            "target_warnings": c.target_warnings(),
            # 튜닝·검증이 본 작동기와 그 출처(config·profile·default) — 판정 조성의 일부다
            "actuator": self.actuator_used(),
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
            "actuator": dict(self.actuator),
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
        # 옛 저장물에는 없다 — 그때 config에 작동기 수치가 명시돼 있어(30·0.7) 그쪽이 이긴다
        s.actuator = {k: float(v) for k, v in (d.get("actuator") or {}).items()}
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
