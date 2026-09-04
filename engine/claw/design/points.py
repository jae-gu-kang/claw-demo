"""역할(role) 있는 운영점 집합 — 자동 설계 루프의 단일 정본 상태.

세 역할은 문서(01 §3.4·§4.1)의 세 개념을 타입으로 구분한 것이다:
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

from dataclasses import dataclass, field

from claw.common.contracts import TrimCase
from claw.trim import saturation_detail

ROLE_VALIDATION = "validation"
ROLE_BREAKPOINT = "breakpoint"
ROLE_ANCHOR = "anchor"
ROLE_RANK = {ROLE_VALIDATION: 0, ROLE_BREAKPOINT: 1, ROLE_ANCHOR: 2}

AXES = ("mach", "alt", "fuel")  # fcl/schedule.py SCHED_VARS와 같은 축 — 스케줄 변수가 곧 격자 축


def envelope_ok(tr) -> bool:
    """이 트림해가 **엔벨로프 안**인가 — 수렴 + 포화 여유 + α 여유.

    세 곳(grid·refine·schedmap)이 각자 판정하던 것을 한 자리로 모은다. schedmap만
    `converged`만 봤고, 그래서 **트림은 되지만 포화·α 여유가 미달인 중점 검증점**이
    엔벨로프 안으로 취급돼 판정·승격·튜닝까지 흘러갔다 — 같은 조건의 coarse 앵커는
    TUNE이 건너뛰고 실패 목록에서도 빠지는데, 두 경로가 갈렸다.
    """
    return bool(tr.converged
                and tr.flags.get("saturation_ok")
                and tr.flags.get("alpha_margin_ok"))


def envelope_verdict(tr) -> dict:
    """envelope_ok + 실패 사유 귀속 — {"ok", "reasons"} (설계 엔벨로프 스캔용).

    ok는 반드시 envelope_ok() 호출 — 판정 정본(01 §4.1)을 재기술하지 않는다.
    reasons는 해당되는 사유 전부, 우선순위 순(첫 항목이 표시 대표):
    not_converged → alpha_margin → saturated_throttle_high(**진짜 추진 한계** —
    프로펠러 추력 곡선 plant/prop.py PropEngine. 다만 SAT_FRAC 0.95 등고선이라
    한계보다 설계 여유만큼 안쪽이다) → saturated_de → saturated_throttle_low.
    """
    reasons = []
    if not tr.converged:
        reasons.append("not_converged")
    if not tr.flags.get("alpha_margin_ok"):
        reasons.append("alpha_margin")
    sat = saturation_detail(tr)
    if sat["throttle_high"]:
        reasons.append("saturated_throttle_high")
    if sat["de"]:
        reasons.append("saturated_de")
    if sat["throttle_low"]:
        reasons.append("saturated_throttle_low")
    return {"ok": envelope_ok(tr), "reasons": reasons}


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

    trimmable: None=미판정, False=트림 실패/포화(엔벨로프 실경계의 데이터화 —
    버리지 않고 "여기는 안 된다"를 남긴다), True=수렴·여유 확보.
    history: 승격 이력 [{"from","to","reason"}] — 감사 추적.
    """

    case: TrimCase
    role: str
    origin: str = ""  # 'coarse' | 'refine' | 'midpoint' | 'promoted:<사유>'
    history: list = field(default_factory=list)
    trimmable: bool | None = None

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
