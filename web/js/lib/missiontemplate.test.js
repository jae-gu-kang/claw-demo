// 미션 템플릿 → 화면 기본값 — 폴백이 예제 기체 사본이라는 계약과 「손대지 않은 칸만」 규칙 (node --test)
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_GRID, defaultGridCases, parseNumberList } from "./grid.js";
import {
  ENVELOPE_FALLBACK, MARGIN_ACT_FALLBACK, gridCentreCase, gridStrings, templateDefaults, untouchedUpdates,
} from "./missiontemplate.js";
import { DEFAULT_FORM, MODE_FALLBACK, defaultModeRows } from "./simrequest.js";
import { GOHEUNG, touchdownWindowM } from "./site.js";

const EXAMPLE = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));

test("웹의 폴백은 예제 기체 문서의 사본이다 — 예제 문서가 바뀌면 여기서 빨개진다", () => {
  const d = templateDefaults(EXAMPLE);
  assert.equal(d.hasTemplate, true);
  assert.deepEqual(d.grid, DEFAULT_GRID, "해석 격자 (lib/grid.js)");
  assert.deepEqual(d.envelope, { ...ENVELOPE_FALLBACK }, "엔벨로프 폼");
  assert.deepEqual(d.margins, { ...MARGIN_ACT_FALLBACK }, "마진 맵 작동기 칸");
  assert.deepEqual(d.sim.form, { fuel: DEFAULT_FORM.fuel, fuelFlow: DEFAULT_FORM.fuelFlow,
    tEnd: DEFAULT_FORM.tEnd, accept: DEFAULT_FORM.accept }, "시뮬 폼 미션 칸");
  assert.deepEqual(d.sim.rows, { ...MODE_FALLBACK }, "기본 모드 표");
  assert.equal(d.rolloutM, GOHEUNG.rolloutM, "착륙 미끄럼 (lib/site.js)");
});

test("템플릿이 없는 기체 — 격자·미션은 없고(폴백을 쓰되 화면이 말한다), 본문 값(α 여유·작동기)은 읽는다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.mission_template = null;
  doc.law.alpha_margin = 0.08;
  doc.actuator.params.wn = 45;
  const d = templateDefaults(doc);
  assert.deepEqual([d.hasTemplate, d.grid, d.sim, d.rolloutM], [false, null, null, null]);
  // 동압·운용 고도는 템플릿이 아니라 문서 본문 — 예제는 null이라 빈칸(경계 없음)
  assert.deepEqual(d.envelope, { margin: "0.08", qMax: "", altMin: "", altMax: "" });
  assert.equal(d.margins.wn, "45");
  assert.equal(templateDefaults(null).hasTemplate, false);
});

test("다른 기체의 템플릿 — 모드 표·격자·접지 창이 그 값으로 선다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.mission_template.sim.climb.speed = 130;
  doc.mission_template.sim.cruise.alt = 450;
  doc.mission_template.sim.rollout_m = 600;
  doc.mission_template.trim_grid = { mach: { from: 0.4, to: 0.5, step: 0.05 }, alt: [2000], fuel: [100, 300] };
  const d = templateDefaults(doc);
  const rows = defaultModeRows(d.sim.rows);
  assert.equal(rows.find((r) => r.name === "launch").speed, "130");
  assert.equal(rows.find((r) => r.name === "cruise").lonValue, "450");
  assert.deepEqual(defaultModeRows(), defaultModeRows(MODE_FALLBACK), "기본 호출은 폴백 그대로");
  assert.equal(defaultGridCases(d.grid).length, 3 * 1 * 2);
  assert.equal(touchdownWindowM(GOHEUNG, d.rolloutM), GOHEUNG.runwayLengthM - 600);
  assert.deepEqual(gridStrings(d.grid), { machFrom: "0.4", machTo: "0.5", machStep: "0.05", alts: "2000", fuels: "100, 300" });
});

test("손대지 않은 칸만 바꾼다 — 사용자가 고친 칸·같은 값은 건드리지 않는다", () => {
  const fallback = { a: "1", b: "2", c: "3" };
  assert.deepEqual(untouchedUpdates({ a: "1", b: "9", c: "3" }, fallback, { a: "5", b: "6", c: "3", d: "7" }), { a: "5" });
  assert.deepEqual(untouchedUpdates({ a: "1" }, fallback, null), {});
});

test("엔벨로프 칸 — 문서의 q̄_max·운용 고도와 템플릿 V-n 고도 목록을 손대지 않은 칸에 채운다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.structural.q_max = 3000;
  doc.operating = { alt_min: 0, alt_max: 4000 };
  doc.mission_template.envelope.alt = [0, 1500, 3000]; // 스키마가 목록도 받는다(스칼라도 계속)
  const d = templateDefaults(doc);
  assert.deepEqual([d.envelope.qMax, d.envelope.altMin, d.envelope.altMax, d.envelope.alt],
    ["3000", "0", "4000", "0, 1500, 3000"]);
  // 폼이 폴백 그대로면 전부 바뀌고, 사용자가 고친 칸(여기선 q̄_max)은 남는다
  const form = { ...ENVELOPE_FALLBACK, qMax: "5000" };
  const up = untouchedUpdates(form, ENVELOPE_FALLBACK, d.envelope);
  assert.deepEqual([up.qMax, up.altMin, up.altMax, up.alt], [undefined, "0", "4000", "0, 1500, 3000"]);
  // 한쪽만 적힌 운용 고도 — 적힌 쪽만 선다(null은 빈칸 = 그 쪽 경계 없음)
  doc.operating = { alt_min: null, alt_max: 2500 };
  assert.deepEqual([templateDefaults(doc).envelope.altMin, templateDefaults(doc).envelope.altMax], ["", "2500"]);
});

test("V-n 고도 — 템플릿 envelope.alt가 수 하나든 목록이든 폼 글이 엔벨로프 그리기의 고도 목록으로 되읽힌다", () => {
  // 엔벨로프 탭 draw()·vn 신호의 기본 고도는 이 폼 글을 parseNumberList로 읽은 것이다(고도마다 V-n 한 장)
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  const vnAlts = (alt) => {
    doc.mission_template.envelope.alt = alt;
    return parseNumberList(templateDefaults(doc).envelope.alt);
  };
  assert.deepEqual(vnAlts(1200), [1200], "스칼라(종전 모양)");
  assert.deepEqual(vnAlts([1200]), [1200], "한 개 목록");
  assert.deepEqual(vnAlts([0, 1500, 3000]), [0, 1500, 3000], "여러 고도 = 병렬 비교");
});

test("gridCentreCase — 격자의 가운데 점(행 추가 첫 값), 기체 상수가 아니라 격자에서", () => {
  assert.deepEqual(gridCentreCase(DEFAULT_GRID), { mach: 0.18, alt: 1000, fuel: 25 });
  // 짝수 개는 아래쪽 가운데 — 목록 끝(가장자리)이 아니다
  assert.deepEqual(gridCentreCase({ machFrom: 0.12, machTo: 0.2, machStep: 0.02, alts: [200, 3000], fuels: [10, 50] }),
    { mach: 0.16, alt: 200, fuel: 10 });
  assert.throws(() => gridCentreCase({ ...DEFAULT_GRID, fuels: [] }), /비었다/);
});
