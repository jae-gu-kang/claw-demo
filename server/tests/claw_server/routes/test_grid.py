"""공통 운용공간 라우트 (05 §11) — 요구 운용영역 → 기본 모델 격자, 트림 결과의 조건 상태.

서버 테스트의 예제는 구 합성 기체(conftest — 1200 kg, trim_grid M0.30~0.55 × 고도 3 × 연료 200)이고 요구 운용영역
절이 없다 — 그래서 기본 경로가 곧 「trim_grid 초안(미확정)」 경로다.
"""

import copy

from claw.profile import load_example


def _doc(pid="region-delta", region="keep", template="keep"):
    d = copy.deepcopy(load_example())
    d["id"], d["name"], d["is_example"] = pid, pid, False
    if region != "keep":
        d["operating_region"] = region
    if template != "keep":
        d["mission_template"] = template
    return d


REGION = {
    "mach": [0.3, 1.2], "alt": [100.0, 3000.0], "fuel": [100.0, 300.0],
    # 경계표는 1000 m까지만 — 3000 m 행은 요구 미정의
    "boundary": [{"fuel": 200.0, "rows": [[100.0, 0.3, 1.2], [1000.0, 0.35, 1.2]]}],
    "base_grid": {"n_mach": 10, "alts": [100.0, 1000.0, 3000.0], "fuels": [200.0]},
}


def test_default_example_gets_an_unconfirmed_draft_from_trim_grid(client):
    r = client.post("/api/grid/base", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["region"]["confirmed"] is False and body["region"]["source"] == "draft:trim_grid"
    assert body["profile"]["source"] == "default-example"
    assert body["axis"] == [0.3, 0.35, 0.4, 0.45, 0.5, 0.55]
    assert len(body["points"]) == 18 and body["counts"] == {"not_run": 18}
    assert body["points"][0]["name"] == "M0.3_h100_f200"  # 값 그대로의 이름 — 표·지도가 되읽는다
    # 서펜타인 — 둘째 행은 마하가 내려간다
    second = [p["mach"] for p in body["points"] if p["alt"] == 1000.0]
    assert second == sorted(second, reverse=True)


def test_confirmed_region_keeps_model_gap_points_and_undefined_rows(client):
    assert client.post("/api/profiles", json={"document": _doc(region=REGION)}).status_code == 201
    body = client.post("/api/grid/base", json={"profile": {"id": "region-delta"}}).json()
    assert body["region"]["confirmed"] is True and body["region"]["source"] == "profile"
    assert body["model"]["mach"] == [0.0, 0.9]
    # 모델(DB 마하 0.9)보다 넓은 요구 — 점을 지우지 않고 모델 부족으로 싣는다
    gap = [p for p in body["points"] if p["state"] == "model_gap"]
    assert gap and all(p["mach"] > 0.9 for p in gap)
    assert body["counts"]["model_gap"] == len(gap)
    rows = {r["alt"]: r for r in body["rows"]}
    assert rows[3000.0]["state"] == "undefined" and rows[3000.0]["n"] == 0  # 행은 사라지지 않는다
    assert rows[1000.0]["bounds"] == [0.35, 1.2] and 0.35 in {p["mach"] for p in body["points"] if p["alt"] == 1000.0}


def test_spec_in_the_request_overrides_the_region_spec(client):
    body = client.post("/api/grid/base", json={"n_mach": 3, "alts": [1000.0], "fuels": [200.0]}).json()
    assert [p["mach"] for p in body["points"]] == [0.3, 0.425, 0.55]
    assert client.post("/api/grid/base", json={"n_mach": 1}).status_code == 422


def test_aircraft_without_region_or_template_says_so(client):
    client.post("/api/profiles", json={"document": _doc(pid="bare-delta", template=None)})
    body = client.post("/api/grid/base", json={"profile": {"id": "bare-delta"}}).json()
    assert body["region"] is None and body["points"] == [] and "요구 운용영역" in body["reason"]


def test_trim_batch_results_carry_the_condition_state(client, wait_job):
    # 1000 m·연료 200: M0.40은 계산 가능·여유 충족, M0.60은 수렴한 평형이 스로틀 판정선을 넘는다 — 계산 가능·여유 미달
    # (날 수 있는 조건이다 — 판정선 미달을 물리적 불가로 부르지 않는다). M0.70은 스로틀 100 %·미수렴이고, 최대 추력
    # 평형을 다시 풀어 감속이 남는다는 근거가 있어 물리적 불가(추력 부족)다
    cases = [{"mach": m, "alt": 1000.0, "fuel": 200.0} for m in (0.40, 0.60, 0.70)]
    j = wait_job(client.post("/api/trim/batch", json={"cases": cases}).json()["id"])
    body = client.get(f"/api/results/{j['result_id']}").json()
    by_mach = {res["case"]["mach"]: res for res in body["results"]}
    assert by_mach[0.4]["state"] == "computable" and by_mach[0.4]["state_reasons"] == []
    assert by_mach[0.4]["margin"] == {"status": "met", "reasons": []} and by_mach[0.4]["state_evidence"] is None
    assert by_mach[0.6]["state"] == "computable" and by_mach[0.6]["state_reasons"] == []
    assert by_mach[0.6]["margin"] == {"status": "short", "reasons": ["throttle_high"]}
    assert by_mach[0.7]["state"] == "infeasible" and by_mach[0.7]["state_reasons"] == ["thrust_deficit", "throttle_high"]
    ev = by_mach[0.7]["state_evidence"]
    assert ev["fixed"] == {"throttle": 1.0} and all(s["vdot"] < -ev["tol"] for s in ev["solutions"])
    # 요구영역 판정도 함께 — 손으로 더한 케이스는 영역 밖일 수 있다(초안 영역 M0.30~0.55)
    assert by_mach[0.4]["region_state"] is None and by_mach[0.6]["region_state"] == "out_of_region"
    assert body["region"]["confirmed"] is False  # 초안으로 계산한 결과는 그 사실을 싣는다


def test_trim_batch_results_carry_the_condition_verdict(client, wait_job):
    # 조건 판정(05 §11.3 · 이관 8단계) — 트림 탭 결과에도 자동 설계와 같은 항목별 판정이 붙는다. 같은 세 조건:
    # M0.40은 채택, M0.60은 추진 여유 미달이지만 채택(v1.65 — 날 수 있는 평형이라 설계에 쓰고 여유 미달은 표시만),
    # M0.70은 트림 불성립으로 제외(트림 항목 —
    # 방금 잰 조건 상태를 그대로 싣는다). 요구영역 판정은 싣되 채택에 쓰지 않는다(이관 2단계 전)
    cases = [{"mach": m, "alt": 1000.0, "fuel": 200.0} for m in (0.40, 0.60, 0.70)]
    cases.append({"mach": 0.0, "alt": 0.0, "fuel": 200.0, "condition": "ground"})
    j = wait_job(client.post("/api/trim/batch", json={"cases": cases}).json()["id"])
    body = client.get(f"/api/results/{j['result_id']}").json()
    by_mach = {res["case"]["mach"]: res for res in body["results"]}
    ok = by_mach[0.4]["verdict"]
    # 요구영역은 초안(trim_grid M0.30~0.55)으로 분류된다 — 미확정이라 confirmed False
    assert ok["adopted"] is True and ok["exclusion"] is None and ok["region"] == {"status": "in", "confirmed": False}
    assert ok["trim"] == {"status": "computable", "reasons": []} and ok["margin"]["status"] == "met"
    assert ok["model"]["status"] == "valid" and ok["limits"]["status"] == "met"
    short = by_mach[0.6]["verdict"]
    assert short["adopted"] is True and short["exclusion"] is None
    assert short["margin"] == {"status": "short", "reasons": ["throttle_high"]}
    assert short["limits"]["status"] == "met" and short["model"]["status"] == "valid"
    assert short["trim"]["status"] == "computable" and short["region"] == {"status": "out_of_region", "confirmed": False}
    bad = by_mach[0.7]["verdict"]
    assert bad["exclusion"] == {"category": "trim", "reasons": ["thrust_deficit", "throttle_high"]}
    assert bad["trim"] == {"status": "infeasible", "reasons": ["thrust_deficit", "throttle_high"]}
    assert by_mach[0.0]["verdict"] is None  # 지상 평형은 조건 판정 대상이 아니다


# ── 요구영역 편집 미리 보기 (05 §11.13 6단계) — 저장하지 않고 「바꾸면 무엇이 달라지나」 ─────────────
def _preview(client, region, pid="region-delta", fuel=200.0):
    return client.post("/api/grid/region/preview",
                       json={"profile": {"id": pid}, "region": region, "fuel": fuel})


WIDER = {**REGION, "boundary": [{"fuel": 200.0, "rows": [[100.0, 0.3, 1.2], [1000.0, 0.35, 1.2], [3000.0, 0.4, 1.0]]}]}


def test_region_preview_answers_without_saving(client):
    client.post("/api/profiles", json={"document": _doc(region=REGION)})
    r = _preview(client, WIDER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert client.get("/api/profiles/region-delta").json()["revision"] == 1  # 저장하지 않는다
    assert body["region"]["confirmed"] is True and body["region"]["boundary"][0]["rows"][-1] == [3000.0, 0.4, 1.0]
    assert body["model"]["mach"] == [0.0, 0.9] and body["fuel"] == 200.0
    out = {o["alt"]: o for o in body["outline"]}
    assert out[3000.0] == {"alt": 3000.0, "mach_lo": 0.4, "mach_hi": 1.0, "state": "in"}
    g = body["grid"]
    assert set(g) >= {"points", "rows", "axis", "counts", "labels"}
    assert sum(g["counts"].values()) == len(g["points"])
    before = client.post("/api/grid/base", json={"profile": {"id": "region-delta"}}).json()
    d = body["impact"]["grid"]
    # 3000 m 행이 미정의 → 정의됨: 기존 점은 전부 유지, 3000 m 점만 새로
    assert d["before"] == len(before["points"]) and d["after"] == len(g["points"])
    assert d["dropped"] == 0 and d["kept"] == len(before["points"])
    assert d["added"] == sum(1 for p in g["points"] if p["alt"] == 3000.0) > 0
    assert len(body["region_key"]) == 12 and body["profile"]["id"] == "region-delta"
    # 같은 절이면 저장된 요구영역과 같은 판 — 격자 차이 없음
    same = _preview(client, REGION).json()
    assert same["impact"]["grid"]["added"] == same["impact"]["grid"]["dropped"] == 0
    assert same["region_key"] != body["region_key"]


def test_region_preview_rejects_with_the_document_path(client):
    client.post("/api/profiles", json={"document": _doc(region=REGION)})
    r = _preview(client, {**REGION, "mach": [1.2, 0.3]})
    assert r.status_code == 422
    assert r.json()["detail"]["path"] == "/operating_region/mach/1" and r.json()["detail"]["message"]
    r = _preview(client, {**REGION, "boundary": [{"fuel": 200.0, "rows": [[100.0, 0.5, 0.4]]}]})
    assert r.json()["detail"]["path"] == "/operating_region/boundary/0/rows/0/2"


def test_region_preview_counts_reuse_from_the_trim_store(client):
    from claw.common.contracts import TrimCase
    from claw.profile import build_profile
    from claw.trim.store import TrimRecord

    client.post("/api/profiles", json={"document": _doc(region=REGION)})
    fp = build_profile(client.get("/api/profiles/region-delta").json()["document"]).trim_fingerprint
    body = _preview(client, WIDER).json()
    run = [p for p in body["grid"]["points"] if p["state"] == "not_run"]
    assert body["impact"]["reused"] == 0 and body["impact"]["new_trims"] == len(run)
    scope = client.app.state.trim_store.scope(fp)
    p = run[0]
    scope.put(TrimCase(p["name"], mach=p["mach"], alt=p["alt"], fuel=p["fuel"]),
              TrimRecord(z=(0.05, 0.0, 0.5), success=True, cost=0.0, converged=True))
    q = run[1]  # 미수렴 기록은 재사용이 아니다 — 다시 푼다
    scope.put(TrimCase(q["name"], mach=q["mach"], alt=q["alt"], fuel=q["fuel"]),
              TrimRecord(z=(0.05, 0.0, 1.0), success=False, cost=1.0, converged=False))
    body = _preview(client, WIDER).json()
    assert body["impact"]["reused"] == 1 and body["impact"]["new_trims"] == len(run) - 1
    got = next(x for x in body["grid"]["points"] if x["name"] == p["name"])
    assert got["stored"] == {"state": "computable", "converged": True}


def test_region_preview_null_is_the_trim_grid_draft(client):
    client.post("/api/profiles", json={"document": _doc(region=REGION)})
    body = _preview(client, None).json()
    assert body["region"]["confirmed"] is False and body["region"]["source"] == "draft:trim_grid"
    assert body["grid"]["axis"] == [0.3, 0.35, 0.4, 0.45, 0.5, 0.55]


def test_region_preview_on_the_example_and_without_fuel(client):
    # 예제도 본다(저장만 막힌다). 연료를 안 주면 요구 연료 하한에서 그린다
    r = client.post("/api/grid/region/preview", json={"region": REGION, "fuel": None})
    assert r.status_code == 200, r.text
    assert r.json()["fuel"] == 100.0 and r.json()["profile"]["source"] == "default-example"
    assert {o["state"] for o in r.json()["outline"]} == {"undefined"}  # 층 200 밖의 연료


def test_region_preview_without_region_or_template(client):
    client.post("/api/profiles", json={"document": _doc(pid="bare-delta", template=None)})
    body = _preview(client, None, pid="bare-delta").json()
    assert body["region"] is None and body["outline"] == [] and body["grid"]["points"] == []
    assert body["region_key"] is None and "요구 운용영역" in body["reason"]


def test_region_preview_says_which_consumers_go_stale(client):
    from claw.opspace import region_echo, region_from_section

    doc = _doc(region=REGION)
    doc["law"]["alloc"]["de_trim"]["source"] = "derived"
    doc["law"]["alloc"]["de_trim"]["provenance"] = {"region": region_echo(region_from_section(REGION))}
    client.post("/api/profiles", json={"document": doc})
    same = {s["what"]: s for s in _preview(client, REGION).json()["impact"]["stale"]}
    assert same["de_trim"]["status"] == "current"
    assert same["gain_tables"]["status"] in ("no_record", "absent")
    assert same["trim_store"]["status"] == "reused"  # 플랜트 키라 요구영역과 무관
    moved = {s["what"]: s for s in _preview(client, WIDER).json()["impact"]["stale"]}
    assert moved["de_trim"]["status"] == "stale" and moved["de_trim"]["label"]
    # 손으로 넣은 표(도출 기록 없음)는 모른다 — 현재라고도 낡았다고도 하지 않는다
    client.post("/api/profiles", json={"document": _doc(pid="explicit-delta", region=REGION)})
    rows = {s["what"]: s for s in _preview(client, WIDER, pid="explicit-delta").json()["impact"]["stale"]}
    assert rows["de_trim"]["status"] == "no_record"


def test_region_preview_returns_every_layer_outline(client):
    # 「전체 연료」가 행 없는 층에 행을 넣을 때 그 층의 엔진 윤곽을 쓴다 — 웹이 고친 행을 복사해 다른 칸을 지어내지 않게
    two = {**REGION, "boundary": [{"fuel": 100.0, "rows": [[100.0, 0.3, 1.2], [3000.0, 0.4, 1.0]]},
                                  {"fuel": 300.0, "rows": [[100.0, 0.32, 1.1], [1000.0, 0.36, 1.1]]}]}
    client.post("/api/profiles", json={"document": _doc(region=REGION)})
    body = _preview(client, two, fuel=100.0).json()
    assert set(body["outlines"]) == {"100.0", "300.0"}
    assert body["outlines"]["100.0"] == body["outline"]  # 보이는 연료의 윤곽과 같은 것
    at = {o["alt"]: o for o in body["outlines"]["300.0"]}
    # 300 kg 층엔 3000 m 행이 없다 — 층 고도 밖이라 미정의(값을 지어내지 않는다), 1000 m는 그 층 값 그대로
    assert at[1000.0] == {"alt": 1000.0, "mach_lo": 0.36, "mach_hi": 1.1, "state": "in"}
    assert at[3000.0]["state"] == "undefined" and at[3000.0]["mach_lo"] is None
    # 경계표가 없으면(초안) 층이 없다 — 빈 사전
    assert _preview(client, None).json()["outlines"] == {}
