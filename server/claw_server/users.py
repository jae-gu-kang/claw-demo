"""사용자 저장소 — 회원 계정·비밀번호 해시 (세션 모드 전용, 옵트인).

레코드: {username, pw_hash, role: admin|user, status: pending|active|rejected,
created_at, last_login}. 자가 가입은 pending으로 태어나 관리자 승인(active)을
기다린다. 저장 백엔드는 둘 — 배포 형편이 갈라서:

    JsonUserStore  users.json 단일 파일 — 로컬·폐쇄망 기본 (디스크 영속).
    PgUserStore    $CLAW_DB_URL (평범한 Postgres URL, 제공자 무관) — 공개 PaaS 배포용.
                   무료 티어 디스크는 재배포마다 비워져 JSON이면 계정이 사라진다.

psycopg는 optional extra [db]로만 설치된다 — 기본 설치·폐쇄망 wheelhouse 불변.
URL이 있는데 psycopg가 없으면 조용한 폴백 대신 기동 실패로 크게 드러낸다
(routes/llm.py의 "존재=선택, 모순=기동 실패" 규율과 동일).

비밀번호는 hashlib.scrypt (stdlib, 의존성 0) — `scrypt$n$r$p$salt$hash` 자기기술
형식이라 파라미터를 올려도 옛 해시가 그대로 검증된다.
"""

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path

from .store import _ID_RE  # 같은 이름 규칙 — 경로 조작 차단 겸 쿠키·URL 안전 문자만

ROLES = ("admin", "user")
STATUSES = ("pending", "active", "rejected")
# update()로 바꿀 수 있는 열 — PgUserStore가 열 이름을 SQL에 f-string으로 넣으므로
# 이 허용목록이 주입 방어선이다. assert가 아니라 명시 검사여야 python -O에서도 산다.
UPDATABLE = frozenset({"pw_hash", "role", "status", "last_login"})


def _check_update_fields(fields: dict) -> None:
    bad = set(fields) - UPDATABLE
    if not fields or bad:
        raise UserError(f"허용되지 않은 갱신 필드: {sorted(bad) or '(없음)'}")

# scrypt 기본 파라미터 — 대화형 로그인 지연(수십 ms)과 서버 부하의 절충
_N, _R, _P = 2**14, 8, 1


class UserError(Exception):
    """저장소 위반 — 라우트가 4xx로 번역한다."""


class UserExists(UserError):
    pass


class UserNotFound(UserError):
    pass


def check_username(name) -> str:
    if not isinstance(name, str) or not _ID_RE.fullmatch(name):
        raise UserError(f"잘못된 아이디: {name!r} — 영문·숫자·_- 1~64자")
    return name


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32
    )
    b64 = base64.b64encode
    return (f"scrypt${_N}${_R}${_P}"
            f"${b64(salt).decode('ascii')}${b64(digest).decode('ascii')}")


def verify_password(password: str, stored: str) -> bool:
    """형식 오류·위조 전부 False — 예외로 500을 내지 않는다."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        want = base64.b64decode(digest)
        got = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt),
            n=int(n), r=int(r), p=int(p), dklen=len(want),
        )
        return hmac.compare_digest(got, want)
    except (ValueError, TypeError):
        return False


def new_record(username: str, password: str, *,
               role: str = "user", status: str = "pending") -> dict:
    assert role in ROLES and status in STATUSES
    return {
        "username": check_username(username),
        "pw_hash": hash_password(password),
        "role": role,
        "status": status,
        "created_at": time.time(),
        "last_login": None,
    }


class JsonUserStore:
    """단일 파일 저장 — store.py의 tmp→rename 원자 쓰기, profiles.py의 Lock 선례.

    파일이 깨져 있으면 그대로 예외를 낸다 — 로그인 전원이 걸린 파일이라
    조용히 빈 목록으로 폴백하면 계정 소실이 소리 없이 지나간다.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, users: dict) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(users, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        tmp.replace(self.path)

    def get(self, username: str) -> dict | None:
        return self._load().get(username)

    def list(self) -> list:
        return sorted(self._load().values(), key=lambda u: u.get("created_at", 0.0))

    def create(self, record: dict) -> None:
        with self._lock:
            users = self._load()
            if record["username"] in users:
                raise UserExists(record["username"])
            users[record["username"]] = record
            self._save(users)

    def update(self, username: str, **fields) -> dict:
        _check_update_fields(fields)  # Pg와 같은 허용목록 — 두 백엔드가 같은 계약을 지킨다
        with self._lock:
            users = self._load()
            if username not in users:
                raise UserNotFound(username)
            users[username].update(fields)
            self._save(users)
            return users[username]

    def delete(self, username: str) -> None:
        with self._lock:
            users = self._load()
            if username not in users:
                raise UserNotFound(username)
            del users[username]
            self._save(users)


class PgUserStore:
    """Postgres 저장 — 작업당 단명 커넥션(autocommit). 트래픽이 로그인·관리
    수준이라 풀이 필요 없고, 커넥션을 쥐고 있지 않아 무료 티어 유휴 끊김과도
    무관하다. 테이블은 첫 기동에 만들어진다 — 이 시점에 URL 오류도 드러난다."""

    _COLS = "username, pw_hash, role, status, created_at, last_login"

    def __init__(self, url: str):
        try:
            import psycopg  # 지연 import — [db] 미설치 폐쇄망에서 JSON 경로가 죽으면 안 된다
        except ImportError as e:
            raise RuntimeError(
                "CLAW_DB_URL이 설정됐지만 psycopg가 없다 — pip install -e 'server[db]'"
            ) from e
        self._pg = psycopg
        self.url = url
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS claw_users (
                       username   TEXT PRIMARY KEY,
                       pw_hash    TEXT NOT NULL,
                       role       TEXT NOT NULL,
                       status     TEXT NOT NULL,
                       created_at DOUBLE PRECISION NOT NULL,
                       last_login DOUBLE PRECISION
                   )"""
            )

    def _conn(self):
        return self._pg.connect(self.url, autocommit=True)

    @staticmethod
    def _record(row) -> dict:
        username, pw_hash, role, status, created_at, last_login = row
        return {"username": username, "pw_hash": pw_hash, "role": role,
                "status": status, "created_at": created_at, "last_login": last_login}

    def get(self, username: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {self._COLS} FROM claw_users WHERE username = %s", (username,)
            ).fetchone()
        return self._record(row) if row else None

    def list(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {self._COLS} FROM claw_users ORDER BY created_at"
            ).fetchall()
        return [self._record(r) for r in rows]

    def create(self, record: dict) -> None:
        with self._conn() as conn:
            try:
                conn.execute(
                    f"INSERT INTO claw_users ({self._COLS}) VALUES (%s,%s,%s,%s,%s,%s)",
                    (record["username"], record["pw_hash"], record["role"],
                     record["status"], record["created_at"], record["last_login"]),
                )
            except self._pg.errors.UniqueViolation:
                raise UserExists(record["username"]) from None

    def update(self, username: str, **fields) -> dict:
        # 열 이름이 f-string으로 SQL에 들어가므로 허용목록으로 못 박는다 (주입 차단).
        # assert가 아니라 명시 검사 — python -O로 구동해도 방어가 유지된다
        _check_update_fields(fields)
        sets = ", ".join(f"{k} = %s" for k in fields)
        with self._conn() as conn:
            row = conn.execute(
                f"UPDATE claw_users SET {sets} WHERE username = %s"
                f" RETURNING {self._COLS}",
                (*fields.values(), username),
            ).fetchone()
        if row is None:
            raise UserNotFound(username)
        return self._record(row)

    def delete(self, username: str) -> None:
        with self._conn() as conn:
            row = conn.execute(
                "DELETE FROM claw_users WHERE username = %s RETURNING username",
                (username,),
            ).fetchone()
        if row is None:
            raise UserNotFound(username)


def make_user_store(db_url: str, json_path):
    return PgUserStore(db_url) if db_url else JsonUserStore(json_path)


def ensure_admin(store, username: str, password: str) -> None:
    """관리자 시드 upsert — 환경변수가 정본. 저장소가 비어도(또는 비번을 잊어도)
    재기동만 하면 이 계정으로는 항상 들어올 수 있다."""
    record = new_record(username, password, role="admin", status="active")
    if store.get(username) is None:
        store.create(record)
    else:
        store.update(username, pw_hash=record["pw_hash"], role="admin", status="active")
