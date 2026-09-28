// 플롯 수치 계층 검증 — 스케일, 눈금, 마진 상태색, 마진 맵 격자 피벗
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  SERIES_COLORS,
  STATUS,
  fuelsOf,
  gainPlotGroups,
  HEATMAP_LAYOUT,
  bodeSeries,
  decadeTicks,
  heatmapCanvasHeight,
  heatmapCellAt,
  heatmapCellWidth,
  interpLogAt,
  linScale,
  logScale,
  OLD_RESULT_HINT,
  STATUS_LABEL,
  criteriaLineText,
  hasMarginStatuses,
  marginCellStatus,
  marginLegendText,
  statusColor,
  marginWorst,
  niceTicks,
  pivotCases,
  planeViews,
  TRIM_CELL_LABEL,
  TRIM_FLAG_LABEL,
  coincidentGroups,
  coincidentNote,
  curveSpread,
  nearOverlapNote,
  pctText,
  trimCueReport,
  trimFlagSummary,
  trimCurves,
  trimEnvelopeCell,
  wpAlt,
  wpMarks,
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

test("statusColor: 판정 넷 → 상태색, 모르는 값은 판정 불가", () => {
  assert.equal(statusColor("fail"), STATUS.bad);
  assert.equal(statusColor("warn"), STATUS.warn);
  assert.equal(statusColor("ok"), STATUS.ok);
  assert.equal(statusColor("na"), STATUS.na);
  assert.equal(statusColor(undefined), STATUS.na);
  assert.equal(statusColor("bogus"), STATUS.na);
});

test("STATUS_LABEL: 엔진 STATUSES 순서·화면 이름 넷", () => {
  assert.deepEqual(Object.keys(STATUS_LABEL), ["fail", "warn", "ok", "na"]);
  assert.deepEqual(Object.values(STATUS_LABEL), ["불합격", "합격·주의", "합격·권장 충족", "판정 불가"]);
});

test("marginCellStatus: 서버 판정을 읽는다 — PM 35° + fail은 불합격(주의가 아니다)", () => {
  const m = { pm_deg: 35, gm_db: 7, pm_status: "fail", gm_status: "warn", status: "fail" };
  assert.equal(marginCellStatus(m, "pm_deg"), "fail");
  assert.equal(statusColor(marginCellStatus(m, "pm_deg")), STATUS.bad); // 종전 문턱 색칠은 주의(주황)였다
  assert.equal(marginCellStatus(m, "gm_db"), "warn");
  // 수치가 아니라 판정을 따른다 — 기체 기준이 PM 30°면 서버가 ok를 싣고 화면도 ok
  assert.equal(marginCellStatus({ pm_deg: 35, pm_status: "ok" }, "pm_deg"), "ok");
});

test("marginCellStatus: 옛 결과(판정 없음)·마진 없음은 na — 브라우저가 다시 판정하지 않는다", () => {
  assert.equal(marginCellStatus({ pm_deg: 35, gm_db: 3 }, "pm_deg"), "na");
  assert.equal(marginCellStatus({ pm_deg: 60, gm_db: 12 }, "gm_db"), "na");
  assert.equal(statusColor(marginCellStatus({ pm_deg: 60 }, "pm_deg")), STATUS.na);
  assert.equal(marginCellStatus(undefined, "pm_deg"), "na");
  assert.equal(marginCellStatus({ pm_deg: 60, pm_status: "weird" }, "pm_deg"), "na");
});

test("marginCellStatus: 폐루프 발산 칸도 색은 서버 판정 그대로 — 웹이 덮어쓰지 않는다", () => {
  // 서버가 발산을 판정에 접어 넣는다(나선 예외 규칙 포함) — 서버가 fail이라 했으면 fail
  const failed = { pm_deg: 80, pm_status: "fail", gm_status: "fail", closed_loop: { stable: false } };
  assert.equal(marginCellStatus(failed, "pm_deg"), "fail");
  assert.equal(statusColor(marginCellStatus(failed, "gm_db")), STATUS.bad);
  // 서버가 예외(예: 느린 나선)로 합격을 줬다면 웹이 불합격으로 뒤집지 않는다
  const exempt = { pm_deg: 80, pm_status: "ok", gm_status: "warn", closed_loop: { stable: false } };
  assert.equal(marginCellStatus(exempt, "pm_deg"), "ok");
  assert.equal(marginCellStatus(exempt, "gm_db"), "warn");
});

test("hasMarginStatuses: 옛 결과 가리기", () => {
  const fresh = { cases: [{ margins: { q: { pm_deg: 50, pm_status: "ok" } } }] };
  const old = { cases: [{ margins: { q: { pm_deg: 50 } } }, { margins: {} }] };
  assert.equal(hasMarginStatuses(fresh), true);
  assert.equal(hasMarginStatuses(old), false);
  assert.equal(hasMarginStatuses({ cases: [{ margins: {} }] }), true); // 마진이 없으면 말할 게 없다
  assert.match(OLD_RESULT_HINT, /옛 결과/);
});

const CRIT = {
  applied: { margin: { pm_min_deg: 45, gm_min_db: 6, gm_good_db: 8 } },
  lines: [
    { metric: "pm_deg", label: "위상여유 PM", unit: "°", direction: "min", pass_key: "pm_min_deg", rec_key: null },
    { metric: "gm_db", label: "이득여유 GM", unit: "dB", direction: "min", pass_key: "gm_min_db", rec_key: "gm_good_db" },
  ],
  echo: { judgement_fingerprint: "aaa" },
};

test("criteriaLineText·marginLegendText: 기체 기준(applied·lines)에서 판정선 문장", () => {
  assert.equal(criteriaLineText(CRIT, "pm_deg"), "위상여유 PM ≥45° 합격");
  assert.equal(criteriaLineText(CRIT, "gm_db"), "이득여유 GM ≥6 dB 합격 · ≥8 dB 권장");
  const strict = { ...CRIT, applied: { margin: { pm_min_deg: 50, gm_min_db: 8, gm_good_db: 12 } } };
  assert.match(marginLegendText(strict), /PM ≥50° 합격.*GM ≥8 dB 합격 · ≥12 dB 권장/);
  assert.match(marginLegendText(CRIT), /불합격 · 합격·주의 · 합격·권장 충족 · 판정 불가/);
  // 기준을 못 읽으면 수치를 지어내지 않는다 — 색 이름만
  assert.equal(criteriaLineText(null, "pm_deg"), null);
  assert.doesNotMatch(marginLegendText(null), /≥/);
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

const trimRow = (mach, alt, fuel, { theta = 0.05, thr = 0.5, de = -0.01, converged = true } = {}) => ({
  case: { mach, alt, fuel, name: `M${mach}-${alt}` },
  converged,
  euler: [0.0, theta, 0.0],
  control: { elevon: [de, de], throttle: [thr, thr] },
});

test("trimCurves: 연료 필터 + 축 정렬 + 고도별 시리즈", () => {
  const rows = [
    trimRow(0.6, 1000, 200, { theta: 0.02, thr: 0.6, de: -0.03 }),
    trimRow(0.4, 1000, 200, { theta: 0.08, thr: 0.4, de: -0.01 }),
    trimRow(0.4, 0, 200, { theta: 0.09 }),
    trimRow(0.6, 0, 200, { theta: 0.03 }),
    trimRow(0.5, 0, 300), // 다른 연료 — 제외
  ];
  const c = trimCurves(rows, 200);
  assert.deepEqual(c.machs, [0.4, 0.6]);
  assert.deepEqual(c.alts, [0, 1000]);
  assert.deepEqual(c.series.alpha.map((s) => s.alt), [0, 1000]);
  // data는 machs 순서 — 입력 순서(0.6 먼저)가 아니라 정렬된 축 순서
  assert.deepEqual(c.series.alpha[1].data, [0.08, 0.02]);
  assert.deepEqual(c.series.throttle[1].data, [0.4, 0.6]);
  assert.deepEqual(c.series.de[1].data, [-0.01, -0.03]);
});

test("trimCurves: 미수렴·빈 조합은 null — 곡선을 끊지 값을 위조하지 않는다", () => {
  const rows = [
    trimRow(0.4, 0, 200),
    trimRow(0.5, 0, 200, { converged: false }),
    trimRow(0.6, 0, 200),
    trimRow(0.4, 3000, 200), // 3000 m는 0.4만 있다 — 나머지 마하는 빈 조합
  ];
  const c = trimCurves(rows, 200);
  assert.deepEqual(c.machs, [0.4, 0.5, 0.6]);
  assert.equal(c.series.alpha[0].data[1], null); // 미수렴
  assert.deepEqual(c.series.throttle[1].data, [0.5, null, null]); // 빈 조합
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

test("wpMarks: 고도가 있으면 세로축 값으로 함께 나온다 (평면 정보만 그리던 회귀)", () => {
  const [, nd, ed] = planeViews(SIG);
  const wps = [[3000, 2000, 600], [6000, -1000, 400]];
  // 측면도 가로축은 N, 정면도는 E — 어느 쪽이든 alt는 같은 세로축 값이다
  assert.deepEqual(wpMarks(wps, nd.wpIdx), [{ x: 3000, alt: 600 }, { x: 6000, alt: 400 }]);
  assert.deepEqual(wpMarks(wps, ed.wpIdx), [{ x: 2000, alt: 600 }, { x: -1000, alt: 400 }]);
});

test("wpMarks: 고도 없는 열은 alt null — 0으로 메우면 넣지 않은 해면 고도를 그린다", () => {
  assert.deepEqual(wpMarks([[100, 200], [300, 400]], 0),
    [{ x: 100, alt: null }, { x: 300, alt: null }]);
});

test("wpMarks: 비수치는 행을 버리지 않고 null — 걸러내면 색인이 밀린다", () => {
  const marks = wpMarks([[0, 0, 100], [null, 5, 200], [10, 20, "높이"]], 0);
  assert.equal(marks.length, 3); // 3번 웨이포인트가 사라지지 않는다
  assert.deepEqual(marks[1], { x: null, alt: 200 });
  assert.deepEqual(marks[2], { x: 10, alt: null }); // 좌표는 살고 고도만 미상
});

test("wpMarks: 웨이포인트가 없으면 빈 목록 (null 입력도)", () => {
  assert.deepEqual(wpMarks([], 0), []);
  assert.deepEqual(wpMarks(null, 0), []);
});

test("wpAlt: '고도가 있는가'의 단일 정본 — 세 그리기가 같은 판정을 본다", () => {
  assert.equal(wpAlt([100, 200, 300]), 300);
  assert.equal(wpAlt([100, 200]), null); // 2열 = 고도 없음 (0이 아니다)
  assert.equal(wpAlt([100, 200, null]), null); // JSON 직렬화 null
  assert.equal(wpAlt([100, 200, NaN]), null);
  assert.equal(wpAlt([100, 200, "300"]), null); // 문자열은 수치가 아니다
  assert.equal(wpAlt([100, 200, 0]), 0); // 해면 고도는 **있는** 값이다
  assert.equal(wpAlt(null), null);
  // wpMarks·bounds3d·3D 그리기가 이 함수를 쓴다 — 사본이 생기면 갈린다
  assert.equal(wpMarks([[1, 2, 3]], 0)[0].alt, wpAlt([1, 2, 3]));
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

test("trimCueReport — 지도 셀 판정 종류별 개수, 범례와 같은 라벨·「가능」은 늘 적는다", () => {
  const row = (name, converged, flags, fuel = 10) => ({ case: { name, fuel }, converged, flags });
  const ok = { residual_ok: true, saturation_ok: true, alpha_margin_ok: true, continuity_ok: true };
  const r = trimCueReport([
    row("a", true, ok), row("b", true, ok, 50), row("c", true, { ...ok, alpha_margin_ok: false }),
    row("d", false, { ...ok, residual_ok: false }, 50),
  ]);
  assert.equal(r.summary,
    `4 케이스 — ${TRIM_CELL_LABEL.ok} 2 · ${TRIM_CELL_LABEL.stall} 1 · ${TRIM_CELL_LABEL.infeasible} 1`
    + " · 판정 플래그 위반 2건 확인 필요 (잔차 1 · α여유 1)");
  assert.deepEqual(r.data, { cases: 4, converged: 3, fuels: [10, 50],
    counts: { ok: 2, stall: 1, saturated: 0, infeasible: 1 },
    flag_violations: { cases: 2, by_flag: { alpha_margin_ok: 1, residual_ok: 1 }, names: ["c", "d"] } });
  // 전부 불가여도 「가능 0」은 적는다 — 없는 성공을 숨기지 않는다. 플래그가 없는 행은 위반이 아니다(미판정)
  assert.equal(trimCueReport([row("d", false, {})]).summary, `1 케이스 — ${TRIM_CELL_LABEL.ok} 0 · ${TRIM_CELL_LABEL.infeasible} 1`);
});

// 쇼케이스 결함 D6 — 진행 카드 줄이 「가능 20」이라 하는 사이 탭 머리줄은 「판정 플래그 위반 3건 확인 필요」였다.
// 지도 셀(가능)은 연속성 플래그를 보지 않는다 — 보고가 셀 집계만 말하면 탭 자신의 경고를 가린다
test("trimCueReport — 지도 셀이 「가능」이어도 판정 플래그 위반은 탭 머리줄과 같은 말로 싣는다", () => {
  const row = (name, flags) => ({ case: { name, fuel: 10 }, converged: true, flags });
  const ok = { residual_ok: true, saturation_ok: true, alpha_margin_ok: true, continuity_ok: true };
  const rows = [
    row("M0.12_h3000_f10", { ...ok, continuity_ok: false }), row("M0.15_h3000_f10", ok),
    row("M0.18_h3000_f50", { ...ok, continuity_ok: false }), row("M0.12_h3000_f50", { ...ok, continuity_ok: false }),
  ];
  const r = trimCueReport(rows);
  assert.equal(r.summary, `4 케이스 — ${TRIM_CELL_LABEL.ok} 4 · 판정 플래그 위반 3건 확인 필요 (연속성 3)`);
  assert.deepEqual(r.data.flag_violations, {
    cases: 3, by_flag: { continuity_ok: 3 },
    names: ["M0.12_h3000_f10", "M0.18_h3000_f50", "M0.12_h3000_f50"],
  });
  // 위반이 없으면 붙이지 않는다(없는 경고를 0건으로 늘어놓지 않는다)
  const clean = trimCueReport([row("a", ok)]);
  assert.equal(clean.summary, `1 케이스 — ${TRIM_CELL_LABEL.ok} 1`);
  assert.deepEqual(clean.data.flag_violations, { cases: 0, by_flag: {}, names: [] });
});

test("trimFlagSummary — 탭 머리줄의 근거: 수렴 수·위반 케이스 수(플래그 하나라도 false)·플래그별 수", () => {
  const row = (name, converged, flags) => ({ case: { name }, converged, flags });
  const s = trimFlagSummary([
    row("a", true, { residual_ok: true, continuity_ok: false, saturation_ok: false }),
    row("b", true, { residual_ok: true, continuity_ok: null }), // null = 미판정 — 위반 아님
    row("c", false, { residual_ok: false, continuity_ok: false }),
  ]);
  assert.deepEqual(s, {
    total: 3, converged: 2, bad: 2,
    byFlag: { saturation_ok: 1, continuity_ok: 2, residual_ok: 1 },
    badNames: ["a", "c"],
    line: "수렴 2/3 · 판정 플래그 위반 2건",
    detail: "잔차 1 · 포화 1 · 연속성 2",
  });
  // 라벨은 트림 표의 열 이름 — 표·머리줄·보고가 한 표를 본다
  assert.deepEqual(Object.values(TRIM_FLAG_LABEL), ["잔차", "포화", "α여유", "연속성"]);
});

// 쇼케이스 결함 D8 — δe 소모·추력 여유 열이 fmt(x·100, 1)(유효 1자리)라 「2e+1 %」로 찍혔다
test("pctText — 비율을 소수 자리 고정 백분율로 (지수 표기 금지)", () => {
  assert.equal(pctText(0.2), "20.0 %");
  assert.equal(pctText(0.567), "56.7 %");
  assert.equal(pctText(0.0004), "0.0 %");
  assert.equal(pctText(1), "100.0 %");
  assert.equal(pctText(0.1234, 0), "12 %");
  assert.equal(pctText(-0.05), "−5.0 %"); // 음수는 수학 기호 빼기
  assert.equal(pctText(null), "—");
  assert.equal(pctText(Number.NaN), "—");
  assert.equal(pctText("inf"), "—");
  for (const v of [0.2, 0.6, 0.5, 0.95]) assert.ok(!/e[+-]/.test(pctText(v)), `${v} → ${pctText(v)}`);
});

// 쇼케이스 결함 D9 — 세 마하의 CL 곡선이 같은 값이라 한 줄만 보이는데 범례는 셋을 말했다
test("coincidentGroups — 값이 같은 곡선끼리 묶는다 (첫 곡선이 대표) · null 자리까지 같아야 같다", () => {
  const a = [0.1, 0.2, 0.3];
  assert.deepEqual(coincidentGroups([a, [...a], [0.1, 0.2, 0.31]]), [[0, 1], [2]]);
  assert.deepEqual(coincidentGroups([a, a, a]), [[0, 1, 2]]);
  assert.deepEqual(coincidentGroups([a]), [[0]]);
  assert.deepEqual(coincidentGroups([]), []);
  // 부동소수 잡음(상대 1e-9)은 같은 값 — 눈에 안 보일 만큼 다른 곡선(1e-4)은 다른 곡선이다
  assert.deepEqual(coincidentGroups([[1, 2], [1 + 1e-12, 2]]), [[0, 1]]);
  assert.deepEqual(coincidentGroups([[1, 2], [1 + 1e-4, 2]]), [[0], [1]]);
  // null(판정 불가 구간)은 같은 자리에 있어야 같다 — 0으로 메우지 않는다
  assert.deepEqual(coincidentGroups([[1, null, 3], [1, null, 3], [1, 2, 3]]), [[0, 1], [2]]);
  // 길이가 다르면 다른 곡선
  assert.deepEqual(coincidentGroups([[1, 2], [1, 2, 3]]), [[0], [1]]);
  // 뒤 곡선이 앞 무리의 대표와만 견준다 — 순서가 곧 대표 순서
  assert.deepEqual(coincidentGroups([[5], [6], [5], [6]]), [[0, 2], [1, 3]]);
});

test("marginWorst — 수렴·수치 마진 칸만 후보, inf·null은 최악이 아니다", () => {
  const e = (name, converged, margins) => ({ trim: { converged, case: { name } }, margins });
  const loops = [{ name: "pitch_q" }, { name: "yaw_r" }];
  const entries = [
    e("A", true, { pitch_q: { pm_deg: 50, gm_db: "inf" }, yaw_r: { pm_deg: 61, gm_db: 9.5 } }),
    e("B", true, { pitch_q: { pm_deg: 38.2, gm_db: 12 }, yaw_r: { pm_deg: null, gm_db: 7.1 } }),
    e("C", false, { pitch_q: { pm_deg: -80, gm_db: -9 } }), // 미수렴 — 선형화점이 없다
    e("D", true, {}),
  ];
  const w = marginWorst(entries, loops);
  assert.deepEqual([w.pm.loop, w.pm.entry.trim.case.name, w.pm.value], ["pitch_q", "B", 38.2]);
  assert.deepEqual([w.gm.loop, w.gm.entry.trim.case.name, w.gm.value], ["yaw_r", "B", 7.1]);
  assert.deepEqual(marginWorst([e("A", true, { pitch_q: { pm_deg: "inf", gm_db: "inf" } })], loops),
    { pm: null, gm: null, unstable: 0 });
  assert.deepEqual(marginWorst([], []), { pm: null, gm: null, unstable: 0 });
});

test("marginWorst — 폐루프 발산 칸은 최악 후보가 아니라 unstable로 센다", () => {
  const e = (name, converged, margins) => ({ trim: { converged, case: { name } }, margins });
  const loops = [{ name: "pitch_q" }];
  const div = (pm, gm) => ({ pm_deg: pm, gm_db: gm, closed_loop: { stable: false, unstable: [[1.97, 21.6]] } });
  const entries = [
    // 발산 칸의 PM·GM은 루프 교차의 고전 판독 — 수가 더 작아도(−5°·−3 dB) 최악 여유로 뽑히면 안 된다
    e("A", true, { pitch_q: div(-5, -3) }),
    e("B", true, { pitch_q: { pm_deg: 45, gm_db: 8, closed_loop: { stable: true } } }),
    e("C", true, { pitch_q: div(82, 20) }), // 넉넉해 보이는 발산 칸도 마찬가지
    e("D", false, { pitch_q: div(1, 1) }), // 미수렴 — 세지 않는다
  ];
  const w = marginWorst(entries, loops);
  assert.deepEqual([w.pm.entry.trim.case.name, w.pm.value], ["B", 45]);
  assert.deepEqual([w.gm.entry.trim.case.name, w.gm.value], ["B", 8]);
  assert.equal(w.unstable, 2);
  // 전부 발산이면 최악 여유는 없다 — 발산 칸의 수가 「최악 PM」으로 둔갑하지 않는다
  assert.deepEqual(marginWorst([entries[0], entries[2]], loops), { pm: null, gm: null, unstable: 2 });
});

test("coincidentNote — 같은 값이라 한 줄로 그린 곡선을 캡션 한 줄로 · 없으면 null", () => {
  const tags = ["mach 0.09", "mach 0.16", "mach 0.23"];
  const all = [[0, 1, 2]];
  // 세 그림 모두 같은 방식으로 겹치면 한 번만 말한다
  assert.equal(coincidentNote([
    { name: "CL", groups: all, tags }, { name: "극선", groups: all, tags }, { name: "L/D", groups: all, tags },
  ]), "같은 값의 곡선은 한 줄(앞 곡선의 색)로 그렸습니다 — CL·극선·L/D 모두 mach 0.09 = mach 0.16 = mach 0.23");
  // 그림마다 다르면 그림별로 — 겹침이 없는 그림은 빼고
  assert.equal(coincidentNote([
    { name: "CL", groups: [[0, 1], [2]], tags }, { name: "극선", groups: [[0], [1], [2]], tags },
  ]), "같은 값의 곡선은 한 줄(앞 곡선의 색)로 그렸습니다 — CL: mach 0.09 = mach 0.16");
  assert.equal(coincidentNote([{ name: "CL", groups: [[0], [1], [2]], tags }]), null);
  assert.equal(coincidentNote([]), null);
});

// 쇼케이스 실측 — 세 마하의 CL 곡선은 같은 값이 아니다(CL 최대 1.103·1.106·1.109). 차가 그림 해상도 아래라 한 줄로
// 보이고 맨 위 곡선의 색만 남는다 — 같은 값이라고 말하면 거짓이고, 말하지 않으면 범례의 셋 중 둘이 사라진 것처럼 읽힌다
test("curveSpread — 모든 곡선이 수인 자리의 (최대 − 최소) 최댓값과 값 범위 대비 비율", () => {
  const s = curveSpread([[0, 1, 2], [0, 1.01, 2], [0, 1.02, 2.01]]);
  assert.ok(Math.abs(s.maxDiff - 0.02) < 1e-12);
  assert.equal(s.range, 2.01);
  assert.ok(Math.abs(s.rel - 0.02 / 2.01) < 1e-12);
  // null 자리는 건너뛴다(끊긴 구간을 0으로 메우지 않는다)
  assert.equal(curveSpread([[0, null, 2], [0, 5, 2]]).maxDiff, 0);
  assert.equal(curveSpread([[1, 2]]), null); // 곡선 하나 — 퍼짐이 없다
  assert.equal(curveSpread([[null], [null]]), null); // 견줄 자리가 없다
});

test("nearOverlapNote — 차가 값 범위의 frac 아래인 그림만 캡션 한 줄로 · 없으면 null", () => {
  const note = nearOverlapNote([
    { name: "CL", spread: { maxDiff: 0.006, range: 1.9, rel: 0.006 / 1.9 } },
    { name: "L/D", spread: { maxDiff: 2, range: 10, rel: 0.2 } }, // 잘 갈린다 — 말하지 않는다
    { name: "극선", spread: null },
  ]);
  assert.equal(note, "겹친 곡선의 차가 그림 해상도보다 작아 한 줄로 보입니다(나중 곡선의 색이 위) — "
    + "CL 최대 차 0.006 (값 범위의 0.3 %)");
  assert.equal(nearOverlapNote([{ name: "L/D", spread: { maxDiff: 2, range: 10, rel: 0.2 } }]), null);
  // 기본 문턱 1.5 % — 쇼케이스 극선의 CD 퍼짐(1.07 %)은 한 줄로 보였다. 같은 값(maxDiff 0)은 coincidentNote의 몫
  assert.match(nearOverlapNote([{ name: "극선", spread: { maxDiff: 0.0033, range: 0.3076, rel: 0.0107 } }]), /극선 최대 차 0\.0033/);
  assert.equal(nearOverlapNote([{ name: "CL", spread: { maxDiff: 0, range: 1, rel: 0 } }]), null);
  assert.equal(nearOverlapNote([]), null);
});
