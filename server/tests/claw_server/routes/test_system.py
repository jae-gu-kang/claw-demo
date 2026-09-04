"""시스템 라우트 검증 — 레지스트리 인덱스·스키마 (웹 폼 자동 생성 원천), 검증, 404."""

import importlib


def test_registry_index_lists_engine_components(client):
    reg = client.get("/api/registry").json()
    assert {"actuator", "blocks", "guidance", "fcl", "nav", "propulsion"} <= set(reg)
    assert "SecondOrderActuator" in reg["actuator"]
    assert "LOS" in reg["guidance"]
    assert "PID" in reg["blocks"]
    # 법칙 컴포넌트 (블록 파라미터 폼 원천 — 02 §2.3)
    assert {"Autopilot", "ScasAxis", "Mixer"} <= set(reg["fcl"])
    assert "ErrorModel" in reg["nav"]
    # 추진 — 블록도 하위 페이지(#blocks/plant/prop)가 **PropEngine**으로 표를 그린다
    # (데모 정본 형상 — 속도·밀도 의존 프로펠러 곡선). SingleEngine·TwinEngine은
    # 상수 추력 형태로 함께 등록돼 있다
    assert {"PropEngine", "SingleEngine", "TwinEngine"} <= set(reg["propulsion"])


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
    # commit 키는 **항상** 있다 — 없으면 소비자가 "옛 서버라 키가 없다"와
    # "커밋을 모른다"를 구분하지 못한다. 로컬 실행은 값이 None
    assert "commit" in body


def test_health_commit_is_the_deploy_identity_or_honest_none(monkeypatch):
    """version은 정적 문자열이라 "어느 커밋이 떠 있나"에 답하지 못한다.

    공개 데모는 /api/health만 무인증이라 밖에서 형상을 확인할 통로가 여기뿐이다.
    모를 때 빈 문자열이나 "unknown"을 내면 소비자가 그것을 SHA로 착각해 비교한다.
    """
    from claw_server.routes.system import deployed_commit

    monkeypatch.delenv("CLAW_GIT_COMMIT", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert deployed_commit() is None

    # Render는 배포마다 자동 주입 — 설정 없이 동작해야 한다
    monkeypatch.setenv("RENDER_GIT_COMMIT", "bb39616deadbeef")
    assert deployed_commit() == "bb39616deadbeef"
    # 플랫폼 중립 오버라이드가 이긴다 (Render 아닌 배포가 직접 넣는 값)
    monkeypatch.setenv("CLAW_GIT_COMMIT", "cafebabe1234")
    assert deployed_commit() == "cafebabe1234"
    # 빈 값·공백은 미설정과 같다 — 플랫폼이 빈 문자열을 주는 경우 방어
    monkeypatch.setenv("CLAW_GIT_COMMIT", "   ")
    assert deployed_commit() == "bb39616deadbeef"
    # 양옆 공백은 **벗긴다** — 그대로 나가면 소비자의 SHA 비교가 조용히 실패한다.
    # 화면에는 SHA가 멀쩡히 보이므로 원인이 눈에 안 띈다
    monkeypatch.setenv("CLAW_GIT_COMMIT", "  abc123  ")
    assert deployed_commit() == "abc123"


def test_health_actually_serves_the_commit_not_just_the_key(client, monkeypatch):
    """라우트가 값을 **실어 나르는지** 핀한다.

    키 존재만 보면 `"commit": None` 하드코딩으로도 통과한다(실측). 그 실패는
    "Render가 주입을 안 했다"와 **바이트 단위로 같은 응답**이라, 확인하는 사람이
    코드가 아니라 플랫폼을 의심하며 다시 대시보드를 열게 된다 — 이 필드가
    없애려던 바로 그 상태로, 이번엔 원인이 안 보이는 채로 돌아간다.
    """
    monkeypatch.setenv("CLAW_GIT_COMMIT", "cafebabe1234")
    assert client.get("/api/health").json()["commit"] == "cafebabe1234"
    monkeypatch.delenv("CLAW_GIT_COMMIT")
    assert client.get("/api/health").json()["commit"] is None


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
