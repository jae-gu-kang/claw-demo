"""자동 설계의 트림 저장소 재사용 (05 §11.10 사용자 후속 ③) — **기본 끔**, config.trim_reuse로 켠다.

서버 몫만 본다(엔진 쪽은 engine/claw/tests/test_design_trim_reuse.py):
- 창을 주는 스위치는 **저장된 세션 설정**이다(routes/design.py `_design_trim_scope`) — 끈 설정으로 제출한 세션이
  재개에서 조용히 켜지지 않고, 켠 설정은 제출·재개 두 길에서 다 창을 받는다(직렬화되지 않는 실행 인자라 재개가
  다시 주지 않으면 조용히 꺼진다 — verdict_ctx와 같은 함정)
- 기본값(끔)으로 돈 설계는 저장소가 꺼진 서버의 결과와 같다 — 재현성이 기본값의 이유다
- 저장된 본문 최상위 trim_reuse · meta trim_reuse_counts — 형제 라우트 여섯 곳과 같은 칸 이름(refs.reuse_echo).
  policy는 "converged"|"off"이고 off면 policy_reason이 어느 스위치였는지(config·store_disabled) 말한다
- 켠 실행의 되울림은 reused_names를 싣는다 — 놀라운 failures를 뒤에 되짚는 단서
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


def test_submit_hands_no_scope_by_default(client, monkeypatch):
    """기본값은 끔 — 설정이 켜지 않으면 창을 주지 않는다(05 §11.10 재현성). 되울림이 그 사유를 말한다."""
    seen = []
    _spy(monkeypatch, seen)
    r = client.post("/api/design/auto", json={"config": _small_config()})
    assert r.status_code == 202
    rid = _wait(client, r.json()["id"])["result_id"]
    assert seen == [None], "설정이 껐는데 창이 왔다 — 설계 결과가 저장소 상태에 따라 달라진다"
    echo = client.get(f"/api/results/{rid}").json()["trim_reuse"]
    assert echo["policy"] == "off" and echo["policy_reason"] == "config" and echo["enabled"] is False


def test_submit_hands_the_scope_when_the_flag_is_on(client, monkeypatch):
    seen = []
    _spy(monkeypatch, seen)
    r = client.post("/api/design/auto", json={"config": _small_config(trim_reuse=True)})
    assert r.status_code == 202
    assert _wait(client, r.json()["id"])["status"] == "done"
    assert len(seen) == 1
    scope = seen[0]
    assert scope is not None, "켰는데 라우트가 창을 안 넘긴다 — 옵트인이 통하지 않는다"
    assert scope.trim_fingerprint == _example_trim_fingerprint()


def test_a_non_bool_flag_is_422(client):
    """참거짓만 — 0/1이나 "true"를 참거짓으로 읽으면 사용자가 켠 줄 모르고 켜진다."""
    for bad in (1, "true"):
        r = client.post("/api/design/auto", json={"config": _small_config(trim_reuse=bad)})
        assert r.status_code == 422, (bad, r.text)
        assert "trim_reuse" in r.text


def test_resume_hands_the_scope_again_from_the_snapshot_profile(client, monkeypatch):
    """재개도 창을 다시 줘야 한다 — trim_store는 verdict_ctx처럼 직렬화되지 않는다(재개만 조용히 꺼지는 함정)."""
    seen = []
    _spy(monkeypatch, seen, status="cancelled", stage="COARSE")
    r = client.post("/api/design/auto", json={"config": _small_config(trim_reuse=True)})
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


def test_resume_of_an_off_session_stays_off(client, monkeypatch):
    """스위치는 **저장된 세션 설정**이다 — 끈 채 제출한 세션이 재개에서 조용히 켜지지 않는다."""
    seen = []
    _spy(monkeypatch, seen, status="cancelled", stage="COARSE")
    r = client.post("/api/design/auto", json={"config": _small_config()})
    rid = _wait(client, r.json()["id"])["result_id"]
    r2 = client.post(f"/api/design/{rid}/resume", json={"approved": []})
    assert r2.status_code == 202, r2.text
    rid2 = _wait(client, r2.json()["id"])["result_id"]
    assert seen == [None, None], "재개가 꺼진 세션에 창을 줬다 — 재개만 다른 해를 볼 수 있다"
    echo = client.get(f"/api/results/{rid2}").json()["trim_reuse"]
    assert echo["policy"] == "off" and echo["policy_reason"] == "config"


def test_saved_result_carries_the_reuse_echo_and_the_meta_counts(client, monkeypatch):
    """되울림 자리·칸 이름은 형제 라우트와 같다 — 웹 lib/opspace.js reuseLine이 그대로 읽는다."""
    seen = []
    _spy(monkeypatch, seen)
    r = client.post("/api/design/auto", json={"config": _small_config(trim_reuse=True)})
    rid = _wait(client, r.json()["id"])["result_id"]
    body = client.get(f"/api/results/{rid}").json()
    echo = body["trim_reuse"]
    # 켠 실행은 꺼낸 점 이름을 싣는다(리뷰 2항) — 껐다는 사유 칸은 없다
    assert set(echo) == {"trim_fingerprint", "reused", "computed", "policy", "enabled", "reused_names"}
    assert echo["trim_fingerprint"] == _example_trim_fingerprint()
    assert echo["policy"] == "converged" and echo["enabled"] is True
    assert echo["reused_names"] == []  # 스파이가 스테이지를 안 돌렸다 — 꺼낸 점이 없다
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


def test_store_off_server_says_why_it_is_off(tmp_path, monkeypatch):
    """CLAW_TRIM_STORE_LIMIT=0 — 켰어도 창이 없다. 사유가 설정이 아니라 서버라고 말해야 고칠 자리를 안다."""
    monkeypatch.setenv("CLAW_TRIM_STORE_LIMIT", "0")
    app = create_app(data_dir=tmp_path / "s")
    assert app.state.trim_store.max_entries == 0
    with TestClient(app) as c:
        seen = []
        _spy(monkeypatch, seen)
        r = c.post("/api/design/auto", json={"config": _small_config(trim_reuse=True)})
        rid = _wait(c, r.json()["id"])["result_id"]
        assert seen == [None], "저장소가 꺼졌는데 창이 왔다 — 꺼진 서버의 동작이 바뀐다"
        body = c.get(f"/api/results/{rid}").json()
        assert body["trim_reuse"]["policy"] == "off"
        assert body["trim_reuse"]["policy_reason"] == "store_disabled"
        assert body["trim_reuse"]["enabled"] is False
        assert body["report"]["trim_reuse"]["enabled"] is False
        # 지문은 꺼진 저장소에서도 싣는다 — 어느 트림 키 공간의 계산이었는지는 저장소 유무와 무관하다
        assert body["trim_reuse"]["trim_fingerprint"] == _example_trim_fingerprint()


_VOLATILE = ("elapsed_s", "elapsed", "trim_reuse")  # 벽시계·실행 이력 — 결과가 아니다(엔진 테스트 _strip과 같은 이유)


def _volatile_free(x):
    """벽시계·재사용 집계를 어느 깊이에서든 뺀 사본 — 두 서버의 **설계 결과**만 남긴다."""
    if isinstance(x, dict):
        return {k: _volatile_free(v) for k, v in x.items() if k not in _VOLATILE}
    if isinstance(x, list):
        return [_volatile_free(v) for v in x]
    return x


def test_default_design_matches_a_store_off_server(client, tmp_path, monkeypatch):
    """기본값(끔)으로 돈 설계는 **저장소가 꺼진 서버의 결과와 같다** — 그것이 기본값의 이유다(재현성).

    먼저 켠 설계 한 번으로 저장소에 이 기체의 좌표를 채운다 — 그러지 않으면 저장소가 비어 있어 「같다」가
    시험되지 않는다(빈 저장소는 켜도 냉간이다). 그 뒤 기본 설정으로 돌린 결과가 저장소를 아예 안 든 서버의
    결과와 보고 전체에서 같아야 한다.
    """
    def run(c, **over):
        r = c.post("/api/design/auto", json={"config": _small_config(**over)})
        assert r.status_code == 202, r.text
        j = _wait(c, r.json()["id"])
        assert j["status"] == "done", j
        return c.get(f"/api/results/{j['result_id']}").json()

    primed = run(client, trim_reuse=True)
    assert primed["trim_reuse"]["computed"] > 0  # 저장소가 이 기체 좌표로 채워졌다
    default = run(client)
    assert default["trim_reuse"]["policy"] == "off"
    assert default["trim_reuse"]["policy_reason"] == "config"
    assert default["trim_reuse"]["reused"] == 0, "기본값인데 저장소에서 꺼냈다 — 게이트가 새고 있다"
    assert default["trim_reuse"]["computed"] == primed["trim_reuse"]["computed"]  # 전부 스스로 풀었다

    monkeypatch.setenv("CLAW_TRIM_STORE_LIMIT", "0")
    app = create_app(data_dir=tmp_path / "off")
    with TestClient(app) as c_off:
        off = run(c_off)
    assert _volatile_free(default["report"]) == _volatile_free(off["report"])
    assert default["gain_export"] == off["gain_export"]


def test_second_design_reuses_the_first_designs_trims(client):
    """실물 두 번 — **켠** 설계의 두 번째는 트림을 저장소에서 꺼낸다(재계산 0회가 목표인 자리)."""
    def run():
        r = client.post("/api/design/auto", json={"config": _small_config(trim_reuse=True)})
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
    # 어느 점을 꺼냈나 — 수와 같은 수의 이름을, 그 실행이 실제로 본 점 이름으로(리뷰 2항)
    names = second["trim_reuse"]["reused_names"]
    assert names == sorted(names) and len(names) == second["trim_reuse"]["reused"]
    meta = next(m for m in client.get("/api/results").json() if m["id"] == rid2)
    assert meta["trim_reuse_counts"]["reused"] == second["trim_reuse"]["reused"]
