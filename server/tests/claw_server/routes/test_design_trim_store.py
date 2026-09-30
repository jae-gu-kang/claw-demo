"""자동 설계의 트림 저장소 재사용 (05 §11.10 사용자 후속 ③) — 조건·모델·풀이 설정이 같으면 트림을 다시 풀지 않는다.

서버 몫만 본다(엔진 쪽은 engine/claw/tests/test_design_trim_reuse.py):
- 제출도 재개도 저장소 창(refs.trim_scope)을 session.run(trim_store=)에 넘긴다 — 직렬화되지 않는 실행 인자라
  재개가 다시 주지 않으면 조용히 꺼진다(verdict_ctx와 같은 함정)
- 저장된 본문 최상위 trim_reuse · meta trim_reuse_counts — 형제 라우트 여섯 곳과 같은 칸 이름(refs.reuse_echo)
- 저장소가 꺼진 서버(CLAW_TRIM_STORE_LIMIT=0)는 창이 None이고 되울림이 policy "off" · enabled false다 — 종전 그대로다
- meta의 규모 셋(judged·failures·iterations)은 보고 값 그대로 — 목록 화면이 본문을 열지 않고 쓴다
"""

import time

import pytest
from fastapi.testclient import TestClient

from claw_server import create_app


def _small_config(**over):
    cfg = {"n_mach": 3, "alts": [1000.0], "fuels": [200.0],
           "budget_points": 24, "budget_iters": 2, "mode": "auto"}
    cfg.update(over)
    return cfg


def _example_trim_fingerprint():
    """예제 기체의 트림 지문 — 라우트가 창을 열 때 쓰는 그 값(refs.trim_scope ← BuiltProfile.trim_fingerprint)."""
    from claw.profile import example_profile

    return example_profile().trim_fingerprint


def _wait(client, job_id, timeout=300.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.02)
    pytest.fail(f"잡이 끝나지 않았다: {job_id}")


def _spy(monkeypatch, seen, status="converged", stage="DONE"):
    """session.run을 대신해 받은 trim_store만 적는다 — 실제 설계 1회는 수십 초이고, 여기서 볼 것은 인계 하나다."""
    import claw_server.routes.design as design_route

    def spy_run(self, *args, **kwargs):
        seen.append(kwargs.get("trim_store"))
        # 진짜 run이 하는 것 중 **보고에 보이는 것**만 대신한다 — 창을 세션에 앉히지 않으면
        # report()["trim_reuse"]["enabled"]가 늘 False라 되울림을 볼 수 없다(엔진 run의 첫 줄)
        self._trim_store = kwargs.get("trim_store")
        self.status, self.stage = status, stage
        return self.report()

    # raising=False를 쓰지 않는다 — run이 개명되면 새 속성을 조용히 만들어 진짜 경로를 안 건드린 채 통과한다
    monkeypatch.setattr(design_route.DesignSession, "run", spy_run)
    return spy_run


def test_submit_hands_the_session_the_trim_store_scope(client, monkeypatch):
    seen = []
    _spy(monkeypatch, seen)
    r = client.post("/api/design/auto", json={"config": _small_config()})
    assert r.status_code == 202
    assert _wait(client, r.json()["id"])["status"] == "done"
    assert len(seen) == 1
    scope = seen[0]
    assert scope is not None, "라우트가 트림 저장소 창을 안 넘긴다 — 설계가 늘 전부 새로 푼다"
    assert scope.trim_fingerprint == _example_trim_fingerprint()


def test_resume_hands_the_scope_again_from_the_snapshot_profile(client, monkeypatch):
    """재개도 창을 다시 줘야 한다 — trim_store는 verdict_ctx처럼 직렬화되지 않는다(재개만 조용히 꺼지는 함정)."""
    seen = []
    _spy(monkeypatch, seen, status="cancelled", stage="COARSE")
    r = client.post("/api/design/auto", json={"config": _small_config()})
    j = _wait(client, r.json()["id"])
    assert j["status"] == "done"
    rid = j["result_id"]
    assert client.get(f"/api/results/{rid}").json()["status"] == "cancelled"
    r2 = client.post(f"/api/design/{rid}/resume", json={"approved": []})
    assert r2.status_code == 202, r2.text
    assert _wait(client, r2.json()["id"])["status"] == "done"
    assert len(seen) == 2
    # 스냅숏 기체의 지문 창 — 제출 때와 같은 기체이므로 같은 창이다(문서가 바뀌면 다른 창이 온다)
    assert seen[1] is not None, "재개가 창을 안 넘긴다 — 재개 실행만 저장소를 못 쓴다"
    assert seen[1].trim_fingerprint == seen[0].trim_fingerprint == _example_trim_fingerprint()


def test_saved_result_carries_the_reuse_echo_and_the_meta_counts(client, monkeypatch):
    """되울림 자리·칸 이름은 형제 라우트와 같다 — 웹 lib/opspace.js reuseLine이 그대로 읽는다."""
    seen = []
    _spy(monkeypatch, seen)
    r = client.post("/api/design/auto", json={"config": _small_config()})
    rid = _wait(client, r.json()["id"])["result_id"]
    body = client.get(f"/api/results/{rid}").json()
    echo = body["trim_reuse"]
    assert set(echo) == {"trim_fingerprint", "reused", "computed", "policy", "enabled"}
    assert echo["trim_fingerprint"] == _example_trim_fingerprint()
    assert echo["policy"] == "converged" and echo["enabled"] is True
    # 스파이가 스테이지를 안 돌렸으니 센 트림도 없다 — 0을 다른 수로 위장하지 않는다
    assert echo["reused"] == 0 and echo["computed"] == 0
    # 보고 쪽 집계와 같은 수 — 두 자리가 갈리면 화면이 어느 쪽을 봤는지에 따라 다른 말을 한다
    assert body["report"]["trim_reuse"]["reused"] == echo["reused"]
    assert body["report"]["trim_reuse"]["computed"] == echo["computed"]
    meta = next(m for m in client.get("/api/results").json() if m["id"] == rid)
    assert meta["trim_reuse_counts"] == {"reused": 0, "computed": 0}


def test_meta_carries_the_report_scale_counts(client, monkeypatch):
    """목록 화면(설계 흐름 개체 목록)이 본문을 열지 않고 규모를 쓴다 — 보고 값 그대로여야 한다."""
    seen = []
    _spy(monkeypatch, seen)
    r = client.post("/api/design/auto", json={"config": _small_config()})
    rid = _wait(client, r.json()["id"])["result_id"]
    rep = client.get(f"/api/results/{rid}").json()["report"]
    meta = next(m for m in client.get("/api/results").json() if m["id"] == rid)
    for key in ("judged", "failures", "iterations"):
        assert meta[key] == rep[key], key


def test_store_off_server_is_unchanged(tmp_path, monkeypatch):
    """CLAW_TRIM_STORE_LIMIT=0 — 창이 None이라 엔진은 종전 그대로 풀고, 되울림이 그 사실을 말한다."""
    monkeypatch.setenv("CLAW_TRIM_STORE_LIMIT", "0")
    app = create_app(data_dir=tmp_path / "s")
    assert app.state.trim_store.max_entries == 0
    with TestClient(app) as c:
        seen = []
        _spy(monkeypatch, seen)
        r = c.post("/api/design/auto", json={"config": _small_config()})
        rid = _wait(c, r.json()["id"])["result_id"]
        assert seen == [None], "저장소가 꺼졌는데 창이 왔다 — 꺼진 서버의 동작이 바뀐다"
        body = c.get(f"/api/results/{rid}").json()
        assert body["trim_reuse"]["policy"] == "off"
        assert body["trim_reuse"]["enabled"] is False
        assert body["report"]["trim_reuse"]["enabled"] is False
        # 지문은 꺼진 저장소에서도 싣는다 — 어느 트림 키 공간의 계산이었는지는 저장소 유무와 무관하다
        assert body["trim_reuse"]["trim_fingerprint"] == _example_trim_fingerprint()


def test_second_design_reuses_the_first_designs_trims(client):
    """실물 두 번 — 같은 기체·같은 설정의 두 번째 설계는 트림을 저장소에서 꺼낸다(재계산 0회가 목표인 자리)."""
    def run():
        r = client.post("/api/design/auto", json={"config": _small_config()})
        assert r.status_code == 202, r.text
        j = _wait(client, r.json()["id"])
        assert j["status"] == "done", j
        rid = j["result_id"]
        return client.get(f"/api/results/{rid}").json(), rid

    first, _ = run()
    # 실물 경로에서 enabled가 참이다 — 엔진 run이 창을 받았다는 되울림(서버가 계산만 하고 안 넘기면 거짓이 된다)
    assert first["trim_reuse"]["enabled"] is True and first["trim_reuse"]["policy"] == "converged"
    assert first["trim_reuse"]["computed"] > 0, "첫 설계가 트림을 하나도 풀지 않았다 — 전제가 바뀌었다"
    assert first["trim_reuse"]["reused"] == 0  # 빈 저장소
    second, rid2 = run()
    assert second["trim_reuse"]["reused"] > 0, (
        "두 번째 설계가 같은 조건의 트림을 다시 풀었다 — 저장소 창이 실제로는 안 쓰인다")
    # 같은 설정이면 같은 점을 본다 — 재사용 + 새로 푼 수의 합이 첫 실행과 같다
    assert (second["trim_reuse"]["reused"] + second["trim_reuse"]["computed"]
            == first["trim_reuse"]["reused"] + first["trim_reuse"]["computed"])
    meta = next(m for m in client.get("/api/results").json() if m["id"] == rid2)
    assert meta["trim_reuse_counts"]["reused"] == second["trim_reuse"]["reused"]
