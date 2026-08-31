// 플롯 수치 계층 검증 — 스케일, 눈금, 마진 상태색, 마진 맵 격자 피벗
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  FALLBACK_CRITERIA,
  SERIES_COLORS,
  STATUS,
  fuelsOf,
  gainPlotGroups,
  gmColor,
  HEATMAP_LAYOUT,
  bodeSeries,
  decadeTicks,
  heatmapCanvasHeight,
  heatmapCellAt,
  heatmapCellWidth,
  interpLogAt,
  linScale,
  logScale,
  marginColor,
  marginLegendText,
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

test("marginColor: 여유 구간 상태색 + 비유한값 정책 (criteria 생략 = 폴백)", () => {
  assert.equal(marginColor(60), STATUS.ok); // 양호 (≥45°)
  assert.equal(marginColor(35), STATUS.warn); // 주의 (30~45°)
  assert.equal(marginColor(10), STATUS.bad); // 부족 (<30°)
  assert.equal(marginColor("inf"), STATUS.ok); // 무한 여유
  assert.equal(marginColor(null), STATUS.na); // 판정 불가 (NaN 직렬화)
});

test("marginColor: 문턱은 인자가 정한다 — 탭마다 다른 판정선을 없앤다", () => {
  // 자동 설계 탭에서 criteria.pm_min_deg를 50으로 올리면 마진 탭도 같이 올라가야
  // 한다. 종전에는 45가 이 함수에 박혀 있어 같은 47° 점을 설계 탭은 fail로,
  // 마진 탭은 초록으로 칠했다 — 한 수치를 두 화면이 다르게 판정한 셈
  const strict = { pm_min_deg: 50, pm_bad_deg: 35 };
  assert.equal(marginColor(47, strict), STATUS.warn); // 폴백이면 ok였을 값
  assert.equal(marginColor(50, strict), STATUS.ok);
  assert.equal(marginColor(34, strict), STATUS.bad); // 폴백이면 warn이었을 값
  // 일부만 넘겨도 나머지는 폴백으로 메운다 (부분 응답에 터지지 않는다)
  assert.equal(marginColor(32, { pm_min_deg: 50 }), STATUS.warn);
  // 비수치 문턱은 무시하고 폴백 — 서버가 null을 내려도 색이 무너지지 않는다
  assert.equal(marginColor(40, { pm_min_deg: null, pm_bad_deg: undefined }), STATUS.warn);
});

test("gmColor: 합격선·목표선 두 층 + 인자 문턱", () => {
  // 목표선(gm_good_db)은 튜너 목표(TuneTargets.gm_db)와 같은 값이라 세 자리가 한
  // 수치를 공유한다 — 화면이 자기 값을 따로 들고 있으면 안 되는 이유
  assert.equal(gmColor(9), STATUS.ok); // ≥8 dB 양호
  assert.equal(gmColor(7), STATUS.warn); // 6~8 주의
  assert.equal(gmColor(3), STATUS.bad); // <6 부족
  assert.equal(gmColor("inf"), STATUS.ok);
  assert.equal(gmColor(null), STATUS.na);
  const strict = { gm_min_db: 8, gm_good_db: 12 };
  assert.equal(gmColor(9, strict), STATUS.warn);
  assert.equal(gmColor(7, strict), STATUS.bad);
  assert.equal(gmColor(12, strict), STATUS.ok);
});

test("marginLegendText: 문턱을 문장에 박는다 (수치를 두 번 적지 않는다)", () => {
  assert.match(marginLegendText(FALLBACK_CRITERIA), /PM ≥45° 양호/);
  assert.match(marginLegendText(FALLBACK_CRITERIA), /GM ≥8 dB 양호/);
  const t = marginLegendText({ pm_min_deg: 50, pm_bad_deg: 35, gm_min_db: 8, gm_good_db: 12 });
  assert.match(t, /PM ≥50° 양호 · 35~50° 주의 · <35° 부족/);
  assert.match(t, /GM ≥12 dB 양호 · 8~12 dB 주의 · <8 dB 부족/);
  // 인자 없으면 폴백 수치가 그대로 문장에 온다 — 화면이 그때 폴백임을 밝힌다
  assert.equal(marginLegendText(undefined), marginLegendText(FALLBACK_CRITERIA));
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

// ── 마진 맵 칸 클릭 → 보드선도 드릴다운 (01 §4.2) ──────────────────────────

const cellEntry = (mach, alt) => ({
  trim: { case: { name: `M${mach}_h${alt}`, mach, alt, fuel: 200 }, converged: true },
  margins: {},
});
const gridPivot = () => pivotCases(
  [cellEntry(0.5, 0), cellEntry(0.6, 0), cellEntry(0.5, 3000), cellEntry(0.6, 3000)], 200);

test("heatmapCellAt — 칸 중앙이 그 칸, 고도축은 위가 큰 값", () => {
  const p = gridPivot();
  const { mL, mT, ch } = HEATMAP_LAYOUT;
  const cw = heatmapCellWidth(p.machs.length, 560);
  // 위쪽 행 = 큰 고도 (heatmapCanvas가 alts를 뒤집어 그린다)
  const top = heatmapCellAt(p, mL + cw / 2, mT + ch / 2, { width: 560 });
  assert.equal(top.mach, 0.5);
  assert.equal(top.alt, 3000);
  assert.equal(top.entry.trim.case.name, "M0.5_h3000");
  const bottomRight = heatmapCellAt(p, mL + cw + cw / 2, mT + ch + ch / 2, { width: 560 });
  assert.equal(bottomRight.mach, 0.6);
  assert.equal(bottomRight.alt, 0);
});

test("heatmapCellAt — 칸 사이 여백은 null (가까운 칸으로 끌어붙이지 않는다)", () => {
  const p = gridPivot();
  const { mL, mT, ch } = HEATMAP_LAYOUT;
  const cw = heatmapCellWidth(p.machs.length, 560);
  // 셀은 cw-3 / ch-3만 칠해진다 — 그 뒤 3 px는 어느 칸도 아니다
  assert.equal(heatmapCellAt(p, mL + cw - 1.5, mT + ch / 2, { width: 560 }), null);
  assert.equal(heatmapCellAt(p, mL + cw / 2, mT + ch - 1.5, { width: 560 }), null);
});

test("heatmapCellAt — 격자 밖·좌측 라벨·cw 상한 우측 여백은 전부 null", () => {
  const p = gridPivot();
  const { mL, mT, ch } = HEATMAP_LAYOUT;
  const cw = heatmapCellWidth(p.machs.length, 560);
  assert.equal(heatmapCellAt(p, mL - 10, mT + ch / 2, { width: 560 }), null); // 고도 라벨
  assert.equal(heatmapCellAt(p, mL + cw / 2, mT - 5, { width: 560 }), null); // 제목
  assert.equal(heatmapCellAt(p, mL + cw / 2, mT + 2 * ch + 5, { width: 560 }), null); // 마하 라벨
  // cw가 90에서 잘려 격자가 width를 다 못 채운다 — 그 우측 여백도 칸이 아니다
  assert.equal(cw, 90);
  assert.equal(heatmapCellAt(p, mL + 2 * cw + 20, mT + ch / 2, { width: 560 }), null);
});

test("heatmapCellAt — 좌표에 케이스가 없으면 entry는 null (칸 자체는 있다)", () => {
  const p = pivotCases([cellEntry(0.5, 0), cellEntry(0.6, 3000)], 200);
  const { mL, mT, ch } = HEATMAP_LAYOUT;
  const cw = heatmapCellWidth(p.machs.length, 560);
  const hole = heatmapCellAt(p, mL + cw / 2, mT + ch / 2, { width: 560 }); // M0.5 @ 3000 없음
  assert.equal(hole.entry, null);
  assert.equal(hole.mach, 0.5);
});

test("logScale — 데케이드가 등간격, 양끝이 range 끝", () => {
  const px = logScale(0.01, 100, 0, 400);
  assert.equal(px(0.01), 0);
  assert.equal(px(100), 400);
  assert.ok(Math.abs(px(1) - 200) < 1e-9);
  // 한 데케이드의 폭이 일정 — log 축의 정의
  assert.ok(Math.abs((px(1) - px(0.1)) - (px(10) - px(1))) < 1e-9);
});

test("decadeTicks — 구간을 덮는 10^k, 좁은 구간은 1·2·5 보조", () => {
  assert.deepEqual(decadeTicks(0.01, 100), [0.01, 0.1, 1, 10, 100]);
  const narrow = decadeTicks(1, 5);
  assert.ok(narrow.length >= 3, narrow);
  assert.ok(narrow.every((t) => t >= 1 && t <= 5), narrow);
  assert.deepEqual(decadeTicks(5, 5), [5]); // 폭 0 — 한 점
});

test("bodeSeries — 비유한 dB는 갭(null), 숫자인 척 0으로 채우지 않는다", () => {
  const s = bodeSeries({
    w: [1, 2, 3, 4],
    mag_db: [10, "-inf", null, -5],
    phase_deg: [-90, -120, -170, -200],
  });
  assert.deepEqual(s.mag, [10, null, null, -5]);
  assert.deepEqual(s.phase, [-90, -120, -170, -200]);
  assert.deepEqual(s.w, [1, 2, 3, 4]);
});

test("heatmapCanvasHeight — 그리기와 클릭 역변환이 같은 논리 높이를 쓴다", () => {
  const { mT, mB, ch } = HEATMAP_LAYOUT;
  assert.equal(heatmapCanvasHeight(3), mT + 3 * ch + mB);
  assert.equal(heatmapCanvasHeight(0), mT + mB);
  // 마지막 행의 아래 끝이 격자 안이어야 한다 — 높이가 짧으면 맨 아래 행이 안 잡힌다
  const p = gridPivot();
  const h = heatmapCanvasHeight(p.alts.length);
  const cw = heatmapCellWidth(p.machs.length, 560);
  const last = heatmapCellAt(p, mL0() + cw / 2, h - mB - 4, { width: 560 });
  assert.notEqual(last, null);
  assert.equal(last.alt, 0); // 맨 아래 행 = 가장 낮은 고도
});

function mL0() { return HEATMAP_LAYOUT.mL; }

test("interpLogAt — log-x 보간, 범위 밖은 가장 가까운 끝값, null은 이웃값", () => {
  const xs = [1, 10, 100];
  const ys = [0, -20, -40];
  assert.equal(interpLogAt(xs, ys, 1), 0);
  assert.equal(interpLogAt(xs, ys, 100), -40);
  assert.ok(Math.abs(interpLogAt(xs, ys, Math.sqrt(10)) - -10) < 1e-9); // 데케이드 중앙
  // 범위 밖 — findIndex가 -1을 내는 자리를 첫 표본으로 접으면 곡선 반대쪽 값이 나온다
  assert.equal(interpLogAt(xs, ys, 1000), -40);
  assert.equal(interpLogAt(xs, ys, 0.1), 0);
  // null 갭은 **알려진 쪽 이웃값**으로 (0으로 채우지 않는다). x=5는 (0, null)
  // 사이라 왼쪽 0, x=50은 (null, -40) 사이라 오른쪽 -40
  assert.equal(interpLogAt(xs, [0, null, -40], 5), 0);
  assert.equal(interpLogAt(xs, [0, null, -40], 50), -40);
  assert.equal(interpLogAt([], [], 1), null);
});
