// 헤더 기체 선택기의 판단 — 전환 규칙·사라진 선택 되돌리기 (node --test, DOM 없이)
//
// 둘 다 "조용히 틀린 기체로 계산하지 않는다"를 떠받친다: 저장이 안 되는데 다시 읽으면 예제로 돌아간 채
// 바꿨다고 믿게 되고, 사라진 선택을 그대로 두면 요청마다 404가 난다.
import { test } from "node:test";
import assert from "node:assert/strict";

import { STORAGE_KEY, currentSelection, setSelection } from "../lib/profile.js";
import { reconcile, restoredNotice, selectedDocument, switchTo } from "./profilepick.js";

const memStorage = () => {
  const m = new Map();
  return { m, getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
};

test("전환 — 같은 선택은 그대로, 취소는 저장하지 않고, 저장이 안 되면 다시 읽지 않는다", () => {
  let reloads = 0;
  const reload = () => { reloads += 1; };
  const yes = () => true;
  try {
    const st = memStorage();
    // 고르지 않은 상태는 예제다 — 예제를 고르는 것은 같은 선택
    assert.deepEqual(switchTo({ id: "example-delta" }, { storage: st, confirmFn: yes, reload }), { ok: true, reason: null });
    assert.equal(reloads, 0);
    assert.deepEqual(switchTo({ id: "heavy" }, { storage: st, confirmFn: () => false, reload }), { ok: false, reason: null });
    assert.equal(st.m.size, 0);
    assert.equal(reloads, 0);
    const broken = { setItem() { throw new Error("QuotaExceededError"); } };
    const r = switchTo({ id: "heavy" }, { storage: broken, confirmFn: yes, reload });
    assert.equal(r.ok, false);
    assert.match(r.reason, /저장소/);
    assert.equal(switchTo({ id: "heavy" }, { storage: null, confirmFn: yes, reload }).ok, false);
    assert.equal(reloads, 0, "저장 못 한 전환은 다시 읽지 않는다");
    assert.equal(switchTo({ id: "../x" }, { storage: st, confirmFn: yes, reload }).ok, false);
    assert.deepEqual(switchTo({ id: "heavy", variant: "v" }, { storage: st, confirmFn: yes, reload }), { ok: true, reason: null });
    assert.equal(reloads, 1);
    assert.deepEqual(JSON.parse(st.m.get(STORAGE_KEY)), { id: "heavy", variant: "v" });
    setSelection({ id: "heavy", variant: "v" });
    const noAsk = () => { throw new Error("같은 선택에 묻지 않는다"); };
    assert.deepEqual(switchTo({ id: "heavy", variant: "v" }, { storage: st, confirmFn: noAsk, reload }), { ok: true, reason: null });
    assert.equal(reloads, 1);
  } finally {
    setSelection(null);
  }
});

test("사라진 선택은 예제로 되돌리고 사유를 남기고 한 번 다시 그린다 — 있는 선택은 건드리지 않는다", () => {
  const list = [
    { id: "example-delta", name: "예제", variants: [] },
    { id: "heavy", name: "무거운", variants: [{ id: "v", name: "변형" }] },
  ];
  let redraws = 0;
  const redraw = () => { redraws += 1; };
  try {
    const st = memStorage();
    setSelection({ id: "heavy", variant: "v" });
    assert.equal(reconcile(list, { storage: st, redraw }), null);
    assert.deepEqual(currentSelection(), { id: "heavy", variant: "v" });
    assert.equal(redraws, 0);
    // 저장으로 고른 형상 변형이 사라졌다 (기체 탭 → refresh 경로)
    st.setItem(STORAGE_KEY, JSON.stringify({ id: "heavy", variant: "gone" }));
    setSelection({ id: "heavy", variant: "gone" });
    const n = reconcile(list, { storage: st, redraw });
    assert.match(n, /형상 변형/);
    assert.match(n, /예제 기체로 되돌렸습니다/);
    assert.equal(currentSelection(), null);
    assert.equal(st.m.has(STORAGE_KEY), false);
    assert.equal(redraws, 1);
    assert.equal(restoredNotice(), n);
    assert.equal(reconcile(list, { storage: st, redraw }), null, "되돌린 뒤에는 할 일이 없다 — 다시 그리기 고리가 없다");
    assert.equal(redraws, 1);
  } finally {
    setSelection(null);
  }
});

test("고른 기체의 적용 문서 — 형상 변형을 적용하고, 한 번 받아 두며, 실패는 기억하지 않는다", async () => {
  const calls = [];
  let fail = true;
  const prevFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (fail) return { ok: false, status: 503, text: async () => JSON.stringify({ detail: "잠깐 없음" }) };
    return { ok: true, status: 200, text: async () => JSON.stringify({ document: {
      id: "heavy", mass: { m_empty: 800 }, variants: [{ id: "v", name: "v", patch: { "/mass/m_empty": 900 } }],
    } }) };
  };
  try {
    setSelection({ id: "heavy", variant: "v" });
    await assert.rejects(selectedDocument());
    fail = false;
    const doc = await selectedDocument(); // 실패를 기억했다면 여기서도 거절됐다
    assert.equal(doc.mass.m_empty, 900, "형상 변형이 적용된 문서");
    assert.equal("variants" in doc, false);
    await selectedDocument();
    assert.equal(calls.length, 2, "성공한 문서는 한 번만 받는다");
    assert.ok(calls.every((u) => u === "/api/profiles/heavy"));
  } finally {
    globalThis.fetch = prevFetch;
    setSelection(null);
  }
});

test("받아 둔 문서는 선택마다다 — 선택이 바뀌면 다시 받고, 없는 형상 변형은 못 받은 것으로 친다", async () => {
  const calls = [];
  const prevFetch = globalThis.fetch;
  const docs = {
    "/api/profiles/heavy": { id: "heavy", mass: { m_empty: 800 }, variants: [] },
    "/api/profiles/example-delta": { id: "example-delta", mass: { m_empty: 700 }, variants: [] },
  };
  globalThis.fetch = async (url) => {
    calls.push(url);
    return { ok: true, status: 200, text: async () => JSON.stringify({ document: docs[url] }) };
  };
  try {
    setSelection({ id: "heavy", variant: "gone" }); // 서버에서 사라진 형상 변형
    await assert.rejects(selectedDocument(), /형상 변형이 없다/);
    setSelection(null); // 헤더가 예제로 되돌렸다
    assert.equal((await selectedDocument()).id, "example-delta", "사라진 선택의 문서를 되돌린 선택에 쓰지 않는다");
    setSelection({ id: "heavy" });
    assert.equal((await selectedDocument()).mass.m_empty, 800);
    assert.deepEqual(calls, ["/api/profiles/heavy", "/api/profiles/example-delta", "/api/profiles/heavy"]);
  } finally {
    globalThis.fetch = prevFetch;
    setSelection(null);
  }
});
