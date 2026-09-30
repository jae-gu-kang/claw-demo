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
let profilesReply = () => [];
let metasReply = () => [];
let docReply = () => ({ revision: 1, fingerprint: "fp1", variants: {},
  document: { id: "x", name: "기체 X", is_example: false, law: { design: null, gain_tables: null } },
  warnings: [] });
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
  if (path === "/profiles") return ok(profilesReply());
  if (path === "/results") return ok(metasReply());
  if (/^\/profiles\/[^/]+$/.test(path)) return ok(docReply());
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
// 평가 단계 실행 칸 — 머리 블록과 같은 data-key를 쓰므로 흰 작업면의 fd-control을 집는다.
const evalStep = (root) => root.find("div")
  .find((d) => d.className === "fd-panel fd-control" && d.getAttribute("data-key") === "eval");
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
  assert.doesNotMatch(t, /계산 실패 재시도/, "다시 푼 점이 없으면 재시도 조각도 없다");
  await idle(root);
});

test("평가 — 계산 실패를 다시 푼 점이 있으면 판정 줄이 재사용 뒤에 재시도를 말한다", async () => {
  const prev = resultReply;
  resultReply = () => ({ ...prev(), trim_retry: { policy: "neighbour_v1", retried: 1, resolved_converged: 0,
    resolved_infeasible: 1, resolved_constraint: 0, still_calc_failed: 0, names: ["M0.2_h200_f10"] } });
  const n = evalPosts().length;
  const root = render();
  runEval(root);
  await waitFor(() => evalPosts().length > n && settled(root), "평가 판정");
  assert.match(textOf(evalStep(root)), /트림 재사용 2 · 새로 1 · 계산 실패 재시도 1 → 물리적 불가 1/);
  await idle(root);
  resultReply = prev;
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


// ── 엔티티 막대 목록(v1.75) ──────────────────────────────────────────────────
//
// 목록은 GET /profiles·GET /results만으로 선다(엔티티당 계산 0회). 검사는 막대 위 글자가 아니라
// data-state·캡션·툴팁으로 한다 — 막대에는 글자가 없다.
const rowNodes = (root) => root.find("div").filter((d) => d.className === "fe-row");
const rowFor = (root, key) => rowNodes(root).find((d) => d.getAttribute("data-key") === key);
const cellFor = (row, stage) => row.find("div")
  .find((d) => d.className === "fe-cell" && d.getAttribute("data-stage") === stage);
const captionOf = (root) => textOf(root.find("p").find((p) => p.className === "fe-caption"));
const openButton = (row) => row.find("button")[0];
const trackButton = (row) => row.find("button").find((b) => b.className === "fe-track");

const LIST_ROWS = [
  { id: "x", name: "기체 X", revision: 1, fingerprint: "fp1", is_example: false, variants: [],
    design_source: "quick_seed", doc_warnings: 0,
    gain_tables: { source: "auto_design", stale: true, stale_variants: [], variants: {} },
    applied_design: null },
  { id: "y", name: "기체 Y", revision: 1, fingerprint: "fp2", is_example: false, variants: [],
    design_source: null, doc_warnings: 2, gain_tables: null, applied_design: null },
];
const LIST_METAS = [
  { id: "d1", kind: "auto_design", created: 10, status: "converged", judged: 4, failures: 0,
    profile: { id: "x", variant: null } },
];

test("목록 — 엔티티 한 줄씩 서고, 칸 상태·캡션이 목록 재료만으로 판정한다", async () => {
  // 목록 재료만의 판정을 보려면 **어느 줄도 지금 선택이 아니어야** 한다 — 선택된 줄에는 이 세션이 돈
  // 기록(모듈 stages)이 얹히기 때문이다(그 얹힘은 아래 테스트가 따로 본다)
  setSelection({ id: "z" });
  profilesReply = () => LIST_ROWS;
  metasReply = () => LIST_METAS;
  const root = render();
  await waitFor(() => rowNodes(root).length === 2, "두 엔티티 줄");
  assert.equal(root.find("div").filter((d) => d.className === "fd-stage").length, 6,
    "붙은 단계 머리는 여섯 블록이다");
  assert.ok(root.find("div").find((d) => d.className === "fd-deck"),
    "엔티티 목록은 단계 블록의 흰 작업면 안에 있다");
  const x = rowFor(root, "x");
  assert.equal(trackButton(x).children.length, 6, "진행 막대 한 개 안에 여섯 구간이 이어진다");
  // ①②는 기록 없는 조회 단계다 — 도달이 아니다
  assert.equal(cellFor(x, "doc").getAttribute("data-state"), "reached", "doc_warnings 0은 판정이다");
  assert.equal(cellFor(x, "envelope").getAttribute("data-state"), "no_record");
  assert.equal(cellFor(x, "seed").getAttribute("data-state"), "skipped");
  assert.equal(cellFor(x, "design").getAttribute("data-state"), "reached");
  assert.equal(cellFor(x, "eval").getAttribute("data-state"), "not_run");
  assert.equal(cellFor(x, "apply").getAttribute("data-state"), "blocked");
  // 막대 위엔 글자가 없다 — 칸 안에 글이 들어가면 캡션·툴팁 규약이 깨진다
  assert.equal(textOf(cellFor(x, "design")), "");
  assert.match(cellFor(x, "design").getAttribute("title"), /전 판정 통과\(판정 4건\)/);
  const y = rowFor(root, "y");
  assert.equal(cellFor(y, "doc").getAttribute("data-tone"), "warn", "문서 경고는 주의다");
  assert.equal(cellFor(y, "design").getAttribute("data-state"), "not_run");
  assert.match(captionOf(root), /엔티티 2개/);
  assert.match(captionOf(root), /막힌 줄 1개/);
});

test("목록 — 진행 막대가 저장 상세를 열고, 선택을 바꾸면 실행 기록을 비운다", async () => {
  setSelection({ id: "x" });
  profilesReply = () => LIST_ROWS;
  metasReply = () => LIST_METAS;
  const root = render();
  await waitFor(() => rowNodes(root).length === 2, "두 엔티티 줄");
  // x로 평가를 한 번 돌려 기록을 만든다
  trackButton(rowFor(root, "x")).emit("click");
  await waitFor(() => rowFor(root, "x").getAttribute("data-open") === "1", "x 펼침");
  await waitFor(() => root.find("div").some((d) => d.className === "fe-store"), "트림 저장 상세");
  assert.equal(trackButton(rowFor(root, "x")).getAttribute("aria-expanded"), "true");
  assert.ok(root.find("div").find((d) => d.className === "fe-detail"),
    "상세는 선택한 막대 바로 아래에서 열린다");
  runEval(root);
  await waitFor(() => settled(root), "평가 판정");
  await idle(root);
  assert.match(textOf(evalStep(root)), /하드 게이트 전부 통과/);
  // 같은 줄의 live 기록이 목록 칸으로도 올라온다(지금 세션이 돈 엔티티에서만)
  assert.equal(cellFor(rowFor(root, "x"), "eval").getAttribute("data-source"), "live");
  assert.equal(cellFor(rowFor(root, "y"), "eval").getAttribute("data-source"), "none");
  // y를 열면 stages가 비고, x의 판정이 y의 레일에 서지 않는다
  openButton(rowFor(root, "y")).emit("click");
  await waitFor(() => rowFor(root, "y").getAttribute("data-open") === "1", "y 펼침");
  assert.match(textOf(evalStep(root)), /아직 안 돌림/);
  assert.equal(rowFor(root, "x").getAttribute("data-open"), "0");
  assert.doesNotMatch(textOf(rowFor(root, "y")), /하드 게이트/);
  profilesReply = () => [];
  metasReply = () => [];
});
