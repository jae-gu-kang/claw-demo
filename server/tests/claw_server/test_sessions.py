"""세션 쿠키 서명 검증 — 왕복, 위조·쓰레기 입력, 만료·시계 역행."""

from claw_server import sessions

SECRET = b"unit-test-secret"


def test_session_roundtrip():
    tok = sessions.sign("kim", SECRET, now=1000.0)
    assert sessions.verify(tok, SECRET, now=1000.0 + 60) == "kim"


def test_session_forgery_and_garbage_none():
    tok = sessions.sign("kim", SECRET, now=1000.0)
    assert sessions.verify(tok, b"other-secret", now=1060.0) is None
    head, _, _ = tok.rpartition(".")
    assert sessions.verify(head + ".deadbeef", SECRET, now=1060.0) is None
    for garbage in ("", ".", "no-dot", "잘못.된것", tok + "x"):
        assert sessions.verify(garbage, SECRET, now=1060.0) is None


def test_session_nonascii_mac_is_none_not_typeerror():
    """서명 자리에 비ASCII가 오면 hmac.compare_digest가 TypeError를 던진다 — 위조로
    처리해야지 500이 되면 안 된다. payload는 ASCII base64라 payload 인코딩 단계를
    통과하고 MAC 비교에서만 걸린다("잘못.된것"은 payload 쪽에서 먼저 걸려 이 경로를 못 판다).
    쿠키 헤더가 latin-1이라 실제로 도달하는 입력이다(/api/auth/me — routes/auth.py)."""
    assert sessions.verify("dGVzdA.한글", SECRET) is None
    assert sessions.verify("dGVzdA.café", SECRET) is None


def test_session_expiry():
    tok = sessions.sign("kim", SECRET, now=1000.0)
    assert sessions.verify(tok, SECRET, now=1000.0 + sessions.MAX_AGE + 1) is None
    # 미래 발급(시계 역행) 토큰도 불허
    future = sessions.sign("kim", SECRET, now=99999.0)
    assert sessions.verify(future, SECRET, now=1000.0) is None


def test_session_username_intact():
    tok = sessions.sign("Kim_-1", SECRET, now=1.0)
    assert sessions.verify(tok, SECRET, now=2.0) == "Kim_-1"


def test_secret_bytes():
    assert sessions.secret_bytes("abc") == b"abc"  # 설정값이 정본
    a, b = sessions.secret_bytes(""), sessions.secret_bytes("")
    assert a != b and len(a) >= 32  # 미설정 = 부팅마다 랜덤 (재시작 시 전원 로그아웃)
