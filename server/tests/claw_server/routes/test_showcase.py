"""쇼케이스 기체 설치 라우트 — 패키지 문서 조회·설치·초기화가 몇 번을 불러도 같은 자리에 선다.

쇼케이스 진행기(web lib/showcase.js)의 준비 단계가 이 설치를 부르고 그 기체를 고른다. 휘발 저장소(공개 데모)는
재시작마다 비워지므로 설치는 「없으면 생성 · 고쳤으면 초기화(이력 유지) · 같으면 그대로」여야 한다.

엔진 쇼케이스 문서(claw.profile.document.load_showcase)와 무관하게 서도록 라우트의 문서 자리를 합성 문서로
갈아끼운다 — 예제 사본에 id·예제 표시만 바꾼 것. 패키지 문서 자체는 마지막 테스트가 본다.
"""

import copy

import pytest
from fastapi.testclient import TestClient

import claw_server.routes.profiles as profiles_route
from claw.profile import build_profile, load_example
from claw_server import create_app

SID = "showcase-delta"


def _packaged():
    d = load_example()
    d.update(id=SID, name="쇼케이스 델타", description="시험용 합성 쇼케이스", is_example=False)
    return d


@pytest.fixture()
def packaged(monkeypatch):
    doc = _packaged()
    # 호출마다 새 사본 — 엔진 로더(load_showcase)도 사본을 준다. 라우트가 고쳐도 다음 호출이 오염되지 않는다
    monkeypatch.setattr(profiles_route, "_showcase_document", lambda: copy.deepcopy(doc))
    return doc


def _install(client):
    r = client.post("/api/profiles/_showcase/install")
    assert r.status_code == 200, r.text
    return r.json()


def test_showcase_document_is_served_without_shadowing_profile_ids(client, packaged):
    r = client.get("/api/profiles/_showcase")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"document", "fingerprint"}
    assert body["document"]["id"] == SID and body["document"]["is_example"] is False
    assert body["fingerprint"] == build_profile(packaged).fingerprint
    # 조회는 설치가 아니다 — 저장소에 아무것도 생기지 않는다
    assert [p["id"] for p in client.get("/api/profiles").json()] == ["example-delta"]
    # `_` 시작 id는 저장소가 거부하므로 이 경로와 기체 id가 겹칠 일이 없다
    bad = copy.deepcopy(packaged)
    bad["id"] = "_showcase"
    assert client.post("/api/profiles", json={"document": bad}).status_code == 422


def test_install_is_idempotent_and_resets_an_edited_aircraft_as_a_new_revision(client, packaged):
    first = _install(client)
    fp = first["fingerprint"]
    assert first == {"id": SID, "revision": 1, "action": "created", "fingerprint": fp, "volatile": False}
    assert fp == client.get("/api/profiles/_showcase").json()["fingerprint"]
    assert _install(client) == {**first, "action": "unchanged"}  # 두 번째는 쓰지 않는다

    listing = {p["id"]: p for p in client.get("/api/profiles").json()}
    assert listing[SID]["is_example"] is False and listing[SID]["revision"] == 1
    got = client.get(f"/api/profiles/{SID}").json()
    assert got["document"] == client.get("/api/profiles/_showcase").json()["document"]

    # 시연 중 공학 수정 — 편집 가능한 저장 기체다(예제처럼 403이 아니다)
    doc = got["document"]
    doc["mass"]["m_empty"] += 5.0
    edited = client.put(f"/api/profiles/{SID}", json={"base_revision": 1, "document": doc})
    assert edited.status_code == 200 and edited.json()["revision"] == 2
    assert edited.json()["fingerprint"] != fp

    reset = _install(client)
    assert reset == {**first, "revision": 3, "action": "reset"}  # 덮지 않고 새 리비전 — 지문은 패키지 문서의 것
    head = client.get(f"/api/profiles/{SID}").json()
    assert head["revision"] == 3 and head["fingerprint"] == fp
    assert head["document"] == client.get("/api/profiles/_showcase").json()["document"]
    # 이력은 남는다 — 고친 리비전을 가리키던 옛 결과가 그 문서를 그대로 되짚는다
    assert client.get(f"/api/profiles/{SID}?revision=2").json()["document"]["mass"]["m_empty"] == doc["mass"]["m_empty"]
    assert _install(client) == {**reset, "action": "unchanged"}


def test_install_recreates_a_deleted_aircraft_without_reusing_revision_numbers(client, packaged):
    _install(client)
    assert client.delete(f"/api/profiles/{SID}").status_code == 204
    again = _install(client)
    # 지운 기체의 rev-1은 남아 있다 — (id, 리비전)은 한 문서를 영원히 가리킨다
    assert (again["action"], again["revision"]) == ("created", 2)


def test_install_recovers_an_aircraft_the_store_cannot_read(client, packaged):
    """다른 기체는 「지운 뒤 다시 만든다」가 복구 경로지만, 설치는 그 자체가 패키지 문서로의 되돌림이다."""
    _install(client)
    root = client.app.state.profiles.root / SID
    (root / "rev-1.json").write_text('{"schema_version": 1, "id": "showcase-delta"}', encoding="utf-8")
    assert client.get(f"/api/profiles/{SID}").status_code == 409
    fixed = _install(client)
    assert (fixed["action"], fixed["revision"]) == ("reset", 2)
    assert client.get(f"/api/profiles/{SID}").status_code == 200

    (root / "head.json").write_text("{not json", encoding="utf-8")
    fixed = _install(client)
    assert (fixed["action"], fixed["revision"]) == ("reset", 3)  # 번호는 남은 리비전 파일 뒤로 이어 센다
    assert client.get(f"/api/profiles/{SID}").json()["revision"] == 3


def test_install_on_a_volatile_store_says_so(tmp_path, packaged):
    with TestClient(create_app(data_dir=tmp_path / "v", profile_volatile=True)) as c:
        assert _install(c)["volatile"] is True


def test_a_packaged_document_that_breaks_the_storage_rules_is_a_server_fault(client, monkeypatch):
    doc = _packaged()
    doc["is_example"] = True
    monkeypatch.setattr(profiles_route, "_showcase_document", lambda: copy.deepcopy(doc))
    for r in (client.get("/api/profiles/_showcase"), client.post("/api/profiles/_showcase/install")):
        assert r.status_code == 500 and r.json()["detail"]["path"] == "/is_example"
    assert [p["id"] for p in client.get("/api/profiles").json()] == ["example-delta"]


def test_a_missing_or_broken_package_file_is_a_server_fault_with_a_reason(client, monkeypatch):
    """패키지 파일이 빠졌거나(배포 누락) JSON이 깨졌으면 맨 500이 아니라 사유 — 진행기 준비 단계가 그 사유로 멈춘다."""
    def missing():
        raise FileNotFoundError("examples/showcase_delta.json")

    for boom, name in ((missing, "FileNotFoundError"), (lambda: __import__("json").loads("{broken"), "JSONDecodeError")):
        monkeypatch.setattr(profiles_route, "_showcase_document", boom)
        for r in (client.get("/api/profiles/_showcase"), client.post("/api/profiles/_showcase/install")):
            assert r.status_code == 500, r.text
            assert r.json()["detail"]["message"].startswith("쇼케이스 기체 문서를 읽을 수 없다") and name in r.text
    assert [p["id"] for p in client.get("/api/profiles").json()] == ["example-delta"]


def test_install_is_behind_the_access_password_like_every_write(tmp_path, packaged):
    import base64

    with TestClient(create_app(data_dir=tmp_path / "g", access_password="pw")) as c:
        assert c.post("/api/profiles/_showcase/install").status_code == 401
        auth = {"authorization": "Basic " + base64.b64encode(b"x:pw").decode("ascii")}
        r = c.post("/api/profiles/_showcase/install", headers=auth)
        assert r.status_code == 200 and r.json()["action"] == "created"
    # 세션 모드(로그인 화면)도 같다 — `_showcase`는 면제 경로가 아니다, 조회까지
    with TestClient(create_app(data_dir=tmp_path / "s", admin_password="root-pw",
                               session_secret="test-secret")) as c:
        assert c.get("/api/profiles/_showcase").status_code == 401
        assert c.post("/api/profiles/_showcase/install").status_code == 401
        assert c.post("/api/auth/login", json={"username": "admin", "password": "root-pw"}).status_code == 200
        r = c.post("/api/profiles/_showcase/install")
        assert r.status_code == 200 and r.json()["action"] == "created"


def test_the_packaged_showcase_document_installs_as_an_editable_aircraft(client):
    """패키지에 실린 **그 문서**(엔진 E1 로더) — 저장 규칙을 넘고, 설치한 기체를 계산이 고를 수 있다."""
    try:
        from claw.profile.document import SHOWCASE_ID, load_showcase
    except ImportError:  # 엔진 쇼케이스 문서가 아직 없는 체크아웃 — 위의 합성 문서 테스트가 계약을 지킨다
        pytest.skip("claw.profile.document.load_showcase 없음")
    doc = load_showcase()
    assert doc["id"] == SID == SHOWCASE_ID and doc["is_example"] is False
    served = client.get("/api/profiles/_showcase").json()
    first = _install(client)
    assert (first["action"], first["revision"], first["id"]) == ("created", 1, SID)
    assert first["fingerprint"] == served["fingerprint"] == build_profile(doc).fingerprint
    assert _install(client)["action"] == "unchanged"
    r = client.get("/api/analysis/vn-envelope", params={"alt": 1000.0, "fuel": 10.0, "profile_id": SID})
    assert r.status_code == 200 and r.json()["profile"]["id"] == SID
