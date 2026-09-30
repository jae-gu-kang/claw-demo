// 게인 탭 쇼케이스 신호 overview — 보고 한 줄이 **배너와 같은 판정**을 말한다 (node --test, 가짜 DOM·가짜 fetch)
//
// 형상 변형이 확정 표를 비운 기체(쇼케이스 EO/IR형)는 카탈로그의 confirmed가 null이다. 배너는 서버 목록 요약으로
// 「규칙 스케줄로 납니다」를 말하는데, 보고만 따로 판정해 「문서 확정 게인 표 없음」이라 했다 — 청중이 보는 진행
// 카드의 줄이 화면 배너와 반대 사실(「이 기체엔 확정 표가 없다」)을 말하던 자리다.
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저

const { store } = await import("../store.js");
const { REPORT_KEY, postCue } = await import("../lib/showcasecue.js");
const { setSelection } = await import("../lib/profile.js");
const { render } = await import("./gains.js");

const DOC = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/showcase_delta.json", import.meta.url), "utf8"));
const MACH = DOC.law.schedule.mach_grid;

// 카탈로그 — 서버 /gains/catalog 모양(자리 하나만 켠 축약). confirmed는 형상 변형 적용 문서 기준이라 EO/IR형에선 null
const slot = (name, scheduled, design) => {
  const [group, key] = name.split(".");
  return {
    name, group, key, available: true, scheduled, design, unit: "-", desc: name, param: key, block: "scas",
    table: { axes: { mach: MACH }, data: MACH.map((m) => design * (DOC.law.schedule.m_design / m) ** 2), extrapolate: "clip" },
  };
};
const catalogFor = (confirmed) => ({
  axis: "mach", filter_tau: 0.5,
  scas_design: { pitch: { kp: -0.67, ki: -0.097, k_rate: 0.173, washout_tau: 0, out_lo: -0.35, out_hi: 0.35 } },
  autopilot_design: { kp_spd: 0.077 },
  default: ["pitch.kp"], design_index: 3,
  slots: [slot("pitch.kp", true, -0.67), slot("pitch.k_rate", false, 0.173)],
  confirmed,
  profile: { id: DOC.id, name: DOC.name, variant: null, revision: 1 },
});

// 목록 요약 — 서버 /profiles 행의 gain_tables(변형별 출처 동봉)
const ROW = {
  id: DOC.id, name: DOC.name, variants: [{ id: "eoir", name: "EO/IR형" }],
  gain_tables: { source: "auto_design", stale: false, stale_variants: [], variants: { eoir: { source: "rule_schedule" } } },
};

let catalog = catalogFor(null);
let profileRows = [ROW];
const gets = [];
const posts = [];
// 요구영역 기본 격자 — 보낼 점 셋 + 모델 부족 하나. 게인 카드는 보낼 점 전부를 서버 이름 그대로 보낸다
const gpt = (mach, alt, state = "not_run") => ({ mach, alt, fuel: 10, name: `M${mach}_h${alt}_f10`, state });
const GRID = {
  region: { confirmed: false, source: "template", mach: [0.1, 0.2], alt: [200, 3000], fuel: [10, 10], boundary: null },
  model: { mach: [0, 0.3], fuel: [0, 50] }, reason: null,
  rows: [{ alt: 200, fuel: 10, bounds: [0.1, 0.2], n: 2, state: "not_run" },
    { alt: 3000, fuel: 10, bounds: [0.1, 0.2], n: 2, state: "not_run" }],
  points: [gpt(0.1, 200), gpt(0.2, 200), gpt(0.2, 3000, "model_gap"), gpt(0.1, 3000)],
  counts: { not_run: 3, model_gap: 1 }, labels: { not_run: "미계산", model_gap: "모델 부족" },
  profile: { id: "x", variant: null, revision: 1 },
};
let gridReply = () => GRID;
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "").replace(/\?.*$/, "");
  const method = opts.method ?? "GET";
  if (method === "GET") gets.push(path);
  const ok = (data) => Promise.resolve(reply(200, data));
  if (method === "POST") posts.push({ path, body: JSON.parse(opts.body) });
  // gridReply가 약속을 내면 그 약속이 풀릴 때 답한다 — 늦게 온 옛 응답 경주를 재현한다
  if (method === "POST" && path === "/grid/base") return Promise.resolve(gridReply()).then((d) => reply(200, d));
  if (method === "POST" && path === "/influence/evaluate") return ok({ id: "ejob" });
  if (path === "/jobs/ejob") return ok({ id: "ejob", status: "done", result_id: "eres", progress: 1, message: "" });
  if (path === "/results/eres") {
    return ok({ depth: "linear", cards: [], checks: null, aggregate: { hard_fail: false, hard_fails: [] },
      trim_reuse: { reused: 2, computed: 1, resolved_failed: 0, policy: "converged" } });
  }
  if (path === "/gains/catalog") return ok(catalog);
  if (path === "/profiles") return ok(profileRows);
  if (path.startsWith("/profiles/")) return ok({ document: DOC, revision: 1 });
  return Promise.resolve(reply(404, { detail: `stub에 없는 경로: ${method} ${path}` }));
};

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
const textOf = (n) => (typeof n === "string" ? n : n?.nodeType === 3 ? n.data : (n?.children ?? []).map(textOf).join(""));

const RULE = /고른 형상 변형\(「EO\/IR형」\)은 규칙 스케줄\(설계 게인 × q̄ 역비\)로 납니다/;

test("EO/IR형을 고르면 overview 보고가 배너와 같은 「규칙 스케줄」 문구다 — 「확정 게인 표 없음」이 아니다", async () => {
  setSelection({ id: DOC.id, variant: "eoir" });
  postCue({ token: "ov-eoir", tab: "gains", action: "overview" });
  const root = render();
  await waitFor(() => finalReport("ov-eoir"), "신호 끝 보고");
  const r = finalReport("ov-eoir");
  assert.equal(r.phase, "done", r.error);
  assert.match(r.summary, RULE);
  assert.doesNotMatch(r.summary, /확정 게인 표 없음/);
  assert.equal(r.data.gain_tables, false);
  assert.equal(r.data.rule_schedule, true);
  // 배너도 같은 문장을 말한다 — 둘이 한 판정을 읽는다
  await waitFor(() => RULE.test(textOf(root)), "규칙 스케줄 배너");
});

test("변형을 고르지 않았으면 목록을 받지 않고 종전 문구 — 기본형에 표가 없다", async () => {
  setSelection({ id: DOC.id });
  profileRows = [{ ...ROW, gain_tables: null }];
  const before = gets.filter((p) => p === "/profiles").length;
  postCue({ token: "ov-base", tab: "gains", action: "overview" });
  render();
  await waitFor(() => finalReport("ov-base"), "신호 끝 보고");
  const r = finalReport("ov-base");
  assert.equal(r.phase, "done", r.error);
  assert.match(r.summary, /문서 확정 게인 표 없음$/);
  assert.equal(r.data.rule_schedule, false);
  assert.equal(gets.filter((p) => p === "/profiles").length, before, "변형이 없으면 목록을 받을 까닭이 없다");
});

test("확정 표가 있으면 자리 수를 말한다 — 규칙 판정은 보지 않는다", async () => {
  setSelection({ id: DOC.id });
  catalog = catalogFor({ slots: ["pitch.kp", "pitch.ki"], stale: false });
  postCue({ token: "ov-conf", tab: "gains", action: "overview" });
  render();
  await waitFor(() => finalReport("ov-conf"), "신호 끝 보고");
  const r = finalReport("ov-conf");
  assert.equal(r.phase, "done", r.error);
  assert.match(r.summary, /문서 확정 게인 표 2자리$/);
  assert.equal(r.data.gain_tables, true);
  assert.equal(r.data.rule_schedule, false);
});

// 쇼케이스 결함 D4 — 신호가 끝나도 화면이 scrollY 0에 머물러 청중이 결과를 못 봤다. 끝나면 결과가 사는 자리를 굴린다
test("overview 신호가 끝나면 탭 머리(확정 표 배너·곡선)를 부드럽게 화면 위로 굴린다", async () => {
  const scrolled = [];
  const proto = Object.getPrototypeOf(document.createElement("div"));
  proto.scrollIntoView = function scrollIntoView(o) { scrolled.push({ node: this, o }); };
  try {
    setSelection({ id: DOC.id });
    postCue({ token: "ov-reveal", tab: "gains", action: "overview" });
    const root = render();
    await waitFor(() => finalReport("ov-reveal"), "신호 끝 보고");
    assert.equal(finalReport("ov-reveal").phase, "done");
    const hit = scrolled.find((s) => s.node === root);
    assert.ok(hit, "탭 머리를 굴리지 않았다");
    assert.deepEqual(hit.o, { block: "start", behavior: "smooth" });
  } finally {
    delete proto.scrollIntoView;
  }
});

// 탭 진입마다 기본 격자를 받는다 — 먼저 나간 느린 응답이 나중 응답(지금 요구영역)을 덮으면 「아직 안 쟀다」 줄이
// 옛 점 수를 말한다. 요청 차례가 더 나중 것이 있으면 늦게 온 답은 버린다(condpick과 같은 규칙)
test("늦게 온 옛 /grid/base 응답이 나중 응답의 기본 격자를 덮지 않는다", async () => {
  setSelection({ id: DOC.id });
  catalog = catalogFor(null);
  let release;
  const slow = new Promise((r) => { release = r; });
  const NONE = { ...GRID, region: null, reason: "요구영역 지움", points: [], rows: [] };
  const replies = [() => slow, () => NONE, () => new Promise(() => {})];
  gridReply = () => replies.shift()();
  render(); // 옛 요청 — 늦게 온다
  const fresh = render(); // 나중 요청 — 먼저 온다
  const strip = (root) => root.find("span").map((n) => n.textContent ?? "").join("\n");
  await waitFor(() => /요구영역 지움/.test(strip(fresh)), "나중 응답의 상태 줄");
  release(GRID);
  await tick(); await tick();
  // 셋째 진입(응답 대기 중)은 모듈에 남은 격자로 먼저 그린다 — 그게 나중 응답이어야 한다
  const third = render();
  assert.match(strip(third), /아직 안 쟀다 — 요구영역 미정의 — 요구영역 지움/);
  assert.doesNotMatch(strip(third), /기본 격자 3점/);
  gridReply = () => GRID;
});

// 게인 카드 평가 — 요구영역 기본 격자의 보낼 점 전부(고르개 없음 · 마진 맵·흐름 평가와 같은 집합, 04 §5)
test("evaluate 신호 — 기본 격자의 보낼 점 전부를 서버 이름으로 보내고, 점 수·초안·트림 재사용을 말한다", async () => {
  setSelection({ id: DOC.id });
  catalog = catalogFor(null);
  gridReply = () => GRID;
  postCue({ token: "ev", tab: "gains", action: "evaluate", args: { depth: "linear" } });
  const root = render();
  await waitFor(() => finalReport("ev"), "신호 끝 보고");
  const r = finalReport("ev");
  assert.equal(r.phase, "done", r.error);
  const body = posts.filter((p) => p.path === "/influence/evaluate").at(-1).body;
  assert.deepEqual(body.cases.map((c) => c.name), ["M0.1_h200_f10", "M0.2_h200_f10", "M0.1_h3000_f10"]);
  assert.equal(r.data.points, 3);
  assert.match(r.summary, /기본 격자 3점$/);
  // 상태 줄은 textContent로 쓴다(가짜 DOM은 그 값을 속성으로만 든다)
  const t = root.find("span").map((n) => n.textContent ?? "").join("\n");
  assert.match(t, /완료 — 요구영역 기본 격자 3점 · 요구영역 미확정 초안/);
  assert.match(t, /트림 재사용 2 · 새로 1/);
});

test("evaluate 신호 — 요구영역 미정의면 보내지 않고 사유로 실패한다(템플릿 격자로 돌지 않는다)", async () => {
  setSelection({ id: DOC.id });
  gridReply = () => ({ ...GRID, region: null, reason: "기체 문서에 요구 운용영역이 없다", points: [], rows: [] });
  const before = posts.filter((p) => p.path === "/influence/evaluate").length;
  postCue({ token: "ev-none", tab: "gains", action: "evaluate", args: { depth: "linear" } });
  render();
  await waitFor(() => finalReport("ev-none"), "신호 끝 보고");
  const r = finalReport("ev-none");
  assert.equal(r.phase, "failed");
  assert.match(r.error, /요구영역 미정의 — 기체 문서에 요구 운용영역이 없다/);
  assert.equal(posts.filter((p) => p.path === "/influence/evaluate").length, before);
  gridReply = () => GRID;
});
