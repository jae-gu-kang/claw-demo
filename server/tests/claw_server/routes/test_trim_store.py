"""서버 트림 저장소 (05 §11.8) — 같은 기체·같은 풀이 설정의 수평비행 트림을 라우트 사이에서 다시 풀지 않는다.

- 앱마다 하나(app.state.trim_store), CLAW_TRIM_STORE_LIMIT(기본 20000, 0 = 꺼짐)
- 결과 본문 최상위 trim_reuse · meta trim_reuse_counts — 몇 점을 재사용했고 몇 점을 새로 풀었나
- 결과 본문 최상위 trim_retry · meta trim_retry_counts — 계산 실패를 몇 점 다시 풀었고 무엇으로 끝났나(이관 7단계)
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
    # 계산 실패 재시도(이관 7단계) — 다 수렴한 배치는 다시 푼 점이 없다. 점에는 retry 키도 없다(골든 불변)
    assert first["trim_retry"] == {"policy": "neighbour_v1", "retried": 0, "resolved_converged": 0,
                                   "resolved_infeasible": 0, "resolved_constraint": 0, "still_calc_failed": 0,
                                   "by_result": ZERO_RESULTS, "names": []}
    assert meta["trim_retry_counts"] == ZERO_COUNTS
    assert all("retry" not in r for r in first["results"])
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


def _wide_region_profile(client, pid="wide-region"):
    """제품 예제(구 합성 기체가 아니다)의 요구영역을 M1.0까지 넓힌 기체 — 이관 7단계 재현 조건(계약서). 100 m 행 고속 쪽이
    저속 해 스로틀에 멈춘 계산 실패였다(인접 시드가 수렴점에서만 움직인다)."""
    from claw.profile.document import load_shipped_example

    d = load_shipped_example()
    d.update(id=pid, name=pid, is_example=False, variants=[])
    d["operating_region"]["mach"] = [0.1, 1.0]
    d["operating_region"]["boundary"] = None
    d["operating_region"]["base_grid"]["n_mach"] = 10
    assert client.post("/api/profiles", json={"document": d}).status_code == 201
    return {"id": pid}


ZERO_RESULTS = {"converged": 0, "limit": 0, "alpha_bound": 0, "multi_limit": 0, "failed": 0}
ZERO_COUNTS = {"retried": 0, "resolved_converged": 0, "resolved_infeasible": 0, "resolved_constraint": 0,
               "still_calc_failed": 0}
# 넓힌 행의 멈춘 네 점 — 다시 풀면 스로틀 상한 하나에 닿고(풀이 쪽 limit), 한계 근거가 추력 부족을 재 물리적 불가다
STUCK_ECHO_COUNTS = {**ZERO_COUNTS, "retried": 4, "resolved_infeasible": 4}
WIDE = [{"mach": m, "alt": 100.0, "fuel": 25.0, "name": f"M{m}_h100_f25"} for m in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)]
STUCK = ["M0.6_h100_f25", "M0.7_h100_f25", "M0.8_h100_f25", "M0.9_h100_f25"]


def test_calc_failed_points_are_retried_and_echoed(client, wait_job):
    """계산 실패(한계에도 탐색 경계에도 붙지 않은 미수렴)를 인접 해·기본값·스로틀 훑기 시드로 다시 푼다 — 재시도 전엔
    M0.6~0.9가 저속 해 스로틀에 멈춘 계산 실패였고, 다시 풀면 스로틀 상한에 닿아 한계 근거(추력 부족)로 판정된다."""
    prof = _wide_region_profile(client)
    body, meta = _job(client, wait_job, "/api/trim/batch", {"cases": WIDE, "profile": prof})
    by = {r["case"]["name"]: r for r in body["results"]}
    for name in STUCK:
        r = by[name]
        # 스로틀 상한 하나에 닿은 첫 시도에서 멈춘다(조기 종료) — 한 번이면 된다
        assert r["retry"]["result"] == "limit" and r["retry"]["stop"] == "limit", (name, r.get("retry"))
        assert r["retry"]["attempts"] == 1
        assert r["retry"]["seeds"][0]["kind"] == "last"
        assert len(r["retry"]["outcomes"]) == r["retry"]["attempts"]
        assert abs(r["control"]["throttle"][0] - 1.0) < 1e-6  # 스로틀 상한(물리 한계)
        assert r["state"] == "infeasible" and "thrust_deficit" in r["state_reasons"], r["state_reasons"]
        assert "retry_exhausted" not in r["state_reasons"]
    # 다시 풀지 않은 점 — 수렴했거나 처음부터 한계에 붙은 점은 retry 키가 없다
    assert all("retry" not in by[w["name"]] for w in WIDE if w["name"] not in STUCK)
    assert not any(r["state"] == "calc_failed" for r in body["results"])
    # 되울림은 최종 조건 상태로 센다 — 「한계에 닿음」이 아니라 「물리적 불가」 넷
    assert body["trim_retry"] == {"policy": "neighbour_v1", **STUCK_ECHO_COUNTS,
                                  "by_result": {**ZERO_RESULTS, "limit": 4}, "names": STUCK}
    assert meta["trim_retry_counts"] == STUCK_ECHO_COUNTS
    # 저장소는 고른 해를 넣는다 — 같은 조건의 다음 실행은 미수렴 기록을 다시 풀고, 여전히 한계라 같은 기록을 싣는다
    again, _ = _job(client, wait_job, "/api/trim/batch", {"cases": WIDE, "profile": prof})
    assert again["trim_retry"]["names"] == STUCK and again["trim_retry"]["resolved_infeasible"] == 4
    assert [r["control"] for r in again["results"]] == [r["control"] for r in body["results"]]


def test_margin_map_echoes_retry(client, wait_job):
    """재시도는 트림 저장소를 쓰는 명목 기체 라우트 모두의 것이다 — 마진 맵도 같은 되울림을 싣는다."""
    prof = _wide_region_profile(client, "wide-region-mm")
    mm, mmeta = _job(client, wait_job, "/api/analysis/margin-map", {"cases": WIDE, "loops": LOOPS, "profile": prof})
    # 마진 맵은 판정을 싣지 않지만 되울림은 다시 푼 점만 조건 상태를 재 트림 탭과 같은 말을 한다
    assert mm["trim_retry"]["names"] == STUCK and mmeta["trim_retry_counts"] == STUCK_ECHO_COUNTS
    cells = {c["trim"]["case"]["name"]: c["trim"] for c in mm["cases"]}
    assert all(cells[n]["retry"]["result"] == "limit" for n in STUCK)


def test_envelope_scan_echoes_retry_from_its_verdicts(client, wait_job):
    """설계 엔벨로프 스캔은 점마다 조건 판정을 이미 잰다 — 되울림이 그 판정의 트림 상태로 센다."""
    prof = _wide_region_profile(client, "wide-region-env")
    body, meta = _job(client, wait_job, "/api/analysis/design-envelope-scan", {"cases": WIDE, "profile": prof})
    assert body["trim_retry"]["names"] == STUCK and meta["trim_retry_counts"] == STUCK_ECHO_COUNTS
    by = {c["trim"]["case"]["name"]: c for c in body["cases"]}
    assert all(by[n]["verdict"]["verdict"]["trim"]["status"] == "infeasible" for n in STUCK)
