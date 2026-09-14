// 미션 템플릿 → 화면 기본값 — 폴백이 예제 기체 사본이라는 계약과 「손대지 않은 칸만」 규칙 (node --test)
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_GRID, defaultGridCases } from "./grid.js";
import {
  ENVELOPE_FALLBACK, MARGIN_ACT_FALLBACK, gridStrings, templateDefaults, untouchedUpdates,
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
  assert.deepEqual(d.envelope, { margin: "0.08" });
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
