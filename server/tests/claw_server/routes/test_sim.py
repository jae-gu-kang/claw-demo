"""시뮬 실행 라우트 검증 — 02 §8 워크플로우 5단계 (미션 → 폐루프 시뮬 → 재생+엔벨로프).

미션 스펙(JSON) → 엔진 계약(ModeSpec·LosPath·NavErrorModel·Simulator) 구성은
서버가, 검증·실행은 엔진이. 구성 오류는 제출 시점 422, 실행은 배치 작업.
"""


def _hold_mission(t_end=20.0, alt=1000.0):
    return {
        "trim": {"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0},
        "modes": [
            {"name": "hold", "speed": 199.0, "alt": alt, "heading": 0.0,
             "exit": ["time_ge", 1e9]},
        ],
        "t_end": t_end,
        "fingerprint": "fp-sim-web",
    }


def test_sim_run_end_to_end_with_mode_chain(client, wait_job):
    req = {
        "trim": {"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0},
        "modes": [
            {"name": "climb", "speed": 199.0, "alt": 1050.0, "heading": 0.0,
             "exit": ["alt_ge", 1045.0], "next": "cruise"},
            {"name": "cruise", "speed": 199.0, "alt": 1050.0, "heading": 0.0,
             "exit": ["time_ge", 1e9]},
        ],
        "t_end": 30.0,
        "fingerprint": "fp-sim-web",
    }
    r = client.post("/api/sim/run", json=req)
    assert r.status_code == 202
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done"
    assert j["progress"] == 1.0 and j["total"] == 3000  # 스텝 수 기준

    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["kind"] == "sim"
    assert body["meta"]["aborted"] is None
    assert len(body["t"]) == 3000 and body["n_total"] == 3000
    assert body["signals"]["mode"][0] == "climb"
    assert body["signals"]["mode"][-1] == "cruise"  # 모드 체인 완주 (엔진 유도 통과)
    assert abs(body["signals"]["h"][-1] - 1050.0) < 10.0
    assert body["envelope"]["worst_margin"] > 0.15
    assert body["params_fingerprint"] == "fp-sim-web"

    meta = client.get("/api/results").json()[0]
    assert meta["kind"] == "sim" and meta["aborted"] is None


def test_sim_replay_downsampled(client, wait_job):
    j = wait_job(client.post("/api/sim/run", json=_hold_mission()).json()["id"],
                 timeout=120.0)
    r = client.get(f"/api/sim/{j['result_id']}/replay", params={"stride": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["stride"] == 10 and body["n_total"] == 2000
    assert len(body["t"]) == 200 and len(body["signals"]["h"]) == 200
    assert len(body["signals"]["mode"]) == 200
    assert body["t"][1] - body["t"][0] == 0.1  # 10 × dt_plant
    assert len(body["envelope"]["stall_margin"]) == 200
    assert all(len(v) == 200 for v in body["envelope"]["flags"].values())
    assert body["envelope"]["worst_margin"] > 0.2  # 요약 스칼라는 원본 해상도 유지
    # 재생은 sim 결과에만 — 다른 종류(트림)는 409
    tj = wait_job(client.post("/api/trim/batch", json={
        "cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]}).json()["id"])
    assert client.get(f"/api/sim/{tj['result_id']}/replay").status_code == 409
    assert client.get("/api/sim/nope/replay").status_code == 404


def test_sim_cancel_preserves_partial_result(client, wait_job):
    import time

    jid = client.post("/api/sim/run", json=_hold_mission(t_end=600.0)).json()["id"]
    deadline = time.time() + 60.0
    while time.time() < deadline:  # 첫 진행 보고 후 취소 (실행 중임을 보장)
        j = client.get(f"/api/jobs/{jid}").json()
        if j["done"] > 0:
            break
        time.sleep(0.05)
    assert j["done"] > 0, "진행 보고 전 시간 초과"
    client.post(f"/api/jobs/{jid}/cancel")
    j = wait_job(jid, timeout=120.0)
    assert j["status"] == "cancelled"
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["meta"]["aborted"] == "cancelled"  # 엔진 절단 경로 통과
    assert 0 < len(body["t"]) < 60000
    assert len(body["signals"]["h"]) == len(body["t"]) == len(body["signals"]["mode"])


def test_sim_run_validation_422(client):
    base = _hold_mission()
    # 미수렴 트림 (저속 저동압)
    bad_trim = dict(base, trim={"name": "slow", "mach": 0.12, "alt": 100.0, "fuel": 400.0})
    assert client.post("/api/sim/run", json=bad_trim).status_code == 422
    # heading 문자열은 "path"만 허용
    bad_hdg = dict(base, modes=[dict(base["modes"][0], heading="pth")])
    assert client.post("/api/sim/run", json=bad_hdg).status_code == 422
    # "path" 헤딩인데 웨이포인트 없음 (엔진 Guidance 구성 오류)
    no_path = dict(base, modes=[dict(base["modes"][0], heading="path")])
    assert client.post("/api/sim/run", json=no_path).status_code == 422
    # 미정의 조건 DSL kind (엔진 validate_condition)
    bad_cond = dict(base, modes=[dict(base["modes"][0], exit=["alt_between", 1, 2])])
    assert client.post("/api/sim/run", json=bad_cond).status_code == 422
    # 제어 주기가 dt_plant 정수배 아님 (엔진 Simulator 검증)
    bad_rate = dict(base, dt_plant=0.004, control_hz=150.0)
    assert client.post("/api/sim/run", json=bad_rate).status_code == 422
    # 항법 모델 미지원 파라미터
    bad_nav = dict(base, nav={"pos_std": 1.0, "unknown_key": 3.0})
    assert client.post("/api/sim/run", json=bad_nav).status_code == 422
    # t_end 상한 (메모리 가드)
    assert client.post("/api/sim/run", json=dict(base, t_end=7200.0)).status_code == 422
