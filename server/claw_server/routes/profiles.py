"""기체 프로파일 라우트 (02 §5.6) — 목록·조회·생성·갱신·삭제·검증·CSV 표 판독·쇼케이스 기체 설치.

기체 문서는 웹에서만 만들고 고친다. 내보내기는 조회(GET)의 `document`, 가져오기는 생성(POST)이다 —
같은 검증을 두 번 적지 않는다. 검증 오류는 422이고 detail이 문서 안 경로를 싣는다(웹 편집기가 칸을
짚는다). 갱신은 base_revision이 최신과 같을 때만 받고, 다르면 409와 최신 리비전을 준다.
"""

import copy
import weakref
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from claw.design.basis import E_REF_DPS, apply_seed_basis, seed_basis
from claw.design.seed import quick_seed
from claw.profile import ProfileError, build_profile, validate_document
from claw.profile.derive import CHECK_STEP, derive_de_trim
from claw.profile.aeroview import MAX_POINTS, aero_slice, stability_slice
from claw.profile.form import form_spec
from claw.profile.schema import document_warnings
from claw.tables import TableError
from claw.tables.loader import parse_table_csv
from claw_server.profiles import EXAMPLE_ID, ProfileConflict, ProfileReadOnly, ProfileUnreadable, upgraded
from claw_server.refs import profile_echo, profile_error_detail
from claw_server.serialize import table_dict, to_jsonable

router = APIRouter(tags=["profiles"])

MAX_CSV_CHARS = 5_000_000  # 공력 표 한 장 — 오타 붙여넣기가 단일 워커를 물지 않게


class ProfileDocIn(BaseModel):
    document: dict


class ProfileUpdateIn(BaseModel):
    base_revision: int = Field(ge=1)
    document: dict


class AeroSliceIn(BaseModel):
    document: dict
    variant: str | None = Field(default=None, min_length=1, max_length=64)
    along: str = Field(min_length=1, max_length=16)
    start: float = Field(allow_inf_nan=False)
    stop: float = Field(allow_inf_nan=False)
    n: int = Field(default=121, ge=2, le=MAX_POINTS)
    fixed: dict[str, float] = Field(default_factory=dict)


class AeroStabilityIn(BaseModel):
    """정적 안정성 도함수 — aero-slice와 같은 문서 계약, 축은 α 고정이라 along이 없다."""

    document: dict
    variant: str | None = Field(default=None, min_length=1, max_length=64)
    start: float = Field(allow_inf_nan=False)
    stop: float = Field(allow_inf_nan=False)
    n: int = Field(default=61, ge=2, le=MAX_POINTS)
    fixed: dict[str, float] = Field(default_factory=dict)


class SeedBasisIn(BaseModel):
    """초기 게인 산출 근거 — aero-slice와 같은 문서 계약(저장 없음·예제 가능), 트림점·대표 오차는 조회 조건."""

    document: dict
    variant: str | None = Field(default=None, min_length=1, max_length=64)
    mach: float = Field(gt=0.0, allow_inf_nan=False)
    alt: float = Field(allow_inf_nan=False)
    fuel: float = Field(ge=0.0, allow_inf_nan=False)
    e_ref_dps: float = Field(default=E_REF_DPS, gt=0.0, le=360.0, allow_inf_nan=False)


class QuickSeedIn(BaseModel):
    base_revision: int = Field(ge=1)
    sim_check: bool = False


class ApplySeedBasisIn(BaseModel):
    """산출 근거 직행 저장 — 트림점은 산출 근거 조회와 같은 계약, 저장 가드는 quick-seed와 같은 계약."""

    base_revision: int = Field(ge=1)
    mach: float = Field(gt=0.0, allow_inf_nan=False)
    alt: float = Field(allow_inf_nan=False)
    fuel: float = Field(ge=0.0, allow_inf_nan=False)
    e_ref_dps: float = Field(default=E_REF_DPS, gt=0.0, le=360.0, allow_inf_nan=False)


class DeriveDeTrimIn(BaseModel):
    base_revision: int = Field(ge=1)
    # 검사 간격 하한 = 기본값 — 더 촘촘하면 트림 수가 격자 × 연료 × 고도로 불어 단일 워커를 문다
    check_step: float = Field(default=CHECK_STEP, ge=CHECK_STEP, le=0.1, allow_inf_nan=False)


class ParseTableIn(BaseModel):
    csv_text: str = Field(min_length=1, max_length=MAX_CSV_CHARS)
    axis_cols: list[str] = Field(min_length=1, max_length=8)
    value_col: str = Field(min_length=1)
    extrapolate: Literal["clip", "linear", "error"] = "clip"


def _fingerprints(doc: dict) -> dict:
    base = build_profile(doc, validated=True)
    return {
        "fingerprint": base.fingerprint,
        "plant_fingerprint": base.plant_fingerprint,
        "variants": {v["id"]: build_profile(doc, v["id"], validated=True).fingerprint
                     for v in doc["variants"]},
    }


def _body(doc: dict, revision: int, notes: list | None = None) -> dict:
    """upgrade_notes — 옛 스키마 문서를 올린 사유(엔진 upgrade_document, 05 §11.13 이관 11단계). 비어 있으면 올림 없음.
    조회에서 비어 있지 않으면 **저장본은 아직 옛 버전**이고, 저장해야 올린 문서가 새 리비전이 된다(profiles.py 머리말)."""
    return {"document": doc, "revision": revision, "is_example": doc["is_example"], **_fingerprints(doc),
            "warnings": document_warnings(doc), "upgrade_notes": list(notes or [])}


@router.get("/profiles")
def list_profiles(request: Request) -> list:
    return request.app.state.profiles.list()


@router.get("/profiles/_form")
def profile_form() -> dict:
    """편집 폼 서술 — 칸 이름·단위·형식·선택지. 정본은 엔진 `claw.profile.form`(검증기 옆)이다.

    기체 id는 `_`로 시작할 수 없으므로(저장소 규칙) 이 경로는 기체 조회와 겹치지 않는다 — 이 선언이
    `/profiles/{profile_id}`보다 앞에 있어야 한다."""
    return form_spec()


def _showcase_document() -> dict:
    """쇼케이스 기체 문서(엔진 패키지 데이터, 검증된 사본) — 라우트가 부르는 한 자리.

    엔진 로더를 부를 때 import한다(모듈 import 시점이 아니라) — 테스트가 이 함수를 합성 문서로 갈아끼운다."""
    from claw.profile.document import load_showcase

    return load_showcase()


def _showcase_checked(request) -> dict:
    """저장 규칙까지 넘긴 쇼케이스 문서 — 조회와 설치가 같은 문서를 말하게(조회는 되는데 설치가 422인 일이 없게)."""
    try:
        return request.app.state.profiles.checked(_showcase_document())
    except ProfileError as e:  # 패키지 문서가 저장 규칙을 못 넘는다 — 요청이 아니라 배포 결함이라 500
        raise HTTPException(status_code=500, detail=profile_error_detail(e))
    except (ImportError, OSError, ValueError) as e:
        # 패키지 파일 없음·손상 JSON·로더 없는 엔진 — 역시 배포 결함. 맨 500이면 진행기가 사유 없이 멈춘다
        raise HTTPException(status_code=500, detail={
            "path": "", "message": f"쇼케이스 기체 문서를 읽을 수 없다 — {type(e).__name__}: {e}"})


@router.get("/profiles/_showcase")
def showcase_document(request: Request) -> dict:
    """쇼케이스 기체 문서 — 설치하지 않고 본다. `_`로 시작하는 경로라 기체 조회와 겹치지 않는다(_form과 같은 자리)."""
    doc = _showcase_checked(request)
    return {"document": doc, "fingerprint": build_profile(doc, validated=True).fingerprint}


@router.post("/profiles/_showcase/install")
def install_showcase(request: Request) -> dict:
    """쇼케이스 기체를 편집 가능한 저장 기체로 설치·초기화 — 없으면 생성, 최신이 패키지 문서와 다르면 그 문서를
    새 리비전으로(이력은 남는다), 같으면 그대로. 몇 번을 불러도 결과가 같다(쇼케이스 진행기의 준비 단계).

    휘발 저장소(재시작·슬립 복귀마다 비워짐)에서는 다시 불러 되살린다 — `volatile`로 그 사실을 함께 준다."""
    doc, rev, action = request.app.state.profiles.install(_showcase_checked(request))
    return {"id": doc["id"], "revision": rev, "action": action,
            "fingerprint": build_profile(doc, validated=True).fingerprint,
            "volatile": bool(getattr(request.app.state, "profile_volatile", False))}


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, request: Request, revision: int | None = None) -> dict:
    store = request.app.state.profiles
    notes = []
    try:
        doc, rev = store.get(profile_id, revision, notes_out=notes)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # 저장 파일의 버전 — 올린 문서를 보여도 디스크는 옛 버전 그대로다(저장해야 바뀐다)
    return {**_body(doc, rev, notes),
            "stored_schema_version": store.stored_schema_version(profile_id, rev) if notes else doc["schema_version"]}


NO_DE_TRIM_TABLE = "이 기체 문서에는 할당 δe_trim 표가 없어 요구 마하를 덮는지 잴 것이 없습니다."


@router.get("/profiles/{profile_id}/de-trim-coverage")
def get_de_trim_coverage(profile_id: str, request: Request, revision: int | None = None) -> dict:
    """할당 δe_trim 표가 요구 마하를 덮는가 (05 §11.13 이관 10단계) — 엔진 `de_trim_coverage`가 정본이다.

    표의 축이 요구를 덮는 것과 그 구간의 도출 근거가 있는 것은 다르다: 표 밖은 끝값(clip)으로 답하고(beyond_table),
    트림 실패·모델 부족으로 근거가 없는 구간(unsupported)과 보간으로 채운 마하(undefined_machs)도 따로 낸다. 조회
    응답(GET /profiles/{id})에 섞지 않는다 — 문서 조회마다 도출 근거를 재지 않게, 기체 탭 δe_trim 패널이 따로 부른다."""
    from claw.profile.derive import de_trim_coverage

    try:
        doc, rev = request.app.state.profiles.get(profile_id, revision)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    alloc = doc["law"].get("alloc")
    if alloc is None or alloc.get("de_trim") is None:
        return {"id": doc["id"], "revision": rev, "coverage": None, "reason": NO_DE_TRIM_TABLE}
    built = build_profile(doc, validated=True)
    return to_jsonable({"id": doc["id"], "revision": rev, "coverage": de_trim_coverage(built), "reason": None})


@router.get("/profiles/{profile_id}/criteria")
def get_profile_criteria(profile_id: str, request: Request, revision: int | None = None) -> dict:
    """이 작업 단위의 평가 기준 — 모든 탭이 판정에 쓰는 한 벌(기준 통합 ①).

    `applied`는 도구 기본값을 펼친 적용값, `written`은 문서가 실제로 적은 칸(없음 = 기본값을 따른다), `defaults`는
    도구 기본값이다 — 편집 화면이 「기본값을 따르는 칸」과 「이 기체가 바꾼 칸」을 가를 수 있게. `lines`는 판정선의
    뜻(방향·합격선·권장선·목표 필드 — design.criteria.LINES)이라 화면이 방향을 다시 적지 않는다. `echo`는 결과에
    실리는 기준 블록과 같은 모양이다 — 화면은 결과의 echo를 이것과 대조해 「재평가 필요」를 가린다.
    `groups`는 판정선 표 밖 그룹의 칸 이름표(트림 여유 판정선 — 이관 12단계)다.
    `metric_scales`는 이 기체 **적용 기준**의 합격선에서 파생한 지표별 자(GainEvalCriteria.to_metric_scales)다 —
    영향성 그래프가 「유의미하게 움직이나」를 가르는 분석용이라 판정에는 영향이 없다(04 §1). 도구 기본값
    경로(/influence/criteria/defaults)의 자를 쓰면 기체가 한계를 바꿔도 그래프는 옛 한계로 켜진다."""
    from dataclasses import asdict

    from claw.design.criteria import LINES, STATUSES
    from claw.pipeline.criteria import GainEvalCriteria
    from claw_server.refs import criteria_echo

    try:
        doc, rev = request.app.state.profiles.get(profile_id, revision)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    built = build_profile(doc, validated=True)
    crit = built.eval_criteria
    return to_jsonable({
        "id": doc["id"], "revision": rev,
        "applied": crit.to_dict(),
        "written": {"criteria": doc.get("criteria"), "tuning": doc.get("tuning")},
        "defaults": GainEvalCriteria().to_dict(),
        "lines": [asdict(ln) for ln in LINES],
        "statuses": list(STATUSES),
        "target_conflicts": crit.target_conflicts(),
        "metric_scales": crit.to_metric_scales(),
        "echo": criteria_echo(crit, built.criteria_source),
        "groups": _criteria_groups(),
    })


def _criteria_groups() -> list:
    """판정선 표(lines) 밖 그룹 중 이름표를 가진 것 — 칸 이름·단위·뜻은 엔진 정본(TRIM_MARGIN_LABELS)이라 화면이 다시
    적지 않는다. 트림 여유 판정선(이관 12단계)은 트림 탭·조건 판정·자동 설계 채택 표의 「여유 미달」을 정하는 선이다."""
    from claw.pipeline.criteria import TRIM_MARGIN_LABELS

    return [{"group": "trim_margin", "title": "트림 여유 판정선 — 트림 탭·조건 판정의 「여유 미달」",
             "cells": [{"key": k, "label": label, "unit": unit, "help": help_}
                       for k, (label, unit, help_) in TRIM_MARGIN_LABELS.items()]}]


@router.post("/profiles", status_code=201)
def create_profile(req: ProfileDocIn, request: Request) -> dict:
    notes = []
    try:
        doc, rev = request.app.state.profiles.create(req.document, notes_out=notes)
    except ProfileError as e:  # 저장 규칙의 id 검사도 경로(/id)가 붙은 ProfileError다
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    except ProfileConflict as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "head": e.head})
    return _body(doc, rev, notes)


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: str, req: ProfileUpdateIn, request: Request) -> dict:
    notes = []
    doc, rev = _store_update(request, profile_id, req.document, req.base_revision, notes)
    return _body(doc, rev, notes)


def _store_update(request, profile_id: str, document, base_revision: int, notes: list) -> tuple:
    """저장소 갱신과 그 오류의 HTTP 대응 — 전체 PUT과 요구영역 PUT이 같은 규칙(403·404·409 head·422 경로)을 쓴다."""
    try:
        return request.app.state.profiles.update(profile_id, document, base_revision, notes_out=notes)
    except ProfileReadOnly as e:
        raise HTTPException(status_code=403, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    except ProfileConflict as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "head": e.head})
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class RegionUpdateIn(BaseModel):
    """operating_region 절 그대로(null = 지우기 → trim_grid 초안). 키를 빠뜨리면 422 — 「지우기」로 읽지 않는다."""

    base_revision: int = Field(ge=1)
    operating_region: dict | None


@router.put("/profiles/{profile_id}/operating-region")
def update_operating_region(profile_id: str, req: RegionUpdateIn, request: Request) -> dict:
    """요구영역만 저장 (05 §11.13 6단계 · 06 §10 ①) — 최신 문서의 operating_region 절만 바꿔 새 리비전으로.

    전체 PUT과 **같은 저장 문서**다: 같은 가드(예제 403 · 낡은 기준 409 head) 뒤 같은 저장소 갱신·같은 문서 검증을
    거친다 — 절 규칙은 엔진 한 곳이고 오류 경로도 /operating_region/…로 같다. 요구영역은 지문 밖이라 지문은 그대로다
    (계산 결과가 낡지 않는다 — 요구영역에 기대는 δe_trim 도출은 provenance.region 대조로 따로 낡는다). 저장 전 확인 단계는
    따로 없다 — 저장이 곧 확정이다(초안 표시는 절이 없을 때뿐)."""
    from claw.opspace import region_key, region_of

    doc, rev, built = _job_head(request, profile_id, req.base_revision)
    new = copy.deepcopy(doc)
    new["operating_region"] = copy.deepcopy(req.operating_region)
    saved, new_rev = _store_update(request, profile_id, new, rev, [])
    region = region_of(saved)
    # 요구영역은 지문 밖이라 기준 리비전 조립의 지문이 곧 새 리비전의 지문이다 — 저장본을 다시 조립하지 않는다
    return {"revision": new_rev, "region": None if region is None else region.to_dict(),
            "region_key": region_key(region), "fingerprint": built.fingerprint}


HISTORY_LIMIT = 50
_HISTORY_MEMO_MAX = 4096
# 저장소 → {(id, 리비전): 그 리비전의 요구영역 요약}. 리비전은 불변이라((id, 리비전)은 한 문서를 영원히 가리킨다 —
# 지워도 번호를 다시 쓰지 않는다) 무효화가 필요 없다. 계보 패널을 열 때마다 전 리비전을 다시 검증·조립하지 않게.
# 저장소를 약한 키로 — id(store)는 앱을 새로 띄우면(테스트) 다른 저장소에 재사용될 수 있다
_history_memo = weakref.WeakKeyDictionary()


def _revision_region(store, profile_id: str, r: int) -> dict:
    """한 리비전의 요구영역 요약 {region_key, confirmed, source, mach, alt, fuel, n_points} — 못 읽으면
    {unreadable, reason}(그건 기억하지 않는다 — 일시적 파일 오류일 수 있다). 지운 뒤라 없으면 KeyError."""
    from claw.opspace import ModelRange, base_grid, region_key, region_of

    memo = _history_memo.setdefault(store, {})
    if (profile_id, r) in memo:
        return memo[(profile_id, r)]
    try:
        doc, _ = store.get(profile_id, r)
    except (ValueError, ProfileUnreadable, OSError) as e:
        return {"unreadable": True, "reason": str(e)}
    region = region_of(doc)
    if region is None:
        out = {"region_key": None, "confirmed": None, "source": None, "mach": None, "alt": None, "fuel": None,
               "n_points": None}
    else:
        # 점 수는 모델과 무관하다(모델은 점의 상태만 가른다) — 리비전마다 기체를 조립하지 않게 전부 덮는 모델로 센다
        try:
            n = len(base_grid(region, ModelRange(mach=None, fuel=(0.0, float("inf"))))["points"])
        except ValueError:
            n = None
        out = {"region_key": region_key(region), "confirmed": region.confirmed, "source": region.source,
               "mach": list(region.mach), "alt": list(region.alt), "fuel": list(region.fuel), "n_points": n}
    if len(memo) >= _HISTORY_MEMO_MAX:
        memo.clear()  # 상한 — 오래 뜬 서버에서 무한히 자라지 않게(다시 읽으면 된다)
    memo[(profile_id, r)] = out
    return out


@router.get("/profiles/{profile_id}/region-history")
def get_region_history(profile_id: str, request: Request,
                       limit: int = Query(default=HISTORY_LIMIT, ge=1, le=1000)) -> dict:
    """요구영역 계보 (05 §11.12 · 06 §10 계보 패널) — {rows, omitted}. rows는 최신 limit개 리비전을 오름차순으로,
    같은 판(region_key)이 이어지면 첫 리비전 한 줄로 접는다(A·B·A는 세 줄 — 되돌림도 이력이다). 행은 {revision,
    region_key, confirmed, source, mach, alt, fuel, n_points} — 요구영역이 없는 리비전은 키·값이 None, 못 읽는 리비전은
    건너뛰지 않고 {revision, unreadable, reason}. omitted는 창 앞에서 읽지 않은 옛 리비전 수(「이전 리비전 k개 생략」)."""
    store = request.app.state.profiles
    try:
        _, head = store.get(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    first = head if head == 0 else max(1, head - limit + 1)  # 예제는 리비전 0 하나뿐
    rows, last = [], object()
    for r in range(first, head + 1):
        try:
            one = _revision_region(store, profile_id, r)
        except KeyError:  # 그사이 지워졌다 — 없는 기체다
            raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
        if one.get("unreadable"):
            rows.append({"revision": r, **one})
            last = object()
            continue
        if one["region_key"] == last:
            continue
        last = one["region_key"]
        rows.append({"revision": r, **one})
    return {"rows": rows, "omitted": max(0, first - 1)}


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, request: Request) -> Response:
    try:
        request.app.state.profiles.delete(profile_id)
    except ProfileReadOnly as e:
        raise HTTPException(status_code=403, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(status_code=204)


@router.post("/profiles/{profile_id}/quick-seed", status_code=202)
def submit_quick_seed(profile_id: str, req: QuickSeedIn, request: Request, response: Response) -> dict:
    """초기 게인 빠른 탐색 잡 (05 §10) — 저장된 최신 리비전에서 게인을 재고, 채택되면 새 리비전으로 쓴다.

    문서를 받지 않는다 — 저장한 기체에서만 돈다(편집 중 글은 먼저 저장한다). 채택 판정·출처는 엔진이 정한다.
    탐색하는 사이 다른 곳에서 저장했으면 덮지 않고 결과에 conflict_head를 남긴다. 예제는 403(복제해서 탐색)."""
    doc, rev, built = _job_head(request, profile_id, req.base_revision)

    def work(job):
        seed = quick_seed(built, sim_check=req.sim_check, on_progress=job.report)
        law = None
        if seed["ok"]:
            design = copy.deepcopy(seed["design"])
            design["provenance"].update(job=job.id, base_revision=rev)
            # 새 시드는 새 설계의 출발 — 옛 확정 게인 표(자동 설계 반영)는 이 설계값과 무관해 지운다.
            # 안 지우면 낡음 대조가 거부해 다음 계산이 전부 조립에서 죽는다 (engine seed.py cand와 같은 규칙)
            law = {"design": design, "gain_tables": None,
                   **({"schedule": seed["schedule"]} if seed["schedule_created"] else {})}
        _finish_profile_job(request, job, "quick_seed", profile_id, doc, rev, built, law, {"seed": seed},
                            ok=seed["ok"])

    return _submit_profile_job(request, response, "quick_seed", work)


@router.post("/profiles/{profile_id}/apply-seed-basis")
def apply_seed_basis_route(profile_id: str, req: ApplySeedBasisIn, request: Request) -> dict:
    """산출 근거 직행 저장 (05 §10.1) — 한 점 닫힌꼴 후보를 law.design 새 리비전으로 쓴다(**검증 전**).

    빠른 탐색과 달리 잡이 아니다 — 한 점 계산이라 동기로 끝난다. 조립 규칙·검증 전 표시는 전부
    엔진(apply_seed_basis)이 정하고, 서버는 quick-seed와 같은 가드(예제 403·낡은 기준 409)와 저장만
    한다. 새 설계의 출발이므로 옛 확정 게인 표는 지운다(quick-seed 채택과 같은 규칙)."""
    doc, rev, built = _job_head(request, profile_id, req.base_revision)
    out = apply_seed_basis(built, req.mach, req.alt, req.fuel, e_ref_dps=req.e_ref_dps)
    if not out["ok"]:
        raise HTTPException(status_code=422, detail=out["reason_text"] or out["reason"])
    design = copy.deepcopy(out["design"])
    design["provenance"].update(base_revision=rev)
    new = copy.deepcopy(doc)
    new["law"].update({"design": design, "gain_tables": None,
                       **({"schedule": out["schedule"]} if out["schedule_created"] else {})})
    try:
        _, new_rev = request.app.state.profiles.update(profile_id, new, rev)
    except ProfileConflict as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "head": e.head})
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    return {"written": True, "revision": new_rev, "schedule_created": out["schedule_created"],
            "provenance": design["provenance"]}


@router.post("/profiles/{profile_id}/derive-de-trim", status_code=202)
def submit_derive_de_trim(profile_id: str, req: DeriveDeTrimIn, request: Request, response: Response) -> dict:
    """δe_trim 표 도출 잡 (02 §5.6.1) — 저장된 최신 리비전의 플랜트로 할당 표를 재고, 채택되면 새 리비전으로 쓴다.

    출처에 플랜트 지문이 남아 플랜트가 바뀌면 법칙 조립이 낡은 표를 거부한다(BuiltProfile.alloc_trim_table).
    가드·충돌 처리는 초기 게인 탐색과 같다."""
    doc, rev, built = _job_head(request, profile_id, req.base_revision)

    # 형상 변형도 함께 잰다 — 표는 문서에 하나라 플랜트를 바꾸는 변형이 같은 표를 쓴다
    variants = [build_profile(doc, v["id"], validated=True) for v in doc["variants"]]

    def work(job):
        out = derive_de_trim(built, variants=variants, check_step=req.check_step, on_progress=job.report)
        law = None
        if out["ok"]:
            alloc = copy.deepcopy(out["alloc"])
            alloc["de_trim"]["provenance"].update(job=job.id, base_revision=rev)
            law = {"alloc": alloc}
        _finish_profile_job(request, job, "derive_de_trim", profile_id, doc, rev, built, law, {"derive": out},
                            ok=out["ok"])

    return _submit_profile_job(request, response, "derive_de_trim", work)


def _job_head(request, profile_id: str, base_revision: int) -> tuple:
    """기체를 고치는 잡의 출발점 — (문서, 리비전, 조립). 예제 403 · 없음 404 · 손상 409 · 낡은 기준 409(head 동봉)."""
    if profile_id == EXAMPLE_ID:
        raise HTTPException(status_code=403, detail="예제 기체는 고칠 수 없다 — 복제한 기체에서 돌린다")
    try:
        doc, rev = request.app.state.profiles.get(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if base_revision != rev:
        raise HTTPException(status_code=409, detail={
            "message": f"기준 리비전 {base_revision}이 최신 {rev}와 다르다 — 최신을 불러온 뒤 돌린다", "head": rev})
    built = build_profile(doc, validated=True)
    built.revision, built.source = rev, "request"
    return doc, rev, built


def _finish_profile_job(request, job, kind, profile_id, doc, rev, built, law, body, *, ok) -> None:
    """채택된 법칙 절(law — {"design"|"schedule"|"alloc": …})을 기준 리비전 위에 쓰고 결과를 남긴다.

    그사이 다른 곳에서 저장했으면 덮지 않고 conflict_head를 남긴다. 취소가 들어왔으면 쓰지 않는다 — 쓰기 직전에
    진행을 끝(1/1)으로 보고하므로, 쓴 뒤에 온 취소가 결과를 「취소됨」으로 강등하지 않는다. 그사이 기체가
    지워졌거나 문서가 저장 규칙을 넘지 못하면 계산 결과는 남기고 write_error로 사유를 싣는다."""
    written, head, new_rev, write_error = False, None, None, None
    if law is not None and not job.cancel_requested:
        new = copy.deepcopy(doc)
        new["law"].update(law)
        job.report(1, 1, "기체 리비전 저장")
        try:
            _, new_rev = request.app.state.profiles.update(profile_id, new, rev)
            written = True
        except ProfileConflict as e:
            head = e.head
        except (KeyError, ValueError, ProfileUnreadable) as e:  # ValueError: 저장 규칙(ProfileError)·id 형식
            write_error = f"{type(e).__name__}: {e}"
    echo = profile_echo(built)
    request.app.state.store.save(job.id, to_jsonable({
        "kind": kind, "profile": {**echo, "base_revision": rev, "revision": new_rev},
        "written": written, "conflict_head": head, "write_error": write_error, **body,
    }), meta={"kind": kind, "profile": echo, "created": job.created,
              "status": "written" if written else ("ok" if ok else "failed")})
    job.result_id = job.id


def _submit_profile_job(request, response, kind, work) -> dict:
    job = request.app.state.jobs.submit(kind, work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


@router.post("/profiles/validate")
def validate_profile(req: ProfileDocIn, request: Request) -> dict:
    """저장하지 않고 검증만 — 편집 중 문서의 오류 경로와 지문. 저장과 같은 규칙이다(예약 id·`_` 시작
    id·예제 표시) — 여기서 통과한 문서를 저장이 거부하면 편집기가 초록 표시 뒤에 실패한다."""
    notes = []
    try:
        doc = request.app.state.profiles.checked(req.document, notes_out=notes)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    # 옛 스키마 문서는 올린 문서를 함께 준다 — 가져오기 미리 보기·편집기가 올린 모양으로 이어 고친다(저장은 아직 없다)
    return {"ok": True, **_fingerprints(doc), "warnings": document_warnings(doc), "upgrade_notes": notes,
            **({"document": doc} if notes else {})}


def _preview_built(document, variant):
    """미리 보기(곡선·산출 근거) 조립 — 저장·검증과 같은 올림 길(upgraded)을 탄다. 옛 스키마 문서(가져온 v2 등)를 편집기가
    저장 전에 보는 길이라, 여기만 올리지 않으면 같은 문서가 검증은 통과하고 곡선은 422가 된다. → (built, 올림 사유)."""
    doc, notes, _ = upgraded(document)
    return build_profile(validate_document(doc), variant, validated=True), notes


def _with_notes(out: dict, notes: list) -> dict:
    # 올렸을 때만 단다 — 올리지 않은 문서의 응답은 종전과 바이트 단위로 같다
    return {**out, "upgrade_notes": notes} if notes else out


@router.post("/profiles/aero-slice")
def profile_aero_slice(req: AeroSliceIn) -> dict:
    """공력 DB 뷰어 곡선 — 문서의 계수 계산기로 한 축을 따라 CL·CD·동체축 계수와 실속 대조 (02 §5.2).

    기체 id가 아니라 **문서**를 받는다: 편집기에서 표를 반입한 직후 저장하지 않고 곡선을 봐야 하고, 읽기 전용
    예제도 같은 길로 본다. 문서는 저장 규칙이 아니라 스키마로만 검증한다(보기일 뿐 저장이 아니다). 옛 스키마 문서는
    저장·검증과 같이 올려서 보고 사유(upgrade_notes)를 함께 준다(_preview_built)."""
    try:
        built, notes = _preview_built(req.document, req.variant)
        return _with_notes(to_jsonable(aero_slice(built, req.along, req.start, req.stop, req.n, req.fixed)), notes)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    except ValueError as e:  # 인자 판정·표 질의 오류(TableError도 ValueError)
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/profiles/aero-stability")
def profile_aero_stability(req: AeroStabilityIn) -> dict:
    """정적 안정성 도함수 곡선 — α 격자의 Clβ·Cnβ·Cmα와 부호 판정 (02 §5.2 확장).

    aero-slice와 같은 계약(문서 본문·스키마 검증만)이고, 도함수·부호 관례·위반 구간은
    전부 엔진(stability_slice) 산출 — 서버는 통과만 한다."""
    try:
        built, notes = _preview_built(req.document, req.variant)
        return _with_notes(to_jsonable(stability_slice(built, req.start, req.stop, req.n, req.fixed)), notes)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    except ValueError as e:  # 인자 판정·표 질의 오류(TableError도 ValueError)
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/profiles/seed-basis")
def profile_seed_basis(req: SeedBasisIn) -> dict:
    """초기 게인 산출 근거 — 한 트림점의 저차 근사 닫힌꼴 후보와 확인(전체 모델·안정·예산) (05 §10.1).

    aero-slice와 같은 계약(문서 본문·스키마 검증만·저장 없음) — 편집 중 문서와 읽기 전용 예제도 같은 길로
    본다. 닫힌꼴·판정·사유 문구는 전부 엔진(seed_basis) 산출이고 시드 채택은 여전히 quick-seed 잡이 한다."""
    try:
        built, notes = _preview_built(req.document, req.variant)
        return _with_notes(to_jsonable(seed_basis(built, req.mach, req.alt, req.fuel, e_ref_dps=req.e_ref_dps)), notes)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    except ValueError as e:  # 인자 판정·표 질의 오류(TableError도 ValueError)
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/profiles/parse-table")
def parse_table(req: ParseTableIn) -> dict:
    """CSV 텍스트(long-format) → 표 JSON — 파일을 올리지 않고 웹이 읽은 텍스트를 보낸다."""
    try:
        table = parse_table_csv(req.csv_text, req.axis_cols, req.value_col,
                                extrapolate=req.extrapolate)
    except TableError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return table_dict(table)
