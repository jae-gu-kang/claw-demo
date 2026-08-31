"""시뮬 실행 라우트 검증 — 02 §8 워크플로우 5단계 (미션 → 폐루프 시뮬 → 재생+엔벨로프).

미션 스펙(JSON) → 엔진 계약(ModeSpec·LosPath·NavErrorModel·Simulator) 구성은
서버가, 검증·실행은 엔진이. 구성 오류는 제출 시점 422, 실행은 배치 작업.
"""

import pytest

from claw.nav import NavErrorModel


def _hold_mission(t_end=20.0, alt=1000.0, **over):
    base = {
        "trim": {"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0},
        "modes": [
            {"name": "hold", "speed": 199.0, "alt": alt, "heading": 0.0,
             "exit": ["time_ge", 1e9]},
        ],
        "t_end": t_end,
        "fingerprint": "fp-sim-web",
    }
    base.update(over)
    return base


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


def test_sim_meta에_웨이포인트가_동봉된다(client, wait_job):
    """경로오차 지표(xtrack_rms)·진단은 저장된 결과만으로 계산돼야 한다 —
    웨이포인트가 결과 meta에 함께 다니지 않으면 소비자가 미션 스펙을 따로
    들고 와 맞춰야 하고, 어긋나면 조용히 틀린 경로오차가 나온다."""
    wps = [[0.0, 0.0], [5000.0, 0.0]]
    j = wait_job(
        client.post("/api/sim/run", json=_hold_mission(t_end=2.0, waypoints=wps))
        .json()["id"],
        timeout=120.0,
    )
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["meta"]["waypoints"] == wps
    # 웨이포인트 없는 미션은 None — "빈 경로"가 아니라 "경로 없음"
    j2 = wait_job(
        client.post("/api/sim/run", json=_hold_mission(t_end=2.0)).json()["id"],
        timeout=120.0,
    )
    assert client.get(f"/api/results/{j2['result_id']}").json()["meta"]["waypoints"] is None


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


def test_sim_duty_report(client, wait_job):
    """타면 사용 통계 — 저장된 전 해상도에서 집계, 응답은 요약(표본 수 무관 유계)."""
    j = wait_job(client.post("/api/sim/run", json=_hold_mission(
        alt=1030.0, actuators={"rate_max": 6.0})).json()["id"], timeout=120.0)
    r = client.get(f"/api/sim/{j['result_id']}/duty", params={"bins": 16})
    assert r.status_code == 200
    body = r.json()
    assert body["result_id"] == j["result_id"]
    assert [c["key"] for c in body["channels"]] == ["elevon_l", "elevon_r", "rudder"]
    assert body["n"] == 2000 and body["t_total"] == 20.0
    assert body["actuators"] is True and body["rate_is_command_slew"] is False

    ch = body["channels"][0]
    assert len(ch["hist"]["edges"]) == 17 and len(ch["hist"]["time"]) == 16
    assert sum(ch["hist"]["time"]) == 20.0
    # 판정 기준선이 결과 meta를 타고 넘어와야 포화가 판정된다
    assert ch["rate_max"] == 6.0 and ch["pos_hi"] == 0.35
    assert ch["pos_sat"] is not None and ch["rate_sat"] is not None
    assert ch["exceedance"]["time"][0] == 20.0  # level 0 = 전체 시간
    assert len(ch["density"]["time"]) == 16  # bins × rate_bins 격자


def test_sim_duty_stride_free_and_bounds(client, wait_job):
    """duty는 stride를 받지 않는다 — 다운샘플본은 최대 타율·짧은 포화를 지운다.

    (알 수 없는 쿼리는 FastAPI가 무시하므로 stride를 붙여도 전 해상도 결과가
    나오는지로 확인한다.)
    """
    j = wait_job(client.post("/api/sim/run", json=_hold_mission()).json()["id"],
                 timeout=120.0)
    rid = j["result_id"]
    a = client.get(f"/api/sim/{rid}/duty").json()
    b = client.get(f"/api/sim/{rid}/duty", params={"stride": 50}).json()
    assert a["n"] == b["n"] == 2000
    assert a["channels"][0]["stats"]["max_rate_abs"] == b["channels"][0]["stats"]["max_rate_abs"]
    # 작동기 미장착 = 명령 직결 — 타율은 요구 slew이고 rate 포화는 판정 불가
    assert a["rate_is_command_slew"] is True
    assert a["channels"][0]["rate_sat"] is None
    assert any("작동기 미장착" in w for w in a["warnings"])

    assert client.get(f"/api/sim/{rid}/duty", params={"bins": 3}).status_code == 422
    assert client.get(f"/api/sim/{rid}/duty", params={"bins": 999}).status_code == 422
    tj = wait_job(client.post("/api/trim/batch", json={
        "cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]}).json()["id"])
    assert client.get(f"/api/sim/{tj['result_id']}/duty").status_code == 409
    assert client.get("/api/sim/nope/duty").status_code == 404


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
    bad_nav = dict(base, nav={"pos_std_h": 1.0, "unknown_key": 3.0})
    assert client.post("/api/sim/run", json=bad_nav).status_code == 422
    # t_end 상한 (메모리 가드)
    assert client.post("/api/sim/run", json=dict(base, t_end=7200.0)).status_code == 422


def test_sim_actuator_params_validation_422(client):
    """작동기 파라미터 오류는 제출 시점 422 — job error로 지연 금지 (리뷰 M1)."""
    base = _hold_mission()
    for act in ({"unknown_key": 3.0}, {"wn": -5.0}, {"pos_lo": -1.0}):
        r = client.post("/api/sim/run", json=dict(base, actuators=act))
        assert r.status_code == 422, act


def test_sim_exit_condition_nonfinite_422(client):
    """exit 조건 인자의 NaN은 경계 차단 — 영원히 참이 안 되는 무증상 모드 방지 (리뷰 S2)."""
    import json as _json

    mission = _hold_mission()
    mission["modes"][0]["exit"] = ["time_ge", float("nan")]
    raw = _json.dumps(mission)  # NaN 리터럴 포함 (httpx json=은 자체 거부)
    r = client.post(
        "/api/sim/run", content=raw, headers={"content-type": "application/json"}
    )
    assert r.status_code == 422
    bad_type = _hold_mission()
    bad_type["modes"][0]["exit"] = ["time_ge", [1.0]]
    assert client.post("/api/sim/run", json=bad_type).status_code == 422


def test_sim_empty_waypoints_rejected_422(client):
    assert client.post(
        "/api/sim/run", json=_hold_mission(waypoints=[])
    ).status_code == 422


def test_sim_nav_empty_dict_attaches_default_model(client, wait_job):
    """nav={} = 기본 파라미터의 오차 모델 장착 (조용한 미장착 금지 — 리뷰 Nit)."""
    r = client.post("/api/sim/run", json=_hold_mission(t_end=2.0, nav={}))
    assert r.status_code == 202
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done"
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["meta"]["nav"] == "NavErrorModel"


def test_sim_autopilot_injection_registry_validated(client, wait_job):
    """AP 주입 검증은 레지스트리 ParamDef 경유 (02 §5.5) — 타입·범위·키를
    제출 시점 422로 판정. 부분 kwargs는 ParamDef 기본값 보충(생성자와 동일
    의미 — 엔진 defaults-match 테스트가 드리프트 가드)."""
    ok = _hold_mission(t_end=2.0, autopilot={"phi_max": 0.5, "kp_spd": 0.2})
    r = client.post("/api/sim/run", json=ok)
    assert r.status_code == 202
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done"
    # 미정의 파라미터 이름 — ParamError 메시지로 판정 주체를 핀
    r = client.post("/api/sim/run", json=_hold_mission(autopilot={"kp_spdX": 0.2}))
    assert r.status_code == 422 and "정의되지 않은 파라미터" in r.text
    # 오타입(문자열·bool) — pydantic 통과 후 ParamDef가 제출 시점 판정
    # (실행 스레드 TypeError로 지연 금지)
    r = client.post("/api/sim/run", json=_hold_mission(autopilot={"kp_spd": "abc"}))
    assert r.status_code == 422 and "수치 필요" in r.text
    r = client.post("/api/sim/run", json=_hold_mission(autopilot={"kp_spd": True}))
    assert r.status_code == 422 and "수치 필요" in r.text
    # 범위 위반 — ParamDef hi
    assert client.post(
        "/api/sim/run", json=_hold_mission(autopilot={"phi_max": 2.0})
    ).status_code == 422


def test_sim_scas_injection_all_axes_registry_validated(client, wait_job):
    """SCAS 주입은 **세 축 전부**가 계약 — 부분 주입은 제출 시점 422.

    한 축만 보내면 나머지가 조용히 데모 설계값으로 남아 "보낸 형상"과 다른 것이
    돈다. 축 안의 kwargs 판정은 AP와 같은 레지스트리 ParamDef 경유다.
    주의: 축 kwargs도 **전체**를 보내야 한다 — ScasAxis의 ParamDef 기본값은
    0이라 일부만 보내면 나머지 게인이 설계값이 아니라 0으로 채워진다.
    """
    axes = {
        "pitch": {"kp": -2.0, "ki": -0.5, "k_rate": 0.4, "out_lo": -0.35, "out_hi": 0.35},
        "roll": {"kp": 1.0, "ki": 0.1, "k_rate": -0.2, "out_lo": -0.35, "out_hi": 0.35},
        "yaw": {"kp": 0.7, "ki": 0.0, "k_rate": 0.8, "washout_tau": 3.0,
                "out_lo": -0.35, "out_hi": 0.35},
    }
    r = client.post("/api/sim/run", json=_hold_mission(t_end=2.0, scas=axes))
    assert r.status_code == 202
    assert wait_job(r.json()["id"], timeout=120.0)["status"] == "done"

    # 부분 주입 (요축 누락) — 조용한 설계값 잔류 금지
    partial = {k: v for k, v in axes.items() if k != "yaw"}
    r = client.post("/api/sim/run", json=_hold_mission(scas=partial))
    assert r.status_code == 422 and "세 축 전부 필요" in r.text
    # 미정의 축 이름
    r = client.post("/api/sim/run", json=_hold_mission(scas={**axes, "zzz": {}}))
    assert r.status_code == 422 and "미정의 SCAS 축" in r.text
    # 축 안의 미정의 키·오타입 — ParamDef가 판정 (AP와 같은 주체)
    bad = {**axes, "pitch": {**axes["pitch"], "kpX": 1.0}}
    r = client.post("/api/sim/run", json=_hold_mission(scas=bad))
    assert r.status_code == 422 and "정의되지 않은 파라미터" in r.text
    bad = {**axes, "pitch": {**axes["pitch"], "kp": "abc"}}
    r = client.post("/api/sim/run", json=_hold_mission(scas=bad))
    assert r.status_code == 422 and "수치 필요" in r.text
    # 축 자리에 dict가 아닌 값
    r = client.post("/api/sim/run", json=_hold_mission(scas={**axes, "yaw": 3.0}))
    assert r.status_code == 422


def test_sim_scas_nonfinite_422(client):
    """축 dict 한 겹 아래의 NaN/Inf도 경계 차단 — AP와 같은 정책 (02 v0.11)."""
    import json as _json

    axes = {
        "pitch": {"kp": -2.0}, "roll": {"kp": 1.0}, "yaw": {"kp": float("nan")},
    }
    raw = _json.dumps(_hold_mission(scas=axes))
    r = client.post(
        "/api/sim/run", content=raw, headers={"content-type": "application/json"}
    )
    assert r.status_code == 422


def test_sim_autopilot_nonfinite_422(client):
    """AP dict의 Infinity/NaN 리터럴은 경계 차단 유지 — ParamDef 범위 비교는
    NaN을 통과시키므로 유한성만은 서버 몫 (02 v0.11 직렬화 정책 보호)."""
    import json as _json

    for bad in (float("inf"), float("nan")):
        mission = _hold_mission(autopilot={"kp_spd": bad})
        raw = _json.dumps(mission)  # 비유한 리터럴 포함 (httpx json=은 자체 거부)
        r = client.post(
            "/api/sim/run", content=raw, headers={"content-type": "application/json"}
        )
        assert r.status_code == 422, bad


def test_sim_waypoint_altitude_flies_the_vertical_profile(client, wait_job):
    """웨이포인트 고도 + alt="path" → 기체가 그 세로 프로파일을 실제로 난다.

    고도를 받아 두고 유도가 안 쓰면 화면의 프로파일이 계획서일 뿐이다 —
    사용자 요청(01 §3.3)의 요점이 "실제로 추종"이므로 그것을 핀한다.
    """
    req = _hold_mission(
        t_end=90.0,
        waypoints=[[6000.0, 0.0, 1600.0]],
        accept_radius=300.0,
        modes=[{"name": "wpnav", "speed": 199.0, "alt": "path", "heading": "path",
                "exit": ["time_ge", 1e9]}],
    )
    j = wait_job(client.post("/api/sim/run", json=req).json()["id"], timeout=300.0)
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert body["meta"]["waypoints"] == [[6000.0, 0.0, 1600.0]]
    h = body["signals"]["h"]
    # 1000 m에서 시작해 1600 m를 향해 올라간다 (구간 선형 명령 + 고도 루프 추종)
    assert h[0] == pytest.approx(1000.0, abs=30.0)
    assert max(h) > 1300.0, f"고도 명령이 먹지 않았다 — 최고 {max(h):.0f} m"


def test_sim_waypoint_altitude_contract_rejections(client):
    """고도 섞인 목록·alt="path" 오용은 제출 시점 422 (조용한 무시 금지)."""
    mixed = _hold_mission(waypoints=[[1000.0, 0.0, 800.0], [2000.0, 0.0]])
    assert client.post("/api/sim/run", json=mixed).status_code == 422
    # 경로가 없는데 alt="path"
    no_path = _hold_mission(
        modes=[{"name": "m", "speed": 199.0, "alt": "path", "exit": ["time_ge", 1e9]}])
    assert client.post("/api/sim/run", json=no_path).status_code == 422
    # 경로는 있는데 고도가 없다 — 고도 축이 조용히 꺼진 채 날면 안 된다
    no_alt = _hold_mission(
        waypoints=[[1000.0, 0.0]],
        modes=[{"name": "m", "speed": 199.0, "alt": "path", "exit": ["time_ge", 1e9]}])
    assert client.post("/api/sim/run", json=no_alt).status_code == 422
    # 문자열은 "path"만 — 오타가 축 off로 조용히 흘러가지 않는다
    typo = _hold_mission(
        modes=[{"name": "m", "speed": 199.0, "alt": "pat", "exit": ["time_ge", 1e9]}])
    assert client.post("/api/sim/run", json=typo).status_code == 422


# ---- 이륙·착륙 (01 §3.3.1) ----


def _landing_mission(**over):
    """발사대 이륙 → 스키드 착륙 전장 — 활주로가 있어야 스키드가 달린다."""
    import math

    base = {
        "trim": {"mach": 0.0, "alt": 0.0, "fuel": 300.0, "condition": "ground"},
        "runway": {"elevation": 0.0, "heading": 0.0, "length": 1500.0},
        "launch": {"length": 10.0, "elev_angle": math.radians(15.0), "exit_speed": 81.5},
        "nav": {"seed": 11},
        "nav_grade": "rtk",
        "modes": [
            {"name": "launch", "speed": 110.0, "pitch": math.radians(21.0),
             "heading": 0.0, "exit": ["off_rail"], "next": "climb"},
            {"name": "climb", "speed": 110.0, "pitch": math.radians(21.0),
             "heading": 0.0, "exit": ["alt_ge", 250.0], "next": "cruise"},
            {"name": "cruise", "speed": 88.0, "alt": 300.0, "heading": 0.0,
             "exit": ["time_ge", 20.0], "next": "approach"},
            {"name": "approach", "speed": 88.0, "hdot": -4.8, "heading": 0.0,
             "exit": ["alt_le", 20.0], "next": "flare"},
            {"name": "flare", "speed": 80.0, "hdot": -0.8, "heading": 0.0,
             "exit": ["on_ground"], "next": "rollout"},
            {"name": "rollout", "speed": 0.0, "pitch": 0.0, "heading": 0.0,
             "exit": ["speed_le", 0.5], "next": "stopped"},
            {"name": "stopped", "speed": 0.0, "pitch": 0.0, "exit": ["time_ge", 1e9]},
        ],
        "t_end": 200.0, "dt_plant": 0.01, "control_hz": 100.0,
        "actuators": {"wn": 30.0, "zeta": 0.7, "rate_max": 10.0},
        "fuel_flow": 0.3,
        "fingerprint": "fp-landing-web",
    }
    base.update(over)
    return base


def test_landing_mission_runs_over_http(client, wait_job):
    """발사→…→정지가 HTTP 경로로 완주하고 단계 시각·기준선이 응답에 실린다.

    **물리 회귀는 엔진 test_landing이 맡는다** — 여기서 보는 것은 전송 계층이다:
    스키마가 받는가, 체인이 도는가, 화면이 그릴 것이 결과와 함께 오는가.
    200초 미션이라 한 번만 돌리고 세 가지를 함께 단정한다.
    """
    r = client.post("/api/sim/run", json=_landing_mission())
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=600.0)
    assert j["status"] == "done", j
    body = client.get(f"/api/results/{j['result_id']}").json()

    seq = []
    for m in body["signals"]["mode"]:
        if not seq or seq[-1] != m:
            seq.append(m)
    assert seq == ["launch", "climb", "cruise", "approach", "flare", "rollout", "stopped"]
    assert body["meta"]["aborted"] is None
    assert not any(any(v) for v in body["envelope"]["flags"].values())

    # 단계 시각 — 없으면 화면이 "언제 접지했나"를 말할 수 없다
    ph = body["meta"]["phases"]
    assert ph["launch_exit_t"] == pytest.approx(0.245, abs=0.001)
    assert ph["touchdown_t"] == pytest.approx(110.1, abs=2.0)
    assert ph["stop_t"] == pytest.approx(132.8, abs=3.0)

    # 기준선은 결과와 함께 다닌다 — 엔진이 소비하지 않는 heading·length도 실려야
    # 재생 화면이 활주로 띠를 그린다 (웨이포인트 동봉과 같은 규약)
    assert body["meta"]["runway"] == {"elevation": 0.0, "heading": 0.0, "length": 1500.0}
    assert body["meta"]["launch"]["length"] == 10.0
    assert body["meta"]["launch"]["exit_speed"] == pytest.approx(81.5)
    assert body["meta"]["launch"]["accel"] is None, "둘 중 준 쪽만 실린다"
    assert body["meta"]["launch"]["origin_height"] == pytest.approx(1.2)


def test_longitudinal_axes_are_exclusive_at_submit(client):
    """alt·pitch·hdot을 함께 켜면 제출 시점 422 — 엔진 판정이 그대로 올라온다."""
    bad = _landing_mission(modes=[
        {"name": "x", "alt": 100.0, "hdot": -2.0, "exit": ["time_ge", 1e9]},
    ])
    r = client.post("/api/sim/run", json=bad)
    assert r.status_code == 422
    assert "종방향" in r.json()["detail"]


def test_ground_conditions_need_a_runway(client):
    """활주로가 없으면 스키드도 없어서 on_ground를 판정할 수 없다 — 제출 시점 거부."""
    body = _landing_mission()
    del body["runway"]
    r = client.post("/api/sim/run", json=body)
    assert r.status_code == 422
    assert "착륙장치" in r.json()["detail"]


def test_off_rail_needs_a_launch_rail(client):
    body = _landing_mission()
    del body["launch"]
    r = client.post("/api/sim/run", json=body)
    assert r.status_code == 422
    assert "발사 레일" in r.json()["detail"]


def test_ground_trim_requires_zero_mach(client):
    """지상 평형에서 mach는 쓰이지 않는다 — 조용히 무시하지 않고 거부한다."""
    r = client.post("/api/sim/run", json=_landing_mission(
        trim={"mach": 0.6, "alt": 0.0, "fuel": 300.0, "condition": "ground"}))
    assert r.status_code == 422
    r = client.post("/api/sim/run", json=_landing_mission(
        trim={"mach": 0.0, "alt": 0.0, "fuel": 300.0}))  # condition 기본 level
    assert r.status_code == 422


def test_rail_needs_exactly_one_of_speed_or_accel(client):
    """둘 다 주면 어느 쪽이 이겼는지 화면이 말할 수 없다 — 엔진 판정이 정본."""
    for launch in ({"length": 10.0, "elev_angle": 0.26, "exit_speed": 81.5, "accel": 300.0},
                   {"length": 10.0, "elev_angle": 0.26}):
        r = client.post("/api/sim/run", json=_landing_mission(launch=launch))
        assert r.status_code == 422
        assert "정확히 하나" in r.json()["detail"]


def test_nav_grade_picks_rtk_without_the_web_restating_numbers():
    """등급은 **이름으로** 고른다 — 웹이 RTK 수치를 재기술하면 §5.5 위반이다.

    요청은 seed만 담고, 값은 엔진 RTK_FIXED에서 온다. nav의 덮어쓰기가 등급 위에
    얹히는 것도 함께 고정한다(등급이 바탕, nav가 위).
    """
    from claw.nav import RTK_FIXED
    from claw_server.routes.sim import SimRunIn, _build

    req = _landing_mission(nav_grade="rtk", nav={"seed": 5})
    assert set(req["nav"]) & set(RTK_FIXED) == set(), "요청에 RTK 수치가 없어야 한다"
    sim, _tr = _build(SimRunIn(**req))
    assert sim.nav_model.pos_std_v == RTK_FIXED["pos_std_v"]
    assert sim.nav_model.bias_std_v == RTK_FIXED["bias_std_v"]
    assert sim.nav_model.seed == 5
    # 자세 오차는 등급이 손대지 않는다 — RTK는 측위를 개선하지 자세가 아니다
    assert sim.nav_model.att_std == NavErrorModel().att_std

    # 대조군 — _landing_mission의 기본이 rtk라 등급을 명시적으로 되돌려야 한다
    plain, _ = _build(SimRunIn(**_landing_mission(nav_grade="default", nav={"seed": 5})))
    assert plain.nav_model.pos_std_v == NavErrorModel().pos_std_v
    # 등급 위에 nav가 덮인다
    over, _ = _build(SimRunIn(**_landing_mission(
        nav_grade="rtk", nav={"seed": 5, "pos_std_v": 0.5})))
    assert over.nav_model.pos_std_v == 0.5
