// dom 헬퍼 검증 — el() 조립 계약, fmt 비유한값 정책, 플래그 배지 (node --test)
// node에는 DOM이 없으므로 최소 가짜 document로 el()의 "계약"만 검증한다.
import { test } from "node:test";
import assert from "node:assert/strict";

class FakeNode {
  constructor(tag) {
    this.tagName = tag;
    this.nodeType = 1;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
  }
  addEventListener(type, fn) {
    (this.listeners[type] ??= []).push(fn);
  }
  setAttribute(k, v) {
    this.attrs[k] = v;
  }
  append(...cs) {
    this.children.push(...cs);
  }
  replaceChildren() {
    this.children = [];
  }
}
class FakeText {
  constructor(s) {
    this.nodeType = 3;
    this.data = s;
  }
}
globalThis.document = {
  createElement: (t) => new FakeNode(t),
  createTextNode: (s) => new FakeText(s),
};

const { el, clear, fmt, flagBadge } = await import("./dom.js");

test("el: 속성·클래스·이벤트·프로퍼티 분기", () => {
  const clicks = [];
  const n = el("button", {
    class: "primary",
    title: "실행",
    disabled: true,
    onclick: () => clicks.push(1),
  });
  assert.equal(n.className, "primary");
  assert.equal(n.attrs.title, "실행");
  assert.equal(n.disabled, true); // 프로퍼티 직접 할당
  assert.equal(n.listeners.click.length, 1);
});

test("el: 자식 중첩 배열 평탄화·null/false 스킵·텍스트 변환", () => {
  const n = el("div", {}, "a", null, [1, [2, false]], el("span", {}));
  const kinds = n.children.map((c) => (c.nodeType === 3 ? c.data : c.tagName));
  assert.deepEqual(kinds, ["a", "1", "2", "span"]);
});

test("clear: 자식 제거 후 노드 반환", () => {
  const n = el("div", {}, "x");
  assert.equal(clear(n), n);
  assert.equal(n.children.length, 0);
});

test("fmt: 비유한값 정책(M13 serialize)과 자릿수", () => {
  assert.equal(fmt(null), "—");
  assert.equal(fmt("inf"), "∞");
  assert.equal(fmt("-inf"), "−∞");
  assert.equal(fmt(0.123456), "0.123");
  assert.equal(fmt(42), "42");
  assert.equal(fmt(1.5, 2), "1.5");
  assert.equal(fmt("climb"), "climb");
});

test("flagBadge: 3-상태 배지 (true/false/null=미판정)", () => {
  assert.equal(flagBadge(true).className, "flag ok");
  assert.equal(flagBadge(false).className, "flag bad");
  assert.equal(flagBadge(null).className, "flag na");
  assert.equal(flagBadge(null).children[0].data, "미판정");
});
