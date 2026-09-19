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


def test_form_spec_is_served_and_does_not_shadow_profile_ids(client):
    form = client.get("/api/profiles/_form")
    assert form.status_code == 200
    assert [s["key"] for s in form.json()["sections"]][:3] == ["geometry", "aero", "stall"]
    assert "PropEngine" in form.json()["registry"]["propulsion"]
    # `_`로 시작하는 id는 저장소가 거부한다 — 폼 경로가 실제 기체를 가릴 수 없다
    assert client.post("/api/profiles", json={"document": _doc(pid="_form")}).status_code == 422


def test_aero_slice_draws_from_the_posted_document(client):
    """저장하지 않은 문서로도 곡선을 낸다 — 편집기에서 표를 반입한 직후 보는 자리."""
    doc = _doc()
    body = {"document": doc, "along": "alpha", "start": -0.1, "stop": 0.4, "n": 11, "fixed": {"mach": 0.4}}
    r = client.post("/api/profiles/aero-slice", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["x"]) == 11 and len(out["coefficients"]["CL"]) == 11
    assert out["stall"]["table_at"] is not None and out["fixed"]["mach"] == 0.4
    assert client.post("/api/profiles/aero-slice", json={**body, "variant": "full-stores"}).status_code == 200
    assert client.post("/api/profiles/aero-slice", json={**body, "variant": "nope"}).status_code == 422
    assert client.post("/api/profiles/aero-slice", json={**body, "along": "qhat"}).status_code == 422
    assert client.post("/api/profiles/aero-slice", json={**body, "n": 1000}).status_code == 422
    bad = _doc()
    bad["aero"]["coefficients"]["CL"][0]["k"] = {"table": {"axes": {"zzz": [0.0, 1.0]}, "data": [1.0, 2.0],
                                                           "extrapolate": "clip"}}
    r = client.post("/api/profiles/aero-slice", json={**body, "document": bad})
    assert r.status_code == 422 and r.json()["detail"]["path"] == "/aero/coefficients/CL/0/k/table/axes/zzz"


def test_aero_stability_derivatives_and_judgments(client):
    """정적 안정성 도함수 — 엔진 stability_slice 통과(도함수 3종·부호 판정·위반 구간)."""
    body = {"document": _doc(), "start": -0.1, "stop": 0.3, "n": 9, "fixed": {"mach": 0.4}}
    r = client.post("/api/profiles/aero-stability", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert set(out["derivatives"]) == {"Cl_beta", "Cn_beta", "Cm_alpha"}
    assert len(out["derivatives"]["Cl_beta"]) == 9 and out["fixed"]["mach"] == 0.4
    for j in out["judgments"].values():
        assert j["stable_sign"] in ("+", "-") and j["all_ok"] is (j["violations"] == [])
    assert client.post("/api/profiles/aero-stability", json={**body, "variant": "nope"}).status_code == 422
    assert client.post("/api/profiles/aero-stability", json={**body, "n": 1000}).status_code == 422
    assert client.post("/api/profiles/aero-stability",
                       json={**body, "fixed": {"V": 1.0}}).status_code == 422


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
    listing = client.get("/api/profiles").json()
    # 목록을 죽이지 않되 숨기지도 않는다 — 복구(삭제)할 id를 화면이 알아야 한다
    assert [p["id"] for p in listing] == ["example-delta", "heavy-delta"]
    assert listing[1]["unreadable"] is True and "heavy-delta" in listing[1]["reason"]


def test_health_says_whether_saved_aircraft_survive_a_restart(tmp_path, monkeypatch):
    """공개 데모(휘발 디스크)에서 "저장했는데 없어졌다"가 버그로 읽히지 않게 — 배포가 알려 준 대로 전한다."""
    from fastapi.testclient import TestClient

    from claw_server import create_app

    with TestClient(create_app(data_dir=tmp_path / "a")) as c:
        assert c.get("/api/health").json()["profile_store"] == {"volatile": False}
    monkeypatch.setenv("CLAW_PROFILE_VOLATILE", "1")
    with TestClient(create_app(data_dir=tmp_path / "b")) as c:
        assert c.get("/api/health").json()["profile_store"] == {"volatile": True}
    with TestClient(create_app(data_dir=tmp_path / "c", profile_volatile=False)) as c:
        assert c.get("/api/health").json()["profile_store"] == {"volatile": False}
    with TestClient(create_app(data_dir=tmp_path / "d", profile_volatile="0")) as c:  # bool("0")은 참이다
        assert c.get("/api/health").json()["profile_store"] == {"volatile": False}


def test_list_keeps_an_aircraft_whose_revision_file_is_missing(client):
    """head는 있는데 리비전 파일이 없다 — 「지워짐」과 달리 같은 id 생성이 409라, 목록이 숨기면 복구할 길이 없다."""
    client.post("/api/profiles", json={"document": _doc()})
    (client.app.state.profiles.root / "heavy-delta" / "rev-1.json").unlink()
    listing = client.get("/api/profiles").json()
    assert [p["id"] for p in listing] == [EXAMPLE_ID, "heavy-delta"]
    assert listing[1]["unreadable"] is True
    assert client.delete("/api/profiles/heavy-delta").status_code == 204  # 목록이 알려 준 id로 치운다
    assert [p["id"] for p in client.get("/api/profiles").json()] == [EXAMPLE_ID]


def test_list_keeps_an_aircraft_whose_summary_fails(client, monkeypatch):
    """조립 단계의 KeyError(레지스트리 오류가 KeyError다)가 "지워진 기체"로 오인돼 목록에서 사라지지 않는다."""
    from claw.params.registry import RegistryError

    from claw_server.profiles import ProfileStore

    client.post("/api/profiles", json={"document": _doc()})
    real = ProfileStore.summary

    def failing(doc, revision):
        if doc["id"] == "heavy-delta":
            raise RegistryError("없는 추진 형식")
        return real(doc, revision)

    monkeypatch.setattr(ProfileStore, "summary", staticmethod(failing))
    listing = client.get("/api/profiles").json()
    assert [p["id"] for p in listing] == [EXAMPLE_ID, "heavy-delta"]
    assert listing[1]["unreadable"] is True and "RegistryError" in listing[1]["reason"]


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


def _seedable(profile_id):
    from claw.profile import load_example

    doc = load_example()
    doc.update(id=profile_id, name="시드 기체", is_example=False)
    doc["law"]["design"] = doc["law"]["schedule"] = doc["law"]["alloc"] = None
    return doc


def test_quick_seed_job_writes_a_seeded_revision(client, wait_job):
    """게인이 빈 기체 → 잡이 부호·크기를 재서 새 리비전으로 쓴다. 출처에 잡 id·기준 리비전이 남는다."""
    from claw.profile import EXAMPLE_ID

    r = client.post("/api/profiles", json={"document": _seedable("seedme")})
    assert r.status_code == 201
    rev = r.json()["revision"]
    listing = {p["id"]: p for p in client.get("/api/profiles").json()}
    assert listing["seedme"]["design_source"] is None and listing[EXAMPLE_ID]["design_source"] == "example"

    assert client.post(f"/api/profiles/{EXAMPLE_ID}/quick-seed", json={"base_revision": 1}).status_code == 403
    assert client.post("/api/profiles/nope/quick-seed", json={"base_revision": 1}).status_code == 404
    stale = client.post("/api/profiles/seedme/quick-seed", json={"base_revision": rev + 1})
    assert stale.status_code == 409 and stale.json()["detail"]["head"] == rev

    r = client.post("/api/profiles/seedme/quick-seed", json={"base_revision": rev})
    assert r.status_code == 202 and r.headers["Location"] == f"/api/jobs/{r.json()['id']}"
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done", j
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["kind"] == "quick_seed" and body["seed"]["ok"] and body["written"] is True
    assert (body["profile"]["base_revision"], body["profile"]["revision"]) == (rev, rev + 1)

    got = client.get("/api/profiles/seedme").json()
    assert got["revision"] == rev + 1
    law = got["document"]["law"]
    assert law["design"]["provenance"]["source"] == "quick_seed"
    assert (law["design"]["provenance"]["job"], law["design"]["provenance"]["base_revision"]) == (j["id"], rev)
    assert law["schedule"]["rule"] == "qbar_inverse"  # 스케줄이 없던 기체라 새로 만들었다
    assert {p["id"]: p for p in client.get("/api/profiles").json()}["seedme"]["design_source"] == "quick_seed"
    meta = next(m for m in client.get("/api/results").json() if m["id"] == j["result_id"])
    assert meta["kind"] == "quick_seed" and meta["status"] == "written"


def test_quick_seed_does_not_overwrite_a_revision_saved_meanwhile(client, wait_job, monkeypatch):
    import claw_server.routes.profiles as routes

    rev = client.post("/api/profiles", json={"document": _seedable("race")}).json()["revision"]
    real = routes.quick_seed

    def racing(built, **kw):
        out = real(built, **kw)
        store = client.app.state.profiles
        cur, head = store.get("race")
        cur["description"] = "탐색하는 사이 저장한 편집"
        store.update("race", cur, head)
        return out

    monkeypatch.setattr(routes, "quick_seed", racing)
    j = wait_job(client.post("/api/profiles/race/quick-seed", json={"base_revision": rev}).json()["id"], timeout=120.0)
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["seed"]["ok"] and body["written"] is False and body["conflict_head"] == rev + 1
    got = client.get("/api/profiles/race").json()
    assert got["revision"] == rev + 1 and got["document"]["description"] == "탐색하는 사이 저장한 편집"
    assert got["document"]["law"]["design"] is None


def test_derive_de_trim_job_writes_a_derived_table_that_goes_stale_with_the_plant(client, wait_job, monkeypatch):
    """도출 잡이 할당 표를 새 리비전으로 쓰고, 플랜트를 고치면 목록이 낡았다고 말한다."""
    import claw_server.routes.profiles as routes

    real = routes.derive_de_trim
    monkeypatch.setattr(routes, "derive_de_trim", lambda built, **kw: real(
        built, variants=kw.get("variants", ()), alts=(0.0, 3000.0), fuel_fracs=(0.5, 1.0), check_step=0.02,
        on_progress=kw.get("on_progress")))
    doc = _seedable("trimme")
    from claw.profile import load_example

    doc["law"] = load_example()["law"]  # 게인·스케줄·손으로 넣은 표가 있는 기체
    rev = client.post("/api/profiles", json={"document": doc}).json()["revision"]
    row = {p["id"]: p for p in client.get("/api/profiles").json()}["trimme"]
    assert row["de_trim"] == {"source": "explicit", "stale": False, "stale_variants": []}
    assert client.post("/api/profiles/trimme/derive-de-trim",
                       json={"base_revision": rev, "check_step": 0.0001}).status_code == 422  # 검사 간격 하한

    j = wait_job(client.post("/api/profiles/trimme/derive-de-trim", json={"base_revision": rev}).json()["id"],
                 timeout=120.0)
    assert j["status"] == "done", j
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["kind"] == "derive_de_trim" and body["derive"]["ok"] and body["written"]
    got = client.get("/api/profiles/trimme").json()
    de_trim = got["document"]["law"]["alloc"]["de_trim"]
    assert de_trim["source"] == "derived" and de_trim["provenance"]["job"] == j["id"]
    assert de_trim["provenance"]["plant_fingerprint"] == got["plant_fingerprint"]
    assert {p["id"]: p for p in client.get("/api/profiles").json()}["trimme"]["de_trim"] == {
        "source": "derived", "stale": False, "stale_variants": []}

    heavier = got["document"]
    heavier["mass"]["m_empty"] *= 1.1
    assert client.put("/api/profiles/trimme", json={"base_revision": got["revision"], "document": heavier}).status_code == 200
    # 예제에서 온 EO/IR형 변형은 표시 모델만 바꿔 플랜트가 기본 문서와 같다 — 기본 문서와 함께 낡는다
    assert {p["id"]: p for p in client.get("/api/profiles").json()}["trimme"]["de_trim"] == {
        "source": "derived", "stale": True, "stale_variants": ["eoir"]}
    # 낡은 표로는 법칙을 조립하지 않는다 — 시뮬 제출이 경로째 422 (500도, 조용한 옛 표 사용도 아니다)
    from tests.claw_server.routes.test_sim import _hold_mission

    r = client.post("/api/sim/run", json={**_hold_mission(t_end=2.0), "profile": {"id": "trimme"}})
    assert r.status_code == 422 and "/law/alloc/de_trim" in str(r.json()["detail"])


def test_results_from_seeded_gains_say_so():
    """초기 탐색 게인 기체의 결과 profile 블록만 design_source를 싣는다 — 예제 결과 블록(골든)은 그대로다."""
    import copy

    from claw.profile import build_profile, example_profile, load_example
    from claw_server.refs import profile_echo

    assert "design_source" not in profile_echo(example_profile())
    doc = load_example()
    doc.update(id="seeded", is_example=False)
    doc["law"]["design"] = copy.deepcopy(doc["law"]["design"])
    doc["law"]["design"]["provenance"] = {"source": "quick_seed", "ok": True}
    assert profile_echo(build_profile(doc))["design_source"] == "quick_seed"


def test_profile_job_keeps_its_result_when_the_aircraft_is_deleted_meanwhile(client, wait_job, monkeypatch):
    """계산은 끝났는데 기체가 지워졌다 — 잡이 오류로 죽어 결과를 잃지 않고, 쓰지 못한 사유를 싣는다."""
    import claw_server.routes.profiles as routes

    rev = client.post("/api/profiles", json={"document": _seedable("gone")}).json()["revision"]
    real = routes.quick_seed

    def deleting(built, **kw):
        out = real(built, **kw)
        client.app.state.profiles.delete("gone")
        return out

    monkeypatch.setattr(routes, "quick_seed", deleting)
    j = wait_job(client.post("/api/profiles/gone/quick-seed", json={"base_revision": rev}).json()["id"], timeout=120.0)
    assert j["status"] == "done", j
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["seed"]["ok"] and body["written"] is False and "KeyError" in body["write_error"]


def test_rejected_seed_is_not_written(client, wait_job, monkeypatch):
    import claw_server.routes.profiles as routes

    rev = client.post("/api/profiles", json={"document": _seedable("nope-seed")}).json()["revision"]
    real = routes.quick_seed
    monkeypatch.setattr(routes, "quick_seed", lambda built, **kw: {**real(built, **kw), "ok": False,
                                                                     "reason": "seed_verify_failed"})
    j = wait_job(client.post("/api/profiles/nope-seed/quick-seed", json={"base_revision": rev}).json()["id"],
                 timeout=120.0)
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["written"] is False and body["write_error"] is None
    assert client.get("/api/profiles/nope-seed").json()["revision"] == rev


def test_derive_job_measures_the_variants_and_names_the_ones_added_later(client, wait_job, monkeypatch):
    """서버 도출 잡이 형상 변형까지 넘긴다 — 안 넘기면 플랜트를 바꾸는 변형이 도출 직후부터 낡은 표로 막힌다."""
    import claw_server.routes.profiles as routes
    from claw.profile import load_example

    real = routes.derive_de_trim
    monkeypatch.setattr(routes, "derive_de_trim", lambda built, **kw: real(
        built, variants=kw.get("variants", ()), machs=(0.3, 0.5), alts=(1000.0,), fuel_fracs=(1.0,), check_step=0.1,
        on_progress=kw.get("on_progress")))
    doc = _seedable("varitrim")
    doc["law"] = load_example()["law"]
    doc["variants"] = [{"id": "heavy", "name": "무거움", "patch": {"/mass/m_empty": doc["mass"]["m_empty"] * 1.05}}]
    rev = client.post("/api/profiles", json={"document": doc}).json()["revision"]
    j = wait_job(client.post("/api/profiles/varitrim/derive-de-trim", json={"base_revision": rev}).json()["id"],
                 timeout=120.0)
    got = client.get("/api/profiles/varitrim").json()
    assert got["document"]["law"]["alloc"]["de_trim"]["provenance"]["configurations"] == ["base", "heavy"], j
    row = {p["id"]: p for p in client.get("/api/profiles").json()}["varitrim"]
    assert row["de_trim"] == {"source": "derived", "stale": False, "stale_variants": []}

    later = got["document"]
    later["variants"].append({"id": "heavier", "name": "더 무거움", "patch": {"/mass/m_empty": later["mass"]["m_empty"] * 1.2}})
    assert client.put("/api/profiles/varitrim", json={"base_revision": got["revision"], "document": later}).status_code == 200
    row = {p["id"]: p for p in client.get("/api/profiles").json()}["varitrim"]
    assert row["de_trim"] == {"source": "derived", "stale": False, "stale_variants": ["heavier"]}


def test_profile_job_cancel_before_the_write_does_not_write_and_after_it_stays_done(client, wait_job, monkeypatch):
    """취소가 쓰기 전에 들어오면 쓰지 않고(「취소됨」), 쓰는 도중·뒤에 들어오면 쓴 결과가 「취소됨」으로 강등되지 않는다."""
    import claw_server.routes.profiles as routes

    store = client.app.state.profiles
    real_seed = routes.quick_seed

    def cancel_then_return(built, **kw):
        out = real_seed(built, **kw)
        for job in client.app.state.jobs.list():
            if job.kind == "quick_seed" and job.status == "running":
                job.request_cancel()
        return out

    rev = client.post("/api/profiles", json={"document": _seedable("cancel-early")}).json()["revision"]
    monkeypatch.setattr(routes, "quick_seed", cancel_then_return)
    j = wait_job(client.post("/api/profiles/cancel-early/quick-seed", json={"base_revision": rev}).json()["id"],
                 timeout=120.0)
    assert j["status"] == "cancelled"
    assert client.get(f"/api/results/{j['result_id']}").json()["written"] is False
    assert client.get("/api/profiles/cancel-early").json()["revision"] == rev

    monkeypatch.setattr(routes, "quick_seed", real_seed)
    real_update = store.update

    def update_then_cancel(*a, **kw):
        out = real_update(*a, **kw)
        for job in client.app.state.jobs.list():
            if job.kind == "quick_seed" and job.status == "running":
                job.request_cancel()
        return out

    monkeypatch.setattr(store, "update", update_then_cancel)
    rev = client.post("/api/profiles", json={"document": _seedable("cancel-late")}).json()["revision"]
    j = wait_job(client.post("/api/profiles/cancel-late/quick-seed", json={"base_revision": rev}).json()["id"],
                 timeout=120.0)
    assert j["status"] == "done"
    assert client.get(f"/api/results/{j['result_id']}").json()["written"] is True
    assert client.get("/api/profiles/cancel-late").json()["revision"] == rev + 1
