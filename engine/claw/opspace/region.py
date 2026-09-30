"""요구 운용영역과 모델 유효영역 (05 §11.2).

요구 운용영역은 **성능을 확보해야 할 범위**다 — 기체 문서의 `operating_region` 절(사용자가 정한 값)이 정본이다.
그 절이 없으면 `mission_template.trim_grid`(계산할 점 목록)의 최솟값·최댓값으로 **초안**을 만들되 「미확정」으로
둔다. 모델 유효영역(공력 DB 마하 범위 · 연료 0~만재)은 따로 두고, 모델 범위에 맞춰 요구영역을 줄이지 않는다 —
넘치는 부분은 조건 상태 「모델 부족」으로 남는다(states.py).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np

_EPS = 1e-9


@dataclass(frozen=True)
class Region:
    """요구 운용영역 — 기본 범위 + 선택적 조건별 경계표.

    boundary: ((fuel_kg, ((alt, mach_lo, mach_hi), ...)), ...) — 연료 층마다 고도 행(정렬됨). 행 사이·층
    사이는 선형 보간. 표가 덮지 않는 (alt, fuel)은 **요구 미정의**다 — 가까운 행으로 늘리지 않는다.
    grid: 기본 격자 명세 {"n_mach", "alts", "fuels"} (05 §11.11).
    """

    mach: tuple
    alt: tuple
    fuel: tuple
    boundary: tuple | None
    grid: dict
    confirmed: bool
    source: str  # "profile" | "draft:trim_grid"

    def mach_bounds(self, alt: float, fuel: float):
        """행(alt, fuel)의 요구 마하 (lo, hi) — 경계표가 덮지 않으면 None(요구 미정의)."""
        if not self.boundary:
            return tuple(self.mach)
        layers = [f for f, _ in self.boundary]
        rows_of = dict(self.boundary)
        if not (layers[0] - _EPS <= fuel <= layers[-1] + _EPS):
            return None

        def layer_bounds(f):
            rows = rows_of[f]
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

    def classify(self, mach: float, alt: float, fuel: float) -> str | None:
        """"out_of_region" | "undefined" | None(요구영역 안)."""
        for v, (lo, hi) in ((mach, self.mach), (alt, self.alt), (fuel, self.fuel)):
            if v < lo - _EPS or v > hi + _EPS:
                return "out_of_region"
        b = self.mach_bounds(alt, fuel)
        if b is None:
            return "undefined"
        if mach < b[0] - _EPS or mach > b[1] + _EPS:
            return "out_of_region"
        return None

    def to_dict(self) -> dict:
        return {
            "mach": list(self.mach), "alt": list(self.alt), "fuel": list(self.fuel),
            "boundary": None if self.boundary is None else [
                {"fuel": f, "rows": [list(r) for r in rows]} for f, rows in self.boundary],
            "grid": {"n_mach": self.grid["n_mach"], "alts": list(self.grid["alts"]),
                     "fuels": list(self.grid["fuels"])},
            "confirmed": self.confirmed, "source": self.source,
        }


def _from_section(r: dict) -> Region:
    """검증된 operating_region 절(schema.py) → Region. 경계표는 연료 층·고도 행 오름차순으로 정렬한다."""
    b = r["boundary"]
    boundary = None if b is None else tuple(
        (float(layer["fuel"]), tuple(sorted(tuple(float(x) for x in row) for row in layer["rows"])))
        for layer in sorted(b, key=lambda layer: layer["fuel"]))
    g = r["base_grid"]
    return Region(mach=tuple(r["mach"]), alt=tuple(r["alt"]), fuel=tuple(r["fuel"]), boundary=boundary,
                  grid={"n_mach": int(g["n_mach"]), "alts": tuple(g["alts"]), "fuels": tuple(g["fuels"])},
                  confirmed=True, source="profile")


def _draft_from_trim_grid(g: dict) -> Region:
    """trim_grid(계산할 점 목록)에서 요구영역 **초안** — 미확정이다. 판정에 쓰는 결과는 그 사실을 싣는다.
    기본 격자 명세는 그 격자의 모양을 따른다(마하 점 수 · 고도 목록 · 연료 목록)."""
    m = g["mach"]
    n_mach = int(np.floor((m["to"] - m["from"]) / m["step"] + 1e-9)) + 1
    return Region(mach=(float(m["from"]), float(m["to"])),
                  alt=(float(min(g["alt"])), float(max(g["alt"]))),
                  fuel=(float(min(g["fuel"])), float(max(g["fuel"]))), boundary=None,
                  grid={"n_mach": max(n_mach, 2), "alts": tuple(g["alt"]), "fuels": tuple(g["fuel"])},
                  confirmed=False, source="draft:trim_grid")


def region_from_section(section: dict) -> Region:
    """operating_region 절(검증 전이어도 된다) → 확정 Region. 문서 검증과 같은 규칙으로 먼저 잰다(ProfileError — 경로
    /operating_region/…). 절 지우기(None)는 문서가 있어야 초안을 만드니 region_of로 간다."""
    from claw.profile.schema import validate_operating_region  # 지연 import — claw.profile이 opspace를 먼저 부른다

    if section is None:
        raise ValueError("절이 없으면(None) region_of(문서)로 초안을 만든다")
    return _from_section(validate_operating_region(section))


def region_of(doc: dict) -> Region | None:
    """적용 문서(검증·정규화된 기체 문서) → 요구 운용영역. operating_region 절이 정본, 없으면 trim_grid 초안,
    둘 다 없으면 None(요구영역을 정하지 않은 기체 — 호출자가 그렇다고 말한다)."""
    if doc.get("operating_region") is not None:
        return _from_section(doc["operating_region"])
    tpl = doc.get("mission_template")
    if tpl is not None:
        return _draft_from_trim_grid(tpl["trim_grid"])
    return None


def region_echo(region) -> dict | None:
    """요구영역의 정규 기록 — δe_trim 도출 출처(provenance.region)와 region_key가 같은 모양을 쓴다. 저장 표의 근거가
    지금 요구영역에서 잰 것인지를 이것 전체로 가른다(derive.de_trim_coverage) — 마하 구간만 같고 고도·연료·경계표·
    격자가 바뀐 영역을 같은 요구로 보지 않게."""
    if region is None:
        return None
    boundary = None if region.boundary is None else [
        [float(f), [[float(a), float(lo), float(hi)] for a, lo, hi in rows]] for f, rows in region.boundary]
    return {"source": region.source, "confirmed": bool(region.confirmed),
            "mach": [float(m) for m in region.mach], "alt": [float(a) for a in region.alt],
            "fuel": [float(f) for f in region.fuel], "boundary": boundary,
            "grid": {"n_mach": int(region.grid["n_mach"]), "alts": [float(a) for a in region.grid["alts"]],
                     "fuels": [float(f) for f in region.grid["fuels"]]}}


def region_key(region) -> str | None:
    """요구영역의 판 — 정규 기록(region_echo)의 sha256 앞 12자. 계보 패널이 기본 격자 판으로 싣고, 리비전 이력이 같은
    판을 한 줄로 접는다. 확정 여부·출처도 기록에 들어 있어 같은 값의 초안과 확정은 다른 판이다(판정에 쓰는지가 다르다)."""
    echo = region_echo(region)
    if echo is None:
        return None
    blob = json.dumps(echo, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


REGION_IN = "in"


def region_outline(region, fuel: float) -> list:
    """연료 fuel에서 요구영역의 고도 행별 마하 경계 — [{alt, mach_lo, mach_hi, state}] 고도 오름차순.

    고도는 경계표 고도(모든 층 — 층 사이 보간의 꺾임이 다른 층 고도에서 생긴다) ∪ 기본 격자 고도 ∪ 기본 범위 끝.
    값은 mach_bounds·classify 그대로라 편집 화면이 보간을 다시 하지 않는다(웹은 보간하지 않는다). state는 "in" ·
    "undefined"(경계표가 안 덮음) · "out_of_region"(기본 범위 밖 연료) — 안이 아니면 마하는 None(없는 띠를 그리지 않는다)."""
    alts = {float(a) for a in region.alt} | {float(a) for a in region.grid["alts"]}
    for _f, rows in region.boundary or ():
        alts |= {float(r[0]) for r in rows}
    out = []
    for alt in sorted(alts):
        # 기본 범위부터 — 범위 밖 연료가 「층 밖이라 미정의」로 둔갑하지 않게(classify와 같은 순서)
        if not (region.fuel[0] - _EPS <= fuel <= region.fuel[1] + _EPS
                and region.alt[0] - _EPS <= alt <= region.alt[1] + _EPS):
            b, state = None, "out_of_region"
        else:
            b = region.mach_bounds(alt, fuel)
            state = "undefined" if b is None else (region.classify(b[0], alt, fuel) or REGION_IN)
        lo, hi = (b if state == REGION_IN else (None, None))
        out.append({"alt": alt, "mach_lo": None if lo is None else float(lo),
                    "mach_hi": None if hi is None else float(hi), "state": state})
    return out


def grid_diff(before_pts, after_pts) -> dict:
    """두 점 집합의 차이 — 이름(값 그대로의 케이스 이름)으로 짝짓는다. 요구영역을 바꾸면 기본 격자가 몇 점 유지되고
    몇 점 새로 생기고 몇 점 빠지나(편집 화면의 「바꾸면 영향」). 개수만 — 어느 점인지는 두 격자가 이미 싣는다."""
    b = {p["name"] for p in before_pts or ()}
    a = {p["name"] for p in after_pts or ()}
    return {"before": len(b), "after": len(a), "kept": len(a & b), "added": len(a - b), "dropped": len(b - a)}


@dataclass(frozen=True)
class ModelRange:
    """모델 유효영역 — 공력 DB 마하 범위와 질량 모델 연료 범위. mach가 None이면 DB 범위 미기재(판단하지 않음)."""

    mach: tuple | None
    fuel: tuple

    def covers(self, mach: float, fuel: float) -> bool:
        if self.mach is not None and not (self.mach[0] - _EPS <= mach <= self.mach[1] + _EPS):
            return False
        return self.fuel[0] - _EPS <= fuel <= self.fuel[1] + _EPS

    def to_dict(self) -> dict:
        return {"mach": None if self.mach is None else list(self.mach), "fuel": list(self.fuel)}


def model_range_of(built) -> ModelRange:
    """BuiltProfile → 모델 유효영역."""
    m = built.db_ranges().get("mach")
    return ModelRange(mach=None if m is None else (float(m[0]), float(m[1])),
                      fuel=(0.0, float(built.doc["mass"]["fuel_max"])))
