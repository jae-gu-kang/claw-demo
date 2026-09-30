// 마진 맵 탭 쇼케이스 신호 — 결과·보고·보드선도는 **지금 화면의** 감시자만 맡는다 (node --test, 가짜 DOM·가짜 fetch)
//
// 신호로 건 잡이 도는 사이 탭을 떠났다 오면 감시자가 둘이다(옛 화면 것 + 재진입이 붙인 것). 먼저 끝난 쪽이
// 신호를 가져가면 최악 칸 보드선도가 버려진 DOM에 열려 청중이 못 본다 — 마지막에 붙은 감시자만 맡아야 한다.
// 또 신호를 읽은 화면이 문서를 기다리는 사이 다시 그려졌으면, 버려진 화면에서 잡을 걸지 않는다.
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저

const { store } = await import("../store.js");
const { REPORT_KEY, postCue } = await import("../lib/showcasecue.js");
const { render } = await import("./margins.js");

const DOC = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));
const CASE = { name: "c1", mach: 0.16, alt: 500, fuel: 20 };
const RESULT = {
  kind: "margin_map",
  cases: [{
    trim: { case: CASE, converged: true, euler: [0, 0.05, 0], control: { elevon: [-0.02], throttle: [0.4] }, flags: {} },
    margins: { pitch_q: { pm_deg: 41.5, gm_db: 11.2 } },
    lon: { modes: [] }, lat: { modes: [] },
  }],
  loops: [{ name: "pitch_q", axis: "lon", x_out: "q", u_in: "de", kp: 0.3, ki: 0, sign: -1 }],
  actuator: null, delay_s: 0, pade_order: 2, fq_criteria: null,
};

// 가짜 서버 — /jobs/ 조회는 붙잡아 두고 손으로 푼다(어느 감시자가 먼저 끝나는지를 시험이 정한다)
// 요구영역 기본 격자 — 보낼 점 셋 + 모델 부족 하나(보내지 않는다). 이름은 서버가 지은 것 그대로 싣는다
const gpt = (mach, alt, state = "not_run") => ({ mach, alt, fuel: 20, name: `M${mach}_h${alt}_f20`, state });
const GRID = {
  region: { confirmed: true, source: "profile", mach: [0.12, 0.2], alt: [500, 2000], fuel: [20, 20], boundary: null },
  model: { mach: [0, 0.3], fuel: [0, 50] }, reason: null,
  rows: [{ alt: 500, fuel: 20, bounds: [0.12, 0.2], n: 2, state: "not_run" },
    { alt: 2000, fuel: 20, bounds: [0.12, 0.2], n: 2, state: "not_run" }],
  points: [gpt(0.12, 500), gpt(0.2, 500), gpt(0.2, 2000, "model_gap"), gpt(0.12, 2000)],
  counts: { not_run: 3, model_gap: 1 }, labels: { not_run: "미계산", model_gap: "모델 부족" },
  profile: { id: "example-delta", variant: null, revision: 1 },
};
let gridReply = () => GRID;
const posts = [];
const heldJobs = [];
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "");
  const method = opts.method ?? "GET";
  if (method === "POST") posts.push({ path, body: JSON.parse(opts.body) });
  const ok = (data) => Promise.resolve(reply(200, data));
  if (method === "POST" && path === "/grid/base") return ok(gridReply());
  if (path.startsWith("/profiles/")) return ok({ document: DOC });
  if (path === "/gains/catalog") return ok({ scas_design: { pitch: { k_rate: 0.3 } } });
  if (path === "/design/defaults") return ok({ config: {} });
  if (method === "POST" && path === "/analysis/margin-map") return ok({ id: "mjob" });
  if (path.startsWith("/jobs/")) return new Promise((resolve) => heldJobs.push(resolve));
  if (path === "/results/mres") return ok(RESULT);
  // 보드선도는 실패로 답한다 — 오류 상자가 **어느 화면의** 슬롯에 앉는지로 누가 열었는지를 본다
  if (path === "/analysis/bode") return Promise.resolve(reply(500, { detail: "BODE_STUB" }));
  return Promise.resolve(reply(404, { detail: `stub에 없는 경로: ${method} ${path}` }));
};
const DONE_JOB = { id: "mjob", status: "done", result_id: "mres", progress: 1, done: 1, total: 1, message: null };

const reports = [];
store.subscribe((k, v) => { if (k === REPORT_KEY && v) reports.push(v); });
const finalReport = (token) => reports.find((r) => r.token === token && (r.phase === "done" || r.phase === "failed"));

const tick = () => new Promise((r) => setTimeout(r, 5));
async function waitFor(cond, what, ms = 2000) {
  for (let t = 0; t < ms; t += 5) {
    if (cond()) return;
    await tick();
  }
  assert.fail(`기다렸지만 오지 않았다: ${what}`);
}
// 글자 — 뷰가 네이티브 append로 붙인 문자열(가짜 노드에선 날 문자열)도 읽는다
const textOf = (n) => (typeof n === "string" ? n : n?.nodeType === 3 ? n.data : (n?.children ?? []).map(textOf).join(""));
const bodePosts = () => posts.filter((p) => p.path === "/analysis/bode").length;

test("신호 잡이 도는 사이 떠났다 오면 — 옛 화면 감시자가 먼저 끝나도 보드선도·보고는 지금 화면이 한다", async () => {
  postCue({ token: "rerender", tab: "margins", action: "run" });
  const rootA = render();
  await waitFor(() => heldJobs.length === 1, "옛 화면 감시자의 진행 구독");
  assert.equal(posts.filter((p) => p.path === "/analysis/margin-map").length, 1);
  const rootB = render(); // 재진입 — 도는 잡에 감시자를 하나 더 붙인다
  await waitFor(() => heldJobs.length === 2, "새 화면 감시자의 진행 구독");

  // 옛 화면 감시자가 먼저 끝을 받는다 — 여기서 신호를 가져가면 안 된다
  heldJobs.shift()(reply(200, DONE_JOB));
  for (let i = 0; i < 20; i += 1) await tick();
  assert.equal(finalReport("rerender"), undefined, "옛 화면 감시자가 보고하지 않았다");
  assert.equal(bodePosts(), 0, "옛 화면 감시자가 보드선도를 열지 않았다");

  heldJobs.shift()(reply(200, DONE_JOB));
  await waitFor(() => finalReport("rerender"), "신호 끝 보고");
  const r = finalReport("rerender");
  assert.equal(r.phase, "done");
  assert.equal(r.resultId, "mres");
  assert.match(r.summary, /PM 최악 41\.5° \(pitch_q @ c1\)/);
  assert.equal(bodePosts(), 1, "최악 칸 보드선도를 한 번 연다");
  assert.ok(textOf(rootB).includes("BODE_STUB"), "보드선도 자리는 지금 화면에 있다");
  assert.ok(!textOf(rootA).includes("BODE_STUB"), "버려진 화면에는 열리지 않는다");
  assert.equal(reports.filter((x) => x.token === "rerender" && x.phase === "done").length, 1);
});

test("신호를 읽은 화면이 문서를 기다리는 사이 다시 그려졌다 — 버려진 화면에서 잡을 걸지 않는다", async () => {
  const before = posts.length;
  postCue({ token: "stale", tab: "margins", action: "run" });
  render(); // 신호를 읽고 문서·설계 게인을 기다린다
  render(); // 그사이 탭이 다시 그려졌다
  await waitFor(() => finalReport("stale"), "신호 끝 보고");
  const r = finalReport("stale");
  assert.equal(r.phase, "failed");
  assert.match(r.error, /다시 그려졌다/);
  assert.equal(posts.slice(before).filter((p) => p.path === "/analysis/margin-map").length, 0);
  assert.equal(heldJobs.length, 0);
});

// 지연 칸의 처음 값은 툴 기본값이다(기체 문서에 지연 칸이 없다) — 결과 캡션이 수치 옆에 그 출처를 단다.
// 출처를 안 밝히면 0.035 s가 고른 기체의 센서·연산 지연처럼 읽힌다
test("결과 캡션 — 손대지 않은 지연 칸으로 잰 결과는 「툴 기본값」이라고 말한다", async () => {
  RESULT.delay_s = 0.035; // 제출한 그대로 되돌려 주는 결과
  const before = posts.length;
  postCue({ token: "delaysrc", tab: "margins", action: "run" });
  const root = render();
  await waitFor(() => heldJobs.length === 1, "감시자의 진행 구독");
  const sent = posts.slice(before).find((p) => p.path === "/analysis/margin-map")?.body;
  assert.equal(sent.delay_s, 0.035);
  assert.equal(sent.pade_order, 2);
  // 점은 요구영역 기본 격자의 보낼 점 전부 — 서버 이름 그대로, 모델 부족 점은 없다
  assert.deepEqual(sent.cases, [
    { name: "M0.12_h500_f20", mach: 0.12, alt: 500, fuel: 20 },
    { name: "M0.2_h500_f20", mach: 0.2, alt: 500, fuel: 20 },
    { name: "M0.12_h2000_f20", mach: 0.12, alt: 2000, fuel: 20 },
  ]);
  heldJobs.shift()(reply(200, DONE_JOB));
  await waitFor(() => finalReport("delaysrc"), "신호 끝 보고");
  assert.ok(textOf(root).includes("지연 포함 (0.035 s, Padé 2차 · 툴 기본값 — 기체 문서에 지연 칸이 없어 기체별 값이 아니다)"),
    "캡션이 지연의 출처를 말한다");
  assert.ok(!textOf(root).includes("트림 재사용"), "되울림이 없는 결과엔 재사용 줄도 없다");
});

test("결과에 trim_reuse가 있으면 「트림 재사용 k · 새로 n」", async () => {
  RESULT.trim_reuse = { trim_fingerprint: "abc", reused: 2, computed: 1, resolved_failed: 0, policy: "converged",
    reused_names: ["M0.12_h500_f20", "M0.2_h500_f20"] };
  postCue({ token: "reuse", tab: "margins", action: "run" });
  const root = render();
  await waitFor(() => heldJobs.length === 1, "감시자의 진행 구독");
  heldJobs.shift()(reply(200, DONE_JOB));
  await waitFor(() => finalReport("reuse"), "신호 끝 보고");
  assert.ok(textOf(root).includes("트림 재사용 2 · 새로 1"), textOf(root).slice(0, 300));
  assert.ok(!textOf(root).includes("계산 실패 재시도"), "다시 푼 점이 없으면 재시도 줄도 없다");
  delete RESULT.trim_reuse;
});

test("결과에 다시 푼 점이 있으면 재사용 줄 옆에 「계산 실패 재시도 n → …」", async () => {
  RESULT.trim_reuse = { trim_fingerprint: "abc", reused: 0, computed: 3, resolved_failed: 0, policy: "converged",
    reused_names: [] };
  RESULT.trim_retry = { policy: "neighbour_v1", retried: 2, resolved_converged: 1, resolved_infeasible: 0,
    resolved_constraint: 0, still_calc_failed: 1, names: ["M0.12_h500_f20", "M0.2_h500_f20"] };
  postCue({ token: "retry", tab: "margins", action: "run" });
  const root = render();
  await waitFor(() => heldJobs.length === 1, "감시자의 진행 구독");
  heldJobs.shift()(reply(200, DONE_JOB));
  await waitFor(() => finalReport("retry"), "신호 끝 보고");
  assert.ok(textOf(root).includes("트림 재사용 0 · 새로 3 · 계산 실패 재시도 2 → 계산 가능 1 · 계산 실패 1"),
    textOf(root).slice(0, 300));
  delete RESULT.trim_reuse;
  delete RESULT.trim_retry;
});

// 요구영역 미정의 — 템플릿 격자로 되돌아가 돌지 않는다. [실행]이 막히고 신호는 사유로 실패한다
test("요구영역 미정의 — [실행]이 막히고 신호는 사유로 실패, 마진 맵을 걸지 않는다", async () => {
  gridReply = () => ({ ...GRID, region: null, reason: "기체 문서에 요구 운용영역이 없다", points: [], rows: [] });
  const before = posts.filter((p) => p.path === "/analysis/margin-map").length;
  postCue({ token: "noregion", tab: "margins", action: "run" });
  const root = render();
  await waitFor(() => finalReport("noregion"), "신호 끝 보고");
  assert.equal(finalReport("noregion").phase, "failed");
  assert.match(finalReport("noregion").error, /요구영역 미정의 — 기체 문서에 요구 운용영역이 없다/);
  const runBtn = root.find("button").find((b) => textOf(b) === "실행");
  assert.equal(runBtn.disabled, true);
  assert.match(runBtn.title, /요구영역 미정의/);
  assert.equal(posts.filter((p) => p.path === "/analysis/margin-map").length, before);
  gridReply = () => GRID;
});
