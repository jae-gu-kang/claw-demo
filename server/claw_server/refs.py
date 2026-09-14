"""요청 → 기체 프로파일 해석 (02 §5.6) — 라우트는 기체를 여기서만 받는다.

요청은 `profile: {id, variant?, revision?}`로 기체를 고른다(GET은 `profile_id`·`profile_variant`·
`profile_revision` 쿼리). 고르지 않으면 예제 기체이고, 그 사실을 `source: "default-example"`로 echo한다
— 조용히 예제로 계산하고 선택한 기체처럼 보이면 안 되기 때문이다.

해석 결과는 저장소 스냅숏으로 남는다(지문 키). 결과 meta·응답에 싣는 `profile` 블록은
`profile_echo`가 만든다 — 어느 기체·어느 형상 변형·어느 리비전·어느 지문으로 계산했는가.
"""

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from claw.profile import EXAMPLE_ID, ProfileError, build_profile


class ProfileRef(BaseModel):
    """기체 선택 — id + 형상 변형 + 리비전(없으면 최신)."""

    id: str = Field(min_length=1, max_length=64)
    variant: str | None = Field(default=None, min_length=1, max_length=64)
    revision: int | None = Field(default=None, ge=0)


def profile_query(
    profile_id: str | None = Query(default=None, min_length=1, max_length=64),
    profile_variant: str | None = Query(default=None, min_length=1, max_length=64),
    profile_revision: int | None = Query(default=None, ge=0),
) -> ProfileRef | None:
    """GET 라우트용 기체 선택 — 변형·리비전만 주고 id를 빠뜨리면 거부한다(예제의 변형으로 오해됨)."""
    if profile_id is None:
        if profile_variant is not None or profile_revision is not None:
            raise HTTPException(status_code=422,
                                detail="profile_variant·profile_revision은 profile_id와 함께 준다")
        return None
    return ProfileRef(id=profile_id, variant=profile_variant, revision=profile_revision)


def profile_error_detail(e: ProfileError) -> dict:
    return {"path": e.path, "message": e.message}


def resolve_profile(request, ref: ProfileRef | None):
    """요청의 기체 선택 → BuiltProfile (revision·source 속성을 달아 돌려준다)."""
    store = request.app.state.profiles
    source = "default-example" if ref is None else "request"
    ref = ref or ProfileRef(id=EXAMPLE_ID)
    from claw_server.profiles import ProfileUnreadable

    try:
        doc, revision = store.get(ref.id, ref.revision)
    except KeyError:
        at = "" if ref.revision is None else f"@{ref.revision}"
        raise HTTPException(status_code=404, detail=f"기체 프로파일 없음: {ref.id}{at}")
    except ProfileUnreadable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        built = build_profile(doc, ref.variant, validated=True)  # store.get이 이미 다시 검증했다
    except ProfileError:
        raise HTTPException(status_code=404, detail=f"없는 형상 변형: {ref.id}/{ref.variant}")
    built.revision = revision
    built.source = source
    store.snapshot(built)
    return built


def resolve_snapshot(request, echo: dict | None):
    """저장된 결과의 기체 echo → 그때 계산에 쓴 BuiltProfile (설계 재개·재현용).

    지문으로 스냅숏을 찾으므로 그 뒤 기체 문서가 고쳐지거나 지워져도 **같은 기체로** 이어간다. echo가
    없는 옛 결과는 기체 선택이 생기기 전의 것 — 예제 기체로 계산됐다 — 이고 source가 그 사실을 남긴다.
    """
    if not echo:
        built = resolve_profile(request, None)
        built.source = "legacy-unrecorded"
        return built
    fp = echo.get("fingerprint", "")
    try:
        doc = request.app.state.profiles.load_snapshot(fp)
    except KeyError:
        raise HTTPException(status_code=409, detail=f"재개 불가 — 계산에 쓴 기체 스냅숏이 없다: {fp!r}")
    except (ValueError, OSError) as e:  # 지문 형식이 틀림, 손상 JSON, UTF-8이 아닌 파일
        raise HTTPException(status_code=409, detail=f"재개 불가 — 기체 스냅숏을 읽을 수 없다: {fp!r} ({e})")
    # 저장소 문서처럼 다시 검증한다 — 스키마가 바뀐 뒤의 옛 스냅숏은 조립 도중 500이 아니라 409다.
    # 스냅숏은 적용 문서라 variants가 없다(지문 밖이라 빈 목록을 채워도 지문은 같다)
    try:
        if not isinstance(doc, dict):
            raise ProfileError("", "스냅숏이 객체가 아니다")
        built = build_profile({**doc, "variants": []})
    except ProfileError as e:
        raise HTTPException(status_code=409, detail=f"재개 불가 — 기체 스냅숏이 현재 스키마를 넘지 못한다: {e}")
    if built.fingerprint != fp:
        raise HTTPException(status_code=409, detail=f"재개 불가 — 스냅숏 지문 불일치: {built.fingerprint} ≠ {fp}")
    # 지문은 이름표를 뺀 계산 내용이라, 같은 지문의 스냅숏은 **다른 이름의 기체**가 먼저 남긴 것일 수
    # 있다(예제를 복제만 한 기체). 계산은 같으니 스냅숏으로 조립하되, 이름표는 저장된 echo의 것을 쓴다
    built.id = echo.get("id", built.id)
    built.name = echo.get("name", built.name)
    built.is_example = echo.get("is_example", built.is_example)
    built.variant = echo.get("variant")
    built.revision = echo.get("revision")
    built.source = "snapshot"
    return built


def profile_echo(built) -> dict:
    """결과 meta·응답에 싣는 기체 블록 — 계산에 쓴 기체를 되짚는 계보."""
    return {
        "id": built.id, "name": built.name, "variant": built.variant,
        # revision·source는 해석기가 단다 — 해석을 안 거친 조립(예: 테스트)에는 None이다
        "revision": getattr(built, "revision", None), "fingerprint": built.fingerprint,
        "plant_fingerprint": built.plant_fingerprint, "is_example": built.is_example,
        "source": getattr(built, "source", None),
    }
