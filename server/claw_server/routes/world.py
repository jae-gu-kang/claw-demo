"""3D 월드 자산 라우트 — 지형 팩 제공 (02 §4 지도 타일 설계).

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


def _root() -> Path:
    return Path(os.environ.get("CLAW_WORLD_DATA", "data/geo"))


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
    return {
        "terrain": packs,
        "reason": reason,
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
