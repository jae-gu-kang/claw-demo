"""관리자 라우트 — 회원관리·접속 현황·서버 데이터 (세션 모드 전용).

전 라우트가 require_admin 의존성 뒤에 있다. 미들웨어(SessionAuthProtect)가
이미 인증을 끝냈으므로 여기서는 요청자의 role만 본다 — 세션 모드가 꺼져
미들웨어가 없으면 request.state.user 자체가 없어 403이다 (개방 서버에서
관리자 API가 무방비로 열리는 사고 방지).

접속 현황의 "지금 접속 중"은 app.state.active(username → 마지막 요청 시각)의
최근 5분 필터다 — --workers 1 전제의 프로세스 메모리(JobManager와 동일,
render.yaml startCommand가 고정). 재시작하면 비지만 로그인 시각(last_login)은
저장소에 남는다.
"""

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from claw_server.routes.auth import public
from claw_server.users import UserError, UserExists, UserNotFound, hash_password, new_record

router = APIRouter(tags=["admin"])  # prefix 없이 전체 경로 — lib/profile.js 라우트 분류 가드가 데코레이터 경로를 그대로 읽는다

ONLINE_WINDOW_S = 300  # "접속 중" = 최근 5분 내 요청


def require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if user is None or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="관리자 전용")
    return user


@router.get("/admin/users")
def list_users(request: Request, admin=Depends(require_admin)) -> list:
    return [public(u) for u in request.app.state.users.list()]


class CreateUserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=4)
    role: Literal["admin", "user"] = "user"


@router.post("/admin/users", status_code=201)
def create_user(req: CreateUserIn, request: Request, admin=Depends(require_admin)) -> dict:
    try:  # 관리자 직접 발급은 승인 절차가 곧 본인이다 — 즉시 active
        record = new_record(req.username, req.password, role=req.role, status="active")
        request.app.state.users.create(record)
    except UserExists:  # UserError의 하위 — 반드시 먼저 잡는다
        raise HTTPException(status_code=409, detail="이미 있는 아이디다")
    except UserError as e:  # 아이디 문자 규칙 위반(_ID_RE) — Pydantic 길이만 봐 통과한 이름
        raise HTTPException(status_code=422, detail=str(e))
    return public(record)


class PatchUserIn(BaseModel):
    status: Literal["pending", "active", "rejected"] | None = None
    role: Literal["admin", "user"] | None = None
    password: str | None = Field(default=None, min_length=4)


def _guard_last_admin(users, name: str, *, to_role=None, to_status=None, delete=False):
    """유일한 active 관리자를 강등·거절·삭제하면 관리 기능 전체가 잠긴다 — 409.

    시드 관리자는 재기동(ensure_admin)으로 살아나지만, 그때까지의 잠김도
    사고다 — 표현 가능한 상태에서 막는다."""
    target = users.get(name)
    if target is None or target["role"] != "admin" or target["status"] != "active":
        return  # 관리자 힘을 잃을 대상이 아니다
    losing = delete or (to_role == "user") or (to_status in ("pending", "rejected"))
    if not losing:
        return
    actives = [u for u in users.list()
               if u["role"] == "admin" and u["status"] == "active"]
    if len(actives) <= 1:
        raise HTTPException(status_code=409, detail="유일한 관리자다 — 먼저 다른 관리자를 두어야 한다")


@router.patch("/admin/users/{name}")
def patch_user(name: str, req: PatchUserIn, request: Request,
               admin=Depends(require_admin)) -> dict:
    users = request.app.state.users
    fields = {}
    if req.status is not None:
        fields["status"] = req.status
    if req.role is not None:
        fields["role"] = req.role
    if req.password is not None:
        fields["pw_hash"] = hash_password(req.password)
    if not fields:
        raise HTTPException(status_code=422, detail="바꿀 것이 없다")
    _guard_last_admin(users, name, to_role=req.role, to_status=req.status)
    try:
        record = users.update(name, **fields)
    except UserNotFound:
        raise HTTPException(status_code=404, detail=f"없는 아이디: {name}")
    if record["status"] != "active":  # 거절·보류 즉시 "접속 중"에서도 내린다
        request.app.state.active.pop(name, None)
    return public(record)


@router.delete("/admin/users/{name}")
def delete_user(name: str, request: Request, admin=Depends(require_admin)) -> dict:
    if name == admin["username"]:
        raise HTTPException(status_code=409, detail="자기 계정은 지울 수 없다 — 다른 관리자에게 부탁할 것")
    users = request.app.state.users
    _guard_last_admin(users, name, delete=True)
    try:
        users.delete(name)
    except UserNotFound:
        raise HTTPException(status_code=404, detail=f"없는 아이디: {name}")
    request.app.state.active.pop(name, None)
    return {"ok": True}


@router.get("/admin/sessions")
def sessions_overview(request: Request, admin=Depends(require_admin)) -> dict:
    now = time.time()
    active = request.app.state.active
    online = sorted(
        ({"username": u, "last_seen": t} for u, t in active.items()
         if now - t <= ONLINE_WINDOW_S),
        key=lambda s: s["last_seen"], reverse=True)
    return {"online": online, "window_s": ONLINE_WINDOW_S,
            "users": [public(u) for u in request.app.state.users.list()]}


@router.get("/admin/data")
def data_overview(request: Request, admin=Depends(require_admin)) -> dict:
    store = request.app.state.store
    metas = store.list()
    total = 0
    for m in metas:
        rid = str(m.get("id", ""))
        for suffix in (".json", ".meta.json"):
            p = store.root / f"{rid}{suffix}"
            try:
                total += p.stat().st_size
            except OSError:
                pass  # 목록과 파일 사이의 경합 — 크기 합은 안내 수치일 뿐
    return {"results": len(metas), "bytes": total,
            "limit": store.limit, "newest": metas[0] if metas else None}


class PruneIn(BaseModel):
    keep: int = Field(ge=0, description="남길 최신 결과 개수")


@router.post("/admin/data/prune")
def prune_data(req: PruneIn, request: Request, admin=Depends(require_admin)) -> dict:
    store = request.app.state.store
    removed = 0
    for old in store.list()[req.keep:]:  # created 내림차순 → 초과분 = 오래된 것
        rid = str(old.get("id", ""))
        try:
            store.delete(rid)
        except ValueError:
            continue  # 외부 유입 메타 방어 — save()의 상한 삭제와 같은 태도
        removed += 1
    return {"removed": removed, "results": len(store.list())}
