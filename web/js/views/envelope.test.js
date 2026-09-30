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

// ── 그림 가장자리 규약 (사용자 지적: 맨 위·맨 아래 점이 잘리고 글씨가 잘린다) ─────────────────────────
//
// 이 선도들은 가짜 서버로 그리게 하기엔 응답이 크고(선도 GET을 일부러 실패시킨다), 가짜 ctx는 textAlign을 기록하지
// 않아 「글자 상자가 넘쳤나」를 그림에서 되읽을 수 없다. 판단 자체는 lib/plot.js(insetScale·tickAlign·clampTextX)에
// 수치로 고정돼 있으므로, 여기서는 **네 선도가 그 판단을 지나는지**를 원문으로 대조한다 — 규약을 공유하니 한 곳만
// 고치고 다른 곳이 어긋나는 것이 이 파일에서 막힐 일이다.
const SRC = readFileSync(new URL("./envelope.js", import.meta.url), "utf8");

test("네 선도의 세로 사상은 표지 여유를 둔다 — 프레임에 앉은 점이 없다 (원문 대조)", () => {
  const inset = SRC.match(/const py = insetScale\(/g) ?? [];
  assert.equal(inset.length, 4, "세로 사상 넷(M-h · V-n · α-M · 운용 한계)이 모두 insetScale이어야 한다");
  assert.equal(SRC.match(/const py = linScale\(/g), null, "여유 없는 세로 사상이 남았다 — 끝 점이 클립에 잘린다");
});

test("가로축 눈금 숫자는 한 규약(xTick — tickAlign + clampTextX)을 지난다 (원문 대조)", () => {
  // 직접 fillText로 바닥 눈금을 찍는 자리가 없어야 한다: 왼쪽 정렬 −10은 끝 눈금이 캔버스 밖으로 넘쳐 잘렸다
  const raw = SRC.match(/ctx\.fillText\([^)]*,\s*px\(t\)[^)]*,\s*H - mB \+ 16\)/g) ?? [];
  assert.deepEqual(raw, [], `바닥 눈금을 직접 찍는 자리가 남았다: ${raw.join(" · ")}`);
  assert.equal((SRC.match(/xTick\(ctx,/g) ?? []).length, 4, "선도 넷의 가로 눈금이 모두 같은 규약을 써야 한다");
  assert.match(SRC, /const xTick = \(ctx, text, x, y, \{ x0, x1, W \}\) => \{[\s\S]*tickAlign\(x, x0, x1\)[\s\S]*clampTextX\(/,
    "xTick이 lib의 판단(tickAlign·clampTextX)을 쓰지 않는다");
});

test("그림 안 이름표는 프레임 안으로 물린다 — 클립에 잘리지 않는다 (원문 대조)", () => {
  // 귀속 라벨(저속 쪽은 오른쪽 정렬이라 왼쪽 틀 밖으로 나간다) · 닫힌 경계 캡 이름(가운데 정렬) · α-M 이름표
  assert.match(SRC, /const tx = inBox\(ctx, a\.text, a\.ax \+ \(side === "lo" \? -10 : 10\), align, mL \+ 2, W - mR - 2\);/);
  assert.match(SRC, /haloText\(capLabel\(cap\.source\),\s*\n\s*inBox\(ctx, capLabel\(cap\.source\)/);
  assert.match(SRC, /const nameAt = \(text, x, y\) => ctx\.fillText\(text, inBox\(/);
  assert.match(SRC, /const inBox = \(ctx, text, x, align, x0, x1\) => clampTextX\(/);
});
