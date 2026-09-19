"""접근 보호 — 두 방식이 공존하고 환경변수가 하나를 고른다 (옵트인).

    $CLAW_ADMIN_PASSWORD 설정   → SessionAuthProtect (계정·쿠키 — 로그인 화면·회원관리)
    없고 $CLAW_ACCESS_PASSWORD  → BasicAuthProtect   (공용 비밀번호 하나 — 기존)
    둘 다 없음                  → 무보호 (로컬·Codespaces 기본 동작)

모드 선택은 create_app이 한다 — "존재=선택"이라 모순 상태가 표현되지 않는다.

둘 다 순수 ASGI 클래스여야 한다 — BaseHTTPMiddleware(@app.middleware)는 websocket
scope를 검사 없이 통과시켜 /api/ws/jobs/{id}가 무방비로 남는다.
"""

import base64
import hmac
import json
import time

from starlette.requests import cookie_parser

from . import sessions


class BasicAuthProtect:
    """http·websocket 전부에 Basic 자격 요구 — 아이디는 무시, 비밀번호만 비교.

    /api/health는 면제: 배포 플랫폼 헬스체크가 자격 없이 온다.
    websocket은 accept 전에 close → 서버가 핸드셰이크를 403으로 거절하고,
    웹 UI는 api.js의 onclose→poll 폴백으로 (자격 실린) REST 폴링으로 강등된다.
    """

    def __init__(self, app, password: str):
        self.app = app
        self._password = password.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):  # lifespan 등
            await self.app(scope, receive, send)
            return
        if scope["path"] == "/api/health" or self._authorized(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()  # websocket.connect — 수신 후 거절이 ASGI 규약
            await send({"type": "websocket.close", "code": 1008})
            return
        body = "인증 필요 — 비밀번호를 입력할 것 (아이디는 무엇이든)".encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"www-authenticate", b'Basic realm="CLAW", charset="UTF-8"'),
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    def _authorized(self, scope) -> bool:
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                break
        else:
            return False
        scheme, _, cred = value.partition(b" ")
        if scheme.lower() != b"basic":
            return False
        try:
            decoded = base64.b64decode(cred.strip(), validate=True)
        except ValueError:  # binascii.Error 포함 — 깨진 자격은 그냥 불허
            return False
        _, _, password = decoded.partition(b":")
        return hmac.compare_digest(password, self._password)  # 타이밍 안전 비교


class SessionAuthProtect:
    """세션 쿠키 인증 — /api/* 만 게이트, 정적 파일은 개방.

    정적을 여는 이유: 로그인 화면 자체가 js/css·블록도 SVG 재료를 먹는다 —
    데이터는 전부 /api 뒤에 있으므로 껍데기 공개는 코드 공개일 뿐이다.
    면제: /api/health(배포 헬스체크), /api/auth/*(로그인 전에 불러야 하는 것들).

    실패 응답에 WWW-Authenticate를 싣지 않는다 — 실으면 브라우저 기본 Basic
    팝업이 자체 로그인 화면을 가린다. 401 JSON을 받은 web/js/api.js가
    claw:auth-required 이벤트로 게이트를 다시 세운다.

    websocket은 BasicAuthProtect와 동일: 쿠키가 핸드셰이크 헤더에 실리므로
    같은 검사를 하고, 불허면 receive() 후 close 1008 (api.js가 REST 폴링 강등).
    """

    EXEMPT = ("/api/health", "/api/auth/login", "/api/auth/signup", "/api/auth/me")

    def __init__(self, app, users, secret: bytes, active: dict):
        self.app = app
        self._users = users
        self._secret = secret
        self._active = active  # username → 마지막 요청 시각. --workers 1 전제
        #                        (JobManager와 같은 프로세스 메모리 — 접속 현황 재료)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):  # lifespan 등
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if not path.startswith("/api") or path in self.EXEMPT:
            await self.app(scope, receive, send)
            return
        user = self._user(scope)
        if user is not None:
            # Starlette request.state가 읽는 자리 — 라우트가 요청자를 안다
            scope.setdefault("state", {})["user"] = user
            self._active[user["username"]] = time.time()
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()  # websocket.connect — 수신 후 거절이 ASGI 규약
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": "인증 필요 — 로그인할 것"}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    def _user(self, scope) -> dict | None:
        """쿠키 → 서명 검증 → 저장소 재조회(active만) — 거절·삭제 즉시 반영."""
        for name, value in scope.get("headers", []):
            if name == b"cookie":
                break
        else:
            return None
        # Starlette와 같은 관대한 파서 — http.cookies.SimpleCookie는 엄격해서 헤더 안
        # 남의 malformed 쿠키 하나에 우리 claw_session까지 함께 버릴 수 있다. me()가
        # request.cookies(=이 파서)를 쓰므로 미들웨어도 같은 파서를 써 둘이 어긋나지 않게 한다
        token = cookie_parser(value.decode("latin-1")).get(sessions.COOKIE)
        if not token:
            return None
        username = sessions.verify(token, self._secret)
        if username is None:
            return None
        record = self._users.get(username)
        if record is None or record.get("status") != "active":
            return None
        return record
