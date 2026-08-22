// 타면 사용 통계 표시 계층 — 여기서 지키는 것:
// ① 각은 표시 직전에만 deg (내부·전송은 rad) ② **판정 불가와 0은 다르다** —
// 한계 미상이면 "포화 0초"가 아니라 "판정 불가" ③ 심각도는 실제 포화율에서 나온다
// ④ 빈 경계·격자 변환이 한 칸 밀리지 않는다 (경계 n+1개 ↔ 값 n개)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEG,
  capabilityBox,
  channelRows,
  densityView,
  exceedanceSeries,
  fmtDeg,
  histBars,
  modeOptions,
  severity,
  viewOf,
} from "./duty.js";

const CH = {
  key: "elevon_l",
  label: "엘레본(좌)",
  unit: "rad",
  pos_lo: -0.35,
  pos_hi: 0.35,
  rate_max: 10.0,
  hist: { edges: [-0.35, 0, 0.35], time: [12.0, 8.0], frac: [0.6, 0.4], out_of_range: 0 },
  exceedance: { level: [0, 0.1, 0.2], time: [20, 6, 1], p50: 0.05, p95: 0.15, p99: 0.19 },
  density: { x_edges: [-0.35, 0, 0.35], y_edges: [-10, 0, 10], time: [[1, 2], [3, 4]] },
  stats: {
    mean: 0.02, std: 0.05, min: -0.1, max: 0.21,
    max_abs: 0.21, max_abs_t: 12.5,
    max_rate_abs: 4.0, max_rate_abs_t: 3.25, usage: 0.6,
  },
  reversals: { count: 7, per_min: 21.0, deadband: 0.2 },
  pos_sat: { time: 0.0, frac: 0.0, events: 0, longest: 0.0, first_t: null },
  rate_sat: { time: 1.5, frac: 0.075, events: 4, longest: 0.6, first_t: 3.1 },
  by_mode: {
    climb: { time: 5.0, hist: { edges: [-0.35, 0, 0.35], time: [1, 4], frac: [0.2, 0.8] },
      stats: { max_abs: 0.21, max_abs_t: 3.0 }, pos_sat: null, rate_sat: null },
  },
};

const REPORT = {
  t_total: 20.0, n: 2000, dt: 0.01, rate_dt: 0.01,
  actuators: true, rate_is_command_slew: false,
  modes: ["climb", "hold"], mode_time: { climb: 5.0, hold: 15.0 },
  warnings: [], channels: [CH],
};

test("fmtDeg: rad → deg 표시 변환 (내부 규약은 rad 유지)", () => {
  assert.equal(fmtDeg(0.35, 2), "20.05°");
  assert.equal(fmtDeg(-0.1, 1), "-5.7°");
  assert.ok(Math.abs(DEG - 57.2957795) < 1e-6);
});

test("fmtDeg: 미상(null·NaN·문자열)은 0이 아니라 —", () => {
  assert.equal(fmtDeg(null), "—");
  assert.equal(fmtDeg(undefined), "—");
  assert.equal(fmtDeg(NaN), "—");
  assert.equal(fmtDeg("inf"), "—");
});

test("severity: 포화가 조금이라도 있으면 주의, 1% 넘으면 경고", () => {
  assert.equal(severity(0), "ok");
  assert.equal(severity(0.005), "warn");
  assert.equal(severity(0.05), "bad");
  assert.equal(severity(null), "na"); // 판정 불가
});

test("channelRows: 포화 판정 불가는 '0초'가 아니라 판정 불가로 나온다", () => {
  const noLimit = {
    ...CH, pos_lo: null, pos_hi: null, rate_max: null,
    pos_sat: null, rate_sat: null, stats: { ...CH.stats, usage: null },
  };
  const [row] = channelRows({ ...REPORT, channels: [noLimit] });
  assert.equal(row.posSat.severity, "na");
  assert.equal(row.rateSat.severity, "na");
  assert.doesNotMatch(row.posSat.text, /^0/, `0으로 위장됨: ${row.posSat.text}`);
  assert.equal(row.usage, "—");
});

test("channelRows: 포화가 실제로 없으면 '없음' (판정 불가와 구분)", () => {
  const [row] = channelRows(REPORT);
  assert.equal(row.posSat.severity, "ok");
  assert.notEqual(row.posSat.text, row.rateSat.text);
  assert.equal(row.rateSat.severity, "bad"); // 7.5% — 경고
  assert.match(row.rateSat.text, /4회/); // 구간 수가 보여야 리밋사이클이 읽힌다
  assert.match(row.rateSat.text, /최장/);
});

test("channelRows: 최대값은 시각과 함께 (언제 그랬는지 없으면 추적이 안 된다)", () => {
  const [row] = channelRows(REPORT);
  assert.match(row.max, /12\.0[35]°/); // 0.21 rad
  assert.match(row.max, /12\.5\s*s/);
  assert.match(row.maxRate, /229/); // 4 rad/s ≈ 229.2 °/s
  assert.match(row.maxRate, /\/s/);
});

test("channelRows: 사용률은 백분율 — 남은 조종권의 단일 요약", () => {
  const [row] = channelRows(REPORT);
  assert.match(row.usage, /60/);
  assert.match(row.usage, /%/);
});

test("channelRows: 반전 횟수는 분당 반전율과 함께 (리밋사이클 판독)", () => {
  const [row] = channelRows(REPORT);
  assert.match(row.reversals, /7/);
  assert.match(row.reversals, /21/);
});

test("channelRows: 반전 횟수에는 불감대가 따라붙는다 (없으면 비교가 불가능)", () => {
  // 불감대는 rate 한계에 비례한다 — 한계가 다른 두 런의 횟수는 같은 척도가 아니다
  const [row] = channelRows(REPORT);
  assert.match(row.reversalsHint, /불감대/);
  assert.match(row.reversalsHint, /11\.5/); // 0.2 rad/s ≈ 11.5 °/s
  const [none] = channelRows({ ...REPORT, channels: [{ ...CH, reversals: null }] });
  assert.equal(none.reversals, "—");
  assert.match(none.reversalsHint, /판정 불가/);
});

test("histBars: 경계 n+1개 → 막대 n개 (한 칸 밀리면 축이 통째로 거짓말한다)", () => {
  const bars = histBars(CH.hist);
  assert.equal(bars.length, 2);
  assert.ok(Math.abs(bars[0].x0 + 20.05) < 0.01);
  assert.ok(Math.abs(bars[0].x1 - 0) < 1e-9);
  assert.ok(Math.abs(bars[1].x1 - 20.05) < 0.01);
  assert.equal(bars[0].time, 12.0);
  assert.equal(bars[0].frac, 0.6);
});

test("histBars: 빈 입력은 예외가 아니라 빈 배열", () => {
  assert.deepEqual(histBars(null), []);
  assert.deepEqual(histBars({ edges: [], time: [] }), []);
});

test("exceedanceSeries: 레벨은 deg, 시간은 s 그대로", () => {
  const ex = exceedanceSeries(CH.exceedance);
  assert.equal(ex.level.length, ex.time.length);
  assert.ok(Math.abs(ex.level[1] - 5.7296) < 0.01);
  assert.equal(ex.time[0], 20);
});

test("capabilityBox: 작동기 능력 상자 — 한계가 없으면 그 변만 null", () => {
  const box = capabilityBox(CH);
  assert.ok(Math.abs(box.xLo + 20.05) < 0.01);
  assert.ok(Math.abs(box.yHi - 572.96) < 0.1); // 10 rad/s
  const noRate = capabilityBox({ ...CH, rate_max: null });
  assert.equal(noRate.yHi, null);
  assert.notEqual(noRate.xHi, null); // 위치 한계는 남는다
});

test("densityView: 격자 경계만 deg 변환, 셀 값(시간)은 그대로", () => {
  const d = densityView(CH.density);
  assert.equal(d.time.length, 2);
  assert.equal(d.time[0][1], 2);
  assert.ok(Math.abs(d.yEdges[2] - 572.96) < 0.1);
  assert.equal(d.xEdges.length, 3);
});

test("modeOptions: 전체가 먼저, 모드마다 체류 시간 표기", () => {
  const opts = modeOptions(REPORT);
  assert.equal(opts[0].value, "");
  assert.match(opts[0].label, /전체/);
  assert.equal(opts[1].value, "climb");
  assert.match(opts[1].label, /5/); // 체류 시간
});

test("viewOf: 모드 선택 시 그 모드의 히스토그램·통계로 갈아끼운다", () => {
  const all = viewOf(CH, "");
  assert.equal(all.hist.time[0], 12.0);
  const climb = viewOf(CH, "climb");
  assert.equal(climb.hist.time[0], 1);
  assert.equal(climb.stats.max_abs_t, 3.0);
});

test("viewOf: 없는 모드는 조용히 전체로 넘어가지 않고 빈 뷰", () => {
  const v = viewOf(CH, "없는모드");
  assert.equal(v, null);
});
