// 설계 흐름 「평가」 단계 — 요구영역 기본 격자의 보낼 점 전부로 잰다 (node --test, 가짜 DOM·가짜 fetch)
//
// (1) /grid/base의 not_run 점만 서버 이름 그대로 /influence/evaluate에 보내고, 판정 줄이 점 수·초안·트림 재사용을 말한다
// (2) 요구영역 미정의면 보내지 않고 그 사유로 멈춘다 — 템플릿 격자로 되돌아가지 않는다
// (3) 트림 재사용 되울림이 없는 결과(옛 서버)면 재사용 조각을 만들지 않는다
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저

const { setSelection } = await import("../lib/profile.js");
const { render } = await import("./flow.js");

const gpt = (mach, alt, state = "not_run") => ({ mach, alt, fuel: 10, name: `M${mach}_h${alt}_f10`, state });
const GRID = {
  region: { confirmed: false, source: "template", mach: [0.1, 0.2], alt: [200, 3000], fuel: [10, 10], boundary: null },
  model: { mach: [0, 0.3], fuel: [0, 50] }, reason: null,
  rows: [], points: [gpt(0.1, 200), gpt(0.2, 200), gpt(0.2, 3000, "model_gap"), gpt(0.1, 3000)],
  counts: { not_run: 3, model_gap: 1 }, labels: {}, profile: { id: "x", variant: null, revision: 1 },
};
const REUSE = { reused: 2, computed: 1, resolved_failed: 0, policy: "converged" };

let gridReply = () => GRID;
let resultReply = () => ({ depth: "full", cards: [], aggregate: { hard_fail: false, hard_fails: [] }, trim_reuse: REUSE });
const posts = [];
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "").replace(/\?.*$/, "");
  const method = opts.method ?? "GET";
  const ok = (data) => Promise.resolve(reply(200, data));
  if (method === "POST") posts.push({ path, body: JSON.parse(opts.body) });
  if (method === "POST" && path === "/grid/base") return ok(gridReply());
  if (method === "POST" && path === "/influence/evaluate") return ok({ id: "ej" });
  if (path === "/jobs/ej") return ok({ id: "ej", status: "done", result_id: "er", progress: 1, message: "" });
  if (path === "/results/er") return ok(resultReply());
  if (path === "/profiles") return ok([]);
  if (path.endsWith("/criteria")) return ok({ echo: null });
  return Promise.resolve(reply(404, { detail: `stub에 없는 경로: ${method} ${path}` }));
};

const tick = () => new Promise((r) => setTimeout(r, 5));
async function waitFor(cond, what, ms = 2000) {
  for (let t = 0; t < ms; t += 5) {
    if (cond()) return;
    await tick();
  }
  assert.fail(`기다렸지만 오지 않았다: ${what}`);
}
const textOf = (n) => (typeof n === "string" ? n : n?.nodeType === 3 ? n.data : (n?.children ?? []).map(textOf).join(""));
// 평가 단계 카드 — 레일의 data-key="eval" 칸
const evalStep = (root) => root.find("div").find((d) => d.getAttribute("data-key") === "eval");
const evalButton = (root) => evalStep(root).find("button").find((b) => textOf(b) === "실행");
const runEval = (root) => evalButton(root).emit("click");
// 실행이 끝나 버튼이 풀릴 때까지 — 안 기다리면 다음 테스트의 클릭을 running 게이트가 삼킨다
const idle = (root) => waitFor(() => !evalButton(root).disabled, "실행 끝");
const evalPosts = () => posts.filter((p) => p.path === "/influence/evaluate");
const settled = (root) => /통과|실패|주의/.test(textOf(evalStep(root).find("div").find((d) => d.className === "fd-status")));

test("평가 — 기본 격자의 보낼 점 전부를 서버 이름으로 보내고, 판정 줄이 점 수·초안·트림 재사용을 말한다", async () => {
  setSelection({ id: "x" });
  gridReply = () => GRID;
  const root = render();
  runEval(root);
  await waitFor(() => settled(root), "평가 판정");
  const body = evalPosts().at(-1).body;
  assert.deepEqual(body.cases.map((c) => c.name), ["M0.1_h200_f10", "M0.2_h200_f10", "M0.1_h3000_f10"]);
  assert.equal(body.depth, "full");
  const t = textOf(evalStep(root));
  assert.match(t, /하드 게이트 전부 통과 · depth=full · 기본 격자 3점 · 요구영역 미확정 초안 · 트림 재사용 2 · 새로 1/);
  await idle(root);
});

test("평가 — 요구영역 미정의면 보내지 않고 사유로 멈춘다(템플릿 격자로 돌지 않는다)", async () => {
  gridReply = () => ({ ...GRID, region: null, reason: "기체 문서에 요구 운용영역이 없다", points: [], rows: [] });
  const before = evalPosts().length;
  const root = render();
  runEval(root);
  await waitFor(() => /요구영역 미정의/.test(textOf(evalStep(root))), "미정의 사유");
  assert.match(textOf(evalStep(root)), /실패 요구영역 미정의 — 기체 문서에 요구 운용영역이 없다/);
  assert.equal(evalPosts().length, before, "요구영역이 없으면 평가를 보내지 않는다");
  await idle(root);
  gridReply = () => GRID;
});

test("평가 — 확정 요구영역·재사용 되울림 없는 결과면 초안 꼬리표·재사용 조각이 없다", async () => {
  gridReply = () => ({ ...GRID, region: { ...GRID.region, confirmed: true } });
  resultReply = () => ({ depth: "full", cards: [], aggregate: { hard_fail: false, hard_fails: [] } });
  const n = evalPosts().length;
  const root = render();
  runEval(root);
  await waitFor(() => evalPosts().length > n && settled(root), "평가 판정");
  const t = textOf(evalStep(root));
  assert.match(t, /depth=full · 기본 격자 3점/);
  assert.doesNotMatch(t, /미확정 초안|트림 재사용/);
});
