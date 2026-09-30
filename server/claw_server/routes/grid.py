"""공통 운용공간 라우트 (05 §11) — 요구 운용영역 → 기본 모델 격자.

탭이 격자를 따로 만들지 않고 여기서 받는다(05 §11.12 「정의는 한 곳」). 점을 어디에 둘지와 트림 전 상태(미계산 ·
모델 부족)는 엔진 claw.opspace가 정하고, 서버는 기체 해석·요청 검증·직렬화만 한다. 동기 응답이다 — 트림을
풀지 않고 좌표만 만든다(상한 claw.opspace.basegrid.MAX_BASE_POINTS).
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from claw.common.contracts import TrimCase
from claw.opspace import STATE_LABEL, STATE_ORDER, base_grid, model_range_of, region_of
from claw.opspace.states import COMPUTABLE, NOT_RUN
from claw_server.refs import ProfileRef, profile_echo, resolve_profile, trim_scope

router = APIRouter(tags=["grid"])

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]

NO_REGION = ("이 기체 문서에는 요구 운용영역(operating_region)도 미션 템플릿 격자(trim_grid)도 없어 기본 격자를 만들 수 "
             "없습니다 — 기체 문서에 요구 운용영역을 적습니다.")


class BaseGridIn(BaseModel):
    """기본 격자 명세 — 안 준 칸은 요구 운용영역의 기본 격자 명세(base_grid)를 쓴다."""

    profile: ProfileRef | None = None
    n_mach: int | None = Field(default=None, ge=2, le=50)
    alts: list[FiniteFloat] | None = Field(default=None, min_length=1, max_length=20)
    fuels: list[FiniteFloat] | None = Field(default=None, min_length=1, max_length=20)


def region_context(built) -> dict:
    """결과·응답에 싣는 요구영역 블록 — 초안(미확정)이면 그 사실이 결과에 남는다(05 §11.2)."""
    region = region_of(built.doc)
    return {"region": None if region is None else region.to_dict(), "model": model_range_of(built).to_dict()}


@router.post("/grid/base")
def post_base_grid(req: BaseGridIn, request: Request) -> dict:
    built = resolve_profile(request, req.profile)
    region = region_of(built.doc)
    ctx = region_context(built)
    echo = profile_echo(built)
    if region is None:
        return {**ctx, "reason": NO_REGION, "axis": [], "rows": [], "points": [], "counts": {},
                "labels": STATE_LABEL, "profile": echo}
    try:
        out = base_grid(region, model_range_of(built), n_mach=req.n_mach, alts=req.alts, fuels=req.fuels)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    counts = {s: 0 for s in STATE_ORDER}
    for p in out["points"]:
        counts[p["state"]] += 1
    _mark_stored(request, built, out["points"])
    return {**ctx, "reason": None, **out, "counts": {s: n for s, n in counts.items() if n},
            "labels": STATE_LABEL, "profile": echo}


def _mark_stored(request, built, points) -> None:
    """트림 저장소에 기록이 있는 점에 stored {state, converged}를 단다(05 §11.8) — 점의 state(트림 전 상태)는 그대로
    둔다: 보낼 점(미계산)의 판정이 저장소 유무로 바뀌면 탭마다 보내는 집합이 달라진다. 기록이 없는 점엔 키가 없다.

    동기 응답이라 판정을 새로 재지 않는다. 수렴 기록의 state는 "computable"이다 — 트림 탭의 trim_assessment도
    수렴 해엔 조립·여유 판정만 하고 이 상태를 낸다(여유 met/short는 판정선 축이라 여기서 싣지 않는다). 미수렴 기록은
    state None(판정 안 함)이다: 계산 실패·제약 도달·물리적 불가를 가르려면 한계 근거 풀이(SLSQP)가 필요한데, 격자를
    받을 때마다 그걸 돌리지 않는다. 기본 재사용 정책("converged")이 이 점을 다음 실행에서 다시 푼다."""
    scope = trim_scope(request, built)
    if scope is None:
        return
    for p in points:
        rec = scope.peek(TrimCase(p["name"], mach=p["mach"], alt=p["alt"], fuel=p["fuel"]))
        if rec is not None:
            p["stored"] = {"state": COMPUTABLE if rec.converged else None, "converged": bool(rec.converged)}


# ── 요구영역 편집 미리 보기 (05 §11.13 6단계 · 06 §10 ①) ───────────────────────────────────────
#
# 저장하지 않고 「이 절로 바꾸면 무엇이 달라지나」를 답한다 — 편집 화면이 입력마다(디바운스) 부른다. 동기이고 싸다: 트림을
# 풀지 않고, 재사용·새 트림 수는 트림 저장소 엿보기(peek)로만 센다. 검증은 엔진 validate_operating_region 한 곳이다 —
# 저장(PUT …/operating-region)이 같은 규칙을 문서 전체 검증으로 다시 거치므로 미리 보기만 통과하는 절이 없다.

NO_REGION_PREVIEW = ("이 기체 문서에는 미션 템플릿 격자(trim_grid)가 없어, 요구영역을 지우면 초안도 없습니다 — 요구 운용영역을 "
                     "적습니다.")

# 소비자 상태 — 요구영역이 바뀌면 무엇이 낡나(06 §10 계보 패널 · 05 §11.12 의존)
CONSUMER_LABEL = {
    ("de_trim", "current"): "δe_trim 표 — 이 요구영역에서 도출됨",
    ("de_trim", "stale"): "δe_trim 표 — 다른 요구영역에서 도출됨 · 다시 도출 필요",
    ("de_trim", "no_record"): "δe_trim 표 — 요구영역 기록 없음(손으로 넣었거나 옛 도출)",
    ("de_trim", "absent"): "δe_trim 표 없음",
    ("gain_tables", "no_record"): "확정 게인 표 — 요구영역 기록 없음",
    ("gain_tables", "absent"): "확정 게인 표 없음",
    ("trim_store", "reused"): "트림 저장소 — 재사용 · 요구영역과 무관(플랜트 키)",
}


class RegionPreviewIn(BaseModel):
    """region은 operating_region 절 그대로(null = 지우기 → trim_grid 초안). 키를 빠뜨리면 422 — 「지우기」로 읽지 않는다."""

    profile: ProfileRef | None = None
    region: dict | None
    fuel: FiniteFloat | None = None


def region_consumers(doc: dict, region) -> list:
    """[{what, status, label}] — 이 요구영역을 쓰면 각 소비자가 현재인가.

    δe_trim만 요구영역 기록(provenance.region)이 있다 — 도출 기록 전체가 이 요구영역과 같을 때만 current(derive
    de_trim_coverage와 같은 대조). 게인 표 출처에는 요구영역 기록이 없어 모른다고 말한다. 트림 저장소는 플랜트 키라
    요구영역이 바뀌어도 해를 그대로 재사용한다."""
    from claw.opspace import region_echo

    alloc = doc["law"].get("alloc")
    de = None if alloc is None else alloc.get("de_trim")
    if de is None:
        de_status = "absent"
    else:
        prov = de.get("provenance") if isinstance(de.get("provenance"), dict) else {}
        if de.get("source") != "derived" or "region" not in prov:
            de_status = "no_record"
        else:
            de_status = "current" if prov["region"] == region_echo(region) else "stale"
    gain_status = "absent" if doc["law"].get("gain_tables") is None else "no_record"
    rows = [("de_trim", de_status), ("gain_tables", gain_status), ("trim_store", "reused")]
    return [{"what": w, "status": s, "label": CONSUMER_LABEL[(w, s)]} for w, s in rows]


def _grid_block(out: dict | None) -> dict:
    points = [] if out is None else out["points"]
    counts = {s: 0 for s in STATE_ORDER}
    for p in points:
        counts[p["state"]] += 1
    return {"points": points, "rows": [] if out is None else out["rows"], "axis": [] if out is None else out["axis"],
            "counts": {s: n for s, n in counts.items() if n}, "labels": STATE_LABEL}


@router.post("/grid/region/preview")
def post_region_preview(req: RegionPreviewIn, request: Request) -> dict:
    """요구영역 편집 미리 보기 — {region, model, outline, outlines, fuel, grid, impact, region_key, profile, reason}. 저장하지
    않는다. outline은 보이는 연료(fuel)의 윤곽, outlines는 경계표 층 연료마다의 윤곽({"200.0": [...]} — 키는 연료 수의
    글, 웹은 수로 짝짓는다).

    impact.grid는 지금 저장된 요구영역의 기본 격자 대비(이름으로 짝짓기), reused는 새 격자에서 트림 저장소에 수렴 기록이
    있는 점, new_trims는 보낼 점(미계산) 중 수렴 기록이 없는 점, stale은 소비자 상태(region_consumers). 절 오류는 422
    {path, message} — 경로가 문서 경로(/operating_region/…)라 편집 표가 칸을 짚는다."""
    from claw.opspace import grid_diff, region_key, region_outline
    from claw.profile import ProfileError
    from claw.profile.schema import validate_operating_region
    from claw_server.refs import profile_error_detail

    built = resolve_profile(request, req.profile)
    try:
        section = validate_operating_region(req.region)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    region = region_of({**built.doc, "operating_region": section})
    model = model_range_of(built)
    current = region_of(built.doc)
    if region is None:
        return {"region": None, "model": model.to_dict(), "outline": [], "outlines": {}, "fuel": req.fuel,
                "grid": _grid_block(None),
                "impact": {"grid": grid_diff(_safe_grid(current, model), []), "reused": 0, "new_trims": 0,
                           "stale": region_consumers(built.doc, None)},
                "region_key": None, "reason": NO_REGION_PREVIEW, "profile": profile_echo(built)}
    fuel = float(region.fuel[0]) if req.fuel is None else float(req.fuel)
    try:
        out = base_grid(region, model)
    except ValueError as e:  # 검증을 넘은 절은 상한(200점) 안이지만, 엔진 상한이 바뀌어도 500이 아니게
        raise HTTPException(status_code=422, detail={"path": "/operating_region/base_grid", "message": str(e)})
    _mark_stored(request, built, out["points"])
    reused = sum(1 for p in out["points"] if p.get("stored", {}).get("converged"))
    new_trims = sum(1 for p in out["points"]
                    if p["state"] == NOT_RUN and not p.get("stored", {}).get("converged"))
    # 층마다 윤곽 — 「전체 연료」가 행 없는 층에 행을 넣을 때 그 층 값을 엔진에서 받는다(웹이 복사로 지어내지 않게)
    outlines = {str(float(f)): region_outline(region, float(f)) for f, _rows in region.boundary or ()}
    return {"region": region.to_dict(), "model": model.to_dict(), "outline": region_outline(region, fuel),
            "outlines": outlines, "fuel": fuel, "grid": _grid_block(out),
            "impact": {"grid": grid_diff(_safe_grid(current, model), out["points"]), "reused": reused,
                       "new_trims": new_trims, "stale": region_consumers(built.doc, region)},
            "region_key": region_key(region), "reason": None, "profile": profile_echo(built)}


def _safe_grid(region, model) -> list:
    """지금 요구영역의 기본 격자 점 — 없거나 만들 수 없으면 빈 목록(비교 기준이 없다)."""
    if region is None:
        return []
    try:
        return base_grid(region, model)["points"]
    except ValueError:
        return []
