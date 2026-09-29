// 엔벨로프 탭 스캔 — 버튼 클릭과 쇼케이스 신호의 경계 (node --test, 가짜 DOM·가짜 fetch)
//
// runScan이 신호를 위치 인자로 받던 때 버튼이 그 함수를 그대로 묶어, 평범한 클릭의 MouseEvent가 신호로 둔갑했다 —
// 잡이 끝나면 토큰·탭·동작 없는 「showcaseReport」가 store에 써졌다(리뷰 지적, 헤드리스 크롬 재현). 클릭은 보고하지
// 않고, 신호는 started·done을 자기 토큰으로 보고하고 결과가 사는 층(②)을 화면 안으로 굴린다(06 §2).
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저

const { store } = await import("../store.js");
const { REPORT_KEY, postCue } = await import("../lib/showcasecue.js");
const { render } = await import("./envelope.js");

// 고른 기체 문서 — 템플릿이 있어야 신호가 폴백(예제 값)으로 돌지 않는다
const DOC = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/showcase_delta.json", import.meta.url), "utf8"));

// 가짜 서버 — 선도 GET은 실패로 돌려(그리기는 사유만 남긴다) 스캔 경로만 본다. /jobs/ 조회는 붙잡아 두고 손으로 푼다
const posts = [];
const heldJobs = [];
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "");
  const method = opts.method ?? "GET";
  if (method === "POST") posts.push({ path, body: JSON.parse(opts.body) });
  if (path.startsWith("/profiles/")) return Promise.resolve(reply(200, { document: DOC }));
  // 스캔 격자는 요구영역의 기본 격자(이관 9단계) — 미계산 둘 + 모델 부족 하나. 모델 부족 점은 보내지 않는다
  if (method === "POST" && path === "/grid/base") {
    const f = JSON.parse(opts.body).fuels?.[0];
    return Promise.resolve(reply(200, {
      region: { mach: [0.1, 0.24], alt: [0, 3000], fuel: [0, 45], confirmed: true, source: "profile" },
      reason: null, axis: [0.1, 0.24],
      rows: [{ alt: 0, fuel: f, bounds: [0.1, 0.24], n: 3, state: "not_run" }],
      points: [
        { name: `M0.1_h0_f${f}`, mach: 0.1, alt: 0, fuel: f, state: "not_run" },
        { name: `M0.24_h0_f${f}`, mach: 0.24, alt: 0, fuel: f, state: "not_run" },
        { name: `M0.3_h0_f${f}`, mach: 0.3, alt: 0, fuel: f, state: "model_gap" },
      ],
      counts: { not_run: 2, model_gap: 1 }, labels: { model_gap: "모델 부족" },
    }));
  }
  if (method === "POST" && path === "/analysis/design-envelope-scan") {
    return Promise.resolve(reply(200, { id: `job${posts.length}` }));
  }
  if (path.startsWith("/jobs/")) return new Promise((resolve) => heldJobs.push({ path, resolve }));
  if (path.startsWith("/results/")) {
    return Promise.resolve(reply(200, { kind: "envelope_scan", cases: [], n_requested: 0 }));
  }
  return Promise.resolve(reply(500, { detail: `stub: ${method} ${path}` }));
};

// store 쓰기 기록 — 보고 키에 쓴 것 전부(토큰 없는 가짜 보고도 잡는다)
const reports = [];
store.subscribe((k, v) => { if (k === REPORT_KEY && v) reports.push(v); });

// 굴린 노드 기록 — 가짜 노드에 scrollIntoView를 달아 revealPanel이 부른 것을 적는다
const scrolled = [];
const proto = Object.getPrototypeOf(document.createElement("div"));
proto.scrollIntoView = function scrollIntoView(o) { scrolled.push({ node: this, o }); };

const tick = () => new Promise((r) => setTimeout(r, 5));
async function waitFor(cond, what, ms = 2000) {
  for (let t = 0; t < ms; t += 5) {
    if (cond()) return;
    await tick();
  }
  assert.fail(`기다렸지만 오지 않았다: ${what}`);
}
const textOf = (n) => (typeof n === "string" ? n : n?.nodeType === 3 ? n.data : (n?.children ?? []).map(textOf).join(""));
const scanButton = (root) => root.find("button").find((b) => textOf(b).startsWith("제어 가능 판정"));
const releaseJobs = () => {
  for (const h of heldJobs.splice(0)) {
    const id = h.path.split("/").pop();
    h.resolve(reply(200, { id, status: "done", result_id: `res-${id}`, progress: 1, done: 1, total: 1, message: null }));
  }
};
const scanPosts = () => posts.filter((p) => p.path === "/analysis/design-envelope-scan");

test("[제어 가능 판정] 클릭 — MouseEvent가 신호로 둔갑하지 않는다 (보고 0건·굴림 없음)", async () => {
  const root = render();
  await tick();
  const click = { type: "click", target: scanButton(root), clientX: 10, clientY: 10, token: undefined };
  scanButton(root).emit("click", click);
  await waitFor(() => heldJobs.length === 1, "스캔 잡의 진행 구독");
  assert.equal(scanPosts().length, 1, "클릭이 스캔을 걸었다");
  releaseJobs();
  await waitFor(() => textOf(root).includes("작업 종료"), "잡 종료 반영");
  await tick();
  assert.deepEqual(reports, [], "클릭이 쇼케이스 보고를 썼다 — 이벤트가 신호로 둔갑");
  assert.deepEqual(scrolled, [], "평범한 클릭은 화면을 굴리지 않는다(신호일 때만)");
});

test("스캔 격자는 요구영역의 기본 격자 — 선도 연료 하나로 받고, 모델 부족 점은 보내지 않는다", () => {
  const grid = posts.filter((p) => p.path === "/grid/base");
  assert.ok(grid.length >= 1, "기본 격자를 받지 않고 스캔했다");
  assert.equal(grid[0].body.fuels.length, 1, "선도 연료 하나");
  assert.equal("n_mach" in grid[0].body, false, "빈 칸은 요구영역 명세 — 명세를 지어 보내지 않는다");
  const sent = scanPosts()[0].body.cases;
  assert.deepEqual(sent.map((c) => c.mach), [0.1, 0.24]);
  assert.ok(sent.every((c) => c.name.startsWith("M0.")), "기본 격자 이름(값 그대로)을 싣는다");
});

test("scan 신호 — 자기 토큰으로 started·done, 결과가 사는 ② 층을 부드럽게 화면 위로", async () => {
  postCue({ token: "scan1", tab: "envelope", action: "scan" });
  render();
  await waitFor(() => heldJobs.length === 1, "신호 스캔의 진행 구독");
  releaseJobs();
  await waitFor(() => reports.some((r) => r.token === "scan1" && r.phase === "done"), "신호 끝 보고");
  const mine = reports.filter((r) => r.token === "scan1");
  assert.deepEqual(mine.map((r) => r.phase), ["started", "done"]);
  assert.ok(mine.every((r) => r.tab === "envelope" && r.action === "scan"));
  assert.ok(reports.every((r) => r.token), "토큰 없는 보고가 섞였다");
  const drawer = scrolled.find((s) => s.node.attrs?.id === "envelope-drawer");
  assert.ok(drawer, "결과 층(패널)을 굴리지 않았다");
  assert.deepEqual(drawer.o, { block: "start", behavior: "smooth" });
});

test("vn 신호 — 끝 보고 앞에서 V-n 선도 절을 공용 revealPanel로 굴린다 (원문 가드)", () => {
  // vn은 선도 GET 두 개를 그리는 길이라 가짜 서버로 끝까지 몰기 무겁다 — 배선만 원문에서 본다
  const src = readFileSync(new URL("./envelope.js", import.meta.url), "utf8");
  const vn = src.match(/if \(c\.action === "vn"\) \{[\s\S]*?\n {6}\} else if/)?.[0];
  assert.ok(vn, "vn 갈래를 찾지 못했다");
  const reveal = vn.indexOf("revealPanel(vnBox.parentElement");
  const done = vn.indexOf('reportCue(c, { phase: "done"');
  assert.ok(reveal > 0 && done > reveal, "V-n 절을 굴리지 않고 보고한다");
  assert.doesNotMatch(src, /scrollIntoView/);
});
