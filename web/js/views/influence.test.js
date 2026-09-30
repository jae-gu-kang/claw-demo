// 영향성 탭 — 비행조건은 요구영역 기본 격자에서 고른다 (05 §11.13 5단계, node --test, 가짜 DOM·가짜 fetch)
//
// (0) 들어오면 기본 격자(POST /grid/base)를 받고, 보낼 수 있는 점(미계산) 전부가 기본 선택이다 — 모델 부족 점은 보내지 않는다
// (1) 탭 고유의 마하 범위·고도·연료 칸이 없다
// (2) 평가 신호의 points(이름)는 그 점만 그 격자 순서로 보낸다 — 격자에 없는 이름이면 조용히 바꿔 돌지 않고 실패한다
// (3) points 없는 2단 평가 신호는 대표점(lib/opspace representativePoints)이다
// (4) 다시 받는 중·못 받은 동안은 옛 점을 보내지 않는다 — 옛 격자가 남아 있어도
// (5) 다시 받은 격자에서 사라진 고른 점은 빼고 그렇다고 말한다 · 요구 미정의 응답은 선택을 지우지 않는다
// (6) 신호는 자기 요청이 더 나중 요청에 밀리면 그 나중 격자를 기다린다
// (7) 폐기된 신호 인자 args.cases는 대표 격자로 조용히 돌지 않고 실패한다
//
// 탭 상태(비행조건 선택·필터)는 모듈 상태라 시험끼리 물려 있다 — 시험마다 fresh()로 기본 격자·「전부」에서 시작한다
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저
// 이 탭의 캔버스는 가짜 컨텍스트가 흉내 내지 않는 호출(setTransform 등)을 쓴다 — 여기서 묻는 것은 비행조건이지 그림이 아니라
// 없는 메서드는 아무것도 안 하는 함수로 둔다
{
  const make = globalThis.document.createElement;
  globalThis.document.createElement = (t) => {
    const n = make(t);
    if (n._ctx) {
      const ctx = n._ctx;
      n._ctx = new Proxy(ctx, { get: (o, k) => (k in o ? o[k] : () => ({ width: 0 })) });
    }
    return n;
  };
  // 재생 애니메이션(setInterval)을 멈춘다 — 「동작 줄이기」 설정의 길(influencecanvas reduceMotion). 안 멈추면 프로세스가 안 끝난다
  globalThis.matchMedia = () => ({ matches: true });
}

const { store } = await import("../store.js");
const { REPORT_KEY, postCue } = await import("../lib/showcasecue.js");
const { render } = await import("./influence.js");

// 가짜 기본 격자 — 두 행(200·3000 m) · 행마다 요구 마하 범위가 다르다 · 모델 부족 1점
const pt = (mach, alt, state = "not_run") => ({ mach, alt, fuel: 10, name: `M${mach}_h${alt}_f10`, state });
const GRID = {
  region: { confirmed: true, source: "profile", mach: [0.1, 0.24], alt: [200, 3000], fuel: [10, 10], boundary: null,
    grid: { n_mach: 3, alts: [200, 3000], fuels: [10] } },
  model: { mach: [0, 0.22], fuel: [0, 50] }, reason: null, axis: [0.1, 0.17, 0.24],
  rows: [{ alt: 200, fuel: 10, bounds: [0.1, 0.24], n: 4, state: "not_run" },
    { alt: 3000, fuel: 10, bounds: [0.12, 0.24], n: 4, state: "not_run" }],
  points: [pt(0.1, 200), pt(0.17, 200), pt(0.2, 200), pt(0.24, 200, "model_gap"), pt(0.24, 3000, "model_gap"),
    pt(0.2, 3000), pt(0.17, 3000), pt(0.12, 3000)],
  counts: { not_run: 6, model_gap: 2 }, labels: { not_run: "미계산", model_gap: "모델 부족" },
  profile: { id: "example-delta", variant: null, revision: 1 },
};

const posts = [];
const heldJobs = [];
const scriptedJobs = new Map();
const scriptedResults = new Map();
let evalSubmit = null;
let sweepSubmit = null;
// /grid/base 응답 — 기본은 GRID. gridGate가 배열이면 응답을 붙잡아 두고(요청 경쟁·받는 중 상태를 손으로 푼다)
let gridReply = () => reply(200, GRID);
let gridGate = null;
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "").split("?")[0];
  const method = opts.method ?? "GET";
  if (method === "POST") posts.push({ path, body: JSON.parse(opts.body) });
  if (method === "POST" && path === "/grid/base") {
    if (gridGate) return new Promise((resolve) => gridGate.push({ resolve }));
    return Promise.resolve(gridReply());
  }
  if (method === "POST" && path === "/influence/evaluate") {
    return Promise.resolve(reply(200, evalSubmit ?? { id: `job${posts.length}` }));
  }
  if (method === "POST" && path === "/influence/improve") {
    return Promise.resolve(reply(202, { id: "improve-ui" }));
  }
  if (method === "POST" && path === "/influence/sweep" && sweepSubmit) {
    return Promise.resolve(reply(200, sweepSubmit));
  }
  if (path.startsWith("/results/") && scriptedResults.has(path.split("/").pop())) {
    return Promise.resolve(reply(200, scriptedResults.get(path.split("/").pop())));
  }
  if (path.startsWith("/jobs/") && scriptedJobs.has(path.split("/").pop())) {
    return Promise.resolve(reply(200, scriptedJobs.get(path.split("/").pop())));
  }
  if (path.startsWith("/jobs/")) return new Promise((resolve) => heldJobs.push({ path, resolve }));
  return Promise.resolve(reply(404, { detail: `stub에 없는 경로: ${method} ${path}` }));
};
const evals = () => posts.filter((p) => p.path === "/influence/evaluate");

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
const btnOf = (root, label) => {
  const b = root.find("button").find((x) => textOf(x).startsWith(label));
  assert.ok(b, `단추 없음: ${label}`);
  return b;
};
const summaryOf = (root) => textOf(root).match(/비행조건(.*?)스텝 s/)?.[1] ?? "";
// 새 방문 — 기본 격자(GRID)를 받고 「전부」로 선택·필터를 되돌린다. 트림 배치 참조도 비운다
async function fresh() {
  gridReply = () => reply(200, GRID);
  gridGate = null;
  store.set("trimBatch", null);
  const root = render();
  await waitFor(() => /기본 격자 6점/.test(summaryOf(root)) && !/다시 받는 중/.test(summaryOf(root)), "기본 격자");
  btnOf(root, "전부").emit("click");
  assert.match(summaryOf(root), /6점 \/ 기본 격자 6점 \(전부\)/);
  return root;
}
const releaseJobs = async () => {
  // 제출 응답 뒤 watchJob의 첫 GET이 대기열에 들어오는 마이크로태스크까지 기다린다.
  await tick();
  for (const h of heldJobs.splice(0)) {
    const id = h.path.split("/").pop();
    h.resolve(reply(200, { id, status: "cancelled", result_id: null, progress: 0, done: 0, total: 1, message: null }));
  }
  await tick();
};

test("평가·설계 개선 — 실행과 목표 설정을 먼저 보여 주고 상세는 접어 둔다", async () => {
  const root = await fresh();
  btnOf(root, "평가·설계 개선").emit("click");
  const sections = root.find("section").filter((node) => node.className === "inf-flow-section");
  assert.equal(sections.length, 3);
  assert.match(textOf(sections[0]), /성능 평가.*1단계 · 선별.*2단계 · 평가.*3단계 · 검증/);
  assert.match(textOf(sections[1]), /목표 성능과 게인 추천.*목표 성능 개선안 계산/);
  const details = root.find("details");
  const limits = details.find((node) => textOf(node).startsWith("탐색 범위"));
  assert.ok(limits);
  assert.notEqual(limits.open, true);
  assert.ok(details.some((node) => textOf(node).startsWith("추가 분석")));
});

test("첫 진입 — 기본 격자를 받고 보낼 점 전부가 선택, 탭 고유의 마하·고도·연료 칸이 없다", async () => {
  const root = render();
  await waitFor(() => /6점 \/ 기본 격자 6점/.test(textOf(root)), "비행조건 요약");
  assert.deepEqual(posts.find((p) => p.path === "/grid/base").body, {}, "요구영역의 명세 그대로 받는다");
  const t = textOf(root);
  assert.match(t, /보내지 않음 — 모델 부족 2점/, "보내지 않는 점이 사라지지 않는다");
  assert.doesNotMatch(t, /mach .*~|alt\[m\]|fuel\[kg\]/, "옛 격자 칸");
  // 표에는 보낼 점만 — 모델 부족 점은 고를 수 없다
  const names = root.find("td").map(textOf).filter((x) => /^M[\d.]+_h/.test(x));
  assert.deepEqual(names, ["M0.1_h200_f10", "M0.17_h200_f10", "M0.2_h200_f10", "M0.2_h3000_f10", "M0.17_h3000_f10",
    "M0.12_h3000_f10"]);
});

test("평가 신호의 points — 그 점만 격자 순서로 보낸다", async () => {
  await fresh();
  const before = evals().length;
  postCue({ token: "pts", tab: "influence", action: "evaluate",
    args: { points: ["M0.12_h3000_f10", "M0.1_h200_f10"], label: "기준" } });
  render();
  await waitFor(() => evals().length === before + 1, "평가 제출");
  const body = evals().at(-1).body;
  assert.deepEqual(body.cases, [
    { name: "M0.1_h200_f10", mach: 0.1, alt: 200, fuel: 10 },
    { name: "M0.12_h3000_f10", mach: 0.12, alt: 3000, fuel: 10 },
  ]);
  assert.equal(body.depth, "full");
  await releaseJobs();
  await waitFor(() => finalReport("pts"), "신호 끝 보고");
});

test("평가 신호의 이름이 격자에 없으면(모델 부족 점 포함) 다른 점으로 돌지 않고 실패한다", async () => {
  await fresh();
  const before = evals().length;
  postCue({ token: "gap", tab: "influence", action: "evaluate", args: { points: ["M0.24_h200_f10"] } });
  render();
  await waitFor(() => finalReport("gap"), "신호 끝 보고");
  assert.equal(finalReport("gap").phase, "failed");
  assert.match(finalReport("gap").error, /기본 격자에 없는 점 1건: M0.24_h200_f10/);
  assert.equal(evals().length, before);
});

test("points 없는 2단 평가 신호는 대표점 — 가운데 연료 × 최저·최고 고도 행 × 행의 마하 양끝", async () => {
  await fresh();
  const before = evals().length;
  postCue({ token: "rep", tab: "influence", action: "evaluate", args: {} });
  const root = render();
  await waitFor(() => evals().length === before + 1, "평가 제출");
  assert.deepEqual(evals().at(-1).body.cases.map((c) => c.name),
    ["M0.1_h200_f10", "M0.2_h200_f10", "M0.2_h3000_f10", "M0.12_h3000_f10"]);
  await releaseJobs();
  await waitFor(() => finalReport("rep"), "신호 끝 보고");
  // 고른 점은 무대의 선택으로 남는다 — 청중이 무엇을 쟀는지 거기서 읽는다
  assert.match(textOf(root), /4점 \/ 기본 격자 6점 \(고름\)/);
});

// 옛 격자는 남아 있어도 보내지 않는다 — 다시 받는 중이면 새 격자가 오기 전이고, 못 받았으면 지금 요구영역을 모른다
test("다시 받는 중·못 받은 동안은 옛 점을 보내지 않는다 — 옛 격자가 남아 있어도", async () => {
  const root = await fresh();
  const before = evals().length;
  gridGate = [];
  btnOf(root, "기본 격자 다시 받기").emit("click");
  await waitFor(() => gridGate.length === 1, "다시 받기 요청");
  btnOf(root, "1단계 · 선별").emit("click");
  await tick();
  assert.equal(evals().length, before, "받는 중에 옛 점을 보냈다");
  assert.match(textOf(root), /기본 격자를 다시 받는 중/);

  gridGate.shift().resolve(reply(500, { detail: "서버 오류" }));
  await waitFor(() => /기본 격자를 받지 못했다/.test(summaryOf(root)), "실패가 요약에 선다");
  assert.match(summaryOf(root), /옛 점을 보내지 않는다/, "옛 격자가 있어도 실패를 크게 말한다");
  btnOf(root, "1단계 · 선별").emit("click");
  await tick();
  assert.equal(evals().length, before, "못 받았는데 옛 점을 보냈다");
  gridGate = null;
});

test("고른 점을 다 빼면 돌지 않는다", async () => {
  const root = await fresh();
  const before = evals().length;
  btnOf(root, "보이는 점 빼기").emit("click");
  assert.match(summaryOf(root), /^0점 /);
  btnOf(root, "1단계 · 선별").emit("click");
  await tick();
  assert.equal(evals().length, before);
  assert.match(textOf(root), /고른 비행조건이 없다/);
});

test("다시 받은 격자에서 사라진 고른 점은 빼고 말한다 · 요구 미정의 응답은 선택을 지우지 않는다", async () => {
  const root = await fresh();
  // 두 점을 손으로 고른다 — 가운데 연료 대표점 대신 체크 칸으로
  btnOf(root, "보이는 점 빼기").emit("click");
  const boxOf = (name) => root.find("tr").find((tr) => textOf(tr).startsWith(name)).find("input")[0];
  for (const n of ["M0.1_h200_f10", "M0.12_h3000_f10"]) {
    const b = boxOf(n);
    b.checked = true;
    b.emit("change");
  }
  assert.match(summaryOf(root), /2점 \/ 기본 격자 6점 \(고름\)/);

  // 요구 미정의 — 점이 없다. 고른 이름은 보류로 남는다(영구히 지우지 않는다)
  gridReply = () => reply(200, { ...GRID, region: null, reason: "기체 문서에 요구 운용영역이 없다", points: [], rows: [] });
  btnOf(root, "기본 격자 다시 받기").emit("click");
  await waitFor(() => /요구영역 미정의/.test(summaryOf(root)), "미정의 안내");
  assert.match(summaryOf(root), /고른 점 2개는 보류/);

  // 한 점이 모델 부족이 된 격자 — 그 점은 뺐다고 말하고 남은 것은 그대로
  const GAP = { ...GRID, points: GRID.points.map((p) => (p.name === "M0.12_h3000_f10" ? { ...p, state: "model_gap" } : p)) };
  gridReply = () => reply(200, GAP);
  const r2 = render(); // 요구 미정의 화면엔 다시 받기 단추가 없다 — 다시 들어온다
  await waitFor(() => /기본 격자 5점/.test(summaryOf(r2)) && !/다시 받는 중/.test(summaryOf(r2)), "새 격자");
  assert.match(summaryOf(r2), /1점 \/ 기본 격자 5점 \(고름\)/);
  assert.match(summaryOf(r2), /고른 점 1개가 새 기본 격자에 없어 뺐다/);
  // 다시 고르면 알림은 걷힌다
  btnOf(r2, "전부").emit("click");
  assert.doesNotMatch(summaryOf(r2), /없어 뺐다/);
});

test("신호의 격자 요청이 더 나중 요청에 밀리면 그 나중 격자로 고른다 — 밀린 응답을 받았다고 치지 않는다", async () => {
  await fresh();
  const before = evals().length;
  gridGate = [];
  postCue({ token: "race", tab: "influence", action: "evaluate", args: { points: ["M0.1_h200_f10"] } });
  render(); // 들어올 때 받기 + 신호의 받기
  await waitFor(() => gridGate.length === 2, "두 요청");
  render(); // 그사이 다시 들어왔다 — 셋째 요청이 이긴다
  await waitFor(() => gridGate.length === 3, "셋째 요청");
  const [first, cueReq, last] = gridGate;
  cueReq.resolve(reply(200, GRID)); // 신호의 응답은 밀렸다
  first.resolve(reply(200, GRID));
  await tick();
  await tick();
  assert.equal(evals().length, before, "밀린 응답으로 평가를 걸었다");
  // 나중 격자 — 같은 이름의 점이 다른 좌표다(요구영역을 고쳤다). 신호는 이 좌표로 보낸다
  const MOVED = { ...GRID, points: GRID.points.map((p) => (p.name === "M0.1_h200_f10" ? { ...p, alt: 201 } : p)) };
  last.resolve(reply(200, MOVED));
  await waitFor(() => evals().length === before + 1, "평가 제출");
  assert.deepEqual(evals().at(-1).body.cases, [{ name: "M0.1_h200_f10", mach: 0.1, alt: 201, fuel: 10 }]);
  gridGate = null;
  await releaseJobs();
  await waitFor(() => finalReport("race"), "신호 끝 보고");
});

test("폐기된 신호 인자 args.cases — 대표 격자로 조용히 돌지 않고 실패한다", async () => {
  await fresh();
  const before = evals().length;
  postCue({ token: "legacy", tab: "influence", action: "evaluate", args: { cases: 4 } });
  render();
  await waitFor(() => finalReport("legacy"), "신호 끝 보고");
  assert.equal(finalReport("legacy").phase, "failed");
  assert.match(finalReport("legacy").error, /args\.cases/);
  assert.match(finalReport("legacy").error, /args\.points/);
  assert.equal(evals().length, before);
});

test("트림 탭 배치(같은 리비전)가 있으면 트림 열이 서고 「트림 채택점만」이 채택점만 고른다", async () => {
  const verdict = (adopted) => ({ trim: { status: "computable", reasons: [] }, model: { status: "valid", reasons: [] },
    limits: { status: adopted ? "ok" : "violated", reasons: adopted ? [] : ["stall_boundary"] },
    margin: { status: "met", reasons: [] }, region: null, adopted,
    exclusion: adopted ? null : { category: "limits", reasons: ["stall_boundary"] } });
  const res = (name, adopted) => {
    const p = GRID.points.find((x) => x.name === name);
    return { case: { name, mach: p.mach, alt: p.alt, fuel: p.fuel }, state: "computable", state_reasons: [],
      verdict: verdict(adopted) };
  };
  const root = await fresh();
  assert.throws(() => btnOf(root, "트림 채택점만"), /단추 없음/, "배치가 없으면 단추도 없다");
  // 다른 리비전의 배치는 붙이지 않는다
  store.set("trimBatch", { profile: { ...GRID.profile, revision: 0 }, results: [res("M0.1_h200_f10", true)] });
  let r = render();
  await waitFor(() => /기본 격자 6점/.test(summaryOf(r)) && !/다시 받는 중/.test(summaryOf(r)), "기본 격자");
  assert.throws(() => btnOf(r, "트림 채택점만"), /단추 없음/, "다른 리비전의 판정을 붙였다");

  store.set("trimBatch", { profile: GRID.profile,
    results: [res("M0.1_h200_f10", true), res("M0.2_h200_f10", false), res("M0.12_h3000_f10", true)] });
  r = render();
  await waitFor(() => /기본 격자 6점/.test(summaryOf(r)) && !/다시 받는 중/.test(summaryOf(r)), "기본 격자");
  assert.ok(r.find("th").some((th) => textOf(th) === "트림"), "트림 열");
  assert.match(textOf(r), /트림 안 함/, "배치에 없는 점");
  btnOf(r, "트림 채택점만").emit("click");
  assert.match(summaryOf(r), /2점 \/ 기본 격자 6점 \(고름\)/);
  const before = evals().length;
  btnOf(r, "1단계 · 선별").emit("click");
  await waitFor(() => evals().length === before + 1, "평가 제출");
  assert.deepEqual(evals().at(-1).body.cases.map((c) => c.name), ["M0.1_h200_f10", "M0.12_h3000_f10"]);
  await releaseJobs();
  await tick();
});

test("수정량 계산 — 버튼 안에 연속 작업 단계·진행률·전체 채움이 보이고 다른 실행은 잠긴다", async () => {
  const report = {
    depth: "full", cards: [], checks: { list: [], n_pass: 0, n_warn: 0, n_fail: 0, n_na: 0, n_judged: 0 },
    stage_order: [], items: {}, hard_checks: [], warnings: [], fingerprint: "shape-ui", criteria_fingerprint: "crit-ui",
    cases: [{ case: "M0.1_h200_f10", midpoint: false, aborted: false, stages: {},
      hard_fails: [{ check: "margins.gm" }], J: null, J_reason: "하드 실패",
      attribution: { status: "ok", findings: [{ rule: "gain", severity: "warn", verdict: "게인 과다" }],
        prescriptions: [{ knobs: ["fcl/Autopilot.K_phi"], knob_class: "gain", direction: "decrease",
          findings: [0], joint_with: [], recheck: ["gm"], notes: [] }] } }],
    aggregate: { hard_fail: true, hard_fails: [{ check: "margins.gm", case: "M0.1_h200_f10" }],
      stages: {}, J: null, J_reason: "하드 실패", n_cases: 1, n_midpoint: 0 },
  };
  evalSubmit = { id: "eval-ui" };
  scriptedJobs.set("eval-ui", { id: "eval-ui", status: "done", result_id: "eval-result-ui",
    progress: 1, done: 1, total: 1, message: "완료" });
  scriptedResults.set("eval-result-ui", report);
  const root = await fresh();
  const evalTab = btnOf(root, "평가·설계 개선");
  if (!root.find("button").some((b) => textOf(b).startsWith("2단계 · 평가"))) evalTab.emit("click");
  await waitFor(() => !btnOf(root, "2단계 · 평가").disabled, "앞선 실행 정리");
  btnOf(root, "2단계 · 평가").emit("click");
  await waitFor(() => /평가 완료/.test(textOf(root)), "평가 완료");
  await tick();
  await waitFor(() => root.find("button").some((b) => textOf(b).startsWith("수정량 계산 →")), "수정량 계산 버튼");

  sweepSubmit = { id: "sweep-ui" };
  btnOf(root, "수정량 계산 →").emit("click");
  await waitFor(() => heldJobs.some((h) => h.path.endsWith("/sweep-ui")), "감도 잡 감시");
  const progress = heldJobs.splice(heldJobs.findIndex((h) => h.path.endsWith("/sweep-ui")), 1)[0];
  progress.resolve(reply(200, { id: "sweep-ui", status: "running", result_id: null,
    progress: 0.4, done: 2, total: 5, message: "게인 변화 측정" }));
  await waitFor(() => btnOf(root, "수정량 계산 →").children[2].textContent === "감도 40%",
    "버튼의 감도 진행률");
  const how = btnOf(root, "수정량 계산 →");
  assert.equal(how.children[0].style.width, "20%", "두 단계 연속 작업 중 감도 40%는 전체 막대의 20%");
  assert.equal(btnOf(root, "2단계 · 평가").disabled, true, "진행 중 평가 중복 실행 방지");

  await waitFor(() => heldJobs.some((h) => h.path.endsWith("/sweep-ui")), "감도 다음 폴링", 1000);
  const cancel = heldJobs.splice(heldJobs.findIndex((h) => h.path.endsWith("/sweep-ui")), 1)[0];
  cancel.resolve(reply(200, { id: "sweep-ui", status: "cancelled", result_id: null,
    progress: 0.4, done: 2, total: 5, message: "취소됨" }));
  await waitFor(() => /^✕ 취소/.test(how.children[2].textContent), "취소 끝 상태");
  evalSubmit = null;
  sweepSubmit = null;
  scriptedJobs.clear();
  scriptedResults.clear();
});

test("통합 분석 — 마진 변화폭을 요청에 전달하고 범위 밖 입력은 제출하지 않는다", async () => {
  const root = await fresh();
  if (!root.find("button").some((b) => textOf(b).startsWith("안정 여유 변화 분석"))) {
    btnOf(root, "평가·설계 개선").emit("click");
  }
  assert.equal(root.find("button").filter((b) => textOf(b).startsWith("운용점 성능 스캔")).length, 1);
  assert.ok(root.find("button").find((b) => textOf(b).startsWith("상세 분석")).hidden);
  const input = root.find("input").find((n) => n.getAttribute("aria-label") === "마진 분석 변화폭 (%)");
  assert.ok(input);
  input.value = "10";
  input.emit("input");
  const before = posts.filter((p) => p.path === "/influence/openloop").length;
  btnOf(root, "안정 여유 변화 분석").emit("click");
  await waitFor(() => posts.filter((p) => p.path === "/influence/openloop").length === before + 1, "마진 요청");
  assert.equal(posts.filter((p) => p.path === "/influence/openloop").at(-1).body.probe_rel, 0.1);
  await tick();
  input.value = "51";
  btnOf(root, "안정 여유 변화 분석").emit("click");
  await tick();
  assert.equal(posts.filter((p) => p.path === "/influence/openloop").length, before + 1);
});

test("게인 자동 추천 — 사용자 목표와 전체 선택 운용점만 보내고 게인은 서버가 선정한다", async () => {
  scriptedJobs.set("improve-ui", { id: "improve-ui", status: "cancelled", progress: 0, done: 0, total: 1 });
  const root = await fresh();
  if (!root.find("button").some((b) => textOf(b).startsWith("목표 성능 개선안 계산"))) {
    btnOf(root, "평가·설계 개선").emit("click");
  }
  const mode = root.find("select").find((n) => n.getAttribute("aria-label") === "개선 목표");
  mode.value = "custom";
  mode.emit("change");
  const target = root.find("input").find((n) => n.getAttribute("aria-label") === "고도 정착시간 목표");
  target.value = "3";
  target.emit("input");
  const gm = root.find("input").find((n) => n.getAttribute("aria-label") === "피치 자세 GM 목표");
  gm.value = "8";
  gm.emit("input");
  assert.doesNotMatch(textOf(root), /조정 변수 선택/);
  btnOf(root, "목표 성능 개선안 계산").emit("click");
  await waitFor(() => posts.some((p) => p.path === "/influence/improve"), "자동 추천 제출");
  const body = posts.find((p) => p.path === "/influence/improve").body;
  assert.equal(body.goal_mode, "custom");
  assert.deepEqual(body.goals, { alt_ts: 3, "gm.pitch_att": 8 });
  assert.equal(body.cases.length, 6);
  assert.equal(body.knobs, undefined);
  await waitFor(() => !btnOf(root, "목표 성능 개선안 계산").disabled, "종료 후 재실행 가능");
  mode.value = "recommended";
  mode.emit("change");
  btnOf(root, "목표 성능 개선안 계산").emit("click");
  await waitFor(() => posts.filter((p) => p.path === "/influence/improve").length >= 2, "권장 성능 제출");
  assert.equal(posts.filter((p) => p.path === "/influence/improve").at(-1).body.goal_mode, "recommended");
  assert.deepEqual(posts.filter((p) => p.path === "/influence/improve").at(-1).body.goals, {});
  scriptedJobs.clear();
});
