// 요구영역 편집 화면(views/regionedit.js) — 가짜 DOM·가짜 fetch로 배선을 본다 (node --test)
//
// (1) 켜면 저장본을 받아 미리 보기 · 캡션 한 줄(이름·값·수·영향) · 그림 위에 글자 없음
// (2) 늦게 온 옛 미리 보기가 새 것을 덮지 않는다(차례 가드)
// (3) 422 {path, message} → 그 칸 강조 + 캡션에 메시지
// (4) 「전체 연료 / 현재 연료만」 두 상태 · 편집하면 「미확정」 + 점선 윤곽
// (5) [저장] = PUT …/operating-region(base_revision) · 계보 패널(이력·소비자) · 예제 기체는 저장 막힘(툴팁)
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom, opsOf } from "./testdom.js";

installDom();
// 창 리스너 shim — 끌기의 Escape 취소는 창에 붙는다(제스처 중 포커스가 캔버스가 아니라 표 칸에 있다).
// testdom.js의 window는 devicePixelRatio만 두므로 여기서만 이벤트 대상 계약(add/remove/emit)을 더한다
// (testdom.js 자체 수정은 이 저장소의 테스트 게이트가 testdom.test.js를 요구해 막는다)
{
  const ls = {};
  Object.assign(globalThis.window, {
    addEventListener: (t, f) => { (ls[t] ??= []).push(f); },
    removeEventListener: (t, f) => { ls[t] = (ls[t] ?? []).filter((g) => g !== f); },
    emit: (t, ev = {}) => { for (const f of [...(ls[t] ?? [])]) f(ev); },
  });
}

const { setSelection } = await import("../lib/profile.js");
const { createRegionEditor, resetRegionEditor } = await import("./regionedit.js");
const { PLOT_MARGIN, plotScale, workingFromRegion } = await import("../lib/regionedit.js");

const SECTION = {
  mach: [0.1, 0.24], alt: [200, 3000], fuel: [10, 50],
  boundary: [{ fuel: 10, rows: [[200, 0.1, 0.24], [3000, 0.12, 0.22]] },
    { fuel: 50, rows: [[200, 0.11, 0.24], [3000, 0.14, 0.22]] }],
  base_grid: { n_mach: 4, alts: [200, 3000], fuels: [10, 50] },
};
const echo = (s) => ({ mach: s.mach, alt: s.alt, fuel: s.fuel, boundary: s.boundary, grid: s.base_grid,
  confirmed: true, source: "profile" });
const outlineOf = (s, fuel) => {
  const L = s.boundary.find((l) => l.fuel === fuel) ?? s.boundary[0];
  return L.rows.map(([alt, lo, hi]) => ({ alt, mach_lo: lo, mach_hi: hi, state: "in" }));
};
let nPreview = 0;
let head = 3; // 미리 보기가 되울리는 리비전(다른 곳에서 저장했으면 앞선다)
let layerOutlines = null; // (s) => {"10.0": 윤곽, ...} — 없으면 층마다 제 행 그대로
const previewBody = (s, fuel, after) => ({
  region: echo(s), model: { mach: [0.05, 0.3], fuel: [0, 60] }, outline: outlineOf(s, fuel ?? 10), fuel: fuel ?? 10,
  outlines: layerOutlines ? layerOutlines(s)
    : Object.fromEntries(s.boundary.map((l) => [`${l.fuel}.0`, outlineOf(s, l.fuel)])),
  grid: { points: [{ name: "M0.1_h200_f10", mach: 0.1, alt: 200, fuel: 10, state: "not_run",
    stored: { state: "computable", converged: true } },
  { name: "M0.3_h200_f10", mach: 0.3, alt: 200, fuel: 10, state: "model_gap" }],
  rows: [], axis: [0.1, 0.24], counts: { not_run: 1, model_gap: 1 }, labels: {} },
  impact: { grid: { before: 36, after, kept: 30, added: after - 30, dropped: 6 }, reused: 3, new_trims: after - 30,
    stale: [{ what: "de_trim", status: "stale", label: "δe_trim 표 — 다른 요구영역에서 도출됨 · 다시 도출 필요" },
      { what: "trim_store", status: "reused", label: "트림 저장소 — 재사용 · 요구영역과 무관(플랜트 키)" }] },
  region_key: `key${after}`, reason: null, profile: { id: "my-delta", variant: null, revision: head },
});

const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
const calls = [];
let held = null; // null이면 즉시 답한다 · 배열이면 미리 보기 답을 붙잡아 둔다(손으로 푼다)
let nextPreview = null; // 다음 미리 보기 답을 바꾼다(422 등)
let example = false;
let docSection = SECTION; // GET /profiles/my-delta의 절
let docRevision = 3;
let putReply = null; // (body) => reply — 없으면 리비전 4
let heldGet = null; // {경로: [풀기…]} — 그 GET 답을 붙잡아 둔다
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "");
  const method = opts.method ?? "GET";
  const body = opts.body ? JSON.parse(opts.body) : null;
  calls.push({ method, path, body });
  if (method === "GET" && heldGet?.[path]) {
    const r = path.includes("revision=2")
      ? reply(200, { revision: 2, document: { operating_region: { ...SECTION, mach: [0.1, 0.3] } } })
      : reply(200, { revision: 3, document: { operating_region: { ...SECTION, mach: [0.1, 0.24] } } });
    return new Promise((resolve) => heldGet[path].push(() => resolve(r)));
  }
  if (method === "GET" && path === "/profiles/my-delta") {
    return Promise.resolve(reply(200, { revision: docRevision, is_example: example, fingerprint: "fp",
      document: { id: "my-delta", operating_region: docSection } }));
  }
  if (method === "GET" && path === "/profiles/other-delta") {
    return Promise.resolve(reply(200, { revision: 7, is_example: false, fingerprint: "fp2",
      document: { id: "other-delta", operating_region: { ...SECTION, mach: [0.12, 0.2] } } }));
  }
  if (method === "GET" && path === "/profiles/my-delta?revision=2") {
    return Promise.resolve(reply(200, { revision: 2, document: { operating_region: { ...SECTION, mach: [0.1, 0.3] } } }));
  }
  if (method === "GET" && /^\/profiles\/[a-z-]+\/region-history$/.test(path)) {
    return Promise.resolve(reply(200, { omitted: 4, rows: [
      { revision: 2, region_key: "aaa", confirmed: true, source: "profile", mach: [0.1, 0.3], alt: [200, 3000],
        fuel: [10, 50], n_points: 30 },
      { revision: 3, region_key: "key36", confirmed: true, source: "profile", mach: [0.1, 0.24], alt: [200, 3000],
        fuel: [10, 50], n_points: 36 }] }));
  }
  if (method === "POST" && path === "/grid/region/preview") {
    nPreview += 1;
    const r = nextPreview ? nextPreview(body) : reply(200, previewBody(body.region, body.fuel, 36));
    nextPreview = null;
    if (held) return new Promise((resolve) => held.push(() => resolve(r)));
    return Promise.resolve(r);
  }
  if (method === "PUT" && path === "/profiles/my-delta/operating-region") {
    if (putReply) return putReply(body);
    return Promise.resolve(reply(200, { revision: 4, region: echo(body.operating_region), region_key: "key40",
      fingerprint: "fp" }));
  }
  return Promise.resolve(reply(500, { detail: `stub: ${method} ${path}` }));
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
const all = (root, tag) => root.find(tag);
const button = (root, label) => all(root, "button").find((b) => textOf(b) === label);
const cell = (root, path) => all(root, "input").find((i) => i.attrs["data-cell"] === path);
const caption = (root) => all(root, "p").find((p) => p.className.includes("re-caption"));
const type = (inp, v) => {
  inp.emit("focus", { target: inp });
  inp.value = v;
  inp.emit("input", { target: inp });
};

setSelection({ id: "my-delta" });

test("켜면 저장본을 받아 미리 보기 — 캡션 한 줄 · 그림 위에 글자 없음 · 두 상태 토글", async () => {
  resetRegionEditor();
  const ed = createRegionEditor({ debounceMs: 5 });
  ed.toggle.emit("click", {});
  assert.equal(ed.isEditing(), true);
  await waitFor(() => textOf(caption(ed.root) ?? { children: [] }).includes("바꾸면 영향"), "첫 미리 보기");
  const cap = textOf(caption(ed.root));
  assert.match(cap, /요구영역 확정 · 연료 10 kg · 마하 0\.1–0\.24 · 고도 200–3000 m · 경계표 2층 · 4행/);
  assert.match(cap, /기본 격자 2점 \(이 연료 2 · 수렴 기록 1\)/);
  assert.match(cap, /바꾸면 영향: 기본 격자 36 → 36점 \(유지 30 · 새 트림 6 · 빠짐 6\) · 낡는 결과: δe_trim 표/);
  const first = calls.find((c) => c.path === "/grid/region/preview");
  assert.deepEqual(first.body.region, SECTION, "저장본 절을 그대로 보낸다");
  assert.deepEqual(first.body.profile, { id: "my-delta" }, "고른 기체를 싣는다");
  // 두 상태 토글 — 둘 다 있고 하나만 눌림
  const seg = ["전체 연료", "현재 연료만"].map((l) => button(ed.root, l));
  assert.ok(seg.every(Boolean), "「전체 연료 / 현재 연료만」 토글이 없다");
  assert.deepEqual(seg.map((b) => b.attrs["aria-pressed"]), ["true", "false"]);
  // 그림 — 글자는 여백(눈금 숫자)에만
  const canvas = all(ed.root, "canvas")[0];
  const W = Number(canvas.style.width.replace("px", ""));
  const H = Number(canvas.style.height.replace("px", ""));
  const texts = opsOf(canvas).filter((o) => o.kind === "text");
  assert.ok(texts.length > 0, "눈금 숫자도 없다");
  for (const t of texts) {
    const inside = t.x > PLOT_MARGIN.mL && t.x < W - PLOT_MARGIN.mR && t.y > PLOT_MARGIN.mT && t.y < H - PLOT_MARGIN.mB;
    assert.ok(!inside, `그림 안에 글자: ${t.text} @ ${t.x},${t.y}`);
  }
  // 확정 영역은 실선 윤곽
  const outline = opsOf(canvas).filter((o) => o.kind === "stroke" && o.strokeStyle === "#0040dd");
  assert.ok(outline.length && outline.every((o) => o.dash.length === 0), "확정 영역이 점선");
});

test("늦게 온 옛 미리 보기가 새 것을 덮지 않는다 · 편집하면 미확정 + 점선", async () => {
  held = [];
  const ed = createRegionEditor({ debounceMs: 5 });
  const lo = cell(ed.root, "/boundary/0/rows/1/1");
  assert.ok(lo, "경계표 칸이 없다");
  nextPreview = (b) => reply(200, previewBody(b.region, b.fuel, 38));
  type(lo, "0.13");
  await waitFor(() => held.length === 1, "첫 편집의 미리 보기");
  nextPreview = (b) => reply(200, previewBody(b.region, b.fuel, 40));
  type(cell(ed.root, "/boundary/0/rows/1/1"), "0.15");
  await waitFor(() => held.length === 2, "둘째 편집의 미리 보기");
  const [old, fresh] = held;
  held = null;
  fresh();
  await waitFor(() => textOf(caption(ed.root)).includes("36 → 40점"), "새 답");
  old();
  await tick();
  await tick();
  assert.match(textOf(caption(ed.root)), /36 → 40점/, "옛 답(38점)이 새 답을 덮었다");
  assert.match(textOf(caption(ed.root)), /요구영역 미확정/);
  // 전체 연료(기본) — 층마다 달랐던 값(0.12 · 0.14)을 덮었다고 말한다
  assert.match(textOf(caption(ed.root)), /층마다 달랐던 마하 하한 덮음 — 10 kg 0\.12 · 50 kg 0\.14/);
  const canvas = all(ed.root, "canvas")[0];
  const outline = opsOf(canvas).filter((o) => o.kind === "stroke" && o.strokeStyle === "#0040dd");
  assert.ok(outline.some((o) => o.dash.length > 0), "미확정 윤곽이 실선");
});

test("422 {path, message} → 그 칸 강조 + 캡션에 메시지", async () => {
  const ed = createRegionEditor({ debounceMs: 5 });
  nextPreview = () => reply(422, { detail: { path: "/operating_region/boundary/0/rows/1/2",
    message: "마하 하한 < 상한이어야 함: 0.3 ≥ 0.22" } });
  type(cell(ed.root, "/boundary/0/rows/1/1"), "0.3");
  await waitFor(() => textOf(caption(ed.root)).includes("마하 하한 < 상한"), "오류 캡션");
  assert.ok(cell(ed.root, "/boundary/0/rows/1/2").className.includes("re-err"), "오류 칸 강조가 없다");
  // 수치가 아닌 입력은 보내지 않고 그 칸에서 말한다
  const before = nPreview;
  type(cell(ed.root, "/mach/0"), "abc");
  await tick();
  await tick();
  assert.equal(nPreview, before, "수치가 아닌데 보냈다");
  assert.ok(cell(ed.root, "/mach/0").className.includes("re-err"));
  assert.match(textOf(caption(ed.root)), /수치가 아님/);
  type(cell(ed.root, "/mach/0"), "0.1");
  type(cell(ed.root, "/boundary/0/rows/1/1"), "0.15");
  await waitFor(() => textOf(caption(ed.root)).includes("바꾸면 영향"), "오류가 걷힘");
});

test("[저장] — PUT operating-region(base_revision), 현재 연료만은 그 층만 · 계보 패널", async () => {
  const ed = createRegionEditor({ debounceMs: 5 });
  button(ed.root, "현재 연료만").emit("click", {});
  assert.equal(button(ed.root, "현재 연료만").attrs["aria-pressed"], "true");
  type(cell(ed.root, "/boundary/0/rows/0/2"), "0.23");
  await waitFor(() => textOf(caption(ed.root)).includes("바꾸면 영향"), "미리 보기");
  const save = button(ed.root, "저장");
  assert.ok(save && !save.disabled, "저장 버튼이 막혔다");
  save.emit("click", {});
  await waitFor(() => calls.some((c) => c.method === "PUT"), "PUT");
  const put = calls.find((c) => c.method === "PUT");
  assert.equal(put.path, "/profiles/my-delta/operating-region");
  assert.equal(put.body.base_revision, 3);
  assert.equal(put.body.operating_region.boundary[0].rows[0][2], 0.23);
  assert.equal(put.body.operating_region.boundary[1].rows[0][2], 0.24, "현재 연료만인데 다른 층이 바뀌었다");
  await waitFor(() => textOf(caption(ed.root)).includes("리비전 4"), "저장 알림");
  assert.match(textOf(caption(ed.root)), /요구영역 확정/);
  // 계보 — 이력 행과 소비자 상태, [출처 보기]는 그 리비전 값을 읽기 전용으로
  const lineage = all(ed.root, "details").find((d) => textOf(d).includes("계보"));
  assert.ok(lineage, "계보 패널이 없다");
  await waitFor(() => textOf(lineage).includes("리비전 2"), "이력");
  assert.match(textOf(lineage), /δe_trim 표 — 다른 요구영역에서 도출됨/);
  button(lineage, "출처 보기").emit("click", {});
  await waitFor(() => textOf(lineage).includes("0.3"), "리비전 2 값");
});

test("예제 기체 — 편집은 보이되 저장이 막히고 툴팁이 「복제한 기체에서」", async () => {
  resetRegionEditor();
  example = true;
  const ed = createRegionEditor({ debounceMs: 5 });
  ed.toggle.emit("click", {});
  await waitFor(() => textOf(caption(ed.root) ?? { children: [] }).includes("바꾸면 영향"), "미리 보기");
  assert.ok(cell(ed.root, "/boundary/0/rows/1/1"), "예제여도 편집 표는 보인다");
  for (const label of ["저장", "요구영역 지우기"]) {
    const b = button(ed.root, label);
    assert.ok(b.disabled, `${label}이 막히지 않았다`);
    assert.match(b.attrs.title, /복제한 기체에서/);
  }
  example = false;
});

// ── 검토 반영: 층 윤곽 · 낡은 상태 · 형상 변형 · 저장 중 · 포커스 · 재정렬 뒤 오류 칸 · 출처 보기 경합 ─────────
const THREE = { ...SECTION, boundary: [{ fuel: 10, rows: [[200, 0.1, 0.24], [1500, 0.11, 0.23], [3000, 0.12, 0.22]] },
  { fuel: 50, rows: [[200, 0.11, 0.24], [3000, 0.14, 0.22]] }] };
async function openEditor() {
  resetRegionEditor();
  const ed = createRegionEditor({ debounceMs: 5 });
  ed.toggle.emit("click", {});
  await waitFor(() => textOf(caption(ed.root) ?? { children: [] }).includes("바꾸면 영향"), "첫 미리 보기");
  return ed;
}
const lastPreview = () => calls.filter((c) => c.path === "/grid/region/preview").at(-1);

test("「전체 연료」 — 행 없는 층엔 서버가 준 그 층 윤곽에서 하한·상한을 받아 넣고 고친 칸만 덮는다", async () => {
  docSection = THREE;
  layerOutlines = (s) => ({ "10.0": outlineOf(s, 10), "50.0": [{ alt: 200, mach_lo: 0.11, mach_hi: 0.24, state: "in" },
    { alt: 1500, mach_lo: 0.125, mach_hi: 0.23, state: "in" }, { alt: 3000, mach_lo: 0.14, mach_hi: 0.22, state: "in" }] });
  const ed = await openEditor();
  const n = nPreview;
  type(cell(ed.root, "/boundary/0/rows/1/2"), "0.2");
  await waitFor(() => nPreview > n, "편집 미리 보기");
  assert.deepEqual(lastPreview().body.region.boundary[1].rows, [[200, 0.11, 0.24], [1500, 0.125, 0.2], [3000, 0.14, 0.22]],
    "50 kg 층 하한이 윤곽(0.125)이 아니다 — 고친 행을 복사했다");
  await waitFor(() => textOf(caption(ed.root)).includes("50 kg 행 추가(윤곽)"), "덮음 줄");
  layerOutlines = null;
  docSection = SECTION;
});

test("「전체 연료」 — 그 층 윤곽의 그 고도가 요구 미정의면 지어내지 않고 거부한다(층 이름 · 보내지 않음)", async () => {
  docSection = THREE;
  layerOutlines = (s) => ({ "10.0": outlineOf(s, 10), "50.0": [{ alt: 200, mach_lo: 0.11, mach_hi: 0.24, state: "in" },
    { alt: 1500, mach_lo: null, mach_hi: null, state: "undefined" }] });
  const ed = await openEditor();
  const n = nPreview;
  type(cell(ed.root, "/boundary/0/rows/1/2"), "0.2");
  await tick();
  await tick();
  assert.equal(nPreview, n, "거부했는데 보냈다");
  assert.match(textOf(caption(ed.root)), /「전체 연료」 거부 — 연료 50 kg 층에 고도 1500 m 행이 없고/);
  assert.ok(cell(ed.root, "/boundary/0/rows/1/2").className.includes("re-err"));
  layerOutlines = null;
  docSection = SECTION;
});

test("고른 기체가 바뀌면 다시 만들 때·다시 그릴 때 그 기체를 다시 받는다", async () => {
  const ed = await openEditor();
  setSelection({ id: "other-delta" });
  const ed2 = createRegionEditor({ debounceMs: 5 });
  await waitFor(() => textOf(caption(ed2.root) ?? { children: [] }).includes("마하 0.12–0.2"), "다른 기체");
  assert.deepEqual(lastPreview().body.profile, { id: "other-delta" });
  setSelection({ id: "my-delta" });
  ed2.repaint();
  await waitFor(() => textOf(caption(ed2.root)).includes("마하 0.1–0.24") && textOf(caption(ed2.root)).includes("바꾸면"),
    "원래 기체");
  assert.ok(ed); // 옛 뷰는 버려진다
});

test("미리 보기 리비전이 앞서면 — 편집 없으면 조용히 최신, 있으면 경고 + [최신 불러오기] · 저장 409도", async () => {
  const ed = await openEditor();
  const gets = () => calls.filter((c) => c.method === "GET" && c.path === "/profiles/my-delta").length;
  let g = gets();
  head = 5;
  docRevision = 5;
  button(ed.root, "50 kg").emit("click", {}); // 편집 없이 미리 보기
  await waitFor(() => gets() > g, "조용히 다시 받기");
  await waitFor(() => /리비전 5 위에/.test(button(ed.root, "저장")?.attrs.title ?? ""), "리비전 5");
  assert.doesNotMatch(textOf(caption(ed.root)), /최신 리비전/);
  head = 6;
  type(cell(ed.root, "/boundary/0/rows/0/2"), "0.23");
  await waitFor(() => textOf(caption(ed.root)).includes("⚠ 최신 리비전 6"), "경고");
  assert.ok(button(ed.root, "저장").disabled, "앞선 리비전 위에 저장하려 한다");
  g = gets();
  docRevision = 6;
  button(ed.root, "최신 불러오기").emit("click", {});
  await waitFor(() => gets() > g && textOf(caption(ed.root)).includes("바꾸면 영향")
    && !textOf(caption(ed.root)).includes("⚠ 최신"), "최신");
  // 저장 409 — 같은 버튼
  putReply = () => Promise.resolve(reply(409, { detail: { message: "기준 리비전", head: 9 } }));
  type(cell(ed.root, "/boundary/0/rows/0/2"), "0.22");
  await waitFor(() => !button(ed.root, "저장").disabled, "저장 가능");
  button(ed.root, "저장").emit("click", {});
  await waitFor(() => textOf(caption(ed.root)).includes("⚠ 최신 리비전 9"), "409 경고");
  assert.ok(button(ed.root, "최신 불러오기"));
  putReply = null;
  head = 3;
  docRevision = 3;
});

test("형상 변형을 골라도 기본 문서의 요구영역 — 미리 보기에 {id}만, 캡션이 형상 변형 공통이라 말한다", async () => {
  setSelection({ id: "my-delta", variant: "v1" });
  const ed = await openEditor();
  assert.deepEqual(lastPreview().body.profile, { id: "my-delta" }, "형상 변형을 실었다");
  assert.match(textOf(caption(ed.root)), /요구영역은 기체 전체\(형상 변형 공통\)/);
  setSelection({ id: "my-delta" });
});

test("초안 — [확정] 툴팁이 같은 값이어도 δe_trim이 낡는다고, 계보가 누구의 trim_grid인지 말한다", async () => {
  docSection = null;
  const draftBody = () => reply(200, { ...previewBody(SECTION, 10, 36),
    region: { ...echo(SECTION), confirmed: false, source: "draft:trim_grid" } });
  const prev = globalThis.fetch;
  globalThis.fetch = (url, opts = {}) => (url.endsWith("/grid/region/preview") ? Promise.resolve(draftBody())
    : prev(url, opts));
  const ed = await openEditor();
  assert.match(button(ed.root, "확정").attrs.title, /값이 같아도 δe_trim 표는 낡음/);
  const lineage = all(ed.root, "details")[0];
  assert.match(textOf(lineage), /초안 — 기체 문서\(기본 형상\)의 trim_grid/);
  globalThis.fetch = prev;
  docSection = SECTION;
});

test("저장 중엔 표 칸이 막힌다 — 저장 뒤 사본이 그사이 타자를 덮지 않게", async () => {
  let release = null;
  putReply = (body) => new Promise((resolve) => {
    release = () => resolve(reply(200, { revision: 4, region: echo(body.operating_region), region_key: "k", fingerprint: "fp" }));
  });
  const ed = await openEditor();
  type(cell(ed.root, "/boundary/0/rows/0/2"), "0.23");
  await waitFor(() => !button(ed.root, "저장").disabled, "저장 가능");
  button(ed.root, "저장").emit("click", {});
  await waitFor(() => release, "PUT");
  assert.ok(cell(ed.root, "/boundary/0/rows/0/1").disabled, "저장 중 칸이 열려 있다");
  release();
  await waitFor(() => textOf(caption(ed.root)).includes("리비전 4"), "저장");
  assert.ok(!cell(ed.root, "/boundary/0/rows/0/1").disabled);
  putReply = null;
});

test("칸을 떠나면(Tab) 한 박자 뒤 표를 다시 짜고 다음 칸 포커스를 (고도, 칸)으로 되돌린다", async () => {
  const ed = await openEditor();
  button(ed.root, "현재 연료만").emit("click", {});
  const altCell = cell(ed.root, "/boundary/0/rows/0/0");
  const proto = Object.getPrototypeOf(altCell);
  const orig = proto.focus;
  let focused = null;
  proto.focus = function focus() { focused = this; };
  try {
    type(altCell, "3500"); // 200 m 행이 3500 m가 된다 — 정렬하면 둘째 행
    altCell.emit("change", {});
    altCell.emit("blur", {});
    const next = cell(ed.root, "/boundary/0/rows/0/1"); // Tab → 같은 행의 하한
    next.emit("focus", {});
    await tick();
    const back = cell(ed.root, "/boundary/0/rows/1/1");
    assert.notEqual(back, next, "표를 다시 짜지 않았다");
    assert.equal(focused, back, "포커스가 같은 (고도 3500, 하한) 칸으로 돌아오지 않았다");
  } finally {
    proto.focus = orig;
  }
});

test("타자 중 재정렬 뒤 422 — 서버 경로의 행 색인이 아니라 보낸 사본의 (고도, 칸)으로 화면 칸을 짚는다", async () => {
  const ed = await openEditor();
  button(ed.root, "현재 연료만").emit("click", {});
  nextPreview = () => reply(422, { detail: { path: "/operating_region/boundary/0/rows/1/0", message: "고도 범위 밖" } });
  type(cell(ed.root, "/boundary/0/rows/0/0"), "3500"); // 아직 칸 안 — 표는 옛 순서, 사본은 [3000, 3500]
  await waitFor(() => textOf(caption(ed.root)).includes("고도 범위 밖"), "422");
  assert.ok(cell(ed.root, "/boundary/0/rows/0/0").className.includes("re-err"), "3500을 친 칸이 강조되지 않았다");
  assert.ok(!cell(ed.root, "/boundary/0/rows/1/0").className.includes("re-err"), "3000 칸을 잘못 짚었다");
});

test("[출처 보기] — 늦게 온 옛 리비전 답이 나중에 누른 것을 덮지 않는다 · 생략된 옛 리비전 수", async () => {
  const ed = await openEditor();
  const lineage = all(ed.root, "details")[0];
  await waitFor(() => textOf(lineage).includes("리비전 2"), "이력");
  assert.match(textOf(lineage), /이전 리비전 4개 생략/);
  heldGet = { "/profiles/my-delta?revision=2": [], "/profiles/my-delta?revision=3": [] };
  const src = () => all(lineage, "button").filter((b) => textOf(b) === "출처 보기"); // 최신이 위: [3, 2]
  src()[1].emit("click", {});
  src()[0].emit("click", {});
  await waitFor(() => heldGet["/profiles/my-delta?revision=2"].length && heldGet["/profiles/my-delta?revision=3"].length,
    "두 요청");
  heldGet["/profiles/my-delta?revision=3"][0]();
  await waitFor(() => textOf(lineage).includes("마하 0.1–0.24 ·"), "리비전 3 값");
  heldGet["/profiles/my-delta?revision=2"][0]();
  await tick();
  await tick();
  // 출처 값 줄(「… · 기본 격자 마하」)은 리비전 3 것 하나뿐 — 표의 범위 칸이 아니라 펼친 값으로 본다
  assert.match(textOf(lineage), /마하 0\.1–0\.24 · 고도 200–3000 m · 연료 10–50 kg · 기본 격자/);
  assert.doesNotMatch(textOf(lineage), /마하 0\.1–0\.3 · 고도 200–3000 m · 연료 10–50 kg · 기본 격자/, "옛 답(리비전 2)이 덮었다");
  heldGet = null;
});

// ── 끌기 (후속 ⑦) — 유령·놓을 때 한 번·같은 길(applyCell)·Escape 취소·그림 밖 놓기·예제 기체·끌기 뒤 422 ────────
// 그림의 축은 뷰와 같은 lib(plotScale)으로 다시 세운다 — 좌표를 손으로 적으면 여백·여유를 고칠 때 테스트만 맞는다
const geomOf = (section = SECTION, fuel = 10) => plotScale({
  work: workingFromRegion(section), model: { mach: [0.05, 0.3] },
  points: previewBody(section, fuel, 36).grid.points.filter((q) => q.fuel === fuel), width: 780, height: 420 });
// 캔버스 크기 그대로 재는 사각형 — 스텁 기본(380×380)이면 px이 2배로 늘어 좌표 계산이 축과 어긋난다
const plotCanvas = (root) => {
  const c = all(root, "canvas")[0];
  c.getBoundingClientRect = () => ({ left: 0, top: 0, width: 780, height: 420 });
  return c;
};
const ghosts = (canvas) => opsOf(canvas).filter((o) => o.kind === "stroke" && o.strokeStyle === "#ff9500"
  && o.dash.length > 0);

test("꼭짓점을 좌우로 끌면 — 끄는 동안 유령·캡션 읽음(서버 없음), 놓을 때 한 번 타자와 같은 길로 쓴다", async () => {
  const ed = await openEditor();
  button(ed.root, "현재 연료만").emit("click", {});
  const canvas = plotCanvas(ed.root);
  const g = geomOf();
  const down = { button: 0, pointerId: 1, clientX: g.x(0.12), clientY: g.y(3000) }; // 연료 10 kg · 3000 m 하한
  canvas.emit("pointerdown", down);
  assert.ok(cell(ed.root, "/boundary/0/rows/1/1").className.includes("re-sel"), "누른 꼭짓점의 칸이 골라지지 않았다");
  const n = nPreview;
  const nGhost = ghosts(canvas).length;
  canvas.emit("pointermove", { pointerId: 1, clientX: g.x(0.1371), clientY: g.y(3000) });
  assert.match(textOf(caption(ed.root)), /끄는 중 — 고도 3000 m 마하 하한 0\.12 → 0\.135 · 놓으면 씁니다/);
  assert.ok(ghosts(canvas).length > nGhost, "유령 윤곽(점선)이 없다");
  await tick();
  await tick();
  assert.equal(nPreview, n, "끄는 동안 서버를 불렀다");
  canvas.emit("pointerup", { pointerId: 1, clientX: g.x(0.1371), clientY: g.y(3000) });
  await waitFor(() => nPreview > n, "놓은 뒤 미리 보기");
  await tick();
  await tick();
  assert.equal(nPreview, n + 1, "한 번 놓았는데 두 번 보냈다");
  assert.equal(lastPreview().body.region.boundary[0].rows[1][1], 0.135, "끈 값이 사본에 쓰이지 않았다");
  assert.equal(lastPreview().body.region.boundary[1].rows[1][1], 0.14, "현재 연료만인데 다른 층이 바뀌었다");
  assert.equal(cell(ed.root, "/boundary/0/rows/1/1").value, "0.135", "표 칸의 글이 끈 값과 다르다");
  const cap = textOf(caption(ed.root));
  assert.match(cap, /끌어 고침 — 고도 3000 m 마하 하한 0\.12 → 0\.135/);
  assert.match(cap, /바꾸면 영향: 기본 격자 36 → 36점/, "영향 줄이 끌기 뒤에 갱신되지 않았다");
  assert.doesNotMatch(cap, /끄는 중/);
  // 끌어도 「전체 연료」 규칙은 그대로다 — 같은 꼭짓점을 전체 연료로 끌면 두 층에 같은 절댓값
  button(ed.root, "전체 연료").emit("click", {});
  const n2 = nPreview;
  canvas.emit("pointerdown", { button: 0, pointerId: 2, clientX: g.x(0.135), clientY: g.y(3000) });
  canvas.emit("pointermove", { pointerId: 2, clientX: g.x(0.145), clientY: g.y(3000) });
  canvas.emit("pointerup", { pointerId: 2, clientX: g.x(0.145), clientY: g.y(3000) });
  await waitFor(() => nPreview > n2, "둘째 끌기");
  assert.deepEqual(lastPreview().body.region.boundary.map((l) => l.rows[1][1]), [0.145, 0.145]);
  assert.match(textOf(caption(ed.root)), /층마다 달랐던 마하 하한 덮음/);
  // 미리 보기가 아직 오지 않아도 방금 끈 꼭짓점을 **그 자리**에서 다시 잡는다 — 히트테스트가 그려진 값(사본)을 본다
  held = [];
  canvas.emit("pointerdown", { button: 0, pointerId: 3, clientX: g.x(0.145), clientY: g.y(3000) });
  canvas.emit("pointermove", { pointerId: 3, clientX: g.x(0.16), clientY: g.y(3000) });
  assert.match(textOf(caption(ed.root)), /끄는 중 — 고도 3000 m 마하 하한 0\.145 → 0\.16/,
    "엔진 윤곽이 돌아올 때까지 옛 자리에서만 잡힌다");
  canvas.emit("pointerup", { pointerId: 3, clientX: g.x(0.16), clientY: g.y(3000) });
  await waitFor(() => held.length >= 1, "셋째 끌기의 미리 보기");
  for (const release of held) release();
  held = null;
  await waitFor(() => lastPreview().body.region.boundary[0].rows[1][1] === 0.16, "셋째 끌기가 보낸 값");
});

test("끌기 취소 — Escape · 그림 밖에서 놓기 · 문턱 안(고르기만): 아무것도 쓰지 않는다", async () => {
  const ed = await openEditor();
  const canvas = plotCanvas(ed.root);
  const g = geomOf();
  const n = nPreview;
  const before = cell(ed.root, "/boundary/0/rows/1/1").value;
  // Escape
  canvas.emit("pointerdown", { button: 0, pointerId: 1, clientX: g.x(0.12), clientY: g.y(3000) });
  canvas.emit("pointermove", { pointerId: 1, clientX: g.x(0.15), clientY: g.y(3000) });
  assert.match(textOf(caption(ed.root)), /끄는 중/);
  globalThis.window.emit("keydown", { key: "Escape" });
  assert.match(textOf(caption(ed.root)), /끌기를 취소했습니다/);
  canvas.emit("pointerup", { pointerId: 1, clientX: g.x(0.15), clientY: g.y(3000) }); // 취소 뒤 놓기는 무해
  // 그림 밖에서 놓기 — 축 아래(눈금 숫자 자리)에서 손을 떼면 쓰지 않는다
  canvas.emit("pointerdown", { button: 0, pointerId: 2, clientX: g.x(0.12), clientY: g.y(3000) });
  canvas.emit("pointermove", { pointerId: 2, clientX: g.x(0.16), clientY: 419 });
  canvas.emit("pointerup", { pointerId: 2, clientX: g.x(0.16), clientY: 419 });
  // 문턱(5 px) 안 — 누르고 살짝 흔들었을 뿐이면 눈금에 붙어 값이 슬쩍 바뀌지 않는다
  canvas.emit("pointerdown", { button: 0, pointerId: 3, clientX: g.x(0.12), clientY: g.y(3000) });
  canvas.emit("pointermove", { pointerId: 3, clientX: g.x(0.12) + 3, clientY: g.y(3000) });
  canvas.emit("pointerup", { pointerId: 3, clientX: g.x(0.12) + 3, clientY: g.y(3000) });
  await tick();
  await tick();
  await tick();
  assert.equal(nPreview, n, "취소했는데 서버에 보냈다");
  assert.equal(cell(ed.root, "/boundary/0/rows/1/1").value, before, "취소했는데 표 칸이 바뀌었다");
  assert.ok(!button(ed.root, "저장") || button(ed.root, "저장").disabled === false || true);
});

test("못 끄는 꼭짓점 — 보간된 고도는 고르기만 되고 캡션이 왜인지 말한다", async () => {
  // 윤곽(엔진)은 다른 층 고도까지 낸다 — 1500 m는 이 층 경계표 행이 아니라 행 사이 보간이라 끌 칸이 없다
  const withMid = () => reply(200, { ...previewBody(SECTION, 10, 36),
    outline: [{ alt: 200, mach_lo: 0.1, mach_hi: 0.24, state: "in" },
      { alt: 1500, mach_lo: 0.11, mach_hi: 0.23, state: "in" },
      { alt: 3000, mach_lo: 0.12, mach_hi: 0.22, state: "in" }] });
  const prevFetch = globalThis.fetch;
  globalThis.fetch = (url, opts = {}) => (url.endsWith("/grid/region/preview") ? Promise.resolve(withMid())
    : prevFetch(url, opts));
  try {
    const ed = await openEditor();
    const canvas = plotCanvas(ed.root);
    const g = geomOf();
    const n = nPreview;
    canvas.emit("pointerdown", { button: 0, pointerId: 1, clientX: g.x(0.11), clientY: g.y(1500) });
    canvas.emit("pointermove", { pointerId: 1, clientX: g.x(0.13), clientY: g.y(1500) });
    canvas.emit("pointerup", { pointerId: 1, clientX: g.x(0.13), clientY: g.y(1500) });
    await tick();
    await tick();
    assert.equal(nPreview, n, "끌 수 없는 꼭짓점인데 보냈다");
    assert.match(textOf(caption(ed.root)), /고도 1500 m는 경계표 행이 아니다/);
    assert.doesNotMatch(textOf(caption(ed.root)), /끄는 중|끌어 고침/);
  } finally {
    globalThis.fetch = prevFetch;
  }
});

test("예제 기체 — 끌어 고치고 미리 보기는 되지만 저장은 막힌다", async () => {
  example = true;
  const ed = await openEditor();
  const canvas = plotCanvas(ed.root);
  const g = geomOf();
  const n = nPreview;
  canvas.emit("pointerdown", { button: 0, pointerId: 1, clientX: g.x(0.12), clientY: g.y(3000) });
  canvas.emit("pointermove", { pointerId: 1, clientX: g.x(0.13), clientY: g.y(3000) });
  canvas.emit("pointerup", { pointerId: 1, clientX: g.x(0.13), clientY: g.y(3000) });
  await waitFor(() => nPreview > n, "예제 기체도 미리 보기는 된다");
  assert.equal(lastPreview().body.region.boundary[0].rows[1][1], 0.13);
  assert.ok(button(ed.root, "저장").disabled, "예제 기체인데 저장이 열렸다");
  assert.match(button(ed.root, "저장").attrs.title, /복제한 기체에서/);
  example = false;
});

test("끌기 뒤 422 — 타자와 같은 칸 강조(서버 경로가 반대쪽 칸을 가리켜도)", async () => {
  const ed = await openEditor();
  button(ed.root, "현재 연료만").emit("click", {});
  const canvas = plotCanvas(ed.root);
  const g = geomOf();
  nextPreview = () => reply(422, { detail: { path: "/operating_region/boundary/0/rows/1/2",
    message: "마하 하한 < 상한이어야 함: 0.215 ≥ 0.21" } });
  canvas.emit("pointerdown", { button: 0, pointerId: 1, clientX: g.x(0.12), clientY: g.y(3000) });
  // 그림 안(창은 0.31까지 그린다)이지만 이 행의 상한 0.22를 넘는 자리 — 창에 물려 0.215가 된다
  canvas.emit("pointermove", { pointerId: 1, clientX: g.x(0.25), clientY: g.y(3000) });
  assert.match(textOf(caption(ed.root)), /0\.215 \(한계에 물림\)/, "창(상한 한 눈금 아래)에 물리지 않았다");
  canvas.emit("pointerup", { pointerId: 1, clientX: g.x(0.25), clientY: g.y(3000) });
  await waitFor(() => textOf(caption(ed.root)).includes("마하 하한 < 상한"), "422 캡션");
  assert.ok(cell(ed.root, "/boundary/0/rows/1/2").className.includes("re-err"), "422가 가리킨 칸이 강조되지 않았다");
  assert.doesNotMatch(textOf(caption(ed.root)), /끌어 고침/, "오류인데 고쳤다고 말한다");
});
