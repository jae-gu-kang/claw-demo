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
    # 66 → 78: 엘레본 제어권한 배분 12노드. 델타윙은 피치·롤이 같은 네 면을 나눠 쓰는데
    # 믹서가 δe ± δa를 자른 사실을 두 축 다 몰라 적분기가 찼다 — 선회 하중만큼을 피치에
    # 먼저 떼어 두고 남은 것을 롤에 주는 배분으로 클립 자체를 없앴다.
    # 입력·출력은 안 늘었다(뱅크 명령을 재활용한다) — 늘었으면 계약이 바뀐 것이다.
    # (엔진 test_influence와 한 쌍 — 한쪽만 고치면 다른 쪽이 깨진다)
    assert kinds["ir"] == 78 and kinds["input"] == 23 and kinds["output"] == 7
    # 지표 12 → 27: A/B/C 재편이 응답특성(축별 Tr·Ts·Mp·sse 12종)·잔여 권한 2종·
    # 포화 최장 지속을 추가 (키는 전부 신규 — 기존 키 rename 없음)
    assert kinds["param"] > 50 and kinds["plant"] == 1 and kinds["metric"] == 27


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
        # M0.7은 프로펠러 전환으로 수평비행 불가 — 두 케이스 다 엔벨로프 안이어야
        # base 행이 둘 나온다 (plant/prop.py, 1000 m·연료 200 kg 상단 M0.595)
        "cases": [{"name": "c1", "mach": 0.4, "alt": 1000.0, "fuel": 200.0},
                  {"name": "c2", "mach": 0.5, "alt": 1000.0, "fuel": 200.0}],
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


def test_sweep_rejects_impossible_shape_at_submit_not_mid_job(client):
    """기체가 낼 수 없는 손잡이는 **제출 시점 422** — 잡 안에서 터지면 안 된다.

    k_diff_thr는 param_universe에 실존하는 손잡이라 계획은 세워진다. 그런데 데모
    기체는 단발이라 그 조합은 예외 없이 실수다. 잡 안에서 터뜨리면 202를 준 뒤
    트림 배치와 base 런을 다 돌리고 나서 **완료된 행이 통째로 버려진다** — 이
    라우트가 독스트링에 적어 둔 "무의미 구성은 제출 시점 422" 계약이 그것이다.
    """
    cases = [{"name": "c", "mach": 0.6, "alt": 1000.0, "fuel": 300.0}]
    r = client.post("/api/influence/sweep",
                    json={"cases": cases, "knobs": ["fcl/Mixer.k_diff_thr"]})
    assert r.status_code == 422
    assert "차동추력" in r.json()["detail"]
    # 형상에 직접 실어 보내는 경로(scan)도 같은 자리에서 걸린다
    r2 = client.post("/api/influence/scan",
                     json={"cases": cases, "mixer": {"k_diff_thr": 0.1}})
    assert r2.status_code == 422
    # 정상 손잡이는 그대로 202 — 가드가 전체를 막아 버리지 않는다
    r3 = client.post("/api/influence/sweep",
                     json={"cases": cases, "knobs": ["fcl/Autopilot.kp_alt"]})
    assert r3.status_code == 202


# ---------- A/B/C 평가 (evaluate·verify) ----------


def test_criteria_defaults_echo(client):
    """웹은 문턱·어휘를 재기술하지 않는다 — 기준·카드·체크·검증 어휘 전부 echo."""
    r = client.get("/api/influence/criteria/defaults")
    assert r.status_code == 200
    body = r.json()
    assert body["criteria"]["schema_version"] == 2
    assert body["criteria"]["actuator"]["sat_frac_max"] == 0.05
    assert [c["key"] for c in body["cards"]][:3] == ["mode_stability", "gm", "pm"]
    assert len(body["cards"]) == 7 and len(body["checks"]) == 9
    assert len(body["items"]) == 11 and len(body["verify"]) == 7
    json.dumps(body, allow_nan=False)


def test_evaluate_job_round_trip(client, wait_job):
    """카드 7 + 체크 9 + 원자료 — 지문 계보와 J·하드 게이트 규약."""
    r = client.post("/api/influence/evaluate", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "t_settle": 2.0, "t_step": 4.0,
        "fingerprint": "fp-eval",
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert res["kind"] == "influence_evaluate"
    assert [c["key"] for c in res["cards"]][:3] == ["mode_stability", "gm", "pm"]
    ch = res["checks"]
    assert ch["n_pass"] + ch["n_warn"] + ch["n_fail"] + ch["n_na"] == 9
    c = res["cases"][0]
    assert set(c["stages"]) == set(res["stage_order"])
    if c["hard_fails"]:
        assert c["J"] is None and c["J_reason"]
    assert res["criteria_fingerprint"]
    assert res["aggregate"]["hard_fail"] in (True, False)
    json.dumps(res, allow_nan=False)


def test_evaluate_depth_linear_is_sim_free(client, wait_job):
    """단계 1 — 시뮬 0. 비선형 항목은 사유를 들고 na, 선형 항목은 판정된다."""
    r = client.post("/api/influence/evaluate", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "depth": "linear",
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    st = res["cases"][0]["stages"]
    assert st["tracking"]["status"] == "na" and "linear" in st["tracking"]["note"]
    assert st["margins"]["status"] != "na"
    gm = next(c for c in res["cards"] if c["key"] == "gm")
    assert gm["value"] is not None  # 선형 카드가 실제 값을 낸다


def test_evaluate_validation_is_at_submit(client):
    """기준 오타·구 스키마·모르는 depth는 202가 아니라 제출 시점 422다."""
    base = {"cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]}
    assert client.post("/api/influence/evaluate", json={
        **base, "criteria": {"actuator": {"sat_frac_maxx": 0.1}},
    }).status_code == 422
    assert client.post("/api/influence/evaluate", json={
        **base, "criteria": {"schema_version": 1},
    }).status_code == 422
    assert client.post("/api/influence/evaluate", json={
        **base, "criteria": {"trim": {"de_frac_warn": 0.4}},  # v1 그룹명
    }).status_code == 422
    assert client.post("/api/influence/evaluate", json={
        **base, "depth": "quick",
    }).status_code == 422


def test_verify_midpoints_multi_fuel_names_are_unique(client, wait_job):
    """중간점 이름은 mach·alt·fuel 전체를 싣는다 — 연료만 다른 격자에서 이름이
    겹치면 귀속이 조용히 다른 케이스로 바뀐다(리뷰 must-fix)."""
    r = client.post("/api/influence/verify", json={
        "cases": [
            {"name": "a1", "mach": 0.5, "alt": 1000.0, "fuel": 100.0},
            {"name": "a2", "mach": 0.5, "alt": 1000.0, "fuel": 200.0},
            {"name": "b1", "mach": 0.55, "alt": 1000.0, "fuel": 100.0},
        ],
        "depth": "linear",
        # 코너 없이 중간점만 — 축이 0이면 코너를 만들지 않는다(흔드는 시늉 금지)
        "criteria": {"robustness": {"mass_frac": 0.0, "cmalpha_frac": 0.0,
                                    "cmq_frac": 0.0}},
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    gm = res["verify"]["grid_midpoints"]
    names = [c["case"] for c in gm["cases"]]
    assert len(names) == len(set(names))  # 겹침 금지
    assert "mid/M0.525_h1000_f100" in names and "mid/M0.525_h1000_f200" in names
    assert res["verify"]["mass_cg"]["status"] == "na"  # 코너 0건 — na지 PASS가 아니다
    json.dumps(res, allow_nan=False)


def test_verify_corner_round_trip(client, wait_job):
    """강건성 코너 — 섭동 기체 재트림 + 하드 판정. CG [TBD]는 문장으로 남는다."""
    r = client.post("/api/influence/verify", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "depth": "linear", "midpoints": False,
        "criteria": {"robustness": {"mass_frac": 0.2, "cmalpha_frac": 0.0,
                                    "cmq_frac": 0.0}},
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    corners = res["verify"]["mass_cg"]["corners"]
    assert [c["label"] for c in corners] == ["mass+20%", "mass-20%"]
    assert "[TBD]" in res["verify"]["mass_cg"]["note"]
    assert res["kind"] == "influence_verify"


def test_verify_guards(client):
    """예약 접두사·총량 상한은 제출 시점 422다."""
    assert client.post("/api/influence/verify", json={
        "cases": [{"name": "mid/M0.5_h1000_f200", "mach": 0.5, "alt": 1000.0,
                   "fuel": 200.0}],
    }).status_code == 422
    # 코너 6 × 40케이스 = 240 > 200 상한
    cases = [{"name": f"c{i}", "mach": 0.4 + i * 1e-3, "alt": 1000.0,
              "fuel": 200.0} for i in range(40)]
    r = client.post("/api/influence/verify", json={
        "cases": cases, "midpoints": False,
    })
    assert r.status_code == 422
    assert "상한" in r.json()["detail"]
