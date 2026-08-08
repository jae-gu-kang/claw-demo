"""시스템 라우트 검증 — 레지스트리 인덱스·스키마 (웹 폼 자동 생성 원천), 404."""


def test_registry_index_lists_engine_components(client):
    reg = client.get("/api/registry").json()
    assert {"actuator", "blocks", "guidance"} <= set(reg)
    assert "SecondOrderActuator" in reg["actuator"]
    assert "LOS" in reg["guidance"]
    assert "PID" in reg["blocks"]


def test_registry_schema_for_form_autogen(client):
    r = client.get("/api/registry/actuator/SecondOrderActuator/schema")
    assert r.status_code == 200
    schema = r.json()
    assert schema["title"] == "actuator/SecondOrderActuator"
    assert "properties" in schema  # 단위·범위 메타 → 폼 자동 생성 (02 §5.5)


def test_registry_schema_unknown_404(client):
    assert client.get("/api/registry/actuator/nope/schema").status_code == 404
    assert client.get("/api/registry/nocat/x/schema").status_code == 404
