"""시스템 라우트 검증 — 레지스트리 인덱스·스키마 (웹 폼 자동 생성 원천), 검증, 404."""

import importlib


def test_registry_index_lists_engine_components(client):
    reg = client.get("/api/registry").json()
    assert {"actuator", "blocks", "guidance", "fcl", "nav"} <= set(reg)
    assert "SecondOrderActuator" in reg["actuator"]
    assert "LOS" in reg["guidance"]
    assert "PID" in reg["blocks"]
    # 법칙 컴포넌트 (블록 파라미터 폼 원천 — 02 §2.3)
    assert {"Autopilot", "ScasAxis", "Mixer"} <= set(reg["fcl"])
    assert "ErrorModel" in reg["nav"]


def test_registry_schema_for_form_autogen(client):
    r = client.get("/api/registry/actuator/SecondOrderActuator/schema")
    assert r.status_code == 200
    schema = r.json()
    assert schema["title"] == "actuator/SecondOrderActuator"
    assert "properties" in schema  # 단위·범위 메타 → 폼 자동 생성 (02 §5.5)


def test_registry_schema_unknown_404(client):
    assert client.get("/api/registry/actuator/nope/schema").status_code == 404
    assert client.get("/api/registry/nocat/x/schema").status_code == 404


def test_health_reports_versions_for_traceability(client):
    """생성 코드·리포트가 인용할 버전 메타 — 어느 엔진으로 뽑은 형상인지."""
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["version"] and body["engine"]


def test_validate_returns_importable_symbol(client):
    """웹 코드 생성은 클래스명을 추론하지 않고 여기서 받는다 — 회신 경로가
    실제로 임포트되고 그 이름이 클래스여야 생성 코드가 실행된다."""
    r = client.post("/api/registry/fcl/Autopilot/validate", json={"values": {"kp_spd": 0.62}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["py_class"] == "Autopilot"
    assert isinstance(getattr(importlib.import_module(body["py_import"]), "Autopilot"), type)


def test_validate_resolves_class_name_that_differs_from_registry_name(client):
    """nav/ErrorModel의 실제 클래스는 NavErrorModel — 이름 추론이 불가능함을 고정."""
    body = client.post("/api/registry/nav/ErrorModel/validate", json={"values": {}}).json()
    assert body["py_class"] == "NavErrorModel"
    assert getattr(importlib.import_module(body["py_import"]), "NavErrorModel", None) is not None


def test_validate_rejects_engine_cross_condition(client):
    """범위 검사만으로는 못 잡는 교차 조건(θ 하한 > 상한) — 엔진 생성자가 판정."""
    r = client.post(
        "/api/registry/fcl/Autopilot/validate",
        json={"values": {"theta_lo": 0.2, "theta_hi": -0.2}},
    )
    assert r.status_code == 422
    assert r.json()["detail"]  # 엔진 메시지 전달


def test_validate_rejects_out_of_range_and_nan(client):
    """NaN은 ParamDef 범위 비교(v < lo)를 조용히 통과하므로 서버가 먼저 차단."""
    import json as _json

    assert client.post(
        "/api/registry/fcl/Autopilot/validate", json={"values": {"phi_max": 9.0}}
    ).status_code == 422
    raw = _json.dumps({"values": {"phi_max": float("nan")}})  # httpx json=은 NaN 자체 거부
    assert client.post(
        "/api/registry/fcl/Autopilot/validate",
        content=raw, headers={"content-type": "application/json"},
    ).status_code == 422


def test_validate_unknown_component_404(client):
    assert client.post(
        "/api/registry/fcl/Nope/validate", json={"values": {}}
    ).status_code == 404
