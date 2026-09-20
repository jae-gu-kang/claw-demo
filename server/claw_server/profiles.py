"""M13 기체 프로파일 저장소 — 리비전·스냅숏 (02 §5.6).

기체 문서는 **웹에서만** 만들고 고친다(사용자 결정). 서버는 그 문서를 검증해 리비전으로 쌓는다:

    {root}/{id}/rev-{n}.json   검증·정규화된 문서 전체 (형상 변형 포함)
    {root}/{id}/head.json      {"revision": n}
    {root}/_snapshots/{fp}.json 계산에 실제로 쓴 **적용 문서**(형상 변형 반영) — 지문으로 찾는다

기체 id는 `_`로 시작할 수 없다(내부 폴더 자리). 삭제는 head만 지워 목록·조회에서 빼고 리비전 파일은
남긴다 — 같은 id로 다시 만들면 리비전 번호를 이어 세어, 옛 결과의 (id, 리비전)이 새 문서를 가리키지
않게 한다 — (id, 리비전)은 한 문서를 영원히 가리킨다. 읽을 때마다 문서를 다시 검증한다 — 스키마가
바뀐 뒤의 옛 저장본은 500이 아니라 "읽을 수 없음"으로 드러난다. head를 못 읽는 기체는 조회·갱신·생성이
충돌이고, 삭제만 받는다(치운 뒤 다시 만드는 복구 경로).

결과 저장소(ResultStore)를 재사용하지 않는 이유: 그쪽은 보존 상한에서 오래된 것을 지운다. 기체
문서와 스냅숏은 결과·설계 재개가 기대는 원본이라 지우면 안 된다. 스냅숏은 기체를 지워도 남는다 —
그 기체로 계산한 옛 결과가 무엇으로 계산됐는지를 말할 수 있어야 하기 때문이다.

예제 기체는 엔진 패키지 데이터이고 읽기 전용이다(리비전 0). 저장은 tmp→rename 원자 쓰기이고,
갱신은 base_revision이 head와 같을 때만 받는다 — 두 화면이 같은 기체를 고치면 나중 저장이 앞의 것을
조용히 덮지 않고 충돌로 드러난다.
"""

import json
import math
import re
import threading
from pathlib import Path

from claw.profile import EXAMPLE_ID, ProfileError, build_profile, load_example, validate_document

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")  # 스키마의 id 규칙과 같다 — 경로 조작 차단을 겸한다
EXAMPLE_REVISION = 0


class ProfileConflict(Exception):
    """이미 있는 id로 생성, 또는 base_revision이 head와 다름."""

    def __init__(self, message: str, head: int | None = None):
        super().__init__(message)
        self.head = head


class ProfileReadOnly(Exception):
    """예제 기체는 고치거나 지울 수 없다."""


class ProfileUnreadable(Exception):
    """저장된 기체 문서를 읽을 수 없다 — 손상, 또는 스키마가 바뀌어 옛 문서가 검증을 못 넘는다."""


def _nonfinite_path(obj, path: str = "") -> str | None:
    """문서 안 첫 NaN·Infinity의 JSON Pointer 경로 — 없으면 None.

    스키마가 검사하지 않고 복사하는 자유 필드(출처 `provenance`)에도 비유한값이 들어올 수 있다. 서버 JSON
    파서는 `NaN` 리터럴을 받지만 저장은 표준 JSON(allow_nan=False)이라, 여기서 경로와 함께 거부하지
    않으면 검증은 통과하고 저장이 500으로 죽는다."""
    if isinstance(obj, float):
        return None if math.isfinite(obj) else (path or "/")
    if isinstance(obj, dict):
        items = obj.items()
    elif isinstance(obj, list):
        items = enumerate(obj)
    else:
        return None
    for key, value in items:
        found = _nonfinite_path(value, f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}")
        if found:
            return found
    return None


def _de_trim_summary(doc: dict, built, variant_builts: dict) -> dict | None:
    """할당 표 요약 — 도출 표면 형상 변형마다도 낡음을 본다(변형이 플랜트를 바꾸면 그 변형만 낡을 수 있다)."""
    de_trim = None if doc["law"]["alloc"] is None else doc["law"]["alloc"]["de_trim"]
    if de_trim is None:
        return None
    stale_variants = ([vid for vid, vb in variant_builts.items() if vb.de_trim_stale]
                      if de_trim["source"] == "derived" else [])
    return {"source": de_trim["source"], "stale": built.de_trim_stale, "stale_variants": stale_variants}


def _gain_tables_summary(doc: dict, built, variant_builts: dict) -> dict | None:
    """확정 게인 표 요약 — 출처·낡음·낡은 형상 변형. 낡음 판정은 조립 거부와 같은 자다
    (build.gain_tables_stale). 표는 기본 문서에서 확정되므로 문서를 바꾸는 변형에서는 기준 지문이
    어긋나 낡음이다 — δe_trim의 stale_variants와 같은 자리에서 미리 말한다(변형 계산 422가
    첫 통보가 되지 않게)."""
    gt = doc["law"]["gain_tables"]
    if gt is None:
        return None
    prov = gt.get("provenance")
    source = prov.get("source") if isinstance(prov, dict) else None
    stale_variants = [vid for vid, vb in variant_builts.items() if vb.gain_tables_stale]
    return {"source": source, "stale": built.gain_tables_stale, "stale_variants": stale_variants}


def _design_source(doc: dict) -> str | None:
    design = doc["law"]["design"]
    prov = None if design is None else design["provenance"]
    return prov.get("source") if isinstance(prov, dict) else None


class ProfileStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._snapshots = self.root / "_snapshots"
        self._snapshots.mkdir(exist_ok=True)
        self._lock = threading.Lock()

    # ── 조회 ────────────────────────────────────────────────────────────────
    @staticmethod
    def id_problem(profile_id) -> str | None:
        """저장소가 받는 기체 id인가 — 아니면 사유. 스키마의 id 규칙에 `_` 시작 금지를 더한다.

        `_`로 시작하는 이름은 저장소 내부 폴더(_snapshots) 자리다 — 기체 id로 받으면 그 기체를 지울 때
        스냅숏이 통째로 사라진다."""
        if not isinstance(profile_id, str) or not _ID_RE.fullmatch(profile_id) or profile_id.startswith("_"):
            return f"잘못된 기체 id: {profile_id!r} (영문·숫자·_·- 1~64자, `_`로 시작 불가)"
        return None

    def _dir(self, profile_id: str) -> Path:
        problem = self.id_problem(profile_id)
        if problem:
            raise ValueError(problem)
        return self.root / profile_id

    def _head(self, profile_id: str) -> int:
        """최신 리비전. head가 없으면 KeyError("없는 기체" — 지운 기체도 여기, 리비전 파일은 남아 있다),
        있는데 못 읽으면 ProfileUnreadable. 둘을 뭉치면 지운 기체가 409로, 손상 기체가 404로 보인다."""
        path = self._dir(profile_id) / "head.json"
        try:
            rev = json.loads(path.read_text(encoding="utf-8"))["revision"]
        except FileNotFoundError:
            raise KeyError(profile_id) from None
        except (OSError, TypeError, KeyError, ValueError):  # ValueError: 손상 JSON과 UTF-8이 아닌 파일
            raise ProfileUnreadable(f"기체 head를 읽을 수 없다: {profile_id}") from None
        # 정수만 받는다 — int()로 바꾸면 1e999는 OverflowError(500), 1.9·true·"2"는 조용히 다른 번호가 된다
        if type(rev) is not int or rev < 1:
            raise ProfileUnreadable(f"기체 head의 리비전이 양의 정수가 아니다: {profile_id} ({rev!r})")
        return rev

    def ids(self) -> list:
        return sorted(d.name for d in self.root.iterdir()
                      if d.is_dir() and _ID_RE.fullmatch(d.name) and not d.name.startswith("_")
                      and (d / "head.json").exists())

    def get(self, profile_id: str, revision: int | None = None) -> tuple:
        """(**다시 검증한** 문서, 리비전). 없으면 KeyError, id 형식이 틀리면 ValueError, 저장본이
        손상됐거나 지금 스키마를 못 넘으면 ProfileUnreadable.

        읽을 때마다 검증한다 — 저장 시점에 통과한 문서도 스키마가 바뀌면 조립 도중 예외로 터진다."""
        if profile_id == EXAMPLE_ID:
            if revision not in (None, EXAMPLE_REVISION):
                raise KeyError(f"{profile_id}@{revision}")
            return load_example(), EXAMPLE_REVISION
        head = self._head(profile_id)  # id 형식이 틀리면 ValueError
        rev = head if revision is None else int(revision)
        try:
            raw = json.loads((self._dir(profile_id) / f"rev-{rev}.json").read_text(encoding="utf-8"))
        except FileNotFoundError:  # 없는 리비전, 또는 삭제와 경합
            raise KeyError(f"{profile_id}@{rev}") from None
        except (ValueError, OSError) as e:  # ValueError: 손상 JSON과 UTF-8이 아닌 파일 둘 다
            raise ProfileUnreadable(f"기체 문서를 읽을 수 없다: {profile_id}@{rev} ({type(e).__name__})") from None
        try:
            doc = validate_document(raw)
        except ProfileError as e:
            raise ProfileUnreadable(f"저장된 기체 문서가 현재 스키마를 넘지 못한다: {profile_id}@{rev} — {e}") from None
        bad = _nonfinite_path(doc)  # 손으로 고친 파일의 NaN — 두면 조회는 null로 조용히 내보내고 계산의 스냅숏 쓰기는 500이다
        if bad:
            raise ProfileUnreadable(f"저장된 기체 문서에 NaN·Infinity가 있다: {profile_id}@{rev} {bad}")
        return doc, rev

    @staticmethod
    def summary(doc: dict, revision: int) -> dict:
        built = build_profile(doc, validated=True)
        # 변형 조립은 한 번만 — 표 낡음 두 판정과 변형 지문(결과 신선도 대조의 근거, v1.32)이 같이 쓴다
        variant_builts = {v["id"]: build_profile(doc, v["id"], validated=True) for v in doc["variants"]}
        return {
            "id": doc["id"], "name": doc["name"], "description": doc["description"],
            "is_example": doc["is_example"], "revision": revision,
            "fingerprint": built.fingerprint,
            # 변형 지문 동봉 — 변형으로 계산한 결과의 신선도를 웹이 지문으로 판정한다(lib/freshness.js)
            "variants": [{"id": v["id"], "name": v["name"],
                          "fingerprint": variant_builts[v["id"]].fingerprint}
                         for v in doc["variants"]],
            # 게인 출처 — null이면 미설계. "quick_seed"면 화면이 「초기 탐색 게인 — 자동 설계 전」을 단다
            "design_source": _design_source(doc),
            # 할당 δe_trim 표 — null이면 없음. 도출 표는 플랜트가 바뀌면 stale(법칙 조립이 거부한다)
            "de_trim": _de_trim_summary(doc, built, variant_builts),
            # 확정 게인 표(v2) — null이면 없음. 반영 뒤 문서가 바뀌면 stale(법칙 조립이 거부한다)
            "gain_tables": _gain_tables_summary(doc, built, variant_builts),
        }

    def list(self) -> list:
        """예제가 맨 앞, 나머지는 id 순. 읽을 수 없는 기체는 목록을 죽이지 않되 **건너뛰지도 않는다** —
        `{id, unreadable: true, reason}`으로 싣는다. 복구 경로가 "그 id를 지우고 다시 만든다"인데 목록에서
        사라지면 화면이 지울 id를 알 길이 없다."""
        out = [self.summary(*self.get(EXAMPLE_ID))]
        for pid in self.ids():
            try:
                doc, revision = self.get(pid)
            except KeyError as e:
                # head가 없으면 목록을 훑는 사이 지워진 것이다. head는 있는데 리비전 파일이 없으면 손상이다 —
                # 건너뛰면 목록에서 사라지는데 같은 id 생성은 head 때문에 409라, 지울 id를 화면이 모르게 된다
                if (self.root / pid / "head.json").exists():
                    out.append({"id": pid, "unreadable": True, "reason": f"기체 문서 파일이 없다: {e}"})
                continue
            except (ValueError, ProfileUnreadable, OSError) as e:
                out.append({"id": pid, "unreadable": True, "reason": str(e)})
                continue
            try:
                out.append(self.summary(doc, revision))
            except (KeyError, ValueError, TypeError) as e:
                # 조립 실패 — 레지스트리 오류(RegistryError)는 KeyError라, 위와 한 except로 묶으면 지운 기체로
                # 오인돼 목록에서 사라진다
                out.append({"id": pid, "unreadable": True, "reason": f"{type(e).__name__}: {e}"})
        return out

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    @classmethod
    def checked(cls, document) -> dict:
        """저장 규칙으로 검증한 문서 — 생성·갱신과 `/profiles/validate`가 같은 규칙을 쓴다(검증은 통과했는데
        저장이 거부하는 문서가 없게). 어긋나면 경로가 붙은 ProfileError."""
        doc = validate_document(document)
        if doc["is_example"]:
            raise ProfileError("/is_example", "서버에 저장하는 기체는 예제일 수 없다 — 예제는 엔진 패키지 데이터다")
        if doc["id"] == EXAMPLE_ID:
            raise ProfileError("/id", f"예약된 id: {EXAMPLE_ID}")
        problem = cls.id_problem(doc["id"])
        if problem:
            raise ProfileError("/id", problem)
        bad = _nonfinite_path(doc)
        if bad:
            raise ProfileError(bad, "JSON으로 저장할 수 없는 값(NaN·Infinity) — 저장본은 표준 JSON이다")
        return doc

    @staticmethod
    def _max_revision(d: Path) -> int:
        # ASCII 숫자만 — `str.isdigit`은 "²"도 참이라 int()가 터진다
        revs = [int(m.group(1)) for p in d.glob("rev-*.json")
                if (m := re.fullmatch(r"rev-([0-9]+)", p.stem))]
        return max(revs, default=0)

    def create(self, document) -> tuple:
        doc = self.checked(document)
        with self._lock:
            d = self._dir(doc["id"])
            if (d / "head.json").exists():
                try:
                    head = self._head(doc["id"])
                except ProfileUnreadable:  # 못 읽는 head도 자리를 차지한다 — 지운 뒤 다시 만든다
                    raise ProfileConflict(
                        f"이 id의 기체 head를 읽을 수 없다 — 지운 뒤 다시 만든다: {doc['id']}") from None
                raise ProfileConflict(f"이미 있는 기체 id: {doc['id']}", head=head)
            d.mkdir(parents=True, exist_ok=True)
            # 지웠다가 같은 id로 다시 만들면 리비전을 이어 센다 — 옛 결과의 (id, 리비전)이 새 문서를
            # 가리키면 안 된다 (지운 기체의 리비전 파일은 스냅숏처럼 남긴다)
            rev = self._max_revision(d) + 1
            self._write(d / f"rev-{rev}.json", doc)
            self._write(d / "head.json", {"revision": rev})
        return doc, rev

    def update(self, profile_id: str, document, base_revision: int) -> tuple:
        if profile_id == EXAMPLE_ID:
            raise ProfileReadOnly("예제 기체는 고칠 수 없다 — 복제해서 새 기체로 만든다")
        self._dir(profile_id)  # id 형식 검사 — 문서 검증보다 먼저
        doc = self.checked(document)
        if doc["id"] != profile_id:
            raise ProfileError("/id", f"경로의 id({profile_id})와 문서의 id({doc['id']})가 다르다")
        with self._lock:
            head = self._head(profile_id)
            if int(base_revision) != head:
                raise ProfileConflict(
                    f"기준 리비전 {base_revision}이 최신 {head}와 다르다 — 다른 곳에서 먼저 저장했다",
                    head=head)
            rev = head + 1
            d = self._dir(profile_id)
            self._write(d / f"rev-{rev}.json", doc)
            self._write(d / "head.json", {"revision": rev})
        return doc, rev

    def delete(self, profile_id: str) -> None:
        """head만 지운다 — 목록·조회에서 사라지지만 리비전 파일은 남아 번호가 재사용되지 않는다.

        head를 읽지 않는다 — 손상된 head도 지울 수 있어야 그 id를 다시 만들 수 있다."""
        if profile_id == EXAMPLE_ID:
            raise ProfileReadOnly("예제 기체는 지울 수 없다")
        path = self._dir(profile_id) / "head.json"
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError:
                raise KeyError(profile_id) from None

    # ── 스냅숏 ──────────────────────────────────────────────────────────────
    def snapshot(self, built) -> None:
        """계산에 쓴 적용 문서를 지문으로 남긴다 — 같은 지문이면 이미 있는 것을 둔다."""
        path = self._snapshots / f"{built.fingerprint}.json"
        if not path.exists():
            with self._lock:
                if not path.exists():
                    self._snapshots.mkdir(parents=True, exist_ok=True)
                    self._write(path, built.doc)

    def load_snapshot(self, fingerprint: str) -> dict:
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{16}", fingerprint):
            raise ValueError(f"잘못된 지문: {fingerprint!r}")
        path = self._snapshots / f"{fingerprint}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise KeyError(fingerprint) from None

    @staticmethod
    def _write(path: Path, obj: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False, indent=1), encoding="utf-8")
        tmp.replace(path)
