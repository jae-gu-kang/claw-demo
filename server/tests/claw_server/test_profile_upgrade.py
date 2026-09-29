"""스키마 v2 → v3 올림 (05 §11.13 이관 11단계) — 저장본·가져오기·스냅숏이 거부되지 않고 올라가며, 사유가 화면에 간다.

정책(profiles.py 머리말):
  - 저장된 v2 리비전은 **디스크에서 고치지 않는다** — 읽을 때마다 올려서(엔진 upgrade_document) 쓰고, 조회 응답이
    upgrade_notes로 그 사실을 말한다. 사용자가 저장해야(PUT·잡 저장) v3 새 리비전이 생긴다. 옛 (id, 리비전)은 영원히
    v2 원본을 가리킨다(조용한 손실 없음).
  - 생성·갱신(가져오기 포함)으로 들어온 v2 문서는 올린 v3를 저장하고, 원본 v2와 사유를 upgrade-{n}.json에 남긴다.
  - 옛 결과의 v2 스냅숏은 지문 대조(스키마를 가리지 않는 해시 — 올리기 전 원본으로)를 넘으면 올려서 조립하고,
    profile 블록의 upgraded_from이 원래 지문과 사유를 싣는다.

픽스처 fixtures/profile_v2.json은 v1.67(3a2bd4c) 엔진으로 검증·정규화한 v2 문서와 그 지문이다.
"""

import copy
import json
from pathlib import Path

import pytest

from claw.profile.schema import SCHEMA_VERSION
from claw_server.profiles import ProfileStore

_FIX = json.loads((Path(__file__).parent / "fixtures" / "profile_v2.json").read_text(encoding="utf-8"))


def _v2(pid="legacy-v2"):
    d = copy.deepcopy(_FIX["document"])
    d["id"] = pid
    return d


def _plant_v2(root: Path, pid="legacy-v2", rev=1):
    """v2 시절 저장소가 남긴 모양 그대로 — 검증 없이 파일로 앉힌다."""
    d = root / pid
    d.mkdir(parents=True)
    (d / f"rev-{rev}.json").write_text(json.dumps(_v2(pid), ensure_ascii=False), encoding="utf-8")
    (d / "head.json").write_text(json.dumps({"revision": rev}), encoding="utf-8")


def _assert_structured(notes):
    """사유는 엔진 모양 그대로 {path, message} — 파이썬 dict 표기(「{'path': …」)가 화면·디스크에 새지 않는다."""
    assert notes
    for n in notes:
        assert set(n) == {"path", "message"}, n
        assert n["path"].startswith("/") and isinstance(n["message"], str) and n["message"], n
        assert "{'" not in n["message"] and "{'" not in n["path"], n
    return {n["path"] for n in notes}


# 픽스처(v2 예제 복제 · 운용 고도 없음 · 요구영역 없음)를 올리면 반드시 나오는 사유 경로
_FIXTURE_PATHS = {"/trim/alpha_bounds", "/trim/alpha_margin", "/mission_template/envelope"}


def test_fixture_is_a_v2_document():
    assert SCHEMA_VERSION == 3
    d = _FIX["document"]
    assert d["schema_version"] == 2 and "operating" in d and "trim" in d


def test_stored_v2_revision_is_read_upgraded_and_left_untouched_on_disk(tmp_path):
    store = ProfileStore(tmp_path)
    _plant_v2(tmp_path)
    before = (tmp_path / "legacy-v2" / "rev-1.json").read_bytes()
    notes = []
    doc, rev = store.get("legacy-v2", notes_out=notes)
    assert rev == 1 and doc["schema_version"] == 3
    assert "operating" not in doc and "trim" not in doc and "solver" in doc
    assert _assert_structured(notes) >= _FIXTURE_PATHS
    # 읽기는 쓰지 않는다 — 저장해야 새 리비전이 생긴다
    assert (tmp_path / "legacy-v2" / "rev-1.json").read_bytes() == before
    assert not list((tmp_path / "legacy-v2").glob("rev-2*"))
    # 목록도 죽지 않고, 올린 기체라고 말한다
    row = next(r for r in store.list() if r["id"] == "legacy-v2")
    assert not row.get("unreadable") and row["upgrade_notes"] == notes
    # 올린 문서를 그대로 저장하면 v3 새 리비전 — 사유 기록은 없다(들어온 문서는 이미 v3)
    new, rev2 = store.update("legacy-v2", doc, 1)
    assert rev2 == 2 and new == doc
    assert json.loads((tmp_path / "legacy-v2" / "rev-2.json").read_text(encoding="utf-8"))["schema_version"] == 3
    after = []
    store.get("legacy-v2", notes_out=after)
    assert after == []  # 최신은 이제 v3
    # 옛 리비전은 여전히 v2 원본을 가리키고, 읽으면 같은 문서로 올라간다(계보 — 올림은 결정적이다)
    old, _ = store.get("legacy-v2", 1)
    assert old == doc


def test_imported_v2_document_is_stored_upgraded_with_the_original_and_notes_recorded(tmp_path):
    store = ProfileStore(tmp_path)
    notes = []
    doc, rev = store.create(_v2("imported"), notes_out=notes)
    assert doc["schema_version"] == 3 and notes
    assert _assert_structured(notes) >= _FIXTURE_PATHS
    text = (tmp_path / "imported" / f"upgrade-{rev}.json").read_text(encoding="utf-8")
    assert "{'" not in text  # 디스크 기록도 구조 그대로
    rec = json.loads(text)
    assert rec["from_schema_version"] == 2 and rec["notes"] == notes
    assert rec["original"] == _v2("imported")  # 원본을 잃지 않는다
    # 기록 파일은 리비전 번호 셈에 끼지 않는다
    assert store._max_revision(tmp_path / "imported") == rev
    # 갱신도 같은 길 — v2를 PUT하면 올려 저장하고 기록한다
    notes2 = []
    _, rev2 = store.update("imported", _v2("imported"), rev, notes_out=notes2)
    assert notes2 == notes and (tmp_path / "imported" / f"upgrade-{rev2}.json").exists()
    # v3 문서 생성은 기록을 남기지 않는다
    store.create({**doc, "id": "plain"})
    assert not list((tmp_path / "plain").glob("upgrade-*"))


def test_checked_reports_upgrade_notes_without_storing(tmp_path):
    notes = []
    doc = ProfileStore.checked(_v2("checked"), notes_out=notes)
    assert doc["schema_version"] == 3 and _assert_structured(notes) >= _FIXTURE_PATHS
    assert not (tmp_path / "checked").exists()


# ── 라우트 ────────────────────────────────────────────────────────────────


def test_routes_return_upgrade_notes(client):
    r = client.post("/api/profiles", json={"document": _v2("route-v2")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["document"]["schema_version"] == 3 and _assert_structured(body["upgrade_notes"]) >= _FIXTURE_PATHS
    # 저장된 것은 v3라 조회에는 사유가 없다
    g = client.get("/api/profiles/route-v2").json()
    assert g["upgrade_notes"] == []
    # 검증만 — 저장 없이 사유를 준다(가져오기 미리 보기)
    v = client.post("/api/profiles/validate", json={"document": _v2("route-v3")}).json()
    assert v["ok"] and v["document"]["schema_version"] == 3 and _assert_structured(v["upgrade_notes"]) >= _FIXTURE_PATHS
    assert client.get("/api/profiles/route-v3").status_code == 404


def test_get_route_says_the_stored_revision_is_v2(client):
    root = Path(client.app.state.profiles.root)
    _plant_v2(root, "planted")
    g = client.get("/api/profiles/planted")
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["document"]["schema_version"] == 3 and _assert_structured(body["upgrade_notes"]) >= _FIXTURE_PATHS
    assert body["stored_schema_version"] == 2
    # 목록 행도 같은 구조(화면 툴팁이 「경로 — 문장」으로 그린다)
    row = next(p for p in client.get("/api/profiles").json() if p["id"] == "planted")
    assert row["upgrade_notes"] == body["upgrade_notes"]
    # 올린 문서로 계산이 돈다 — 저장하지 않아도(읽기 전용 올림)
    t = client.get("/api/analysis/design-envelope", params={"fuel": 200.0, "profile_id": "planted"})
    assert t.status_code == 200, t.text
    up = t.json()["profile"]["upgraded_from"]
    assert up["schema_version"] == 2 and _assert_structured(up["notes"]) >= _FIXTURE_PATHS


def test_v2_snapshot_of_an_old_result_still_resolves(client):
    """옛 결과(v2 기체로 계산)의 스냅숏 — 지문 대조를 넘으면 올려서 조립하고, 원래 지문과 사유를 echo한다."""
    from claw_server.refs import resolve_snapshot

    root = Path(client.app.state.profiles.root)
    fp = _FIX["fingerprint"]
    snap = {k: v for k, v in _FIX["document"].items() if k != "variants"}
    (root / "_snapshots" / f"{fp}.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

    class _Req:
        app = client.app

    echo = {"id": "legacy-v2", "name": "v2 저장 기체", "fingerprint": fp, "revision": 1, "variant": None,
            "is_example": False}
    built = resolve_snapshot(_Req(), echo)
    assert built.doc["schema_version"] == 3 and built.source == "snapshot"
    assert built.upgraded_from["schema_version"] == 2 and built.upgraded_from["fingerprint"] == fp
    assert _assert_structured(built.upgraded_from["notes"]) >= _FIXTURE_PATHS
    # 지문이 안 맞는 v2 스냅숏(손으로 고친 파일)은 여전히 409
    bad = copy.deepcopy(snap)
    bad["mass"]["m_empty"] += 1.0
    (root / "_snapshots" / f"{fp}.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        resolve_snapshot(_Req(), echo)
    assert e.value.status_code == 409 and "지문" in e.value.detail


def test_v1_documents_are_passed_through_and_rejected_by_the_validator(client):
    """엔진은 v2만 올린다 — v1은 원문 그대로 검증기로 가서 「지원 스키마 버전」 422다(올림 사유 없음)."""
    from claw_server.profiles import upgraded

    v1 = {**_v2("old-v1"), "schema_version": 1}
    doc, notes, old = upgraded(v1)
    assert doc is v1 and notes == [] and old is None
    r = client.post("/api/profiles/validate", json={"document": v1})
    assert r.status_code == 422 and r.json()["detail"]["path"] == "/schema_version"


# ── 미리 보기 라우트도 같은 올림 길 ─────────────────────────────────────────


@pytest.mark.parametrize("route,extra", [
    ("aero-slice", {"along": "alpha", "start": -0.1, "stop": 0.3, "n": 5, "fixed": {"mach": 0.3}}),
    ("aero-stability", {"start": -0.1, "stop": 0.3, "n": 5, "fixed": {"mach": 0.3}}),
    ("seed-basis", {"mach": 0.2, "alt": 1000.0, "fuel": 25.0}),
])
def test_preview_routes_upgrade_v2_documents(client, route, extra):
    """곡선·산출 근거 미리 보기도 저장·검증과 같은 올림 길(upgraded) — 가져온 v2 문서를 저장 전에 볼 수 있다."""
    r = client.post(f"/api/profiles/{route}", json={"document": _v2("preview"), **extra})
    assert r.status_code == 200, r.text
    assert _assert_structured(r.json()["upgrade_notes"]) >= _FIXTURE_PATHS
    # v3 문서는 종전 응답 그대로(키를 달지 않는다)
    from claw.profile import load_example

    r3 = client.post(f"/api/profiles/{route}", json={"document": load_example(), **extra})
    assert r3.status_code == 200 and "upgrade_notes" not in r3.json()


# ── 도출 표 도장 ────────────────────────────────────────────────────────────


def test_stored_v2_example_keeps_its_derived_table_usable(client):
    """v2에서 최신이던 도출 δe_trim 표는 올린 뒤에도 조립된다(엔진이 증명 뒤 v3 지문으로 다시 찍는다) — 요약이 낡음이라고
    하지 않고, 사유가 다시 찍었다고 말한다."""
    engine_fix = Path(__file__).resolve().parents[3] / "engine" / "claw" / "tests" / "fixtures" / "delta_demo_v2.json"
    raw = json.loads(engine_fix.read_text(encoding="utf-8"))
    raw.update(id="derived-v2", is_example=False)
    root = Path(client.app.state.profiles.root)
    (root / "derived-v2").mkdir()
    (root / "derived-v2" / "rev-1.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (root / "derived-v2" / "head.json").write_text(json.dumps({"revision": 1}), encoding="utf-8")
    body = client.get("/api/profiles/derived-v2").json()
    notes = {n["path"]: n["message"] for n in body["upgrade_notes"]}
    assert "다시 찍었다" in notes["/law/alloc/de_trim"]
    row = next(p for p in client.get("/api/profiles").json() if p["id"] == "derived-v2")
    assert row["de_trim"]["stale"] is False, row["de_trim"]


# ── 스냅숏 — 같은 지문·다른 내용 ────────────────────────────────────────────


def test_snapshots_with_the_same_fingerprint_but_different_content_are_kept_apart(client):
    """트림 α 여유만 다른 두 v2 문서는 올리면 같은 지문이다(여유가 지문 밖 기준으로 옮겨 간다). 먼저 남은 스냅숏으로 뒤
    결과를 조용히 재개하면 다른 문서다 — 뒤 것은 `{지문}-{내용 해시}`로 따로 남고 결과 echo가 그 키를 싣는다."""
    from claw_server.refs import resolve_snapshot

    a, b = _v2("margin-a"), _v2("margin-b")
    b["trim"]["alpha_margin"] = 0.05
    for d in (a, b):
        assert client.post("/api/profiles", json={"document": d}).status_code == 201
    ra = client.get("/api/analysis/design-envelope", params={"fuel": 25.0, "profile_id": "margin-a"}).json()["profile"]
    rb = client.get("/api/analysis/design-envelope", params={"fuel": 25.0, "profile_id": "margin-b"}).json()["profile"]
    assert ra["fingerprint"] == rb["fingerprint"]
    assert "snapshot" not in ra and rb["snapshot"].startswith(ra["fingerprint"] + "-")

    class _Req:
        app = client.app

    got_a, got_b = resolve_snapshot(_Req(), ra), resolve_snapshot(_Req(), rb)
    assert got_a.trim_bounds["alpha_margin"] != got_b.trim_bounds["alpha_margin"]
    assert got_b.trim_bounds["alpha_margin"] == 0.05 and got_b.snapshot_key == rb["snapshot"]
    # 같은 문서를 다시 계산하면 같은 키 — 파일이 늘지 않는다
    again = client.get("/api/analysis/design-envelope", params={"fuel": 25.0, "profile_id": "margin-b"}).json()["profile"]
    assert again["snapshot"] == rb["snapshot"]
    snaps = sorted(p.name for p in (Path(client.app.state.profiles.root) / "_snapshots").glob(f"{ra['fingerprint']}*"))
    assert len(snaps) == 2
    # 이름표만 다른 복제는 같은 스냅숏 — 키를 달지 않는다
    c = _v2("margin-a-copy")
    c["name"] = "이름만 다른 복제"
    assert client.post("/api/profiles", json={"document": c}).status_code == 201
    rc = client.get("/api/analysis/design-envelope", params={"fuel": 25.0, "profile_id": "margin-a-copy"}).json()
    assert "snapshot" not in rc["profile"]
    # 키 파일을 손으로 고치면(내용 해시 불일치) 다른 문서로 재개하지 않고 409
    from fastapi import HTTPException

    path = Path(client.app.state.profiles.root) / "_snapshots" / f"{rb['snapshot']}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["criteria"] = None
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(HTTPException) as e:
        resolve_snapshot(_Req(), rb)
    assert e.value.status_code == 409 and "해시" in e.value.detail
    # 지문과 맞지 않는 키도 거부
    with pytest.raises(HTTPException) as e:
        resolve_snapshot(_Req(), {**rb, "snapshot": "0000000000000000-0000000000000000"})
    assert e.value.status_code == 409
