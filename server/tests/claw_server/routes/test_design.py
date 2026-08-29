"""자동 설계 라우트 검증 — 기본값 응답, 202 잡, 저장 스키마, 예산 422, gated 재개."""

import pytest


def _small_config(**over):
    cfg = {"n_mach": 3, "alts": [1000.0], "fuels": [200.0],
           "budget_points": 24, "budget_iters": 2, "mode": "auto"}
    cfg.update(over)
    return cfg


def test_defaults_expose_engine_config(client):
    r = client.get("/api/design/defaults")
    assert r.status_code == 200
    body = r.json()
    cfg = body["config"]
    assert cfg["mode"] == "gated"  # 기본 모드 — 승인 게이트 (사용자 확정)
    assert cfg["criteria"]["pm_min_deg"] == 45.0
    assert cfg["criteria"]["gm_min_db"] == 6.0
    assert cfg["targets"]["pm_deg"] == 50.0
    assert body["max_points"] == 200


def test_budget_and_unknown_key_rejected(client):
    r = client.post("/api/design/auto", json={"config": {"budget_points": 999}})
    assert r.status_code == 422
    r2 = client.post("/api/design/auto", json={"config": {"nope": 1}})
    assert r2.status_code == 422
    r3 = client.post("/api/design/auto", json={"config": {"criteria": {"bad_key": 1}}})
    assert r3.status_code == 422


def test_auto_design_end_to_end(client, wait_job):
    r = client.post("/api/design/auto",
                    json={"config": _small_config(), "fingerprint": "fp-ad"})
    assert r.status_code == 202
    assert r.headers["Location"].startswith("/api/jobs/")
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"

    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["kind"] == "auto_design"
    assert body["report"]["status"] in ("converged", "escalated", "budget_exhausted")
    roles = {p["role"] for p in body["points"]["points"]}
    assert "anchor" in roles
    # 스케줄 인지 검증 결과와 게인 반출이 실려 있다
    assert body["margin_out"]["cases"]
    export = body["gain_export"]
    assert export["tables"] or export["constants"]
    # 반출 테이블은 sim/codegen 페이로드에 그대로 주입 가능한 형상
    for spec in export["tables"].values():
        assert spec.get("kind") == "poly" or ("axes" in spec and "data" in spec)
    meta = client.get("/api/results").json()[0]
    assert meta["kind"] == "auto_design" and meta["fingerprint"] == "fp-ad"


def test_gated_pause_and_resume(client, wait_job):
    """조악한 적합 강제로 실패 유도 — awaiting_approval 저장 → 승인 재개 → 새 결과."""
    cfg = _small_config(mode="gated", fit_tol=10.0, max_segments=1, max_degree=1,
                        budget_iters=3)
    r = client.post("/api/design/auto", json={"config": cfg})
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    body = client.get(f"/api/results/{j['result_id']}").json()
    if body["report"]["status"] != "awaiting_approval":
        pytest.skip("이 형상에서 실패가 없다 — gated 재개는 엔진 테스트가 덮는다")
    cards = body["proposed_actions"]
    assert cards and all("verdict" in a for a in cards)
    approvable = [a["id"] for a in cards if a["action"]["type"] != "escalate"]
    assert approvable

    r2 = client.post(f"/api/design/{j['result_id']}/resume",
                     json={"approved": approvable})
    assert r2.status_code == 202
    j2 = wait_job(r2.json()["id"], timeout=300.0)
    assert j2["status"] == "done"
    body2 = client.get(f"/api/results/{j2['result_id']}").json()
    assert body2["iter_n"] >= 1
    meta2 = client.get(f"/api/results/{j2['result_id']}").json()
    assert body2["kind"] == "auto_design"
    # 계보 — 부모 결과 id가 메타에 남는다
    metas = {m["id"]: m for m in client.get("/api/results").json()}
    assert metas[j2["result_id"]]["parent"] == j["result_id"]


def test_resume_rejects_terminal_and_missing(client, wait_job):
    r = client.post("/api/design/auto", json={"config": _small_config()})
    j = wait_job(r.json()["id"], timeout=300.0)
    body = client.get(f"/api/results/{j['result_id']}").json()
    if body["report"]["status"] == "awaiting_approval":
        pytest.skip("종결 상태가 아니다")
    r2 = client.post(f"/api/design/{j['result_id']}/resume", json={"approved": ["x"]})
    assert r2.status_code == 409
    r3 = client.post("/api/design/no-such/resume", json={"approved": ["x"]})
    assert r3.status_code == 404
