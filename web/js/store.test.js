// store 검증 — 공유 상태 set/get/구독/해지 (node --test, 의존 0)
import { test } from "node:test";
import assert from "node:assert/strict";

import { store } from "./store.js";

test("set/get 왕복과 구독 알림", () => {
  const seen = [];
  const unsub = store.subscribe((k, v) => seen.push([k, v]));
  store.set("lastTrim", "abc123");
  assert.equal(store.get("lastTrim"), "abc123");
  assert.deepEqual(seen, [["lastTrim", "abc123"]]);
  unsub();
  store.set("lastTrim", "def456");
  assert.equal(seen.length, 1); // 해지 후 알림 없음
  assert.equal(store.get("lastTrim"), "def456");
});

test("미설정 키는 undefined", () => {
  assert.equal(store.get("없는키"), undefined);
});
