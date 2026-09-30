from types import SimpleNamespace


def test_improvement_reuses_measurements_and_saves_verified_design(client, wait_job, monkeypatch):
    from claw_server.routes import influence as route
    counters = {"eval": 0, "sweep": 0}
    monkeypatch.setattr(route, "trim_batch", lambda *a, **k: [SimpleNamespace(converged=True)])

    def evaluate(*args, **kwargs):
        counters["eval"] += 1
        return {"cases": [{"case": "A", "metrics_raw": {"alt_ts": 4 if counters["eval"] == 1 else 2}, "attribution": {}}],
                "aggregate": {"hard_fail": False, "hard_fails": []}, "aborted": False}

    def sweep(*args, **kwargs):
        counters["sweep"] += 1
        return {"rows": [], "aborted": False}

    monkeypatch.setattr(route, "evaluate", evaluate)
    monkeypatch.setattr(route, "run_sweep", sweep)
    monkeypatch.setattr(route, "constrained_proposal", lambda rows, knobs, *args, **kwargs:
        {"solvable": True, "spans": {k: .1 if i == 0 else 0 for i, k in enumerate(knobs)}})
    body = {"cases": [{"name": "A", "mach": .3, "alt": 1000, "fuel": 100}],
            "goal_mode": "custom", "goals": {"alt_ts": 3}, "max_changed": 1}

    def run():
        response = client.post("/api/influence/improve", json=body)
        assert response.status_code == 202, response.text
        done = wait_job(response.json()["id"])
        assert done["status"] == "done", done
        return done["result_id"], client.get(f"/api/results/{done['result_id']}").json()

    rid, result = run()
    assert result["accepted"]
    assert result["recommendations"]
    counts = counters.copy()
    _, repeated = run()
    assert repeated["reused"]
    assert counters == counts
    scan = client.post("/api/influence/scan", json={"cases": body["cases"], "t_step": 15}).json()
    scan_job = wait_job(scan["id"])
    assert scan_job["status"] == "done", scan_job.get("error")
    scanned = client.get(f"/api/results/{scan_job['result_id']}").json()
    assert scanned["reused_evaluation_id"] == result["baseline_id"]
    assert counters == counts
    entity = client.post("/api/design-entities", json={"profile_id": "example-delta", "name": "추천 설계"}).json()
    saved = client.post(f"/api/design-entities/{entity['id']}/versions", json={
        "expected_count": 0, "mode": "improvement", "improvement_result_id": rid, "candidate_index": 0})
    assert saved.status_code == 201, saved.text
    version = saved.json()["versions"][0]
    assert version["source"]["kind"] == "improvement"
    assert version["evaluations"][0]["result_id"] == result["candidates"][0]["evaluation_id"]
    body["t_step"] = 16
    run()
    assert counters["eval"] > counts["eval"], "변경된 기동 조건의 과거 평가를 재사용하면 안 됩니다"


def test_improvement_rejects_invalid_goal_before_job(client):
    response = client.post("/api/influence/improve", json={
        "cases": [{"name": "A", "mach": .3, "alt": 1000, "fuel": 100}],
        "goal_mode": "custom", "goals": {"alt_ts": -1}})
    assert response.status_code == 422


def test_already_met_does_not_tune_or_save_duplicate(client, wait_job, monkeypatch):
    from claw_server.routes import influence as route
    monkeypatch.setattr(route, "trim_batch", lambda *a, **k: [SimpleNamespace(converged=True)])
    monkeypatch.setattr(route, "evaluate", lambda *a, **k: {
        "cases": [{"case": "A", "metrics_raw": {"alt_ts": 2}}],
        "aggregate": {"hard_fail": False}})
    def unexpected(*args, **kwargs):
        raise AssertionError("이미 목표를 충족하면 감도 측정을 하지 않는다")
    monkeypatch.setattr(route, "run_sweep", unexpected)
    response = client.post("/api/influence/improve", json={
        "cases": [{"name": "A", "mach": .3, "alt": 1000, "fuel": 100}],
        "goal_mode": "custom", "goals": {"alt_ts": 3}})
    done = wait_job(response.json()["id"])
    assert done["status"] == "done", done
    result = client.get(f"/api/results/{done['result_id']}").json()
    assert result["accepted"] and result["candidates"][0]["unchanged"]
    entity = client.post("/api/design-entities", json={"profile_id": "example-delta", "name": "중복 방지"}).json()
    response = client.post(f"/api/design-entities/{entity['id']}/versions", json={
        "expected_count": 0, "mode": "improvement", "improvement_result_id": done["result_id"], "candidate_index": 0})
    assert response.status_code == 422


def test_real_improvement_pipeline(client, wait_job):
    response = client.post("/api/influence/improve", json={
        "cases": [{"name": "A", "mach": .3, "alt": 1000, "fuel": 100}],
        "goal_mode": "custom", "goals": {"alt_rms": 0},
        "iterations": 1, "max_changed": 1, "t_settle": .05, "t_step": .15})
    assert response.status_code == 202, response.text
    done = wait_job(response.json()["id"])
    assert done["status"] == "done", done
    result = client.get(f"/api/results/{done['result_id']}").json()
    assert result["recommendations"]
    assert result["candidates"]
    assert not result["accepted"], "짧은 기동에서 오차 0 목표를 달성했다고 표시하면 안 된다"


def test_recommended_mode_includes_configured_margin_goal(client, wait_job, monkeypatch):
    from claw_server.routes import influence as route
    monkeypatch.setattr(route, "trim_batch", lambda *a, **k: [SimpleNamespace(converged=True)])
    monkeypatch.setattr(route, "evaluate", lambda *a, **k: {
        "cases": [{"case": "A", "metrics_raw": {"alt_rms": 4, "spd_rms": 1, "hdg_rms": .05},
                   "stages": {"margins": {"loops": {
                       "pitch_att": {"margins": {"gm_db": 7, "pm_deg": 50}}}}}}],
        "aggregate": {"hard_fail": False}})
    monkeypatch.setattr(route, "run_sweep", lambda *a, **k: {
        "rows": [{"case": "A", "label": "base", "metrics": {"alt_rms": 4}}]})
    measured = []
    def enrich(rows, *args, **kwargs):
        rows["rows"][0]["metrics"]["gm.pitch_att"] = 7
        measured.append(True)
    monkeypatch.setattr(route, "enrich_sweep_linear", enrich)
    monkeypatch.setattr(route, "constrained_proposal", lambda *a, **k: {
        "solvable": False, "reason": "목표 범위 밖"})
    response = client.post("/api/influence/improve", json={
        "cases": [{"name": "A", "mach": .3, "alt": 1000, "fuel": 100}],
        "goal_mode": "recommended", "iterations": 1})
    done = wait_job(response.json()["id"])
    assert done["status"] == "done", done
    result = client.get(f"/api/results/{done['result_id']}").json()
    assert result["goals"]["gm.pitch_att"] == 8
    assert measured
    assert not result["accepted"]


def test_sensitivity_subset_preserves_full_case_evaluation(client, wait_job, monkeypatch):
    from claw_server.routes import influence as route
    seen = {"trim": [], "evaluate": [], "sweep": []}
    def trims(_ac, cases, **kwargs):
        seen["trim"].append(len(cases))
        return [SimpleNamespace(converged=True, case=c) for c in cases]
    def evaluate(_ac, trs, *_args, **kwargs):
        seen["evaluate"].append(len(trs))
        return {"cases": [{"case": tr.case.name, "metrics_raw": {"alt_ts": 5}}
                          for tr in trs], "aggregate": {"hard_fail": False}}
    def sweep(_ac, trs, *_args, **kwargs):
        seen["sweep"].append(len(trs))
        return {"rows": [], "aborted": False}
    monkeypatch.setattr(route, "trim_batch", trims)
    monkeypatch.setattr(route, "evaluate", evaluate)
    monkeypatch.setattr(route, "run_sweep", sweep)
    monkeypatch.setattr(route, "constrained_proposal", lambda *a, **k: {
        "solvable": False, "reason": "범위 밖"})
    cases = [{"name": f"P{i}", "mach": .3, "alt": 1000, "fuel": 100}
             for i in range(5)]
    response = client.post("/api/influence/improve", json={
        "cases": cases, "goal_mode": "custom", "goals": {"alt_ts": 3}, "iterations": 1})
    done = wait_job(response.json()["id"])
    assert done["status"] == "done", done
    assert seen == {"trim": [5], "evaluate": [5], "sweep": [4]}
    result = client.get(f"/api/results/{done['result_id']}").json()
    assert len(result["candidates"][0]["sensitivity_cases"]) == 4
