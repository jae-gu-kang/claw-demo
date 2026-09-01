"""3D 월드 자산 라우트 검증 — 지형 팩 제공 (02 §4 지도 타일 설계).

이 라우터의 계약은 둘이다. ① **바깥으로 나가지 않는다** — 자산은 전처리 스크립트가 미리
구워 두고 서버는 파일만 내준다. ② **없는 것은 사유를 문장으로 말한다** — 화면이 "지형
없음"과 "서버 오류"를 구분할 수 있어야 한다.
"""

import struct

import pytest

MAGIC = b"CLAWTER1"


def _write_pack(path, name="test-terrain-v1.bin", header=b'{"origin":{},"tiers":[]}'):
    p = path / name
    p.write_bytes(MAGIC + struct.pack("<I", len(header)) + header)
    return p


@pytest.fixture
def world_dir(tmp_path, monkeypatch):
    d = tmp_path / "geo"
    d.mkdir()
    monkeypatch.setenv("CLAW_WORLD_DATA", str(d))
    return d


def test_자산이_없으면_사유_문장을_낸다(client, world_dir):
    """404가 아니라 이유를 말한다 — 화면이 '없음'과 '고장'을 구분해야 한다."""
    body = client.get("/api/world/manifest").json()
    assert body["terrain"] == []
    assert body["reason"] and "build_terrain" in body["reason"]


def test_폴더_자체가_없어도_500이_아니다(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAW_WORLD_DATA", str(tmp_path / "없는폴더"))
    r = client.get("/api/world/manifest")
    assert r.status_code == 200
    assert r.json()["reason"]


def test_타일_배경은_무엇이_없어서_없는지_말한다(client, world_dir):
    """"준비 중"이 아니라 막고 있는 것의 이름을 적는다 — 다음 사람이 무엇을 구하면
    되는지 알 수 있어야 한다."""
    tiles = client.get("/api/world/manifest").json()["tiles"]
    assert tiles["available"] is False
    assert "인증키" in tiles["reason"]


def test_지형_팩을_목록에_올리고_내준다(client, world_dir):
    _write_pack(world_dir)
    body = client.get("/api/world/manifest").json()
    assert body["reason"] is None
    assert [t["name"] for t in body["terrain"]] == ["test-terrain-v1.bin"]

    r = client.get("/api/world/terrain/test-terrain-v1.bin")
    assert r.status_code == 200
    assert r.content[:8] == MAGIC
    assert r.headers["etag"]
    # 오래 캐시하지 않는다 — 같은 이름에 다시 구운 내용이 들어갈 수 있다.
    # no-cache는 미사용이 아니라 조건부 요청이라 안 바뀐 팩은 304로 끝난다(아래 테스트).
    assert r.headers["cache-control"] == "no-cache"


def test_매직이_다른_파일은_목록에_넣지_않는다(client, world_dir):
    """옛 포맷을 새 코드가 조용히 읽는 일을 목록 단계에서 막는다."""
    (world_dir / "bogus-terrain-v9.bin").write_bytes(b"NOTAPACK" + b"\0" * 16)
    assert client.get("/api/world/manifest").json()["terrain"] == []
    assert client.get("/api/world/terrain/bogus-terrain-v9.bin").status_code == 404


@pytest.mark.parametrize("name", ["nope-terrain-v1.bin", "test-terrain-v2.bin"])
def test_없는_팩은_404다(client, world_dir, name):
    _write_pack(world_dir)
    assert client.get(f"/api/world/terrain/{name}").status_code == 404


@pytest.mark.parametrize("name", ["a/b.bin", "a b.bin", "a;b.bin", "a\\b.bin"])
def test_이름_규칙을_벗어나면_내주지_않는다(client, world_dir, name):
    """경로 주입을 문법으로 막는다 — 화이트리스트가 한 겹 더 있지만 여기서 먼저 걸린다."""
    _write_pack(world_dir)
    assert client.get(f"/api/world/terrain/{name}").status_code != 200


def test_매니페스트에_없는_파일은_이름이_멀쩡해도_안_준다(client, world_dir):
    """이름 규칙만으로는 부족하다 — 폴더에 우연히 놓인 파일이 새어 나가면 안 된다."""
    (world_dir / "secret.bin").write_bytes(b"x" * 32)
    assert client.get("/api/world/terrain/secret.bin").status_code == 404


def test_서버는_자산을_받으러_바깥으로_나가지_않는다(client, world_dir, monkeypatch):
    """런타임 아웃바운드가 없다는 것을 **실행 가능한 형태로** 못박는다.

    **소켓 층을 막는다.** urlopen만 막으면 urllib를 쓰는 경우만 잡히고 httpx·requests·
    맨소켓은 그대로 새어 나간다 — 실제로 처음엔 urlopen만 막아 두어, 핸들러에 진짜
    getaddrinfo를 심어도 13개가 전부 통과했다(리뷰의 변이시험). 소켓을 막으면 어느
    라이브러리를 쓰든 걸린다.

    폐쇄망에서 이 서버가 도는 근거가 이것이다 — 자산은 전처리가 미리 굽고 서버는 파일만 읽는다.

    **전제**: conftest의 client 픽스처가 `with TestClient(app)`으로 포털을 미리 세운다.
    그래서 이벤트루프의 self-pipe(socketpair)가 이 monkeypatch보다 **먼저** 만들어진다.
    `with`를 떼면 이 테스트가 "서버가 바깥으로 나갔다"로 죽으면서 엉뚱한 범인을 가리킨다 —
    조용히 통과하는 게 아니라 시끄럽게 실패하므로 위험하진 않지만, 그때 이 줄을 보면 된다.
    """
    import socket

    def explode(*a, **k):
        raise AssertionError("서버가 바깥으로 나갔다")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "getaddrinfo", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    _write_pack(world_dir)
    assert client.get("/api/world/manifest").status_code == 200
    assert client.get("/api/world/terrain/test-terrain-v1.bin").status_code == 200


def test_바뀌지_않은_팩은_304로_끝난다(client, world_dir):
    """ETag가 장식이 아니라 실제로 재검증에 쓰인다 — no-cache가 매번 전송을 뜻하지 않게."""
    _write_pack(world_dir)
    first = client.get("/api/world/terrain/test-terrain-v1.bin")
    assert first.status_code == 200
    etag = first.headers["etag"]
    again = client.get("/api/world/terrain/test-terrain-v1.bin",
                       headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""


def test_다시_구운_팩은_크기가_같아도_새로_받는다(client, world_dir):
    """파일명의 v1은 **포맷** 버전이라 다시 구우면 같은 이름에 다른 내용이 들어간다.

    **크기가 같은 재굽기**로 시험한다 — 그것이 현실적인 경우(같은 --tier 구성)이고,
    크기만 보는 검증자로는 못 잡는다. 헤더 길이를 유지한 채 내용만 바꾼다.
    """
    _write_pack(world_dir, header=b'{"origin":{},"tiers":[],"z":1}')
    etag = client.get("/api/world/terrain/test-terrain-v1.bin").headers["etag"]
    _write_pack(world_dir, header=b'{"origin":{},"tiers":[],"z":2}')  # 같은 길이
    r = client.get("/api/world/terrain/test-terrain-v1.bin", headers={"If-None-Match": etag})
    assert r.status_code == 200, "내용이 바뀌었는데 304를 주면 안 된다"
    assert "max-age" not in r.headers["cache-control"]


def test_약한_검증자도_재검증에_쓰인다(client, world_dir):
    """프록시가 ETag를 W/"..."로 바꿔 보내도 304가 나와야 한다 — 아니면 매번 전송이다."""
    _write_pack(world_dir)
    etag = client.get("/api/world/terrain/test-terrain-v1.bin").headers["etag"]
    r = client.get("/api/world/terrain/test-terrain-v1.bin",
                   headers={"If-None-Match": f"W/{etag}"})
    assert r.status_code == 304
