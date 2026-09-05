"""게인 설계 평가기준 정본 — 필수 11항목의 문턱값 데이터 (02 §2.4 확장).

지금까지 폐루프 판정선은 diagnose.py 모듈 상수(THRESHOLDS·_GRID_CHECKS)로,
마진 판정선은 design/criteria.py MarginCriteria로 흩어져 있었고, 항목 4·6·7·8·
10·11(응답특성·액추에이터 여유·권한·동시명령·회복·스케줄 전이)은 판정선 자체가
없었다. 이 모듈이 11항목 전체의 문턱을 **한 데이터**로 정본화한다.

MarginCriteria는 **수정하지 않고 합성**한다 — 그 dataclass는 오토디자인 핫패스
(judge/shortfall/fingerprint, AutoDesignConfig.__post_init__ 정합 검사)에 결합돼
있어 필드를 늘리면 오토디자인 전체가 다시 계약을 통과해야 한다. 항목 2·3은 기존
인스턴스를 그대로 꽂는다.

**하드 게이트의 목록은 여기 없다** — 무엇이 하드 실패인가(불안정·포화·α/Nz 초과·
GM/PM 미달)는 pipeline/evaluate.py의 코드 상수다. 설정으로 하드 제약을 끌 수 있으면
게이트가 아니다. 이 모듈은 **문턱값만** 쥔다.

기본값 시딩 원칙: 기존 판정선과 같은 값으로 시작한다 (sat_frac 0.05 =
diagnose.SAT_FRAC_WARN, rms = diagnose.RMS_THRESH, windup 0.02 =
diagnose.WINDUP_FRAC, α 마진 0.0 = diagnose._GRID_CHECKS) — 기준 정본화가
조용한 판정 변화가 되면 안 된다. 값의 출처가 바뀌는 것이지 값이 바뀌는 게 아니다.

`fingerprint()`가 기준 버전의 계보 키다 (02 §5.4 "합격기준을 파라미터로 관리하면
판정 기준이 지문에 포함됨") — 평가 결과 저장물에 동봉해 "무슨 기준으로 판정했나"를
남긴다.

향후 복수 게인 조정 최적화기는 이 기준을 evaluate()와 함께 적합도 함수로 그대로
소비한다 — 가중치(JWeights)가 그 목적함수 J의 정본이다.
"""

import math
from dataclasses import asdict, dataclass, field, fields

from claw.design.criteria import MarginCriteria
from claw.design.tune import TuneTargets
from claw.params.paramset import canonical_hash

# 기준 스키마 버전 — v2: A/B/C 등급 재편(J 5항 재정의·권한 하드·트림→권한 그룹).
# 지문이 v1과 달라지는 것은 의도된 단절이고, 화면은 이 번호로 "구버전 스키마"를
# 지문 불일치와 구분해 말한다.
SCHEMA_VERSION = 2


def _frac(name, v, lo=0.0, hi=1.0):
    x = float(v)
    if not (lo <= x <= hi) or math.isnan(x):
        raise ValueError(f"{name}은 [{lo}, {hi}] 필요: {v}")
    return x


def _pos(name, v):
    x = float(v)
    if not x > 0.0 or not math.isfinite(x):
        raise ValueError(f"{name}은 양수여야 함: {v}")
    return x


@dataclass(frozen=True)
class StabilityCriteria:
    """항목 1 — 폐루프 안정성. 발산 실근은 배진폭 시간으로 허용선을 긋는다.

    나선 모드의 완만한 발산은 관례상 허용된다(MIL-8785 Level 1: 배진폭 ≥ 20 s) —
    실근 발산을 무조건 fail로 하면 정상 설계가 상시 빨간불이 된다. 진동쌍(복소)의
    발산은 허용선이 없다 — 무조건 fail.
    """

    t2_min_s: float = 20.0  # 발산 **실근**의 배진폭 시간 허용선 [s]

    def __post_init__(self):
        _pos("t2_min_s", self.t2_min_s)


@dataclass(frozen=True)
class AuthorityCriteria:
    """A⑦ 제어권한 — 트림 소모 + 비행 중 잔여 권한(엘레본 예산). 수렴 게이트와 별개.

    trim/trim.py SAT_FRAC(0.95)은 "트림 해가 경계에 앉았나"(수렴 판정)이고, 여기는
    "트림 뒤·기동 중 여유가 남나"다 — 트림에서 이미 85 %를 쓰면 동특성 게인이
    아무리 좋아도 실질 기동 여유가 없다. b_min_frac은 **하드 게이트**의 문턱이다:
    비행 중 최소 잔여 권한(min_pitch/roll_authority_frac — 배분 신호 계측)이 이
    아래면 그 형상은 Fail. 계측이 없는 형상(alloc 미장착)에서는 하드 판정에서
    빠진다(evaluate의 envelope.nz 패턴).
    """

    de_frac_warn: float = 0.5  # |δe_trim| / 한계 — 이 위면 warn
    de_frac_max: float = 0.85  # 이 위면 fail (기동 여유 실질 소진)
    b_min_frac: float = 0.10  # 비행 중 최소 잔여 권한 / 엘레본 예산 — 하드 하한

    def __post_init__(self):
        if not 0.0 < self.de_frac_warn <= self.de_frac_max <= 1.0:
            raise ValueError(
                f"0 < de_frac_warn({self.de_frac_warn}) ≤ de_frac_max"
                f"({self.de_frac_max}) ≤ 1 필요")
        _frac("b_min_frac", self.b_min_frac)


@dataclass(frozen=True)
class ActuatorCriteria:
    """항목 6 — 위치/레이트 **여유**. 한계를 안 넘는 것으론 부족하고 남는 여유를 잰다.

    포화율(sat_frac·rate_sat_frac)은 하드 게이트의 문턱이고, 여유(pos_margin ·
    근접 체류)는 감점(warn)이다 — "정상 기동에서 한계 근처를 계속 쓰는 게인"도
    좋은 설계가 아니라는 요구의 자리.
    """

    sat_frac_max: float = 0.05  # 위치 포화 시간비 (diagnose.SAT_FRAC_WARN 시드)
    rate_sat_frac_max: float = 0.05  # 타율 포화 시간비
    pos_margin_min_frac: float = 0.10  # 1 − 최대사용률 이 아래면 warn
    rate_margin_min_frac: float = 0.10
    near_limit_band: float = 0.90  # 한계의 이 배율 위를 "근접"으로 본다
    near_limit_frac_max: float = 0.10  # 근접 체류 시간비 이 위면 warn

    def __post_init__(self):
        for n in ("sat_frac_max", "rate_sat_frac_max", "pos_margin_min_frac",
                  "rate_margin_min_frac", "near_limit_frac_max"):
            _frac(n, getattr(self, n))
        if not 0.0 < self.near_limit_band < 1.0:
            raise ValueError(f"near_limit_band는 (0, 1) 필요: {self.near_limit_band}")


@dataclass(frozen=True)
class EnvelopeCriteria:
    """항목 5 — 실속·엔벨로프 마진. nz/q 한계는 계측 신설 전까지 None(=미계측).

    None은 "한계 없음"이 아니라 "이 판정을 아직 못 한다"다 — evaluate가 na로 낸다.
    q_rate_limit은 **피치레이트**[rad/s] 해석이다(동압은 mach·고도 플래그가 간접
    커버) — 사용자 확인 예정 [가정].
    """

    alpha_margin_min: float = 0.0  # worst_stall_margin 하한 (기존 판정선과 동일)
    limiter_frac_max: float = 0.02  # α리미터 작동 시간비 (diagnose.LIMITER_FRAC 시드)
    nz_limit: float | None = None  # [TBD] 수직하중배수 상한 — V-n n_lim에서 시드 예정
    q_rate_limit: float | None = None  # [TBD] 피치레이트 상한 [rad/s]

    def __post_init__(self):
        if not math.isfinite(float(self.alpha_margin_min)):
            raise ValueError(f"alpha_margin_min은 유한값: {self.alpha_margin_min}")
        _frac("limiter_frac_max", self.limiter_frac_max)
        for n in ("nz_limit", "q_rate_limit"):
            v = getattr(self, n)
            if v is not None:
                _pos(n, v)


@dataclass(frozen=True)
class ResponseCriteria:
    """항목 4 — 명령 추종. RMS는 기존 판정선(diagnose.RMS_THRESH 시드)이고
    Tr/Ts/Mp/sse 문턱은 응답특성 지표 신설과 함께 채운다(빈 dict = 아직 판정선 없음).

    settle_band_frac은 Ts(재정착) 판정 밴드다 — 문턱이 아니라 **정의의 일부**라
    여기 산다(±2 %가 관례).
    """

    rms_max: dict = field(default_factory=lambda: {"alt": 10.0, "spd": 2.0, "hdg": 0.1})
    tr_max: dict = field(default_factory=dict)  # {"alt": s, ...} [TBD]
    ts_max: dict = field(default_factory=dict)
    mp_max: dict = field(default_factory=dict)  # 비율 (0.08 = 8 %)
    sse_max: dict = field(default_factory=dict)  # 절대 단위 (m·m/s·rad)
    # Ts의 정착 밴드(±2 %)는 문턱이 아니라 **측정의 정의**라 여기 없다 —
    # pipeline/metrics.py SETTLE_BAND_FRAC이 정본이다 (측정과 정의는 한 몸)
    # 대역폭 창 [TBD] — 상한 근거(구조모드 이격)가 데모에 없다. 값 없이 자리만 둔다
    bandwidth_window: tuple | None = None

    def __post_init__(self):
        for n in ("rms_max", "tr_max", "ts_max", "mp_max", "sse_max"):
            for k, v in getattr(self, n).items():
                _pos(f"{n}[{k}]", v)


@dataclass(frozen=True)
class CouplingCriteria:
    """항목 8 — 교차축·동시명령 (델타익 필수). 동시 기동의 크기와 그때의 문턱.

    피치·롤이 같은 엘레본 예산을 나눠 쓰므로(fcl/graphs.py 배분) 단독축 시험만으로는
    부족하다 — 롤이 권한을 소모한 상태의 피치업에서 실속·포화 마진이 남는지가 질문.
    """

    dh: float = 100.0  # 동시 기동 고도 스텝 [m] (표준 기동과 같은 값 시드)
    dpsi: float = 0.5  # 동시 기동 헤딩 스텝 [rad] — 뱅크(롤 예산 소모) 유도
    alpha_margin_min: float = 0.0  # 동시 기동 중 실속마진 하한
    sat_frac_max: float = 0.05  # 동시 기동 중 위치 포화 시간비 상한
    nz_limit: float | None = None  # [TBD] — envelope와 같은 사유

    def __post_init__(self):
        for n in ("dh", "dpsi"):
            if not math.isfinite(float(getattr(self, n))):
                raise ValueError(f"{n}은 유한값: {getattr(self, n)}")
        if self.dh == 0.0 or self.dpsi == 0.0:
            raise ValueError("dh·dpsi 중 0이 있다 — 두 축이 동시에 걸려야 동시명령이다")
        _frac("sat_frac_max", self.sat_frac_max)
        if not math.isfinite(float(self.alpha_margin_min)):
            raise ValueError(f"alpha_margin_min은 유한값: {self.alpha_margin_min}")
        if self.nz_limit is not None:
            _pos("nz_limit", self.nz_limit)


@dataclass(frozen=True)
class RecoveryCriteria:
    """항목 10 — 포화 회복·안티와인드업. 포화가 풀린 뒤 깨끗이 돌아오는가."""

    overshoot_max_frac: float = 0.20  # 해제 후 재초과 비율 상한
    resettle_max_s: float = 5.0  # 해제 후 재정착 시간 상한 [s]
    windup_frac_max: float = 0.02  # 적분기 클램프 주차 시간비 (diagnose.WINDUP_FRAC 시드)

    def __post_init__(self):
        _frac("overshoot_max_frac", self.overshoot_max_frac, hi=10.0)
        _pos("resettle_max_s", self.resettle_max_s)
        _frac("windup_frac_max", self.windup_frac_max)


@dataclass(frozen=True)
class ScheduleCriteria:
    """항목 11 — 스케줄 전이. 인접 격자점 상대 점프 상한과 중간점 평가 스위치.

    per_table은 {테이블 이름: 상한} 예외다 — 클램프 곡선처럼 계단이 의도인 테이블에
    전역 상한을 강요하지 않기 위한 자리.
    """

    rel_step_max: float = 0.5  # 인접 격자점 |ΔK|/max(|K|) 상한 [기본값]
    per_table: dict = field(default_factory=dict)
    midpoints: bool = True  # 격자점 사이 중간점 케이스를 평가에 포함할지
    # 결함 케이스 비율이 이 이하면 국소(스케줄 셀 형상), 넘으면 전역(설계점 게인).
    # "어느 층을 만질 것인가"의 분기라 스케줄 기준과 한 몸이다 (diagnose.LOCAL_FRAC 시드)
    local_frac: float = 1.0 / 3.0

    def __post_init__(self):
        _pos("rel_step_max", self.rel_step_max)
        _frac("local_frac", self.local_frac, lo=1e-6, hi=1.0)
        for k, v in self.per_table.items():
            _pos(f"per_table[{k}]", v)

    def limit_for(self, table_name: str) -> float:
        return float(self.per_table.get(table_name, self.rel_step_max))


@dataclass(frozen=True)
class RobustnessCriteria:
    """항목 9 — 강건성 분산. 결정적 코너가 1차이고 Monte-Carlo는 자리만 있다.

    cg_frac 기본 0.0은 [TBD]의 정직한 표기다 — 데모 기체는 cg_empty=cg_full=0이고
    모멘트 기준점 이전이 미구현이라(plant/aircraft.py) CG를 흔들어도 동역학이 안
    변한다. 0이 아닌 값을 기본으로 두면 "CG ±20 % 통과"가 조용한 거짓 합격이 된다.
    """

    mass_frac: float = 0.20
    cmalpha_frac: float = 0.20
    cmq_frac: float = 0.20
    cg_frac: float = 0.0  # [TBD] 모멘트 기준점 이전 구현 전까지 무효
    corners: str = "axis"  # 'axis'(축별 ±, n×2회) | 'vertices'(2^n 코너)
    monte_carlo_n: int = 0  # 0 = 비활성 [확장 자리 — 샘플링 구현은 스코프 밖]

    def __post_init__(self):
        for n in ("mass_frac", "cmalpha_frac", "cmq_frac", "cg_frac"):
            _frac(n, getattr(self, n))
        if self.corners not in ("axis", "vertices"):
            raise ValueError(f"corners는 'axis'|'vertices': {self.corners}")
        if int(self.monte_carlo_n) < 0:
            raise ValueError(f"monte_carlo_n ≥ 0 필요: {self.monte_carlo_n}")


@dataclass(frozen=True)
class JWeights:
    """최적화 점수 J = w_ζ·J_ζ + w_BW·J_BW + w_RMS·J_RMS + w_Mp·J_Mp + w_δ·J_δ
    의 가중치 (v2 — 사용자 확정 정의. 구 track/surf/rate/overshoot/settle 5항을
    대체한다). 각 항은 무차원 정규화값이다(evaluate 참조):

      J_ζ  = 목표 감쇠(targets.zeta_sp·zeta_dr) 대비 부족 비율²
      J_BW = 목표 대역폭(targets.roll_lambda) 대비 부족 비율² — 피치 BW 목표는 [TBD]
      J_RMS = Σ (추종 RMS / 판정선)²
      J_Mp = 오버슈트 비율² — Ts는 J에 없다(카드 표시 전용, 사용자 정의)
      J_δ  = 위치·타율 정규화 사용량²의 평균 (surf·rate 0.5씩 합성)

    GM/PM은 여기 없다 — 목적함수가 아니라 **제약조건**이다(하드 게이트).
    하드 통과 후보 사이의 서열이지 합격/불합격이 아니고, 어느 항이든 지표가
    None이면 J도 None이다(0으로 위장 금지).

    w_zeta·w_bw 기본값은 [가정·TBD] — 교정 데이터가 생기면 재검토. 나머지는
    v1 값 계승(w_rms=구 w_track, w_mp=구 w_overshoot, w_delta≈구 surf+rate 합).
    """

    w_zeta: float = 0.3  # [가정 — 교정 전 임시값]
    w_bw: float = 0.3  # [가정 — 교정 전 임시값]
    w_rms: float = 1.0
    w_mp: float = 0.5
    w_delta: float = 0.15

    def __post_init__(self):
        for f in fields(self):
            v = float(getattr(self, f.name))
            if v < 0.0 or not math.isfinite(v):
                raise ValueError(f"{f.name}은 0 이상 유한값: {v}")


_SUBS = {
    "margin": MarginCriteria,
    "stability": StabilityCriteria,
    "authority": AuthorityCriteria,
    "actuator": ActuatorCriteria,
    "envelope": EnvelopeCriteria,
    "response": ResponseCriteria,
    "coupling": CouplingCriteria,
    "recovery": RecoveryCriteria,
    "schedule": ScheduleCriteria,
    "robustness": RobustnessCriteria,
    "targets": TuneTargets,
    "weights": JWeights,
}


@dataclass(frozen=True)
class GainEvalCriteria:
    """A/B/C 등급 평가기준 한 벌 — evaluate()·verify()의 판정 입력이자 계보 데이터.

    targets는 J_ζ·J_BW의 목표값 정본이다 — 오토디자인 튜너의 TuneTargets를 그대로
    합성한다(재기술 금지: 튜너가 겨냥한 목표와 평가가 재는 목표가 같은 수여야
    "튜닝 성공 = 좋은 J"가 성립한다).
    """

    margin: MarginCriteria = field(default_factory=MarginCriteria)  # A②③ + ζ 하드
    stability: StabilityCriteria = field(default_factory=StabilityCriteria)  # B 극점
    authority: AuthorityCriteria = field(default_factory=AuthorityCriteria)  # A⑦
    actuator: ActuatorCriteria = field(default_factory=ActuatorCriteria)  # A⑦(사용률)
    envelope: EnvelopeCriteria = field(default_factory=EnvelopeCriteria)  # B 엔벨로프
    response: ResponseCriteria = field(default_factory=ResponseCriteria)  # A④⑤⑥·B
    coupling: CouplingCriteria = field(default_factory=CouplingCriteria)  # B 교차축
    recovery: RecoveryCriteria = field(default_factory=RecoveryCriteria)  # B 회복
    schedule: ScheduleCriteria = field(default_factory=ScheduleCriteria)  # B 전이
    robustness: RobustnessCriteria = field(default_factory=RobustnessCriteria)  # C
    targets: TuneTargets = field(default_factory=TuneTargets)  # J_ζ·J_BW 목표
    weights: JWeights = field(default_factory=JWeights)

    def to_dict(self) -> dict:
        out = {"schema_version": SCHEMA_VERSION}
        for name in _SUBS:
            sub = getattr(self, name)
            d = sub.to_dict() if hasattr(sub, "to_dict") else asdict(sub)
            # tuple은 JSON 왕복에서 list가 된다 — 지문이 왕복 전후로 갈리지 않게
            # 여기서 미리 list로 낸다 (bandwidth_window)
            out[name] = {k: list(v) if isinstance(v, tuple) else v
                         for k, v in d.items()}
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "GainEvalCriteria":
        """dict → 기준. 모르는 키는 오류다 — 오타가 기본값으로 조용히 대체되면
        사용자는 자기 문턱이 반영됐다고 믿는다 (서버 422의 근거)."""
        if d is None:
            return cls()
        d = dict(d)
        ver = d.pop("schema_version", SCHEMA_VERSION)
        if ver != SCHEMA_VERSION:
            # 구 스키마(v1: trim 그룹·w_track류 가중치)는 조용히 매핑하지 않는다 —
            # 문턱 체계가 달라졌는데 절반만 이식되면 "내 기준이 반영됐다"는 착각이 된다
            raise ValueError(
                f"기준 스키마 v{ver}는 지원하지 않는다 (현재 v{SCHEMA_VERSION}) — "
                "기본값에서 다시 시작하세요")
        unknown = set(d) - set(_SUBS)
        if unknown:
            raise ValueError(f"알 수 없는 기준 그룹: {sorted(unknown)}")
        kwargs = {}
        for name, sub_cls in _SUBS.items():
            if name not in d or d[name] is None:
                continue
            sub_d = dict(d[name])
            if name == "response" and sub_d.get("bandwidth_window") is not None:
                sub_d["bandwidth_window"] = tuple(sub_d["bandwidth_window"])
            try:
                kwargs[name] = (sub_cls.from_dict(sub_d)
                                if hasattr(sub_cls, "from_dict") else sub_cls(**sub_d))
            except TypeError as e:
                # dataclass가 모르는 필드는 TypeError로 나온다 — 사유를 사람 말로
                raise ValueError(f"기준 그룹 '{name}' 필드 오류: {e}") from None
        return cls(**kwargs)

    def to_diagnose_thresholds(self) -> dict:
        """단일런 진단(diagnose_run)이 쓰는 문턱 — **이 정본에서 파생**한다.

        진단과 평가가 각자 상수를 들면 같은 런이 화면마다 다른 판정을 받는다
        (사용자가 기준을 바꿔도 진단만 옛 숫자로 판정하는 자리였다). 귀속 비율
        (filter_dominance·contrib_dominance)은 여기 없다 — 그건 합격선이 아니라
        "어느 항이 주도했나"를 가르는 **방법 파라미터**라 진단 모듈이 보유한다.
        """
        return {
            "rms": dict(self.response.rms_max),
            "sat_frac": self.actuator.sat_frac_max,
            "windup_frac": self.recovery.windup_frac_max,
            "limiter_frac": self.envelope.limiter_frac_max,
            "local_frac": self.schedule.local_frac,
        }

    def to_grid_thresholds(self) -> dict:
        """격자 국소성 판정(diagnose_grid)이 쓰는 지표별 문턱 — 같은 정본에서."""
        rms = self.response.rms_max
        out = {}
        for axis, key in (("alt", "alt_rms"), ("spd", "spd_rms"), ("hdg", "hdg_rms")):
            if axis in rms:
                out[key] = float(rms[axis])
        out["surf_sat_frac"] = float(self.actuator.sat_frac_max)
        out["limiter_frac"] = float(self.envelope.limiter_frac_max)
        out["worst_stall_margin"] = float(self.envelope.alpha_margin_min)
        return out

    def fingerprint(self) -> str:
        """판정 기준의 계보 지문 — 평가 저장물에 동봉 (02 §5.4)."""
        return canonical_hash(self.to_dict())
