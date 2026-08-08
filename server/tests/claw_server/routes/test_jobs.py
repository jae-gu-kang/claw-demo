"""작업 라우트 검증 — 빈 목록, 미존재 작업 404 (조회·취소), 웹소켓 진행률 푸시."""

TERMINAL = ("done", "error", "cancelled")


def test_jobs_empty_then_404(client):
    assert client.get("/api/jobs").json() == []
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_ws_job_progress_stream(client, wait_job):
    """웹소켓 — 진행률 변화 푸시, 종단 상태로 종료 (M13 [확정] 진행률 모니터링)."""
    cases = [{"mach": m, "alt": 1000.0, "fuel": 200.0} for m in (0.5, 0.6, 0.7)]
    jid = client.post("/api/trim/batch", json={"cases": cases}).json()["id"]
    msgs = []
    with client.websocket_connect(f"/api/ws/jobs/{jid}") as ws:
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m["status"] in TERMINAL:
                break
    assert msgs[-1]["status"] == "done"
    assert msgs[-1]["progress"] == 1.0 and msgs[-1]["result_id"] == jid
    progresses = [m["progress"] for m in msgs]
    assert progresses == sorted(progresses)  # 단조 증가 (중복 없는 변화 푸시)
    assert all(m["id"] == jid for m in msgs)


def test_ws_unknown_job_reports_error(client):
    with client.websocket_connect("/api/ws/jobs/nope") as ws:
        assert "error" in ws.receive_json()
