// 트림 탭 쇼케이스 신호의 관문 — 칸·케이스를 덮기 전에 거른다 (node --test, 가짜 DOM·가짜 fetch)
//
// 신호는 문서 도착을 기다린 뒤 격자 칸을 템플릿 격자로 덮고 케이스를 다시 만든다. 그 기다림 사이에
// (1) 사용자의 배치가 이미 돌고 있으면 — 덮은 뒤 runBatch가 거절해 사용자가 돌리던 케이스 목록만 잃는다
// (2) 탭이 다시 그려졌으면 — 버려진 화면의 칸으로 잡을 걸어 지금 화면엔 진행바가 없다
// 둘 다 덮기 전에 사유를 달고 실패해야 한다(엔벨로프 신호와 같은 관문).
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저

const { store } = await import("../store.js");
const { REPORT_KEY, postCue } = await import("../lib/showcasecue.js");
const { render } = await import("./trim.js");

// 고른 기체 문서 — 템플릿 격자를 폴백(DEFAULT_GRID, 15건)과 다르게(3건) 둬 누가 케이스를 만들었는지 가린다
const DOC = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));
DOC.mission_template.trim_grid = { mach: { from: 0.12, to: 0.2, step: 0.04 }, alt: [500], fuel: [20] };

// 가짜 서버 — /jobs/ 조회는 붙잡아 두고(타이머 없음 — 되돌린 코드가 매달려도 프로세스가 끝난다) 손으로 푼다
const posts = [];
const heldJobs = [];
let profileFails = true;
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "");
  const method = opts.method ?? "GET";
  if (method === "POST") posts.push({ path, body: JSON.parse(opts.body) });
  if (path.startsWith("/profiles/")) {
    return Promise.resolve(profileFails ? reply(500, { detail: "문서 없음" }) : reply(200, { document: DOC }));
  }
  if (method === "POST" && path === "/trim/batch") return Promise.resolve(reply(200, { id: `job${posts.length}` }));
  if (path.startsWith("/jobs/")) return new Promise((resolve) => heldJobs.push({ path, resolve }));
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
// 글자 — 뷰가 네이티브 append로 붙인 문자열(가짜 노드에선 날 문자열)도 읽는다
const textOf = (n) => (typeof n === "string" ? n : n?.nodeType === 3 ? n.data : (n?.children ?? []).map(textOf).join(""));
const buttons = (root, prefix) => root.find("button").filter((b) => textOf(b).startsWith(prefix));
// [배치 실행] — 도는 동안 라벨이 「실행 중…」으로 바뀌므로 글자가 아니라 자리(머리줄의 주 버튼)로 찾는다
const runBtnOf = (root) => root.find("button").find((b) => b.className === "primary");
const releaseJobs = () => {
  for (const h of heldJobs.splice(0)) {
    const id = h.path.split("/").pop();
    h.resolve(reply(200, { id, status: "cancelled", result_id: null, progress: 0, done: 0, total: 1, message: null }));
  }
};

test("사용자 배치가 도는 중에 온 신호 — 칸·케이스를 덮지 않고 사유를 단다", async () => {
  // 문서를 못 받은 화면 — 칸은 폴백 격자, 사용자가 그 격자로 케이스를 만들어 배치를 건다
  const rootA = render();
  await tick();
  buttons(rootA, "격자 생성")[0].emit("click");
  runBtnOf(rootA).onclick();
  await waitFor(() => heldJobs.length === 1, "사용자 배치의 진행 구독");
  assert.equal(posts.length, 1);
  const userCases = posts[0].body.cases.length;
  assert.equal(userCases, 15, "폴백 격자(예제 기체) 15건");

  // 그사이 문서가 서고, 진행기가 트림 신호를 건다(탭 재진입 — 진행 감시가 새 화면에 다시 붙는다)
  profileFails = false;
  postCue({ token: "busy", tab: "trim", action: "run" });
  const rootB = render();
  await waitFor(() => finalReport("busy"), "신호 끝 보고");
  const r = finalReport("busy");
  assert.equal(r.phase, "failed");
  assert.match(r.error, /이미 실행 중/);
  assert.equal(posts.length, 1, "신호가 배치를 새로 걸지 않았다");

  // 사용자 배치가 끝난 뒤 다시 누르면 **사용자가 만든 케이스 그대로** 나간다 — 신호가 템플릿 격자(3건)로 덮지 않았다
  releaseJobs();
  await waitFor(() => !runBtnOf(rootB).disabled, "배치 종료 반영");
  runBtnOf(rootB).onclick();
  await waitFor(() => heldJobs.length === 1, "두 번째 배치의 진행 구독");
  assert.equal(posts.length, 2);
  assert.equal(posts[1].body.cases.length, userCases);
  releaseJobs();
  await waitFor(() => !runBtnOf(rootB).disabled, "두 번째 배치 종료");
});

test("신호를 읽은 화면이 문서를 기다리는 사이 다시 그려졌다 — 버려진 칸으로 잡을 걸지 않는다", async () => {
  const before = posts.length;
  postCue({ token: "stale", tab: "trim", action: "run" });
  render(); // 신호를 읽고 문서를 기다린다
  render(); // 그사이 탭이 다시 그려졌다(같은 해시로 다시 이동 등)
  await waitFor(() => finalReport("stale"), "신호 끝 보고");
  const r = finalReport("stale");
  assert.equal(r.phase, "failed");
  assert.match(r.error, /다시 그려졌다/);
  assert.equal(posts.length, before, "버려진 화면이 배치를 걸지 않았다");
  assert.equal(heldJobs.length, 0);
});

// 쇼케이스 결함 D4·D6·D8 — 신호가 끝나면 수치 패널을 화면 안으로 굴리고, 보고 줄이 탭 머리줄의 경고(판정 플래그 위반)를
// 가리지 않으며, 표의 백분율이 「2e+1 %」가 아니다
test("run 신호 끝 — 수치 패널을 굴리고, 보고·머리줄이 같은 플래그 위반을 말하고, 백분율이 고정 소수다", async () => {
  const scrolled = [];
  const proto = Object.getPrototypeOf(document.createElement("div"));
  proto.scrollIntoView = function scrollIntoView(o) { scrolled.push({ node: this, o }); };
  const row = (mach, flags) => ({
    case: { name: `M${mach}_h500_f20`, mach, alt: 500, fuel: 20 }, converged: true,
    flags: { residual_ok: true, saturation_ok: true, alpha_margin_ok: true, continuity_ok: true, ...flags },
    euler: [0, 0.05, 0], control: { elevon: [-0.02], throttle: [0.4] },
    reserve: { de: { frac: 0.2 }, thr: { reserve_hi: 0.6 }, alpha: { stall_reserve: 0.1 } },
  });
  const results = [row(0.12, { continuity_ok: false }), row(0.16, {}), row(0.2, {})];
  const prevFetch = globalThis.fetch;
  globalThis.fetch = (url, opts = {}) => (url.replace(/^\/api/, "").startsWith("/results/")
    ? Promise.resolve(reply(200, { results })) : prevFetch(url, opts));
  try {
    profileFails = false;
    postCue({ token: "run-ok", tab: "trim", action: "run" });
    const root = render();
    await waitFor(() => heldJobs.length === 1, "신호 배치의 진행 구독");
    for (const h of heldJobs.splice(0)) {
      h.resolve(reply(200, { id: "j", status: "done", result_id: "r-ok", progress: 1, done: 3, total: 3, message: null }));
    }
    await waitFor(() => finalReport("run-ok"), "신호 끝 보고");
    const r = finalReport("run-ok");
    assert.equal(r.phase, "done", r.error);
    assert.match(r.summary, /판정 플래그 위반 1건 확인 필요 \(연속성 1\)$/);
    assert.match(textOf(root), /수렴 3\/3 · 판정 플래그 위반 1건 \(연속성 1\)/, "머리줄과 보고가 같은 말");
    const hit = scrolled.find((s) => s.node.attrs?.id === "trim-drawer");
    assert.ok(hit, "수치 패널을 굴리지 않았다");
    assert.deepEqual(hit.o, { block: "start", behavior: "smooth" });
    const text = textOf(root);
    assert.match(text, /20\.0 %/);
    assert.match(text, /60\.0 %/);
    assert.doesNotMatch(text, /e\+1 %/);
  } finally {
    globalThis.fetch = prevFetch;
    delete proto.scrollIntoView;
  }
});
