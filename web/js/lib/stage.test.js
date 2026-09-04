// 전면 배치 뼈대의 판단부 — 숨은 칩·배지·분류 줄
import { test } from "node:test";
import assert from "node:assert/strict";

import { badgeOf, chipModels, openDef, resolveOpen, toggleOpen } from "./stage.js";

const DEFS = [
  { key: "a", label: "가", group: "입력", count: () => 3 },
  { key: "b", label: "나", group: "입력", count: () => 0 },
  { key: "c", label: "다", group: "결과", count: () => null },
  { key: "w", label: "⚠", group: "결과", hidden: () => true, count: () => 9 },
];

test("badgeOf: 셀 수 없는 것과 0은 배지가 없다 — '0건'은 안 센 것과 구분이 안 된다", () => {
  assert.equal(badgeOf(3), "3");
  assert.equal(badgeOf(0), null);
  assert.equal(badgeOf(null), null);
  assert.equal(badgeOf(undefined), null);
  assert.equal(badgeOf(NaN), null);
  assert.equal(badgeOf(Infinity), null);
  // 셌다는 사실 자체를 말해야 하면 문자열로 — 그때는 0이 들어가도 배지가 선다
  assert.equal(badgeOf("0/15"), "0/15");
  assert.equal(badgeOf(""), null);
});

test("resolveOpen: 없는 키·숨은 키는 열리지 않는다 (여는 버튼 없는 서랍 방지)", () => {
  assert.equal(resolveOpen(DEFS, "a"), "a");
  assert.equal(resolveOpen(DEFS, "없음"), null);
  assert.equal(resolveOpen(DEFS, "w"), null); // hidden
  assert.equal(resolveOpen(DEFS, null), null);
  assert.equal(resolveOpen(undefined, "a"), null);
});

test("resolveOpen: hidden은 매번 다시 묻는다 — 조건이 생기면 그 칩은 열 수 있다", () => {
  let warn = false;
  const defs = [{ key: "w", label: "⚠", hidden: () => !warn }];
  assert.equal(resolveOpen(defs, "w"), null);
  warn = true;
  assert.equal(resolveOpen(defs, "w"), "w");
});

test("toggleOpen: 같은 칩이면 닫고 다른 칩이면 그쪽 — 한 번에 하나", () => {
  assert.equal(toggleOpen(DEFS, null, "a"), "a");
  assert.equal(toggleOpen(DEFS, "a", "a"), null);
  assert.equal(toggleOpen(DEFS, "a", "c"), "c");
  // 숨은 칩으로는 못 넘어간다 — 넘어가면 서랍만 뜨고 누를 버튼이 없다
  assert.equal(toggleOpen(DEFS, "a", "w"), null);
});

test("chipModels: 배지·펼침·숨김이 한 배열로 — 숨은 칩은 배지도 펼침도 없다", () => {
  const m = chipModels(DEFS, "c");
  assert.deepEqual(m.map((x) => x.key), ["a", "b", "c", "w"]);
  assert.deepEqual(m.map((x) => x.badge), ["3", null, null, null]);
  assert.deepEqual(m.map((x) => x.expanded), [false, false, true, false]);
  assert.deepEqual(m.map((x) => x.hidden), [false, false, false, true]);
});

test("chipModels: 숨은 칩이 열려 있으면 아무것도 펼쳐지지 않는다", () => {
  assert.equal(chipModels(DEFS, "w").some((x) => x.expanded), false);
});

test("chipModels: 분류 라벨은 바뀌는 지점에만 — 칩마다 붙이면 줄만 길어진다", () => {
  assert.deepEqual(chipModels(DEFS, null).map((x) => x.startsGroup),
    [true, false, true, false]);
});

test("chipModels: 숨은 칩은 분류 줄을 열지도 닫지도 않는다", () => {
  // 분류의 첫 칩이 숨으면 라벨은 **다음 보이는 칩**이 받아야 한다 —
  // 숨은 칩이 라벨을 가져가면 그 분류의 이름이 화면에서 사라진다
  const defs = [
    { key: "a", label: "가", group: "입력" },
    { key: "h", label: "숨", group: "결과", hidden: () => true },
    { key: "c", label: "다", group: "결과" },
  ];
  assert.deepEqual(chipModels(defs, null).map((x) => x.startsGroup),
    [true, false, true]);
});

test("chipModels: 분류가 없으면 라벨 줄도 없다", () => {
  const defs = [{ key: "a", label: "가" }, { key: "b", label: "나" }];
  assert.deepEqual(chipModels(defs, null).map((x) => x.startsGroup), [false, false]);
});

test("chipModels: count·hidden은 값으로도 받는다 (함수가 아닌 정적 정의)", () => {
  const m = chipModels([{ key: "a", label: "가", count: 2, hidden: false }], null);
  assert.equal(m[0].badge, "2");
  assert.equal(m[0].hidden, false);
});

test("openDef: 열린 서랍의 정의 — 숨은 것은 돌려주지 않는다", () => {
  assert.equal(openDef(DEFS, "a").label, "가");
  assert.equal(openDef(DEFS, "w"), null);
  assert.equal(openDef(DEFS, null), null);
});
