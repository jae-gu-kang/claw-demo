"""요청 → 기체 프로파일 해석 (02 §5.6) — 라우트는 기체를 여기서만 받는다.

요청은 `profile: {id, variant?, revision?}`로 기체를 고른다(GET은 `profile_id`·`profile_variant`·
`profile_revision` 쿼리). 고르지 않으면 예제 기체이고, 그 사실을 `source: "default-example"`로 echo한다
— 조용히 예제로 계산하고 선택한 기체처럼 보이면 안 되기 때문이다.

해석 결과는 저장소 스냅숏으로 남는다(지문 키). 결과 meta·응답에 싣는 `profile` 블록은
`profile_echo`가 만든다 — 어느 기체·어느 형상 변형·어느 리비전·어느 지문으로 계산했는가.
"""

from typing import Literal

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

    notes = []
    try:
        doc, revision = store.get(ref.id, ref.revision, notes_out=notes)
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
    if notes:
        # 옛 스키마 저장본을 읽을 때 올려서 계산했다 — (id, 리비전)은 옛 원본 파일을 가리키므로 그 사실을 결과가 싣는다
        built.upgraded_from = {"schema_version": store.stored_schema_version(ref.id, revision), "notes": notes}
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
    # 같은 지문·다른 내용으로 따로 남은 스냅숏(ProfileStore.snapshot) — echo가 그 키를 실었으면 그 파일이다
    key = echo.get("snapshot") or fp
    if key != fp and not (isinstance(key, str) and key.startswith(f"{fp}-")):
        raise HTTPException(status_code=409, detail=f"재개 불가 — 스냅숏 키가 지문과 맞지 않는다: {key!r} ≠ {fp!r}")
    try:
        doc = request.app.state.profiles.load_snapshot(key)
    except KeyError:
        raise HTTPException(status_code=409, detail=f"재개 불가 — 계산에 쓴 기체 스냅숏이 없다: {key!r}")
    except (ValueError, OSError) as e:  # 지문 형식이 틀림, 손상 JSON, UTF-8이 아닌 파일
        raise HTTPException(status_code=409, detail=f"재개 불가 — 기체 스냅숏을 읽을 수 없다: {key!r} ({e})")
    if key != fp:
        from claw_server.profiles import snapshot_hash

        # 내용 해시가 이름과 같아야 그 결과의 문서다 — 지문 대조는 지문 밖 칸(기준 등)을 못 본다
        if not isinstance(doc, dict) or snapshot_hash(doc) != key.split("-", 1)[1]:
            raise HTTPException(status_code=409, detail=f"재개 불가 — 스냅숏 내용 해시 불일치: {key!r}")
    # 저장소 문서처럼 다시 검증한다 — 스키마가 바뀐 뒤의 옛 스냅숏은 조립 도중 500이 아니라 409다.
    # 스냅숏은 적용 문서라 variants가 없다(지문 밖이라 빈 목록을 채워도 지문은 같다)
    if not isinstance(doc, dict):
        raise HTTPException(status_code=409, detail="재개 불가 — 기체 스냅숏이 객체가 아니다")
    from claw_server.profiles import upgraded

    upgraded_from = None
    if upgraded(doc)[2] is not None:
        # 옛 스키마 스냅숏(05 §11.13 이관 11단계) — 올리면 지문이 바뀐다(절이 옮겨 가므로). 무결성은 **올리기 전**
        # 원본으로 잰다: 계보 지문은 이름표를 뺀 문서의 해시라 스키마를 가리지 않는다. 맞으면 올려서 조립하고 원래
        # 지문·사유를 echo한다 — 옛 결과의 설계 재개가 스키마 변경으로 끊기지 않게
        from claw.profile.fingerprint import profile_fingerprint

        try:
            raw_fp = profile_fingerprint({**doc, "variants": []})
        except (KeyError, TypeError, AttributeError, ValueError):
            raw_fp = None
        if raw_fp != fp:
            raise HTTPException(status_code=409, detail=f"재개 불가 — 옛 스키마 스냅숏 지문 불일치: {raw_fp} ≠ {fp}")
        try:
            doc, notes, old = upgraded(doc)
        except ProfileError as e:
            raise HTTPException(status_code=409, detail=f"재개 불가 — 옛 스키마 스냅숏을 올리지 못한다: {e}")
        upgraded_from = {"schema_version": old, "fingerprint": fp, "notes": notes}
    try:
        built = build_profile({**doc, "variants": []})
    except ProfileError as e:
        raise HTTPException(status_code=409, detail=f"재개 불가 — 기체 스냅숏이 현재 스키마를 넘지 못한다: {e}")
    if upgraded_from is None and built.fingerprint != fp:
        raise HTTPException(status_code=409, detail=f"재개 불가 — 스냅숏 지문 불일치: {built.fingerprint} ≠ {fp}")
    if upgraded_from is not None:
        built.upgraded_from = upgraded_from
        # 올린 문서도 제 지문으로 남긴다 — 재개 결과의 echo가 가리킨다. 올린 지문이 다른 문서와 겹치면(트림 α 여유만 달랐던
        # 두 v2 문서) snapshot이 내용 해시 키로 따로 남기고 built.snapshot_key에 적는다
        request.app.state.profiles.snapshot(built)
    elif key != fp:
        built.snapshot_key = key  # 재개 결과도 같은 파일을 가리킨다
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
        # 초기 탐색 게인으로 계산한 결과만 표시한다 — 자동 설계 전 게인이라는 사실이 결과와 함께 다녀야 한다.
        # 다른 출처에는 키를 달지 않는다: 예제 기체 결과의 서버 골든(바이트 동일 증명)이 이 블록을 싣는다
        **({"design_source": "quick_seed"} if _seeded(built) else {}),
        # 옛 스키마 문서(저장본·스냅숏)를 올려서 계산했다 — {schema_version, notes, fingerprint?(스냅숏의 원래 지문)}.
        # 올린 경우에만 단다(골든 보존과 같은 이유)
        **({"upgraded_from": built.upgraded_from} if getattr(built, "upgraded_from", None) else {}),
        # 같은 지문에 내용이 다른 스냅숏이 먼저 있었다 — 이 결과의 문서는 `{지문}-{내용 해시}` 파일이다(ProfileStore.snapshot).
        # 없으면 지문 파일이 곧 이 문서다(키를 달지 않는다 — 골든 보존)
        **({"snapshot": built.snapshot_key} if getattr(built, "snapshot_key", None) else {}),
    }


def _seeded(built) -> bool:
    design = built.doc["law"]["design"]
    prov = None if design is None else design["provenance"]
    return isinstance(prov, dict) and prov.get("source") == "quick_seed"


# ── 평가 기준 해석 (기준 통합 ① S3a) ─────────────────────────────────────────────
#
# 기체 프로파일 = 설계 작업 단위이고, 그 단위의 모든 탭이 프로파일의 기준 한 벌(/criteria 합격·권장선 +
# /tuning 목표·가중치)로 판정한다. 라우트는 기준을 여기서만 받는다 — 라우트마다 기본값을 따로 만들면 같은 점이
# 탭마다 다르게 판정된다(기준 통합의 이유). 결과에는 criteria_echo를 싣는다: 어느 기준(지문 둘·판정 함수 버전)
# 으로, 어디서 온 기준(source)으로 판정했나. 이 블록은 profile_echo와 **따로** 둔다 — profile 블록은 서버 골든이
# 바이트로 못박고 있고, 기준은 기체가 아니다.

CRITERIA_SOURCES = ("profile", "default", "request", "snapshot")


REQUEST_CRITERIA_REJECTED = ("판정선·튜닝 목표는 요청에 싣지 않는다 — 선택한 기체 프로파일의 /criteria·/tuning이 "
                             "정본이다(기체 탭에서 편집). 다른 기준으로 보려면 그 기준을 적은 기체(복제)를 고른다")


def resolve_criteria(built, request_criteria: dict | None = None):
    """(GainEvalCriteria, source) — 선택 기체의 기준("profile" | 없으면 도구 기본값 "default").

    요청 기준은 **거절한다**(기준 통합 ① S3b, v1.54): 같은 기체의 결과가 요청마다 다른 기준으로 판정되면 탭마다 같은
    점이 다르게 판정되던 문제로 돌아간다. 시험용 「가정 기준」이 필요하면 시험 모드를 따로 설계한다(결정 — 이번 범위
    밖). 거절은 ValueError다(라우트가 422). 출처 "request"는 v1.52~v1.53 사이에 저장된 결과를 읽기 위해 어휘에 남는다.

    스냅숏에서 되살린 기체(built.source == "snapshot")는 source를 "snapshot"으로 밝힌다: 스냅숏은 기체 지문 키로
    저장되는데 기준은 지문 밖이라, 그 문서의 기준은 **이 기체를 처음 남긴 문서의 기준**일 뿐 그 결과를 낸 기준이라는
    보장이 없다. 재개 경로는 저장된 결과가 실은 기준을 써야 한다. 요청 기준 형식 오류는 ValueError다(라우트가 422)."""
    if request_criteria is not None:
        raise ValueError(REQUEST_CRITERIA_REJECTED)
    if getattr(built, "source", None) == "snapshot":
        return built.eval_criteria, "snapshot"
    return built.eval_criteria, built.criteria_source


def criteria_echo(crit, source: str) -> dict:
    """결과 meta·응답에 싣는 기준 블록 — 판정 기준 지문·목표 지문·판정 함수 버전·출처.
    화면은 이것을 지금 프로파일의 지문과 대조해 「재평가 필요」(판정 기준 지문 다름)·「J 재계산 필요」·「목표와 다름」
    (목표 지문만 다름)을 가른다. scheme이 없는 옛 결과는 대조할 수 없다(「판정 기준 미상」)."""
    from claw.pipeline.criteria import JUDGEMENT_SCHEME

    if source not in CRITERIA_SOURCES:
        raise ValueError(f"기준 출처는 {CRITERIA_SOURCES} 중 하나: {source!r}")
    return {
        "judgement_fingerprint": crit.judgement_fingerprint(),
        "targets_fingerprint": crit.targets_fingerprint(),
        "scheme": JUDGEMENT_SCHEME,
        "source": source,
    }


# ── 트림 저장소 (05 §11.8) ─────────────────────────────────────────────────────
#
# 라우트는 저장소 창을 여기서만 받는다 — 명목 기체(profile.aircraft())의 수평비행 트림만 대상이다. 섭동 기체(검증 코너·
# 스윕 없는 강건성)·지상 평형·보드선도의 z0 풀이는 창을 받지 않는다(엔진 trim_batch가 섭동 기체를 거부하는 것과 짝).

ReusePolicy = Literal["converged", "none"]  # 요청 플래그 — 수렴 기록만 재사용 / 읽지 않음(쓰기는 한다)
REUSE_POLICY_OFF = "off"  # 저장소가 꺼진 서버(CLAW_TRIM_STORE_LIMIT=0) — 요청 정책과 무관하게 전부 새로 푼다


def trim_scope(request, profile):
    """이 기체의 트림 지문 창 — 저장소가 꺼져 있으면 None(trim_batch가 종전 그대로 푼다)."""
    store = getattr(request.app.state, "trim_store", None)
    if store is None or not store.enabled:
        return None
    return store.scope(profile.trim_fingerprint)


def stored_failures(scope, cases) -> frozenset:
    """배치 전에 저장소에 **미수렴**으로 있던 케이스 이름 — 다시 풀린 실패를 echo가 세게(resolved_failed)."""
    if scope is None:
        return frozenset()
    out = set()
    for c in cases:
        rec = scope.peek(c)
        if rec is not None and not rec.converged:
            out.add(c.name)
    return frozenset(out)


def reuse_echo(results, scope, policy: str, failed_before=frozenset(), *, trim_fingerprint: str | None = None) -> dict:
    """결과 본문 최상위 trim_reuse — 몇 점을 저장소에서 꺼냈고 몇 점을 새로 풀었나. 재사용한 해도 판정은 이 요청의
    기준으로 다시 세웠다(엔진 assemble_level) — 이 블록은 「풀이를 누가 했나」만 말한다."""
    reused = [tr.case.name for tr in results if getattr(tr, "origin", "computed") == "reused"]
    computed = [tr for tr in results if getattr(tr, "origin", "computed") != "reused"]
    return {
        # 꺼진 저장소에서도 지문은 싣는다 — 어느 트림 키 공간의 계산이었는지는 저장소 유무와 무관하다
        "trim_fingerprint": trim_fingerprint or (None if scope is None else scope.trim_fingerprint),
        "reused": len(reused),
        "computed": len(computed),
        "resolved_failed": sum(1 for tr in computed if tr.case.name in failed_before),
        "policy": REUSE_POLICY_OFF if scope is None else policy,
        "reused_names": reused,
    }


def reuse_counts(echo: dict) -> dict:
    """meta용 요약 — 목록 화면이 본문을 열지 않고 「재사용 k · 새로 n」을 쓴다."""
    return {k: echo[k] for k in ("reused", "computed", "resolved_failed")}
