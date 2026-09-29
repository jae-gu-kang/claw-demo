"""기체 프로파일 라우트 (02 §5.6) — 목록·조회·생성·갱신·삭제·검증·CSV 표 판독·쇼케이스 기체 설치.

기체 문서는 웹에서만 만들고 고친다. 내보내기는 조회(GET)의 `document`, 가져오기는 생성(POST)이다 —
같은 검증을 두 번 적지 않는다. 검증 오류는 422이고 detail이 문서 안 경로를 싣는다(웹 편집기가 칸을
짚는다). 갱신은 base_revision이 최신과 같을 때만 받고, 다르면 409와 최신 리비전을 준다.
"""

import copy
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
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


def _body(doc: dict, revision: int) -> dict:
    return {"document": doc, "revision": revision, "is_example": doc["is_example"], **_fingerprints(doc),
            "warnings": document_warnings(doc)}


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
    try:
        doc, rev = request.app.state.profiles.get(profile_id, revision)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {profile_id}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _body(doc, rev)


@router.get("/profiles/{profile_id}/criteria")
def get_profile_criteria(profile_id: str, request: Request, revision: int | None = None) -> dict:
    """이 작업 단위의 평가 기준 — 모든 탭이 판정에 쓰는 한 벌(기준 통합 ①).

    `applied`는 도구 기본값을 펼친 적용값, `written`은 문서가 실제로 적은 칸(없음 = 기본값을 따른다), `defaults`는
    도구 기본값이다 — 편집 화면이 「기본값을 따르는 칸」과 「이 기체가 바꾼 칸」을 가를 수 있게. `lines`는 판정선의
    뜻(방향·합격선·권장선·목표 필드 — design.criteria.LINES)이라 화면이 방향을 다시 적지 않는다. `echo`는 결과에
    실리는 기준 블록과 같은 모양이다 — 화면은 결과의 echo를 이것과 대조해 「재평가 필요」를 가린다.
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
    })


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
    try:
        doc = request.app.state.profiles.checked(req.document)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    return {"ok": True, **_fingerprints(doc), "warnings": document_warnings(doc)}


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


@router.post("/profiles/aero-stability")
def profile_aero_stability(req: AeroStabilityIn) -> dict:
    """정적 안정성 도함수 곡선 — α 격자의 Clβ·Cnβ·Cmα와 부호 판정 (02 §5.2 확장).

    aero-slice와 같은 계약(문서 본문·스키마 검증만)이고, 도함수·부호 관례·위반 구간은
    전부 엔진(stability_slice) 산출 — 서버는 통과만 한다."""
    try:
        built = build_profile(validate_document(req.document), req.variant, validated=True)
        return to_jsonable(stability_slice(built, req.start, req.stop, req.n, req.fixed))
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
        built = build_profile(validate_document(req.document), req.variant, validated=True)
        return to_jsonable(seed_basis(built, req.mach, req.alt, req.fuel, e_ref_dps=req.e_ref_dps))
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
