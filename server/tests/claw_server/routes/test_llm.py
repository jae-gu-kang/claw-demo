"""LLM 라우트 (미션 초안 + 결과 브리핑) — 202 잡·degrade 계약.

초안의 의미 검증은 웹(lib/mission.js buildModes·buildWaypoints)과 실행 시점
/sim/run 422가 정본이고, 브리핑의 가지치기 계약은 test_brief.py가 지킨다.
여기서 지키는 것은 서버 계약이다:
  ① 키가 없으면 status가 사유 문장을 내고, 생성 POST는 503 + 같은 사유로 거부
  ② 키가 있으면 202 잡이 돌고 산출물(초안/소견서)과 메타가 저장소에 실린다
  ③ 호출 실패·모델 거절이 잡 error와 사유로 드러난다 (조용한 실패 금지)
  ④ 상태 조회는 바깥으로 나가지 않는다 — 아웃바운드는 생성 호출 하나뿐
     (routes/world.py "서버는 나가지 않는다" 계약의 명시적 예외 범위 고정)
  ⑤ 브리핑 대상 검증 — 없는 결과 404 · 소견서의 소견서 422 · 지문 승계
"""

import json
import socket
import threading
from pathlib import Path

import claw_server.routes.llm as llm_route

_REPO = Path(__file__).resolve().parents[4]

# 스키마(structured output)가 보장하는 형상의 최소 예 — 서버는 이걸 깊이
# 검증하지 않고 그대로 실어야 한다 (의미 검증은 웹·엔진 몫)
_DRAFT = {
    "summary": "북쪽 5 km 왕복",
    "assumptions": ["순항 고도 200 m"],
    "modeRows": [
        {"name": "cruise", "speed": "88", "lonAxis": "alt", "lonValue": "200",
         "heading": "path", "exitKind": "path_done", "exitValue": "", "next": ""},
    ],
    "wpRows": [{"n": "5000", "e": "0", "d": ""}],
    "runConditions": {"mach": "0", "alt": "0", "fuel": "300", "groundOn": True,
                      "launchOn": True, "tEnd": "200", "accept": "100"},
    "warnings": [],
}


def _fake_raw(draft):
    """Anthropic Messages API 원시 응답의 최소 재현 — 첫 text 블록이 JSON."""
    return {
        "content": [{"type": "text", "text": json.dumps(draft, ensure_ascii=False)}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


def test_키가_없으면_상태가_사유를_말하고_생성은_503(client):
    """degrade는 world/manifest 규약 — 404·빈 응답이 아니라 사유 문장.

    conftest _no_deploy_env가 CLAW_ANTHROPIC_API_KEY를 지워 두는 것이 전제다 —
    개발 셸의 진짜 키가 이 테스트를 뒤집으면 안 된다."""
    s = client.get("/api/llm/status")
    assert s.status_code == 200
    body = s.json()
    assert body["available"] is False
    assert body["model"] is None
    assert "CLAW_ANTHROPIC_API_KEY" in body["reason"]  # 사유에 복구 열쇠 이름

    r = client.post("/api/llm/mission-draft", json={"intent": "북쪽으로 5 km"})
    assert r.status_code == 503
    assert "CLAW_ANTHROPIC_API_KEY" in r.json()["detail"]


def test_키가_있으면_상태가_모델을_말한다(client, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    body = client.get("/api/llm/status").json()
    assert body["available"] is True
    assert body["model"] == "claude-opus-5"  # 기본 모델
    assert body["reason"] is None
    # 모델 교체는 환경변수 하나 — 배포마다 코드 수정 없이
    monkeypatch.setenv("CLAW_ANTHROPIC_MODEL", "claude-sonnet-5")
    assert client.get("/api/llm/status").json()["model"] == "claude-sonnet-5"


def test_초안과_의도가_저장되고_메타에_모드_수가_실린다(client, wait_job, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    calls = {}

    def fake(*, api_key, model, system, user, schema):
        calls.update(api_key=api_key, model=model, system=system,
                     user=user, schema=schema)
        return _fake_raw(_DRAFT)

    # raising 기본값 유지 — call_anthropic이 개명되면 여기가 시끄럽게 죽어야
    # 테스트가 진짜 경로를 안 건드린 채 통과하는 일이 없다 (test_design 관례)
    monkeypatch.setattr(llm_route, "call_anthropic", fake)

    r = client.post("/api/llm/mission-draft", json={"intent": "북쪽 5 km 왕복"})
    assert r.status_code == 202, r.text
    assert r.headers["Location"].startswith("/api/jobs/")
    job = wait_job(r.json()["id"])
    assert job["status"] == "done", job

    body = client.get(f"/api/results/{job['result_id']}").json()
    assert body["kind"] == "mission_draft"
    assert body["draft"] == _DRAFT          # 그대로 — 서버는 의미 검증을 재구현하지 않는다
    assert body["intent"] == "북쪽 5 km 왕복"
    assert body["model"] == "claude-opus-5"
    assert body["usage"]["output_tokens"] == 20

    meta = next(m for m in client.get("/api/results").json()
                if m["id"] == job["result_id"])
    assert meta["kind"] == "mission_draft"
    assert meta["n"] == len(_DRAFT["modeRows"])
    assert meta["fingerprint"] == ""  # 초안은 형상 산출물이 아니다 — 계보 없음을 위장 금지

    assert calls["user"] == "북쪽 5 km 왕복"
    assert calls["api_key"] == "test-key"
    assert calls["model"] == "claude-opus-5"
    # 초안 경로는 초안 프롬프트·스키마로 부른다 — 브리핑과 갈리는 자리
    assert calls["system"] is llm_route._SYSTEM
    assert calls["schema"] is llm_route._DRAFT_SCHEMA


def test_나가는_요청은_계약_그대로다(client, wait_job, monkeypatch):
    """다른 테스트는 call_anthropic을 통째로 갈아끼우므로 그 **안쪽**(파라미터
    이름·헤더·스키마)이 틀려도 조용히 초록이 된다 — 여기서는 httpx 경계에서
    나가는 것을 통짜로 고정한다 (지킴이 없는 선언 금지 — 리뷰 지적).
    structured outputs 현행 이름은 output_config.format(GA, 베타 헤더 불요)이고
    output_format은 구명칭이다 — API가 또 바뀌면 이 테스트를 실측과 함께 고칠 것."""
    import httpx

    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    sent = {}

    class _Resp:
        status_code = 200

        def json(self):
            return _fake_raw(_DRAFT)

    def fake_post(url, *, timeout, headers, json):
        sent.update(url=url, timeout=timeout, headers=headers, body=json)
        return _Resp()

    # TestClient는 httpx.Client 인스턴스를 쓰므로 모듈 함수 httpx.post 교체와
    # 충돌하지 않는다 — 잡 스레드의 call_anthropic만 이 fake를 만난다
    monkeypatch.setattr(httpx, "post", fake_post)
    r = client.post("/api/llm/mission-draft", json={"intent": "계약 고정"})
    job = wait_job(r.json()["id"])
    assert job["status"] == "done", job

    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"]["x-api-key"] == "test-key"
    assert sent["headers"]["anthropic-version"] == "2023-06-01"
    body = sent["body"]
    assert body["model"] == "claude-opus-5"
    assert body["messages"] == [{"role": "user", "content": "계약 고정"}]
    assert body["system"] == llm_route._SYSTEM  # 초안 규약 프롬프트가 실제로 실린다
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] == llm_route._DRAFT_SCHEMA


def test_호출_중_취소는_cancelled로_남고_저장이_없다(client, wait_job, monkeypatch):
    """단발 호출인데도 보고를 두 번 하는 이유가 이 계약이다 — 보고가 없으면
    done==total==0이라 취소가 done으로 위장된다(jobs.py _run의 completed 판정).
    work의 이른-return 가드를 지우면 이 테스트가 잡는다 (지킴이 — 리뷰 지적)."""
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    gate = threading.Event()
    entered = threading.Event()

    def gated(*, api_key, model, system, user, schema):
        entered.set()
        assert gate.wait(timeout=30), "테스트 게이트 시간 초과"
        return _fake_raw(_DRAFT)

    monkeypatch.setattr(llm_route, "call_anthropic", gated)
    r = client.post("/api/llm/mission-draft", json={"intent": "취소 시험"})
    job_id = r.json()["id"]
    assert entered.wait(timeout=30)  # 호출 안에 들어간 뒤에
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    gate.set()  # 호출이 끝나 돌아온다 — 다음 report가 취소를 본다
    job = wait_job(job_id)
    assert job["status"] == "cancelled", job
    assert job["result_id"] is None
    # 취소된 초안은 저장되지 않는다 — 반쪽 결과 없음 (verify.py와 같은 규약)
    assert all(m["id"] != job_id for m in client.get("/api/results").json())


def test_프롬프트의_활주로_사실은_정본과_같다():
    """활주로 수치의 정본은 data/geo/goheung-runway.json이다(웹 lib/site.js도
    같은 대조 테스트를 갖는다). 시스템 프롬프트는 그 셋째 사본이라 낡아도
    아무것도 안 빨개지는 자리였다 — 여기서 빨개지게 만든다 (리뷰 지적)."""
    geo = json.loads((_REPO / "data/geo/goheung-runway.json").read_text())
    sys_prompt = llm_route._SYSTEM
    assert str(geo["heading_rad"]) in sys_prompt
    assert str(geo["threshold_south"]["lat_deg"]) in sys_prompt
    assert str(geo["threshold_south"]["lon_deg"]) in sys_prompt
    assert str(int(geo["length_m"])) in sys_prompt


def test_호출_실패는_잡_error와_사유로_남는다(client, wait_job, monkeypatch):
    """가장 흔한 실패(잘못된 키·요율 한계)가 침묵이 되면 안 된다."""
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "bad-key")

    def fake(*, api_key, model, system, user, schema):
        raise RuntimeError("Anthropic API 401 — invalid x-api-key")

    monkeypatch.setattr(llm_route, "call_anthropic", fake)
    r = client.post("/api/llm/mission-draft", json={"intent": "아무거나"})
    assert r.status_code == 202
    job = wait_job(r.json()["id"])
    assert job["status"] == "error"
    assert "401" in job["error"]


def test_모델_거절은_사유를_들어_실패한다(client, wait_job, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        llm_route, "call_anthropic",
        lambda **kw: {"content": [], "stop_reason": "refusal"})
    r = client.post("/api/llm/mission-draft", json={"intent": "아무거나"})
    job = wait_job(r.json()["id"])
    assert job["status"] == "error"
    assert "거절" in job["error"]


def test_빈_의도는_422(client, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    assert client.post("/api/llm/mission-draft",
                       json={"intent": ""}).status_code == 422
    # 공백만은 min_length를 통과한다 — 빈 의도로 실 API를 부르지 않는다
    assert client.post("/api/llm/mission-draft",
                       json={"intent": "   "}).status_code == 422


# ── 결과 브리핑 (/llm/brief) ──────────────────────────────────────────────

_BRIEF = {"headline": "격자 전 케이스 수렴 — 이상 없음",
          "body": "트림 배치 1케이스가 수렴했고 판정 플래그 위반이 없다.",
          "look_at": ["트림 탭 「케이스별 수치·판정」 패널"]}


def _seed(client, rid, kind, payload, fingerprint="deadbeefdeadbeef"):
    """저장소에 브리핑 대상 결과를 직접 심는다 — 라우트 경유 없이 (테스트 전용)."""
    client.app.state.store.save(
        rid, payload,
        meta={"kind": kind, "created": 1.0, "fingerprint": fingerprint, "n": 1})
    return rid


def test_소견서가_저장되고_부모와_지문을_잇는다(client, wait_job, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    # sim을 대상으로 — 가지치기(배제 마커)가 실제 경로에서 도는지도 여기서 본다
    rid = _seed(client, "simres01", "sim", {
        "kind": "sim",
        "t": list(range(10000)),
        "envelope": {"stall_margin": list(range(10000)), "worst_margin": 0.12},
        "meta": {"phases": {"touchdown_t": 96.9}},
    })
    calls = {}

    def fake(*, api_key, model, system, user, schema):
        calls.update(system=system, user=user, schema=schema)
        return _fake_raw(_BRIEF)

    monkeypatch.setattr(llm_route, "call_anthropic", fake)
    r = client.post("/api/llm/brief", json={"result_id": rid})
    assert r.status_code == 202, r.text
    job = wait_job(r.json()["id"])
    assert job["status"] == "done", job

    body = client.get(f"/api/results/{job['result_id']}").json()
    assert body["kind"] == "llm_brief"
    assert body["parent"] == rid
    assert body["parent_kind"] == "sim"
    assert body["headline"] == _BRIEF["headline"]
    assert body["look_at"] == _BRIEF["look_at"]

    meta = next(m for m in client.get("/api/results").json()
                if m["id"] == job["result_id"])
    assert meta["kind"] == "llm_brief"
    assert meta["parent"] == rid           # 어느 결과의 소견인지 목록에서 잇는다
    assert meta["fingerprint"] == "deadbeefdeadbeef"  # 대상의 지문 승계

    # 브리핑 경로는 브리핑 프롬프트·스키마로 부르고, 가지치기가 실제로 돌았다
    from claw_server.brief import BRIEF_SCHEMA, BRIEF_SYSTEM
    assert calls["system"] is BRIEF_SYSTEM
    assert calls["schema"] is BRIEF_SCHEMA
    assert "[제외" in calls["user"]          # sim 시계열이 마커로 대체됐다
    assert "worst_margin" in calls["user"]   # 판정 스칼라는 실렸다
    assert "deadbeefdeadbeef" in calls["user"]  # 메타 동봉
    assert len(calls["user"]) < 20_000       # 유계 — 시계열이 새면 여기서 터진다


def test_없는_결과의_소견서는_404(client, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    r = client.post("/api/llm/brief", json={"result_id": "nope404"})
    assert r.status_code == 404
    assert "결과 없음" in r.json()["detail"]


def test_소견서의_소견서는_만들지_않는다(client, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    rid = _seed(client, "briefres1", "llm_brief", {"kind": "llm_brief"})
    r = client.post("/api/llm/brief", json={"result_id": rid})
    assert r.status_code == 422
    assert "소견서" in r.json()["detail"]


def test_대상이_사라진_소견서는_사유로_실패한다(client, wait_job, monkeypatch):
    """제출 시점 메타 확인과 잡 안의 load 사이에 보존 상한이 대상을 밀어낼 수
    있다(레이스) — 트레이스백이 아니라 사유 문장이어야 한다 (리뷰 지적,
    design.py resume KeyError 선례)."""
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    rid = _seed(client, "gonesoon1", "trim_batch", {"kind": "trim_batch"})

    def vanished(_result_id):
        raise KeyError(_result_id)

    monkeypatch.setattr(client.app.state.store, "load", vanished)
    r = client.post("/api/llm/brief", json={"result_id": rid})
    assert r.status_code == 202
    job = wait_job(r.json()["id"])
    assert job["status"] == "error"
    assert "사라졌습니다" in job["error"]  # KeyError 원문이 아니라 사유 문장
    assert "보존 상한" in job["error"]


def test_소견서도_키가_없으면_503(client):
    r = client.post("/api/llm/brief", json={"result_id": "whatever1"})
    assert r.status_code == 503
    assert "CLAW_ANTHROPIC_API_KEY" in r.json()["detail"]


# ── 교신 대본 (/llm/comms) ────────────────────────────────────────────────

_COMMS = {"lines": [
    {"t": 0.5, "speaker": "TOWER", "text": "CLAW-01, 이륙을 허가한다"},
    {"t": 79.0, "speaker": "UAV", "text": "고흥 타워, CLAW-01 접지"},
], "warnings": []}


def _seed_sim(client, rid="simcomms1"):
    n = 100
    return _seed(client, rid, "sim", {
        "kind": "sim",
        "t": [i * 0.5 for i in range(n)],
        "signals": {"mode": ["launch"] * 10 + ["cruise"] * 90,
                    "h": [100.0] * n, "V": [88.0] * n},
        "envelope": {"min_alt": 0.5, "min_alt_t": 40.0},
        "meta": {"case": "c1", "t_end": 49.5,
                 "phases": {"launch_exit_t": 0.5, "touchdown_t": None,
                            "stop_t": None, "td_sink_rate": None,
                            "td_speed": None}},
        "n_total": n,
    })


def test_교신_대본이_저장되고_비행_로그가_유계다(client, wait_job, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    rid = _seed_sim(client)
    calls = {}

    def fake(*, api_key, model, system, user, schema):
        calls.update(system=system, user=user, schema=schema)
        return _fake_raw(_COMMS)

    monkeypatch.setattr(llm_route, "call_anthropic", fake)
    r = client.post("/api/llm/comms", json={"result_id": rid})
    assert r.status_code == 202, r.text
    job = wait_job(r.json()["id"])
    assert job["status"] == "done", job

    body = client.get(f"/api/results/{job['result_id']}").json()
    assert body["kind"] == "llm_comms"
    assert body["parent"] == rid
    assert body["parent_kind"] == "sim"
    assert body["lines"] == _COMMS["lines"]

    meta = next(m for m in client.get("/api/results").json()
                if m["id"] == job["result_id"])
    assert meta["kind"] == "llm_comms"
    assert meta["parent"] == rid
    assert meta["n"] == 2  # 대본 줄 수

    from claw_server.comms import COMMS_SCHEMA, COMMS_SYSTEM
    assert calls["system"] is COMMS_SYSTEM
    assert calls["schema"] is COMMS_SCHEMA
    assert "launch → cruise" in calls["user"]  # 비행 로그가 실제로 실렸다
    assert len(calls["user"]) < 10_000         # 유계 — 시계열이 새면 여기서 터진다


def test_sim이_아닌_결과의_교신_대본은_거부한다(client, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    rid = _seed(client, "notasim1", "trim_batch", {"kind": "trim_batch"})
    r = client.post("/api/llm/comms", json={"result_id": rid})
    assert r.status_code == 422
    assert "sim 결과가 아님" in r.json()["detail"]


def test_교신_대본도_키가_없으면_503(client):
    r = client.post("/api/llm/comms", json={"result_id": "whatever1"})
    assert r.status_code == 503
    assert "CLAW_ANTHROPIC_API_KEY" in r.json()["detail"]


def test_상태_조회는_바깥으로_나가지_않는다(client, monkeypatch):
    """아웃바운드는 생성 잡의 call_anthropic 하나뿐이어야 한다 — 상태 조회가
    키 검증 등으로 나가기 시작하면 폐쇄망에서 탭을 여는 것만으로 걸린다
    (test_world의 소켓 차단 관용구 — client 픽스처가 포털을 먼저 세운 뒤라 안전)."""
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")

    def explode(*a, **k):
        raise AssertionError("서버가 바깥으로 나갔다")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "getaddrinfo", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    assert client.get("/api/llm/status").status_code == 200
