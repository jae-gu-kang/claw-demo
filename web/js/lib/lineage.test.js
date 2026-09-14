// 결과 목록 계보 칸 — 두 지문(v1.12)과 옛 단일 지문의 구분
import { test } from "node:test";
import assert from "node:assert/strict";

import { lineageText } from "./lineage.js";

test("v1.12 검증 결과는 구조·값 지문 둘을 보인다", () => {
  assert.equal(
    lineageText({ kind: "verify_flight", structure_fingerprint: "60ef218187ba1d01", param_fingerprint: "36e8f3b34dd1827c" }),
    "구조 60ef218187ba1d01 · 값 36e8f3b34dd1827c");
});

test("옛 검증 결과의 단일 지문은 구 형상 지문으로 구분한다 — 같은 칸에서 같은 종류로 읽히지 않게", () => {
  assert.equal(lineageText({ kind: "verify_flight", fingerprint: "9b992c84c6e5d4f8" }), "구 형상 지문 9b992c84c6e5d4f8");
});

test("다른 종류는 보낸 지문 그대로, 없으면 대시", () => {
  assert.equal(lineageText({ kind: "sim", fingerprint: "abc" }), "abc");
  assert.equal(lineageText({ kind: "sim", fingerprint: "" }), "—");
  assert.equal(lineageText(null), "—");
});
