// PI 개루프 스펙 편집 로직 검증 — 마진 맵 다중 루프 폼의 계약
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { machRange, serpentineCases } from "./grid.js";
import {
  AXIS_NAMES, DEFAULT_LOOPS, bodeLawGainNote, cellGainNote, gainAt, gainCueData, gainSourceText, gainSummaryTag,
  lawGainRecord, lawGainsPerCase, lawKpText, loopGainSources, loopKpTag, loopsAt, requestLoops, runGainInfo,
  validateActuatorDelay, validateLoops, DELAY_TOOL_DEFAULT, delaySourceText,
  LOOPS_LOADING_TEXT, bodeMarginNotes, bodeOthers, docLoopNames, followDocRows, loopLoadState, marginCellView,
  marginSemanticsText, marginUnstable, stableMarginEntries, unstableCells, unstableTail,
} from "./loops.js";
import { gridCentreCase } from "./missiontemplate.js";

const EXAMPLE = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));

test("AXIS_NAMES ↔ 엔진 linearize.py 자구 대조 (교차 파일 드리프트 가드, 리뷰 S2)", () => {
  // 정본(engine/claw/trim/linearize.py)을 직접 읽어 대조 — 엔진 rename 시
  // 이 테스트가 즉시 깨진다 (모노레포 전제 — 웹 테스트는 개발 환경 전용).
  const src = readFileSync(
    new URL("../../../engine/claw/trim/linearize.py", import.meta.url), "utf8");
  const names = (key) => {
    const m = src.match(new RegExp(`${key} = \\(([^)]*)\\)`));
    assert.ok(m, `엔진에서 ${key} 정의를 못 찾음 — 정규식/파일 경로 확인`);
    return [...m[1].matchAll(/"(\w+)"/g)].map((g) => g[1]);
  };
  assert.deepEqual(AXIS_NAMES.lon.states, names("LON_STATES"));
  assert.deepEqual(AXIS_NAMES.lon.inputs, names("LON_INPUTS"));
  assert.deepEqual(AXIS_NAMES.lat.states, names("LAT_STATES"));
  assert.deepEqual(AXIS_NAMES.lat.inputs, names("LAT_INPUTS"));
});

test("DEFAULT_LOOPS: 3축 레이트 루프의 구조만 — 게인은 없다(기체가 나는 게인 몫)", () => {
  assert.deepEqual(DEFAULT_LOOPS.map((l) => [l.name, l.axis, l.x_out, l.u_in, l.sign, l.group]), [
    ["pitch_q", "lon", "q", "de", "-1", "pitch"],
    ["roll_p", "lat", "p", "da", "-1", "roll"],
    ["yaw_r", "lat", "r", "dr", "-1", "yaw"],
  ]);
  assert.ok(DEFAULT_LOOPS.every((l) => !("kp" in l) && !("ki" in l)), "기체 의존 게인을 코드에 두지 않는다");
});

// ── 루프 게인 = 기체가 실제로 나는 게인 (확정 표 > 규칙 스케줄, 엔진 assemble_law 우선순위) ──

const SHOWCASE = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/showcase_delta.json", import.meta.url), "utf8"));

// 카탈로그 꼴(GET /gains/catalog) — 3축 k_rate 자리만. rule: 자리 → 규칙 표(서버 제안 표 자리), scheduled: 켠 자리
function catalogOf(doc, { confirmed = null, rule = {}, scheduled = null } = {}) {
  const on = new Set(scheduled ?? doc.law.schedule?.scheduled ?? []);
  return {
    axis: "mach",
    scas_design: doc.law.design.scas,
    slots: ["pitch", "roll", "yaw"].map((g) => ({
      name: `${g}.k_rate`, group: g, key: "k_rate", available: true, scheduled: on.has(`${g}.k_rate`),
      design: doc.law.design.scas[g].k_rate, table: rule[`${g}.k_rate`] ?? null,
    })),
    confirmed,
  };
}
const T = (mach, data) => ({ axes: { mach }, data, extrapolate: "clip" });
// 검증용 독립 오라클 — 1축 선형 보간 + 양끝 clip (엔진 claw/tables Table.interp와 같은 뜻)
function lerp(t, x) {
  const g = t.axes.mach;
  const d = t.data;
  if (x <= g[0]) return d[0];
  if (x >= g[g.length - 1]) return d[d.length - 1];
  const i = g.findIndex((v, j) => x >= v && x < g[j + 1]);
  return d[i] + ((x - g[i]) / (g[i + 1] - g[i])) * (d[i + 1] - d[i]);
}
const kpOf = (rows, name) => Number(rows.find((r) => r.name === name).kp);

test("loopGainSources: 쇼케이스 기체 — 신선한 확정 게인 표가 정본이다(시드 설계값 k_rate가 아니다)", () => {
  const tables = SHOWCASE.law.gain_tables.tables;
  // 규칙 표 자리에 엉뚱한 값을 둔다 — 확정 표가 있으면 읽혀선 안 된다(전체 교체)
  const junk = T([0.05, 0.3], [99, 99]);
  const cat = catalogOf(SHOWCASE, {
    confirmed: { slots: Object.keys(tables).sort(), stale: false },
    rule: { "pitch.k_rate": junk, "roll.k_rate": junk, "yaw.k_rate": junk },
  });
  const src = loopGainSources(cat, tables);
  assert.equal(src.basis, "confirmed");
  assert.deepEqual(src.loops.map((l) => [l.name, l.kind]),
    [["pitch_q", "confirmed"], ["roll_p", "confirmed"], ["yaw_r", "confirmed"]]);
  const at = { mach: 0.147, alt: 0, fuel: 25 }; // 시드 설계점(law.schedule.m_design)
  const { rows, skipped } = loopsAt(src, at);
  assert.deepEqual(skipped, []);
  for (const [name, slot] of [["pitch_q", "pitch.k_rate"], ["roll_p", "roll.k_rate"], ["yaw_r", "yaw.k_rate"]]) {
    assert.ok(Math.abs(kpOf(rows, name) - lerp(tables[slot], at.mach)) < 1e-12, `${name}: 확정 표 @M0.147`);
    const group = slot.split(".")[0];
    assert.notEqual(kpOf(rows, name), SHOWCASE.law.design.scas[group].k_rate, `${name}: 시드 설계값이 아니다`);
  }
  // 표 격자점에서는 표 값 그대로, 표 밖은 clip — 엔진 Table(clip)과 같은 뜻
  const pt = tables["pitch.k_rate"];
  pt.axes.mach.forEach((m, i) => assert.equal(gainAt(src.loops[0], { mach: m }), pt.data[i]));
  assert.equal(gainAt(src.loops[0], { mach: 0.01 }), pt.data[0]);
  assert.equal(gainAt(src.loops[0], { mach: 0.9 }), pt.data[pt.data.length - 1]);
  // 부호는 게인이 보유 — 롤 k_rate는 음수 그대로 루프 kp가 된다
  const v = validateLoops(rows);
  assert.ok(!v.errors, JSON.stringify(v.errors));
  assert.ok(v.loops[1].kp < 0);
  assert.ok(v.loops.every((l) => l.ki === 0 && l.sign === -1));
});

test("loopGainSources: 확정 표는 전체 교체 — 표에 없는 자리는 규칙 표가 아니라 설계 상수", () => {
  const cat = catalogOf(SHOWCASE, {
    confirmed: { slots: ["pitch.k_rate"], stale: false },
    rule: { "yaw.k_rate": T([0.1, 0.2], [5, 1]) },
  });
  const src = loopGainSources(cat, { "pitch.k_rate": T([0.1, 0.2], [0.6, 0.2]) });
  assert.deepEqual(src.loops.map((l) => l.kind), ["confirmed", "fixed", "fixed"]);
  const { rows } = loopsAt(src, { mach: 0.15 });
  assert.ok(Math.abs(kpOf(rows, "pitch_q") - 0.4) < 1e-12);
  assert.equal(kpOf(rows, "yaw_r"), SHOWCASE.law.design.scas.yaw.k_rate);
});

test("loopGainSources: 확정 표가 있다는데 표가 없거나 자리가 어긋나면 던진다 — 규칙 표로 조용히 갈음하지 않는다", () => {
  const cat = catalogOf(SHOWCASE, { confirmed: { slots: ["pitch.k_rate", "yaw.k_rate"], stale: false } });
  assert.throws(() => loopGainSources(cat, null), /받지 못했다/);
  assert.throws(() => loopGainSources(cat, { "pitch.k_rate": T([0.1], [1]) }), /자리가 다르다/);
});

test("loopGainSources: 확정 표가 낡았으면 규칙 스케줄 — 캡션은 그 표로 날 수 없다는 사실부터 말한다", () => {
  const rule = { "pitch.k_rate": T([0.1, 0.2], [0.3, 0.1]), "roll.k_rate": T([0.1, 0.2], [-0.4, -0.2]),
    "yaw.k_rate": T([0.1, 0.2], [1.6, 0.4]) };
  const cat = catalogOf(SHOWCASE, { confirmed: { slots: ["pitch.k_rate"], stale: true }, rule });
  const src = loopGainSources(cat, null); // 낡은 표는 읽지 않는다 — 문서 표를 넘기지 않아도 된다
  assert.equal(src.basis, "rule");
  assert.equal(src.staleConfirmed, true);
  const ref = { mach: 0.15, alt: 0, fuel: 25 };
  const { rows } = loopsAt(src, ref);
  assert.ok(Math.abs(kpOf(rows, "pitch_q") - 0.2) < 1e-12);
  const info = runGainInfo(src, rows, rows, ref, [ref]);
  assert.match(gainSourceText(info), /확정 게인 표가 낡아 조립이 거부한다/);
  assert.match(gainSourceText(info), /날 게인이 없다/);
  assert.match(gainSummaryTag(info), /규칙 스케줄\(확정 표 낡음\) @M0\.15/);
  // 낡은 표 아래에서는 「기체가 실제로 나는 게인」이라고 말하지 않는다 — 날 게인이 없다
  const wide = runGainInfo(src, rows, rows, ref, [ref, { ...ref, mach: 0.1 }]);
  assert.doesNotMatch(gainSourceText(wide), /실제로 나는|실제 게인/);
  assert.match(gainSourceText(wide), /그 칸의 규칙 스케줄 게인으로 잰 마진/);
  assert.doesNotMatch(cellGainNote(wide, "pitch_q", { ...ref, mach: 0.1 }, kpOf(rows, "pitch_q")), /실제로 나는/);
});

// 요 k_rate를 스케줄에서 뺀 선택 — 예제 문서는 2026-09 재튜닝부터 요 k_rate도 스케줄하므로(7자리) 「안 한 자리」 분기는
// 이 선택으로 세운다(카탈로그 scheduled — 게인 탭에서 자리를 끈 것과 같은 꼴)
const NO_YAW_SCHED = ["pitch.k_rate", "roll.k_rate"];

test("loopGainSources: 확정 표 없는 예제 기체 — 스케줄한 자리는 규칙 표, 안 한 자리(요 k_rate)는 설계 상수", () => {
  const sched = EXAMPLE.law.schedule.scheduled;
  assert.ok(sched.includes("pitch.k_rate") && sched.includes("yaw.k_rate"), "예제 문서 전제 — 요 k_rate도 스케줄한다");
  const rule = { "pitch.k_rate": T([0.1, 0.3], [0.8, 0.2]), "roll.k_rate": T([0.1, 0.3], [-0.9, -0.3]),
    "yaw.k_rate": T([0.1, 0.3], [9, 9]) }; // 요 자리는 켜지지 않았다 — 제안 표가 있어도 읽지 않는다
  const src = loopGainSources(catalogOf(EXAMPLE, { rule, scheduled: NO_YAW_SCHED }), null);
  assert.equal(src.basis, "rule");
  assert.equal(src.staleConfirmed, false);
  assert.deepEqual(src.loops.map((l) => l.kind), ["rule", "rule", "fixed"]);
  const { rows } = loopsAt(src, { mach: 0.2 });
  assert.ok(Math.abs(kpOf(rows, "pitch_q") - 0.5) < 1e-12);
  assert.ok(Math.abs(kpOf(rows, "roll_p") + 0.6) < 1e-12);
  assert.equal(kpOf(rows, "yaw_r"), EXAMPLE.law.design.scas.yaw.k_rate);
});

test("loopsAt: 0이거나 못 읽은 게인은 사유와 함께 뺀다 — 제로 개루프·2축 표·미설계", () => {
  const src = {
    basis: "rule", staleConfirmed: false, loops: [
      { ...DEFAULT_LOOPS[0], slot: "pitch.k_rate", kind: "rule", constant: 0.1,
        table: { axes: { mach: [0.1, 0.2], alt: [0, 1] }, data: [[1, 1], [1, 1]] } },
      { ...DEFAULT_LOOPS[1], slot: "roll.k_rate", kind: "fixed", constant: 0, table: null },
      { ...DEFAULT_LOOPS[2], slot: "yaw.k_rate", kind: "fixed", constant: null, table: null },
    ],
  };
  const { rows, skipped } = loopsAt(src, { mach: 0.15 });
  assert.deepEqual(rows, []);
  assert.deepEqual(skipped.map((s) => s.name), ["pitch_q", "roll_p", "yaw_r"]);
  assert.match(skipped[0].reason, /1축 표가 아니다/);
  assert.match(skipped[1].reason, /= 0/);
  assert.match(skipped[2].reason, /설계값에 yaw.k_rate이 없다/);
  // 카탈로그 자체가 없으면 3축 모두 설계값 없음 — 예제 값을 물려주지 않는다
  assert.deepEqual(loopsAt(loopGainSources(null, null), { mach: 0.15 }).rows, []);
});

test("runGainInfo·gainSourceText: 한 kp로 잰 격자 — 그 칸의 실제 게인과 같은 칸 수·실제 범위를 말한다", () => {
  const tables = SHOWCASE.law.gain_tables.tables;
  const cat = catalogOf(SHOWCASE, { confirmed: { slots: Object.keys(tables).sort(), stale: false } });
  const src = loopGainSources(cat, tables);
  const points = serpentineCases(machRange(0.12, 0.18, 0.015), [200, 3000], [10, 50]); // 쇼케이스 템플릿 꼴 격자
  const ref = gridCentreCase({ machFrom: 0.12, machTo: 0.18, machStep: 0.015, alts: [200, 3000], fuels: [10, 50] });
  const seed = loopsAt(src, ref).rows;
  const info = runGainInfo(src, seed.map((r) => ({ ...r })), seed, ref, points);
  assert.equal(info.basis, "confirmed");
  assert.equal(info.nCases, 20);
  assert.equal(info.exactCases, 4); // 가운데 마하 열(고도 2 × 연료 2)만
  assert.deepEqual(info.exactMachs, [ref.mach]);
  const pitch = info.loops.find((l) => l.name === "pitch_q");
  assert.ok(Math.abs(pitch.min - lerp(tables["pitch.k_rate"], 0.18)) < 1e-12);
  assert.ok(Math.abs(pitch.max - lerp(tables["pitch.k_rate"], 0.12)) < 1e-12);
  assert.ok(pitch.min < pitch.kp && pitch.kp < pitch.max);
  const text = gainSourceText(info);
  assert.match(text, /문서 확정 게인 표/);
  assert.match(text, /루프마다 kp 하나/);
  assert.match(text, new RegExp(`20칸 중 4칸\\(M${ref.mach}\\)`));
  assert.match(text, /판정까지 뒤집힐 수 있는 근사/); // 근사의 크기를 숨기지 않는다(교차가 바뀌면 PM이 부호째 뒤집힌다)
  assert.doesNotMatch(text, /손으로 적은/);
  assert.match(gainSummaryTag(info), new RegExp(`확정 게인 표 @M${ref.mach} \\(20칸 중 4칸 정확\\)`));
  assert.equal(loopKpTag(info, "pitch_q"), `확정 게인 표 @M${ref.mach}`);
  const cue = gainCueData(info);
  assert.deepEqual(Object.keys(cue.loops[0]), ["name", "slot", "kind", "kp", "min", "max"]); // 표·함수는 싣지 않는다
  assert.equal(cue.exact_cases, 4);

  // 손댄 루프는 문서 게인이 아니다 — 출처를 붙이지 않고 따로 말한다
  const edited = seed.map((r) => (r.name === "roll_p" ? { ...r, kp: "-0.3" } : { ...r }));
  const info2 = runGainInfo(src, edited, seed, ref, points);
  assert.deepEqual(info2.edited, ["roll_p"]);
  assert.deepEqual(info2.loops.map((l) => l.name), ["pitch_q", "yaw_r"]);
  assert.equal(loopKpTag(info2, "roll_p"), "손으로 적은 값");
  assert.match(gainSourceText(info2), /손으로 적은 루프\(roll_p\)/);

  // 격자에 없는 마하에서 읽었으면 정확한 칸이 없다
  const off = { ...ref, mach: 0.3 };
  const info3 = runGainInfo(src, loopsAt(src, off).rows, loopsAt(src, off).rows, off, points);
  assert.equal(info3.exactCases, 0);
  assert.match(gainSourceText(info3), /실제 게인으로 잰 칸이 없다/);
});

test("runGainInfo: 스케줄 안 한 자리뿐이면 모든 칸이 정확하다 — 근사라고 말하지 않는다", () => {
  const cat = catalogOf(SHOWCASE, { scheduled: [] });
  const src = loopGainSources(cat, null);
  const ref = { mach: 0.15, alt: 200, fuel: 10 };
  const points = serpentineCases([0.12, 0.15, 0.18], [200], [10]);
  const rows = loopsAt(src, ref).rows;
  const info = runGainInfo(src, rows, rows, ref, points);
  assert.equal(info.exactCases, 3);
  assert.match(gainSourceText(info), /모든 칸이 그 칸의 실제 게인/);
  assert.doesNotMatch(gainSourceText(info), /근사/);
  assert.equal(loopKpTag(info, "yaw_r"), "설계 상수(스케줄 안 한 자리)");
});

test("cellGainNote: 누른 칸의 실제 비행 게인이 맵의 kp와 다를 때만 한 줄", () => {
  const src = loopGainSources(catalogOf(SHOWCASE, { rule: { "pitch.k_rate": T([0.1, 0.2], [0.6, 0.2]) },
    scheduled: ["pitch.k_rate"] }), null);
  const ref = { mach: 0.15, alt: 0, fuel: 25 };
  const rows = loopsAt(src, ref).rows;
  const info = runGainInfo(src, rows, rows, ref, [ref, { ...ref, mach: 0.1 }]);
  const kp = kpOf(rows, "pitch_q"); // 0.4
  assert.equal(cellGainNote(info, "pitch_q", ref, kp), null); // 게인을 읽은 칸
  const note = cellGainNote(info, "pitch_q", { mach: 0.1, alt: 0, fuel: 25 }, kp);
  assert.match(note, /M0\.1\)에서 기체가 실제로 나는 pitch\.k_rate = 0\.6 — 이 곡선과 맵은 /);
  assert.match(note, /에서 읽은 kp\([\d.]+\)로 쟀다/);
  assert.match(note, /\+50 %/);
  assert.equal(cellGainNote(info, "yaw_r", { mach: 0.1 }, kpOf(rows, "yaw_r")), null); // 스케줄 안 한 자리 — 칸마다 같다
  assert.equal(cellGainNote(null, "pitch_q", ref, kp), null);
});

// ── 칸별 법칙 게인 (margin-map loops[]의 gain_source "profile") — 서버가 칸마다 조립 법칙에서 읽는다 ──

test("lawGainsPerCase: 출처가 섰고 확정 표가 낡지 않았을 때만 — 낡은 표는 서버 조립이 거부한다(422)", () => {
  const tables = SHOWCASE.law.gain_tables.tables;
  const fresh = loopGainSources(catalogOf(SHOWCASE, {
    confirmed: { slots: Object.keys(tables).sort(), stale: false } }), tables);
  assert.equal(lawGainsPerCase(fresh), true);
  assert.equal(lawGainsPerCase(loopGainSources(catalogOf(EXAMPLE, {}), null)), true); // 규칙 스케줄도 조립이 선다
  const stale = loopGainSources(catalogOf(SHOWCASE, { confirmed: { slots: ["pitch.k_rate"], stale: true } }), null);
  assert.equal(lawGainsPerCase(stale), false);
  assert.equal(lawGainsPerCase({ error: new Error("x") }), false);
  assert.equal(lawGainsPerCase(null), false);
});

test("requestLoops: 문서 게인 루프는 kp·ki 없이 gain_source \"profile\" — 손으로 적은 루프는 적은 값 그대로", () => {
  const v = validateLoops([
    { name: "pitch_q", axis: "lon", x_out: "q", u_in: "de", kp: "0.39", ki: "0", sign: "-1" },
    { name: "roll_p", axis: "lat", x_out: "p", u_in: "da", kp: "-0.3", ki: "0", sign: "-1" },
  ]);
  const req = requestLoops(v.loops, ["pitch_q"]);
  // 서버는 법칙 게인 루프에 kp·ki가 실려 오면 거절한다 — 키 자체가 없어야 한다
  assert.deepEqual(req[0], { name: "pitch_q", axis: "lon", x_out: "q", u_in: "de", sign: -1, gain_source: "profile" });
  assert.deepEqual(req[1], v.loops[1]);
  assert.deepEqual(requestLoops(v.loops), v.loops); // 법칙 게인 루프가 없으면 종전 요청 그대로
});

// 쇼케이스 템플릿 꼴 격자 — 한 kp 근사였다면 20칸 중 4칸만 정확했던 격자다(위 runGainInfo 테스트)
const S1_GRID = { machFrom: 0.12, machTo: 0.18, machStep: 0.015, alts: [200, 3000], fuels: [10, 50] };

test("runGainInfo(perCase): 문서 게인 루프를 칸마다 읽으면 전 칸 정확 — 한 kp도, 근사라는 말도 없다", () => {
  const tables = SHOWCASE.law.gain_tables.tables;
  const src = loopGainSources(catalogOf(SHOWCASE, { confirmed: { slots: Object.keys(tables).sort(), stale: false } }), tables);
  const points = serpentineCases(machRange(0.12, 0.18, 0.015), S1_GRID.alts, S1_GRID.fuels);
  const ref = gridCentreCase(S1_GRID);
  const seed = loopsAt(src, ref).rows;
  const info = runGainInfo(src, seed.map((r) => ({ ...r })), seed, ref, points, true);
  assert.equal(info.perCase, true);
  assert.equal(info.nCases, 20);
  assert.equal(info.exactCases, 20);
  assert.ok(info.loops.every((l) => l.perCase && l.kp === null), "칸별 루프에는 한 kp가 없다");
  const pitch = info.loops.find((l) => l.name === "pitch_q");
  assert.ok(Math.abs(pitch.min - lerp(tables["pitch.k_rate"], 0.18)) < 1e-12);
  assert.ok(Math.abs(pitch.max - lerp(tables["pitch.k_rate"], 0.12)) < 1e-12);
  const text = gainSourceText(info);
  assert.match(text, /칸마다 그 칸에서 기체가 실제로 나는 k_rate/);
  assert.match(text, /문서 확정 게인 표\(자동 설계 반영 — 시뮬·코드가 조립하는 표\)를 칸의 운용점에서 읽는다/);
  assert.match(text, /격자 20칸 모두 그 칸의 실제 게인으로 잰 마진/);
  assert.doesNotMatch(text, /근사|루프마다 kp 하나|칸 중/);
  assert.equal(gainSummaryTag(info), "루프 게인 확정 게인 표 칸별 (전 칸 정확)");
  assert.equal(loopKpTag(info, "pitch_q"), "확정 게인 표 칸별");
  // 칸별 루프는 누른 칸의 게인이 곧 맵의 게인이다 — 「이 칸 게인은 그보다 +n %」 주석이 없다
  assert.equal(cellGainNote(info, "pitch_q", { mach: 0.12, alt: 200, fuel: 10 }, undefined), null);
  assert.equal(cellGainNote(info, "pitch_q", { mach: 0.12, alt: 200, fuel: 10 }, 0.39), null);
  const cue = gainCueData(info);
  assert.equal(cue.per_case, true);
  assert.equal(cue.exact_cases, 20);
  assert.equal(cue.ref_mach, null);
  assert.ok(cue.loops.every((l) => l.kp === null && !("src" in l)));

  // 손댄 루프는 칸별이 아니다 — 적은 한 값으로 전 칸을 잰다고 따로 말한다
  const edited = seed.map((r) => (r.name === "roll_p" ? { ...r, kp: "-0.3" } : { ...r }));
  const info2 = runGainInfo(src, edited, seed, ref, points, true);
  assert.deepEqual(info2.edited, ["roll_p"]);
  assert.deepEqual(info2.loops.map((l) => l.name), ["pitch_q", "yaw_r"]);
  assert.equal(loopKpTag(info2, "roll_p"), "손으로 적은 값");
  assert.match(gainSourceText(info2), /손으로 적은 루프\(roll_p\)의 kp는 문서 게인이 아니다 — 적은 값 하나로 전 칸/);
  assert.doesNotMatch(gainSourceText(info2), /roll_p -?0\.\d+~/, "손댄 루프의 범위를 문서 게인처럼 싣지 않는다");

  // 스케줄 안 한 자리는 칸마다 같은 설계 상수다 — 출처가 그렇게 말한다
  const ex = loopGainSources(catalogOf(EXAMPLE, { rule: { "pitch.k_rate": T([0.1, 0.3], [0.8, 0.2]),
    "roll.k_rate": T([0.1, 0.3], [-0.9, -0.3]) }, scheduled: NO_YAW_SCHED }), null);
  const exRows = loopsAt(ex, ref).rows;
  const exInfo = runGainInfo(ex, exRows, exRows, ref, points, true);
  assert.equal(loopKpTag(exInfo, "yaw_r"), "설계 상수(스케줄 안 한 자리)");
  assert.equal(loopKpTag(exInfo, "pitch_q"), "규칙 스케줄 칸별");
  // 캡션 수치는 유효숫자 3자리다(loops.js g3) — 예제 요 댐퍼는 툴 도출 값(0.3335…)이라 원값 그대로는 안 찍힌다
  const yawShown = String(Number(EXAMPLE.law.design.scas.yaw.k_rate.toPrecision(3)));
  assert.match(gainSourceText(exInfo), new RegExp(`yaw_r ${yawShown}\\(스케줄 안 한 자리 — 설계 상수\\)`));
  assert.match(gainSourceText(exInfo), /문서 규칙 스케줄/);
});

// 서버 결과 꼴(POST /analysis/margin-map → /results) — 법칙 게인 루프가 있을 때만 profile_gains·entry.gains가 붙는다
function lawBody(gainsByCase, { basis = "confirmed", yawScheduled = true } = {}) {
  return {
    loops: [
      { name: "pitch_q", axis: "lon", x_out: "q", u_in: "de", sign: -1, gain_source: "profile" },
      { name: "yaw_r", axis: "lat", x_out: "r", u_in: "dr", sign: -1, gain_source: "profile" },
    ],
    profile_gains: { basis, loops: {
      pitch_q: { kp: { slot: "pitch.k_rate", scheduled: true } },
      yaw_r: { kp: { slot: "yaw.k_rate", scheduled: yawScheduled } },
    } },
    cases: gainsByCase.map(([m, p, y]) => ({ trim: { case: { mach: m } }, margins: {},
      gains: { pitch_q: { kp: p, ki: 0 }, yaw_r: { kp: y, ki: 0 } } })),
  };
}

test("lawGainRecord: 캡션의 칸별 범위는 서버가 실제로 쓴 게인(entry.gains)에서 — 화면이 표에서 짐작한 값이 아니다", () => {
  const body = lawBody([[0.12, 0.5, 2.0], [0.15, 0.4, 2.0], [0.18, 0.3, 2.0]], { yawScheduled: false });
  const law = lawGainRecord(body);
  assert.deepEqual(law, { basis: "confirmed", nCases: 3, loops: [
    { name: "pitch_q", slot: "pitch.k_rate", scheduled: true, min: 0.3, max: 0.5 },
    { name: "yaw_r", slot: "yaw.k_rate", scheduled: false, min: 2.0, max: 2.0 },
  ] });
  // 요청 게인만의 결과(종전 모양 — 서버 골든의 margin_map)는 기록이 없다
  assert.equal(lawGainRecord({ loops: [{ name: "pitch_q", kp: 0.5 }], cases: [] }), null);
  assert.equal(lawGainRecord(null), null);
  // 제출 기록(화면이 표에서 읽은 범위)과 서버 기록이 다르면 캡션·보고는 서버 기록을 말한다
  const info = { basis: "confirmed", staleConfirmed: false, perCase: true, ref: { mach: 0.15 }, nCases: 3,
    exactCases: 3, exactMachs: [], edited: ["roll_hand"],
    loops: [{ name: "pitch_q", slot: "pitch.k_rate", kind: "confirmed", perCase: true, kp: null, min: 9, max: 9 }] };
  const text = gainSourceText(info, law);
  assert.match(text, /pitch_q 0\.3~0\.5/);
  assert.match(text, /yaw_r 2\(스케줄 안 한 자리 — 설계 상수\)/);
  assert.match(text, /격자 3칸 모두/);
  assert.match(text, /손으로 적은 루프\(roll_hand\)/);
  assert.doesNotMatch(text, /\b9\b/);
  assert.equal(lawKpText(law, "pitch_q"), "0.3~0.5");
  assert.equal(lawKpText(law, "yaw_r"), "2");
  assert.equal(lawKpText(law, "roll_hand"), null);
  assert.equal(loopKpTag(null, "pitch_q", law), "확정 게인 표 칸별"); // 제출 기록 없이도(다시 연 결과) 출처를 말한다
  assert.equal(loopKpTag(null, "yaw_r", law), "설계 상수(스케줄 안 한 자리)");
  assert.equal(gainSummaryTag(null, lawGainRecord(lawBody([[0.12, 0.5, 2]], { basis: "rule" }))),
    "루프 게인 규칙 스케줄 칸별 (전 칸 정확)");
  // 규칙 스케줄 결과의 출처 문장 — 조사는 괄호 앞 낱말(스케줄)에 붙는다
  assert.match(gainSourceText(info, lawGainRecord(lawBody([[0.12, 0.5, 2]], { basis: "rule" }))),
    /문서 규칙 스케줄\(law\.schedule — 시뮬·코드가 조립하는 표\)을 칸의 운용점에서 읽는다/);
  const cue = gainCueData(info, law);
  assert.equal(cue.per_case, true);
  assert.deepEqual(cue.loops.map((l) => [l.name, l.kind, l.min, l.max]),
    [["pitch_q", "confirmed", 0.3, 0.5], ["yaw_r", "fixed", 2, 2]]);
  assert.deepEqual(cue.edited, ["roll_hand"]);
});

test("bodeLawGainNote: 법칙 게인 루프의 보드선도는 그 칸의 게인을 말한다 — 요청 게인 루프면 null", () => {
  const res = { gains: { kp: 0.39848, ki: 0 },
    profile_gains: { basis: "confirmed", loops: { pitch_q: { kp: { slot: "pitch.k_rate", scheduled: true } } } } };
  const note = bodeLawGainNote(res);
  assert.equal(note, "이 곡선의 kp = 0.3985 — 이 칸에서 기체가 실제로 나는 pitch.k_rate 값이다(문서 확정 게인 표를 "
    + "이 칸의 운용점에서 읽음). 맵의 이 칸(pitch_q)과 같은 게인이다");
  assert.match(note, /문서 확정 게인 표를 이 칸의 운용점에서 읽음/);
  assert.match(note, /맵의 이 칸\(pitch_q\)과 같은 게인/);
  const fixed = bodeLawGainNote({ gains: { kp: 0.8, ki: 0 },
    profile_gains: { basis: "rule", loops: { yaw_r: { kp: { slot: "yaw.k_rate", scheduled: false } } } } });
  assert.match(fixed, /스케줄 안 한 자리 — 설계 상수/);
  // 규칙 스케줄 칸 — 「스케줄를」이 아니라 「스케줄을」
  const rule = bodeLawGainNote({ gains: { kp: 0.2078, ki: 0 },
    profile_gains: { basis: "rule", loops: { pitch_q: { kp: { slot: "pitch.k_rate", scheduled: true } } } } });
  assert.match(rule, /\(문서 규칙 스케줄을 이 칸의 운용점에서 읽음\)/);
  assert.equal(bodeLawGainNote({ margins: {}, loop: { kp: 0.5 } }), null);
  assert.equal(bodeLawGainNote(null), null);
});

const row = (over = {}) => ({
  name: "pitch_q", axis: "lon", x_out: "q", u_in: "de",
  kp: "0.5", ki: "0.8", sign: "-1", ...over,
});

test("validateLoops: 정상 행 → 수치 파싱된 루프 스펙", () => {
  const r = validateLoops([row(), row({ name: "roll_p", axis: "lat", x_out: "p", u_in: "da" })]);
  assert.ok(!r.errors);
  assert.equal(r.loops[0].kp, 0.5);
  assert.equal(r.loops[1].axis, "lat");
});

test("validateLoops: 빈 목록 허용 — 고유치·감쇠비만 보는 실행 (loops 없이 마진 생략)", () => {
  assert.deepEqual(validateLoops([]), { loops: [] });
});

test("validateLoops: 서버 검증 미러 — 이름·축 정합·무의미 루프 거부", () => {
  assert.ok(validateLoops([row({ name: " " })]).errors);          // 이름 없음
  assert.ok(validateLoops([row(), row()]).errors);                 // 이름 중복
  assert.ok(validateLoops([row({ x_out: "p" })]).errors);          // lon축에 없는 상태
  assert.ok(validateLoops([row({ u_in: "da" })]).errors);          // lon축에 없는 입력
  assert.ok(validateLoops([row({ kp: "0", ki: "0" })]).errors);    // 제로 개루프
  assert.ok(validateLoops([row({ sign: "0" })]).errors);           // sign=0
});

test("validateLoops: 미지 축 → 오류만 반환, loops 미노출 (continue 경로, 리뷰 S3)", () => {
  const r = validateLoops([row({ axis: "xyz" })]);
  assert.ok(r.errors.some((e) => e.includes("미지 축")));
  assert.ok(!("loops" in r)); // 오류 시 부분 축적 loops가 새어나가지 않음
});

test("validateLoops: 수치 파싱 함정 — 빈 문자열·비수치·비유한 거부 (Number('')===0)", () => {
  assert.ok(validateLoops([row({ kp: "" })]).errors);
  assert.ok(validateLoops([row({ ki: "abc" })]).errors);
  assert.ok(validateLoops([row({ sign: "1e999" })]).errors);
  // 오류에 어느 루프인지 표시 (여러 행일 때 위치 특정)
  const r = validateLoops([row(), row({ name: "roll_p", kp: "x" })]);
  assert.ok(r.errors.some((e) => e.includes("roll_p")));
});

// ── 작동기·지연 포함 옵션 (서버 MarginMapIn.actuator/delay_s/pade_order 미러) ──

const adRow = (over = {}) => ({
  useActuator: true, wn: "30", zeta: "0.7",
  useDelay: true, delaySeconds: "0.035", padeOrder: "2", ...over,
});

test("validateActuatorDelay: 둘 다 꺼짐 — actuator null·delay_s 0 (서버 기본값과 동일)", () => {
  const r = validateActuatorDelay(adRow({ useActuator: false, useDelay: false }));
  assert.ok(!("errors" in r)); // validateLoops와 동일 관례: 성공 시 errors 키 자체가 없음
  assert.deepEqual(r, { actuator: null, delay_s: 0, pade_order: 2 });
});

test("validateActuatorDelay: 작동기만 켜짐 — wn·zeta 파싱, delay_s는 0", () => {
  const r = validateActuatorDelay(adRow({ useDelay: false }));
  assert.ok(!r.errors);
  assert.deepEqual(r.actuator, { wn: 30, zeta: 0.7 });
  assert.equal(r.delay_s, 0);
});

test("validateActuatorDelay: 지연만 켜짐 — actuator는 null, delay_s·pade_order 파싱", () => {
  const r = validateActuatorDelay(adRow({ useActuator: false }));
  assert.ok(!r.errors);
  assert.equal(r.actuator, null);
  assert.equal(r.delay_s, 0.035);
  assert.equal(r.pade_order, 2);
});

test("validateActuatorDelay: 둘 다 켜짐 — 전부 파싱 (실서버 대조 기본값 30/0.7/0.035/2)", () => {
  const r = validateActuatorDelay(adRow());
  assert.ok(!("errors" in r));
  assert.deepEqual(r, { actuator: { wn: 30, zeta: 0.7 }, delay_s: 0.035, pade_order: 2 });
});

test("validateActuatorDelay: 서버 제약 미러 — wn·zeta는 양수, delay_s는 비음수, pade_order는 1 이상 정수", () => {
  assert.ok(validateActuatorDelay(adRow({ wn: "0" })).errors);
  assert.ok(validateActuatorDelay(adRow({ zeta: "-0.1" })).errors);
  assert.ok(validateActuatorDelay(adRow({ delaySeconds: "-0.01" })).errors);
  assert.ok(validateActuatorDelay(adRow({ padeOrder: "0" })).errors);
  assert.ok(validateActuatorDelay(adRow({ padeOrder: "1.5" })).errors); // 정수 아님
});

test("validateActuatorDelay: 꺼진 그룹의 필드는 검증 생략 (빈 값이어도 통과)", () => {
  const r = validateActuatorDelay(adRow({ useActuator: false, wn: "", zeta: "abc" }));
  assert.ok(!r.errors);
  assert.equal(r.actuator, null);
});

test("validateActuatorDelay: 수치 파싱 함정 — 빈 문자열·비유한 거부 (켜진 상태에서)", () => {
  assert.ok(validateActuatorDelay(adRow({ wn: "" })).errors);
  assert.ok(validateActuatorDelay(adRow({ delaySeconds: "1e999" })).errors);
});


test("지연 칸 기본값은 툴 기본값 — 엔진 기본(항법 출력 지연 + 제어주기 반주기)과 대조하고, 결과 캡션이 출처를 말한다", () => {
  // 정본을 직접 읽어 대조 — 엔진 기본값이 바뀌면 이 칸의 「0.03 + 0.005」 설명이 거짓이 된다
  const nav = readFileSync(new URL("../../../engine/claw/nav/error_model.py", import.meta.url), "utf8");
  const navDelay = Number(/ParamDef\("delay_s", ([\d.]+),/.exec(nav)?.[1]);
  const shape = readFileSync(new URL("../../../engine/claw/pipeline/influence.py", import.meta.url), "utf8");
  const hz = Number(/control_hz: float = ([\d.]+)/.exec(shape)?.[1]);
  assert.ok(Math.abs(DELAY_TOOL_DEFAULT.delay_s - (navDelay + 0.5 / hz)) < 1e-12, `${navDelay} + 0.5/${hz}`);
  assert.equal(DELAY_TOOL_DEFAULT.pade_order, 2);
  // 기체 문서 스키마에 지연 칸이 없다 — 생기면 작동기 칸처럼 문서에서 채우고 이 테스트를 고친다
  const schema = readFileSync(new URL("../../../engine/claw/profile/schema.py", import.meta.url), "utf8");
  assert.doesNotMatch(schema, /delay|latency/i);
  const ad = (d, p) => validateActuatorDelay({ useActuator: false, useDelay: true, delaySeconds: d, padeOrder: p });
  assert.match(delaySourceText(ad("0.035", "2")), /^툴 기본값 — 기체 문서에 지연 칸이 없어/);
  assert.equal(delaySourceText(ad("0.05", "2")), "입력값");
  assert.equal(delaySourceText(ad("0.035", "3")), "입력값");
  assert.equal(delaySourceText(validateActuatorDelay({ useActuator: false, useDelay: false })), null);
  assert.equal(delaySourceText(null), null);
});


// ── round1 #4 — 편집 행은 루프마다 문서를 따라간다 ─────────────────────────────────────────────────────

const seedAt = (kp) => [
  { name: "pitch_q", axis: "lon", x_out: "q", u_in: "de", kp: String(kp[0]), ki: "0", sign: "-1" },
  { name: "roll_p", axis: "lat", x_out: "p", u_in: "da", kp: String(kp[1]), ki: "0", sign: "-1" },
  { name: "yaw_r", axis: "lat", x_out: "r", u_in: "dr", kp: String(kp[2]), ki: "0", sign: "-1" },
];

test("followDocRows — yaw_r kp만 고친 뒤 점이 바뀌면 pitch_q·roll_p는 새 점의 문서 게인, yaw_r은 적은 값 그대로", () => {
  const A = seedAt([0.8, -0.47, 1.2]);
  const B = seedAt([0.5, -0.3, 1.2]);
  let rows = followDocRows([], A);
  assert.deepEqual(rows, A); // 처음 — 문서 행 그대로
  rows[2].kp = "1.1";
  rows[2].touched = true; // 편집 표 oninput
  rows = followDocRows(rows, B);
  assert.deepEqual(rows.map((r) => r.kp), ["0.5", "-0.3", "1.1"]);
  // 게인 기록 — 손대지 않은 두 루프는 문서 게인(칸별)이고, 손으로 적은 값은 yaw_r 하나다
  assert.deepEqual(docLoopNames(rows, B), ["pitch_q", "roll_p"]);
  const lawNames = docLoopNames(rows, B);
  const v = validateLoops(rows);
  assert.ok(v.loops, v.errors);
  const req = requestLoops(v.loops, lawNames);
  assert.equal(req[0].gain_source, "profile");
  assert.equal(req[1].gain_source, "profile");
  assert.equal(req[2].gain_source, undefined);
  assert.equal(req[2].kp, 1.1);
  assert.ok(!("touched" in req[2]), "편집 표시가 요청에 새지 않는다");
});

test("followDocRows — 지운 문서 루프는 되살리지 않고, 새 점에서 사라진 루프는 손대지 않았으면 빠진다", () => {
  const A = seedAt([0.8, -0.47, 1.2]);
  let rows = followDocRows([], A).filter((r) => r.name !== "roll_p"); // 사용자가 roll_p 삭제
  rows = followDocRows(rows, seedAt([0.5, -0.3, 1.0]), ["roll_p"]);
  assert.deepEqual(rows.map((r) => r.name), ["pitch_q", "yaw_r"]);
  // yaw_r이 새 점에서 게인 0이라 문서 행에서 빠지면 따라 빠진다 — 손댄 행은 남는다
  rows.push({ name: "loop_4", axis: "lon", x_out: "q", u_in: "de", kp: "0.5", ki: "0", sign: "-1", touched: true });
  rows = followDocRows(rows, seedAt([0.4, -0.2, 1.0]).slice(0, 2), ["roll_p"]);
  assert.deepEqual(rows.map((r) => r.name), ["pitch_q", "loop_4"]);
  assert.equal(rows[0].kp, "0.4");
  // 출처를 못 받으면(빈 문서 행) 손대지 않은 행은 모두 빠지고 손댄 행만 남는다
  assert.deepEqual(followDocRows(rows, []).map((r) => r.name), ["loop_4"]);
});

test("loopLoadState — 카탈로그 대기 중이면 loading(실행이 루프 0개로 돌지 않게, round1 #5)", () => {
  assert.equal(loopLoadState(null), "loading");
  assert.equal(loopLoadState(undefined), "loading");
  assert.equal(loopLoadState({ error: new Error("x") }), "error");
  assert.equal(loopLoadState({ loops: [] }), "ready");
  assert.match(LOOPS_LOADING_TEXT, /받는 중/);
});

// ── e2e D2 — 칸의 마진은 나이퀴스트 여유, 발산은 발산으로 ───────────────────────────────────────────────

const UNSTABLE = { gm_db: -4.8, pm_deg: -44.4, wcg: 20.6, wcp: 28.5,
  closed_loop: { stable: false, unstable: [[3.75, 23.0]] } };
const SLOW = { gm_db: 10.1, pm_deg: 81.8, wcg: 19.9, wcp: 7.1, closed_loop: { stable: false, unstable: [[0.0092, 0]] } };
const LEAD = { gm_db: 13.3, pm_deg: 70.5, wcg: 19.1, wcp: 0.19, pm_lead: true,
  crossings: { gain: [{ w: 0.19, pm_deg: -70.5 }, { w: 0.27, pm_deg: -147.3 }, { w: 1.86, pm_deg: -159.3 }, { w: 5.68, pm_deg: 87.0 }],
    phase: [{ w: 19.07, gm_db: 13.3 }, { w: 245, gm_db: 71.6 }] } };

test("marginCellView — 발산 칸은 수가 좋아 보여도 「발산」·−∞(부족 색), 그 밖은 수 그대로", () => {
  assert.deepEqual(marginCellView(SLOW, "pm_deg"), { value: -Infinity, text: "발산", unstable: true });
  assert.deepEqual(marginCellView(SLOW, "gm_db"), { value: -Infinity, text: "발산", unstable: true });
  assert.deepEqual(marginCellView(LEAD, "pm_deg"), { value: 70.5, text: "70.5°", unstable: false });
  assert.deepEqual(marginCellView({ gm_db: "inf", pm_deg: 60 }, "gm_db"), { value: "inf", text: "∞ dB", unstable: false });
  assert.deepEqual(marginCellView({ gm_db: null, pm_deg: 60 }, "gm_db"), { value: null, text: "—", unstable: false });
  assert.equal(marginCellView(undefined, "pm_deg"), null);
  assert.equal(marginUnstable(LEAD), false);
});

const cell = (name, margins, converged = true) => ({ trim: { case: { name }, converged }, margins });

test("unstableCells·stableMarginEntries·unstableTail — 최악 보고는 발산을 먼저, 여유 최소는 안정 칸끼리", () => {
  const entries = [cell("c1", { pitch_q: LEAD, roll_p: SLOW }), cell("c2", { pitch_q: UNSTABLE, roll_p: LEAD }),
    cell("c3", { pitch_q: UNSTABLE }, false)];
  const loops = [{ name: "pitch_q" }, { name: "roll_p" }];
  const bad = unstableCells(entries, loops);
  assert.deepEqual(bad.map((c) => `${c.loop}@${c.entry.trim.case.name}`), ["roll_p@c1", "pitch_q@c2"]); // 미수렴 칸 제외
  const st = stableMarginEntries(entries);
  assert.deepEqual(Object.keys(st[0].margins), ["pitch_q"]);
  assert.deepEqual(Object.keys(st[1].margins), ["roll_p"]);
  assert.equal(st[0].trim, entries[0].trim);
  assert.equal(entries[0].margins.roll_p, SLOW, "원본은 그대로");
  assert.equal(unstableTail(bad), "폐루프 발산 2칸 — roll_p @ c1 (극 0.0092 rad/s)");
  assert.equal(unstableTail([bad[1]]), "폐루프 발산 1칸 — pitch_q @ c2 (극 3.75 ± 23j rad/s)");
  assert.equal(unstableTail([]), null);
});

test("marginSemanticsText — 끊는 자리·나이퀴스트 거리·발산·게인 탭 판정 범위를 말한다", () => {
  const body = {
    loops: [{ name: "pitch_q" }, { name: "roll_p" }, { name: "yaw_r" }],
    cases: [cell("c1", { pitch_q: LEAD, roll_p: { ...LEAD, pm_lead: undefined, closed_with: ["yaw_r"] },
      yaw_r: { gm_db: 17.9, pm_deg: 89, gm_lower: true, closed_with: ["roll_p"] } })],
  };
  const t = marginSemanticsText(body);
  assert.match(t, /roll_p\(닫음: yaw_r\) · yaw_r\(닫음: roll_p\)/);
  assert.match(t, /−1까지의 거리/);
  assert.match(t, /1칸은 위상이 앞서는\(진상\) 쪽이, 1칸은 이득을 줄이는 쪽이 가장 가깝다/);
  assert.match(t, /하드 게이트도 레이트 루프 GM·PM을 같은 끊는 자리/);
  assert.doesNotMatch(t, /재지 않는다/);
  assert.doesNotMatch(t, /발산/);
  const t2 = marginSemanticsText({ loops: [{ name: "pitch_q" }], cases: [cell("c", { pitch_q: UNSTABLE })] });
  assert.match(t2, /하나를 끊은 개루프/);
  assert.match(t2, /1칸은 이 루프를 닫은 폐루프가 발산한다/);
  assert.equal(marginSemanticsText({ loops: [], cases: [] }), null);
});

test("bodeMarginNotes·bodeOthers — 곡선 밑 주석과 칸과 같은 조립(닫아 둘 루프)", () => {
  const n = bodeMarginNotes({ ...LEAD, closed_with: ["yaw_r"] });
  assert.match(n[0], /yaw_r를 닫은 개루프/);
  assert.match(n[1], /진상 쪽/);
  assert.match(n[2], /0 dB 교차 4개 · −180° 교차 2개/);
  assert.match(n[2], /루프 교차\(가장 높은 0 dB 교차 5.68 rad\/s\)의 PM은 87°/);
  const u = bodeMarginNotes(UNSTABLE);
  assert.equal(u.length, 1);
  assert.match(u[0], /발산한다\(극 3.75 ± 23j rad\/s\)/);
  const low = bodeMarginNotes({ gm_db: 6, pm_deg: 60, gm_lower: true });
  assert.equal(low.length, 1);
  assert.match(low[0], /^GM은 이득을 그만큼 줄이면 −1에 닿는 거리다/);
  assert.deepEqual(bodeMarginNotes({ gm_db: 9, pm_deg: 50 }), []);
  const loops = [{ name: "pitch_q" }, { name: "roll_p" }, { name: "yaw_r" }];
  assert.deepEqual(bodeOthers(loops, { closed_with: ["yaw_r"] }), [{ name: "yaw_r" }]);
  assert.deepEqual(bodeOthers(loops, {}), []);
});
