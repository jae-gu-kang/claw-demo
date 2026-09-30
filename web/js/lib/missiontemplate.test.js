// 미션 템플릿 → 화면 기본값 — 폴백이 예제 기체 사본이라는 계약과 「손대지 않은 칸만」 규칙 (node --test)
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { parseNumberList } from "./grid.js";
import {
  ENVELOPE_FALLBACK, MARGIN_ACT_FALLBACK, templateDefaults, untouchedUpdates,
} from "./missiontemplate.js";
import { DEFAULT_FORM, MODE_FALLBACK, defaultModeRows } from "./simrequest.js";
import { GOHEUNG, touchdownWindowM } from "./site.js";

const EXAMPLE = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));

test("웹의 폴백은 예제 기체 문서의 사본이다 — 예제 문서가 바뀌면 여기서 빨개진다", () => {
  const d = templateDefaults(EXAMPLE);
  assert.equal(d.hasTemplate, true);
  // 템플릿 격자는 자동 설계 칸의 자리표시로만 읽힌다 — 해석 격자는 요구영역의 기본 격자(/grid/base)다
  assert.deepEqual(d.grid, { machFrom: 0.14, machTo: 0.22, machStep: 0.02, alts: [100, 1000, 3000], fuels: [25] },
    "예제 문서 trim_grid 그대로");
  // 운용 고도 칸(altMin·altMax)은 문서가 채우지 않는 빈칸 폴백이다(스키마 v3 — 아래 시험)
  const { altMin, altMax, ...fromDoc } = ENVELOPE_FALLBACK;
  assert.deepEqual([altMin, altMax], ["", ""]);
  assert.deepEqual(d.envelope, fromDoc, "엔벨로프 폼");
  assert.deepEqual(d.margins, { ...MARGIN_ACT_FALLBACK }, "마진 맵 작동기 칸");
  assert.deepEqual(d.sim.form, { fuel: DEFAULT_FORM.fuel, fuelFlow: DEFAULT_FORM.fuelFlow,
    tEnd: DEFAULT_FORM.tEnd, accept: DEFAULT_FORM.accept }, "시뮬 폼 미션 칸");
  assert.deepEqual(d.sim.rows, { ...MODE_FALLBACK }, "기본 모드 표");
  assert.equal(d.rolloutM, GOHEUNG.rolloutM, "착륙 미끄럼 (lib/site.js)");
});

test("엔벨로프 스캔 격자는 템플릿에서 읽지 않는다 — 요구영역의 기본 격자에서 받는다(이관 9단계)", () => {
  const d = templateDefaults(EXAMPLE);
  for (const k of ["scanFrom", "scanTo", "scanStep", "scanAlts"]) {
    assert.equal(k in d.envelope, false, `템플릿 스캔 칸 ${k}이 폼으로 새면 요구영역과 무관한 사각 격자가 되살아난다`);
    assert.equal(k in ENVELOPE_FALLBACK, false, k);
  }
});

test("템플릿이 없는 기체 — 격자·미션은 없고(폴백을 쓰되 화면이 말한다), 본문 값(α 여유·작동기)은 읽는다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.mission_template = null;
  doc.law.alpha_margin = 0.08;
  doc.actuator.params.wn = 45;
  const d = templateDefaults(doc);
  assert.deepEqual([d.hasTemplate, d.grid, d.sim, d.rolloutM], [false, null, null, null]);
  // 동압은 템플릿이 아니라 문서 본문 — 예제는 null이라 빈칸(경계 없음). 운용 고도는 문서에서 채우지 않는다(스키마 v3)
  assert.deepEqual(d.envelope, { margin: "0.08", qMax: "" });
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
  assert.deepEqual(d.grid, { machFrom: 0.4, machTo: 0.5, machStep: 0.05, alts: [2000], fuels: [100, 300] });
  assert.equal(touchdownWindowM(GOHEUNG, d.rolloutM), GOHEUNG.runwayLengthM - 600);
});

test("손대지 않은 칸만 바꾼다 — 사용자가 고친 칸·같은 값은 건드리지 않는다", () => {
  const fallback = { a: "1", b: "2", c: "3" };
  assert.deepEqual(untouchedUpdates({ a: "1", b: "9", c: "3" }, fallback, { a: "5", b: "6", c: "3", d: "7" }), { a: "5" });
  assert.deepEqual(untouchedUpdates({ a: "1" }, fallback, null), {});
});

test("엔벨로프 칸 — 문서의 q̄_max와 템플릿 V-n 고도 목록을 손대지 않은 칸에 채운다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.structural.q_max = 3000;
  doc.mission_template.envelope.alt = [0, 1500, 3000]; // 스키마가 목록도 받는다(스칼라도 계속)
  const d = templateDefaults(doc);
  assert.deepEqual([d.envelope.qMax, d.envelope.alt], ["3000", "0, 1500, 3000"]);
  // 폼이 폴백 그대로면 전부 바뀌고, 사용자가 고친 칸(여기선 q̄_max)은 남는다
  const form = { ...ENVELOPE_FALLBACK, qMax: "5000" };
  const up = untouchedUpdates(form, ENVELOPE_FALLBACK, d.envelope);
  assert.deepEqual([up.qMax, up.alt], [undefined, "0, 1500, 3000"]);
});

test("운용 고도 칸은 문서에서 채우지 않는다 — 스키마 v3는 운용 고도가 요구영역 고도다(이관 11단계)", () => {
  // 요구영역 고도 끝은 서버·엔진이 선도 끝으로 그린다(bounds.alt_*_source "region"). 칸에 같은 값을 채워 보내면
  // 요구영역 끝이 「운용 입력」으로 두 번 그려진다 — 칸은 연구용 덮어쓰기로만 남는다
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.operating_region = { ...(doc.operating_region ?? {}), alt: [200, 3000] };
  doc.operating = { alt_min: 0, alt_max: 4000 }; // 옛 절이 남아 있어도(올리기 전 v2 사본) 읽지 않는다
  const d = templateDefaults(doc);
  assert.equal("altMin" in d.envelope, false);
  assert.equal("altMax" in d.envelope, false);
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
