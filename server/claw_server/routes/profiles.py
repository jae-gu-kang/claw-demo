"""기체 프로파일 라우트 (02 §5.6) — 목록·조회·생성·갱신·삭제·검증·CSV 표 판독.

기체 문서는 웹에서만 만들고 고친다. 내보내기는 조회(GET)의 `document`, 가져오기는 생성(POST)이다 —
같은 검증을 두 번 적지 않는다. 검증 오류는 422이고 detail이 문서 안 경로를 싣는다(웹 편집기가 칸을
짚는다). 갱신은 base_revision이 최신과 같을 때만 받고, 다르면 409와 최신 리비전을 준다.
"""

import copy
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from claw.design.seed import quick_seed
from claw.profile import ProfileError, build_profile, validate_document
from claw.profile.derive import CHECK_STEP, derive_de_trim
from claw.profile.aeroview import MAX_POINTS, aero_slice
from claw.profile.form import form_spec
from claw.tables import TableError
from claw.tables.loader import parse_table_csv
from claw_server.profiles import EXAMPLE_ID, ProfileConflict, ProfileReadOnly, ProfileUnreadable
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


class QuickSeedIn(BaseModel):
    base_revision: int = Field(ge=1)
    sim_check: bool = False


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


def _body(doc: dict, revision: int) -> dict:
    return {"document": doc, "revision": revision, "is_example": doc["is_example"], **_fingerprints(doc)}


@router.get("/profiles")
def list_profiles(request: Request) -> list:
    return request.app.state.profiles.list()


@router.get("/profiles/_form")
def profile_form() -> dict:
    """편집 폼 서술 — 칸 이름·단위·형식·선택지. 정본은 엔진 `claw.profile.form`(검증기 옆)이다.

    기체 id는 `_`로 시작할 수 없으므로(저장소 규칙) 이 경로는 기체 조회와 겹치지 않는다 — 이 선언이
    `/profiles/{profile_id}`보다 앞에 있어야 한다."""
    return form_spec()


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, request: Request, revision: int | None = None) -> dict:
    try:
        doc, rev = request.app.state.profiles.get(profile_id, revision)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _body(doc, rev)


@router.post("/profiles", status_code=201)
def create_profile(req: ProfileDocIn, request: Request) -> dict:
    try:
        doc, rev = request.app.state.profiles.create(req.document)
    except ProfileError as e:  # 저장 규칙의 id 검사도 경로(/id)가 붙은 ProfileError다
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    except ProfileConflict as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "head": e.head})
    return _body(doc, rev)


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: str, req: ProfileUpdateIn, request: Request) -> dict:
    try:
        doc, rev = request.app.state.profiles.update(profile_id, req.document, req.base_revision)
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
    return _body(doc, rev)


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
            law = {"design": design, **({"schedule": seed["schedule"]} if seed["schedule_created"] else {})}
        _finish_profile_job(request, job, "quick_seed", profile_id, doc, rev, built, law, {"seed": seed},
                            ok=seed["ok"])

    return _submit_profile_job(request, response, "quick_seed", work)


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
    try:
        doc = request.app.state.profiles.checked(req.document)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    return {"ok": True, **_fingerprints(doc)}


@router.post("/profiles/aero-slice")
def profile_aero_slice(req: AeroSliceIn) -> dict:
    """공력 DB 뷰어 곡선 — 문서의 계수 계산기로 한 축을 따라 CL·CD·동체축 계수와 실속 대조 (02 §5.2).

    기체 id가 아니라 **문서**를 받는다: 편집기에서 표를 반입한 직후 저장하지 않고 곡선을 봐야 하고, 읽기 전용
    예제도 같은 길로 본다. 문서는 저장 규칙이 아니라 스키마로만 검증한다(보기일 뿐 저장이 아니다)."""
    try:
        built = build_profile(validate_document(req.document), req.variant, validated=True)
        return to_jsonable(aero_slice(built, req.along, req.start, req.stop, req.n, req.fixed))
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
