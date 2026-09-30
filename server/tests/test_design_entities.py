"""Saved design revisions survive result pruning and reject mismatched evaluations."""

import copy

from claw.profile import load_example
from claw.profile import build_profile
from claw_server.design_entities import DesignEntityStore
from claw_server.refs import profile_echo


def _profile(client, pid="candidate"):
    doc = load_example()
    doc.update(id=pid, name="Candidate", is_example=False, variants=[])
    response = client.post("/api/profiles", json={"document": doc})
    assert response.status_code == 201, response.text
    return doc


def _create(client, name="Baseline"):
    response = client.post("/api/design-entities", json={"profile_id": "candidate", "name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _echo(client):
    doc = client.get("/api/profiles/candidate").json()
    built = build_profile(doc["document"], validated=True)
    built.revision = doc["revision"]
    return profile_echo(built)


def test_manual_versions_branch_and_evaluations(client):
    _profile(client)
    entity = _create(client)
    tables = {"pitch.k_rate": {"axes": {"mach": [0.2, 0.4]}, "data": [0.1, 0.2], "extrapolate": "clip"}}
    version = client.post(f"/api/design-entities/{entity['id']}/versions", json={
        "expected_count": 0, "mode": "manual", "config": {"gain_tables": tables}, "note": "first"})
    assert version.status_code == 201, version.text
    assert version.json()["versions"][0]["config"]["gain_tables"] == tables
    assert client.post(f"/api/design-entities/{entity['id']}/versions", json={
        "expected_count": 0, "mode": "manual", "config": {"gain_tables": tables}}).status_code == 409

    echo = _echo(client)
    body = {"kind": "influence_evaluate", "profile": echo, "design_input": {"gain_tables": tables},
            "aggregate": {"hard_fail": False, "hard_fails": []}, "criteria_echo": {"scheme": "test"}}
    client.app.state.store.save("evalgood", body)
    linked = client.post(f"/api/design-entities/{entity['id']}/versions/1/evaluations",
                         json={"result_id": "evalgood"})
    assert linked.status_code == 201, linked.text
    assert linked.json()["versions"][0]["evaluations"][0]["hard_fail"] is False
    next_version = client.post(f"/api/design-entities/{entity['id']}/versions", json={
        "expected_count": 1, "mode": "manual", "config": {"gain_tables": tables},
        "based_on_evaluation_id": "evalgood", "note": "evaluation follow-up"})
    assert next_version.status_code == 201, next_version.text
    assert next_version.json()["versions"][1]["based_on_evaluation_id"] == "evalgood"
    assert next_version.json()["versions"][1]["parent_version"] == 1
    assert client.post(f"/api/design-entities/{entity['id']}/versions", json={
        "expected_count": 2, "mode": "manual", "config": {"gain_tables": tables},
        "based_on_evaluation_id": "unrelated"}).status_code == 422
    client.app.state.store.save("trimgood", {"kind": "trim_batch", "profile": echo,
        "trim_reuse": {"source": "computed"}})
    attached = client.post(f"/api/design-entities/{entity['id']}/versions/2/artifacts",
                           json={"result_id": "trimgood"})
    assert attached.status_code == 201, attached.text
    assert attached.json()["versions"][1]["artifacts"][0]["result_id"] == "trimgood"
    wrong_echo = {**echo, "fingerprint": "other"}
    client.app.state.store.save("trimbad", {"kind": "trim_batch", "profile": wrong_echo})
    assert client.post(f"/api/design-entities/{entity['id']}/versions/2/artifacts",
                       json={"result_id": "trimbad"}).status_code == 409
    client.app.state.store.delete("evalgood")
    assert client.get(f"/api/design-entities/{entity['id']}").json()["versions"][0]["evaluations"]

    bad = copy.deepcopy(body)
    bad["design_input"]["gain_tables"]["pitch.k_rate"]["data"] = [9, 9]
    client.app.state.store.save("evalbad", bad)
    assert client.post(f"/api/design-entities/{entity['id']}/versions/1/evaluations",
                       json={"result_id": "evalbad"}).status_code == 409
    branch = client.post(f"/api/design-entities/{entity['id']}/branch",
                         json={"name": "Alternative", "number": 1})
    assert branch.status_code == 201, branch.text
    assert branch.json()["branch"] == {"entity_id": entity["id"], "version": 1}
    assert branch.json()["versions"][0]["evaluations"] == []
    assert branch.json()["versions"][0]["artifacts"] == []


def test_auto_result_is_copied_and_profile_is_checked(client):
    _profile(client)
    entity = _create(client)
    echo = _echo(client)
    client.app.state.store.save("autook", {"kind": "auto_design", "profile": echo,
        "gain_export": {"tables_resampled": {"pitch.k_rate": {"axes": {"mach": [0.2, 0.4]}, "data": [0.1, 0.2]}},
                        "constants": {}}})
    saved = client.post(f"/api/design-entities/{entity['id']}/versions", json={
        "expected_count": 0, "mode": "auto", "auto_result_id": "autook"})
    assert saved.status_code == 201, saved.text
    client.app.state.store.delete("autook")
    assert client.get(f"/api/design-entities/{entity['id']}").json()["versions"][0]["config"]["gain_tables"]
    other = _create(client, "Other")
    assert client.post(f"/api/design-entities/{other['id']}/versions", json={
        "expected_count": 0, "mode": "auto", "auto_result_id": "missing"}).status_code == 404


def test_apply_manual_table_and_reopen_store(client):
    _profile(client)
    item = _create(client)
    tables = {"pitch.k_rate": {"axes": {"mach": [0.2, 0.4]},
                               "data": [0.1, 0.2], "extrapolate": "clip"}}
    saved = client.post(f"/api/design-entities/{item['id']}/versions", json={
        "expected_count": 0, "mode": "manual", "config": {"gain_tables": tables}})
    assert saved.status_code == 201, saved.text
    assert client.post(f"/api/design-entities/{item['id']}/versions/1/apply",
                       json={"base_revision": 2}).status_code == 409
    applied = client.post(f"/api/design-entities/{item['id']}/versions/1/apply",
                          json={"base_revision": 1})
    assert applied.status_code == 200, applied.text
    assert applied.json()["revision"] == 2
    document = client.get("/api/profiles/candidate").json()["document"]
    assert document["law"]["gain_tables"]["provenance"]["entity_id"] == item["id"]
    assert DesignEntityStore(client.app.state.design_entities.root).get(item["id"])["versions"][0]["adopted_revision"] == 2
    branch = client.post(f"/api/design-entities/{item['id']}/branch",
                         json={"name": "Unapplied branch", "number": 1})
    assert "adopted_revision" not in branch.json()["versions"][0]

    # A document-based evaluation can be attached only to the adopted version.
    echo = _echo(client)
    client.app.state.store.save("evaldoc", {"kind": "influence_evaluate", "profile": echo,
        "design_input": {}, "aggregate": {"hard_fail": False, "hard_fails": []}})
    linked = client.post(f"/api/design-entities/{item['id']}/versions/1/evaluations",
                         json={"result_id": "evaldoc"})
    assert linked.status_code == 201, linked.text
