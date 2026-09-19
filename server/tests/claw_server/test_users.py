"""사용자 저장소 검증 — 해시 왕복, JSON 저장 CRUD·원자성, 관리자 시드.

PgUserStore는 외부 DB가 있어야 돌므로 $CLAW_TEST_DB_URL 없으면 skip —
폐쇄망 CI에서 자동 통과. 세션 서명은 test_sessions.py.
"""

import json
import os

import pytest

from claw_server.users import (
    JsonUserStore,
    UserError,
    UserExists,
    UserNotFound,
    ensure_admin,
    hash_password,
    make_user_store,
    new_record,
    verify_password,
)


# ── 비밀번호 해시 ──────────────────────────────────────────────


def test_password_roundtrip():
    h = hash_password("비밀번호1")
    assert h.startswith("scrypt$")
    assert verify_password("비밀번호1", h)
    assert not verify_password("다른것", h)


def test_password_salt_differs():
    assert hash_password("x") != hash_password("x")  # salt가 매번 다르다


def test_verify_broken_hash_is_false_not_500():
    for broken in ("", "plain", "scrypt$a$b$c$d$e", "md5$1$1$1$AA==$AA=="):
        assert verify_password("x", broken) is False


def test_old_params_still_verify():
    """자기기술 형식 — 파라미터를 올려도 옛 해시가 검증돼야 한다."""
    import base64, hashlib
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(b"pw", salt=salt, n=2**8, r=4, p=1, dklen=32)
    old = (f"scrypt${2**8}$4$1${base64.b64encode(salt).decode()}"
           f"${base64.b64encode(digest).decode()}")
    assert verify_password("pw", old)


# ── 레코드·아이디 규칙 ────────────────────────────────────────


def test_new_record_shape():
    r = new_record("kim_1", "pw")
    assert r["role"] == "user" and r["status"] == "pending"
    assert r["last_login"] is None and r["created_at"] > 0


def test_bad_username_rejected():
    for bad in ("", "한글", "a/b", "a" * 65, "a\nb"):
        with pytest.raises(UserError):
            new_record(bad, "pw")


# ── JsonUserStore ─────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path):
    return JsonUserStore(tmp_path / "users.json")


def test_json_crud(store):
    assert store.get("kim") is None and store.list() == []
    store.create(new_record("kim", "pw"))
    assert store.get("kim")["status"] == "pending"
    with pytest.raises(UserExists):
        store.create(new_record("kim", "pw2"))
    store.update("kim", status="active", role="admin")
    assert store.get("kim")["role"] == "admin"
    with pytest.raises(UserNotFound):
        store.update("none", status="active")
    store.delete("kim")
    assert store.get("kim") is None
    with pytest.raises(UserNotFound):
        store.delete("kim")


def test_update_rejects_unknown_fields(store):
    """허용목록 밖 필드는 거부 — PgUserStore가 열 이름을 SQL에 넣으므로 주입 방어선.
    assert가 아니라 명시 검사라 python -O에서도 유지된다(두 백엔드 공용 계약)."""
    store.create(new_record("kim", "pw"))
    # created_at은 실제 열이지만 update로는 못 바꾼다, is_admin은 아예 없는 필드, {}는 빈 갱신
    for bad in ({"is_admin": True}, {"created_at": 0.0}, {}):
        with pytest.raises(UserError):
            store.update("kim", **bad)
    # 허용 필드는 그대로 통과
    assert store.update("kim", status="active")["status"] == "active"


def test_json_list_ordered_by_created(store):
    a = new_record("a", "pw"); a["created_at"] = 2.0
    b = new_record("b", "pw"); b["created_at"] = 1.0
    store.create(a); store.create(b)
    assert [u["username"] for u in store.list()] == ["b", "a"]


def test_json_atomic_no_tmp_left(store, tmp_path):
    store.create(new_record("kim", "pw"))
    assert not list(tmp_path.glob("*.tmp"))  # tmp→rename 뒤처리
    # 파일이 실제 JSON으로 남는다 (재기동 영속)
    again = JsonUserStore(store.path)
    assert again.get("kim")["username"] == "kim"


def test_json_corrupt_file_raises(store):
    """깨진 users.json은 빈 목록 폴백이 아니라 예외 — 계정 소실이 조용히 지나가면 안 된다."""
    store.path.write_text("{보손", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        store.get("kim")


def test_ensure_admin_upserts(store):
    ensure_admin(store, "admin", "s1")
    assert store.get("admin")["role"] == "admin"
    assert verify_password("s1", store.get("admin")["pw_hash"])
    # 비번 교체·강등 복구 — 환경변수가 정본
    store.update("admin", status="rejected")
    ensure_admin(store, "admin", "s2")
    got = store.get("admin")
    assert got["status"] == "active" and verify_password("s2", got["pw_hash"])


def test_make_user_store_json_default(tmp_path):
    s = make_user_store("", tmp_path / "u.json")
    assert isinstance(s, JsonUserStore)


# ── PgUserStore (외부 DB 있을 때만) ───────────────────────────


@pytest.mark.skipif(not os.environ.get("CLAW_TEST_DB_URL"),
                    reason="CLAW_TEST_DB_URL 미설정 — 폐쇄망/로컬 기본")
def test_pg_crud_roundtrip():
    s = make_user_store(os.environ["CLAW_TEST_DB_URL"], None)
    try:
        s.delete("pg_test_kim")
    except UserNotFound:
        pass
    s.create(new_record("pg_test_kim", "pw"))
    with pytest.raises(UserExists):
        s.create(new_record("pg_test_kim", "pw"))
    assert s.update("pg_test_kim", status="active")["status"] == "active"
    assert s.get("pg_test_kim")["status"] == "active"
    s.delete("pg_test_kim")
    assert s.get("pg_test_kim") is None
