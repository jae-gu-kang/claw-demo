"""목록 요약의 `applied_design` — 확정 게인 표가 그대로 어느 자동 설계 결과의 반영물인가 (02 §5.6).

반영(apply-gains)은 표를 문서에 써서 지문을 바꾼다 — 그래서 그 표를 낸 자동 설계 결과가 곧바로 「낡음」으로
보였다(바뀐 것이 제 산출물뿐인데). 목록이 "표가 반영한 그대로이고 표 밖은 반영 뒤 그대로"일 때만 그 결과
id를 싣고, 웹(lib/freshness.js)이 그 결과를 「문서에 반영됨」으로 말한다. 표를 손으로 고치거나 표 밖을
고치면 다시 null(낡음)이어야 한다 — 이 파일이 그 양쪽을 고정한다.
"""

import copy

from claw.profile import build_profile, load_example, validate_document
from claw.profile.fingerprint import gain_tables_basis_fingerprint
from claw_server.profiles import ProfileStore


def _doc(pid):
    d = load_example()
    d.update(id=pid, name="반영 표시 시험", description="시험용", is_example=False, variants=[])
    return d


def _with_tables(doc, *, result_id="r-applied", base_revision=1, scale=1.0):
    """반영이 쓰는 모양의 확정 표 절 — 출처에 결과 id·기준 리비전·기준 지문(apply-gains와 같은 칸)."""
    d = copy.deepcopy(doc)
    d["law"]["gain_tables"] = None
    grid = d["law"]["schedule"]["mach_grid"]
    k0 = build_profile(validate_document(d)).design_gains()["pitch.kp"]
    prov = {"source": "auto_design", "basis_fingerprint": gain_tables_basis_fingerprint(validate_document(d))}
    if result_id is not None:
        prov.update(result_id=result_id, base_revision=base_revision, applied_at="2026-09-26T00:00:00+00:00")
    d["law"]["gain_tables"] = {
        "tables": {"pitch.kp": {"axes": {"mach": list(grid)}, "data": [k0 * scale] * len(grid),
                                "extrapolate": "clip"}},
        "provenance": prov,
    }
    return d


def _row(client, pid):
    return next(p for p in client.get("/api/profiles").json() if p["id"] == pid)


def test_summary_names_the_applied_result_only_when_tables_are_verbatim_and_basis_unchanged():
    plain = validate_document(_doc("ap-unit"))
    assert ProfileStore.summary(plain, 1)["applied_design"] is None  # 표 없음

    tabled = validate_document(_with_tables(plain, base_revision=1))
    section = copy.deepcopy(tabled["law"]["gain_tables"])
    assert ProfileStore.summary(tabled, 2, section)["applied_design"] == {"result_id": "r-applied", "revision": 2}
    # 반영이 쓴 리비전을 못 읽었으면(재료 없음) 판정하지 않는다 — 낡음 그대로
    assert ProfileStore.summary(tabled, 2)["applied_design"] is None

    # 표를 손으로 고쳤다(출처는 남음) — 더는 그 결과의 산출물이 아니다
    hand = copy.deepcopy(tabled)
    hand["law"]["gain_tables"]["tables"]["pitch.kp"]["data"][0] *= 1.5
    hand = validate_document(hand)
    assert ProfileStore.summary(hand, 3, section)["applied_design"] is None

    # 표 밖(기준 지문 안)을 고쳤다 — 표가 낡았고, 그 결과를 계산한 문서와도 다르다
    edited = copy.deepcopy(tabled)
    edited["mass"]["m_empty"] += 1.0
    edited = validate_document(edited)
    assert ProfileStore.summary(edited, 3, copy.deepcopy(edited["law"]["gain_tables"]))["applied_design"] is None

    # 결과 id 없는 출처(생성기 문서·손으로 넣은 표)는 이름 댈 결과가 없다
    gen = validate_document(_with_tables(plain, result_id=None))
    assert ProfileStore.summary(gen, 1, copy.deepcopy(gen["law"]["gain_tables"]))["applied_design"] is None


def test_listing_tracks_the_applied_result_across_revisions(client):
    """리비전을 건너서도 — 반영 뒤 지문 밖(표시 모델)만 고치면 유지, 표를 손으로 고치면 null, 되돌리면 다시,
    표 밖(질량)을 고치면 null."""
    pid = "ap-list"
    assert client.post("/api/profiles", json={"document": _doc(pid)}).status_code == 201
    assert _row(client, pid)["applied_design"] is None

    head = client.get(f"/api/profiles/{pid}").json()["document"]
    applied = _with_tables(head, base_revision=1)
    assert client.put(f"/api/profiles/{pid}", json={"base_revision": 1, "document": applied}).status_code == 200
    assert _row(client, pid)["applied_design"] == {"result_id": "r-applied", "revision": 2}

    # 지문 밖(표시 모델) 편집 — 리비전 3. 반영이 쓴 리비전 2를 다시 읽어 대조한다
    doc = client.get(f"/api/profiles/{pid}").json()["document"]
    doc["display"] = None
    assert client.put(f"/api/profiles/{pid}", json={"base_revision": 2, "document": doc}).status_code == 200
    row = _row(client, pid)
    assert row["revision"] == 3 and row["applied_design"] == {"result_id": "r-applied", "revision": 2}

    # 표를 손으로 고침(출처는 그대로) — 리비전 4
    hand = copy.deepcopy(doc)
    hand["law"]["gain_tables"]["tables"]["pitch.kp"]["data"][0] *= 1.5
    assert client.put(f"/api/profiles/{pid}", json={"base_revision": 3, "document": hand}).status_code == 200
    row = _row(client, pid)
    assert row["gain_tables"]["stale"] is False  # 조립 기준(기준 지문)으로는 낡지 않았지만
    assert row["applied_design"] is None          # 그 결과의 산출물은 더는 아니다

    # 되돌림 — 리비전 5, 표 절이 리비전 2와 같다
    assert client.put(f"/api/profiles/{pid}", json={"base_revision": 4, "document": doc}).status_code == 200
    assert _row(client, pid)["applied_design"] == {"result_id": "r-applied", "revision": 2}

    # 표 밖(질량) 편집 — 리비전 6, 낡음
    heavy = copy.deepcopy(doc)
    heavy["mass"]["m_empty"] += 1.0
    assert client.put(f"/api/profiles/{pid}", json={"base_revision": 5, "document": heavy}).status_code == 200
    row = _row(client, pid)
    assert row["gain_tables"]["stale"] is True and row["applied_design"] is None


def test_real_apply_gains_names_its_result_in_the_listing(client, wait_job):
    """계약 대조 — 실제 apply-gains가 적는 출처(result_id·base_revision)로 목록이 그 결과를 이름 댄다.
    반영이 문서 지문을 바꿔 결과 echo의 지문과 지금 목록 지문은 다르다(웹이 이 둘을 함께 본다)."""
    pid = "ap-real"
    assert client.post("/api/profiles", json={"document": _doc(pid)}).status_code == 201
    r = client.post("/api/design/auto", json={
        "config": {"n_mach": 3, "alts": [1000.0], "fuels": [200.0], "budget_points": 24,
                   "budget_iters": 2, "mode": "auto"},
        "profile": {"id": pid}})
    assert r.status_code == 202, r.text
    j = wait_job(r.json()["id"], timeout=300.0)
    assert j["status"] == "done", j
    rid = j["result_id"]
    ok = client.post(f"/api/design/{rid}/apply-gains", json={"base_revision": 1})
    assert ok.status_code == 200, ok.text

    row = _row(client, pid)
    assert row["applied_design"] == {"result_id": rid, "revision": ok.json()["revision"]}
    echo = client.get(f"/api/results/{rid}").json()["profile"]
    assert echo["fingerprint"] != row["fingerprint"]  # 지문만 보면 낡음 — 그래서 이 칸이 필요하다
