"""결과 라우트 검증 — 빈 목록, 미존재·부정 id는 404 (내부 오류 미노출), 본문은 파일 그대로."""

import asyncio
import json
import tracemalloc


def test_results_empty_then_404(client):
    assert client.get("/api/results").json() == []
    assert client.get("/api/results/nope").status_code == 404
    assert client.get("/api/results/a.b").status_code == 404  # 부정 id도 404로 맵핑


# ── 본문 통째 조회는 저장 파일을 흘려보낸다 (Render 512 MB — store.py 머리말) ──────────
#
# dict로 돌려주던 때는 파싱본 + 응답 직렬화본이 함께 서서 S1 기본 미션 sim(본문 68.6 MB)에서
# 서버 정점 +193 MB(tracemalloc)·uvicorn RSS +195 MB, 예제 기체 750 s(106.9 MB)에서
# +307 MB·RSS +338 MB(정점 516 MB)였다. 흘려보내면 +2 MB(RSS +8~12 MB)다.


def _sim_like(n_sig, n):
    """sim 본문 꼴의 합성 결과 — 긴 신호 여럿 + 한글 meta + 빈 dict·스칼라 (test_store와 같은 꼴)."""
    return {
        "t": [i * 0.01 for i in range(n)],
        "signals": {f"s{k}": [((i * 7919 + k) % 1000) / 3.0 for i in range(n)]
                    for k in range(n_sig)} | {"mode": ["launch"] * n},
        "envelope": {"stall_margin": [0.1] * n, "flags": {"alpha": [False] * n},
                     "worst_margin": 0.1, "first_flag_t": None},
        "empty": {},
        "meta": {"profile": {"name": "쇼케이스 델타"}, "dt_plant": 1e-05, "note": "a,\n b"},
        "kind": "sim",
    }


def test_result_body_is_the_stored_file_byte_for_byte(client):
    """응답 바이트 = 저장 파일 — 값·**키 순서**는 저장 본문(store.load)과 같고 글자 모양(줄 나눔·
    공백·수 표기)만 파일의 것이다(예전 응답은 1e-05를 0.00001로 썼다). 이 형식 이전의 한 줄
    본문도 그 파일 그대로 나간다. 머리는 JSON·길이 그대로."""
    store = client.app.state.store
    store.save("r1", _sim_like(3, 50), meta={"kind": "sim", "created": 1.0})
    legacy = {"kind": "trim_batch", "rows": [{"mach": 0.6, "ok": True}], "note": "한 줄"}
    (store.root / "old1.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    for rid in ("r1", "old1"):
        r = client.get(f"/api/results/{rid}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        assert r.content == (store.root / f"{rid}.json").read_bytes(), rid
        assert int(r.headers["content-length"]) == len(r.content)
        # 값과 키 순서까지 — 골든(hexjson)이 dict 순서를 본다
        want = store.load(rid)
        assert json.dumps(r.json(), ensure_ascii=False) == json.dumps(want, ensure_ascii=False)
    assert client.get("/api/results/old1").json() == legacy


def test_result_body_of_a_real_job_reads_back_the_same(client, wait_job):
    """잡이 저장한 실제 결과(트림 배치)도 파싱한 값이 store.load와 같다 — 종류를 묻지 않는 길이다."""
    j = wait_job(client.post("/api/trim/batch", json={
        "cases": [{"mach": 0.6, "alt": 1000.0, "fuel": 200.0}]}).json()["id"])
    rid = j["result_id"]
    body = client.get(f"/api/results/{rid}").json()
    assert body["kind"] == "trim_batch"
    assert json.dumps(body, ensure_ascii=False) == json.dumps(
        client.app.state.store.load(rid), ensure_ascii=False)


def _server_peak(app, path):
    """ASGI 앱을 직접 불러 서버 쪽 정점만 잰다 — 본문 청크는 받는 즉시 버린다.

    TestClient는 응답 본문을 통째로 두 벌 버퍼링해(파일 크기 ×2) 서버 정점을 가린다."""
    got = {"status": None, "n": 0}
    asked = []

    async def receive():
        if not asked:
            asked.append(1)
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(3600)  # 끊김 감시 — 응답이 끝나면 취소된다

    async def send(msg):
        if msg["type"] == "http.response.start":
            got["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            got["n"] += len(msg.get("body", b""))

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "headers": [(b"host", b"testserver")],
             "server": ("testserver", 80), "client": ("testclient", 1)}
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        asyncio.run(app(scope, receive, send))
        return got, tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()


def test_result_body_is_not_parsed_on_the_server(client):
    """서버 정점이 본문 크기와 무관해야 한다 — 파싱본(값 하나에 float 24 B + 목록 칸 8 B라 파일
    글보다 크다)도 직렬화본도 서지 않고 1 MB 청크 두어 개만 선다(S1 68.6 MB 본문에서도 +2.2 MB).
    dict로 돌려주면 파싱본 + 직렬화본이라 본문 크기의 몇 배가 되어 여기서 걸린다."""
    store = client.app.state.store
    store.save("big1", _sim_like(40, 10000), meta={"kind": "sim", "created": 1.0})
    size = (store.root / "big1.json").stat().st_size
    assert size > 5_000_000  # 청크(1 MB) 여러 개 — 흘려보내기와 통째 읽기가 갈리는 크기
    got, peak = _server_peak(client.app, "/api/results/big1")
    assert got["status"] == 200
    assert peak < 0.5 * size, (peak, size)
    assert got["n"] == size  # 파일 전부가 나갔다(청크를 빠뜨리지 않았다)
