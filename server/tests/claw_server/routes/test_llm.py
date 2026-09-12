"""LLM 라우트 (미션 초안·브리핑·교신·질문) — 202 잡·degrade·백엔드 선택 계약.

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

import pytest

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
    assert body["backend"] is None
    assert "CLAW_ANTHROPIC_API_KEY" in body["reason"]  # 사유에 복구 열쇠 이름
    assert "CLAW_LLM_BASE_URL" in body["reason"]       # 폐쇄망 경로도 함께 안내

    r = client.post("/api/llm/mission-draft", json={"intent": "북쪽으로 5 km"})
    assert r.status_code == 503
    assert "CLAW_ANTHROPIC_API_KEY" in r.json()["detail"]


def test_키가_있으면_상태가_모델을_말한다(client, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    body = client.get("/api/llm/status").json()
    assert body["available"] is True
    assert body["model"] == "claude-opus-5"  # 기본 모델
    assert body["backend"] == "anthropic"
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

    # raising 기본값 유지 — call_llm이 개명되면 여기가 시끄럽게 죽어야
    # 테스트가 진짜 경로를 안 건드린 채 통과하는 일이 없다 (test_design 관례)
    monkeypatch.setattr(llm_route, "call_llm", fake)

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
    """다른 테스트는 call_llm을 통째로 갈아끼우므로 그 **안쪽**(파라미터
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
    # 충돌하지 않는다 — 잡 스레드의 call_llm(_post_anthropic)만 이 fake를 만난다
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

    monkeypatch.setattr(llm_route, "call_llm", gated)
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

    monkeypatch.setattr(llm_route, "call_llm", fake)
    r = client.post("/api/llm/mission-draft", json={"intent": "아무거나"})
    assert r.status_code == 202
    job = wait_job(r.json()["id"])
    assert job["status"] == "error"
    assert "401" in job["error"]


def test_모델_거절은_사유를_들어_실패한다(client, wait_job, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        llm_route, "call_llm",
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

    monkeypatch.setattr(llm_route, "call_llm", fake)
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

    monkeypatch.setattr(llm_route, "call_llm", fake)
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


# ── 전역 질문 (/llm/ask) ──────────────────────────────────────────────────

_ANSWER = {"answer": "마진 맵 탭 히트맵에서 봅니다 — 칸을 누르면 보드선도까지.",
           "actions": [{"view": "margins", "sub": "", "label": "마진 맵",
                        "why": "PM·GM 히트맵이 전면이다"}]}


def test_문답이_저장되고_산출물_메타가_동봉된다(client, wait_job, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    _seed(client, "askmeta01", "margin_map", {"kind": "margin_map"})  # 실재 근거
    calls = {}

    def fake(*, api_key, model, system, user, schema):
        calls.update(system=system, user=user, schema=schema)
        return _fake_raw(_ANSWER)

    monkeypatch.setattr(llm_route, "call_llm", fake)
    r = client.post("/api/llm/ask", json={"question": "실속 마진은 어디서 봐?"})
    assert r.status_code == 202, r.text
    job = wait_job(r.json()["id"])
    assert job["status"] == "done", job

    body = client.get(f"/api/results/{job['result_id']}").json()
    assert body["kind"] == "llm_ask"
    assert body["question"] == "실속 마진은 어디서 봐?"
    assert body["answer"] == _ANSWER["answer"]
    assert body["actions"] == _ANSWER["actions"]

    meta = next(m for m in client.get("/api/results").json()
                if m["id"] == job["result_id"])
    assert meta["kind"] == "llm_ask"
    assert meta["n"] == 1  # 액션 수

    from claw_server.ask import ASK_SCHEMA, ASK_SYSTEM
    assert calls["system"] is ASK_SYSTEM
    assert calls["schema"] is ASK_SCHEMA
    assert "실속 마진은 어디서 봐?" in calls["user"]
    assert "margin_map" in calls["user"]      # 메타가 실재 근거로 실렸다
    assert len(calls["user"]) < 20_000        # 유계 — 메타는 머리 30건뿐


def test_문답_메타는_최신_30건만_동봉된다(client, wait_job, monkeypatch):
    """유계가 이 엔드포인트의 명시 설계다 — 상한을 지우면 산출물이 쌓인 배포
    (개발 서버 실측 232건)에서 프롬프트가 통짜 목록이 된다. 한 건 시딩으로는
    슬라이스를 지워도 초록이라(리뷰 지적) 35건을 심어 개수를 센다."""
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    store = client.app.state.store
    for i in range(35):
        store.save(f"askcap{i:02d}", {"kind": "trim_batch"},
                   meta={"kind": "trim_batch", "created": float(i),
                         "fingerprint": "", "n": 1})
    calls = {}

    def fake(*, api_key, model, system, user, schema):
        calls.update(user=user)
        return _fake_raw(_ANSWER)

    monkeypatch.setattr(llm_route, "call_llm", fake)
    r = client.post("/api/llm/ask", json={"question": "뭐 돌렸어?"})
    job = wait_job(r.json()["id"])
    assert job["status"] == "done", job
    assert calls["user"].count("askcap") == 30
    assert "askcap34" in calls["user"]   # 최신은 실린다 (created 내림차순)
    assert "askcap04" not in calls["user"]  # 머리 밖은 빠진다


def test_빈_질문과_공백_질문은_422(client, monkeypatch):
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    assert client.post("/api/llm/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/llm/ask", json={"question": "  "}).status_code == 422


def test_문답도_키가_없으면_503(client):
    r = client.post("/api/llm/ask", json={"question": "아무거나"})
    assert r.status_code == 503
    assert "CLAW_ANTHROPIC_API_KEY" in r.json()["detail"]


def test_상태_조회는_바깥으로_나가지_않는다(client, monkeypatch):
    """아웃바운드는 생성 잡의 call_llm 하나뿐이어야 한다 — 상태 조회가
    키 검증 등으로 나가기 시작하면 폐쇄망에서 탭을 여는 것만으로 걸린다
    (test_world의 소켓 차단 관용구 — client 픽스처가 포털을 먼저 세운 뒤라 안전)."""
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")

    def explode(*a, **k):
        raise AssertionError("서버가 바깥으로 나갔다")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "getaddrinfo", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    assert client.get("/api/llm/status").status_code == 200


# ── 로컬 백엔드 (OpenAI 호환 — 폐쇄망 사내 서버) ─────────────────────────


def _fake_raw_openai(draft):
    """OpenAI 호환(/chat/completions) 원시 응답의 최소 재현."""
    return {
        "choices": [{"message": {"role": "assistant",
                                 "content": json.dumps(draft, ensure_ascii=False)},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


def test_백엔드_선택은_설정_존재로_정해진다(client, monkeypatch):
    """명시 스위치가 없다 — "스위치=로컬인데 URL 없음" 같은 모순 상태가 표현
    자체가 안 되게(존재 = 옵트인, CLAW_ 접두 철학의 연장). BASE_URL 존재는
    로컬 **커밋**이라 Anthropic 키가 있어도 폴백하지 않는다 — 폐쇄망 의도
    구성이 조용히 밖으로 나가는 사고 차단."""
    # anthropic만
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "k")
    body = client.get("/api/llm/status").json()
    assert body["available"] is True and body["backend"] == "anthropic"
    # 둘 다 — 로컬이 이긴다
    monkeypatch.setenv("CLAW_LLM_BASE_URL", "http://box:8000/v1")
    monkeypatch.setenv("CLAW_LLM_MODEL", "qwen3-32b")
    body = client.get("/api/llm/status").json()
    assert body["backend"] == "openai" and body["model"] == "qwen3-32b"
    # URL만 있고 모델 없음 — 키가 있어도 불가용, 사유가 빠진 변수를 지목
    monkeypatch.delenv("CLAW_LLM_MODEL")
    body = client.get("/api/llm/status").json()
    assert body["available"] is False and body["backend"] == "openai"
    assert "CLAW_LLM_MODEL" in body["reason"]
    r = client.post("/api/llm/ask", json={"question": "?"})
    assert r.status_code == 503
    assert "CLAW_LLM_MODEL" in r.json()["detail"]
    # 로컬만 (키 없음) — 폐쇄망의 정상 구성
    monkeypatch.delenv("CLAW_ANTHROPIC_API_KEY")
    monkeypatch.setenv("CLAW_LLM_MODEL", "qwen3-32b")
    body = client.get("/api/llm/status").json()
    assert body["available"] is True and body["backend"] == "openai"
    assert body["reason"] is None


def test_로컬_백엔드로_나가는_요청은_계약_그대로다(client, wait_job, monkeypatch):
    """와이어 골든의 로컬판 — 존재 이유는 Anthropic 골든과 같다(대부분의
    테스트가 call_llm을 통째로 갈아끼우므로 그 경계 안쪽이 틀려도 조용히
    초록). 구조화 출력은 response_format.json_schema(strict) — 이 필드를
    무시하는 서버·모델이면 응답이 산문이 되고, JSON 가드가 사유로 잡는다."""
    import httpx

    monkeypatch.setenv("CLAW_LLM_BASE_URL", "http://10.0.0.5:8000/v1/")  # 꼬리 / 허용
    monkeypatch.setenv("CLAW_LLM_MODEL", "qwen3-32b")
    sent = {}

    class _Resp:
        status_code = 200

        def json(self):
            return _fake_raw_openai(_DRAFT)

    def fake_post(url, *, timeout, headers, json):
        sent.update(url=url, timeout=timeout, headers=headers, body=json)
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    r = client.post("/api/llm/mission-draft", json={"intent": "계약 고정"})
    job = wait_job(r.json()["id"])
    assert job["status"] == "done", job

    assert sent["url"] == "http://10.0.0.5:8000/v1/chat/completions"
    # 키 없음 = 인증 헤더 자체가 없다 (빈 Bearer는 게이트웨이가 401을 낸다)
    assert not any(k.lower() == "authorization" for k in sent["headers"])
    body = sent["body"]
    assert body["model"] == "qwen3-32b"
    assert body["messages"] == [
        {"role": "system", "content": llm_route._SYSTEM},  # system은 첫 메시지로
        {"role": "user", "content": "계약 고정"},
    ]
    js = body["response_format"]
    assert js["type"] == "json_schema"
    assert js["json_schema"]["strict"] is True
    assert js["json_schema"]["schema"] == llm_route._DRAFT_SCHEMA


def test_로컬_응답은_내부_계약으로_정규화된다(client, wait_job, monkeypatch):
    """라우트·저장 형상은 백엔드를 모른다 — usage 키(prompt_tokens ↔
    input_tokens)까지 옮겨져야 저장 형상이 백엔드마다 갈리지 않는다(설계
    조사가 찾은 유일한 누수 지점). 키가 있으면 Bearer가 실린다."""
    import httpx

    monkeypatch.setenv("CLAW_LLM_BASE_URL", "http://box/v1")
    monkeypatch.setenv("CLAW_LLM_MODEL", "m1")
    monkeypatch.setenv("CLAW_LLM_API_KEY", "gw-token")
    sent = {}

    class _Resp:
        status_code = 200

        def json(self):
            return _fake_raw_openai(_DRAFT)

    def fake_post(url, *, timeout, headers, json):
        sent.update(headers=headers)
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    r = client.post("/api/llm/mission-draft", json={"intent": "정규화"})
    job = wait_job(r.json()["id"])
    assert job["status"] == "done", job
    body = client.get(f"/api/results/{job['result_id']}").json()
    assert body["draft"] == _DRAFT
    assert body["model"] == "m1"
    assert body["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert sent["headers"]["authorization"] == "Bearer gw-token"


def test_로컬_거절도_같은_사유로_실패한다(client, wait_job, monkeypatch):
    """content_filter → refusal 매핑 — 거절이 백엔드와 무관하게 한 문장으로
    나온다 (_to_anthropic_shape)."""
    import httpx

    monkeypatch.setenv("CLAW_LLM_BASE_URL", "http://box/v1")
    monkeypatch.setenv("CLAW_LLM_MODEL", "m1")

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": ""},
                                 "finish_reason": "content_filter"}],
                    "usage": {}}

    monkeypatch.setattr(httpx, "post",
                        lambda url, *, timeout, headers, json: _Resp())
    r = client.post("/api/llm/mission-draft", json={"intent": "아무거나"})
    job = wait_job(r.json()["id"])
    assert job["status"] == "error"
    assert "거절" in job["error"]


def test_json_가드는_펜스를_벗기고_산문은_사유로_실패시킨다():
    """구조화 출력 강제가 약한 로컬 모델의 1차 방어선 — 실패가 파이썬
    트레이스백이 아니라 사유 문장이어야 한다 (조용한 실패 금지 — 이 파일에서
    유일하게 규약 밖이던 자리)."""
    fenced = {"content": [{"type": "text",
                           "text": "```json\n{\"a\": 1}\n```"}],
              "stop_reason": "end_turn"}
    assert llm_route._extract_json(fenced) == {"a": 1}
    prose = {"content": [{"type": "text",
                          "text": "네, 알겠습니다. 요청하신 JSON은 다음과 같습니다"}],
             "stop_reason": "end_turn"}
    with pytest.raises(RuntimeError, match="JSON이 아닙니다"):
        llm_route._extract_json(prose)


def test_정규화는_stop_reason_어휘까지_하나로_만든다():
    """반만 옮기면(content_filter만) stop_reason을 보는 분기가 로컬 백엔드에서만
    조용히 빠진다 — 잘림 판정(아래)이 바로 그 소비자다."""
    def shape(finish):
        return llm_route._to_anthropic_shape(
            {"choices": [{"message": {"content": "{}"},
                          "finish_reason": finish}]})["stop_reason"]
    assert shape("stop") == "end_turn"
    assert shape("length") == "max_tokens"
    assert shape("content_filter") == "refusal"


def test_잘린_출력은_토큰_상한_사유로_실패한다(client, wait_job, monkeypatch):
    """finish_reason "length"로 잘린 JSON을 "모델 응답이 JSON이 아닙니다"로
    오진하지 않는다 — 처방(입력 축소)이 다르다. Anthropic의 stop_reason
    "max_tokens"도 같은 판정을 탄다(어휘 정규화가 술어를 하나로 만든다)."""
    import httpx

    monkeypatch.setenv("CLAW_LLM_BASE_URL", "http://box/v1")
    monkeypatch.setenv("CLAW_LLM_MODEL", "m1")

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "{\"summary\": \"잘렸"},
                                 "finish_reason": "length"}],
                    "usage": {}}

    monkeypatch.setattr(httpx, "post",
                        lambda url, *, timeout, headers, json: _Resp())
    r = client.post("/api/llm/mission-draft", json={"intent": "긴 미션"})
    job = wait_job(r.json()["id"])
    assert job["status"] == "error"
    assert "토큰 상한" in job["error"]


def test_대본이_스키마를_어기면_사유로_실패한다(client, wait_job, monkeypatch):
    """초안·문답과 달리 대본에는 웹 정규화가 없다 — 서버(validate_lines)가
    마지막 방어선이다. 어긴 값이 저장되면 그대로 자막·발화로 흐른다."""
    monkeypatch.setenv("CLAW_ANTHROPIC_API_KEY", "test-key")
    rid = _seed_sim(client, "simbad001")
    bad = {"lines": [{"t": "0.5", "speaker": "TOWER", "text": "t가 문자열"}],
           "warnings": []}
    monkeypatch.setattr(llm_route, "call_llm", lambda **kw: _fake_raw(bad))
    job = wait_job(client.post("/api/llm/comms",
                               json={"result_id": rid}).json()["id"])
    assert job["status"] == "error"
    assert "유한한 수" in job["error"]

    bad2 = {"lines": [{"t": 1.0, "speaker": "PILOT", "text": "x"}],
            "warnings": []}
    monkeypatch.setattr(llm_route, "call_llm", lambda **kw: _fake_raw(bad2))
    job = wait_job(client.post("/api/llm/comms",
                               json={"result_id": rid}).json()["id"])
    assert job["status"] == "error"
    assert "PILOT" in job["error"]
