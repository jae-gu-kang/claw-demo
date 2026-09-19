"""세션 쿠키 서명 — stdlib HMAC만, 서버측 세션 없음.

토큰 = base64url(username|issued) "." hmac_sha256_hex. 쿠키에는 아이디·발급시각·
서명만 싣고 **role·status는 싣지 않는다** — 매 요청 UserStore에서 다시 읽어
관리자의 거절·삭제가 이미 발급된 쿠키에도 즉시 반영된다 (쿠키에 구우면 회수 불가).

시크릿은 $CLAW_SESSION_SECRET — 미설정이면 부팅마다 랜덤이라 재시작 시 전원
로그아웃된다 (로컬 무해, 공개 배포는 설정 권고 — render.yaml 주석).
"""

import base64
import hashlib
import hmac
import secrets
import time

COOKIE = "claw_session"
MAX_AGE = 14 * 24 * 3600  # 14일 — Set-Cookie Max-Age와 서버 검증이 같은 값을 쓴다


def secret_bytes(configured: str) -> bytes:
    return configured.encode("utf-8") if configured else secrets.token_bytes(32)


def _mac(payload: bytes, secret: bytes) -> str:
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def sign(username: str, secret: bytes, now: float | None = None) -> str:
    issued = time.time() if now is None else now
    payload = base64.urlsafe_b64encode(f"{username}|{issued}".encode("utf-8"))
    return f"{payload.decode('ascii')}.{_mac(payload, secret)}"


def verify(token: str, secret: bytes,
           now: float | None = None, max_age: float = MAX_AGE) -> str | None:
    """위조·만료·형식 오류 전부 None — 예외로 500을 내지 않는다."""
    try:
        payload, _, mac = token.rpartition(".")
        if not payload or not hmac.compare_digest(
            mac, _mac(payload.encode("ascii"), secret)
        ):
            return None
        username, _, issued = (
            base64.urlsafe_b64decode(payload.encode("ascii"))
            .decode("utf-8").rpartition("|")
        )
        age = (time.time() if now is None else now) - float(issued)
        if not username or not (0 <= age <= max_age):  # 시계 역행(미래 발급)도 불허
            return None
        return username
    except (ValueError, UnicodeDecodeError, TypeError):
        # TypeError: MAC 자리에 비ASCII가 오면 hmac.compare_digest가 던진다
        # (쿠키 헤더는 latin-1이라 payload는 ASCII여도 서명 자리는 비ASCII일 수 있다 —
        # /api/auth/me가 관대한 쿠키 파서라 여기까지 도달하면 위조가 아니라 500이 된다)
        return None
