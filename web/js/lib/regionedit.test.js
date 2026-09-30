// 요구영역 편집 lib — 편집 사본·칸 쓰기(전체 연료 / 현재 연료만)·경계표 세우기·오류 칸·꼭짓점·영향 줄·계보 (node --test)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  addRow, applyCell, boundarySummary, errorCell, errorTarget, fuelChoices, hitVertex, impactLine, impactTip, isLayerFuel, layerIndexAt,
  layerNote, lineageRows, plotScale, removeRow, sameSection, seedBoundary, shownFuels, tableRows, vertexCell,
  workingFromRegion,
} from "./regionedit.js";

// 서버 되울림(Region.to_dict) — 기본 격자 명세는 grid 키
const ECHO = {
  mach: [0.1, 0.24], alt: [200, 3000], fuel: [10, 50],
  boundary: [
    { fuel: 10, rows: [[200, 0.1, 0.24], [3000, 0.12, 0.22]] },
    { fuel: 50, rows: [[200, 0.11, 0.24], [3000, 0.14, 0.22]] },
  ],
  grid: { n_mach: 6, alts: [200, 1000, 3000], fuels: [10, 50] }, confirmed: true, source: "profile",
};
const NO_TABLE = { ...ECHO, boundary: null, confirmed: false, source: "draft:trim_grid" };
// 경계표 없는 영역의 윤곽(엔진 region_outline — 연료 무관) — 고도 합집합: 경계 끝·격자 고도
const OUTLINE = [
  { alt: 200, mach_lo: 0.1, mach_hi: 0.24, state: null },
  { alt: 1000, mach_lo: 0.1, mach_hi: 0.24, state: null },
  { alt: 3000, mach_lo: 0.1, mach_hi: 0.24, state: null },
];

test("workingFromRegion — 되울림(grid) → 절 모양(base_grid), 깊은 사본", () => {
  const w = workingFromRegion(ECHO);
  assert.deepEqual(Object.keys(w), ["mach", "alt", "fuel", "boundary", "base_grid"]);
  assert.deepEqual(w.base_grid, { n_mach: 6, alts: [200, 1000, 3000], fuels: [10, 50] });
  w.boundary[0].rows[0][1] = 9;
  assert.equal(ECHO.boundary[0].rows[0][1], 0.1, "원본을 고쳤다");
  assert.equal(workingFromRegion(null), null);
  assert.equal(workingFromRegion(NO_TABLE).boundary, null);
  // 절 모양(base_grid) 입력도 받는다 — 저장본 문서의 operating_region
  assert.deepEqual(workingFromRegion(w).base_grid, w.base_grid);
  assert.ok(sameSection(workingFromRegion(ECHO), workingFromRegion(ECHO)));
  assert.ok(!sameSection(w, workingFromRegion(ECHO)));
});

test("현재 연료만 — 그 층만 바꾸고 다른 층은 그대로", () => {
  const w = workingFromRegion(ECHO);
  const r = applyCell(w, { path: "/boundary/0/rows/1/1", value: "0.13", scope: "layer" });
  assert.equal(r.error, null);
  assert.equal(r.work.boundary[0].rows[1][1], 0.13);
  assert.equal(r.work.boundary[1].rows[1][1], 0.14, "다른 층이 바뀌었다");
  assert.equal(w.boundary[0].rows[1][1], 0.12, "입력 사본을 고쳤다");
  assert.deepEqual(r.changes, [{ fuel: 10, alt: 3000, col: 1, old: 0.12, value: 0.13, inserted: false, source: null }]);
  assert.equal(layerNote(r.changes), null, "한 층 쓰기는 덮은 층이 없다");
});

test("전체 연료 — 같은 고도 행의 같은 칸에 같은 절댓값, 달랐던 층은 옛 값을 말한다", () => {
  const w = workingFromRegion(ECHO);
  const r = applyCell(w, { path: "/boundary/0/rows/1/1", value: 0.15, scope: "all" });
  assert.deepEqual(r.work.boundary.map((l) => l.rows[1][1]), [0.15, 0.15]);
  assert.deepEqual(r.changes.map((c) => [c.fuel, c.old]), [[10, 0.12], [50, 0.14]]);
  assert.equal(layerNote(r.changes), "층마다 달랐던 마하 하한 덮음 — 10 kg 0.12 · 50 kg 0.14");
  // 층마다 같던 칸(마하 상한 0.22)은 덮은 것이 없다
  const same = applyCell(w, { path: "/boundary/0/rows/1/2", value: 0.2, scope: "all" });
  assert.deepEqual(same.work.boundary.map((l) => l.rows[1][2]), [0.2, 0.2]);
  assert.equal(layerNote(same.changes), null);
});

test("전체 연료 — 그 고도 행이 없는 층엔 그 층의 엔진 윤곽에서 행을 넣고 고친 칸만 덮는다", () => {
  const w = workingFromRegion({ ...ECHO, boundary: [
    { fuel: 10, rows: [[200, 0.1, 0.24], [1500, 0.11, 0.23], [3000, 0.12, 0.22]] },
    { fuel: 50, rows: [[200, 0.11, 0.24], [3000, 0.14, 0.22]] },
  ] });
  // 서버 outlines의 키는 연료 수의 글("50.0") — 수로 짝짓는다
  const outlines = { "10.0": [], "50.0": [{ alt: 1500, mach_lo: 0.125, mach_hi: 0.23, state: "in" }] };
  const r = applyCell(w, { path: "/boundary/0/rows/1/2", value: 0.2, scope: "all", outlines });
  assert.equal(r.error, null);
  // 하한·상한 둘 다 그 층 윤곽 값(0.125 · 0.23)에서 — 고친 칸(상한)만 새 값, 하한은 고친 행(0.11)의 복사가 아니다
  assert.deepEqual(r.work.boundary[1].rows, [[200, 0.11, 0.24], [1500, 0.125, 0.2], [3000, 0.14, 0.22]]);
  assert.deepEqual(r.changes[1], { fuel: 50, alt: 1500, col: 2, old: 0.23, value: 0.2, inserted: true, source: "outline" });
  assert.equal(layerNote(r.changes), "층마다 달랐던 마하 상한 덮음 — 10 kg 0.23 · 50 kg 행 추가(윤곽)");
});

test("전체 연료 — 행 없는 층의 윤곽이 없거나 안(in)이 아니면 지어내지 않고 거부한다", () => {
  const w = workingFromRegion({ ...ECHO, boundary: [
    { fuel: 10, rows: [[200, 0.1, 0.24], [1500, 0.11, 0.23], [3000, 0.12, 0.22]] },
    { fuel: 50, rows: [[200, 0.11, 0.24], [3000, 0.14, 0.22]] },
  ] });
  for (const outlines of [null, {}, { 50: [{ alt: 200, mach_lo: 0.11, mach_hi: 0.24, state: "in" }] },
    { 50: [{ alt: 1500, mach_lo: null, mach_hi: null, state: "undefined" }] },
    { 50: [{ alt: 1500, mach_lo: 0.1, mach_hi: 0.2, state: "out_of_region" }] }]) {
    const r = applyCell(w, { path: "/boundary/0/rows/1/2", value: 0.2, scope: "all", outlines });
    assert.equal(r.work, w, "거부했는데 사본이 바뀌었다");
    assert.deepEqual(r.changes, []);
    assert.equal(r.error.path, "/boundary/0/rows/1/2");
    assert.match(r.error.message, /연료 50 kg 층/);
  }
  // 현재 연료만은 다른 층을 건드리지 않으니 윤곽이 필요 없다
  assert.equal(applyCell(w, { path: "/boundary/0/rows/1/2", value: 0.2, scope: "layer" }).error, null);
});

test("workingFromRegion — 경계표를 엔진 순서(층은 연료, 행은 고도 오름차순)로 — 저장본과 사본이 같은 순서", () => {
  const w = workingFromRegion({ ...ECHO, boundary: [
    { fuel: 50, rows: [[3000, 0.14, 0.22], [200, 0.11, 0.24]] },
    { fuel: 10, rows: [[3000, 0.12, 0.22], [200, 0.1, 0.24]] },
  ] });
  assert.deepEqual(w.boundary, workingFromRegion(ECHO).boundary);
  assert.ok(sameSection(w, workingFromRegion(ECHO)));
});

test("errorTarget — 422 경로를 보낸 사본에서 (연료, 고도, 칸)으로 — 타자 중 재정렬된 색인이 아니라 값으로 짝짓는다", () => {
  const sent = workingFromRegion(ECHO);
  assert.deepEqual(errorTarget({ path: "/operating_region/boundary/1/rows/1/2", message: "x" }, sent),
    { fuel: 50, alt: 3000, col: 2, path: null });
  assert.deepEqual(errorTarget({ path: "/operating_region/mach/1" }, sent),
    { fuel: null, alt: null, col: null, path: "/mach/1" });
  // 보낸 사본이 없으면(로컬 오류 — 칸 자신의 경로) 칸 이름 그대로
  assert.deepEqual(errorTarget({ path: "/boundary/0/rows/1/1" }, null),
    { fuel: null, alt: null, col: null, path: "/boundary/0/rows/1/1" });
  assert.equal(errorTarget(null, sent), null);
});

test("고도 칸 쓰기는 행을 다시 정렬한다 — 색인이 엔진 검증 경로와 맞게", () => {
  const w = workingFromRegion(ECHO);
  const r = applyCell(w, { path: "/boundary/1/rows/0/0", value: 3500, scope: "layer" });
  assert.deepEqual(r.work.boundary[1].rows.map((x) => x[0]), [3000, 3500]);
});

test("경계표가 없으면 첫 편집이 연료 양끝 × 고도 양끝 행을 윤곽에서 세운다 (웹은 보간하지 않는다)", () => {
  const w = workingFromRegion(NO_TABLE);
  assert.deepEqual(fuelChoices(w), [10, 50]);
  const rows = tableRows(w, 50, OUTLINE);
  assert.deepEqual(rows.map((r) => [r.alt, r.lo, r.hi, r.virtual]), [[200, 0.1, 0.24, true], [3000, 0.1, 0.24, true]]);
  assert.deepEqual(rows[1].paths, ["/boundary/1/rows/1/0", "/boundary/1/rows/1/1", "/boundary/1/rows/1/2"]);
  const seeded = seedBoundary(w, OUTLINE);
  assert.deepEqual(seeded.boundary, [
    { fuel: 10, rows: [[200, 0.1, 0.24], [3000, 0.1, 0.24]] },
    { fuel: 50, rows: [[200, 0.1, 0.24], [3000, 0.1, 0.24]] },
  ]);
  assert.equal(w.boundary, null, "입력 사본을 고쳤다");
  // 가상 행의 칸을 고치면 세운 뒤 쓴다 — 칸 이름이 세운 뒤의 색인과 같다
  const r = applyCell(w, { path: rows[1].paths[1], value: 0.13, scope: "layer", outline: OUTLINE });
  assert.deepEqual(r.work.boundary[1].rows[1], [3000, 0.13, 0.24]);
  assert.deepEqual(r.work.boundary[0].rows[1], [3000, 0.1, 0.24]);
  // 윤곽에 고도 끝 행이 없으면 세우지 않는다 — 지어내지 않는다
  const bad = applyCell(w, { path: "/boundary/0/rows/0/1", value: 0.2, outline: OUTLINE.slice(1) });
  assert.match(bad.error.message, /고도 200 m 행이 없어/);
  assert.equal(bad.work, w);
  assert.throws(() => seedBoundary(w, null), /윤곽에/);
  // 연료·고도 범위가 한 점이면 층·행도 하나
  const flat = seedBoundary({ ...w, fuel: [30, 30], alt: [500, 500] }, [{ alt: 500, mach_lo: 0.1, mach_hi: 0.2 }]);
  assert.deepEqual(flat.boundary, [{ fuel: 30, rows: [[500, 0.1, 0.2]] }]);
});

test("범위·기본 격자 칸 — 수치가 아니면 사본 그대로, 오류는 그 칸 경로", () => {
  const w = workingFromRegion(ECHO);
  assert.equal(applyCell(w, { path: "/mach/1", value: "0.3" }).work.mach[1], 0.3);
  assert.equal(applyCell(w, { path: "/base_grid/n_mach", value: "8" }).work.base_grid.n_mach, 8);
  assert.deepEqual(applyCell(w, { path: "/base_grid/alts", value: "200, 2000 3000" }).work.base_grid.alts,
    [200, 2000, 3000]);
  const e1 = applyCell(w, { path: "/alt/0", value: "abc" });
  assert.equal(e1.work, w);
  assert.equal(e1.error.path, "/alt/0");
  assert.equal(applyCell(w, { path: "/base_grid/n_mach", value: "2.5" }).error.path, "/base_grid/n_mach");
  assert.equal(applyCell(w, { path: "/base_grid/fuels", value: "1, x" }).error.path, "/base_grid/fuels");
  assert.equal(applyCell(w, { path: "/boundary/0/rows/1/1", value: "" }).error.path, "/boundary/0/rows/1/1");
  assert.match(applyCell(w, { path: "/boundary/5/rows/0/1", value: 1 }).error.message, /없는 행/);
  assert.match(applyCell(w, { path: "/nope", value: 1 }).error.message, /모르는 칸/);
});

test("행 추가·지우기 — 층 범위, 마지막 행은 지우지 않는다", () => {
  const w = workingFromRegion(ECHO);
  const a = addRow(w, { fuel: 50, row: ["1500", 0.12, 0.23], scope: "layer" });
  assert.deepEqual(a.work.boundary[1].rows.map((r) => r[0]), [200, 1500, 3000]);
  assert.equal(a.work.boundary[0].rows.length, 2);
  const all = addRow(w, { fuel: 50, row: [1500, 0.12, 0.23], scope: "all" });
  assert.deepEqual(all.work.boundary.map((l) => l.rows.length), [3, 3]);
  assert.match(addRow(w, { fuel: 10, row: [200, 0.1, 0.2] }).error.message, /이미 있다/);
  assert.match(addRow(w, { fuel: 10, row: [200, "x", 0.2] }).error.message, /세 수치/);
  const d = removeRow(all.work, { fuel: 10, alt: 1500, scope: "all" });
  assert.deepEqual(d.work.boundary.map((l) => l.rows.length), [2, 2]);
  const one = workingFromRegion({ ...ECHO, boundary: [{ fuel: 10, rows: [[200, 0.1, 0.2]] }] });
  assert.match(removeRow(one, { fuel: 10, alt: 200 }).error.message, /마지막 행/);
  assert.match(removeRow(workingFromRegion(NO_TABLE), { fuel: 10, alt: 200 }).error.message, /경계표가 없다/);
});

test("errorCell — 서버 422 경로 → 표의 칸 (접두 떼기·목록 원소와 행은 담는 칸으로)", () => {
  assert.deepEqual(errorCell("/operating_region/boundary/1/rows/0/2"),
    { cell: "/boundary/1/rows/0/2", layer: 1, row: 0, col: 2 });
  assert.equal(errorCell("/boundary/0/rows/3").cell, "/boundary/0/rows/3/0");
  assert.deepEqual(errorCell("/operating_region/boundary/1/fuel"), { cell: null, layer: 1, row: null, col: null });
  assert.equal(errorCell("/operating_region/mach/1").cell, "/mach/1");
  assert.equal(errorCell("/operating_region/mach").cell, "/mach/0");
  assert.equal(errorCell("/operating_region/base_grid/alts/2").cell, "/base_grid/alts");
  assert.equal(errorCell("/operating_region/base_grid").cell, "/base_grid/n_mach");
  assert.equal(errorCell("/operating_region").cell, null);
  assert.equal(errorCell(null).cell, null);
});

test("hitVertex — 반경 안의 가장 가까운 꼭짓점, 마하 없는 행은 꼭짓점이 없다 → vertexCell", () => {
  const scale = { x: (m) => m * 1000, y: (a) => 1000 - a / 10 };
  const outline = [...OUTLINE, { alt: 3500, mach_lo: null, mach_hi: null, state: "undefined" }];
  const h = hitVertex(outline, 243, 700, scale); // (0.24, 3000) 은 (240, 700)
  assert.deepEqual([h.alt, h.side, h.mach], [3000, "hi", 0.24]);
  assert.equal(hitVertex(outline, 300, 700, scale), null, "반경 밖");
  assert.equal(hitVertex(outline, 240, 650, { ...scale, r: 4 }), null);
  const w = workingFromRegion(ECHO);
  assert.equal(vertexCell(w, 50, h), "/boundary/1/rows/1/2");
  assert.equal(vertexCell(w, 50, { alt: 1000, side: "lo" }), null, "보간된 고도는 표의 칸이 아니다");
  const nt = workingFromRegion(NO_TABLE);
  assert.equal(vertexCell(nt, 10, { alt: 200, side: "lo" }, OUTLINE), "/boundary/0/rows/0/1", "가상 행");
  assert.equal(vertexCell(nt, 10, { alt: 1000, side: "hi" }, OUTLINE), "/mach/1", "경계표 없으면 기본 범위");
  assert.equal(layerIndexAt(w, 50), 1);
  assert.equal(layerIndexAt(w, 30), -1);
});

test("impactLine — 기본 격자 전후·유지·새 트림·빠짐·낡는 결과, 달랐던 층 덮음을 덧붙인다", () => {
  // 서버 모양 — grid_diff는 수, reused·new_trims는 impact 바로 아래, stale은 소비자 상태 {what, status, label}
  const impact = {
    grid: { before: 36, after: 40, kept: 30, added: 10, dropped: 6 }, reused: 12, new_trims: 7,
    stale: [{ what: "de_trim", status: "stale", label: "δe_trim 표 — 다른 요구영역에서 도출됨 · 다시 도출 필요" },
      { what: "gain_tables", status: "no_record", label: "확정 게인 표 — 요구영역 기록 없음" },
      { what: "trim_store", status: "reused", label: "트림 저장소 — 재사용 · 요구영역과 무관(플랜트 키)" }],
  };
  assert.equal(impactLine(impact), "바꾸면 영향: 기본 격자 36 → 40점 (유지 30 · 새 트림 7 · 빠짐 6) · 낡는 결과: "
    + "δe_trim 표 (기록 없어 모름: 확정 게인 표)");
  // 점 목록도 센다 · 낡는 것이 없으면 「없음」
  assert.equal(impactLine({ grid: { before: ["a", "b", "c"], after: ["a", "b", "c"], kept: 3, added: 0, dropped: [] },
    new_trims: 0, stale: [{ what: "de_trim", status: "current" }, { what: "gain_tables", status: "absent" }] }),
  "바꾸면 영향: 기본 격자 3 → 3점 (유지 3 · 새 트림 0 · 빠짐 0) · 낡는 결과: 없음");
  const changes = [
    { fuel: 10, alt: 3000, col: 1, old: 0.12, value: 0.15, inserted: false },
    { fuel: 50, alt: 3000, col: 1, old: 0.14, value: 0.15, inserted: false },
  ];
  assert.match(impactLine(impact, { changes }), / · 층마다 달랐던 마하 하한 덮음 — 10 kg 0\.12 · 50 kg 0\.14$/);
  assert.equal(impactLine(null), null);
  assert.match(impactTip(impact), /재사용 12점/);
  assert.match(impactTip(impact), /δe_trim 표 — 다른 요구영역에서 도출됨/);
});

test("lineageRows — 최신이 위, 지금 판 표시, 요구영역 없는 리비전", () => {
  const rows = lineageRows([
    { revision: 1, region_key: null, confirmed: null, source: null, n_points: null },
    { revision: 4, unreadable: true, reason: "스키마 v2 — 올리지 못함" },
    { revision: 3, region_key: "abc123abc123", confirmed: true, source: "profile", mach: [0.1, 0.24], alt: [200, 3000],
      fuel: [10, 50], n_points: 40 },
    { revision: 2, region_key: "def456def456", confirmed: false, source: "draft:trim_grid", mach: [0.1, 0.3],
      alt: [0, 3000], fuel: [10, 50], n_points: 36 },
  ], { region_key: "abc123abc123" });
  assert.deepEqual(rows.map((r) => [r.revision, r.state, r.current]),
    [[4, "못 읽음", false], [3, "확정", true], [2, "초안", false], [1, "없음", false]]);
  assert.equal(rows[0].source, "스키마 v2 — 올리지 못함");
  assert.equal(rows[1].range, "마하 0.1–0.24 · 고도 200–3000 m · 연료 10–50 kg");
  assert.equal(rows[1].points, 40);
  assert.equal(rows[3].range, "—");
  assert.equal(rows[3].points, null);
  assert.deepEqual(lineageRows(null), []);
  assert.equal(boundarySummary(workingFromRegion(ECHO)), "경계표 2층 · 4행");
  assert.equal(boundarySummary(workingFromRegion(NO_TABLE)), "경계표 없음");
});

test("plotScale — 요구 범위·모델 마하·점을 덮는 창, 고도는 위로 증가", () => {
  const w = workingFromRegion(ECHO);
  const s = plotScale({ work: w, model: { mach: [0.05, 0.3], fuel: [0, 50] }, points: [{ mach: 0.35, alt: 200 }],
    width: 600, height: 400 });
  assert.ok(s.x(0.05) >= s.mL && s.x(0.35) <= 600 - s.mR, "모델 하한·점이 창 안");
  assert.ok(s.y(3000) < s.y(200), "고도가 위로 증가");
  assert.ok(s.y(200) <= 400 - s.mB && s.y(3000) >= s.mT);
  // 모델 마하 미기재 · 한 점짜리 고도 범위도 창이 선다(0 폭 나눗셈 없음)
  const flat = plotScale({ work: { ...w, alt: [500, 500] }, model: { mach: null }, points: [], width: 600, height: 400 });
  assert.ok(Number.isFinite(flat.y(500)) && Number.isFinite(flat.x(0.1)));
  assert.equal(plotScale({ work: null, width: 10, height: 10 }), null);
});

test("연료 칩 — 편집할 층 ∪ 기본 격자 연료, 층이 아닌 연료는 보기만", () => {
  const w = workingFromRegion({ ...ECHO, grid: { n_mach: 6, alts: [200], fuels: [25, 50] } });
  assert.deepEqual(shownFuels(w), [10, 25, 50]);
  assert.equal(isLayerFuel(w, 25), false);
  assert.equal(isLayerFuel(w, 50), true);
  assert.deepEqual(tableRows(w, 25, OUTLINE), [], "층 사이 연료엔 편집할 행이 없다");
  assert.deepEqual(shownFuels(workingFromRegion(NO_TABLE)), [10, 50]);
  assert.deepEqual(shownFuels(null), []);
});
