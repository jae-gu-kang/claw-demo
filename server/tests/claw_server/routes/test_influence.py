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
    # 66/23 — 이륙·착륙 도입으로 종방향 축(승강률 4노드·피치 1노드·θ 출처 Switch 2단)과
    # 그 입력 4개(cmd_pitch·cmd_hdot·pitch_on·hdot_on)가 늘었다 (엔진 test_influence와 한 쌍)
    assert kinds["ir"] == 66 and kinds["input"] == 23 and kinds["output"] == 7
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


# ---------- 진단 (처방 카드) ----------


def _run_sim(client, wait_job, **over):
    body = {
        "trim": {"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0},
        "modes": [{"name": "hold", "speed": 199.0, "alt": 1000.0, "heading": 0.0,
                   "exit": ["time_ge", 1e9]}],
        "t_end": 2.0,
    }
    body.update(over)
    j = wait_job(client.post("/api/sim/run", json=body).json()["id"], timeout=120.0)
    assert j["status"] == "done"
    return j["result_id"]


def test_diagnose_round_trip(client, wait_job):
    """저장된 sim 결과 → 진단 응답 — 지표·판정·처방·문턱이 한 덩이로 온다."""
    rid = _run_sim(client, wait_job)
    r = client.post("/api/influence/diagnose", json={"result_id": rid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result_id"] == rid
    assert set(body["metrics"]) >= {"alt_rms", "surf_sat_frac", "limiter_frac"}
    assert body["metrics"]["alt_rms"] is not None
    assert isinstance(body["findings"], list) and isinstance(body["prescriptions"], list)
    assert body["thresholds"]["sat_frac"] > 0
    json.dumps(body, allow_nan=False)  # NaN을 흘리면 브라우저 파싱이 터진다


def test_diagnose_missing_and_wrong_kind(client, wait_job):
    assert client.post("/api/influence/diagnose",
                       json={"result_id": "nope"}).status_code == 404
    tj = wait_job(client.post("/api/trim/batch", json={
        "cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]}).json()["id"])
    assert client.post("/api/influence/diagnose",
                       json={"result_id": tj["result_id"]}).status_code == 409


# ---------- 2단 개루프 (openloop_delta) ----------


def test_openloop_job_round_trip(client, wait_job):
    """게인 Δ → 케이스별 마진 변화 — 잡 기반 202, 스케줄 상수는 분리 보고."""
    r = client.post("/api/influence/openloop", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "params": ["table.pitch.k_rate", "fcl/ScasAxis.pitch.kp"],
        "fingerprint": "fp-ol",
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert res["kind"] == "influence_openloop"
    assert res["cases"] == ["design"]
    assert res["params"]["fcl/ScasAxis.pitch.kp"]["status"] == "overridden"
    entry = res["params"]["table.pitch.k_rate"]["loops"]["pitch_rate"]["design"]
    assert entry["delta"]["pm_deg"] is not None
    json.dumps(res, allow_nan=False)  # inf 마진은 null로 직렬화돼야 한다


def test_openloop_unknown_param_is_422(client):
    r = client.post("/api/influence/openloop", json={
        "cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "params": ["없는.자리"],
    })
    assert r.status_code == 422


# ---------- 3단 폐루프 스윕 (closedloop_sweep) ----------


def test_sweep_job_round_trip(client, wait_job):
    """처방 부분공간 스윕 — base + 처방 런의 지표와 Δ가 행으로 온다."""
    r = client.post("/api/influence/sweep", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "knobs": ["table.pitch.kp"],
        "span": [0.1],
        "t_settle": 2.0, "t_step": 4.0,
        "fingerprint": "fp-sweep",
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert res["kind"] == "influence_sweep"
    labels = [row["label"] for row in res["rows"]]
    assert labels == ["base", "table.pitch.kp@+0.1"]
    base, run = res["rows"]
    assert base["delta"] is None  # 기준런 — Δ의 기준이지 Δ가 아니다
    assert run["metrics"]["alt_rms"] is not None
    assert run["delta"]["alt_rms"] is not None
    assert base["fingerprint"] != run["fingerprint"]
    json.dumps(res, allow_nan=False)


def test_sweep_pair_nonadditivity(client, wait_job):
    """쌍 (A, B, A+B) 3점 — 비가산성이 "동시에 바꿔야 하는가"의 정량 답이다."""
    r = client.post("/api/influence/sweep", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "knobs": [],
        "pairs": [["table.pitch.kp", "table.pitch.k_rate"]],
        "t_settle": 2.0, "t_step": 4.0,
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert len(res["rows"]) == 4  # base + A + B + AB
    na = res["nonadditivity"]
    assert len(na) == 1 and na[0]["case"] == "design"
    assert na[0]["knobs"] == ["table.pitch.kp", "table.pitch.k_rate"]
    assert na[0]["values"]["alt_rms"] is not None


def test_sweep_validation(client):
    # 오타 knob은 제출 시점 422 — 잡이 돌고 나서 실패하면 트림 비용을 지불한다
    assert client.post("/api/influence/sweep", json={
        "cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "knobs": ["없는.자리"],
    }).status_code == 422
    # 흔들 것이 없는 스윕은 무의미 구성
    assert client.post("/api/influence/sweep", json={
        "cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "knobs": [],
    }).status_code == 422


# ---------- 3단 A 전 케이스 스캔 (base 런 + diagnose_grid) ----------


def test_scan_job_round_trip(client, wait_job):
    """전 케이스 base 스캔 — 케이스마다 base 런 1개 + 국소성 판정(grid)이 온다."""
    r = client.post("/api/influence/scan", json={
        "cases": [{"name": "c1", "mach": 0.5, "alt": 1000.0, "fuel": 200.0},
                  {"name": "c2", "mach": 0.7, "alt": 1000.0, "fuel": 200.0}],
        "t_settle": 2.0, "t_step": 4.0,
        "fingerprint": "fp-scan",
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert res["kind"] == "influence_scan"
    assert [row["label"] for row in res["rows"]] == ["base", "base"]
    assert [row["case"] for row in res["rows"]] == ["c1", "c2"]
    g = res["grid"]["metrics"]["alt_rms"]
    assert g["n_cases"] == 2
    assert g["verdict"] in {"ok", "local", "global"}
    assert isinstance(g["bad_cases"], list)
    assert res["grid"]["local_frac"] > 0
    json.dumps(res, allow_nan=False)


def test_cases_cap_is_422(client):
    """격자 상한 — 오타 격자(간격 0.001 등)가 단일 워커를 시간 단위로 점유하지 않게."""
    cases = [{"mach": 0.5 + i * 1e-4, "alt": 1000.0, "fuel": 200.0}
             for i in range(201)]
    assert client.post("/api/influence/scan",
                       json={"cases": cases}).status_code == 422
    assert client.post("/api/influence/openloop",
                       json={"cases": cases}).status_code == 422
    assert client.post("/api/influence/sweep", json={
        "cases": cases, "knobs": ["table.pitch.kp"]}).status_code == 422


def test_diagnose_fingerprint_mismatch_warns(client, wait_job):
    """계보 불일치는 오류가 아니라 경고다 — 결과는 내되 승격 판정이 실제 런 형상과
    다를 수 있음을 화면이 알아야 한다."""
    rid = _run_sim(client, wait_job, fingerprint="fp-sim-web")
    body = client.post("/api/influence/diagnose", json={"result_id": rid}).json()
    assert any("계보 불일치" in w for w in body["warnings"])
    # 지문 없이 저장된 결과는 경고 없음 (비교할 계보가 없다)
    rid2 = _run_sim(client, wait_job)
    body2 = client.post("/api/influence/diagnose", json={"result_id": rid2}).json()
    assert not any("계보 불일치" in w for w in body2["warnings"])
