"""시뮬 실행 라우트 검증 — 02 §8 워크플로우 7단계 (미션 → 폐루프 시뮬 → 재생+엔벨로프).

미션 스펙(JSON) → 엔진 계약(ModeSpec·LosPath·NavErrorModel·Simulator) 구성은
서버가, 검증·실행은 엔진이. 구성 오류는 제출 시점 422, 실행은 배치 작업.
"""

import pytest

from claw.nav import NavErrorModel
from claw.profile import example_profile


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
    # 빈 시간의 합은 t_total과 같아야 한다 — 다만 **완전 일치로 묻지 않는다**:
    # 빈마다 count × dt(0.01)를 더하므로 16개를 합치면 마지막 자리에 반올림이 남고
    # (여기서는 20.000000000000004), 그 4e-15는 집계가 틀린 것이 아니라 이진
    # 부동소수의 사정이다. 완전 일치를 걸어 두면 빈 수·플랫폼이 바뀔 때마다
    # 없는 결함을 신고한다 — 판정선은 "빠뜨린 시간이 없나"이지 비트 일치가 아니다
    assert sum(ch["hist"]["time"]) == pytest.approx(20.0)
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


# ── 재생·타면 사용은 본문을 통째로 세우지 않는다 (Render 512 MB — store.py 머리말) ──


def _replay_by_slicing(full, stride):
    """재생 솎음의 기준 — 통째 읽은 본문을 자르던 원래 알고리즘 그대로(v1.46까지의 sim_replay)."""
    sl = slice(None, None, stride)
    out = dict(full)
    out["t"] = full["t"][sl]
    out["signals"] = {k: v[sl] for k, v in full["signals"].items()}
    envelope = dict(full["envelope"])
    if "stall_margin" in envelope:
        envelope["stall_margin"] = envelope["stall_margin"][sl]
    if "flags" in envelope:
        envelope["flags"] = {k: v[sl] for k, v in envelope["flags"].items()}
    out["envelope"] = envelope
    out["stride"] = stride
    return out


def test_sim_replay_is_the_full_body_sliced_byte_for_byte(client, wait_job):
    """읽으면서 솎아도 응답은 통째 읽고 자르던 때와 **키 순서까지** 같다 — 재생 화면·착륙 요약·
    가상환경이 같은 본문을 받는다. stride가 표본 수를 나누지 않거나 넘어도 같다."""
    import json

    j = wait_job(client.post("/api/sim/run", json=_hold_mission(
        actuators={"rate_max": 6.0})).json()["id"], timeout=120.0)
    rid = j["result_id"]
    full = client.get(f"/api/results/{rid}").json()
    for stride in (2, 7, 10, 1999, 5000):
        got = client.get(f"/api/sim/{rid}/replay", params={"stride": stride}).json()
        want = _replay_by_slicing(full, stride)
        assert json.dumps(got, ensure_ascii=False) == json.dumps(want, ensure_ascii=False), stride
    # stride 1은 저장 본문 그대로다
    assert client.get(f"/api/sim/{rid}/replay").json() == full


def test_sim_replay_does_not_build_the_full_resolution_body(client, wait_job):
    """재생(stride>1)의 메모리 정점이 전 해상도 파싱본보다 작아야 한다 — 예전에는 본문 글 한 벌과
    파싱본을 통째로 세운 뒤 잘랐다(S1 기본 미션 68.6 MB 본문에서 +218~263 MB). 기준은 전 해상도
    파싱본(store.load)이다 — 통째 조회(/results/{id})는 이제 파일을 파싱 없이 흘려보내므로 그 정점은
    TestClient의 응답 버퍼링만 잰다(기준으로 쓰면 비교가 뜻을 잃는다)."""
    import tracemalloc

    j = wait_job(client.post("/api/sim/run", json=_hold_mission()).json()["id"], timeout=120.0)
    rid = j["result_id"]

    def peak_of(call):
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            base = tracemalloc.get_traced_memory()[0]
            call()
            return tracemalloc.get_traced_memory()[1] - base
        finally:
            tracemalloc.stop()

    parsed = peak_of(lambda: client.app.state.store.load(rid))
    lean = peak_of(lambda: client.get(f"/api/sim/{rid}/replay", params={"stride": 10}).raise_for_status())
    assert lean < 0.35 * parsed, (lean, parsed)
    # stride 1은 여기서 재지 않는다 — TestClient가 응답 본문을 통째로 두 벌 버퍼링해(파일 크기 ×2)
    # 서버 쪽 정점이 가려진다. 파싱 없이 흘려보낸다는 사실은 아래 바이트 대조가 고정한다.


def test_sim_replay_stride_one_streams_the_stored_json(client, wait_job):
    """stride 1은 저장 본문 파일 그대로다 — 값은 /results와 같고, 종류 판정(409)·없음(404)도 그대로다."""
    j = wait_job(client.post("/api/sim/run", json=_hold_mission(t_end=2.0)).json()["id"],
                 timeout=120.0)
    rid = j["result_id"]
    r = client.get(f"/api/sim/{rid}/replay")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.content == (client.app.state.store.root / f"{rid}.json").read_bytes()
    assert int(r.headers["content-length"]) == len(r.content)
    assert r.json() == client.get(f"/api/results/{rid}").json()
    tj = wait_job(client.post("/api/trim/batch", json={
        "cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]}).json()["id"])
    assert client.get(f"/api/sim/{tj['result_id']}/replay").status_code == 409
    assert client.get("/api/sim/nope/replay").status_code == 404


def test_sim_duty_parses_only_the_signals_the_engine_reads(client, wait_job, monkeypatch):
    """타면 사용은 DUTY_SIGNALS만 파싱한다 — 그 목록이 엔진 duty_report가 실제로 읽는 신호를 다
    덮는지 감시 dict로 확인하고, 골라 읽은 응답이 통째 본문으로 계산한 것과 같은지 본다.
    엔진이 새 신호를 읽기 시작하면(또는 신호를 통째로 훑으면) 여기서 빨개진다."""
    import json

    from claw.analysis.duty import duty_report
    from claw_server.routes import sim as sim_route
    from claw_server.routes.sim import DUTY_SIGNALS
    from claw_server.serialize import to_jsonable

    j = wait_job(client.post("/api/sim/run", json=_hold_mission(
        alt=1030.0, actuators={"rate_max": 6.0})).json()["id"], timeout=120.0)
    rid = j["result_id"]
    full = client.app.state.store.load(rid)
    seen = set()

    class Watch(dict):
        def __getitem__(self, k):
            seen.add(k)
            return super().__getitem__(k)

        def get(self, k, default=None):
            seen.add(k)
            return super().get(k, default)

        def __contains__(self, k):
            seen.add(k)
            return super().__contains__(k)

        def __iter__(self):
            seen.add("*전체*")
            return super().__iter__()

        def keys(self):
            seen.add("*전체*")
            return super().keys()

        def items(self):
            seen.add("*전체*")
            return super().items()

        def values(self):
            seen.add("*전체*")
            return super().values()

    ref = to_jsonable(duty_report(full["t"], Watch(full["signals"]), full["meta"],
                                  bins=16, rate_bins=24))
    assert seen and seen <= DUTY_SIGNALS, seen
    ref["result_id"] = rid
    got = client.get(f"/api/sim/{rid}/duty", params={"bins": 16}).json()
    assert json.dumps(got, ensure_ascii=False) == json.dumps(ref, ensure_ascii=False)
    # 트림 여유 분해가 선택 신호(mach·wow·on_rail)를 실제로 쓰는 런이어야 위 대조가 뜻이 있다
    assert got["trim_reserve"]["de_dyn_reserve_min_frac"] is not None

    # 목록이 엔진보다 모자라도 답은 같다 — 목록 밖 신호는 읽는 순간 그 줄만 마저 파싱한다
    # (없는 신호처럼 굴면 엔진의 .get이 None을 받아 그 보정을 조용히 건너뛴다)
    monkeypatch.setattr(sim_route, "DUTY_SIGNALS", frozenset({"de"}))
    assert client.get(f"/api/sim/{rid}/duty", params={"bins": 16}).json() == got
    monkeypatch.undo()

    # 쓰지 않는 신호 줄은 파싱조차 하지 않는다 — 그 줄을 망가뜨려도 타면 사용은 그대로다
    # (통째 읽기였다면 본문 전체가 손상 판정 → 404)
    path = client.app.state.store.root / f"{rid}.json"
    lines = path.read_text(encoding="utf-8").split("\n")
    victim = next(i for i, ln in enumerate(lines) if ln.startswith('"alpha": '))
    lines[victim] = '"alpha": @손상@,'
    path.write_text("\n".join(lines), encoding="utf-8")
    assert client.get(f"/api/sim/{rid}/duty", params={"bins": 16}).json() == got
    assert client.get(f"/api/sim/{rid}/replay", params={"stride": 10}).status_code == 404


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
    # 엔진 test_landing과 같은 값 — 프로펠러 전환으로 뒤로 밀렸다(107.3→115.4,
    # 129.9→137.9). 여유추력이 5,840 N → 1,320 N으로 줄어 상승·가속이 느려진 것이지
    # 접지 품질이 나빠진 게 아니다(엔진 쪽이 접지 속도 −0.96 m/s를 따로 못박는다).
    # 그다음 두 번은 발진 직후 스로틀이다 — 이 HTTP 경로 실측 115.74 → 112.05 → 111.27(정지 138.68 → 134.92 →
    # 134.13): 속도 명령필터 추월 동기화(fcl/graphs.py 속도 절)가 이탈 직후 스로틀 0 구간을 없앴고, 발사 출력
    # 웜스타트(sim/simulator.py run)가 남은 램프를 없앴다. 엔진 test_landing과 같은 사슬이다
    assert ph["touchdown_t"] == pytest.approx(111.3, abs=2.0)
    assert ph["stop_t"] == pytest.approx(134.1, abs=3.0)

    # 기준선은 결과와 함께 다닌다 — 엔진이 소비하지 않는 heading·length도 실려야
    # 재생 화면이 활주로 띠를 그린다 (웨이포인트 동봉과 같은 규약)
    assert body["meta"]["runway"] == {"elevation": 0.0, "heading": 0.0, "length": 1500.0}
    assert body["meta"]["launch"]["length"] == 10.0
    assert body["meta"]["launch"]["exit_speed"] == pytest.approx(81.5)
    assert body["meta"]["launch"]["accel"] is None, "둘 중 준 쪽만 실린다"
    assert body["meta"]["launch"]["origin_height"] == pytest.approx(2.9)


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
    """등급은 **이름으로** 고른다 — 웹이 RTK 수치를 재기술하면 02 §5.5 위반이다.

    요청은 seed만 담고, 값은 엔진 RTK_FIXED에서 온다. nav의 덮어쓰기가 등급 위에
    얹히는 것도 함께 고정한다(등급이 바탕, nav가 위).
    """
    from claw.nav import RTK_FIXED
    from claw_server.routes.sim import SimRunIn, _build

    req = _landing_mission(nav_grade="rtk", nav={"seed": 5})
    assert set(req["nav"]) & set(RTK_FIXED) == set(), "요청에 RTK 수치가 없어야 한다"
    sim, _tr = _build(SimRunIn(**req), example_profile())
    assert sim.nav_model.pos_std_v == RTK_FIXED["pos_std_v"]
    assert sim.nav_model.bias_std_v == RTK_FIXED["bias_std_v"]
    assert sim.nav_model.seed == 5
    # 자세 오차는 등급이 손대지 않는다 — RTK는 측위를 개선하지 자세가 아니다
    assert sim.nav_model.att_std == NavErrorModel().att_std

    # 대조군 — _landing_mission의 기본이 rtk라 등급을 명시적으로 되돌려야 한다
    plain, _ = _build(SimRunIn(**_landing_mission(nav_grade="default", nav={"seed": 5})), example_profile())
    assert plain.nav_model.pos_std_v == NavErrorModel().pos_std_v
    # 등급 위에 nav가 덮인다
    over, _ = _build(SimRunIn(**_landing_mission(
        nav_grade="rtk", nav={"seed": 5, "pos_std_v": 0.5})), example_profile())
    assert over.nav_model.pos_std_v == 0.5


def test_sim_meta에_측지_원점이_동봉된다(client, wait_job):
    """저장된 결과만으로 궤적을 실제 지도 위에 얹으려면 원점이 함께 다녀야 한다.

    웨이포인트·활주로와 같은 "기준선은 결과와 함께 다닌다" 규약이다. 원점 없이 저장된
    결과는 나중에 어느 지점의 비행이었는지 알 방법이 없고, 그때 추정 원점을 끼워 넣으면
    화면이 지어낸 좌표를 사실처럼 그린다.
    """
    origin = {"lat": 34.6, "lon": 127.2}
    j = wait_job(
        client.post("/api/sim/run", json=_hold_mission(t_end=2.0, origin=origin))
        .json()["id"],
        timeout=120.0,
    )
    meta = client.get(f"/api/results/{j['result_id']}").json()["meta"]
    assert meta["origin"]["lat"] == 34.6
    assert meta["origin"]["lon"] == 127.2
    assert meta["origin"]["datum"] == "wgs84"
    # 활주로가 없으면 곡률반경 기준 고도는 0이고, **그 사실을 출처로 밝힌다**
    assert meta["origin"]["h_ref"] == 0.0
    assert meta["origin"]["h_ref_src"] == "default 0"


def test_원점_없는_미션은_meta에_None을_남긴다(client, wait_job):
    """"원점 미지정"과 "적도 본초자오선"은 다른 사실이다 — 0,0으로 위장하지 않는다."""
    j = wait_job(
        client.post("/api/sim/run", json=_hold_mission(t_end=2.0)).json()["id"],
        timeout=120.0,
    )
    assert client.get(f"/api/results/{j['result_id']}").json()["meta"]["origin"] is None


def test_활주로가_있으면_원점의_기준고도가_활주로_표고다(client, wait_job):
    """곡률반경 평가에 쓴 고도가 무엇이었는지 결과가 밝혀야 한다.

    h_ref 500 m는 곡률반경을 7.8e-5만큼 바꾸고 원점 20 km 지점에서 1.6 m 어긋난다 —
    나중에 그 어긋남을 설명하려면 어느 값을 썼는지가 결과에 남아 있어야 한다.
    """
    j = wait_job(
        client.post("/api/sim/run", json=_hold_mission(
            t_end=2.0, origin={"lat": 34.6, "lon": 127.2},
            runway={"elevation": 12.5, "heading": 0.0, "length": 1200.0},
        )).json()["id"],
        timeout=120.0,
    )
    origin = client.get(f"/api/results/{j['result_id']}").json()["meta"]["origin"]
    assert origin["h_ref"] == 12.5
    assert origin["h_ref_src"] == "runway.elevation"


@pytest.mark.parametrize(
    "origin",
    [
        {"lat": 91.0, "lon": 127.2},
        {"lat": -91.0, "lon": 127.2},
        # 극 근방 — 국지 접평면 근사가 성립하지 않는 구간(geodesy가 |lat| > 89를 거부).
        # 여기서 받아 주면 저장된 뒤 지도 계층에서 터진다.
        {"lat": 89.5, "lon": 127.2},
        {"lat": -89.5, "lon": 127.2},
        {"lat": 34.6, "lon": 181.0},
        {"lat": 34.6, "lon": -181.0},
        {"lat": 34.6},  # lon 누락 — 반쪽 원점은 원점이 아니다
        {"lat": 34.6, "lon": 127.2, "datum": "bessel"},  # 미지원 측지계
    ],
)
def test_범위_밖_원점은_422로_거부된다(client, origin):
    """지도 등록 기준이 말이 안 되면 제출 시점에 막는다 — 조용히 감싸 돌지 않는다."""
    r = client.post("/api/sim/run", json=_hold_mission(t_end=2.0, origin=origin))
    assert r.status_code == 422


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_비유한_원점_리터럴은_422로_거부된다(client, bad):
    """JSON 파서는 NaN·Infinity 리터럴을 받아 주지만 FiniteFloat이 경계에서 막는다.

    통과시키면 지도 등록이 조용히 무의미해지는 데다, 저장 시점 allow_nan=False에서
    결과 인코딩이 통째로 죽는다 (routes/trim.py FiniteFloat 도입 사유와 같다).
    """
    import json as _json

    mission = _hold_mission(t_end=2.0)
    mission["origin"] = {"lat": 34.6, "lon": 127.2}
    raw = _json.dumps(mission).replace('"lon": 127.2', f'"lon": {bad}')
    r = client.post(
        "/api/sim/run", content=raw, headers={"content-type": "application/json"}
    )
    assert r.status_code == 422


def test_unseeded_aircraft_sim_run_is_a_422_with_the_document_path(client, unseeded_doc):
    """게인 미설계 기체의 실행 제출은 202 전에 422 — detail이 {path, message}라 웹이 「기체 탭 →
    초기 게인」 링크를 경로 대조로 세운다 (문자열 detail이던 종전에는 링크가 서지 않았다)."""
    assert client.post("/api/profiles", json={"document": unseeded_doc("no-gains-sim")}).status_code == 201
    r = client.post("/api/sim/run", json={
        "trim": {"name": "t", "mach": 0.45, "alt": 1000.0, "fuel": 200.0},
        "modes": [{"name": "hold", "speed": 150.0, "alt": 1000.0, "heading": 0.0, "exit": ["time_ge", 1e9]}],
        "t_end": 1.0, "profile": {"id": "no-gains-sim"}})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["path"] == "/law/design", r.text
