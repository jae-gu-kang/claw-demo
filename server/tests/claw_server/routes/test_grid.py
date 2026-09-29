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
