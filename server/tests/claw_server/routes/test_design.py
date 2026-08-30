"""자동 설계 라우트 검증 — 기본값 응답, 202 잡, 저장 스키마, 예산 422, gated 재개."""

import math
import types

import numpy as np
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


def test_defaults_expose_reason_text(client):
    """튜닝 포기 사유의 설명 문구는 엔진이 정본 — 웹이 다시 적으면 두 곳이 갈린다.

    갈린 쪽이 화면이라 사용자는 엔진이 뜻하지 않은 안내를 읽는다 (tune.py REASON_*
    머리말의 실제 사고: 마진은 통과했는데 "마진 미달"이라 적혀 있었다). criteria
    기본값을 웹이 재기술하지 않는 것과 같은 이유로 이 표도 /defaults가 내려 준다.
    """
    from claw.design.tune import REASON_TEXT

    body = client.get("/api/design/defaults").json()
    assert body["reason_text"] == REASON_TEXT  # 엔진 표 그대로 — 서버가 손대지 않는다
    # 사유 코드가 늘면 표도 함께 늘어야 한다 (코드만 늘고 문구가 없으면 화면이 빈다)
    assert "target_unreached" in body["reason_text"]
    assert all(isinstance(v, str) and v for v in body["reason_text"].values())


def test_defaults_expose_lambda_fracs(client):
    """λ 합격선은 절대값이 아니라 목표 대비 비율이다 — 그 비율도 엔진이 정본이다.

    lam_min_frac·lam_good_frac이 /defaults에 안 나오면 웹은 λ 자리를 색칠할 근거가
    없어 수치를 하드코딩하게 된다 (criteria 이관 이전 상태로 되돌아간다).
    """
    from claw.design import MarginCriteria

    cr = client.get("/api/design/defaults").json()["config"]["criteria"]
    assert cr["lam_min_frac"] == MarginCriteria().lam_min_frac == 0.5
    assert cr["lam_good_frac"] == MarginCriteria().lam_good_frac == 0.8


def test_criteria_override_reaches_saved_config(client, wait_job):
    """중첩 criteria 덮어쓰기가 **저장된 세션 config까지** 실제로 도달하는지.

    202만 보면 부족하다 — _build_config가 중첩 override를 조용히 무시해도 요청은
    수락되고, 사용자는 0.6으로 판정했다고 믿은 채 0.5로 판정한 결과를 읽는다.
    안 적은 형제 필드가 엔진 기본값으로 남는 것도 함께 본다 (덮어쓰기가 판정선
    전체를 갈아 끼우면 안 된다).
    """
    cfg = _small_config(criteria={"lam_min_frac": 0.6})
    r = client.post("/api/design/auto", json={"config": cfg})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done"
    saved = client.get(f"/api/results/{j['result_id']}").json()["config"]["criteria"]
    assert saved["lam_min_frac"] == 0.6  # 덮어쓴 값
    assert saved["lam_good_frac"] == 0.8  # 안 적은 형제는 엔진 기본값 유지
    assert saved["pm_min_deg"] == 45.0


def test_invalid_lambda_fracs_are_422_before_202(client):
    """모순된 λ 비율은 제출 시점에 막는다 — 202로 새면 워커를 돌린 뒤에야 안다.

    MarginCriteria.__post_init__의 ValueError가 _build_config →
    submit_auto_design의 except (ValueError, TypeError)까지 도달하는 경로를 고정한다.
    놓치면 500이거나(예외가 새는 경우) 잡 스레드 안에서 터져 원인 없는 실패가 된다.
    """
    for criteria in (
        {"lam_min_frac": 0.9},  # > lam_good_frac(0.8) — 합격선이 목표선보다 높다
        {"lam_good_frac": 1.5},  # > 1 — 목표의 150%를 목표선으로 삼을 수는 없다
        {"lam_min_frac": 0.0},  # 0 이하 — 무엇이든 통과하는 합격선
        {"lam_min_frac": 0.9, "lam_good_frac": 0.85},  # 둘 다 적어도 순서는 지켜야 한다
    ):
        r = client.post("/api/design/auto", json={"config": {"criteria": criteria}})
        assert r.status_code == 422, f"{criteria} → {r.status_code}"


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
    # 처방 효과 회계 — "처방을 냈다"와 "고쳤다"는 다르다 (실제 실행에서도 실린다)
    for key in ("ineffective_actions", "sealed", "fit_tighten"):
        assert isinstance(body["report"][key], int), key
    export = body["gain_export"]
    assert export["tables"] or export["constants"]
    # 반출 테이블은 sim/codegen 페이로드에 그대로 주입 가능한 형상
    for spec in export["tables"].values():
        assert spec.get("kind") == "poly" or ("axes" in spec and "data" in spec)
    # 재양자화 고지 — 자리마다 빠짐없이 (하나라도 비면 웹이 그 자리를 무오차로 읽는다)
    assert export["resample_tol"] > 0.0
    assert set(export["resample_error"]) == set(export["tables"])
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
    # delay_s·criteria 두 줄은 엔진 __post_init__(delay_s < 0, pm_bad <= pm_min)이
    # 먼저 잡아 이 가드가 없어도 422다 — 계약 표현이지 가드의 증거는 아니다.
    # 나머지 다섯이 가드를 고정한다(빼면 전부 202로 샌다)
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
    """double 범위를 넘는 정수는 422다 — 중첩이든 top-level이든.

    json.loads는 임의 정밀도 int를 그대로 만들고 config는 dict라 pydantic이
    통과시킨다. 서버가 안 막으면 새는 방식이 자리마다 다르다: 중첩(criteria·
    targets)은 엔진 from_dict의 float()에서 OverflowError → **500**, top-level
    스칼라와 alts/fuels 항목은 config 층에 변환 자리가 없어 **조용히 202**로
    수용된 뒤 잡 스레드로 넘어간다. 아래 여섯은 그 두 갈래를 모두 덮는다 —
    다른 상한에 먼저 걸려 어차피 422가 되는 자리(budget_points·budget_iters)는
    이 검사를 고정하지 못해 뺐다.
    """
    big = "9" * 400
    for body in (f'{{"config": {{"actuator_wn": {big}}}}}',      # top-level → 202로 샘
                 f'{{"config": {{"pade_order": {big}}}}}',
                 f'{{"config": {{"budget_tune_evals": {big}}}}}',
                 f'{{"config": {{"alts": [{big}]}}}}',
                 f'{{"config": {{"criteria": {{"pm_min_deg": {big}}}}}}}',  # 중첩 → 500
                 f'{{"config": {{"targets": {{"pm_deg": {big}}}}}}}'):
        r = client.post("/api/design/auto", content=body,
                        headers={"content-type": "application/json"})
        assert r.status_code == 422, f"큰 int → {r.status_code} (500 또는 조용한 202로 샌 것)"


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


def test_missing_result_hints_at_retention_limit(tmp_path):
    """승인 대기 세션은 보존 상한에 밀려 사라질 수 있다 — 오타와 구별해 준다.

    conftest의 autouse 픽스처가 CLAW_RESULT_LIMIT를 지우므로 기본 client의
    store.limit은 **항상 None**이다 — 그 앱으로는 힌트 분기가 한 번도 실행되지
    않아, 힌트를 통째로 지워도 테스트가 통과한다. 상한을 건 앱을 따로 세운다.
    """
    from fastapi.testclient import TestClient

    from claw_server import create_app

    with TestClient(create_app(data_dir=tmp_path / "store", result_limit=3)) as c:
        r = c.post("/api/design/no-such/resume", json={"approved": ["x"]})
        assert r.status_code == 404
        assert "보존 상한 3건" in r.json()["detail"]


def test_malformed_id_is_422_without_retention_hint(client):
    """저장될 수 없는 형식의 id는 밀려난 것이 아니다 — 힌트가 반대로 안내하면 안 된다."""
    r = client.post("/api/design/a.b/resume", json={"approved": ["x"]})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "잘못된 결과 id" in detail
    assert "보존 상한" not in detail


def test_cancelled_session_resumes_without_approvals(client, tmp_path):
    """이번 수정의 본래 시나리오 — 취소 세션은 승인할 처방이 없어도 재개된다.

    종전에는 ResumeIn 스키마(min_length=1)가 핸들러 진입 전에 422로 막았다.
    엔진 테스트는 DesignSession.run만 덮어 이 경로를 지나지 않는다.
    """
    from claw.design import AutoDesignConfig, DesignSession

    s = DesignSession(AutoDesignConfig(n_mach=3, alts=(1000.0,), fuels=(200.0,),
                                       budget_points=12, budget_iters=2))
    s.status = "cancelled"
    payload = s.to_dict()
    payload["report"] = s.report()
    payload["proposed_actions"] = []
    payload["gain_export"] = {"tables": {}, "tables_resampled": {}, "constants": {}}
    client.app.state.store.save("cancelled-x", payload,
                                meta={"kind": "auto_design", "created": 0.0,
                                      "status": "cancelled", "stage": "COARSE"})
    r = client.post("/api/design/cancelled-x/resume", json={"approved": []})
    assert r.status_code == 202, r.text


def test_schema_mismatch_is_409_not_500(client):
    """저장된 세션이 지금 엔진 스키마와 안 맞으면 409 — 500으로 새면 안 된다."""
    client.app.state.store.save("stale-x", {"kind": "auto_design", "config": {"nope": 1}},
                                meta={"kind": "auto_design", "created": 0.0})
    r = client.post("/api/design/stale-x/resume", json={"approved": ["x"]})
    assert r.status_code == 409
    assert "스키마" in r.json()["detail"]


def test_non_integer_counts_rejected(client):
    """격자 개수·차수에 float을 넣으면 엔진 범위 비교는 통과하고 잡 안에서 터진다."""
    for cfg in ({"n_mach": 2.5}, {"pade_order": 2.5}, {"budget_points": 24.7},
                {"max_degree": 3.5}):
        r = client.post("/api/design/auto", json={"config": cfg})
        assert r.status_code == 422, f"{cfg} → {r.status_code}"
    # 정수값 float은 통과해야 한다 (JSON은 24와 24.0을 구별하지 않는다)
    assert client.post("/api/design/auto",
                       json={"config": _small_config(budget_points=24.0)}
                       ).status_code == 202


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


def _effect_session():
    """처방 효과 회계가 채워진 세션 — 실행 없이 저장 계약만 보기 위한 최소 구성."""
    from claw.design import AutoDesignConfig, DesignSession

    s = DesignSession(AutoDesignConfig())
    s.fit_tighten = 2
    s.refit_gains = {"pitch.kp": {"m060_a05000_f0200": 1.25}}
    # 봉인은 _SEAL_AFTER(2)회 연속 무효부터 — 1회짜리는 아직 봉인이 아니다
    s.ineffective = {"m060_a05000_f0200|pitch_att|margin_deficit": 2,
                     "m080_a05000_f0200|yaw_damper|damping_deficit": 1}
    s.applied_log = [
        {"id": "a1", "iter": 0, "case": "m060_a05000_f0200", "loop": "pitch_att",
         "verdict": "margin_deficit", "type": "refit_at",
         "effect": {"before": {"status": "fail", "severity": 0.2},
                    "after": {"status": "fail", "severity": 0.2}, "changed": False}},
        {"id": "a2", "iter": 0, "case": "m080_a05000_f0200", "loop": "yaw_damper",
         "verdict": "damping_deficit", "type": "promote",
         # 측정 불가 자리 — severity가 원시 inf/nan으로 남은 기록 (직렬화 정책 표적)
         "effect": {"before": {"status": "fail", "severity": math.inf},
                    "after": {"status": "na", "severity": math.nan}, "changed": True}},
    ]
    s.margin_out = {"cases": {}, "failures": [
        {"case": "m080_a05000_f0200", "loop": "yaw_damper", "severity": math.inf},
    ]}
    return s


def test_saved_result_carries_effect_accounting(client):
    """처방 효과 회계가 저장 → 조회 왕복에서 살아남는지 — report·to_dict 양쪽.

    report의 ineffective_actions·sealed·fit_tighten과 to_dict의 refit_gains·
    fit_tighten·applied_log·ineffective는 "반영했는데 안 고쳐졌다"를 화면이 말할
    수 있게 하는 유일한 근거다. _save_session이 세 조각(to_dict·report·
    proposed_actions)을 손으로 이어 붙이므로, 엔진에 필드가 늘어도 서버가 저장을
    안 하면 아무 데서도 안 터지고 조용히 사라진다.
    """
    from claw_server.routes.design import _save_session

    s = _effect_session()
    job = types.SimpleNamespace(id="effect-x", created=0.0, result_id=None)
    _save_session(client.app.state.store, job, s, "fp-effect")
    assert job.result_id == "effect-x"

    body = client.get("/api/results/effect-x").json()
    rep = body["report"]
    assert rep["ineffective_actions"] == 1  # changed=False인 기록만
    assert rep["sealed"] == 1  # 연속 2회짜리 하나 (1회짜리는 아직 아니다)
    assert rep["fit_tighten"] == 2
    assert body["fit_tighten"] == 2
    assert body["refit_gains"] == {"pitch.kp": {"m060_a05000_f0200": 1.25}}
    assert [r["id"] for r in body["applied_log"]] == ["a1", "a2"]
    assert body["ineffective"]["m060_a05000_f0200|pitch_att|margin_deficit"] == 2


def test_saved_effect_log_obeys_nonfinite_policy(client):
    """측정 불가 자리의 inf/nan이 직렬화 정책을 우회하지 않는지 — 저장이 터지는 자리다.

    criteria.severity는 볼 지표가 없으면 +inf다. ResultStore는 allow_nan=False라
    원시 inf가 한 조각이라도 남아 있으면 **저장 시점에 ValueError**로 세션 전량이
    소실된다 (잡은 이미 202로 답한 뒤다). _save_session이 store.save 직전에
    payload 전체를 to_jsonable로 마감하는 것이 그 방어다 — 새 필드를 그 봉투 밖에서
    이어 붙이거나 마감을 빠뜨리면 여기서 걸린다.
    """
    from claw_server.routes.design import _save_session

    s = _effect_session()
    job = types.SimpleNamespace(id="policy-x", created=0.0, result_id=None)
    _save_session(client.app.state.store, job, s, "fp-policy")  # 여기서 안 터져야 한다

    body = client.get("/api/results/policy-x").json()
    eff = body["applied_log"][1]["effect"]
    assert eff["before"]["severity"] == "inf"  # ±inf → 문자열
    assert eff["after"]["severity"] is None  # NaN → null
    assert body["margin_out"]["failures"][0]["severity"] == "inf"


def _poly_session():
    """다항 한 자리 + 격자 한 자리 — 재샘플 고지의 두 갈래를 다 덮는 최소 구성."""
    from claw.design import AutoDesignConfig, DesignSession
    from claw.tables import PolyTable, Table

    s = DesignSession(AutoDesignConfig())
    s.sched_tables = {
        # 3차 곡선 — 선형 재샘플이 반드시 어긋난다 (오차 0이 나오면 재측정이 가짜다)
        "pitch.kp": PolyTable("mach", [
            {"x0": 0.2, "x1": 0.6, "coeffs": [-2.0, 1.5, -3.0, 2.0], "c": 0.4, "h": 0.2},
            {"x0": 0.6, "x1": 0.95, "coeffs": [-1.0, 0.5, 4.0], "c": 0.775, "h": 0.175},
        ], name="pitch.kp"),
        "yaw.k_rate": Table({"mach": [0.2, 0.6, 0.95]}, [1.0, 2.0, 3.0], name="yaw.k_rate"),
    }
    s.sched_constants = {"roll.ki": 0.5}
    return s


def test_gain_export_reports_resample_error(client):
    """"게인 확정"이 주입하는 것은 검증한 다항이 아니라 재양자화된 테이블이다.

    tables_resampled는 resample_to_table의 tol_interp로 다시 양자화한 근사인데,
    세션이 검증한(margin_out) 형상은 다항 쪽이다. 그 차이를 반출이 말하지 않으면
    화면은 "확정"이 검증 결과를 그대로 물려받는 것처럼 보인다. 실제로 쓴 허용치와
    자리별 최대 어긋남이 함께 실리는지 고정한다.
    """
    from claw_server.routes.design import _RESAMPLE_TOL, _gain_export

    ex = _gain_export(_poly_session())
    assert ex["resample_tol"] == _RESAMPLE_TOL
    assert set(ex["resample_error"]) == {"pitch.kp", "yaw.k_rate"}

    err = ex["resample_error"]["pitch.kp"]
    assert err["max_abs"] > 0.0  # 곡선을 직선으로 이었으니 0일 수 없다
    assert err["n_points"] == len(ex["tables_resampled"]["pitch.kp"]["data"])
    # 격자 자리는 재샘플이 곧 원본 — 오차가 정의상 0이다 (다항 경로와 뭉뚱그리지 않는다)
    assert ex["resample_error"]["yaw.k_rate"]["max_abs"] == 0.0


def test_resample_error_is_measured_not_assumed(client):
    """보고한 오차가 실제로 잰 값인지 — tol을 그대로 베껴 적는 것과 구별한다.

    resample_to_table의 tol_interp는 목표치이지 보장이 아니다(구간 중점만 보며
    이분하고 max_pts·depth 상한에서 멈춘다). 그래서 허용치를 오차로 되받아 적으면
    "이만큼 어긋난다"가 거짓이 된다. 보고된 지점(at)에서 다항과 재샘플 테이블을
    직접 평가해 max_abs와 맞는지 확인한다.
    """
    from claw.tables import Table
    from claw_server.routes.design import _gain_export

    s = _poly_session()
    ex = _gain_export(s)
    err = ex["resample_error"]["pitch.kp"]
    spec = ex["tables_resampled"]["pitch.kp"]
    rt = Table(spec["axes"], spec["data"], extrapolate="clip")

    at = err["at"]
    poly = s.sched_tables["pitch.kp"]
    assert err["max_abs"] == pytest.approx(
        abs(float(poly.interp(mach=at)) - float(rt.interp(mach=at))), rel=1e-9, abs=1e-12
    )
    # max_frac은 곡선 진폭 대비 — resample_tol과 같은 자여야 나란히 놓고 읽을 수 있다
    scale = float(np.max(np.abs(poly.interp(mach=np.linspace(0.2, 0.95, 1001)))))
    assert err["max_frac"] == pytest.approx(err["max_abs"] / scale, rel=1e-3)
