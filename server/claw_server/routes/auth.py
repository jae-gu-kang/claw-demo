"""인증 라우트 — 로그인·로그아웃·가입 신청·내 정보 (세션 모드 전용, auth.py 머리말).

이 라우트들은 SessionAuthProtect의 면제 목록에 있다(/auth/logout만 예외 —
로그아웃은 인증된 자만 의미가 있다). 세션 모드가 아니면 로그인·가입은 404:
기능이 "실패"한 게 아니라 "없다" — llm.py의 백엔드 미설정 처리와 같은 태도.

/auth/me는 모든 모드에서 200이다 — 웹 부팅 게이트(web/js/views/login.js)가
"로그인 화면을 세울 것인가"를 이 응답 하나로 판단한다.
"""

import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from claw_server import sessions
from claw_server.users import (
    UserError, UserExists, hash_password, new_record, verify_password,
)

router = APIRouter(tags=["auth"])  # prefix 없이 전체 경로 — lib/profile.js 라우트 분류 가드가 데코레이터 경로를 그대로 읽는다

# 없는 아이디에도 scrypt를 한 번 돌려 응답 시간을 맞추는 더미 해시 — 아래 login 참조.
# 모듈 로드 시 한 번 계산(부팅당 scrypt 1회, 무시할 비용)
_DUMMY_HASH = hash_password("timing-equalizer")


def public(record: dict) -> dict:
    """응답용 사영 — pw_hash는 어떤 응답에도 싣지 않는다."""
    return {k: record[k] for k in
            ("username", "role", "status", "created_at", "last_login")}


def _session_only(request: Request):
    if getattr(request.app.state, "auth_mode", "open") != "session":
        raise HTTPException(status_code=404, detail="세션 모드가 아니다 — $CLAW_ADMIN_PASSWORD 미설정")
    return request.app.state


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


@router.post("/auth/login")
def login(req: Credentials, request: Request) -> JSONResponse:
    state = _session_only(request)
    record = state.users.get(req.username)
    # 비번을 먼저 본다 — 비번도 모르는 쪽에 pending/rejected(계정 존재)를 말하지 않는다.
    # 가입 409가 이미 존재를 노출하지만, 로그인 경로만큼은 탐침 재료를 늘리지 않는다.
    # 없는 아이디에도 **더미 해시로 verify를 돌려** scrypt 시간을 맞춘다 — 안 그러면
    # record is None이 즉시 401을 반환해 응답 시간 차로 아이디 존재 여부가 샌다.
    ok = verify_password(req.password, record["pw_hash"] if record is not None else _DUMMY_HASH)
    if record is None or not ok:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 맞지 않는다")
    if record["status"] != "active":
        raise HTTPException(status_code=403, detail={
            "code": record["status"],
            "message": ("가입 승인 대기 중이다 — 관리자 승인 후 로그인된다"
                        if record["status"] == "pending" else "가입이 거절된 계정이다"),
        })
    now = time.time()
    state.users.update(req.username, last_login=now)
    state.active[req.username] = now
    resp = JSONResponse({"username": record["username"], "role": record["role"]})
    # Secure 플래그는 안 단다 — 프록시 뒤(uvicorn이 http로 보는 배포)에서 켜면
    # 쿠키가 아예 안 붙는다. HttpOnly+SameSite=Lax가 실효 방어선.
    resp.set_cookie(sessions.COOKIE, sessions.sign(req.username, state.session_secret),
                    max_age=sessions.MAX_AGE, httponly=True, samesite="lax", path="/")
    return resp


@router.post("/auth/logout")
def logout(request: Request) -> JSONResponse:
    state = _session_only(request)
    user = getattr(request.state, "user", None)  # 미들웨어가 실어 준 요청자
    if user is not None:
        state.active.pop(user["username"], None)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(sessions.COOKIE, path="/")
    return resp


@router.get("/auth/me")
def me(request: Request) -> dict:
    mode = getattr(request.app.state, "auth_mode", "open")
    if mode != "session":
        return {"mode": mode, "user": None}
    # 이 경로는 면제라 미들웨어가 검사하지 않았다 — 같은 검사를 여기서 한다
    state = request.app.state
    username = sessions.verify(request.cookies.get(sessions.COOKIE, ""),
                               state.session_secret)
    record = state.users.get(username) if username else None
    if record is None or record["status"] != "active":
        return {"mode": "session", "user": None}
    return {"mode": "session", "user": public(record)}


class SignupIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=4, description="최소 4자")


@router.post("/auth/signup", status_code=201)
def signup(req: SignupIn, request: Request) -> dict:
    state = _session_only(request)
    try:
        record = new_record(req.username, req.password)  # pending으로 태어난다
        state.users.create(record)
    except UserExists:
        raise HTTPException(status_code=409, detail="이미 있는 아이디다")
    except UserError as e:  # 아이디 형식 위반 — 422로 번역
        raise HTTPException(status_code=422, detail=str(e))
    return {"username": record["username"], "status": record["status"]}
