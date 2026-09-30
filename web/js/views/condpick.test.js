// 비행조건 고르개(views/condpick.js) — 영향성 탭에서 떼어 낸 공용 부품 (node --test, 가짜 DOM·가짜 fetch)
//
// 영향성 탭의 행동(views/influence.test.js)은 그 탭을 통해 그대로 시험한다. 여기서는 부품 자체의 계약:
// (1) 받으면 보낼 점 전부가 기본 · 모델 부족은 보내지 않는다
// (2) reset은 필터·선택·뺀 점 알림을 걷고 「전부」로 · select는 그 이름만 격자 순서로
// (3) 요구영역 미정의면 보내지 않고 사유를 던진다(템플릿 격자로 되돌아가지 않는다)
// (4) key가 다르면 상태가 따로다 · 같은 key는 다시 만들어도 선택이 남는다
// (5) 저장소 힌트(points[].stored)가 있으면 요약에 「트림 저장 k」
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom();

const { createCondPicker } = await import("./condpick.js");

const pt = (mach, alt, state = "not_run", stored) => ({ mach, alt, fuel: 10, name: `M${mach}_h${alt}_f10`, state,
  ...(stored ? { stored } : {}) });
const GRID = {
  region: { confirmed: false, source: "template", mach: [0.1, 0.2], alt: [200, 3000], fuel: [10, 10], boundary: null },
  model: { mach: [0, 0.3], fuel: [0, 50] }, reason: null,
  rows: [{ alt: 200, fuel: 10, bounds: [0.1, 0.2], n: 3, state: "not_run" },
    { alt: 3000, fuel: 10, bounds: [0.1, 0.2], n: 3, state: "not_run" }],
  points: [pt(0.1, 200, "not_run", { state: "not_run", converged: true }), pt(0.15, 200), pt(0.2, 200, "model_gap"),
    pt(0.2, 3000), pt(0.15, 3000), pt(0.1, 3000)],
  counts: { not_run: 5, model_gap: 1 }, labels: { not_run: "미계산", model_gap: "모델 부족" },
  profile: { id: "x", variant: null, revision: 1 },
};
let gridReply = GRID;
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "").split("?")[0];
  if ((opts.method ?? "GET") === "POST" && path === "/grid/base") return Promise.resolve(reply(200, gridReply));
  return Promise.resolve(reply(404, { detail: path }));
};
const textOf = (n) => (typeof n === "string" ? n : n?.nodeType === 3 ? n.data : (n?.children ?? []).map(textOf).join(""));

test("받으면 보낼 점 전부 · 모델 부족 제외 · 초안 꼬리표 · 저장 힌트", async () => {
  gridReply = GRID;
  let changes = 0;
  const p = createCondPicker({ key: "t1", onChange: () => { changes += 1; } });
  assert.throws(() => p.selectedCases(), /아직 받지 못했다/);
  const r = await p.latest();
  assert.equal(r.status, "ok");
  assert.deepEqual(p.selectedCases().map((c) => c.name),
    ["M0.1_h200_f10", "M0.15_h200_f10", "M0.2_h3000_f10", "M0.15_h3000_f10", "M0.1_h3000_f10"]);
  const t = textOf(p.el);
  assert.match(t, /5점 \/ 기본 격자 5점 \(전부\)/);
  assert.match(t, /요구영역 미확정 초안/);
  assert.match(t, /트림 저장 1/);
  assert.ok(changes > 0, "onChange");
});

test("select는 그 이름만 격자 순서로 · reset은 전부로", async () => {
  gridReply = GRID;
  const p = createCondPicker({ key: "t2" });
  await p.latest();
  p.select(["M0.1_h3000_f10", "M0.15_h200_f10"]);
  assert.deepEqual(p.selectedCases().map((c) => c.name), ["M0.15_h200_f10", "M0.1_h3000_f10"]);
  assert.match(textOf(p.el), /2점 \/ 기본 격자 5점 \(고름\)/);
  p.state.filter.alts = [200];
  p.reset();
  assert.equal(p.state.filter.alts, null);
  assert.equal(p.selectedCases().length, 5);
});

test("같은 key는 다시 만들어도 선택이 남고, 다른 key는 따로다", async () => {
  gridReply = GRID;
  const a = createCondPicker({ key: "t3" });
  await a.latest();
  a.select(["M0.1_h200_f10"]);
  const a2 = createCondPicker({ key: "t3" });
  assert.deepEqual(a2.selectedCases().map((c) => c.name), ["M0.1_h200_f10"]);
  const b = createCondPicker({ key: "t3-other" });
  await b.latest();
  assert.equal(b.selectedCases().length, 5);
});

test("요구영역 미정의 — 보내지 않고 사유를 던진다 · 고른 이름은 보류", async () => {
  gridReply = GRID;
  const p = createCondPicker({ key: "t4", where: "위 「비행조건」" });
  await p.latest();
  p.select(["M0.1_h200_f10"]);
  gridReply = { ...GRID, region: null, reason: "기체 문서에 요구 운용영역이 없다", points: [], rows: [] };
  const r = await p.latest();
  assert.equal(r.status, "undefined");
  assert.match(r.reason, /요구영역 미정의 — 기체 문서에 요구 운용영역이 없다/);
  assert.throws(() => p.selectedCases(), /요구영역 미정의/);
  assert.match(textOf(p.el), /고른 점 1개는 보류/);
  gridReply = GRID;
  await p.latest();
  assert.deepEqual(p.selectedCases().map((c) => c.name), ["M0.1_h200_f10"]);
  p.select([]);
  assert.throws(() => p.selectedCases(), /위 「비행조건」에서 점을 고른다/);
});
