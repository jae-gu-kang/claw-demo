"""표별 절점 집합 — 게인 표의 분할점을 설계점에서 떼어 이름 붙은 객체로 둔다 (05 §11.5 · 이관 3단계).

종전에는 튜닝한 마하가 곧 표의 분할점이었다(fit 표 모드가 표본을 같은 마하끼리 평균해 그 자리에 놓았다). 그래서 설계점을
늘리면(REFINE 보강·검증점 승격) 절점도 늘었다 — 쇼케이스 표 자리마다 36점(coarse 7 + 보강 29). 설계점은 튜닝할 조건
목록이고 절점은 표의 형상이다(05 §11.4 「설계점은 절점과 독립이다」). 여기서는 절점을 집합으로 두고:

- **KnotSet** — 이름 · 축(첫 적용은 마하 1축) · 좌표 · 출처(source) · 이력. 출처는 초기 규칙(`base_axis` · `uniform:<n>` ·
  `user` · `samples`)이거나 분리(`split:<부모>`)다.
- **공유가 기본** — 표(게인 자리)는 모두 한 집합(`common`)을 참조한다(table_knots {자리: 집합 이름}). 절점 추가가 표 일부에만
  필요하면 그 표들을 떼어 자기 집합을 갖게 한다(add_knot — 공유/독립을 기록한다).
- **단조 성장** — 좌표는 더해지기만 한다(상한 max_per_table). 이터레이션 종료 보장의 한 겹이다: 같은 자리에 두 번 넣지
  않고(이미 있으면 skipped), 상한에 닿으면 더 넣지 않는다. 무효 처방은 오케스트레이터의 봉인이 막는다.

값은 여기서 정하지 않는다 — fit.table_on_knots가 설계점 표본 전부로 최소제곱(구간 선형 기저) 풀이를 한다. 표본이 없는 절점은
그 표에서 빠지고 보고된다(unsupported_knots).
"""

from dataclasses import dataclass, field

import numpy as np

from claw.design.points import ROLE_DESIGN, pre_excluded

KNOT_RULES = ("base_axis", "uniform", "user", "samples")
# 절점 설정 기본값 [기본값 — 사용자 결정 2026-09-30]: 요구영역 기본 격자의 공통 마하 좌표, 표당 상한 16.
# 16은 쇼케이스 기본 격자(8점)의 두 배 — 이분 두 번이면 닿는 수라 add_knot 순환이 예산보다 먼저 끝난다. 실측 근거는 없다
DEFAULT_KNOTS = {"rule": "base_axis", "n": None, "coords": None, "max_per_table": 16}
COMMON = "common"  # 기본 공유 집합의 이름
_ROUND = 6  # 균등 절점 좌표 반올림 — refine._ROUND와 같은 자릿수(이름·기록이 흔들리지 않게)
_EQ = 1e-9  # 같은 좌표로 보는 폭 — 마하 반올림 자릿수보다 충분히 작다


@dataclass
class KnotSet:
    name: str
    axis: str = "mach"
    coords: list = field(default_factory=list)
    source: str = ""
    history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "axis": self.axis, "coords": [float(c) for c in self.coords],
                "source": self.source, "history": [dict(h) for h in self.history]}

    @classmethod
    def from_dict(cls, d: dict) -> "KnotSet":
        return cls(name=d["name"], axis=d.get("axis", "mach"), coords=[float(c) for c in d["coords"]],
                   source=d.get("source", ""), history=[dict(h) for h in d.get("history", ())])


def check_knots_config(cfg: dict) -> dict:
    """절점 설정 검증 — 정규형 dict를 돌려준다(AutoDesignConfig가 부른다 — 서버 422도 이 ValueError다)."""
    unknown = sorted(set(cfg) - set(DEFAULT_KNOTS))
    if unknown:
        raise ValueError(f"knots: 미정의 키 {unknown} — 허용: {sorted(DEFAULT_KNOTS)}")
    out = {**DEFAULT_KNOTS, **cfg}
    if out["rule"] not in KNOT_RULES:
        raise ValueError(f"knots.rule은 {list(KNOT_RULES)} 중 하나: {out['rule']!r}")
    if out["n"] is not None:
        if isinstance(out["n"], bool) or int(out["n"]) != out["n"] or out["n"] < 2:
            raise ValueError(f"knots.n은 2 이상 정수 또는 없음: {out['n']!r}")
        out["n"] = int(out["n"])
    if out["coords"] is not None:
        cs = [float(c) for c in out["coords"]]
        if len(cs) < 2 or any(b <= a for a, b in zip(cs, cs[1:])) or not all(np.isfinite(cs)):
            raise ValueError(f"knots.coords는 2개 이상의 유한한 강한 증가 좌표: {out['coords']!r}")
        out["coords"] = cs
    if out["rule"] == "user" and out["coords"] is None:
        raise ValueError("knots.rule 'user'는 coords가 있어야 한다")
    m = out["max_per_table"]
    if isinstance(m, bool) or int(m) != m or m < 2:
        raise ValueError(f"knots.max_per_table은 2 이상 정수: {m!r}")
    out["max_per_table"] = int(m)
    if out["coords"] is not None and len(out["coords"]) > out["max_per_table"]:
        raise ValueError(f"knots.coords {len(out['coords'])}개가 표당 상한 max_per_table {out['max_per_table']}을 넘는다")
    return out


def _design_machs(points) -> list:
    """튜닝 표본이 나오는 점의 마하 — 채택한 설계점(트림 전 제외·채택 안 함 제외). 검증점은 표본이 없다."""
    return sorted({float(p.case.mach) for p in points.by_role(ROLE_DESIGN)
                   if p.trimmable is not False and not pre_excluded(p)})


def _uniform(machs, n) -> list:
    if not machs:
        return []
    lo, hi = machs[0], machs[-1]
    if hi <= lo:
        return [lo]
    return [round(float(m), _ROUND) for m in np.linspace(lo, hi, n)]


def initial_knot_sets(cfg_knots: dict, *, region_grid, points, slots) -> tuple:
    """첫 FIT의 절점 집합 — (knot_sets {이름: KnotSet}, table_knots {자리: 집합 이름}). 표는 전부 `common` 하나를 공유한다.

    규칙(cfg_knots["rule"]):
    - base_axis — 요구영역 기본 격자의 공통 마하 좌표(region_grid["axis"] — COARSE가 쓴 격자, 설정의 n_mach 덮음 포함).
      요구영역이 없으면(옛 coarse_grid 경로) 설계 마하 범위의 균등 절점 LEGACY_N_MACH개(`uniform:<n>`) — 옛 격자의 마하 수와 같다
    - uniform — 설계 마하 범위의 균등 절점 n개(없으면 LEGACY_N_MACH)
    - user — 준 좌표 그대로
    - samples — 채택한 설계점의 마하마다(옛 규칙 — 옛 세션 재개가 같은 표를 내게)
    """
    from claw.design.orchestrator import LEGACY_N_MACH  # 순환 import — 옛 격자 마하 수의 정본은 거기다

    cfg = check_knots_config(cfg_knots)
    rule = cfg["rule"]
    machs = _design_machs(points)
    if rule == "base_axis" and region_grid is not None and region_grid.get("axis"):
        coords, source = [float(m) for m in region_grid["axis"]], "base_axis"
    elif rule in ("base_axis", "uniform"):
        n = cfg["n"] if (rule == "uniform" and cfg["n"] is not None) else LEGACY_N_MACH
        coords, source = _uniform(machs, n), f"uniform:{n}"
    elif rule == "user":
        coords, source = list(cfg["coords"]), "user"
    else:
        coords, source = machs, "samples"
    sets = {COMMON: KnotSet(name=COMMON, axis="mach", coords=sorted(coords), source=source,
                            history=[{"op": "init", "rule": rule, "n": len(coords)}])}
    return sets, {s: COMMON for s in slots}


def union_knots(knot_sets: dict, table_knots: dict, slots=None) -> list:
    """평가 대상 표들의 절점 합집합(정렬) — 검증 마하 구간을 나누는 목록(05 §11.6 ①). slots None = 전 표."""
    names = {table_knots[s] for s in (table_knots if slots is None else slots) if s in table_knots}
    out: list = []
    for c in sorted(c for n in names for c in knot_sets[n].coords):
        if not out or c - out[-1] > _EQ:
            out.append(float(c))
    return out


def _users(table_knots, name) -> list:
    return sorted(s for s, n in table_knots.items() if n == name)


def add_knot(knot_sets: dict, table_knots: dict, slots, mach: float, *, reason: str, point, iter_n: int,
             max_per_table: int) -> dict:
    """이름 댄 표(slots)에 절점 하나 — {"added", "split": [떼어 낸 자리], "skipped": 사유|None}. 제자리 갱신.

    집합을 함께 쓰는 표 중 일부만 이름을 댔으면 그 표들을 떼어 새 집합(`split:<부모>` — 부모 좌표·이력 복사)으로 옮긴 뒤
    더한다 — 이름 안 댄 표의 형상을 바꾸지 않는다(05 §11.5 독립). 이름 댄 표가 그 집합의 사용자 전부면 제자리에 더한다.
    이미 있는 좌표나 상한에 닿은 집합에는 더하지 않는다(단조·유한 — 종료 보장). 아무 표에도 못 더했으면 skipped에 사유."""
    mach = float(mach)
    groups: dict = {}
    for s in sorted(set(slots)):
        if s in table_knots:
            groups.setdefault(table_knots[s], []).append(s)
    added, split, why = False, [], []
    for name, group in sorted(groups.items()):
        ks = knot_sets[name]
        if any(abs(c - mach) <= _EQ for c in ks.coords):
            why.append(f"{name}: 이미 M{mach:g} 절점이 있다")
            continue
        if len(ks.coords) >= max_per_table:
            why.append(f"{name}: 표당 절점 상한 {max_per_table}에 닿았다")
            continue
        if group != _users(table_knots, name):
            new_name = "+".join(group)
            ks = KnotSet(name=new_name, axis=ks.axis, coords=list(ks.coords), source=f"split:{name}",
                         history=[dict(h) for h in ks.history] + [{"op": "split", "from": name, "iter": iter_n}])
            knot_sets[new_name] = ks
            for s in group:
                table_knots[s] = new_name
            split.extend(group)
        ks.coords = sorted(ks.coords + [mach])
        ks.history.append({"op": "add", "mach": mach, "reason": reason, "point": point, "iter": iter_n})
        added = True
    for name in [n for n in knot_sets if not _users(table_knots, n)]:
        del knot_sets[name]  # 표가 모두 떠난 부모 — 좌표·이력은 떼어 낸 집합이 물려받았다
    if not groups:
        why.append("이름 댄 표가 절점 집합을 참조하지 않는다")
    return {"added": added, "split": sorted(split), "skipped": None if added else " · ".join(why)}


def knot_record(knot_sets: dict, table_knots: dict, fits: dict) -> dict:
    """결과·반출 기록(provenance.knots) — {"sets": {이름: {axis, coords, source, history}},
    "tables": {자리: {set, shared, unsupported, unsupported_detail, n}}}.

    tables에는 표로 선 자리만 싣는다(fits의 kind "table" — 상수로 접힌 자리는 표가 없다. fits가 비었으면 전 자리).
    shared는 그 집합을 참조하는 자리가 둘 이상인가(그 집합의 사용자 수 — 공통 집합인가와는 다르다: 떼어 낸 집합도 두 표가
    함께 쓰면 True다), unsupported는 표본이 받치지 않아 그 표에서 뺀 절점(fit.table_on_knots), unsupported_detail은 그
    사유(none 표본 없음 · far 가중 < 0.5)와 끝 바깥인가(edge), n은 그 표에 실제로 놓인 분할점 수다."""
    sets = {n: {k: v for k, v in ks.to_dict().items() if k != "name"} for n, ks in sorted(knot_sets.items())}
    tables = {}
    for slot, name in sorted(table_knots.items()):
        rep = (fits or {}).get(slot)
        if fits and (rep is None or rep.get("kind") != "table"):
            continue
        unsup = [float(c) for c in (rep or {}).get("unsupported_knots") or ()]
        tables[slot] = {"set": name, "shared": len(_users(table_knots, name)) > 1, "unsupported": unsup,
                        "unsupported_detail": _unsupported_detail(rep, unsup),
                        "n": None if rep is None else rep.get("n_breakpoints")}
    return {"sets": sets, "tables": tables}


def _unsupported_detail(rep, unsup) -> list:
    """뺀 절점마다 {knot, reason none|far|None, edge} — edge는 남은 분할점 범위 밖(끝값 clip 구간)인가, 아니면 안쪽에서
    뺀 절점(이웃 두 절점 사이 직선으로 메워진다)인가. 둘은 뜻이 달라 화면이 가른다(범위 밖 vs 표본 부족으로 뺌)."""
    bps = list((rep or {}).get("breakpoints") or ())
    why = {float(d["knot"]): d.get("reason") for d in (rep or {}).get("unsupported_detail") or ()}
    out = []
    for c in unsup:
        edge = None if not bps else bool(c < min(bps) - _EQ or c > max(bps) + _EQ)
        out.append({"knot": c, "reason": why.get(c), "edge": edge})
    return out
