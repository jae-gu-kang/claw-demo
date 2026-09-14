"""기체 프로파일 라우트 (02 §5.6) — 목록·조회·생성·갱신·삭제·검증·CSV 표 판독.

기체 문서는 웹에서만 만들고 고친다. 내보내기는 조회(GET)의 `document`, 가져오기는 생성(POST)이다 —
같은 검증을 두 번 적지 않는다. 검증 오류는 422이고 detail이 문서 안 경로를 싣는다(웹 편집기가 칸을
짚는다). 갱신은 base_revision이 최신과 같을 때만 받고, 다르면 409와 최신 리비전을 준다.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from claw.profile import ProfileError, build_profile
from claw.profile.form import form_spec
from claw.tables import TableError
from claw.tables.loader import parse_table_csv
from claw_server.profiles import ProfileConflict, ProfileReadOnly, ProfileUnreadable
from claw_server.refs import profile_error_detail
from claw_server.serialize import table_dict

router = APIRouter(tags=["profiles"])

MAX_CSV_CHARS = 5_000_000  # 공력 표 한 장 — 오타 붙여넣기가 단일 워커를 물지 않게


class ProfileDocIn(BaseModel):
    document: dict


class ProfileUpdateIn(BaseModel):
    base_revision: int = Field(ge=1)
    document: dict


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


@router.post("/profiles/validate")
def validate_profile(req: ProfileDocIn, request: Request) -> dict:
    """저장하지 않고 검증만 — 편집 중 문서의 오류 경로와 지문. 저장과 같은 규칙이다(예약 id·`_` 시작
    id·예제 표시) — 여기서 통과한 문서를 저장이 거부하면 편집기가 초록 표시 뒤에 실패한다."""
    try:
        doc = request.app.state.profiles.checked(req.document)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=profile_error_detail(e))
    return {"ok": True, **_fingerprints(doc)}


@router.post("/profiles/parse-table")
def parse_table(req: ParseTableIn) -> dict:
    """CSV 텍스트(long-format) → 표 JSON — 파일을 올리지 않고 웹이 읽은 텍스트를 보낸다."""
    try:
        table = parse_table_csv(req.csv_text, req.axis_cols, req.value_col,
                                extrapolate=req.extrapolate)
    except TableError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return table_dict(table)
