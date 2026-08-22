"""영향성 라우트 계약 — 응답이 자기모순 없이 화면이 그릴 수 있는 형태인지."""

import json


def _post(client, body=None):
    r = client.post("/api/influence/structural", json=body or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_structural_returns_a_self_consistent_graph(client):
    p = _post(client)
    ids = {n["id"] for n in p["nodes"]}
    assert len(ids) == len(p["nodes"]), "노드 id 중복"
    for e in p["edges"]:
        assert e["src"] in ids and e["dst"] in ids, e


def test_structural_node_census(client):
    from collections import Counter

    kinds = Counter(n["kind"] for n in _post(client)["nodes"])
    assert kinds["ir"] == 59 and kinds["input"] == 19 and kinds["output"] == 7
    assert kinds["param"] > 50 and kinds["plant"] == 1 and kinds["metric"] == 8


def test_structural_is_json_safe(client):
    """NaN을 흘리면 브라우저 JSON.parse가 터진다 — 서버 직렬화 정책과 같은 규약."""
    json.dumps(_post(client), allow_nan=False)


def test_shape_flows_through(client):
    """형상을 바꾸면 지문도 그래프도 바뀐다 — 응답이 요청을 무시하지 않는지."""
    a = _post(client)
    b = _post(client, {"with_limiter": False})
    assert a["fingerprint"] != b["fingerprint"]
    assert b["graph"]["n_nodes"] < a["graph"]["n_nodes"]
    assert not [n for n in b["nodes"] if n["id"] == "param:fcl/AlphaLimiter.margin"]


def test_offgraph_can_be_excluded(client):
    p = _post(client, {"include_offgraph": False})
    assert not [n for n in p["nodes"] if n.get("band") == "nav"]
    assert not [e for e in p["edges"] if e["kind"] == "offgraph"]


def test_scheduled_constants_are_flagged(client):
    """무력화·미방출을 조용히 넘기면 '왜 안 먹지'를 사용자가 혼자 알아내야 한다."""
    p = _post(client)
    by_id = {n["id"]: n for n in p["nodes"]}
    assert by_id["param:fcl/ScasAxis.pitch.kp"]["overridden"] == ["scas_pitch_pid"]
    assert by_id["param:fcl/ScasAxis.pitch.k_rate"]["inert"] is True
    assert by_id["param:fcl/ScasAxis.yaw.kp"]["overridden"] == []
    assert any("게인 스케줄이 덮어써" in w for w in p["warnings"])


def test_structural_parameter_produces_ghost_nodes(client):
    """구조를 바꾸는 파라미터는 '올리면 생길' 노드를 유령으로 드러낸다."""
    p = _post(client)
    ghosts = {n["id"] for n in p["nodes"] if n["kind"] == "ghost"}
    assert {"ap_ff_t_raw", "ap_ff_t", "ap_thr_ff", "ap_thr_out"} <= ghosts
    assert all(n["appears_with"] for n in p["nodes"] if n["kind"] == "ghost")


def test_engine_rejects_bad_config_as_422(client):
    r = client.post("/api/influence/structural", json={"autopilot": {"phi_max": 99.0}})
    assert r.status_code == 422
    r = client.post("/api/influence/structural", json={"autopilot": {"없는키": 1.0}})
    assert r.status_code == 422


def test_nonfinite_is_refused(client):
    r = client.post(
        "/api/influence/structural",
        content=json.dumps({"scas": {"pitch": {"kp": float("nan")}}}),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422
    assert "비유한값" in json.dumps(r.json(), ensure_ascii=False)


def test_probe_rel_is_bounded(client):
    assert client.post("/api/influence/structural", json={"probe_rel": 0}).status_code == 422
    assert client.post("/api/influence/structural", json={"probe_rel": 2}).status_code == 422


def test_elapsed_is_reported(client):
    """동기 유지의 근거를 응답이 들고 있어야 나중에 판단이 가능하다."""
    assert _post(client)["elapsed_ms"] > 0
