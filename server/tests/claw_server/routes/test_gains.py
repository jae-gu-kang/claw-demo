"""게인 스케줄 편집 경로 검증 — 02 §8 워크플로우 4단계 (웹 테이블 편집 → 시뮬 반영).

GET /api/gains/demo(설계 테이블 조회) → 편집 → 시뮬 요청 gain_tables 주입의
왕복을 핀한다. 그룹·게인 이름 검증(FCL 조립)과 테이블 규격 검증(Table)은
엔진 소관 — 서버는 422 매핑만.
"""


def _hold_mission(**over):
    base = {
        "trim": {"name": "design", "mach": 0.6, "alt": 1000.0, "fuel": 200.0},
        "modes": [
            {"name": "hold", "speed": 199.0, "alt": 1000.0, "heading": 0.0,
             "exit": ["time_ge", 1e9]},
        ],
        "t_end": 5.0,
    }
    base.update(over)
    return base


def test_demo_gain_tables_listing(client):
    r = client.get("/api/gains/demo")
    assert r.status_code == 200
    tables = r.json()
    assert {"pitch.kp", "pitch.ki", "pitch.k_rate", "roll.kp", "roll.ki",
            "roll.k_rate"} == set(tables)
    t = tables["pitch.kp"]
    assert list(t["axes"]) == ["mach"]
    machs = t["axes"]["mach"]
    assert machs == sorted(machs) and len(t["data"]) == len(machs)
    assert t["extrapolate"] == "clip"


def test_edited_gain_tables_roundtrip_into_sim(client, wait_job):
    """조회한 테이블을 편집(피치 kp 0.9배)해 시뮬에 주입 — 정상 완주."""
    tables = client.get("/api/gains/demo").json()
    tables["pitch.kp"]["data"] = [0.9 * v for v in tables["pitch.kp"]["data"]]
    r = client.post("/api/sim/run", json=_hold_mission(gain_tables=tables))
    assert r.status_code == 202
    j = wait_job(r.json()["id"], timeout=120.0)
    assert j["status"] == "done"
    body = client.get(f"/api/results/{j['result_id']}").json()
    assert abs(body["signals"]["h"][-1] - 1000.0) < 5.0  # 소폭 소프트닝 — 유지 성능 보전


def test_autopilot_gain_override_into_sim(client, wait_job):
    """AP 게인 오버라이드 (파라미터 스터디 경로) — 엔진 Autopilot kwargs 통과."""
    r = client.post("/api/sim/run", json=_hold_mission(autopilot={"kp_alt": 0.008}))
    assert r.status_code == 202
    assert wait_job(r.json()["id"], timeout=120.0)["status"] == "done"
    # 미지원 게인 이름은 엔진 TypeError → 422
    bad = client.post("/api/sim/run", json=_hold_mission(autopilot={"kp_nope": 1.0}))
    assert bad.status_code == 422


def test_gain_tables_validation_422(client):
    tables = client.get("/api/gains/demo").json()
    # 미정의 그룹 이름 (FCL 조립 검증)
    bad_group = dict(tables)
    bad_group["pitchX.kp"] = bad_group.pop("pitch.kp")
    assert client.post(
        "/api/sim/run", json=_hold_mission(gain_tables=bad_group)
    ).status_code == 422
    # 미정의 게인 "키" — 실행 시점 TypeError로 지연 금지 (리뷰 M1)
    bad_key = dict(tables)
    bad_key["pitch.kpX"] = bad_key.pop("pitch.kp")
    assert client.post(
        "/api/sim/run", json=_hold_mission(gain_tables=bad_key)
    ).status_code == 422
    # 빈 dict — 조용한 무스케줄 방지 (리뷰 S2)
    assert client.post(
        "/api/sim/run", json=_hold_mission(gain_tables={})
    ).status_code == 422
    # 데이터 형상 불일치 (Table 검증)
    bad_shape = {k: dict(v) for k, v in tables.items()}
    bad_shape["pitch.kp"]["data"] = bad_shape["pitch.kp"]["data"][:-1]
    assert client.post(
        "/api/sim/run", json=_hold_mission(gain_tables=bad_shape)
    ).status_code == 422
    # 스케줄 비활성 조립에 주입 (엔진 구성 오류)
    assert client.post(
        "/api/sim/run", json=_hold_mission(gain_tables=tables, with_schedule=False)
    ).status_code == 422
    # 비유한값 데이터 (경계 차단)
    bad_nan = {k: dict(v) for k, v in tables.items()}
    bad_nan["pitch.kp"]["data"] = list(bad_nan["pitch.kp"]["data"])
    bad_nan["pitch.kp"]["data"][0] = None  # JSON null → 검증 오류
    assert client.post(
        "/api/sim/run", json=_hold_mission(gain_tables=bad_nan)
    ).status_code == 422
