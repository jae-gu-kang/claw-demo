"""기체 프로파일 라우트 — 저장·리비전·선택이 계산에 실제로 반영되는가 (02 §5.6).

선택한 기체가 **이름만 붙고 예제 기체로 계산되는** 것이 이 단계가 막으려는 실패다. 그래서 목록·저장만
보지 않고, 더 무거운 기체를 고르면 트림 받음각과 실속속도가 실제로 커지는지를 본다.
"""

from claw.profile import EXAMPLE_ID, load_example


def _doc(pid="heavy-delta", m_empty=900.0):
    d = load_example()
    d.update(id=pid, name="무거운 델타", description="시험용", is_example=False)
    d["mass"]["m_empty"] = m_empty
    d["variants"] = [{"id": "full-stores", "name": "외장 만재", "patch": {"/mass/m_empty": 1000.0}}]
    return d


def _trim(client, wait_job, profile=None):
    body = {"cases": [{"mach": 0.45, "alt": 1000.0, "fuel": 200.0}]}
    if profile is not None:
        body["profile"] = profile
    r = client.post("/api/trim/batch", json=body)
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"])
    assert j["status"] == "done"
    return client.get(f"/api/results/{j['result_id']}").json()


def test_example_is_listed_first_and_read_only(client):
    listing = client.get("/api/profiles").json()
    assert listing[0]["id"] == EXAMPLE_ID and listing[0]["is_example"] is True
    got = client.get(f"/api/profiles/{EXAMPLE_ID}")
    assert got.status_code == 200 and got.json()["revision"] == 0
    assert client.delete(f"/api/profiles/{EXAMPLE_ID}").status_code == 403
    assert client.put(f"/api/profiles/{EXAMPLE_ID}",
                      json={"base_revision": 1, "document": got.json()["document"]}).status_code == 403


def test_create_revise_conflict_and_delete(client):
    created = client.post("/api/profiles", json={"document": _doc()})
    assert created.status_code == 201 and created.json()["revision"] == 1
    assert client.post("/api/profiles", json={"document": _doc()}).status_code == 409
    doc = created.json()["document"]
    doc["mass"]["m_empty"] = 950.0
    revised = client.put("/api/profiles/heavy-delta", json={"base_revision": 1, "document": doc})
    assert revised.status_code == 200 and revised.json()["revision"] == 2
    # 같은 기준 리비전으로 또 저장하면 조용히 덮지 않고 충돌이다
    stale = client.put("/api/profiles/heavy-delta", json={"base_revision": 1, "document": doc})
    assert stale.status_code == 409 and stale.json()["detail"]["head"] == 2
    assert client.get("/api/profiles/heavy-delta?revision=1").json()["document"]["mass"]["m_empty"] == 900.0
    assert client.get("/api/profiles/heavy-delta").json()["document"]["mass"]["m_empty"] == 950.0
    assert [p["id"] for p in client.get("/api/profiles").json()] == [EXAMPLE_ID, "heavy-delta"]
    assert client.delete("/api/profiles/heavy-delta").status_code == 204
    assert client.get("/api/profiles/heavy-delta").status_code == 404


def test_validation_errors_carry_the_document_path(client):
    bad = _doc()
    bad["mass"]["m_empty"] = -1
    r = client.post("/api/profiles/validate", json={"document": bad})
    assert r.status_code == 422 and r.json()["detail"]["path"] == "/mass/m_empty"
    ok = client.post("/api/profiles/validate", json={"document": _doc()}).json()
    assert ok["ok"] and set(ok["variants"]) == {"full-stores"}
    as_example = _doc()
    as_example["is_example"] = True
    assert client.post("/api/profiles", json={"document": as_example}).status_code == 422
    assert client.post("/api/profiles", json={"document": _doc(pid=EXAMPLE_ID)}).status_code == 422
    # 검증은 저장과 같은 규칙이다 — 검증이 통과시킨 문서를 저장이 거부하면 편집기가 초록 뒤에 실패한다
    for doc, path in ((as_example, "/is_example"), (_doc(pid=EXAMPLE_ID), "/id"), (_doc(pid="_x"), "/id")):
        r = client.post("/api/profiles/validate", json={"document": doc})
        assert r.status_code == 422 and r.json()["detail"]["path"] == path, r.text


def test_selected_aircraft_changes_the_computation_and_is_echoed(client, wait_job):
    client.post("/api/profiles", json={"document": _doc()})
    ex = _trim(client, wait_job)
    heavy = _trim(client, wait_job, {"id": "heavy-delta"})
    stores = _trim(client, wait_job, {"id": "heavy-delta", "variant": "full-stores"})
    assert ex["profile"]["source"] == "default-example" and ex["profile"]["is_example"] is True
    assert heavy["profile"]["id"] == "heavy-delta"
    assert heavy["profile"]["revision"] == 1 and heavy["profile"]["source"] == "request"
    assert stores["profile"]["variant"] == "full-stores"
    assert len({ex["profile"]["fingerprint"], heavy["profile"]["fingerprint"],
                stores["profile"]["fingerprint"]}) == 3
    # 수평비행 트림은 θ = α — 무거울수록 같은 조건에서 더 큰 받음각이 필요하다
    theta = [r["results"][0]["euler"][1] for r in (ex, heavy, stores)]
    assert theta[0] < theta[1] < theta[2], theta
    metas = client.get("/api/results").json()
    assert {m["profile"]["id"] for m in metas} == {EXAMPLE_ID, "heavy-delta"}


def test_get_routes_take_the_profile_query(client):
    client.post("/api/profiles", json={"document": _doc()})
    base = "/api/analysis/vn-envelope?alt=1000&fuel=200"
    ex = client.get(base).json()
    heavy = client.get(base + "&profile_id=heavy-delta").json()
    assert ex["profile"]["is_example"] is True and heavy["profile"]["id"] == "heavy-delta"
    assert heavy["speeds"]["v_s"] > ex["speeds"]["v_s"]  # 무거우면 실속속도가 높다
    assert (ex["limits_source"], heavy["limits_source"]) == ("demo-placeholder", "profile")
    assert client.get(base + "&profile_id=nope").status_code == 404
    assert client.get(base + "&profile_variant=full-stores").status_code == 422  # id 없는 변형
    assert client.get(base + "&profile_id=heavy-delta&profile_variant=nope").status_code == 404
    catalog = client.get("/api/gains/catalog?profile_id=heavy-delta").json()
    assert catalog["profile"]["id"] == "heavy-delta"


def test_snapshot_outlives_the_profile_it_came_from(client, wait_job):
    client.post("/api/profiles", json={"document": _doc()})
    fp = _trim(client, wait_job, {"id": "heavy-delta"})["profile"]["fingerprint"]
    client.delete("/api/profiles/heavy-delta")
    # 그 기체로 계산한 결과가 무엇으로 계산됐는지는 기체를 지워도 말할 수 있어야 한다
    snap = client.app.state.profiles.load_snapshot(fp)
    assert snap["mass"]["m_empty"] == 900.0  # 이름표(id)는 먼저 남긴 기체의 것일 수 있어 보지 않는다


def test_parse_table_reads_csv_text(client):
    ok = client.post("/api/profiles/parse-table", json={
        "csv_text": "mach,alpha_stall\n0.1,0.4\n0.5,0.33\n",
        "axis_cols": ["mach"], "value_col": "alpha_stall"})
    assert ok.status_code == 200 and ok.json()["axes"]["mach"] == [0.1, 0.5]
    missing = client.post("/api/profiles/parse-table", json={
        "csv_text": "mach,x\n0.1,1\n0.5,2\n", "axis_cols": ["mach"], "value_col": "alpha_stall"})
    assert missing.status_code == 422


def test_internal_folder_names_are_not_profile_ids(client):
    # `_snapshots` 기체를 만들었다 지우면 스냅숏이 통째로 사라지던 자리
    for pid in ("_snapshots", "_x"):
        r = client.post("/api/profiles", json={"document": _doc(pid=pid)})
        assert r.status_code == 422, (pid, r.text)
    assert client.delete("/api/profiles/_snapshots").status_code == 422


def test_delete_then_recreate_continues_revision_numbers(client):
    client.post("/api/profiles", json={"document": _doc()})
    client.delete("/api/profiles/heavy-delta")
    # 손으로 넣은 이상한 파일 이름이 번호 세기를 죽이지 않는다 ("²".isdigit()은 참이다)
    (client.app.state.profiles.root / "heavy-delta" / "rev-².json").write_text("{}", encoding="utf-8")
    again = client.post("/api/profiles", json={"document": _doc(m_empty=1200.0)})
    # 옛 결과의 (heavy-delta, 1)이 새 문서를 가리키면 안 된다
    assert again.status_code == 201 and again.json()["revision"] == 2
    # (id, 리비전)은 한 문서를 영원히 가리킨다 — 옛 번호는 지운 기체의 문서 그대로다 (02 §5.6)
    old = client.get("/api/profiles/heavy-delta?revision=1")
    assert old.status_code == 200 and old.json()["document"]["mass"]["m_empty"] == 900.0
    assert client.get("/api/profiles/heavy-delta").json()["document"]["mass"]["m_empty"] == 1200.0


def test_compute_can_select_an_older_revision(client, wait_job):
    created = client.post("/api/profiles", json={"document": _doc()}).json()
    doc = created["document"]
    doc["mass"]["m_empty"] = 1100.0
    client.put("/api/profiles/heavy-delta", json={"base_revision": 1, "document": doc})
    old = _trim(client, wait_job, {"id": "heavy-delta", "revision": 1})
    new = _trim(client, wait_job, {"id": "heavy-delta"})
    assert (old["profile"]["revision"], new["profile"]["revision"]) == (1, 2)
    assert old["results"][0]["euler"][1] < new["results"][0]["euler"][1]


def test_unreadable_stored_document_is_409_not_500(client):
    client.post("/api/profiles", json={"document": _doc()})
    root = client.app.state.profiles.root / "heavy-delta"
    (root / "rev-1.json").write_text('{"schema_version": 1, "id": "heavy-delta"}', encoding="utf-8")
    assert client.get("/api/profiles/heavy-delta").status_code == 409
    assert client.get("/api/analysis/vn-envelope?alt=1000&fuel=200&profile_id=heavy-delta").status_code == 409
    assert [p["id"] for p in client.get("/api/profiles").json()] == ["example-delta"]  # 목록은 건너뛴다


def test_unreadable_head_is_409_and_delete_is_the_way_out(client):
    """head가 손상된 기체 — 목록에서 사라지고 고칠 수도 다시 만들 수도 없던 자리. 삭제로 치우고 다시 만든다."""
    cases = (("broken-json", "{not json"), ("no-revision", "{}"), ("not-utf8", b"\xff\xfe"),
             ("inf-revision", '{"revision": 1e999}'), ("string-revision", '{"revision": "2"}'),
             ("zero-revision", '{"revision": 0}'), ("bool-revision", '{"revision": true}'))
    for pid, head in cases:
        assert client.post("/api/profiles", json={"document": _doc(pid=pid)}).status_code == 201
        path = client.app.state.profiles.root / pid / "head.json"
        path.write_bytes(head if isinstance(head, bytes) else head.encode())
        assert client.get(f"/api/profiles/{pid}").status_code == 409, pid
        assert client.get("/api/profiles").status_code == 200, pid  # 손상 기체 하나가 목록을 죽이지 않는다
        assert client.put(f"/api/profiles/{pid}",
                          json={"base_revision": 1, "document": _doc(pid=pid)}).status_code == 409, pid
        assert client.post("/api/profiles", json={"document": _doc(pid=pid)}).status_code == 409, pid
        assert client.delete(f"/api/profiles/{pid}").status_code == 204, pid
        again = client.post("/api/profiles", json={"document": _doc(pid=pid)})
        assert again.status_code == 201 and again.json()["revision"] == 2, pid


def test_nonfinite_values_are_refused_by_validate_and_save_alike(client):
    """스키마가 복사만 하는 출처 필드의 NaN — 검증은 통과하고 저장이 500으로 죽던 자리. 브라우저는 NaN을
    못 보내지만(JSON.stringify는 null) 스크립트 가져오기는 보낸다."""
    import json

    d = _doc()
    d["law"]["design"]["provenance"] = {"source": "script", "score": float("nan")}
    headers = {"content-type": "application/json"}
    client.post("/api/profiles", json={"document": _doc(pid="other")})
    for method, url, body in (("post", "/api/profiles/validate", {"document": d}),
                              ("post", "/api/profiles", {"document": d}),
                              ("put", "/api/profiles/other", {"base_revision": 1, "document": {**d, "id": "other"}})):
        r = client.request(method, url, content=json.dumps(body), headers=headers)
        assert r.status_code == 422, (url, r.text)
        assert r.json()["detail"]["path"] == "/law/design/provenance/score", (url, r.text)


def test_unwritable_stored_revision_is_409(client):
    """UTF-8이 아닌 저장본(422였다)과 손으로 넣은 NaN(조회는 null로 조용히 내보내고 계산의 스냅숏 쓰기는 500이었다)."""
    import json

    nan_doc = _doc()
    nan_doc["law"]["design"]["provenance"] = {"score": float("nan")}
    for content in (b"\xff\xfe{}", json.dumps(nan_doc).encode()):
        rev = client.post("/api/profiles", json={"document": _doc()}).json()["revision"]  # 다시 만들면 2
        (client.app.state.profiles.root / "heavy-delta" / f"rev-{rev}.json").write_bytes(content)
        assert client.get("/api/profiles/heavy-delta").status_code == 409, content[:20]
        assert client.get("/api/analysis/vn-envelope?alt=1000&fuel=200&profile_id=heavy-delta").status_code == 409
        client.delete("/api/profiles/heavy-delta")


def test_resume_rejects_a_snapshot_that_no_longer_validates(client):
    """스냅숏도 저장소 문서처럼 다시 검증한다 — 스키마가 바뀐 뒤의 옛 스냅숏은 500이 아니라 409다."""
    import json
    import types

    import pytest
    from fastapi import HTTPException

    from claw_server.refs import profile_echo, resolve_profile, resolve_snapshot

    req = types.SimpleNamespace(app=client.app)
    built = resolve_profile(req, None)
    path = client.app.state.profiles.root / "_snapshots" / f"{built.fingerprint}.json"
    snap = json.loads(path.read_text(encoding="utf-8"))
    del snap["mass"]
    path.write_text(json.dumps(snap), encoding="utf-8")
    with pytest.raises(HTTPException) as e:
        resolve_snapshot(req, profile_echo(built))
    assert e.value.status_code == 409 and "스키마" in e.value.detail
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(HTTPException) as e:
        resolve_snapshot(req, profile_echo(built))
    assert e.value.status_code == 409
    path.write_text("[]", encoding="utf-8")  # 객체가 아닌 스냅숏 — 조립 전에 막지 않으면 TypeError 500
    with pytest.raises(HTTPException) as e:
        resolve_snapshot(req, profile_echo(built))
    assert e.value.status_code == 409
    path.unlink()
    with pytest.raises(HTTPException) as e:
        resolve_snapshot(req, profile_echo(built))
    assert e.value.status_code == 409 and "없다" in e.value.detail


def test_resume_snapshot_keeps_the_saved_aircraft_identity(client, wait_job):
    """예제를 복제만 한 기체는 예제와 지문이 같다 — 재개가 스냅숏의 이름표로 기체를 바꿔 말하면 안 된다."""
    import types

    from claw_server.refs import profile_echo, resolve_profile, resolve_snapshot

    req = types.SimpleNamespace(app=client.app)
    example = resolve_profile(req, None)  # 예제 이름표로 스냅숏이 먼저 남는다
    clone = _doc(pid="my-clone", m_empty=800.0)
    clone["variants"] = []
    client.post("/api/profiles", json={"document": clone})
    from claw_server.refs import ProfileRef

    mine = resolve_profile(req, ProfileRef(id="my-clone"))
    assert mine.fingerprint == example.fingerprint
    resumed = resolve_snapshot(req, profile_echo(mine))
    assert (resumed.id, resumed.is_example, resumed.revision, resumed.source) == ("my-clone", False, 1, "snapshot")
    assert resolve_snapshot(req, None).source == "legacy-unrecorded"
