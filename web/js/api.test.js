// api 래퍼 검증 — 응답 파싱, ApiError 매핑, 422 detail 포맷 (node --test, fetch 모킹)
import { test } from "node:test";
import assert from "node:assert/strict";

const { api, ApiError, errorText, TERMINAL } = await import("./api.js");

function mockFetch(status, body) {
  globalThis.fetch = async (url, opts) => {
    mockFetch.last = { url, opts };
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => (body === undefined ? "" : JSON.stringify(body)),
    };
  };
}

test("get: JSON 파싱·경로 결합", async () => {
  mockFetch(200, { status: "ok", jobs: 0 });
  const r = await api.get("/health");
  assert.deepEqual(r, { status: "ok", jobs: 0 });
  assert.equal(mockFetch.last.url, "/api/health");
});

test("post: 본문 직렬화 + content-type", async () => {
  mockFetch(202, { id: "j1" });
  const r = await api.post("/trim/batch", { cases: [] });
  assert.equal(r.id, "j1");
  assert.equal(mockFetch.last.opts.method, "POST");
  assert.equal(mockFetch.last.opts.headers["content-type"], "application/json");
  assert.equal(mockFetch.last.opts.body, '{"cases":[]}');
});

test("오류 응답 → ApiError(detail 추출)", async () => {
  mockFetch(404, { detail: "결과 없음: nope" });
  await assert.rejects(api.get("/results/nope"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 404);
    assert.equal(err.detail, "결과 없음: nope");
    return true;
  });
});

test("빈 본문 응답은 null", async () => {
  mockFetch(200, undefined);
  assert.equal(await api.get("/x"), null);
});

test("errorText: pydantic 422 배열 → 줄단위 요약", () => {
  const err = new ApiError(422, [
    { loc: ["body", "cases", 0, "mach"], msg: "Input should be greater than 0" },
    { loc: ["body", "t_end"], msg: "필수" },
  ]);
  assert.equal(
    errorText(err),
    "body.cases.0.mach: Input should be greater than 0\nbody.t_end: 필수"
  );
  assert.equal(errorText(new ApiError(500, "서버 오류")), "서버 오류");
  assert.equal(errorText(new Error("일반 오류")), "Error: 일반 오류");
});

test("TERMINAL 상태 집합", () => {
  assert.deepEqual([...TERMINAL].sort(), ["cancelled", "done", "error"]);
});

test("고른 기체가 계산 요청에만 실린다 — 규칙은 lib/profile.js", async () => {
  const { setSelection } = await import("./lib/profile.js");
  setSelection({ id: "heavy-delta", variant: "full-stores" });
  try {
    mockFetch(202, { id: "j1" });
    await api.post("/trim/batch", { cases: [] });
    assert.deepEqual(JSON.parse(mockFetch.last.opts.body),
      { cases: [], profile: { id: "heavy-delta", variant: "full-stores" } });
    mockFetch(200, {});
    await api.get("/analysis/vn-envelope?alt=1000");
    assert.equal(mockFetch.last.url,
      "/api/analysis/vn-envelope?alt=1000&profile_id=heavy-delta&profile_variant=full-stores");
    await api.get("/results");
    assert.equal(mockFetch.last.url, "/api/results");
    await api.put("/profiles/heavy-delta", { base_revision: 1, document: {} });
    assert.equal(mockFetch.last.opts.method, "PUT");
    assert.deepEqual(JSON.parse(mockFetch.last.opts.body), { base_revision: 1, document: {} });
    mockFetch(204, undefined);
    assert.equal(await api.del("/profiles/heavy-delta"), null);
    assert.equal(mockFetch.last.opts.method, "DELETE");
  } finally {
    setSelection(null);
  }
});

test("401 → claw:auth-required 발화 (로그인 게이트 재소환), /auth/*와 로그인 실패는 제외", async () => {
  const fired = [];
  globalThis.window = { dispatchEvent: (ev) => fired.push(ev) };
  globalThis.CustomEvent ??= class { constructor(type, opts) { this.type = type; this.detail = opts?.detail; } };
  try {
    mockFetch(401, { detail: "인증 필요" });
    await assert.rejects(api.get("/jobs"), ApiError);
    assert.equal(fired.length, 1);
    assert.equal(fired[0].type, "claw:auth-required");
    assert.equal(fired[0].detail.path, "/jobs");
    // 로그인 실패 401이 게이트를 다시 세우면 재귀 — /auth/*는 조용히 던지기만
    await assert.rejects(api.post("/auth/login", { username: "a", password: "b" }), ApiError);
    assert.equal(fired.length, 1);
    // 401이 아닌 실패는 발화하지 않는다
    mockFetch(403, { detail: "관리자 전용" });
    await assert.rejects(api.get("/admin/users"), ApiError);
    assert.equal(fired.length, 1);
  } finally {
    delete globalThis.window;
  }
});
