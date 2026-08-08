"""작업 라우트 검증 — 빈 목록, 미존재 작업 404 (조회·취소)."""


def test_jobs_empty_then_404(client):
    assert client.get("/api/jobs").json() == []
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/cancel").status_code == 404
