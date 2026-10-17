"""기동 시 기체 심기 — 패키지의 Banshee 문서를 저장 기체로, **한 번도 없었을 때만** 넣는다.

헤더 기체 선택기는 /api/profiles 목록을 그대로 보이므로 심긴 기체가 거기 떠야 한다. 사용자가 고친 리비전을 다시 뜰 때
덮으면 안 되고, 지운 기체를 되살려도 안 된다(지움은 head만 지우고 리비전 파일은 남는다 — 그 자리가 「있었다」의 표시다).
다른 서버 테스트는 목록을 정확히 비교하므로 conftest가 심기를 끈다 — 여기서는 명시로 켠다.
"""

import pytest
from fastapi.testclient import TestClient

from claw.profile import BANSHEE_ID, load_banshee
from claw_server import create_app
from claw_server.profiles import ProfileStore


def _app(tmp_path, **kw):
    return create_app(data_dir=tmp_path / "store", seed_aircraft=True, **kw)


def test_처음_뜨면_banshee가_목록에_뜬다(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        row = next(p for p in c.get("/api/profiles").json() if p["id"] == BANSHEE_ID)
        assert row["revision"] == 1 and row["is_example"] is False
        assert c.get(f"/api/profiles/{BANSHEE_ID}").status_code == 200


def test_고친_기체는_다시_떠도_덮지_않는다(tmp_path):
    store = ProfileStore(tmp_path / "p")
    assert store.seed(load_banshee()) == "created"
    doc, rev = store.get(BANSHEE_ID)
    doc["name"] = "내 Banshee"
    store.update(BANSHEE_ID, doc, base_revision=rev)
    assert store.seed(load_banshee()) == "kept"
    doc, rev = store.get(BANSHEE_ID)
    assert doc["name"] == "내 Banshee" and rev == 2  # 같은 내용의 새 리비전도 쓰지 않는다


def test_다시_떠도_고친_리비전이_남는다(tmp_path):
    """기동 경로 그대로 — 같은 저장 루트로 앱을 두 번 세운다."""
    with TestClient(_app(tmp_path)) as c:
        doc = c.get(f"/api/profiles/{BANSHEE_ID}").json()["document"]
        doc["name"] = "내 Banshee"
        assert c.put(f"/api/profiles/{BANSHEE_ID}", json={"document": doc, "base_revision": 1}).status_code == 200
    with TestClient(_app(tmp_path)) as c:
        row = next(p for p in c.get("/api/profiles").json() if p["id"] == BANSHEE_ID)
        assert (row["name"], row["revision"]) == ("내 Banshee", 2)


def test_쓰다_멈춘_빈_자리는_다시_심는다(tmp_path):
    store = ProfileStore(tmp_path / "p")
    (tmp_path / "p" / BANSHEE_ID).mkdir(parents=True)
    assert store.seed(load_banshee()) == "created"
    assert BANSHEE_ID in store.ids()


def test_지운_기체는_되살리지_않는다(tmp_path):
    store = ProfileStore(tmp_path / "p")
    store.seed(load_banshee())
    store.delete(BANSHEE_ID)
    assert store.seed(load_banshee()) == "kept"
    assert BANSHEE_ID not in store.ids()


def _listed(tmp_path, **kw):
    with TestClient(create_app(data_dir=tmp_path / "store", **kw)) as c:
        return BANSHEE_ID in [p["id"] for p in c.get("/api/profiles").json()]


def test_심기를_끄면_넣지_않는다(tmp_path):
    assert not _listed(tmp_path / "a", seed_aircraft=False)
    assert not _listed(tmp_path / "b", seed_aircraft="0")  # 문자열 "0"은 끔(_flag)


@pytest.mark.parametrize("env, on", [(None, True), ("1", True), ("0", False), ("false", False), ("off", False)])
def test_환경변수_미설정이면_켜고_끄는_값만_끈다(tmp_path, monkeypatch, env, on):
    if env is None:
        monkeypatch.delenv("CLAW_SEED_AIRCRAFT", raising=False)
    else:
        monkeypatch.setenv("CLAW_SEED_AIRCRAFT", env)
    assert _listed(tmp_path) is on
