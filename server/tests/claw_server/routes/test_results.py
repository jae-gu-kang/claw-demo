"""결과 라우트 검증 — 빈 목록, 미존재·부정 id는 404 (내부 오류 미노출)."""


def test_results_empty_then_404(client):
    assert client.get("/api/results").json() == []
    assert client.get("/api/results/nope").status_code == 404
    assert client.get("/api/results/a.b").status_code == 404  # 부정 id도 404로 맵핑
