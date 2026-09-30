"""서버 트림 저장소 (05 §11.8) — 같은 기체·같은 풀이 설정의 수평비행 트림을 라우트 사이에서 다시 풀지 않는다.

- 앱마다 하나(app.state.trim_store), CLAW_TRIM_STORE_LIMIT(기본 20000, 0 = 꺼짐)
- 결과 본문 최상위 trim_reuse · meta trim_reuse_counts — 몇 점을 재사용했고 몇 점을 새로 풀었나
- /grid/base 점에 저장소 기록이 있으면 stored {state, converged} — 미수렴 기록은 state None(판정을 다시 재지 않는다)
"""

import pytest
from fastapi.testclient import TestClient

from claw_server import create_app

CASES = [{"mach": m, "alt": 1000.0, "fuel": 200.0} for m in (0.40, 0.45, 0.50)]
LOOPS = [{"name": "pitch_q", "axis": "lon", "x_out": "q", "u_in": "de", "kp": 0.5, "ki": 0.0}]


def _job(client, wait_job, url, body):
    r = client.post(url, json=body)
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done", j
    res = client.get(f"/api/results/{j['result_id']}").json()
    meta = next(m for m in client.get("/api/results").json() if m["id"] == j["result_id"])
    return res, meta


def test_trim_batch_then_margin_map_reuses_every_point(client, wait_job):
    first, meta = _job(client, wait_job, "/api/trim/batch", {"cases": CASES})
    tr = first["trim_reuse"]
    assert tr["reused"] == 0 and tr["computed"] == 3 and tr["policy"] == "converged"
    assert tr["reused_names"] == [] and tr["resolved_failed"] == 0 and tr["trim_fingerprint"]
    assert meta["trim_reuse_counts"] == {"reused": 0, "computed": 3, "resolved_failed": 0}
    mm, mmeta = _job(client, wait_job, "/api/analysis/margin-map", {"cases": CASES, "loops": LOOPS})
    assert mm["trim_reuse"]["reused"] == 3 and mm["trim_reuse"]["computed"] == 0
    assert mm["trim_reuse"]["reused_names"] == [c["case"]["name"] for c in first["results"]]
    assert mmeta["trim_reuse_counts"]["reused"] == 3
    # 재사용한 해 = 첫 배치의 해(비트 동일)
    for a, b in zip(first["results"], mm["cases"]):
        assert a["control"] == b["trim"]["control"] and a["euler"] == b["trim"]["euler"]


def test_reuse_none_solves_again(client, wait_job):
    _job(client, wait_job, "/api/trim/batch", {"cases": CASES})
    again, _ = _job(client, wait_job, "/api/trim/batch", {"cases": CASES, "reuse": "none"})
    assert again["trim_reuse"]["reused"] == 0 and again["trim_reuse"]["policy"] == "none"
    assert client.post("/api/trim/batch", json={"cases": CASES, "reuse": "always"}).status_code == 422


def test_env_zero_disables_the_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAW_TRIM_STORE_LIMIT", "0")
    app = create_app(data_dir=tmp_path / "s")
    assert app.state.trim_store.max_entries == 0
    monkeypatch.setenv("CLAW_TRIM_STORE_LIMIT", "7")
    assert create_app(data_dir=tmp_path / "t").state.trim_store.max_entries == 7
    monkeypatch.delenv("CLAW_TRIM_STORE_LIMIT")
    assert create_app(data_dir=tmp_path / "u").state.trim_store.max_entries == 20000
    assert create_app(data_dir=tmp_path / "v", trim_store_limit=0).state.trim_store.max_entries == 0


def test_disabled_store_echoes_off(tmp_path):
    import time

    with TestClient(create_app(data_dir=tmp_path / "s", trim_store_limit=0)) as c:
        for _ in range(2):
            jid = c.post("/api/trim/batch", json={"cases": CASES}).json()["id"]
            deadline = time.time() + 60
            while c.get(f"/api/jobs/{jid}").json()["status"] not in ("done", "error") and time.time() < deadline:
                time.sleep(0.02)
            body = c.get(f"/api/results/{jid}").json()
            assert body["trim_reuse"]["policy"] == "off" and body["trim_reuse"]["reused"] == 0
        assert len(c.app.state.trim_store) == 0


def test_store_is_per_app(tmp_path):
    a, b = create_app(data_dir=tmp_path / "a"), create_app(data_dir=tmp_path / "b")
    assert a.state.trim_store is not b.state.trim_store


def test_grid_base_marks_stored_points(client, wait_job):
    body = client.post("/api/grid/base", json={"n_mach": 3, "alts": [1000.0], "fuels": [200.0]}).json()
    pts = [p for p in body["points"] if p["state"] == "not_run"]
    assert pts and all("stored" not in p for p in body["points"])
    _job(client, wait_job, "/api/trim/batch",
         {"cases": [{"mach": p["mach"], "alt": p["alt"], "fuel": p["fuel"], "name": p["name"]} for p in pts[:2]]})
    body = client.post("/api/grid/base", json={"n_mach": 3, "alts": [1000.0], "fuels": [200.0]}).json()
    by = {p["name"]: p for p in body["points"]}
    for p in pts[:2]:
        assert by[p["name"]]["stored"] == {"state": "computable", "converged": True}
        assert by[p["name"]]["state"] == "not_run"  # 트림 전 상태는 그대로 — 보낼 점 판정이 바뀌지 않는다
    assert all("stored" not in by[p["name"]] for p in pts[2:])


def _put_failed(client, fp, mach, alt, fuel, name="x"):
    """저장소에 미수렴 기록을 직접 넣는다 — 스로틀 상한에 붙은 해라 판정을 재면 한계 근거 풀이(SLSQP)가 돈다."""
    from claw.common.contracts import TrimCase
    from claw.trim.store import TrimRecord

    scope = client.app.state.trim_store.scope(fp)
    assert scope.put(TrimCase(name, mach=mach, alt=alt, fuel=fuel),
                     TrimRecord(z=(0.05, 0.0, 1.0), success=False, cost=1.0, converged=False))


def test_grid_base_marks_failed_record_without_assessing(client, wait_job, monkeypatch):
    first, _ = _job(client, wait_job, "/api/trim/batch", {"cases": CASES[:1]})
    fp = first["trim_reuse"]["trim_fingerprint"]
    body = client.post("/api/grid/base", json={"n_mach": 3, "alts": [1000.0], "fuels": [200.0]}).json()
    p0 = next(p for p in body["points"] if p["state"] == "not_run")
    _put_failed(client, fp, p0["mach"], p0["alt"], p0["fuel"])
    import claw.opspace.states as states

    def boom(*a, **k):
        raise AssertionError("/grid/base가 미수렴 기록의 근거 풀이를 돌렸다")

    monkeypatch.setattr(states, "_limit_evidence", boom)
    monkeypatch.setattr(states, "trim_assessment", boom)
    body = client.post("/api/grid/base", json={"n_mach": 3, "alts": [1000.0], "fuels": [200.0]}).json()
    got = next(p for p in body["points"] if p["name"] == p0["name"])
    # 판정하지 않은 기록에 물리 판정어를 달지 않는다 — 다음 실행이 다시 푼다
    assert got["stored"] == {"state": None, "converged": False}
    assert got["state"] == "not_run"


def test_stored_failure_is_resolved_and_counted(client, wait_job):
    first, _ = _job(client, wait_job, "/api/trim/batch", {"cases": CASES[:1]})
    fp = first["trim_reuse"]["trim_fingerprint"]
    new = {"mach": 0.55, "alt": 1000.0, "fuel": 200.0, "name": "late"}
    _put_failed(client, fp, new["mach"], new["alt"], new["fuel"])
    res, meta = _job(client, wait_job, "/api/trim/batch", {"cases": [CASES[0], new]})
    tr = res["trim_reuse"]
    assert tr["reused"] == 1 and tr["computed"] == 1 and tr["resolved_failed"] == 1
    assert tr["reused_names"] == [res["results"][0]["case"]["name"]]
    assert meta["trim_reuse_counts"] == {"reused": 1, "computed": 1, "resolved_failed": 1}
    # 다시 푼 해가 수렴하면 미수렴 기록을 대체한다 — 셋째 배치는 둘 다 재사용
    assert res["results"][1]["converged"] is True
    again, _ = _job(client, wait_job, "/api/trim/batch", {"cases": [CASES[0], new]})
    assert again["trim_reuse"]["reused"] == 2 and again["trim_reuse"]["resolved_failed"] == 0


def test_bode_and_sweep_never_touch_the_store(client, wait_job):
    r = client.post("/api/analysis/bode", json={"case": CASES[0], "loop": LOOPS[0]})
    assert r.status_code == 200, r.text
    assert len(client.app.state.trim_store) == 0
    # 스윕은 명목 기체라도 저장소 밖에서 푼다(v1 배선 대상 아님) — 돌린 뒤에도 비어 있다
    r = client.post("/api/influence/sweep", json={
        "cases": [{"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0}],
        "knobs": ["table.pitch.kp"], "span": [0.1], "t_settle": 2.0, "t_step": 4.0})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done", j
    assert len(client.app.state.trim_store) == 0
