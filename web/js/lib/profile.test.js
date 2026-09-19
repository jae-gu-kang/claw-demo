// 기체 선택 규칙 — 저장값 정규화·요청 주입·서버 라우트 분류 가드 (node --test, 의존 0)
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  COMPUTE_GET, COMPUTE_POST, EXAMPLE_ID, NOT_AIRCRAFT, STORAGE_KEY,
  currentSelection, loadSelection, normalizeSelection, profileRef, sameSelection, saveSelection,
  selectionProblem, setSelection, withProfile,
} from "./profile.js";

const fakeStorage = (init = {}) => {
  const m = new Map(Object.entries(init));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    m,
  };
};
const brokenStorage = {
  getItem() { throw new Error("SecurityError"); },
  setItem() { throw new Error("QuotaExceededError"); },
  removeItem() { throw new Error("SecurityError"); },
};

test("선택 정규화 — 모양이 틀린 값은 버린다 (손상된 저장값이 요청을 망치지 않게)", () => {
  assert.deepEqual(normalizeSelection({ id: "heavy-delta" }), { id: "heavy-delta", variant: null });
  assert.deepEqual(normalizeSelection({ id: "a", variant: "full-stores" }), { id: "a", variant: "full-stores" });
  for (const bad of [null, "a", [], {}, { id: "" }, { id: "../x" }, { id: 3 }, { id: "a".repeat(65) }]) {
    assert.equal(normalizeSelection(bad), null, JSON.stringify(bad));
  }
  assert.deepEqual(normalizeSelection({ id: "a", variant: "no/slash" }), { id: "a", variant: null });
});

test("저장·읽기 왕복 — 손상·막힌 저장소는 null이고, 못 쓰면 false로 말한다", () => {
  const s = fakeStorage();
  assert.equal(saveSelection(s, { id: "heavy-delta", variant: "v1" }), true);
  assert.deepEqual(loadSelection(s), { id: "heavy-delta", variant: "v1" });
  assert.equal(saveSelection(s, null), true);
  assert.equal(s.m.has(STORAGE_KEY), false);
  assert.equal(loadSelection(fakeStorage({ [STORAGE_KEY]: "{not json" })), null);
  assert.equal(loadSelection(fakeStorage({ [STORAGE_KEY]: '{"id":"../etc"}' })), null);
  assert.equal(loadSelection(brokenStorage), null);
  assert.equal(loadSelection(null), null);
  assert.equal(saveSelection(brokenStorage, { id: "a" }), false);
});

test("선택이 없으면 요청을 건드리지 않는다 — 서버가 예제 기체로 계산하고 그렇다고 말한다", () => {
  const body = { cases: [] };
  assert.deepEqual(withProfile("POST", "/trim/batch", body, null), { path: "/trim/batch", body });
  assert.deepEqual(withProfile("GET", "/gains/catalog", undefined, null), { path: "/gains/catalog", body: undefined });
});

test("POST 계산 라우트 본문에만 싣는다 — 이미 실은 profile·배열·비계산 라우트는 두고, 원본은 안 고친다", () => {
  const sel = { id: "heavy-delta", variant: "full-stores" };
  const body = { cases: [1] };
  const out = withProfile("POST", "/trim/batch", body, sel);
  assert.deepEqual(out.body, { cases: [1], profile: { id: "heavy-delta", variant: "full-stores" } });
  assert.equal("profile" in body, false);
  const own = { profile: { id: EXAMPLE_ID } };
  assert.equal(withProfile("POST", "/sim/run", own, sel).body, own);
  assert.deepEqual(withProfile("POST", "/results", { a: 1 }, sel).body, { a: 1 });
  assert.deepEqual(withProfile("POST", "/llm/ask", { question: "q" }, sel).body, { question: "q" });
  assert.deepEqual(withProfile("PUT", "/trim/batch", { a: 1 }, sel).body, { a: 1 });
  assert.deepEqual(withProfile("POST", "/trim/batch", [1], sel).body, [1]);
  // 키만 있고 값이 undefined면 JSON에서 사라진다 — 실은 것으로 치면 서버가 조용히 예제로 계산한다
  assert.deepEqual(withProfile("POST", "/trim/batch", { cases: [], profile: undefined }, sel).body.profile,
    { id: "heavy-delta", variant: "full-stores" });
  // 형상 변형이 없으면 variant 키 자체를 싣지 않는다
  assert.deepEqual(withProfile("POST", "/design/auto", {}, { id: "a" }).body, { profile: { id: "a" } });
});

test("GET 계산 라우트는 쿼리로 — 기존 쿼리 뒤에 붙이고, 이미 있으면 두고, 인코딩한다", () => {
  const sel = { id: "heavy-delta", variant: "full-stores" };
  assert.equal(withProfile("GET", "/analysis/vn-envelope?alt=1000&fuel=200", undefined, sel).path,
    "/analysis/vn-envelope?alt=1000&fuel=200&profile_id=heavy-delta&profile_variant=full-stores");
  assert.equal(withProfile("GET", "/gains/catalog", undefined, { id: "a_b" }).path,
    "/gains/catalog?profile_id=a_b");
  assert.equal(withProfile("GET", "/gains/catalog?", undefined, { id: "a" }).path, "/gains/catalog?profile_id=a");
  const pinned = "/analysis/design-envelope?profile_id=other&alt=1";
  assert.equal(withProfile("GET", pinned, undefined, sel).path, pinned);
  assert.equal(withProfile("GET", "/results/abc", undefined, sel).path, "/results/abc");
});

test("현재 선택 — set/get과 요청용 ref·같은 선택 대조", () => {
  try {
    assert.deepEqual(setSelection({ id: "a", variant: "v" }), { id: "a", variant: "v" });
    assert.deepEqual(currentSelection(), { id: "a", variant: "v" });
    assert.deepEqual(profileRef(), { id: "a", variant: "v" });
    assert.equal(setSelection("garbage"), null);
    assert.equal(profileRef(), null);
    assert.ok(sameSelection({ id: "a" }, { id: "a", variant: null }));
    assert.ok(!sameSelection({ id: "a" }, { id: "a", variant: "v" }));
    assert.ok(sameSelection(null, undefined));
  } finally {
    setSelection(null);
  }
});

test("저장된 선택이 목록에서 사라진 사유", () => {
  const list = [
    { id: EXAMPLE_ID, name: "예제 델타윙", variants: [] },
    { id: "heavy-delta", name: "무거운 델타", variants: [{ id: "full-stores", name: "외장 만재" }] },
    { id: "broken", unreadable: true, reason: "head를 읽을 수 없다" },
  ];
  assert.equal(selectionProblem(list, null), null);
  assert.equal(selectionProblem(list, { id: "heavy-delta", variant: "full-stores" }), null);
  assert.match(selectionProblem(list, { id: "gone" }), /서버에 없습니다/);
  assert.match(selectionProblem(list, { id: "broken" }), /읽을 수 없습니다/);
  assert.match(selectionProblem(list, { id: "heavy-delta", variant: "nope" }), /형상 변형/);
});

// 서버 라우트 전부를 원문에서 읽어 대조한다(blocks.test.js가 index.html·main.js를 읽는 방식).
// 사본 목록을 두는 대가 — 서버에 계산 라우트가 생겼는데 여기 없으면, 웹은 기체를 싣지 않고
// 서버는 예제 기체로 계산해 **선택한 기체의 이름 없이 조용히** 틀린다
test("서버 라우트 전부가 분류돼 있다 — 기체를 받는 라우트 ↔ COMPUTE_*, 나머지 ↔ NOT_AIRCRAFT", () => {
  // withProfile은 실제 경로를 **그대로** 대조한다 — 경로 매개변수 템플릿은 영영 안 맞아 조용히 빠진다
  for (const p of [...COMPUTE_POST, ...COMPUTE_GET]) {
    assert.ok(!p.includes("{"), `${p}: 경로 매개변수가 있는 계산 라우트는 withProfile이 못 맞춘다 — 대조 방식을 먼저 바꿀 것`);
  }
  const server = new URL("../../../server/claw_server/", import.meta.url);
  assert.ok(!/@app\.(get|post|put|delete|patch|api_route)\(/.test(readFileSync(new URL("app.py", server), "utf8")),
    "app.py에 라우트가 생겼다 — 이 가드는 routes/*.py만 읽는다");
  const dir = new URL("routes/", server);
  const seen = new Set();
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".py"))) {
    const text = readFileSync(new URL(file, dir), "utf8");
    const heads = [...text.matchAll(/@router\.(get|post|put|patch|delete)\("([^"]+)"/g)];
    // 가드가 못 읽는 선언(여러 줄·작은따옴표·api_route)은 조용히 건너뛰지 않고 빨개진다 (websocket만 예외)
    const declared = [...text.matchAll(/@router\.(\w+)\(/g)].filter((m) => m[1] !== "websocket");
    assert.equal(declared.length, heads.length, `${file}: 해석하지 못한 라우트 선언이 있다 — 한 줄·큰따옴표 get/post/put/patch/delete로 쓸 것`);
    heads.forEach((m, i) => {
      const method = m[1].toUpperCase();
      const path = m[2];
      const key = `${method} ${path}`;
      const segment = text.slice(m.index, heads[i + 1]?.index ?? text.length);
      const compute = (method === "POST" && COMPUTE_POST.has(path))
        || (method === "GET" && COMPUTE_GET.has(path));
      const exempt = Object.hasOwn(NOT_AIRCRAFT, key);
      assert.ok(compute !== exempt, `${file} ${key}: 기체를 싣는 라우트(COMPUTE_*)와 기체 무관(NOT_AIRCRAFT) 중 정확히 하나로 분류할 것`);
      const readsProfile = /\bresolve_profile\(|\bprofile_query\b/.test(segment);
      if (compute) {
        assert.ok(readsProfile, `${file} ${key}: 웹이 기체를 싣는데 서버가 읽지 않는다`);
      } else {
        assert.ok(!readsProfile, `${file} ${key}: 서버가 기체를 받는데 웹이 싣지 않는다 — 조용히 예제 기체로 계산된다`);
        assert.ok(typeof NOT_AIRCRAFT[key] === "string" && NOT_AIRCRAFT[key].length > 0, `${key}: 사유가 비었다`);
      }
      seen.add(key);
    });
  }
  assert.ok(seen.size > 30, `서버 라우트 ${seen.size}개 — 원문 파싱 실패?`);
  const stale = [
    ...[...COMPUTE_POST].map((p) => `POST ${p}`),
    ...[...COMPUTE_GET].map((p) => `GET ${p}`),
    ...Object.keys(NOT_AIRCRAFT),
  ].filter((k) => !seen.has(k));
  assert.deepEqual(stale, [], "서버에 없는 라우트가 목록에 남았다");
});

test("복제·편집기 글·서버 오류 문구 — 기체 탭의 판단", async () => {
  const { cloneDocument, exportFileName, parseDocumentText, profileErrorText } = await import("./profile.js");
  const src = { id: EXAMPLE_ID, name: "예제 델타윙", description: "예제", is_example: true,
    mass: { m_empty: 800 }, variants: [{ id: "v", name: "변형", patch: {} }] };
  const c = cloneDocument(src, { id: "my-delta", name: "내 델타" });
  assert.deepEqual([c.id, c.name, c.is_example], ["my-delta", "내 델타", false]);
  assert.match(c.description, /example-delta/);
  c.mass.m_empty = 900;
  assert.equal(src.mass.m_empty, 800, "원본을 고치면 안 된다");
  assert.deepEqual(c.variants, src.variants);

  assert.deepEqual(parseDocumentText('{"id":"a"}'), { doc: { id: "a" }, error: null });
  assert.match(parseDocumentText("{id: a}").error, /JSON이 아닙니다/);
  assert.match(parseDocumentText("[1]").error, /객체/);
  assert.match(parseDocumentText("null").error, /객체/);

  assert.equal(profileErrorText({ path: "/mass/m_empty", message: "양수여야 함" }), "/mass/m_empty: 양수여야 함");
  assert.equal(profileErrorText({ path: "", message: "객체가 아니다" }), "객체가 아니다");
  assert.equal(profileErrorText("문자열 detail"), null);
  assert.equal(profileErrorText([{ loc: ["body"], msg: "x" }]), null);
  assert.equal(exportFileName("my-delta", 3), "my-delta-rev3.json");
});

// 가상환경 번들(web/world)은 빌드가 js/api.js를 **자기 안에 복사**한다 — 그 사본의 lib/profile.js 선택은
// main.js가 채우지 않으므로, 그 번들이 계산 라우트를 부르면 조용히 예제 기체로 계산된다. 지금은 저장
// 결과·재생·자산만 부른다. 부르게 되는 날 이 가드가 선택을 넘기는 길부터 만들게 한다 (06 §8)
test("가상환경 번들은 계산 라우트를 부르지 않는다 — 기체 선택을 공유하지 않는 api.js 사본이라서", () => {
  const src = new URL("../../world/src/", import.meta.url);
  const files = readdirSync(src, { recursive: true })
    .filter((f) => typeof f === "string" && /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f));
  assert.ok(files.length > 10, `web/world/src .ts/.tsx ${files.length}개 — 경로가 바뀌었나?`);
  assert.ok(files.some((f) => f.endsWith(".tsx")), "화면 조립(.tsx)이 빠졌다 — 새 호출이 가장 생기기 쉬운 자리다");
  for (const f of files) {
    const text = readFileSync(new URL(f, src), "utf8");
    // api 래퍼 경로("/sim/run")와 fetch 직접 경로("/api/sim/run") 둘 다. 경로를 이어 붙여 만드는 호출은
    // 글로 못 잡는다 — 06 §8이 그 한계를 적는다
    for (const p of [...COMPUTE_POST, ...COMPUTE_GET]) {
      for (const q of ['"', "'", "`"]) {
        for (const lit of [`${q}${p}`, `${q}/api${p}`]) {
          assert.ok(!text.includes(lit), `web/world/src/${f}: 계산 라우트 ${p}를 부른다 — 기체 선택이 실리지 않는다`);
        }
      }
    }
  }
});
