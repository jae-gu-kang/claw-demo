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
    cfg = _small_config(mode="gated", fit_tol=0.99, max_segments=1, max_degree=1,
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


def test_bad_types_are_422_not_500(client):
    """데이터클래스는 값을 강제 변환하지 않는다 — 타입 오류가 새면 500이 된다.

    형제 라우트(sim·codegen·influence)는 전부 (ValueError, TypeError)를 422로 매핑한다.
    """
    for cfg in (
        {"budget_points": "abc"},
        {"budget_iters": None},
        {"n_mach": "x"},
        {"refine_tol": "x"},
        {"alts": "notalist"},
        {"alts": ["x"]},
        {"targets": {"pm_deg": None}},
        {"criteria": {"pm_min_deg": "abc"}},
        {"mode": 3},
    ):
        r = client.post("/api/design/auto", json={"config": cfg})
        assert r.status_code == 422, f"{cfg} → {r.status_code} (500이면 잡 스레드에서 터진다)"


def test_nonfinite_config_is_422(client):
    """NaN·Inf는 제출 시점에 막는다 — 엔진 범위 비교를 조용히 통과하기 때문이다.

    통과한 NaN은 작동기·기준값을 오염시켜 마진이 전부 NaN이 되고, 문턱 비교가
    모조리 False라 **계산한 적 없는 판정이 합격으로 보고된다**. 202 잡이라
    화면에는 정상으로 보이므로 사용자가 알아챌 방법이 없다.
    """
    # 원시 본문으로 보낸다 — httpx의 json= 인코더는 NaN을 거부하지만 파이썬
    # json.loads(서버 파싱 경로)는 NaN·Infinity 리터럴을 받아들인다. 즉 이 경로는
    # 표준 클라이언트로 막히지 않는다
    for body in (
        '{"config": {"actuator_wn": NaN}}',
        '{"config": {"refine_tol": Infinity}}',
        '{"config": {"delay_s": -Infinity}}',
        '{"config": {"alts": [1000.0, NaN]}}',
        '{"config": {"fuels": [Infinity]}}',
        '{"config": {"criteria": {"pm_min_deg": NaN}}}',
        '{"config": {"targets": {"pm_deg": Infinity}}}',
    ):
        r = client.post("/api/design/auto", content=body,
                        headers={"content-type": "application/json"})
        assert r.status_code == 422, f"{body} → {r.status_code} (NaN이 새면 허위 합격 판정)"


def test_huge_int_stays_422(client):
    """double 범위를 넘는 정수도 422다 — 유한성 검사가 500을 만들지 않는다.

    json.loads는 임의 정밀도 int를 그대로 만들고 config는 dict라 pydantic이
    통과시킨다. 유한성 검사를 int에까지 걸면 math.isfinite가 OverflowError를
    내는데, 그건 라우트의 except (ValueError, TypeError)에 안 잡혀 500이 된다
    — 엔진 범위 검사는 큰 int도 멀쩡히 비교해 422를 내던 자리다.
    """
    big = "9" * 400
    for body in (f'{{"config": {{"budget_points": {big}}}}}',
                 f'{{"config": {{"budget_iters": {big}}}}}'):
        r = client.post("/api/design/auto", content=body,
                        headers={"content-type": "application/json"})
        assert r.status_code == 422, f"큰 int → {r.status_code} (500이면 유한성 검사가 터진 것)"


def test_nonterminating_targets_rejected(client):
    """백오프가 끝나지 않는 목표값은 제출 시점에 막는다 — 워커 영구 점유 방지."""
    for targets in ({"backoff": 1.0}, {"wc_att_floor_frac": 0.0}, {"wc_ratio_att": 0.0}):
        r = client.post("/api/design/auto", json={"config": {"targets": targets}})
        assert r.status_code == 422, f"{targets} → {r.status_code}"


def test_max_degree_bounded_to_gain_schema(client):
    """반출 다항이 게인 페이로드 스키마(구간 계수 8개)를 넘으면 되먹일 수 없다."""
    assert client.post("/api/design/auto",
                       json={"config": {"max_degree": 40}}).status_code == 422
    assert client.post("/api/design/auto",
                       json={"config": {"max_segments": 999}}).status_code == 422


def test_influence_accepts_poly_gain_tables(client):
    """게인 페이로드가 넓어졌으면 influence도 같은 빌더를 써야 한다 (500 금지)."""
    poly = {
        "kind": "poly", "axis": "mach",
        "segments": [
            {"x0": 0.15, "x1": 0.3, "coeffs": [-8.0, 0.0], "c": 0.225, "h": 0.075},
            {"x0": 0.3, "x1": 0.95, "coeffs": [-3.0, 2.0, -0.5], "c": 0.625, "h": 0.325},
        ],
    }
    r = client.post("/api/influence/structural", json={"gain_tables": {"pitch.kp": poly}})
    assert r.status_code == 200, r.text
    # 구간 검증 실패는 여전히 422 (500이 아니라)
    bad = {"kind": "poly", "axis": "mach", "segments": [
        {"x0": 0.15, "x1": 0.3, "coeffs": [1.0], "c": 0.2, "h": 0.1},
        {"x0": 0.4, "x1": 0.95, "coeffs": [1.0], "c": 0.6, "h": 0.3},
    ]}
    assert client.post("/api/influence/structural",
                       json={"gain_tables": {"pitch.kp": bad}}).status_code == 422


def test_missing_result_hints_at_retention_limit(client):
    """승인 대기 세션은 보존 상한에 밀려 사라질 수 있다 — 오타와 구별해 준다."""
    r = client.post("/api/design/no-such/resume", json={"approved": ["x"]})
    assert r.status_code == 404
    # 이 앱의 store에 상한이 걸려 있으면 그 사실을 알려 준다 (없으면 그냥 결과 없음)
    detail = r.json()["detail"]
    assert "결과 없음" in detail


def test_awaiting_approval_requires_at_least_one(client, wait_job):
    """승인 대기 상태에서 빈 승인 목록은 무의미한 재개 — 422로 막는다."""
    cfg = _small_config(mode="gated", fit_tol=0.99, max_segments=1, max_degree=1,
                        budget_iters=3)
    r = client.post("/api/design/auto", json={"config": cfg})
    j = wait_job(r.json()["id"], timeout=300.0)
    body = client.get(f"/api/results/{j['result_id']}").json()
    if body["report"]["status"] != "awaiting_approval":
        pytest.skip("이 형상에서 승인 대기가 아니다")
    r2 = client.post(f"/api/design/{j['result_id']}/resume", json={"approved": []})
    assert r2.status_code == 422
    assert "승인한 처방이 없다" in r2.json()["detail"]
