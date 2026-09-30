"""Saved design alternatives, revisions, branches, and matching evaluations."""

import copy
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from claw.profile import ProfileError, build_profile
from claw.profile.fingerprint import gain_tables_basis_fingerprint
from claw_server.refs import profile_echo
from claw_server.profiles import ProfileConflict, ProfileReadOnly, ProfileUnreadable
from claw_server.routes.sim import PolyTableIn, TableIn, build_gain_tables


router = APIRouter(tags=["design entities"])


class CreateIn(BaseModel):
    profile_id: str
    variant: str | None = None
    name: str = Field(min_length=1, max_length=100)


class VersionIn(BaseModel):
    expected_count: int = Field(ge=0)
    mode: str
    config: dict | None = None
    auto_result_id: str | None = None
    based_on_evaluation_id: str | None = None
    parent_version: int | None = Field(default=None, ge=1)
    note: str = Field(default="", max_length=500)
    improvement_result_id: str | None = None
    candidate_index: int = Field(default=0, ge=0)


class EvaluationIn(BaseModel):
    result_id: str


class BranchIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    number: int = Field(ge=1)


class ApplyIn(BaseModel):
    base_revision: int = Field(ge=1)


def _entity(request, entity_id):
    try:
        return request.app.state.design_entities.get(entity_id)
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(404, "설계안 없음") from None


def _result(request, result_id, kind):
    try:
        body = request.app.state.store.load(result_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "결과 없음") from None
    if body.get("kind") != kind:
        raise HTTPException(422, f"{kind} 결과가 아닙니다")
    return body


def _same_profile(a, b):
    return a.get("id") == b.get("profile_id") and (a.get("variant") or None) == b.get("variant")


def _profile_echo(request, item):
    try:
        doc, revision = request.app.state.profiles.get(item["profile_id"])
        built = build_profile(doc, item["variant"], validated=True)
        built.revision = revision
        return profile_echo(built)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, f"기체 또는 형상 변형을 읽을 수 없습니다: {exc}") from exc


def _bounded_config(config):
    if not isinstance(config, dict):
        raise HTTPException(422, "설계 설정이 필요합니다")
    allowed = {"gain_tables", "scas", "autopilot", "with_schedule", "with_limiter", "constants"}
    if set(config) - allowed:
        raise HTTPException(422, "지원하지 않는 설계 설정이 있습니다")
    if not any(config.get(k) for k in ("gain_tables", "scas", "autopilot", "constants")):
        raise HTTPException(422, "저장할 게인 또는 제어 설정이 없습니다")
    for key in ("gain_tables", "scas", "autopilot", "constants"):
        if config.get(key) is not None and not isinstance(config[key], dict):
            raise HTTPException(422, f"{key} 설정은 객체여야 합니다")
    for key in ("with_schedule", "with_limiter"):
        if key in config and not isinstance(config[key], bool):
            raise HTTPException(422, f"{key} 설정은 참/거짓이어야 합니다")
    try:
        serialized = json.dumps(config, allow_nan=False)
    except (TypeError, ValueError):
        raise HTTPException(422, "설계 설정은 유한한 JSON 값이어야 합니다") from None
    if len(serialized) > 1_000_000:
        raise HTTPException(422, "설계 설정이 너무 큽니다")
    try:
        tables = {name: (PolyTableIn if value.get("kind") == "poly" else TableIn).model_validate(value)
                  for name, value in (config.get("gain_tables") or {}).items()}
        build_gain_tables(tables)
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise HTTPException(422, f"게인 표를 읽을 수 없습니다: {exc}") from exc
    return copy.deepcopy(config)


@router.get("/design-entities")
def list_entities(request: Request, profile_id: str | None = None, variant: str | None = None):
    return request.app.state.design_entities.list(profile_id, variant)


@router.post("/design-entities", status_code=201)
def create_entity(req: CreateIn, request: Request):
    if not req.name.strip():
        raise HTTPException(422, "설계안 이름을 입력하세요")
    _profile_echo(request, req.model_dump())
    return request.app.state.design_entities.create(req.profile_id, req.variant, req.name.strip())


@router.get("/design-entities/{entity_id}")
def get_entity(entity_id: str, request: Request):
    return _entity(request, entity_id)


@router.post("/design-entities/{entity_id}/versions", status_code=201)
def add_version(entity_id: str, req: VersionIn, request: Request):
    item = _entity(request, entity_id)
    if req.expected_count != len(item["versions"]):
        raise HTTPException(409, "설계안이 그사이 바뀌었습니다. 다시 불러와 저장하세요")
    if req.parent_version is not None and req.parent_version > req.expected_count:
        raise HTTPException(422, "기존 설계 버전만 선행 버전으로 지정할 수 있습니다")
    basis_version = next((version["number"] for version in item["versions"]
        if any(evaluation["result_id"] == req.based_on_evaluation_id
               for evaluation in version["evaluations"])), None)
    if req.based_on_evaluation_id and basis_version is None:
        raise HTTPException(422, "이 설계안에 연결된 평가만 후속 설계의 근거로 지정할 수 있습니다")
    if basis_version is not None and req.parent_version not in (None, basis_version):
        raise HTTPException(422, "근거 평가와 선행 설계 버전이 다릅니다")
    improved = None
    if req.mode == "improvement":
        if not req.improvement_result_id or req.config is not None:
            raise HTTPException(422, "개선 실행 결과를 지정하세요")
        body = _result(request, req.improvement_result_id, "influence_improve")
        candidates = body.get("candidates") or []
        if body.get("aborted") or req.candidate_index >= len(candidates):
            raise HTTPException(422, "완료된 개선 후보가 아닙니다")
        improved = candidates[req.candidate_index]
        if not improved.get("accepted") or improved.get("unchanged"):
            raise HTTPException(422, "목표와 하드 기준을 만족한 후보만 저장할 수 있습니다")
        verified = _result(request, improved["evaluation_id"], "influence_evaluate")
        if (verified.get("aggregate") or {}).get("hard_fail") is not False:
            raise HTTPException(409, "연결된 실측 평가가 하드 기준을 만족하지 않습니다")
        echo = body.get("profile") or {}
        if not _same_profile(echo, item) or echo.get("fingerprint") != _profile_echo(request, item).get("fingerprint"):
            raise HTTPException(409, "개선 실행 이후 기체 기준이 변경됐습니다")
        config = _bounded_config(improved["config"])
        source = {"kind": "improvement", "result_id": req.improvement_result_id,
                  "candidate_index": req.candidate_index, "sweep_id": improved["sweep_id"]}
        auto_summary = {"goals": improved["goals"], "criteria_echo": body.get("criteria_echo")}
    elif req.mode == "auto":
        if not req.auto_result_id or req.config is not None:
            raise HTTPException(422, "자동 설계 결과 ID 하나를 지정하세요")
        body = _result(request, req.auto_result_id, "auto_design")
        echo = body.get("profile") or {}
        if not _same_profile(echo, item):
            raise HTTPException(409, "설계 결과의 기체·형상 변형이 설계안과 다릅니다")
        export = body.get("gain_export") or {}
        config = _bounded_config({"gain_tables": export.get("tables_resampled") or {},
                                  "constants": export.get("constants") or {}})
        source = {"kind": "auto", "result_id": req.auto_result_id}
        auto_summary = {"status": body.get("status"), "criteria_echo": body.get("criteria_echo"),
                        "trim_reuse": body.get("trim_reuse")}
    elif req.mode == "manual":
        if req.auto_result_id:
            raise HTTPException(422, "수동 버전에는 자동 설계 결과 ID를 지정하지 않습니다")
        config = _bounded_config(req.config)
        echo = _profile_echo(request, item)
        source = {"kind": "manual"}
        auto_summary = None
    else:
        raise HTTPException(422, "설계 방식은 auto, manual 또는 improvement이어야 합니다")
    version = {"config": config, "profile": echo, "source": source, "note": req.note,
               "based_on_evaluation_id": req.based_on_evaluation_id,
               "parent_version": req.parent_version or basis_version or (req.expected_count or None),
               "auto_summary": auto_summary}
    try:
        saved = request.app.state.design_entities.append_version(entity_id, req.expected_count, version)
        if improved:
            request.app.state.design_entities.attach_evaluation(entity_id, req.expected_count + 1,
                {"result_id": improved["evaluation_id"], "profile": echo,
                 "criteria_echo": verified.get("criteria_echo"), "hard_fail": False, "hard_fails": 0})
            return request.app.state.design_entities.get(entity_id)
        return saved
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


def _equal(a, b):
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def _evaluation_matches(request, item, number, version, evaluation):
    evaluated = evaluation.get("design_input")
    if not isinstance(evaluated, dict):
        return False
    echo = evaluation.get("profile") or {}
    saved = version["config"]
    explicit_tables = evaluated.get("gain_tables")
    if explicit_tables is None:
        try:
            doc, _ = request.app.state.profiles.get(echo["id"], echo["revision"])
            built = build_profile(doc, echo.get("variant"), validated=True)
        except (KeyError, ValueError):
            return False
        if built.fingerprint != echo.get("fingerprint"):
            return False
        gain_tables = built.doc["law"].get("gain_tables") or {}
        provenance = gain_tables.get("provenance") or {}
        if not ((provenance.get("source") == "design_entity"
                 and provenance.get("entity_id") == item["id"]
                 and provenance.get("version") == number)
                or (provenance.get("source") == "auto_design"
                    and provenance.get("result_id") == version["source"].get("result_id"))):
            return False
        actual_tables = gain_tables.get("tables")
    else:
        if echo.get("fingerprint") != version["profile"].get("fingerprint"):
            return False
        actual_tables = explicit_tables
    if not _equal(actual_tables or {}, saved.get("gain_tables") or {}):
        return False
    # Extra overrides change the evaluated controller, even if its table is unchanged.
    for key in ("scas", "autopilot", "with_schedule", "with_limiter"):
        if not _equal(evaluated.get(key), saved.get(key)):
            return False
    # Auto-design constants are not reconstructable from a table-only evaluation.
    if saved.get("constants"):
        return False
    return True


@router.post("/design-entities/{entity_id}/versions/{number}/evaluations", status_code=201)
def attach_evaluation(entity_id: str, number: int, req: EvaluationIn, request: Request):
    item = _entity(request, entity_id)
    if not 1 <= number <= len(item["versions"]):
        raise HTTPException(404, "설계 버전 없음")
    version = item["versions"][number - 1]
    body = _result(request, req.result_id, "influence_evaluate")
    echo = body.get("profile") or {}
    if not _same_profile(echo, item) or not _evaluation_matches(request, item, number, version, body):
        raise HTTPException(409, "평가한 기체·게인 설정이 이 설계 버전과 다릅니다")
    aggregate = body.get("aggregate") or {}
    evaluation = {"result_id": req.result_id, "profile": echo,
                  "criteria_echo": body.get("criteria_echo"),
                  "hard_fail": aggregate.get("hard_fail"),
                  "hard_fails": len(aggregate.get("hard_fails") or [])}
    return request.app.state.design_entities.attach_evaluation(entity_id, number, evaluation)


@router.post("/design-entities/{entity_id}/versions/{number}/artifacts", status_code=201)
def attach_artifact(entity_id: str, number: int, req: EvaluationIn, request: Request):
    item = _entity(request, entity_id)
    if not 1 <= number <= len(item["versions"]):
        raise HTTPException(404, "설계 버전 없음")
    body = _result(request, req.result_id, "trim_batch")
    echo = body.get("profile") or {}
    saved = item["versions"][number - 1]["profile"]
    if not _same_profile(echo, item) or echo.get("fingerprint") != saved.get("fingerprint"):
        raise HTTPException(409, "트림 결과의 기체 기준이 설계 버전과 다릅니다")
    artifact = {"kind": "trim_batch", "result_id": req.result_id, "profile": echo,
                "trim_reuse": body.get("trim_reuse"), "summary": body.get("summary")}
    return request.app.state.design_entities.attach_artifact(entity_id, number, artifact)


@router.post("/design-entities/{entity_id}/branch", status_code=201)
def branch_entity(entity_id: str, req: BranchIn, request: Request):
    parent = _entity(request, entity_id)
    if not 1 <= req.number <= len(parent["versions"]):
        raise HTTPException(404, "분기할 설계 버전 없음")
    child = request.app.state.design_entities.create(parent["profile_id"], parent["variant"],
        req.name.strip(), {"entity_id": entity_id, "version": req.number})
    version = copy.deepcopy(parent["versions"][req.number - 1])
    version.pop("number", None)
    version.pop("created_at", None)
    version.pop("evaluations", None)
    version.pop("artifacts", None)
    version.pop("adopted_revision", None)
    version["based_on_evaluation_id"] = None
    version["parent_version"] = None
    return request.app.state.design_entities.append_version(child["id"], 0, version)


@router.post("/design-entities/{entity_id}/versions/{number}/apply")
def apply_version(entity_id: str, number: int, req: ApplyIn, request: Request):
    item = _entity(request, entity_id)
    if not 1 <= number <= len(item["versions"]):
        raise HTTPException(404, "설계 버전 없음")
    if item["variant"] is not None:
        raise HTTPException(422, "형상 변형 설계는 기본 기체 문서에 반영할 수 없습니다")
    version = item["versions"][number - 1]
    config = version["config"]
    if not config.get("gain_tables") or any(config.get(k) for k in ("scas", "autopilot", "constants")):
        raise HTTPException(422, "문서 반영은 마하 게인 표만 가진 버전에서 가능합니다")
    if config.get("with_schedule") is False or config.get("with_limiter") is False:
        raise HTTPException(422, "스케줄 또는 리미터를 끈 버전은 문서에 반영할 수 없습니다")
    try:
        doc, revision = request.app.state.profiles.get(item["profile_id"])
    except (KeyError, ProfileUnreadable):
        raise HTTPException(404, "기체 문서 없음") from None
    if revision != req.base_revision:
        raise HTTPException(409, "기체 문서 리비전이 바뀌었습니다")
    built = build_profile(doc, validated=True)
    if built.fingerprint != version["profile"].get("fingerprint"):
        raise HTTPException(409, "설계 버전의 기준 기체와 현재 기체가 다릅니다")
    new = copy.deepcopy(doc)
    new["law"]["gain_tables"] = {"tables": copy.deepcopy(config["gain_tables"]),
        "provenance": {"source": "design_entity", "entity_id": entity_id, "version": number,
                       "base_revision": revision,
                       "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "basis_fingerprint": gain_tables_basis_fingerprint(built.doc)}}
    try:
        _, written = request.app.state.profiles.update(item["profile_id"], new, revision)
    except ProfileReadOnly as exc:
        raise HTTPException(403, str(exc)) from exc
    except ProfileConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.app.state.design_entities.mark_adopted(entity_id, number, written)
    return {"written": True, "revision": written, "entity_id": entity_id, "version": number}
