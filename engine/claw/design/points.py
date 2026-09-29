"""역할(role) 있는 운영점 집합 — 자동 설계 루프의 단일 정본 상태.

세 역할은 문서(01 §3.4 · 01 §4.1)의 세 개념을 타입으로 구분한 것이다:
- anchor     : 트림·선형화점 (플랜트를 실제로 아는 점)
- breakpoint : 게인 스케줄 격자점 (게인이 고정되는 점)
- validation : 마진 검증점 (보간 구간을 확인하는 점)

역할은 서열이 있고(validation < breakpoint < anchor) 승격은 **단방향 래칫**이다 —
분류기(classify)가 검증점을 breakpoint·anchor로 올릴 수는 있어도 되돌릴 수 없어,
이터레이션이 같은 점을 두고 진동하지 않는다 (orchestrator 종료 보장의 한 겹).

serpentine()은 web/js/lib/grid.js serpentineCases의 Python 이식 — 의도적 중복이다
(웹은 수동 격자, 엔진은 자동 격자). 리스트상 인접 = 물리 인접이 되어
trim_batch의 인접 시드·연속성 판정 전제를 만족시킨다. 케이스 이름도 웹
nameCases와 같은 원칙(비반올림 — 반올림 이름은 정밀 격자에서 겹치고, 겹친
이름은 매핑을 조용히 오귀속시킨다)을 따른다.
"""

import copy
from dataclasses import dataclass, field

from claw.common.contracts import TrimCase
from claw.trim import saturation_detail

ROLE_VALIDATION = "validation"
ROLE_BREAKPOINT = "breakpoint"
ROLE_ANCHOR = "anchor"
ROLE_RANK = {ROLE_VALIDATION: 0, ROLE_BREAKPOINT: 1, ROLE_ANCHOR: 2}

AXES = ("mach", "alt", "fuel")  # fcl/schedule.py SCHED_VARS와 같은 축 — 스케줄 변수가 곧 격자 축


def envelope_ok(tr, ctx) -> bool:
    """이 트림해를 자동 설계가 **채택**하는가 — 공통 조건 판정의 채택(opspace/verdict.py condition_verdict).

    트림 계산 가능 ∧ 모델 유효 ∧ 제한 충족, 미평가는 통과가 아니다(05 §11.3 · 이관 8단계). 여유 미달은 채택을 막지
    않는다(v1.65 채택 정책 — 판정의 margin 항목에 표시만 남는다). 종전에는
    여기서 수렴 ∧ 포화 여유 ∧ α 여유 한 비트를 따로 냈고, 트림 탭은 조건 상태를 따로 냈다 — 같은 조건에 두 판정이
    섰다. ctx(VerdictContext)는 필수다: 문맥 없는 옛 정의로 되돌아가는 길을 두면 정의가 다시 둘이 된다.
    격자·보강·마진 맵(grid·refine·schedmap)은 이 함수가 아니라 condition_verdict를 직접 불러 판정 전체를 점에 싣는다
    (OperatingPoint.verdict) — 채택 비트는 늘 그 판정의 adopted다.
    """
    from claw.opspace.verdict import condition_verdict  # opspace.basegrid가 이 모듈을 import한다 — 순환을 늦춰 끊는다

    return bool(condition_verdict(tr, ctx)["adopted"])


_LEGACY_ONLY = frozenset({"throttle_high", "throttle_low", "de", "alpha_margin", "not_converged"})


def envelope_verdict(tr, ctx) -> dict:
    """채택 + 실패 사유 귀속 + 여유 수치 — {"ok", "reasons", "reserve", "verdict"} (설계 엔벨로프 스캔용).

    ok·verdict는 condition_verdict 그대로다 — 판정 정본(05 §11.3)을 재기술하지 않는다.
    reserve는 판정의 근거 수치다(TrimResult.reserve 요약 — δe 소모율·트림 추력 여유·실속 여유·α 판정 한계). 트림이
    여유를 계산하지 않았으면(지상 평형·옛 해) None.
    reasons는 해당되는 사유 전부 — 웹 스캔 라벨(web/js/lib/envelope.js)이 첫 항목을 대표로 쓰므로 옛 코드와 순서를
    먼저 둔다: not_converged → alpha_margin → saturated_throttle_high(**진짜 추진 한계** — 프로펠러 추력 곡선
    plant/prop.py PropEngine. 다만 판정선 trim_margin.sat_frac(기본 0.95) 등고선이라 한계보다 설계 여유만큼 안쪽이다) → saturated_de →
    saturated_throttle_low. 그 뒤에 판정의 모델·제한·여유 사유 중 옛 코드가 말하지 않은 것(db_mach·db_alpha·
    fuel_range·stall_boundary·limiter_clips_trim·q_max·mach_no·stall_basis_missing)을 판정 순서대로 중복 없이 붙인다.
    """
    from claw.opspace.verdict import alpha_margin_short, condition_verdict

    verdict = condition_verdict(tr, ctx)
    reasons = []
    if not tr.converged:
        reasons.append("not_converged")
    # 판정선은 문맥의 적용 기준(ctx.trim_bounds — criteria.trim_margin)으로 다시 잰다 — 트림 때 찍힌 플래그가 아니다
    a_short = alpha_margin_short(tr, ctx.trim_bounds)
    if a_short or (a_short is None and not tr.flags.get("alpha_margin_ok")):
        reasons.append("alpha_margin")
    sat = saturation_detail(tr, ctx.trim_bounds)
    if sat["throttle_high"]:
        reasons.append("saturated_throttle_high")
    if sat["de"]:
        reasons.append("saturated_de")
    if sat["throttle_low"]:
        reasons.append("saturated_throttle_low")
    for item in ("model", "limits", "margin"):
        for code in verdict[item]["reasons"]:
            if code not in _LEGACY_ONLY and code not in reasons:
                reasons.append(code)
    r = getattr(tr, "reserve", None) or {}
    reserve = None if not r else {
        "de_frac": r["de"]["frac"], "thr_reserve": r["thr"]["reserve_hi"],
        "alpha_stall_reserve": r["alpha"]["stall_reserve"], "alpha_limit": r["alpha"]["limit"],
    }
    return {"ok": verdict["adopted"], "reasons": reasons, "reserve": reserve, "verdict": verdict}


# 트림 전 제외 상태 — 기본 격자가 트림 전에 정한 모델 부족·요구영역 밖·요구 미정의(opspace/verdict.py PRE_TRIM_CATEGORY와
# 같은 셋. 순환 import를 피해 값으로 적는다 — test_design_points가 둘이 같은지 본다)
PRE_TRIM_STATES = frozenset({"model_gap", "out_of_region", "undefined"})


def pre_excluded(pt) -> bool:
    """트림 전에 제외된 점인가 — 판정의 트림 상태가 트림 전 제외 상태(pre_trim_verdict가 실은 것).

    이 점은 트림도 선형화도 하지 않는다(05 §11.13 2단계 — 버리지 않고 목록에 남기되 설계하지 않는다). 튜닝·검증점 생성·
    마진 맵은 `PointSet.designable()`로 이 점을 뺀 집합을 본다 — 빼지 않으면 마진 맵이 이 점을 트림하려 든다."""
    v = pt.verdict
    return v is not None and v["trim"]["status"] in PRE_TRIM_STATES


def case_name(mach: float, alt: float, fuel: float) -> str:
    """격자 값 그대로의 정본 이름 — 반올림하지 않는다 (web grid.js nameCases 원칙).

    유효숫자 12자리 — 기본 `%g`(6자리)는 축 크기에 따라 refine의 중점 좌표
    반올림(소수점 6자리, refine._ROUND)보다 거칠어진다: 고도 1007.8125와
    1007.81255가 둘 다 'h1007.81'이 되어 **서로 다른 운영점이 같은 이름을 갖는다**.
    이름이 케이스 매핑 키라 겹치면 트림·마진이 조용히 다른 점에 귀속된다.
    """
    return f"M{mach:.12g}_h{alt:.12g}_f{fuel:.12g}"


@dataclass
class OperatingPoint:
    """운영점 하나 — TrimCase(기존 계약) + 역할 + 계보.

    trimmable: None=미판정, False=채택 안 함(트림 실패·모델 밖·제한 위반 — 여유 미달은 채택이다 — 엔벨로프 실경계의 데이터화 —
    버리지 않고 "여기는 안 된다"를 남긴다), True=채택. 판정에서 세울 때는 verdict["adopted"] 그대로다.
    verdict: 그 채택을 낸 조건 판정 전체(opspace/verdict.py condition_verdict) — 제외 범주·사유가 여기 있다.
    None이면 판정 없이 세운 trimmable(옛 결과·손으로 세운 점)이다.
    history: 승격 이력 [{"from","to","reason"}] — 감사 추적.
    """

    case: TrimCase
    role: str
    origin: str = ""  # 'coarse' | 'refine' | 'midpoint' | 'promoted:<사유>'
    history: list = field(default_factory=list)
    trimmable: bool | None = None
    verdict: dict | None = None

    def __post_init__(self):
        if self.role not in ROLE_RANK:
            raise ValueError(f"미정의 역할 {self.role!r} — 허용: {sorted(ROLE_RANK)}")

    @property
    def name(self) -> str:
        return self.case.name

    def coords(self) -> tuple:
        return (self.case.mach, self.case.alt, self.case.fuel)

    def to_dict(self) -> dict:
        return {
            "name": self.case.name,
            "mach": self.case.mach,
            "alt": self.case.alt,
            "fuel": self.case.fuel,
            "role": self.role,
            "origin": self.origin,
            "history": list(self.history),
            "trimmable": self.trimmable,
            "verdict": copy.deepcopy(self.verdict),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OperatingPoint":
        case = TrimCase(
            name=d["name"], mach=float(d["mach"]), alt=float(d["alt"]), fuel=float(d["fuel"])
        )
        return cls(
            case=case,
            role=d["role"],
            origin=d.get("origin", ""),
            history=list(d.get("history", ())),
            trimmable=d.get("trimmable"),
            verdict=copy.deepcopy(d.get("verdict")),  # 옛 결과에는 없다 — 미판정
        )


class PointSet:
    """이름 → OperatingPoint (삽입 순서 유지). 격자가 아니라 목록이다 —
    (alt, fuel) 행마다 mach 범위가 달라도 되고(coarse_grid), 중점 삽입(refine)으로
    비균일해져도 된다. 인접 관계는 좌표에서 그때그때 계산한다.
    """

    def __init__(self, points=()):
        self._points: dict[str, OperatingPoint] = {}
        for pt in points:
            self.add(pt)

    def __len__(self):
        return len(self._points)

    def __contains__(self, name):
        return name in self._points

    def __iter__(self):
        return iter(self._points.values())

    def get(self, name: str) -> OperatingPoint:
        return self._points[name]

    def names(self) -> tuple:
        return tuple(self._points)

    def add(self, pt: OperatingPoint) -> None:
        if not pt.case.name:
            raise ValueError("이름 없는 케이스 — case_name()으로 정본 이름을 먼저 부여")
        if pt.case.name in self._points:
            raise ValueError(f"케이스 이름 중복: {pt.case.name} — 같은 좌표가 두 번 들어왔다")
        self._points[pt.case.name] = pt

    def promote(self, name: str, new_role: str, reason: str) -> OperatingPoint:
        """역할 승격 — 단방향 래칫. 역행(강등)·제자리는 ValueError."""
        if new_role not in ROLE_RANK:
            raise ValueError(f"미정의 역할 {new_role!r} — 허용: {sorted(ROLE_RANK)}")
        pt = self._points[name]
        if ROLE_RANK[new_role] <= ROLE_RANK[pt.role]:
            raise ValueError(
                f"{name}: {pt.role} → {new_role} 승격 불가 — 역할은 단방향 래칫 "
                "(validation < breakpoint < anchor)"
            )
        pt.history.append({"from": pt.role, "to": new_role, "reason": reason})
        pt.role = new_role
        pt.origin = pt.origin or f"promoted:{reason}"
        return pt

    def designable(self) -> "PointSet":
        """트림 전 제외 점(pre_excluded)을 뺀 집합 — 같은 OperatingPoint 객체를 나눈다(판정·승격이 원본에 그대로 반영).

        튜닝·검증점 생성·마진 맵이 쓴다. 점을 **더하는** 쪽(보강·검증점 추가)은 원본 집합에 더한다 — 이 집합은 보기다."""
        return PointSet(p for p in self._points.values() if not pre_excluded(p))

    def by_role(self, role: str) -> list:
        """정확히 그 역할인 점들 (선언 순서)."""
        return [p for p in self._points.values() if p.role == role]

    def at_least(self, role: str) -> list:
        """그 역할 이상인 점들 — anchor는 breakpoint·validation의 역할도 겸한다
        (상위 역할이 하위 역할의 상위 집합이라는 서열 의미)."""
        rank = ROLE_RANK[role]
        return [p for p in self._points.values() if ROLE_RANK[p.role] >= rank]

    # ── 인접 관계 ────────────────────────────────────────────────────────

    def adjacent_pairs(self, role_at_least: str = ROLE_VALIDATION) -> list:
        """축정렬 최근접 쌍 목록 [(name_a, name_b, axis)] — a가 축값이 작은 쪽.

        한 축만 다르고 나머지 두 축이 같은 점들을 그 축으로 정렬해 이웃끼리 묶는다.
        refine(플랜트 거리)·schedmap(검증점 중점 생성)·classify(이웃 판정)가 공유하는
        인접 정의의 정본이다.
        """
        pts = self.at_least(role_at_least)
        pairs = []
        for axis_i, axis in enumerate(AXES):
            rows: dict[tuple, list] = {}
            for p in pts:
                c = p.coords()
                key = c[:axis_i] + c[axis_i + 1:]
                rows.setdefault(key, []).append(p)
            for row in rows.values():
                row.sort(key=lambda p: p.coords()[axis_i])
                for a, b in zip(row, row[1:]):
                    pairs.append((a.name, b.name, axis))
        return pairs

    def neighbors(self, name: str, role_at_least: str = ROLE_VALIDATION) -> list:
        """이 점과 축정렬 인접한 점 이름 목록."""
        out = []
        for a, b, _axis in self.adjacent_pairs(role_at_least):
            if a == name:
                out.append(b)
            elif b == name:
                out.append(a)
        return out

    def flanking(self, name: str, role_at_least: str) -> tuple | None:
        """이 점을 축상 양옆에서 끼는 role 이상 점 — (아래, 위, 축) 또는 None.

        classify(플랜트 거리·이웃 통과 판정)와 orchestrator(검증점 추가 좌표)가
        공유하는 인접 정의 — adjacent_pairs와 같은 축정렬 규약이다.
        """
        v = self.get(name)
        vc = v.coords()
        for axis_i, axis in enumerate(AXES):
            lo = hi = None
            for p in self.at_least(role_at_least):
                if p.name == name:
                    continue
                c = p.coords()
                if c[:axis_i] + c[axis_i + 1:] != vc[:axis_i] + vc[axis_i + 1:]:
                    continue
                if c[axis_i] < vc[axis_i] and (lo is None or c[axis_i] > lo.coords()[axis_i]):
                    lo = p
                if c[axis_i] > vc[axis_i] and (hi is None or c[axis_i] < hi.coords()[axis_i]):
                    hi = p
            if lo is not None and hi is not None:
                return lo.name, hi.name, axis
        return None

    # ── trim_batch 시드 순서 ─────────────────────────────────────────────

    def serpentine(self, role_at_least: str = ROLE_VALIDATION) -> list:
        """서펜타인 순서의 TrimCase 목록 — 리스트 인접 = 물리 인접 (인접 시드 전제).

        web grid.js serpentineCases와 같은 규칙: (fuel, alt) 행 순회, 행마다 mach
        방향을 교대로 뒤집는다. 행 구성이 비균일해도(행마다 mach 다름) 성립한다.
        """
        pts = self.at_least(role_at_least)
        rows: dict[tuple, list] = {}
        for p in pts:
            rows.setdefault((p.case.fuel, p.case.alt), []).append(p)
        cases = []
        for i, key in enumerate(sorted(rows)):
            row = sorted(rows[key], key=lambda p: p.case.mach, reverse=(i % 2 == 1))
            cases.extend(p.case for p in row)
        return cases

    # ── 직렬화 (세션 저장·재개 왕복) ─────────────────────────────────────

    def to_dict(self) -> dict:
        return {"points": [p.to_dict() for p in self._points.values()]}

    @classmethod
    def from_dict(cls, d: dict) -> "PointSet":
        return cls(OperatingPoint.from_dict(e) for e in d["points"])
