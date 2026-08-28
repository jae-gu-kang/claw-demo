"""접근 보호 — 공용 비밀번호 하나짜리 HTTP Basic Auth (옵트인).

공개 URL 배포(무료 PaaS 등)에서 최소한의 문턱. $CLAW_ACCESS_PASSWORD가 설정된
경우에만 create_app이 등록하므로 로컬·Codespaces 기본 동작은 무영향.

순수 ASGI 클래스여야 한다 — BaseHTTPMiddleware(@app.middleware)는 websocket
scope를 검사 없이 통과시켜 /api/ws/jobs/{id}가 무방비로 남는다.
"""

import base64
import hmac


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
