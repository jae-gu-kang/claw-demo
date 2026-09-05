"""탑재 C 신뢰성 검증 라우트 (검증 탭) — 202 잡 → DAL A 리포트 저장.

판정 문구·요약·DO-178C 표의 정본은 엔진(claw.verify)이고 그 검출력은 엔진
테스트가 단정한다. 여기서 지키는 것은 서버 계약이다:
  ① 형상이 곧 대상 — 지문이 /codegen/flight와 같은가 (같은 조립을 쓰는가)
  ② 구성 오류는 202 수락 전에 422로 거부되는가
  ③ 리포트가 결과 저장소에 실리고 메타에 판정이 앉는가
  ④ 환경 정직성 — 컴파일러가 있으면 대조·유닛 pass, 없으면 skip (조용한 부재 금지)
"""

import shutil

TERMINAL = ("done", "error", "cancelled")


def _run(client, wait_job, **body):
    r = client.post("/api/verify/flight", json={"t_end": 6.0, **body})
    assert r.status_code == 202, r.text
    job = wait_job(r.json()["id"], timeout=300.0)
    assert job["status"] == "done", job
    res = client.get(f"/api/results/{job['result_id']}")
    assert res.status_code == 200
    return job["result_id"], res.json()


def test_리포트가_저장되고_요약과_판정이_실린다(client, wait_job):
    rid, body = _run(client, wait_job)
    assert body["kind"] == "verify_flight"
    rep = body["report"]
    assert [r["key"] for r in rep["summary"]] == [
        "static", "compile", "paths", "equiv", "coverage"]
    assert rep["verdict"] in ("pass", "fail", "pass_with_skips")
    # DAL A 증적 구획 — 화면·보고서가 소비하는 것들이 전부 실려야 한다
    assert rep["dal"] and rep["cases"] and rep["units"]
    assert any(r["status"] == "out" for r in rep["dal"])  # 범위 밖 명시 (조용한 누락 금지)
    assert all("text" in f for f in rep["files"])  # 자립적 증적 — 소스 동봉
    # 메타에도 판정 — 결과 탭 목록이 본문 없이 판정을 보여줄 수 있어야 한다
    meta = next(m for m in client.get("/api/results").json() if m["id"] == rid)
    assert meta["kind"] == "verify_flight"
    assert meta["verdict"] == rep["verdict"]
    assert meta["fingerprint"] == rep["fingerprint"]


def test_환경에_정직하다_컴파일러_유무(client, wait_job):
    _rid, body = _run(client, wait_job)
    rep = body["report"]
    by = {r["key"]: r for r in rep["summary"]}
    assert by["coverage"]["status"] in ("pass", "fail", "skip")  # 측정은 판정으로 승격됐다
    if shutil.which("cc") or shutil.which("gcc") or shutil.which("clang"):
        assert by["compile"]["status"] == "pass", rep["compile"]
        assert by["equiv"]["status"] == "pass", rep["equivalence"]
        assert all(c["status"] == "pass" for c in rep["cases"])
        units = {u["unit"]: u for u in rep["units"]}
        assert set(units) == {"sched", "ap", "lim", "scas", "mix", "fcl", "claw_rt"}
        assert all(u["cases"]["passed"] == u["cases"]["total"] for u in rep["units"])
        if rep["coverage"]["status"] == "measured":
            assert rep["mcdc"]["status"] == "measured"
            assert rep["coverage"]["files"] and "line_counts" in rep["coverage"]["files"][0]
    else:
        assert by["compile"]["status"] == "skip"
        assert by["equiv"]["status"] == "skip"
        assert rep["coverage"]["status"] == "skip" and rep["coverage"]["reason"]


def test_지문이_codegen_라우트와_같다(client, wait_job):
    """검증한 코드 = Autocode 탭이 보여 준 코드 — 조립이 갈라지면 지문이 갈라진다."""
    edited = {"autopilot": {"kp_alt": 0.008}}
    code = client.post("/api/codegen/flight", json=edited).json()
    _rid, body = _run(client, wait_job, **edited)
    assert body["report"]["fingerprint"] == code["fingerprint"]


def test_구성_오류는_202_전에_422(client):
    r = client.post("/api/verify/flight",
                    json={"scas": {"pitch": {"kp": -2.0}}, "t_end": 6.0})
    assert r.status_code == 422 and "세 축 전부 필요" in r.text
    r = client.post("/api/verify/flight", json={"t_end": 0})
    assert r.status_code == 422
