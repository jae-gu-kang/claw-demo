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


# ---------- 스케줄 자리 (어떤 게인에 테이블을 붙일지) ----------


def test_gain_slot_catalog(client):
    """자리 목록은 18칸 격자로 오되 켤 수 있는 곳은 16이다 — 속도·헤딩의 k_rate는
    rate 경로가 없어 구조상 불가. 빈칸으로 두면 왜 없는지 알 수 없어 사유를 함께 준다."""
    d = client.get("/api/gains/catalog").json()
    assert d["axis"] == "mach"
    slots = {s["name"]: s for s in d["slots"]}
    assert len(slots) == 18
    assert sum(1 for s in slots.values() if s["available"]) == 16
    for name in ("speed.k_rate", "heading.k_rate"):
        assert slots[name]["available"] is False
        assert "rate" in slots[name]["reason"]
    # 기본 스케줄 6자리만 켜져 있다 — 나머지는 켤 수 있으나 지금은 설계점 고정
    on = {n for n, s in slots.items() if s.get("scheduled")}
    assert on == set(d["default"]) == {
        "pitch.kp", "pitch.ki", "pitch.k_rate", "roll.kp", "roll.ki", "roll.k_rate"}
    # AP 축은 설계 파라미터 이름이 다르다 — 웹이 "무엇이 고정되는지" 보여 줄 수 있어야
    assert slots["alt.k_rate"]["param"] == "k_hdot"
    assert slots["alt.k_rate"]["design"] == -0.008
    assert slots["alt.k_rate"]["unit"]
    # 상수가 어느 컴포넌트에 사는가 — 웹이 축 이름으로 추측하지 않도록 서버가 말한다
    assert slots["alt.k_rate"]["block"] == "autopilot"
    assert slots["yaw.kp"]["block"] == "scas"


def test_catalog_design_value_matches_demo_tables(client):
    """끄면 굳는 값(design)과 켜져 있을 때의 설계점 값이 같아야 한다 — 자리를 켜고
    끄는 것만으로 설계점 거동이 달라지면 비교 자체가 불가능해진다."""
    d = client.get("/api/gains/catalog").json()
    demo = client.get("/api/gains/demo").json()
    for s in d["slots"]:
        if not s["available"]:
            continue
        machs, data = s["table"]["axes"]["mach"], s["table"]["data"]
        assert data[machs.index(0.6)] == s["design"], s["name"]
        if s["name"] in demo:  # 이미 켜진 자리는 설계 테이블과 동일해야 한다
            assert s["table"] == demo[s["name"]]


def test_catalog_carries_scas_design_kwargs(client):
    """구조도 SCAS 축 폼의 초기값 — 레지스트리 스키마로는 대신할 수 없다.

    ScasAxis는 범용 축 컴포넌트라 ParamDef 기본값이 전부 0이다. 그걸 폼 기본값으로
    쓰면 "기본값으로 되돌리기"가 게인을 0으로 만든다. 데모 기체의 설계 kwargs는
    조립(make_demo_fcl)만 알고 있으므로 여기서 내려 준다 — 스케줄 자리가 아닌
    washout_tau·클램프까지 포함해야 세 축 전부를 보내는 req.scas를 만들 수 있다.
    """
    d = client.get("/api/gains/catalog").json()
    design = d["scas_design"]
    assert set(design) == {"pitch", "roll", "yaw"}
    assert design["pitch"]["kp"] == -2.0
    assert design["yaw"]["washout_tau"] == 2.0  # 스케줄 자리가 아닌 값도 온다
    # 게인 자리는 slot design과 같은 값이어야 한다 — 두 곳이 갈리면 폼과 격자가 어긋난다
    slots = {s["name"]: s for s in d["slots"] if s["available"]}
    for name, s in slots.items():
        if s["block"] == "scas":
            assert design[s["group"]][s["param"]] == s["design"], name
    # 그대로 시뮬에 실을 수 있는 형상이어야 한다 (세 축 전부 = req.scas 계약)
    r = client.post("/api/sim/run", json=_hold_mission(t_end=2.0, scas=design))
    assert r.status_code == 202


def test_catalog_design_index_points_at_the_design_mach(client):
    """설계점 인덱스 — 웹이 상수↔테이블을 오갈 때의 기준점.

    이게 있어야 웹이 스케줄 스케일 규칙(데모는 동압 역비)을 다시 적지 않고도
    "켜면 이 상수에서 출발", "끄면 이 값으로 굳음"을 계산할 수 있다.
    """
    d = client.get("/api/gains/catalog").json()
    i = d["design_index"]
    for s in d["slots"]:
        if not s["available"]:
            continue
        machs, data = s["table"]["axes"]["mach"], s["table"]["data"]
        assert machs[i] == 0.6, "설계점 마하가 아니다"
        assert data[i] == s["design"], s["name"]


def test_catalog_slot_subset_runs_and_changes_flight_code(client):
    """자리 선택은 표시 설정이 아니라 형상이다 — 탑재 C의 룩업 수와 지문이 바뀐다."""
    cat = {s["name"]: s for s in client.get("/api/gains/catalog").json()["slots"]}
    base = client.post("/api/codegen/flight", json={}).json()
    subset = {n: cat[n]["table"] for n in ("pitch.kp", "roll.kp", "yaw.k_rate")}
    r = client.post("/api/codegen/flight", json={"gain_tables": subset})
    assert r.status_code == 200
    got = r.json()

    def sched(body):
        return next(f["text"] for f in body["files"] if f["name"] == "fcl_sched.c")

    assert sched(base).count("claw_lookup1d") == 6
    assert sched(got).count("claw_lookup1d") == 3
    assert got["fingerprint"] != base["fingerprint"]
    # 요축 레이트 게인이 상수에서 신호가 된다
    scas = next(f["text"] for f in got["files"] if f["name"] == "fcl_scas.c")
    assert "sched_yaw_k_rate" in scas


def test_schedule_off_drops_the_whole_subsystem(client):
    """'전부 끔' = with_schedule=False — 룩업도 필터 상태도 남지 않는다."""
    off = client.post("/api/codegen/flight", json={"with_schedule": False}).json()
    names = {f["name"] for f in off["files"]}
    assert "fcl_sched.c" not in names and "fcl_sched.h" not in names
    assert off["fingerprint"] != client.post("/api/codegen/flight", json={}).json()[
        "fingerprint"]


def test_structurally_impossible_slot_rejected(client):
    """카탈로그가 불가라고 한 자리를 우겨 넣으면 422 — 목록과 검증이 같은 표를 본다."""
    cat = {s["name"]: s for s in client.get("/api/gains/catalog").json()["slots"]}
    tab = cat["pitch.kp"]["table"]
    for name in ("speed.k_rate", "heading.k_rate"):
        r = client.post("/api/codegen/flight", json={"gain_tables": {name: tab}})
        assert r.status_code == 422, name
