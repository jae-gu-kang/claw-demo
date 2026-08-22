// 플롯 수치 계층 검증 — 스케일, 눈금, 마진 상태색, 마진 맵 격자 피벗
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  SERIES_COLORS,
  STATUS,
  fuelsOf,
  gainPlotGroups,
  linScale,
  marginColor,
  niceTicks,
  pivotCases,
  planeViews,
  trimEnvelopeCell,
} from "./plot.js";

test("linScale: 선형 사상·역방향 범위", () => {
  const s = linScale(0, 10, 0, 100);
  assert.equal(s(5), 50);
  const flip = linScale(0, 10, 100, 0); // 캔버스 y축 (아래로 증가)
  assert.equal(flip(0), 100);
  assert.equal(flip(10), 0);
});

test("niceTicks: 1-2-5 스텝, 범위 포함", () => {
  assert.deepEqual(niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(niceTicks(0.4, 0.8, 5), [0.4, 0.5, 0.6, 0.7, 0.8]);
  assert.deepEqual(niceTicks(5, 5, 5), [5]); // 퇴화 구간
});

test("marginColor: 여유 구간 상태색 + 비유한값 정책", () => {
  assert.equal(marginColor(60), STATUS.ok); // 양호 (≥45°)
  assert.equal(marginColor(35), STATUS.warn); // 주의 (30~45°)
  assert.equal(marginColor(10), STATUS.bad); // 부족 (<30°)
  assert.equal(marginColor("inf"), STATUS.ok); // 무한 여유
  assert.equal(marginColor(null), STATUS.na); // 판정 불가 (NaN 직렬화)
});

test("trimEnvelopeCell: 판정 우선순위 — 불가 > 실속 근접 > 포화 > 가능", () => {
  const base = { residual_ok: true, saturation_ok: true, alpha_margin_ok: true,
                 continuity_ok: true };
  const cell = (converged, flags) => trimEnvelopeCell({ converged, flags });
  assert.equal(cell(true, base).kind, "ok");
  assert.equal(cell(false, base).kind, "infeasible"); // 미수렴
  assert.equal(cell(true, { ...base, residual_ok: false }).kind, "infeasible");
  // α 여유 위반이 포화보다 우선 (더 치명적 — 실속 경계 접근)
  assert.equal(
    cell(true, { ...base, alpha_margin_ok: false, saturation_ok: false }).kind,
    "stall",
  );
  assert.equal(cell(true, { ...base, saturation_ok: false }).kind, "saturated");
  // 연속성 미판정(null)은 가능 판정에 영향 없음 (3-상태)
  assert.equal(cell(true, { ...base, continuity_ok: null }).kind, "ok");
  // 색·라벨 존재
  const c = cell(true, base);
  assert.ok(c.color.startsWith("#") && c.text.length > 0);
});


function entry(mach, alt, fuel, pm) {
  return {
    trim: { case: { mach, alt, fuel }, converged: true },
    margins: { pitch_q: { pm_deg: pm } },
  };
}

function gainTable(machs, data) {
  return { axes: { mach: machs }, data, extrapolate: "clip" };
}

test("gainPlotGroups: '그룹.게인' 접두부 묶기 + 등장 순서 + 색 배정", () => {
  const machs = [0.2, 0.4, 0.6];
  const { groups, skipped } = gainPlotGroups({
    "pitch.kp": gainTable(machs, [-4, -3, -2]),
    "pitch.ki": gainTable(machs, [-1, -0.7, -0.5]),
    "roll.kp": gainTable(machs, [2, 1.5, 1]),
  });
  assert.equal(skipped.length, 0);
  assert.deepEqual(groups.map((g) => g.group), ["pitch", "roll"]);
  const pitch = groups[0];
  assert.deepEqual(pitch.mach, machs);
  assert.deepEqual(pitch.series.map((s) => s.label), ["kp", "ki"]);
  assert.deepEqual(pitch.series[0].data, [-4, -3, -2]);
  // 그룹 내 시리즈 순번으로 색 배정 — 그룹이 달라지면 순번 리셋
  assert.equal(pitch.series[0].color, SERIES_COLORS[0]);
  assert.equal(pitch.series[1].color, SERIES_COLORS[1]);
  assert.equal(groups[1].series[0].color, SERIES_COLORS[0]);
});

test("gainPlotGroups: 1D mach 아닌 테이블은 사유와 함께 제외", () => {
  const { groups, skipped } = gainPlotGroups({
    "pitch.kp": gainTable([0.2, 0.6], [-4, -2]),
    "pitch.k2d": { axes: { mach: [0.2, 0.6], alt: [0, 1000] }, data: [[1, 2], [3, 4]] },
    "yaw.k_alpha": { axes: { alpha: [0, 0.1] }, data: [1, 2] },
  });
  assert.deepEqual(groups.map((g) => g.group), ["pitch"]);
  assert.equal(groups[0].series.length, 1);
  assert.deepEqual(skipped.map((s) => s.name), ["pitch.k2d", "yaw.k_alpha"]);
  assert.ok(skipped.every((s) => s.reason.length > 0));
});

test("gainPlotGroups: 그룹 내 mach 축 불일치는 제외 (차트가 x축 공유)", () => {
  const { groups, skipped } = gainPlotGroups({
    "pitch.kp": gainTable([0.2, 0.4, 0.6], [-4, -3, -2]),
    "pitch.ki": gainTable([0.2, 0.5, 0.6], [-1, -0.7, -0.5]), // 축 다름
  });
  assert.equal(groups[0].series.length, 1);
  assert.equal(skipped.length, 1);
  assert.equal(skipped[0].name, "pitch.ki");
});

test("gainPlotGroups: 생성된 그룹은 시리즈 ≥ 1 보장 (첫 테이블이 그룹을 만들며 진입)", () => {
  const { groups } = gainPlotGroups({
    "yaw.k2d": { axes: { mach: [0.2], alt: [0] }, data: [[1]] }, // 그룹 미생성 (2D)
    "pitch.kp": gainTable([0.2, 0.6], [-4, -2]),
    "pitch.ki": gainTable([0.2, 0.5], [-1, -0.5]), // 축 불일치 — 그룹은 남고 시리즈만 제외
  });
  assert.ok(groups.every((g) => g.series.length >= 1));
  assert.deepEqual(groups.map((g) => g.group), ["pitch"]);
});

test("pivotCases: 연료 필터 + 축 정렬 + 조회", () => {
  const entries = [
    entry(0.6, 1000, 200, 50), entry(0.4, 1000, 200, 40),
    entry(0.4, 100, 200, 45), entry(0.6, 100, 200, 55),
    entry(0.5, 1000, 300, 60), // 다른 연료 — 제외돼야 함
  ];
  const p = pivotCases(entries, 200);
  assert.deepEqual(p.machs, [0.4, 0.6]);
  assert.deepEqual(p.alts, [100, 1000]);
  assert.equal(p.at(0.4, 1000).margins.pitch_q.pm_deg, 40);
  assert.equal(p.at(0.5, 1000), null); // 빈 셀
  assert.deepEqual(fuelsOf(entries), [200, 300]);
});

const SIG = { pn: [0, 100, 200], pe: [0, 10, 20], h: [1000, 1010, 1020] };

test("planeViews: 3면도 축 배정 — N–E 평면만 등축", () => {
  const views = planeViews(SIG);
  assert.deepEqual(views.map((v) => v.key), ["ne", "nd", "ed"]);
  // 축 배정: N–E는 E(가로)×N(세로), 연직 평면은 수평좌표(가로)×고도(세로)
  assert.deepEqual(views.map((v) => [v.xs, v.ys]), [
    [SIG.pe, SIG.pn], [SIG.pn, SIG.h], [SIG.pe, SIG.h],
  ]);
  // 등축은 N–E만 — 연직 평면까지 등축이면 고도 변화가 직선으로 뭉개진다
  assert.deepEqual(views.map((v) => v.equal), [true, false, false]);
});

test("planeViews: 평면 이름은 NED 축 (XY/YZ/ZX 표기 금지 — 내부 좌표가 NED)", () => {
  for (const v of planeViews(SIG)) {
    assert.match(v.title, /^[NE]–[ED] 평면/);
    assert.doesNotMatch(v.title, /XY|YZ|ZX/);
  }
});

test("planeViews: 배열은 복사 없이 참조 — 재렌더가 최신 신호를 본다", () => {
  const views = planeViews(SIG);
  assert.equal(views[0].ys, SIG.pn); // deepEqual이 아닌 동일성
  assert.equal(views[1].ys, SIG.h);
});

test("planeViews: wpIdx는 가로축 성분 — 웨이포인트 [n, e] 색인", () => {
  const [ne, nd, ed] = planeViews(SIG);
  assert.equal(ne.wpIdx, null); // N–E는 도달반경 원으로 직접 그림
  assert.equal(nd.wpIdx, 0); // 가로축 N → wp[0]
  assert.equal(ed.wpIdx, 1); // 가로축 E → wp[1]
  // 색인이 가로축 라벨과 어긋나면 안내선이 엉뚱한 곳에 선다
  for (const v of [nd, ed]) assert.ok(v.xLabel.startsWith(["N", "E"][v.wpIdx]));
});

test("planeViews: 연직축 라벨에 부호 규약 명시 (D 하방 양 → h = −D)", () => {
  const views = planeViews(SIG);
  for (const v of views.slice(1)) assert.match(v.yLabel, /−D/);
  assert.equal(views[0].yLabel, "N [m]"); // N–E 평면에는 붙지 않음
});
