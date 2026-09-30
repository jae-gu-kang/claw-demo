// 트림 탭 — 첫 진입의 기본 격자, 쇼케이스 신호의 관문 (node --test, 가짜 DOM·가짜 fetch)
//
// 격자는 서버 `POST /grid/base`(엔진 claw.opspace)가 요구 운용영역에서 만든다. 이 탭은
// (0) 처음 들어오면 격자를 받아 케이스를 채운다 — 빈 케이스 목록으로 시작하지 않는다(종전 결함: 0케이스)
// (1) 모델 부족 점은 트림 케이스로 보내지 않는다
// 신호는 격자를 다시 받고 케이스를 덮는다. 그 사이에
// (2) 사용자의 배치가 이미 돌고 있으면 — 덮기 전에 사유를 달고 실패한다(사용자가 고친 케이스를 잃지 않게)
// (3) 탭이 다시 그려졌으면 — 버려진 화면으로 잡을 걸지 않는다
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저

const { store } = await import("../store.js");
const { REPORT_KEY, postCue } = await import("../lib/showcasecue.js");
const { render } = await import("./trim.js");

// 가짜 기본 격자 — 트림 대상 3점 + 모델 부족 1점
const pt = (mach, state = "not_run") => ({ mach, alt: 500, fuel: 20, name: `M${mach}_h500_f20`, state });
const GRID = {
  region: { confirmed: true, source: "profile", mach: [0.12, 0.5], alt: [500, 500], fuel: [20, 20], boundary: null,
    grid: { n_mach: 3, alts: [500], fuels: [20] } },
  model: { mach: [0, 0.45], fuel: [0, 50] }, reason: null, axis: [0.12, 0.16, 0.2],
  rows: [{ alt: 500, fuel: 20, bounds: [0.12, 0.5], n: 4, state: "not_run" }],
  points: [pt(0.12), pt(0.16), pt(0.2), pt(0.5, "model_gap")],
  counts: { not_run: 3, model_gap: 1 }, labels: { not_run: "미계산", model_gap: "모델 부족" },
};

// 가짜 서버 — /jobs/ 조회는 붙잡아 두고(타이머 없음 — 되돌린 코드가 매달려도 프로세스가 끝난다) 손으로 푼다
const posts = [];
let gridGate = null; // 설정되면 /grid/base 응답을 붙잡아 둔다 — 같은 방문 안의 요청 경쟁을 손으로 푼다
const heldJobs = [];
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "");
  const method = opts.method ?? "GET";
  if (method === "POST") posts.push({ path, body: JSON.parse(opts.body) });
  if (method === "POST" && path === "/grid/base") {
    const body = JSON.parse(opts.body);
    if (gridGate) return new Promise((resolve) => gridGate.push({ body, resolve }));
    return Promise.resolve(reply(200, GRID));
  }
  if (method === "POST" && path === "/trim/batch") return Promise.resolve(reply(200, { id: `job${posts.length}` }));
  if (path.startsWith("/jobs/")) return new Promise((resolve) => heldJobs.push({ path, resolve }));
  return Promise.resolve(reply(404, { detail: `stub에 없는 경로: ${method} ${path}` }));
};
const batches = () => posts.filter((p) => p.path === "/trim/batch");
const gridPosts = () => posts.filter((p) => p.path === "/grid/base");

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
// [배치 실행] — 도는 동안 라벨이 「실행 중…」으로 바뀌므로 글자가 아니라 자리(머리줄의 주 버튼)로 찾는다
const runBtnOf = (root) => root.find("button").find((b) => b.className === "primary");
// 패널 열기 — 패널 내용은 열 때 그린다
const openDrawer = (root, label) => {
  const b = root.find("button").find((x) => textOf(x).startsWith(label));
  assert.ok(b, `패널 단추 없음: ${label}`);
  b.emit("click");
};
const releaseJobs = () => {
  for (const h of heldJobs.splice(0)) {
    const id = h.path.split("/").pop();
    h.resolve(reply(200, { id, status: "cancelled", result_id: null, progress: 0, done: 0, total: 1, message: null }));
  }
};

test("첫 진입 — 요구영역의 기본 격자를 받아 케이스를 채운다, 모델 부족 점은 트림하지 않는다", async () => {
  const root = render();
  await waitFor(() => textOf(runBtnOf(root)).includes("3케이스"), "기본 격자 케이스 3건");
  assert.deepEqual(gridPosts()[0].body, {}, "첫 진입은 칸이 아니라 요구영역의 명세로 받는다");
  openDrawer(root, "운용영역·기본 격자");
  assert.match(textOf(root), /기본 격자 4점 — 미계산 3 · 모델 부족 1/);
  runBtnOf(root).onclick();
  await waitFor(() => heldJobs.length === 1, "배치의 진행 구독");
  assert.deepEqual(batches()[0].body.cases.map((c) => c.name), ["M0.12_h500_f20", "M0.16_h500_f20", "M0.2_h500_f20"]);
  releaseJobs();
  await waitFor(() => !runBtnOf(root).disabled, "배치 종료 반영");
});

test("사용자 배치가 도는 중에 온 신호 — 케이스를 덮지 않고 사유를 단다", async () => {
  // 사용자가 케이스 하나를 지우고 배치를 건다(모듈 상태라 탭에 다시 들어와도 케이스가 남는다)
  const rootA = render();
  await tick();
  openDrawer(rootA, "케이스 목록");
  rootA.find("button").filter((b) => textOf(b) === "삭제")[0].emit("click");
  runBtnOf(rootA).onclick();
  await waitFor(() => heldJobs.length === 1, "사용자 배치의 진행 구독");
  const userCases = batches().at(-1).body.cases.length;
  assert.equal(userCases, 2);

  const before = batches().length;
  postCue({ token: "busy", tab: "trim", action: "run" });
  const rootB = render();
  await waitFor(() => finalReport("busy"), "신호 끝 보고");
  const r = finalReport("busy");
  assert.equal(r.phase, "failed");
  assert.match(r.error, /이미 실행 중/);
  assert.equal(batches().length, before, "신호가 배치를 새로 걸지 않았다");

  // 사용자 배치가 끝난 뒤 다시 누르면 **사용자가 고친 케이스 그대로** 나간다
  releaseJobs();
  await waitFor(() => !runBtnOf(rootB).disabled, "배치 종료 반영");
  runBtnOf(rootB).onclick();
  await waitFor(() => heldJobs.length === 1, "두 번째 배치의 진행 구독");
  assert.equal(batches().at(-1).body.cases.length, userCases);
  releaseJobs();
  await waitFor(() => !runBtnOf(rootB).disabled, "두 번째 배치 종료");
});

test("신호가 격자를 받는 사이 탭이 다시 그려졌다 — 버려진 화면으로 잡을 걸지 않는다", async () => {
  const before = batches().length;
  postCue({ token: "stale", tab: "trim", action: "run" });
  render(); // 신호를 읽고 격자를 기다린다
  render(); // 그사이 탭이 다시 그려졌다(같은 해시로 다시 이동 등)
  await waitFor(() => finalReport("stale"), "신호 끝 보고");
  const r = finalReport("stale");
  assert.equal(r.phase, "failed");
  assert.match(r.error, /다시 그려졌다/);
  assert.equal(batches().length, before, "버려진 화면이 배치를 걸지 않았다");
  assert.equal(heldJobs.length, 0);
});

// 쇼케이스 결함 D4·D6·D8 — 신호가 끝나면 수치 패널을 화면 안으로 굴리고, 보고 줄이 탭 머리줄의 경고(판정 플래그 위반)를
// 가리지 않으며, 표의 백분율이 「2e+1 %」가 아니다. 보고의 개수는 조건 상태 라벨이다
test("run 신호 끝 — 수치 패널을 굴리고, 보고·머리줄이 같은 플래그 위반을 말하고, 상태로 센다", async () => {
  const scrolled = [];
  const proto = Object.getPrototypeOf(document.createElement("div"));
  proto.scrollIntoView = function scrollIntoView(o) { scrolled.push({ node: this, o }); };
  const row = (mach, flags, state = "computable", reasons = []) => ({
    case: { name: `M${mach}_h500_f20`, mach, alt: 500, fuel: 20 }, converged: true,
    flags: { residual_ok: true, saturation_ok: true, alpha_margin_ok: true, continuity_ok: true, ...flags },
    euler: [0, 0.05, 0], control: { elevon: [-0.02], throttle: [0.4] },
    reserve: { de: { frac: 0.2 }, thr: { reserve_hi: 0.6 }, alpha: { stall_reserve: 0.1 } },
    state, state_reasons: reasons, region_state: null,
  });
  // M0.16은 조건 판정(05 §11.3 · 이관 8단계)이 실린 결과 — 수렴했지만 실속 경계를 넘어 자동 설계가 채택하지 않는다
  const stalled = { ...row(0.16, {}), verdict: {
    trim: { status: "computable", reasons: [] }, model: { status: "valid", reasons: [] },
    limits: { status: "violated", reasons: ["stall_boundary"] }, margin: { status: "met", reasons: [] }, region: null,
    adopted: false, exclusion: { category: "limits", reasons: ["stall_boundary"] } } };
  // M0.2는 계산 실패를 다시 풀어 스로틀 상한에 닿은 점(05 §11.3 · 이관 7단계) — 근거 열이 「재시도 n회 → 결과」를 싣는다
  const results = [row(0.12, { continuity_ok: false }), stalled,
    { ...row(0.2, { saturation_ok: false }, "infeasible", ["throttle_high"]),
      retry: { attempts: 2, seeds: [], outcomes: [], chosen: 1, result: "limit" } }];
  const prevFetch = globalThis.fetch;
  globalThis.fetch = (url, opts = {}) => (url.replace(/^\/api/, "").startsWith("/results/")
    ? Promise.resolve(reply(200, { results,
      trim_reuse: { trim_fingerprint: "f", reused: 1, computed: 2, resolved_failed: 0, policy: "converged" },
      trim_retry: { policy: "neighbour_v1", retried: 1, resolved_converged: 0, resolved_infeasible: 1,
        resolved_constraint: 0, still_calc_failed: 0, names: ["M0.2_h500_f20"] } }))
    : prevFetch(url, opts));
  try {
    postCue({ token: "run-ok", tab: "trim", action: "run" });
    const root = render();
    await waitFor(() => heldJobs.length === 1, "신호 배치의 진행 구독");
    for (const h of heldJobs.splice(0)) {
      h.resolve(reply(200, { id: "j", status: "done", result_id: "r-ok", progress: 1, done: 3, total: 3, message: null }));
    }
    await waitFor(() => finalReport("run-ok"), "신호 끝 보고");
    const r = finalReport("run-ok");
    assert.equal(r.phase, "done", r.error);
    assert.match(r.summary,
      /^3 케이스 — 계산 가능 1 · 계산 가능·제한 위반 1 · 물리적 불가 1 · 판정 플래그 위반 2건 확인 필요/);
    assert.match(textOf(root), /계산 가능 · 실속 경계 위반/, "상태 열이 채택하지 않은 까닭을 싣는다");
    assert.match(textOf(root), /자동 설계 제외 \(제한 위반\) — 실속 경계 위반/, "근거 열이 조건 판정을 싣는다");
    assert.match(textOf(root), /수렴 3\/3 · 판정 플래그 위반 2건/, "머리줄과 보고가 같은 말");
    assert.match(textOf(root), /스로틀 상한/, "표가 물리적 불가의 근거를 싣는다");
    assert.match(textOf(root), /트림 재사용 1 · 새로 2/, "서버 트림 저장소 되울림");
    assert.match(textOf(root), /계산 실패 재시도 1 → 물리적 불가 1/, "서버 계산 실패 재시도 되울림");
    assert.match(textOf(root), /스로틀 상한 — 재시도 2회 → 물리 한계 하나에 닿음/, "근거 열이 다시 푼 기록을 싣는다");
    assert.doesNotMatch(textOf(root), /null/);
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

test("같은 방문의 격자 요청 경쟁 — 늦게 온 옛 응답이 새 응답을 덮지 않는다", async () => {
  gridGate = [];
  const root = render(); // 재진입 — 케이스가 요구영역 명세 그대로가 아니면 자동 요청은 없다
  await tick();
  const auto = gridGate.length;
  // 명세를 적고 [격자 생성] 두 번 — 첫 요청(옛)과 둘째 요청(새)
  const gen = root.find("button").filter((b) => textOf(b) === "격자 생성")[0];
  gen.emit("click");
  gen.emit("click");
  await waitFor(() => gridGate.length === auto + 2, "두 요청");
  const [oldReq, newReq] = gridGate.slice(auto);
  const NEW = { ...GRID, points: [pt(0.3)], counts: { not_run: 1 } };
  newReq.resolve(reply(200, NEW));
  await waitFor(() => textOf(runBtnOf(root)).includes("1케이스"), "새 응답 반영");
  oldReq.resolve(reply(200, GRID)); // 옛 응답이 늦게 온다
  for (const g of gridGate.slice(0, auto)) g.resolve(reply(200, GRID));
  await tick();
  await tick();
  assert.match(textOf(runBtnOf(root)), /1케이스/, "옛 응답이 케이스를 덮었다");
  gridGate = null;
});

test("재진입 — 요구영역 명세 그대로 받은 케이스면 격자를 다시 받는다(문서가 바뀌었을 수 있다), 손으로 고친 목록은 둔다", async () => {
  // 패널은 모듈 상태라 이미 열려 있을 수 있다 — 삭제 단추가 없을 때만 연다
  const deleteButtons = (root) => {
    if (!root.find("button").some((x) => textOf(x) === "삭제")) openDrawer(root, "케이스 목록");
    return root.find("button").filter((x) => textOf(x) === "삭제");
  };
  // 앞 시험이 [격자 생성]으로 받은 목록(명세 칸) — 요구영역 명세 그대로가 아니라 재진입이 다시 받지 않는다
  const before = gridPosts().length;
  render();
  await tick();
  assert.equal(gridPosts().length, before, "명세 칸으로 받은 목록을 재진입이 덮었다");
  // 목록을 비우면 재진입이 요구영역 명세로 받는다 — 그 목록은 다시 들어올 때마다 새로 받는다
  for (const b of deleteButtons(render())) b.emit("click");
  render();
  await waitFor(() => gridPosts().length === before + 1, "빈 목록 재진입의 자동 요청");
  await tick();
  const r = render();
  await waitFor(() => gridPosts().length === before + 2, "명세 그대로인 목록의 재요청");
  await tick();
  deleteButtons(r)[0].emit("click"); // 손으로 고친다
  render();
  await tick();
  assert.equal(gridPosts().length, before + 2, "손으로 고친 목록을 덮으러 다시 받았다");
});

// 영향성 탭이 점마다 붙이는 트림 판정(store trimBatch)은 **끝난 배치**만이다 — 취소된 배치의 완료분을 올리면 영향성 탭이
// 나머지 점을 「트림 안 함」으로 읽고, 「트림 채택점만」이 반쪽 배치에서 고른다
test("취소된 배치의 완료분은 영향성 탭에 넘기지 않는다, 끝난 배치만 넘긴다", async () => {
  const done = { profile: { id: "p", variant: null, revision: 1 },
    results: [{ case: { name: "M0.12_h500_f20", mach: 0.12, alt: 500, fuel: 20 }, converged: true,
      flags: { residual_ok: true, saturation_ok: true, alpha_margin_ok: true, continuity_ok: true },
      euler: [0, 0.05, 0], control: { elevon: [-0.02], throttle: [0.4] },
      reserve: { de: { frac: 0.2 }, thr: { reserve_hi: 0.6 }, alpha: { stall_reserve: 0.1 } },
      state: "computable", state_reasons: [], region_state: null }] };
  const prevFetch = globalThis.fetch;
  globalThis.fetch = (url, opts = {}) => (url.replace(/^\/api/, "").startsWith("/results/")
    ? Promise.resolve(reply(200, done)) : prevFetch(url, opts));
  const finish = (status) => {
    for (const h of heldJobs.splice(0)) {
      h.resolve(reply(200, { id: "j", status, result_id: `r-${status}`, progress: 1, done: 1, total: 3, message: null }));
    }
  };
  try {
    store.set("trimBatch", null);
    postCue({ token: "part", tab: "trim", action: "run" });
    render();
    await waitFor(() => heldJobs.length === 1, "신호 배치의 진행 구독");
    finish("cancelled"); // 완료분 1케이스를 저장하고 취소됐다
    await waitFor(() => finalReport("part"), "신호 끝 보고");
    assert.equal(finalReport("part").phase, "failed");
    assert.equal(store.get("trimBatch"), null, "반쪽 배치가 영향성 탭의 트림 열로 갔다");

    postCue({ token: "full", tab: "trim", action: "run" });
    render();
    await waitFor(() => heldJobs.length === 1, "두 번째 배치의 진행 구독");
    finish("done");
    await waitFor(() => finalReport("full"), "신호 끝 보고");
    assert.equal(store.get("trimBatch")?.results?.length, 1, "끝난 배치는 넘긴다");
  } finally {
    globalThis.fetch = prevFetch;
  }
});
