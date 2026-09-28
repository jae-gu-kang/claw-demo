"""M13 결과 저장소 — JSON 파일 저장·조회 (단독 사용자 로컬, 02 §4).

본문({id}.json)과 메타({id}.meta.json)를 분리 — 목록 조회가 대형 시계열
본문을 읽지 않게 한다. 본문을 먼저 쓰고 메타를 마지막에 쓰므로 목록에
보이는 결과는 본문 존재가 보장된다. 쓰기는 tmp→rename으로 원자적.
allow_nan=False — 비유한값은 serialize 정책(NaN→null 등)으로 정리된 뒤여야
하며, 위반은 저장 시점에 ValueError로 드러난다.

**본문은 줄 나눈 JSON이다.** 여전히 JSON 문서 하나지만(원본 JSON 링크·외부 도구가
그대로 읽는다) 최상위 항목마다, 비지 않은 최상위 dict는 그 항목마다 한 줄이다 —
sim 본문이면 신호 하나가 한 줄이다. 이유는 메모리다(Render 무료 512 MB·단일 워커):
S1 기본 미션(475 s × 100 Hz × 시계열 90개 — t·신호 84·엔벨로프 5) 본문은 68.6 MB인데 통째로 읽으면 파일 글
한 벌(meta의 한글 기체 이름 몇 자 때문에 UCS-2가 되어 137 MB)과 파싱본(129 MB)이
동시에 서서 +274 MB였다. 줄 단위로 읽고 쓰면 정점이 파싱본 + 한 줄이고, `want`·
`each`로 필요한 항목만 파싱하거나 파싱 직후 솎으면 파싱본도 서지 않는다
(재생 stride·타면 사용 — routes/sim.py). 엔진 함수가 무엇을 읽을지 다 모르는 소비자(타면 사용·
진단·교신)는 `load_picked`로 신호를 골라 읽는다 — 목록 밖 신호는 읽는 순간 채워 답이 같다.
파싱 결과는 json.loads와 값·키 순서까지 같다.
줄 경계는 b"\\n"뿐이다 — json.dumps가 값 안의 제어문자를 이스케이프하므로 값이 줄을
나누지 않는다(U+2028 등은 이스케이프되지 않아 splitlines를 쓰면 안 된다).
이 형식 이전의 한 줄 본문도 그대로 읽는다(첫 줄이 "{"만이 아니면 통째 읽기).
"""

import json
import re
from json.decoder import scanstring
from pathlib import Path

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")  # fullmatch 사용 — '$'는 후행 개행 허용
_DECODER = json.JSONDecoder()
_HEAD = b"{\n"  # 줄 나눈 본문의 첫 줄 — 한 줄 본문은 "{"와 첫 키가 같은 줄이다


class ResultStore:
    def __init__(self, root, limit: int | None = None):
        if limit is not None and limit < 1:  # 0·음수는 슬라이스가 뒤집혀 전량 삭제 사고
            raise ValueError(f"잘못된 보존 상한: {limit!r}")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.limit = limit  # 보존 개수 상한 (None = 무제한) — 휘발성 디스크 배포용

    def save(self, result_id: str, payload: dict, meta: dict | None = None) -> None:
        self._check_id(result_id)
        meta = dict(meta or {})
        meta["id"] = result_id
        self._write_body(self.root / f"{result_id}.json", payload)
        self._write(self.root / f"{result_id}.meta.json", meta)
        if self.limit is not None:
            for old in self.list()[self.limit :]:  # created 내림차순 → 초과분 = 오래된 것
                rid = str(old.get("id", ""))
                if not _ID_RE.fullmatch(rid):  # 외부 유입 메타 방어 — 경로 조작 불허 유지
                    continue
                self.delete(rid)

    def delete(self, result_id: str) -> None:
        """결과 하나 제거 (없어도 조용히 성공 — 상한 삭제·수동 정리 공용).

        메타 먼저 — 목록에서 사라진 뒤 본문 제거 (본문 없는 유령 목록 방지)."""
        self._check_id(result_id)
        (self.root / f"{result_id}.meta.json").unlink(missing_ok=True)
        (self.root / f"{result_id}.json").unlink(missing_ok=True)

    def load(self, result_id: str, *, want=None, each=None) -> dict:
        """본문 읽기 — 인자 없으면 전부(json.loads와 같은 값·키 순서).

        항목의 경로(path)는 (최상위 키,) 또는 — 값이 비지 않은 최상위 dict면 —
        (최상위 키, 하위 키)다. sim 본문이면 ("t",) · ("signals", "de") ·
        ("envelope", "flags") · ("meta", "limits") 꼴이다.
        want(path) → 거짓이면 그 항목을 **파싱하지 않고** 건너뛴다(그릇 dict는 남는다).
        each(path, value) → 담을 값. 파싱 직후 항목마다 불려 솎은 값만 남길 수 있다.
        손상 본문은 ValueError(JSONDecodeError 포함) — 통째 읽기와 같은 예외 계약이다.
        """
        self._check_id(result_id)
        try:
            fh = open(self.root / f"{result_id}.json", "rb")
        except FileNotFoundError:  # 없음 — 목록과 본문 사이 경합(보존 상한 삭제)도 여기로
            raise KeyError(result_id) from None
        with fh:
            # 길이 제한 — 한 줄 본문이면 머리 판정에 파일 전체(수십 MB)를 한 번 더 읽지 않는다
            if fh.readline(len(_HEAD) + 1) == _HEAD:
                try:
                    return _read_lines(fh, want, each)
                except ValueError:
                    pass  # 줄 규칙 밖(손으로 들여쓴 JSON 등) — 아래 통째 읽기가 판정한다
            # 이 형식 이전의 한 줄 본문 — 통째로 읽고 같은 경로 규칙을 적용한다.
            # 진짜 손상이면 여기서 JSONDecodeError(ValueError)가 난다
            fh.seek(0)
            obj = json.loads(fh.read().decode("utf-8"))
            return obj if want is None and each is None else _select(obj, want, each)

    def load_picked(self, result_id: str, box: str, names, *, want=None) -> dict:
        """본문 읽기 — 쪼갠 최상위 dict `box`(sim이면 "signals")는 names만 파싱하고 나머지는 **읽는 순간** 채운다.

        소비자가 엔진 함수라 무엇을 읽는지 라우트가 다 알 수 없다 — names는 미리 읽기 힌트이고, 목록 밖
        항목을 읽으면 PickedEntries가 그 줄만 마저 파싱해 답은 통째 읽기와 같다(메모리만 더 든다).
        want는 box 밖 항목의 골라 읽기다(load와 같은 경로 규칙). 없음·손상 예외는 load와 같다."""
        names = frozenset(names)
        rest = set()
        order = []  # 본문의 항목 순서 — 다 채운 뒤 통째 읽기와 같은 순서로 되돌린다

        def pick(path) -> bool:
            if path[0] == box and len(path) == 2:
                order.append(path[1])
                if path[1] in names:
                    return True
                rest.add(path[1])
                return False
            return want is None or want(path)

        payload = self.load(result_id, want=pick)

        def fetch(keys):
            keys = set(keys)
            body = self.load(result_id, want=lambda p: p[0] == box and len(p) == 2 and p[1] in keys)
            return body.get(box) or {}

        if isinstance(payload, dict) and isinstance(payload.get(box), dict):
            payload[box] = PickedEntries(payload[box], rest, fetch, order)
        return payload

    def open_body(self, result_id: str):
        """본문 파일을 바이너리로 연다 — 통째 전달(원본 JSON 조회)을 파싱 없이 흘려보내는 길.

        파일 바이트가 곧 JSON 문서 하나다(줄 나눈 본문도, 이 형식 이전의 한 줄 본문도).
        load() 후 응답 직렬화로 보내면 파싱본과 직렬화본 두 벌이 선다(S1 기본 미션 +258 MB).
        없으면 KeyError. 연 뒤에 보존 상한이 지워도 연 핸들로는 끝까지 읽힌다(POSIX).
        닫는 것은 호출자 몫이다."""
        self._check_id(result_id)
        try:
            return open(self.root / f"{result_id}.json", "rb")
        except FileNotFoundError:
            raise KeyError(result_id) from None

    def exists(self, result_id: str) -> bool:
        self._check_id(result_id)
        return (self.root / f"{result_id}.json").exists()

    def list(self) -> list:
        """저장 결과 메타 목록 — 최신(created 내림차순) 우선. 손상 메타는 건너뜀."""
        metas = []
        for p in self.root.glob("*.meta.json"):
            try:
                metas.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue  # 손상 파일 하나가 목록 전체를 죽이지 않도록
        return sorted(metas, key=lambda m: m.get("created", 0.0), reverse=True)

    @staticmethod
    def _check_id(result_id: str) -> None:
        if not _ID_RE.fullmatch(result_id):  # 경로 조작 차단 ('.' '/' 개행 등 불허)
            raise ValueError(f"잘못된 결과 id: {result_id!r}")

    @staticmethod
    def _write(path: Path, obj: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        tmp.replace(path)

    @staticmethod
    def _write_body(path: Path, obj: dict) -> None:
        """본문 쓰기 — 줄 단위라 글 한 벌을 통째로 세우지 않는다(정점 = 한 줄).

        줄 단위라 비유한값 위반이 중간에 날 수 있다 — 반쯤 쓴 tmp를 지우고 다시 던진다
        (목록에도 본문에도 남지 않는 것은 통째 쓰기 때와 같다)."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp, "wb") as fh:
                for line in _body_lines(obj):
                    fh.write(line.encode("utf-8"))
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise


class PickedEntries(dict):
    """골라 읽은 쪼갠 dict(sim 신호 등) — 고르지 않은 항목을 읽으면 그 줄만 마저 파싱해 채운다(load_picked).

    엔진의 선택 신호 읽기는 `signals.get(name)`이 None이면 그 보정을 조용히 건너뛴다
    (예: wow·on_rail 없음 = 지상 구간 없음). 그래서 목록 밖 신호를 없는 것처럼 굴면
    **조용히 다른 수**가 나온다 — 있는 신호는 있다고 답하고, 읽으면 채운다."""

    def __init__(self, picked: dict, rest: set, fetch, order=()):
        super().__init__(picked)
        self._rest = rest  # 본문에 있으나 아직 파싱하지 않은 항목 이름
        self._fetch = fetch  # [이름] → {이름: 값} (본문을 다시 훑어 그 줄만 파싱)
        # 본문의 항목 순서 — 다 채우면 이 순서로 되돌린다(줄 읽기가 통째 읽기로 물러나면 두 번 세므로 중복 제거)
        self._order = tuple(dict.fromkeys(order))

    def _fill(self, names) -> None:
        names = [n for n in names if n in self._rest]
        if names:
            self._rest.difference_update(names)
            dict.update(self, self._fetch(names))
            if not self._rest and self._order:
                # 채운 항목은 끝에 붙는다 — 다 채웠으면 본문 순서로 다시 세워 통째로 훑는 소비자가
                # 통째 읽기와 같은 순서를 본다(값은 참조만 옮긴다)
                known = [k for k in self._order if dict.__contains__(self, k)]
                seen = set(known)
                extra = [k for k in dict.keys(self) if k not in seen]
                items = [(k, dict.__getitem__(self, k)) for k in known + extra]
                dict.clear(self)
                dict.update(self, items)

    def __missing__(self, key):
        self._fill([key])
        if not dict.__contains__(self, key):
            # 본래 없는 항목이다 — dict.__getitem__을 다시 부르면 이 __missing__으로 돌아와 무한 재귀였다
            # (sim.py 시절 _PickedSignals의 잠복 결함 — 엔진은 .get으로 읽어 드러나지 않았다)
            raise KeyError(key)
        return dict.__getitem__(self, key)

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in self._rest

    def get(self, key, default=None):
        return self[key] if key in self else default

    # 통째로 훑는 소비자는 전부 채운 뒤 dict 그대로 — 정답이 먼저다
    def __iter__(self):
        self._fill(list(self._rest))
        return dict.__iter__(self)

    def __len__(self):
        return dict.__len__(self) + len(self._rest)

    def keys(self):
        self._fill(list(self._rest))
        return dict.keys(self)

    def values(self):
        self._fill(list(self._rest))
        return dict.values(self)

    def items(self):
        self._fill(list(self._rest))
        return dict.items(self)


def _pair(key, value) -> str:
    """'"키": 값' — json.dumps에 맡겨 키 강제 변환(int→"1" 등)·비유한값 거부가 통째 쓰기와 같다."""
    return json.dumps({key: value}, ensure_ascii=False, allow_nan=False)[1:-1]


def _split(value) -> bool:
    """최상위 값을 하위 항목별 줄로 나누는가 — 읽기(_select 포함)와 쓰기가 같은 규칙이다."""
    return isinstance(value, dict) and bool(value)


def _body_lines(obj):
    """본문 → 줄들. dict가 아니면(저장 계약 밖) 한 줄 — 읽기가 통째 읽기로 받는다."""
    if not isinstance(obj, dict):
        yield json.dumps(obj, ensure_ascii=False, allow_nan=False)
        return
    yield "{\n"
    items = list(obj.items())
    for i, (key, value) in enumerate(items):
        tail = ",\n" if i < len(items) - 1 else "\n"
        if _split(value):
            yield _pair(key, 0)[:-1] + "{\n"  # '"키": ' + '{'
            sub = list(value.items())
            for j, (k, v) in enumerate(sub):
                yield _pair(k, v) + (",\n" if j < len(sub) - 1 else "\n")
            yield "}" + tail
        else:
            yield _pair(key, value) + tail
    yield "}\n"


def _read_lines(fh, want, each) -> dict:
    """줄 나눈 본문(첫 줄 다음부터) → dict. 한 줄씩 파싱해 정점이 파싱본 + 한 줄이다."""
    out = {}
    box = None  # 지금 채우는 쪼갠 최상위 dict
    top = None  # 그 dict의 최상위 키
    for raw in fh:
        line = raw.decode("utf-8")
        if line.endswith("\n"):
            line = line[:-1]
        if box is not None and line in ("}", "},"):
            box = top = None
            continue
        if box is None and line == "}":
            return out
        if not line.startswith('"'):
            raise ValueError(f"결과 본문 형식 오류: {line[:40]!r}")
        key, end = scanstring(line, 1)
        if not line.startswith(": ", end):
            raise ValueError(f"결과 본문 형식 오류: {line[:40]!r}")
        start = end + 2
        if box is None and line[start:] == "{":  # 쪼갠 최상위 dict의 시작 — 그릇은 늘 남긴다
            out[key] = box = {}
            top = key
            continue
        path = (key,) if box is None else (top, key)
        if want is not None and not want(path):
            continue  # 파싱하지 않는다 — 이 항목의 파싱본은 한 번도 서지 않는다
        value, stop = _DECODER.raw_decode(line, start)  # 슬라이스 사본 없이 제자리 파싱
        if line[stop:] not in ("", ","):
            raise ValueError(f"결과 본문 형식 오류: {line[:40]!r}")
        (out if box is None else box)[key] = value if each is None else each(path, value)
    raise ValueError("결과 본문이 끝나지 않았다")  # 닫는 "}" 없음 — 잘린 파일


def _select(obj: dict, want, each) -> dict:
    """한 줄 본문(이미 파싱된 dict)에 줄 나눈 본문과 같은 경로 규칙으로 want·each를 적용."""
    if not isinstance(obj, dict):
        return obj  # 저장 계약 밖(dict 아닌 본문) — 경로가 없으니 고를 것도 없다
    out = {}
    for key, value in obj.items():
        if _split(value):
            box = out[key] = {}
            for k, v in value.items():
                path = (key, k)
                if want is None or want(path):
                    box[k] = v if each is None else each(path, v)
        else:
            path = (key,)
            if want is None or want(path):
                out[key] = value if each is None else each(path, value)
    return out
