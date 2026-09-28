/** 결과 패널 보이기 — 부드럽게·패널 머리를 위로, 모션 축소 설정·버려진 화면·빈 노드 (06 §2 「결과가 사는 패널을 연다」). */

import assert from "node:assert/strict";
import { test } from "node:test";

import { revealPanel } from "./reveal.js";

// 가짜 노드 — scrollIntoView에 넘긴 옵션을 적어 둔다
const node = (extra = {}) => {
  const calls = [];
  return { calls, scrollIntoView: (o) => calls.push(o), ...extra };
};
const winWith = (reduce) => ({ matchMedia: (q) => ({ matches: reduce && q.includes("prefers-reduced-motion") }) });

test("revealPanel — 기본은 부드럽게, 패널 머리를 화면 위에 (block start)", () => {
  const n = node();
  assert.equal(revealPanel(n, { win: winWith(false) }), true);
  assert.deepEqual(n.calls, [{ block: "start", behavior: "smooth" }]);
});

test("revealPanel — block을 고를 수 있다 (경고처럼 가운데에 둘 것)", () => {
  const n = node();
  revealPanel(n, { block: "center", win: winWith(false) });
  assert.deepEqual(n.calls, [{ block: "center", behavior: "smooth" }]);
});

test("revealPanel — 모션 축소 설정이면 부드러운 이동을 끈다 (smooth는 그 설정을 무시한다)", () => {
  const n = node();
  revealPanel(n, { win: winWith(true) });
  assert.deepEqual(n.calls, [{ block: "start", behavior: "auto" }]);
});

test("revealPanel — matchMedia가 없거나 던져도 부드럽게 굴린다 (보이기가 실패의 원인이 되지 않는다)", () => {
  const a = node();
  revealPanel(a, { win: {} });
  assert.deepEqual(a.calls, [{ block: "start", behavior: "smooth" }]);
  const b = node();
  revealPanel(b, { win: { matchMedia: () => { throw new Error("막힘"); } } });
  assert.deepEqual(b.calls, [{ block: "start", behavior: "smooth" }]);
});

test("revealPanel — 버려진 화면(문서에서 떨어진 노드)은 굴리지 않는다", () => {
  // 잡이 끝난 뒤의 보고는 떠난 화면에서도 간다 — 그 화면의 패널을 굴리면 지금 보는 탭이 튄다
  const n = node({ isConnected: false });
  assert.equal(revealPanel(n, { win: winWith(false) }), false);
  assert.deepEqual(n.calls, []);
});

test("revealPanel — 노드가 없거나 scrollIntoView가 없으면 조용히 false (뷰 테스트의 가짜 노드 포함)", () => {
  assert.equal(revealPanel(null), false);
  assert.equal(revealPanel(undefined), false);
  assert.equal(revealPanel({}), false);
});
