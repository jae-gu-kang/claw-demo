"""3D 월드 자산 라우트 — 지형 팩과 모델 GLB 제공 (02 §4 지도 타일 설계).

**이 라우터는 바깥으로 나가지 않는다.** 지형·영상 자산은 개발 환경의 전처리 스크립트가
미리 구워 두고(`scripts/terrain/build_terrain.py`), 서버는 그 파일을 내주기만 한다.
그래서 런타임 아웃바운드 의존(httpx 등)이 늘지 않고, 폐쇄망에서는 반입한 팩만으로 그대로
돈다 — `scripts/run.sh`가 세운 "네트워크로 나가지 않고 그 사실을 말하며 죽는다" 철학과
같은 자리다.

자산이 없을 때 **404가 아니라 사유 문장을 낸다**: 화면이 "지형 없음"과 "서버 오류"를
구분해 말할 수 있어야 한다.
"""

import hashlib
import os
import struct
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()

# 팩 이름은 파일명이 된다 — 경로 주입을 문법으로 막는다(그 위에 화이트리스트가 한 번 더).
_NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
_MAGIC = b"CLAWTER1"
_GLB_MAGIC = b"glTF"


def _root() -> Path:
    return Path(os.environ.get("CLAW_WORLD_DATA", "data/geo"))


def _model_root() -> Path:
    """모델 GLB의 뿌리. 지형과 **다른 꾸러미**라 경로도 따로 둔다 — 지형은 재생성이
    네트워크를 타지만 모델은 리포에 실려 오고, 폐쇄망에서 둘의 반입 시점이 다르다."""
    return Path(os.environ.get("CLAW_MODEL_DATA", "models"))


def _scan_models() -> tuple[dict[str, Path], list[str], list[str]]:
    """`models/<모델>/<이름>.glb` → (쓸 수 있는 것, **이름이 겹쳐 뺀 것**, **못 읽어 뺀 것**).

    **이름을 평탄하게 쓴다.** 하위 경로를 URL에 실으면 그 자체가 경로 주입 표면이 되고,
    화이트리스트도 두 조각을 따로 검사해야 한다. 그 대가로 파일명이 겹칠 수 있는데,
    겹치면 **둘 다 뺀다** — 조용히 하나를 고르면 화면이 다른 기체를 그린다.

    뺀 이름을 함께 돌려주는 이유: 그냥 빼기만 하면 매니페스트가 "GLB가 없습니다 —
    구우십시오"라고 답한다. 구워 놓은 사람은 다시 굽고, 아무것도 안 바뀌고, 어디에도
    충돌을 가리키는 신호가 없다. **뺐다는 사실이 목록에 남아야 한다.**

    **매직이 틀리거나 못 읽은 것도 같다.** 폐쇄망으로 옮기다 잘린 파일, 부분 복사,
    권한 문제는 전부 "첫 네 바이트가 glTF가 아닌 .glb"로 나타난다. 파일은 눈앞에
    있는데 매니페스트가 "없습니다"라고 답하면 사람은 굽기를 반복한다 — 이름 충돌에서
    고친 것과 **정확히 같은 실패**라, 같이 드러낸다.
    """
    root = _model_root()
    if not root.is_dir():
        return {}, [], []
    seen: dict[str, Path] = {}
    dupes: set[str] = set()
    unreadable: list[str] = []
    for p in sorted(root.glob("*/*.glb")):
        try:
            with p.open("rb") as f:
                if f.read(4) != _GLB_MAGIC:
                    unreadable.append(p.name)
                    continue  # 매직이 다르면 목록에 넣지 않는다 (조용한 오독 금지)
        except OSError:
            unreadable.append(p.name)
            continue
        if p.name in seen:
            dupes.add(p.name)
            continue
        seen[p.name] = p
    for name in dupes:
        seen.pop(name, None)
    return seen, sorted(dupes), sorted(set(unreadable))


def _entries_to_models(entries: dict[str, Path]) -> list[dict]:
    out = []
    for name, p in sorted(entries.items()):
        try:
            out.append({"name": name, "bytes": p.stat().st_size})
        except OSError:
            continue  # 훑는 사이에 사라졌다 — 없는 것으로 답한다 (500 대신)
    return out


def _model_path(name: str) -> Path | None:
    """**화이트리스트를 통과한 이름만** 넘어온다는 전제를 여기서 다시 세운다.

    같은 스캔을 쓰므로 중복 규칙과 매직 검사가 그대로 걸린다 — 호출 순서에 안전을
    기대지 않는다(호출측이 바뀌어도 여기가 엉뚱한 파일을 내주지 않는다).
    """
    entries, _, _ = _scan_models()
    return entries.get(name)


def _terrain_packs() -> list[dict]:
    root = _root()
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.glob("*-terrain-*.bin")):
        try:
            with p.open("rb") as f:
                if f.read(8) != _MAGIC:
                    continue  # 매직이 다르면 목록에 넣지 않는다 (조용한 오독 금지)
        except OSError:
            continue
        out.append({"name": p.name, "bytes": p.stat().st_size})
    return out


@router.get("/world/manifest")
def world_manifest() -> dict:
    """3D 월드가 쓸 수 있는 자산 목록 — **없으면 그 사유를 문장으로 낸다.**"""
    packs = _terrain_packs()
    root = _root()
    if packs:
        reason = None
    elif not root.is_dir():
        reason = (f"지형 자산 폴더가 없습니다 ({root}) — "
                  "scripts/terrain/build_terrain.py로 팩을 구우십시오.")
    else:
        reason = (f"{root}에 지형 팩(*-terrain-*.bin)이 없습니다 — "
                  "scripts/terrain/build_terrain.py로 구우십시오.")
    # **한 번만 훑는다.** 두 번 훑으면 목록과 "뺀 것"이 서로 다른 관측에서 나와
    # 어긋날 수 있고, 모든 GLB를 두 번 여는 값도 그냥 낭비다.
    entries, dropped, unreadable = _scan_models()
    models = _entries_to_models(entries)
    reasons = []
    if dropped:
        # **뺐다는 사실을 반드시 말한다.** 안 그러면 "구우십시오"라는 틀린 안내가 간다.
        reasons.append(
            "이름이 겹쳐 뺀 GLB: " + ", ".join(dropped)
            + " — 여러 폴더에 같은 파일명이 있으면 어느 것인지 말할 수 없어 둘 다 "
              "내주지 않습니다. 한쪽 이름을 바꾸십시오."
        )
    if unreadable:
        reasons.append(
            "매직이 glTF가 아니거나 읽지 못한 파일: " + ", ".join(unreadable)
            + " — 옮기다 잘렸거나 부분 복사되었을 수 있습니다. 다시 구우십시오."
        )
    if reasons:
        models_reason = " / ".join(reasons)
    elif models:
        models_reason = None
    elif not _model_root().is_dir():
        models_reason = (f"모델 폴더가 없습니다 ({_model_root()}) — "
                         "models/<모델>/generate_*.py로 GLB를 구우십시오.")
    else:
        models_reason = (f"{_model_root()}에 GLB가 없습니다 — "
                         "models/<모델>/generate_*.py로 구우십시오.")

    return {
        "terrain": packs,
        "reason": reason,
        # 모델도 **없으면 사유를 문장으로** — 지형과 같은 규약이다.
        "models": models,
        "models_reason": models_reason,
        # 이름이 곧 약속이다 — 뺀 이유가 둘이므로 둘로 나눠 답한다.
        "models_dropped_duplicate": dropped,
        "models_dropped_unreadable": unreadable,
        # 타일 배경은 아직 없다. "준비 중"이 아니라 **무엇이 없어서 없는지**를 적는다
        "tiles": {"available": False,
                  "reason": "배경 영상 타일은 국토정보플랫폼 인증키가 있어야 합니다."},
        "root": str(root),
    }


def _etag(path: Path) -> str:
    """크기·mtime에 **헤더 블록 해시**를 섞은 검증자.

    크기와 mtime만 쓰면 위험한 경우가 남는다: 같은 --tier 구성으로 다시 구우면 크기가
    같고, mtime 해상도가 1초인 파일시스템에서는 그것도 같을 수 있다. 그러면 브라우저가
    옛 지형을 계속 쓰면서 알 길이 없다. 헤더 블록에는 티어 제원과 표고 범위·커버리지가
    들어 있어(build_terrain.py), 내용이 달라지면 거의 확실히 달라진다. 파일 전체를 해시하지
    않는 것은 2 MB를 304 하나에 읽지 않기 위해서다.
    """
    st = path.stat()
    with path.open("rb") as f:
        head = f.read(12)
        header_len = struct.unpack("<I", head[8:12])[0] if len(head) == 12 else 0
        block = f.read(min(header_len, 1 << 16))
    digest = hashlib.sha256(
        struct.pack("<QQ", st.st_size, st.st_mtime_ns) + block
    ).hexdigest()[:32]
    return f'"{digest}"'


@router.get("/world/terrain/{name}")
def world_terrain(name: str, request: Request) -> Response:
    if not name or set(name) - _NAME_OK:
        raise HTTPException(status_code=422, detail=f"팩 이름에 허용되지 않는 문자: {name!r}")
    # 화이트리스트 — 이름 규칙을 통과해도 매니페스트에 없는 파일은 내주지 않는다
    if name not in {p["name"] for p in _terrain_packs()}:
        raise HTTPException(status_code=404, detail=f"지형 팩 없음: {name}")

    etag = _etag(_root() / name)
    # **max-age를 길게 주지 않는다.** 파일명의 v1은 *포맷* 버전이지 내용 버전이 아니라,
    # --tier를 바꿔 다시 구우면 같은 이름에 다른 내용이 들어간다. 오래 캐시하면 브라우저가
    # 하루 동안 옛 지형을 보여 주고 사용자에게는 알 길이 없다. no-cache는 미사용이 아니라
    # **조건부 요청**이라(아래 If-None-Match) 안 바뀐 팩은 304로 끝난다.
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    # 프록시가 약한 검증자(W/"...")로 바꿔 보내면 완전일치는 매번 어긋난다 — 대역폭만
    # 손해지만 한 줄로 없어진다.
    incoming = (request.headers.get("if-none-match") or "").strip()
    if incoming.startswith("W/"):
        incoming = incoming[2:]
    if incoming == etag:
        # starlette.Response는 조건부 요청을 스스로 처리하지 않는다(StaticFiles만 한다) —
        # 그래서 여기서 직접 답한다. 안 하면 ETag가 장식일 뿐이다.
        return Response(status_code=304, headers=headers)
    return Response(
        content=(_root() / name).read_bytes(), media_type="application/octet-stream", headers=headers,
    )


def _model_etag(content: bytes) -> str:
    """**보낼 바이트 그대로**를 해시한 검증자.

    크기·mtime만 쓰면 같은 스크립트로 다시 구웠을 때 둘 다 같을 수 있어(재현 가능한
    빌드라 흔하다) 브라우저가 옛 기체를 계속 그린다. GLB는 100 KB 남짓이라 전체 해시가
    싸고, 싸면 정확한 쪽을 고른다.

    **mtime을 섞지 않는다.** 내용이 그대로인데 touch만 해도 전량 재전송이 되어, 조건부
    요청을 두는 목적과 반대로 간다. 그리고 이 해시는 응답 본문으로 쓸 바로 그 바이트에서
    나온다 — 검증자용으로 한 번, 본문용으로 또 한 번 읽으면 그 사이에 다시 구워진 파일이
    **낡은 ETag를 달고** 나가고, `no-cache` 아래서 영영 낡은 채로 남는다.
    """
    return f'"{hashlib.sha256(content).hexdigest()[:32]}"'


@router.get("/world/model/{name}")
def world_model(name: str, request: Request) -> Response:
    """모델 GLB — 지형 팩과 같은 규율(이름 문법 · 화이트리스트 · 조건부 304 · 무-아웃바운드)."""
    if not name or set(name) - _NAME_OK:
        raise HTTPException(status_code=422, detail=f"모델 이름에 허용되지 않는 문자: {name!r}")
    path = _model_path(name)  # 중복 규칙과 매직 검사를 통과한 것만 돌아온다
    if path is None:
        raise HTTPException(status_code=404, detail=f"모델 없음: {name}")

    try:
        content = path.read_bytes()
    except OSError:
        # 훑은 뒤 읽기 전에 사라졌다 — 경합이지 서버 고장이 아니다.
        raise HTTPException(status_code=404, detail=f"모델 없음: {name}") from None

    etag = _model_etag(content)
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    incoming = (request.headers.get("if-none-match") or "").strip()
    if incoming.startswith("W/"):
        incoming = incoming[2:]
    if incoming == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=content, media_type="model/gltf-binary", headers=headers)
