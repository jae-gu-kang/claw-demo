"""영향성 라우트 계약 — 응답이 자기모순 없이 화면이 그릴 수 있는 형태인지."""

import json


def _criteria_profile(client, pid, criteria):
    """시험용 기준을 적은 기체를 만들어 그 선택(ref)을 돌려준다 — 요청 기준은 거절되므로(v1.54) 다른 기준으로
    돌리려면 그 기준을 적은 기체를 고른다(기준 통합 ① 결정)."""
    from claw.profile import load_example

    doc = load_example()
    doc.update(id=pid, name=f"시험 기준 {pid}", description="시험용", is_example=False)
    doc["criteria"] = criteria
    r = client.post("/api/profiles", json={"document": doc})
    assert r.status_code == 201, r.text
    return {"id": pid}


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
    # 78 → 80: θ 상한 마하 표 2노드(ap_theta_hi_raw 실속표 룩업 · ap_theta_hi 스칼라 상자 클램프, v1.11)
    assert kinds["ir"] == 80 and kinds["input"] == 23 and kinds["output"] == 7
    # 지표 12 → 29: 응답특성(축별 Tr·Ts·Mp·sse 12종)·잔여 권한 2종·포화 최장 지속
    # (v0.56), 추력 포화율·최소 여유 2종(v0.72) — 키는 전부 신규, rename 없음
    assert kinds["param"] > 50 and kinds["plant"] == 1 and kinds["metric"] == 34


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


def _watch_dict(seen):
    """접근 기록 dict — 엔진이 신호를 무엇을 읽는지 센다(통째로 훑으면 "*전체*")."""

    class Watch(dict):
        def __getitem__(self, k):
            seen.add(k)
            return super().__getitem__(k)

        def get(self, k, default=None):
            seen.add(k)
            return super().get(k, default)

        def __contains__(self, k):
            seen.add(k)
            return super().__contains__(k)

        def __iter__(self):
            seen.add("*전체*")
            return super().__iter__()

        def keys(self):
            seen.add("*전체*")
            return super().keys()

        def items(self):
            seen.add("*전체*")
            return super().items()

        def values(self):
            seen.add("*전체*")
            return super().values()

    return Watch


def test_diagnose_parses_only_the_signals_the_engine_reads(client, wait_job, monkeypatch):
    """진단은 DIAGNOSE_SIGNALS만 먼저 파싱한다(예제 750 s 본문에서 통째 파싱은 서버 힙 +216 MB) — 그 목록이
    엔진 diagnose_run이 실제로 읽는 신호를 다 덮는지 감시 dict로 보고, 골라 읽은 응답이 통째 읽기와 같은지 본다.
    엔진이 새 신호를 읽기 시작하면(또는 신호를 통째로 훑으면) 여기서 빨개진다."""
    from claw.pipeline.diagnose import diagnose_run
    from claw.profile import example_profile
    from claw_server.routes import influence as influence_route
    from claw_server.routes.influence import DIAGNOSE_SIGNALS, DiagnoseIn, to_shape

    rid = _run_sim(client, wait_job, t_end=4.0, actuators={"rate_max": 6.0})
    full = client.app.state.store.load(rid)
    seen = set()
    diagnose_run({**full, "signals": _watch_dict(seen)(full["signals"])},
                 to_shape(DiagnoseIn(result_id=rid), example_profile()))
    assert seen and seen <= DIAGNOSE_SIGNALS, sorted(seen - DIAGNOSE_SIGNALS)

    def body(**kw):
        r = client.post("/api/influence/diagnose", json={"result_id": rid, **kw})
        assert r.status_code == 200, r.text
        out = r.json()
        out.pop("elapsed_ms")
        return json.dumps(out, ensure_ascii=False)

    got = body()
    # 통째 읽기와 같다 — 목록을 본문의 신호 전부로 두면 골라 읽기가 곧 통째 읽기다
    monkeypatch.setattr(influence_route, "DIAGNOSE_SIGNALS", frozenset(full["signals"]))
    assert body() == got
    # 목록이 엔진보다 모자라도 답은 같다 — 목록 밖 신호는 읽는 순간 그 줄만 마저 파싱한다
    monkeypatch.setattr(influence_route, "DIAGNOSE_SIGNALS", frozenset())
    assert body() == got
    monkeypatch.undo()

    # 쓰지 않는 신호 줄은 파싱조차 하지 않는다 — 그 줄을 망가뜨려도 진단은 그대로다
    # (통째 읽기였다면 본문 전체가 손상 판정 → 404)
    assert "alpha" in full["signals"] and "alpha" not in DIAGNOSE_SIGNALS
    path = client.app.state.store.root / f"{rid}.json"
    lines = path.read_text(encoding="utf-8").split("\n")
    victim = next(i for i, ln in enumerate(lines) if ln.startswith('"alpha": '))
    lines[victim] = '"alpha": @손상@,'
    path.write_text("\n".join(lines), encoding="utf-8")
    assert body() == got


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
    # 실행 조건 기록(05 §11.13 이관 13단계) — 화면 기본값으로 고른 점도 결과가 조건을 싣는다(이름만으로는 못 되짚는다)
    assert res["conditions"] == {"cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0, "condition": "level"}]}
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
    assert res["conditions"] == {  # 스윕 저장물에 케이스 좌표가 없던 자리(이관 13단계)
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0, "condition": "level"}],
        # 실행한 기동 — 처방 확인 런의 실측 비교가 같은 기동인지 대조하는 근거(요청 t_settle·t_step·dt_plant)
        "maneuver": {"dv": 3.0, "dh": 30.0, "dpsi": 0.3, "t_settle": 2.0, "t_step": 4.0, "dt_plant": 0.01}}
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
    assert [c["name"] for c in res["conditions"]["cases"]] == ["c1", "c2"]
    assert [c["mach"] for c in res["conditions"]["cases"]] == [0.4, 0.5]
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


def _heavy_aircraft(client):
    """예제를 복제해 공허 질량만 바꾼 기체 — 지문이 예제와 다르다."""
    from claw.profile import load_example

    d = load_example()
    d.update(id="heavy-delta", name="무거운 델타", description="시험용", is_example=False, variants=[])
    d["mass"]["m_empty"] = 900.0
    assert client.post("/api/profiles", json={"document": d}).status_code == 201
    return {"id": "heavy-delta"}


def test_diagnose_warns_when_the_run_flew_another_aircraft(client, wait_job):
    """기체는 형상 지문 밖이라 형상 계보 경고로는 안 잡힌다 — 기체 지문을 따로 대조한다 (02 §5.6)."""
    heavy = _heavy_aircraft(client)
    rid = _run_sim(client, wait_job)  # 예제 기체로 난 런
    same = client.post("/api/influence/diagnose", json={"result_id": rid}).json()
    assert not any("기체 불일치" in w for w in same["warnings"])
    other = client.post("/api/influence/diagnose", json={"result_id": rid, "profile": heavy})
    assert other.status_code == 200, other.text
    assert any("기체 불일치" in w for w in other.json()["warnings"])
    # 기체 기록이 없는 옛 결과는 대조할 계보가 없다 — 경고하지 않는다
    store = client.app.state.store
    legacy = store.load(rid)
    del legacy["meta"]["profile"]
    store.save("legacy-sim", legacy, meta={"kind": "sim"})
    old = client.post("/api/influence/diagnose", json={"result_id": "legacy-sim", "profile": heavy}).json()
    assert not any("기체 불일치" in w for w in old["warnings"])


def test_prescribe_refuses_results_computed_for_another_aircraft(client):
    """다른 기체의 스윕·평가로 풀고 이 기체로 확인하면 처방과 확인이 서로 다른 기체를 말한다 — 409."""
    store = client.app.state.store
    example_fp = client.get("/api/profiles/example-delta").json()["fingerprint"]
    other = {"fingerprint": "0123456789abcdef"}
    store.save("sweep-other", {"kind": "influence_sweep", "rows": [], "profile": other},
               meta={"kind": "influence_sweep"})
    store.save("sweep-mine", {"kind": "influence_sweep", "rows": [], "profile": {"fingerprint": example_fp}},
               meta={"kind": "influence_sweep"})
    store.save("eval-other", {"kind": "influence_evaluate", "profile": other}, meta={"kind": "influence_evaluate"})
    store.save("sweep-legacy", {"kind": "influence_sweep", "rows": []}, meta={"kind": "influence_sweep"})
    store.save("eval-legacy", {"kind": "influence_evaluate"}, meta={"kind": "influence_evaluate"})
    base = {"cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}], "confirm": "none"}

    swept = client.post("/api/influence/prescribe", json={**base, "result_id": "sweep-other"})
    assert swept.status_code == 409 and "기체 불일치: 스윕" in swept.json()["detail"], swept.text
    evaluated = client.post("/api/influence/prescribe",
                            json={**base, "result_id": "sweep-mine", "eval_result_id": "eval-other"})
    assert evaluated.status_code == 409 and "기체 불일치: 평가" in evaluated.json()["detail"], evaluated.text
    # 기체 기록이 없는 옛 결과는 대조하지 않는다 — 빈 스윕이라 다음 검사(단독 런 없음)에서 멈춘다
    legacy = client.post("/api/influence/prescribe",
                         json={**base, "result_id": "sweep-legacy", "eval_result_id": "eval-legacy"})
    assert legacy.status_code == 422 and "기체 불일치" not in legacy.text, legacy.text


def test_sweep_rejects_impossible_shape_at_submit_not_mid_job(client):
    """기체가 낼 수 없는 설계변수는 **제출 시점 422** — 잡 안에서 터지면 안 된다.

    k_diff_thr는 param_universe에 실존하는 설계변수라 계획은 세워진다. 그런데 데모
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
    # 정상 설계변수는 그대로 202 — 가드가 전체를 막아 버리지 않는다
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
    assert len(body["cards"]) == 7 and len(body["checks"]) == 10
    assert len(body["items"]) == 11 and len(body["verify"]) == 7
    # 지표 척도 — 영향성 그래프의 "유의미하게 움직였나"가 이 자를 쓴다.
    # 판정선이 없는 지표는 **빠져 있어야** 한다: 있다고 말하면 화면이 없는
    # 기준으로 판정한 것처럼 보인다 (tr/ts/mp/sse는 아직 [TBD])
    scales = body["metric_scales"]
    assert scales["alt_rms"] == 10.0 and scales["hdg_rms"] == 0.1
    assert "alt_ts" not in scales and "worst_stall_margin" not in scales
    json.dumps(body, allow_nan=False)


def test_evaluate_job_round_trip(client, wait_job):
    """카드 7 + 체크 10 + 원자료 — 지문 계보와 J·하드 게이트 규약."""
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
    assert res["conditions"] == {"cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0, "condition": "level"}]}
    assert [c["key"] for c in res["cards"]][:3] == ["mode_stability", "gm", "pm"]
    ch = res["checks"]
    assert ch["n_pass"] + ch["n_warn"] + ch["n_fail"] + ch["n_na"] == 10
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
        "profile": _criteria_profile(client, "no-corners", {"robustness": {
            "mass_frac": 0.0, "cmalpha_frac": 0.0, "cmq_frac": 0.0}}),
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    gm = res["verify"]["grid_midpoints"]
    names = [c["case"] for c in gm["cases"]]
    assert len(names) == len(set(names))  # 겹침 금지
    assert "mid/M0.525_h1000_f100" in names and "mid/M0.525_h1000_f200" in names
    # 실행 조건 — 요청 케이스와 서버가 만든 중간점 둘 다 좌표로 남는다(이관 13단계)
    assert [c["name"] for c in res["conditions"]["cases"]] == ["a1", "a2", "b1"]
    mids = {c["name"]: c for c in res["conditions"]["midpoints"]}
    assert mids["mid/M0.525_h1000_f100"]["mach"] == 0.525 and mids["mid/M0.525_h1000_f100"]["fuel"] == 100.0
    assert res["verify"]["mass_cg"]["status"] == "na"  # 코너 0건 — na지 PASS가 아니다
    json.dumps(res, allow_nan=False)


def test_verify_corner_round_trip(client, wait_job):
    """강건성 코너 — 섭동 기체 재트림 + 하드 판정. CG [TBD]는 문장으로 남는다."""
    r = client.post("/api/influence/verify", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "depth": "linear", "midpoints": False,
        "profile": _criteria_profile(client, "mass-only", {"robustness": {
            "mass_frac": 0.2, "cmalpha_frac": 0.0, "cmq_frac": 0.0}}),
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


# ---------- 정량 처방 (prescribe) ----------


def _small_sweep(client, wait_job, span=None):
    r = client.post("/api/influence/sweep", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "knobs": ["table.pitch.kp"],
        **({"span": span} if span else {}),
        "t_settle": 2.0, "t_step": 4.0,
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    return j["result_id"]


def test_prescribe_round_trip(client, wait_job):
    """저장 스윕 → 단일 필요 변화량 + 조합 + 확인 런(evaluate) + 적용 페이로드."""
    rid = _small_sweep(client, wait_job, span=[-0.1, 0.1])
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid,
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "confirm": "linear",
        "t_settle": 2.0, "t_step": 4.0,
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert res["kind"] == "influence_prescribe"
    assert res["conditions"] == {"cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0, "condition": "level"}]}  # 확인 런의 격자
    assert res["knobs"] == ["table.pitch.kp"]
    s = res["singles"]["table.pitch.kp"]
    # 대상 지표마다 solvable 아니면 사유가 있다 — 빈칸 없음
    for metric, rec in s.items():
        assert rec["solvable"] in (True, False)
        if not rec["solvable"]:
            assert rec["reason"]
    assert "spans" in res["joint"]
    # 목적 선택(04 §7.3) — 기본은 최소 수정이고, 엔진은 정보 키(바뀐 게인)만 더한다
    assert res["objective"] == "min_change" and res["joint"]["objective"] == "min_change"
    assert res["joint"]["changed_count"] == len(res["joint"]["changed_knobs"])
    assert "perf" not in res["confirm"]  # 성능 비교는 성능 목적에만
    # 확인 런은 evaluate v2 페이로드다 — 카드가 실린다
    assert [c["key"] for c in res["confirm"]["cards"]][:2] == ["mode_stability", "gm"]
    # 적용 페이로드 — 배율이 이미 곱힌 실효 테이블 (웹은 다시 곱하지 않는다)
    assert res["gain_export"]["tables"]["pitch.kp"]["axes"]["mach"]
    json.dumps(res, allow_nan=False)


def test_prescribe_guards(client, wait_job):
    base = {"cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]}
    assert client.post("/api/influence/prescribe", json={
        **base, "result_id": "nope"}).status_code == 404
    # sim 결과를 넘기면 409 — 종류가 다른 저장물로 처방을 풀면 조용한 오답이 된다
    sim_rid = _run_sim(client, wait_job)
    assert client.post("/api/influence/prescribe", json={
        **base, "result_id": sim_rid}).status_code == 409
    rid = _small_sweep(client, wait_job)
    assert client.post("/api/influence/prescribe", json={
        **base, "result_id": rid, "knobs": ["없는.자리"]}).status_code == 422


def test_prescribe_inherits_from_evaluate(client, wait_job):
    """② 승계 — 평가가 좁혀 준 지표·설계변수를 사용자가 다시 고르지 않는다."""
    case = {"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}
    ev = client.post("/api/influence/evaluate", json={
        "cases": [case], "t_settle": 2.0, "t_step": 4.0})
    j = wait_job(ev.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    eval_rid = j["result_id"]
    ev_res = client.get(f"/api/results/{eval_rid}").json()
    # ① 평가가 소견까지 같은 런에서 냈다 — 별도 진단 실행이 없다
    att = ev_res["cases"][0]["attribution"]
    assert att["status"] == "ok" and att["prescriptions"]
    # 격자 재기가 국소성 판정을 함께 낸다 (스캔 흡수)
    assert ev_res["aggregate"]["locality"]["metrics"]
    knob = att["prescriptions"][0]["knobs"][0]

    # 승계한 설계변수를 실제로 흔든 스윕이라야 감도가 있다
    sw = client.post("/api/influence/sweep", json={
        "cases": [case], "knobs": [knob], "span": [-0.1, 0.1],
        "t_settle": 2.0, "t_step": 4.0})
    js = wait_job(sw.json()["id"], timeout=300.0)
    assert js["status"] == "done"

    r = client.post("/api/influence/prescribe", json={
        "result_id": js["result_id"], "eval_result_id": eval_rid,
        "cases": [case], "confirm": "none",
    })
    assert r.status_code == 202, r.text
    j2 = wait_job(r.json()["id"], timeout=300.0)
    assert j2["status"] == "done"
    res = client.get(f"/api/results/{j2['result_id']}").json()
    inh = res["inherited"]
    assert inh["from"] == eval_rid
    assert knob in inh["knobs"] and res["knobs"] == [knob]
    # 승계한 지표만 푼다 — 통과한 지표까지 풀면 표의 절반이 "이미 문턱 안"이 된다
    solved = set(res["singles"][knob].keys())
    if inh["metrics"]:
        assert solved <= set(inh["metrics"])
    json.dumps(res, allow_nan=False)


def test_prescribe_승계_설계변수가_스윕에_없으면_거절(client, wait_job):
    """감도가 없는 설계변수의 필요 변화량을 지어내지 않는다 — 사유와 함께 422."""
    case = {"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}
    ev = client.post("/api/influence/evaluate", json={
        "cases": [case], "t_settle": 2.0, "t_step": 4.0})
    eval_rid = wait_job(ev.json()["id"], timeout=300.0)["result_id"]
    # 평가가 지목하지 않을 자리만 흔든 스윕
    rid = _small_sweep(client, wait_job, span=[0.1])
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "eval_result_id": eval_rid, "cases": [case]})
    assert r.status_code == 422
    assert "스윕이 흔들지 않았다" in r.json()["detail"]


def test_prescribe_inherit_guards(client, wait_job):
    base = {"cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]}
    rid = _small_sweep(client, wait_job)
    assert client.post("/api/influence/prescribe", json={
        **base, "result_id": rid, "eval_result_id": "nope"}).status_code == 404
    # 종류가 다른 저장물을 승계원으로 주면 409 — 조용히 무시하면 승계한 척이 된다
    assert client.post("/api/influence/prescribe", json={
        **base, "result_id": rid, "eval_result_id": rid}).status_code == 409


# ---------- 처방 목적 선택 — 기준 충족 최소 수정 / 성능 개선 (04 §7.3) ----------

_CASE = {"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}
_OK_METRICS = {"alt_rms": 5.0, "spd_rms": 1.0, "hdg_rms": 0.05, "surf_sat_frac": 0.0,
               "worst_stall_margin": 0.2, "de_dyn_reserve_min_frac": 0.5,
               "alt_ts": 10.0, "spd_ts": 12.0, "hdg_ts": 8.0,
               "alt_mp": 0.1, "spd_mp": 0.05, "hdg_mp": 0.02}


# 확인 런(t_settle 2·t_step 4·기본 dt_plant·표준 기동)과 같은 기동 기록 — 스윕 라우트가 싣는 conditions.maneuver 모양
_MANEUVER = {"dv": 3.0, "dh": 30.0, "dpsi": 0.3, "t_settle": 2.0, "t_step": 4.0, "dt_plant": 0.01}


def _fake_sweep(client, rid="sweep-fake", case="design", conditions=None, base_fp=None):
    """합성 스윕 저장물 — 6DOF 없이 풀이 경로만 시험한다(목적 전달·에코·422).

    conditions: 실행 조건 기록(없으면 옛 스윕처럼 뺀다). base_fp: base 행 형상 지문."""
    rows = [{"case": case, "label": "base", "role": "base", "overrides": {}, "aborted": False,
             "metrics": dict(_OK_METRICS), **({"fingerprint": base_fp} if base_fp else {})}]
    for s in (-0.1, 0.1):
        m = dict(_OK_METRICS, alt_ts=10.0 - 20.0 * s, alt_rms=5.0 - 5.0 * s)
        rows.append({"case": case, "label": f"table.pitch.kp@{s:+g}", "role": "single",
                     "overrides": {"table.pitch.kp": 1.0 + s}, "aborted": False, "metrics": m})
    payload = {"kind": "influence_sweep", "rows": rows}
    if conditions is not None:
        payload["conditions"] = conditions
    client.app.state.store.save(rid, payload, meta={"kind": "influence_sweep"})
    return rid


def _shape_fp(client, wait_job, monkeypatch):
    """요청 형상의 지문 — 확인 런 없는 처방 한 번(시뮬 0)의 결과 fingerprint."""
    rid = _fake_sweep(client, rid="sweep-fp")
    _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.0}})
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [_CASE], "confirm": "none"})
    j = wait_job(r.json()["id"])
    return client.get(f"/api/results/{j['result_id']}").json()["fingerprint"]


def _perf_confirm(client, wait_job, rid, **extra):
    """성능 목적 + full 확인 런(짧은 기동) → confirm.perf."""
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [_CASE], "confirm": "full", "objective": "performance",
        "t_settle": 2.0, "t_step": 4.0, **extra})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done", j
    return client.get(f"/api/results/{j['result_id']}").json()["confirm"]["perf"]


def _spy_joint(monkeypatch, out):
    """라우트의 solve_joint를 가로채 받은 인자를 기록한다 — 엔진 풀이는 엔진 테스트의 몫."""
    from claw_server.routes import influence as influence_route

    seen = {}

    def fake(rows, knobs, criteria, **kw):
        seen.update(kw, knobs=list(knobs))
        return {"objective": kw.get("objective", "min_change"), "changed_knobs": [],
                "changed_count": 0, **out}
    monkeypatch.setattr(influence_route, "solve_joint", fake)
    return seen


def test_prescribe_기본_목적은_최소_수정이고_성능_인자를_넘기지_않는다(client, wait_job, monkeypatch):
    rid = _fake_sweep(client)
    seen = _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.0}})
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [_CASE], "confirm": "none"})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"])
    assert j["status"] == "done", j
    assert seen["objective"] == "min_change"
    # 최소 수정에는 성능 인자가 가지 않는다 — 엔진 기본값 그대로(종전 호출과 같은 해)
    assert not {"perf_metrics", "perf_weights", "smooth_weight"} & set(seen)
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert res["objective"] == "min_change"
    assert "note" not in res["inherited"]
    meta = next(m for m in client.get("/api/results").json() if m["id"] == j["result_id"])
    assert meta["objective"] == "min_change"


def test_prescribe_성능_목적은_인자를_넘기고_에코한다(client, wait_job, monkeypatch):
    rid = _fake_sweep(client)
    seen = _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.0}})
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [_CASE], "confirm": "none",
        "objective": "performance", "perf_metrics": ["alt_ts", "alt_rms"],
        "perf_weights": {"alt_ts": 2.0, "alt_rms": 0.0}, "smooth_weight": 0.5})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"])
    assert j["status"] == "done", j
    assert seen["objective"] == "performance"
    assert seen["perf_metrics"] == ["alt_ts", "alt_rms"]
    assert seen["perf_weights"] == {"alt_ts": 2.0, "alt_rms": 0.0}
    assert seen["smooth_weight"] == 0.5
    # 성능은 하드 기준 전부를 지킨다 — 실패 지표 좁히기(승계)를 넘기지 않는다
    assert seen.get("metrics") is None
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert res["objective"] == "performance"
    assert "하드 기준 전부" in res["inherited"]["note"]
    meta = next(m for m in client.get("/api/results").json() if m["id"] == j["result_id"])
    assert meta["objective"] == "performance"



def test_prescribe_성능_목적_실엔진_풀이(client, wait_job):
    """가로채지 않은 엔진 풀이 — 합성 스윕에서 alt_ts를 줄이는 쪽으로 밀고 결과가 JSON 안전하다."""
    rid = _fake_sweep(client)
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [_CASE], "confirm": "none", "objective": "performance",
        "perf_metrics": ["alt_ts", "alt_rms"], "smooth_weight": 0.0})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"])
    assert j["status"] == "done", j
    res = client.get(f"/api/results/{j['result_id']}").json()
    jt = res["joint"]
    assert jt["objective"] == "performance" and jt["perf_metrics"] == ["alt_ts", "alt_rms"]
    assert jt["spans"]["table.pitch.kp"] > 0  # 두 지표 다 kp↑로 준다
    assert jt["objective_value"]["predicted"] < jt["objective_value"]["base"]
    assert jt["changed_knobs"] == ["table.pitch.kp"]
    json.dumps(res, allow_nan=False)
    # 엔진이 모르는 지표는 제출 시점 422 (실엔진 ValueError)
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [_CASE], "confirm": "none", "objective": "performance",
        "perf_metrics": ["no_such_metric"]})
    assert r.status_code == 422 and "no_such_metric" in r.json()["detail"], r.text

def test_prescribe_최소_수정에_성능_인자를_보내면_422(client):
    rid = _fake_sweep(client)
    for extra in ({"perf_metrics": ["alt_ts"]}, {"perf_weights": {"alt_ts": 2.0}},
                  {"smooth_weight": 0.1}, {"objective": "min_change", "smooth_weight": 0.5}):
        r = client.post("/api/influence/prescribe", json={
            "result_id": rid, "cases": [_CASE], "confirm": "none", **extra})
        assert r.status_code == 422, (extra, r.text)
        assert "performance" in r.text and "min_change" in r.text, r.text


def test_prescribe_성능_해가_안_풀리면_확인_런을_생략한다(client, wait_job, monkeypatch):
    rid = _fake_sweep(client)
    _spy_joint(monkeypatch, {"solvable": False, "spans": {"table.pitch.kp": 0.2},
                             "reason": "선형 모델에서 하드 문턱을 전부 만족하는 해가 표본 스팬 안에 없다"})
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [_CASE], "confirm": "full", "objective": "performance"})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"])
    assert j["status"] == "done", j
    res = client.get(f"/api/results/{j['result_id']}").json()
    assert res["confirm"] is None and res["gain_export"] is None
    assert any("풀리지 않았다" in w and "확인 런 생략" in w for w in res["warnings"]), res["warnings"]


def test_prescribe_성능_인자_검증은_제출_시점_422(client, monkeypatch):
    rid = _fake_sweep(client)
    base = {"result_id": rid, "cases": [_CASE], "confirm": "none", "objective": "performance"}
    for bad in ({"perf_weights": {"alt_ts": -1.0}}, {"smooth_weight": -0.1},
                {"smooth_weight": 11.0}, {"objective": "fastest"}):
        r = client.post("/api/influence/prescribe", json={**base, **bad})
        assert r.status_code == 422, (bad, r.text)
    # 비유한 가중은 JSON에 못 싣는다 — 문자열 "inf"로 와도 거절
    r = client.post("/api/influence/prescribe", json={**base, "perf_weights": {"alt_ts": "inf"}})
    assert r.status_code == 422, r.text

    # 엔진이 모르는 지표·가중 키는 엔진 ValueError → 422 (잡 안에서 터지면 사유가 잡 오류로 묻힌다)
    from claw_server.routes import influence as influence_route

    def boom(*_a, **_k):
        raise ValueError("알 수 없는 성능 지표: ['nope']")
    monkeypatch.setattr(influence_route, "solve_joint", boom)
    r = client.post("/api/influence/prescribe", json={**base, "perf_metrics": ["nope"]})
    assert r.status_code == 422 and "nope" in r.json()["detail"], r.text


def test_prescribe_성능_확인_런은_실측_변화를_싣는다(client, wait_job, monkeypatch):
    """confirm.perf — 스윕 base(같은 이름·같은 좌표) 대비 확인 런 실측 성능 지표. 판정자는 여전히 evaluate."""
    rid = _small_sweep(client, wait_job, span=[-0.1, 0.1])
    _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.05},
                             "perf_metrics": ["alt_rms", "alt_ts", "alt_mp"]})
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [_CASE], "confirm": "full",
        "objective": "performance", "t_settle": 2.0, "t_step": 4.0})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done", j
    res = client.get(f"/api/results/{j['result_id']}").json()
    perf = res["confirm"]["perf"]
    assert perf["base_source"] == "sweep"
    got = perf["cases"]["design"]
    assert set(got) == {"alt_rms", "alt_ts", "alt_mp"}  # 풀이가 쓴 지표만
    # 스윕은 실행한 기동을 기록한다 — 확인 런 대조의 근거
    sweep = client.get(f"/api/results/{rid}").json()
    assert sweep["conditions"]["maneuver"] == _MANEUVER
    # 실제 수치 — 기준은 스윕 base 행, 새 값은 확인 런 표준 기동 실측, 목적함수와 같은 정규화
    from claw.pipeline.prescribe import _num, _perf_floor

    base_m = next(r for r in sweep["rows"] if r["label"] == "base")["metrics"]
    new_m = res["confirm"]["cases"][0]["metrics_raw"]
    moved = 0
    for m, rec in got.items():
        b, v = _num(base_m[m]), _num(new_m[m])  # 저장물의 비유한은 "inf" 문자열 → None
        assert rec["base"] == b and rec["new"] == v, (m, rec, base_m[m], new_m[m])
        if rec["delta_frac"] is None:
            assert "inf" in (rec["base_state"], rec["new_state"]), (m, rec)
            continue
        want = (v - b) / max(abs(b), _perf_floor(m))
        assert abs(rec["delta_frac"] - want) < 1e-12, (m, rec, want)
        moved += rec["delta_frac"] != 0.0
    assert moved, got  # +5 % kp는 무언가를 움직인다 — 0이면 같은 형상을 비교한 것
    assert perf["omitted"] == [] and perf["notes"] == []
    # 판정은 그대로 evaluate — 카드가 실린다
    assert res["confirm"]["cards"]
    json.dumps(res, allow_nan=False)


def test_prescribe_성능_확인_기준을_못_찾으면_사유와_함께_뺀다(client, wait_job, monkeypatch):
    """확인 케이스 이름이 스윕 케이스와 안 맞고 평가 결과도 없으면 비교를 지어내지 않는다 (full 확인 런)."""
    rid = _fake_sweep(client, case="other", conditions={
        "cases": [{"name": "other", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "maneuver": dict(_MANEUVER)})
    _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.05}})
    perf = _perf_confirm(client, wait_job, rid)
    assert perf["cases"] == {} and perf["base_source"] is None
    assert [o["case"] for o in perf["omitted"]] == ["design"]
    reason = perf["omitted"][0]["reason"]
    assert "같은 이름의 케이스가 없다" in reason and "승계한 평가 결과가 없다" in reason, reason


def test_prescribe_성능_확인_옛_스윕은_기동_기록이_없어_뺀다(client, wait_job, monkeypatch):
    rid = _fake_sweep(client, conditions={"cases": [dict(_CASE)]})  # maneuver 없음
    _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.05}})
    perf = _perf_confirm(client, wait_job, rid)
    assert perf["cases"] == {}
    assert "기동 기록" in perf["omitted"][0]["reason"], perf


def test_prescribe_성능_확인_스윕_기동이_다르면_뺀다(client, wait_job, monkeypatch):
    rid = _fake_sweep(client, conditions={"cases": [dict(_CASE)],
                                          "maneuver": dict(_MANEUVER, dt_plant=0.02)})
    _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.05}})
    perf = _perf_confirm(client, wait_job, rid)
    assert perf["cases"] == {}
    assert "기동이 다르다" in perf["omitted"][0]["reason"]
    assert "dt_plant 0.02≠0.01" in perf["omitted"][0]["reason"], perf


def test_prescribe_성능_확인_스윕_base_형상이_다르면_뺀다(client, wait_job, monkeypatch):
    rid = _fake_sweep(client, conditions={"cases": [dict(_CASE)], "maneuver": dict(_MANEUVER)},
                      base_fp="다른형상")
    _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.05}})
    perf = _perf_confirm(client, wait_job, rid)
    assert perf["cases"] == {}
    assert "형상 지문" in perf["omitted"][0]["reason"], perf


def _fake_eval(client, fp, maneuver, rid="eval-fake", conditions=True):
    ev = {"kind": "influence_evaluate", "fingerprint": fp, "aggregate": {},
          "cases": [{"case": "design", "hard_fails": [], "metrics_raw": dict(_OK_METRICS)}]}
    if maneuver is not None:
        ev["maneuver"] = maneuver
    if conditions:
        ev["conditions"] = {"cases": [dict(_CASE, condition=None)]}
    client.app.state.store.save(rid, ev, meta={"kind": "influence_evaluate"})
    return rid


def test_prescribe_성능_확인_평가_대체는_같은_기동일_때만(client, wait_job, monkeypatch):
    fp = _shape_fp(client, wait_job, monkeypatch)
    rid = _fake_sweep(client, conditions={"cases": [dict(_CASE)],
                                          "maneuver": dict(_MANEUVER, t_step=9.0)})
    _spy_joint(monkeypatch, {"solvable": True, "spans": {"table.pitch.kp": 0.05}})
    ev_man = {k: _MANEUVER[k] for k in ("dv", "dh", "dpsi", "t_settle", "t_step")}
    # 같은 형상·같은 기동(t_hold는 동시명령 런만 정해 대조하지 않는다) → 평가가 기준, dt_plant 미대조는 노트로
    ok = _fake_eval(client, fp, dict(ev_man, t_hold=4.0), rid="eval-ok")
    perf = _perf_confirm(client, wait_job, rid, eval_result_id=ok)
    assert perf["base_source"] == "evaluate" and set(perf["cases"]) == {"design"}
    assert perf["cases"]["design"]["alt_ts"]["base"] == _OK_METRICS["alt_ts"]
    assert any("dt_plant" in n for n in perf["notes"]), perf
    # 기동이 다르면 뺀다
    bad = _fake_eval(client, fp, dict(ev_man, t_settle=5.0), rid="eval-bad")
    perf = _perf_confirm(client, wait_job, rid, eval_result_id=bad)
    assert perf["cases"] == {}
    assert "평가와 확인 런의 기동이 다르다: t_settle" in perf["omitted"][0]["reason"], perf
    # 기동 기록 없는 옛 평가도 추측하지 않는다
    old = _fake_eval(client, fp, None, rid="eval-old")
    perf = _perf_confirm(client, wait_job, rid, eval_result_id=old)
    assert perf["cases"] == {} and "평가 결과에 기동 기록이 없다" in perf["omitted"][0]["reason"]
    # 좌표 기록 없는 평가도 뺀다
    nocoord = _fake_eval(client, fp, dict(ev_man), rid="eval-nocoord", conditions=False)
    perf = _perf_confirm(client, wait_job, rid, eval_result_id=nocoord)
    assert perf["cases"] == {} and "좌표 기록이 없다" in perf["omitted"][0]["reason"]


def test_verify_mission_profile_crosses_the_schedule(client, wait_job):
    """미션 프로파일 [자리] → 실측 (v1.41) — 시간축 스케줄 통과가 결과에 실린다.

    코너 0·중간점 끔이면 이 런이 유일한 시뮬이다. 통과는 mach 시계열 실측,
    RMS는 facts 보고만(판정선 없음), t_mission이 엔진 천장을 덮는다.
    """
    r = client.post("/api/influence/verify", json={
        "cases": [{"name": "a", "mach": 0.4, "alt": 1000.0, "fuel": 200.0},
                  {"name": "b", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "depth": "full", "midpoints": False,
        "t_settle": 2.0, "t_step": 10.0, "t_mission": 60.0,
        "profile": _criteria_profile(client, "mission-only", {"robustness": {
            "mass_frac": 0.0, "cmalpha_frac": 0.0, "cmq_frac": 0.0}}),
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    res = client.get(f"/api/results/{j['result_id']}").json()
    mp = res["verify"]["mission_profile"]
    assert "[자리]" not in (mp.get("note") or "")  # placeholder가 아니라 실측이다
    assert mp["status"] in ("ok", "warn", "fail")
    got = mp["crossed"]["mach"]
    assert got["expected"] and got["crossed"] == got["expected"]
    assert mp["scenario"]["t_end"] == 60.0  # t_mission이 천장을 덮었다
    assert mp["facts"]["rms"]["spd_rms"] is not None
    json.dumps(res, allow_nan=False)


def test_verify_mission_knob_validation(client):
    """t_mission은 양수·유한만 — 0·음수·NaN은 202 전에 422다."""
    base = {"cases": [{"name": "a", "mach": 0.5, "alt": 1000.0, "fuel": 200.0}]}
    for bad in (0.0, -5.0):
        assert client.post("/api/influence/verify",
                           json={**base, "t_mission": bad}).status_code == 422
    # 스위치 끔은 유효한 요청 — na + 사유가 결과에 남는다 (제출은 202)
    assert client.post("/api/influence/verify", json={
        **base, "depth": "linear",
        "profile": _criteria_profile(client, "mission-off", {"schedule": {"mission": False}}),
    }).status_code == 202



# ---------- 기준 통합 S3a — 판정 라우트는 기체 프로파일의 기준을 쓰고 출처를 밝힌다 ----------


def _linear_evaluate(client, wait_job, **over):
    """단계 1(시뮬 0) 평가 → (본문, 저장 meta)."""
    r = client.post("/api/influence/evaluate", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "depth": "linear", **over,
    })
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done", j
    res = client.get(f"/api/results/{j['result_id']}").json()
    root = client.app.state.store.root
    meta = json.loads((root / f"{j['result_id']}.meta.json").read_text(encoding="utf-8"))
    return res, meta


def test_evaluate_echoes_default_criteria_for_the_example(client, wait_job):
    """/criteria 없는 예제 → 도구 기본값(source default). 본문의 기준 전문·옛 지문은 그대로."""
    from claw.pipeline.criteria import JUDGEMENT_SCHEME, GainEvalCriteria

    res, meta = _linear_evaluate(client, wait_job)
    d = GainEvalCriteria()
    echo = {"judgement_fingerprint": d.judgement_fingerprint(),
            "targets_fingerprint": d.targets_fingerprint(),
            "scheme": JUDGEMENT_SCHEME, "source": "default"}
    assert res["criteria_echo"] == echo and meta["criteria_echo"] == echo
    assert res["criteria"] == d.to_dict()  # 엔진이 실은 기준 전문 — 덮이지 않는다
    assert res["criteria_fingerprint"] == d.fingerprint() == meta["criteria_fingerprint"]
    assert res["profile"] == meta["profile"]


def test_evaluate_uses_profile_criteria(client, wait_job):
    """프로파일 /criteria.margin.pm_min_deg가 판정선이 된다 — 요청이 기준을 안 들고 와도."""
    from claw.pipeline.criteria import GainEvalCriteria
    from claw.profile import load_example

    d = load_example()
    d.update(id="strict-delta", name="엄격한 델타", description="시험용", is_example=False, variants=[])
    d["criteria"] = {"margin": {"pm_min_deg": 89.0}}
    assert client.post("/api/profiles", json={"document": d}).status_code == 201

    base, _ = _linear_evaluate(client, wait_job)
    res, meta = _linear_evaluate(client, wait_job, profile={"id": "strict-delta"})
    strict = GainEvalCriteria.from_dict({"margin": {"pm_min_deg": 89.0}})
    assert res["criteria_echo"]["source"] == meta["criteria_echo"]["source"] == "profile"
    assert res["criteria_echo"]["judgement_fingerprint"] == strict.judgement_fingerprint()
    assert res["criteria_echo"]["judgement_fingerprint"] != base["criteria_echo"]["judgement_fingerprint"]
    assert res["criteria"]["margin"]["pm_min_deg"] == 89.0  # 판정에 쓴 기준 전문
    assert base["criteria"]["margin"]["pm_min_deg"] != 89.0
    # PM 카드의 판정선이 프로파일 값이고, 89°는 실제 PM이 못 넘으니 판정이 실패다
    pm_base = next(c for c in base["cards"] if c["key"] == "pm")
    pm = next(c for c in res["cards"] if c["key"] == "pm")
    assert pm_base["threshold"]["pm_min_deg"] == GainEvalCriteria().margin.pm_min_deg
    assert pm["threshold"]["pm_min_deg"] == 89.0
    assert pm["primary"] == pm_base["primary"]  # 같은 기체·형상 — 잰 값은 같고 판정선만 다르다
    assert pm["status"] == "fail"
    assert any(f["check"] == "margins.pm" and f["limit"] == 89.0
               for f in res["cases"][0]["hard_fails"])


def test_request_criteria_are_rejected(client):
    """요청 기준은 거절한다(v1.54 S3b) — 판정하는 영향성 라우트 전부. 형식이 맞아도 422이고, 사유가 기체 편집을 가리킨다.
    같은 기체의 결과가 요청마다 다른 기준으로 판정되면 탭마다 같은 점이 다르게 판정되던 문제로 돌아간다."""
    from claw_server.refs import REQUEST_CRITERIA_REJECTED

    case = [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}]
    good = {"margin": {"pm_min_deg": 50.0}}
    for route, body in (("evaluate", {"cases": case, "depth": "linear"}),
                        ("verify", {"cases": case, "depth": "linear"}),
                        ("scan", {"cases": case})):
        r = client.post(f"/api/influence/{route}", json={**body, "criteria": good})
        assert r.status_code == 422, (route, r.text)
        assert REQUEST_CRITERIA_REJECTED in r.text
    # 명시적 null은 「안 보냄」이다 — 거절하지 않는다
    assert client.post("/api/influence/evaluate",
                       json={"cases": case, "depth": "linear", "criteria": None}).status_code == 202


def test_diagnose_echoes_criteria_source(client, wait_job):
    rid = _run_sim(client, wait_job)
    body = client.post("/api/influence/diagnose", json={"result_id": rid}).json()
    assert body["criteria_echo"]["source"] == "default"
    from claw_server.refs import REQUEST_CRITERIA_REJECTED

    r = client.post("/api/influence/diagnose",
                    json={"result_id": rid, "criteria": {"margin": {"pm_min_deg": 50.0}}})
    assert r.status_code == 422 and REQUEST_CRITERIA_REJECTED in r.text  # 요청 기준 거절(v1.54)
    # 처방도 같다 — 판정하는 영향성 라우트 다섯 모두(evaluate·verify·scan은 test_request_criteria_are_rejected)
    r = client.post("/api/influence/prescribe", json={
        "result_id": rid, "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "criteria": {"margin": {"pm_min_deg": 50.0}}})
    assert r.status_code == 422 and REQUEST_CRITERIA_REJECTED in r.text, r.text[:300]
