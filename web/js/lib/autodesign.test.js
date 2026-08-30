/** autodesign 순수 로직 검증 — 설정 페이로드, 점·판정 결합, 처방 그룹, 게인 채택. */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  actionCards,
  adoptStorePayload,
  buildConfig,
  pointRows,
  statusCounts,
  statusRank,
  verdictLegend,
  worstStatus,
} from "./autodesign.js";

const RESULT = {
  points: {
    points: [
      { name: "A", mach: 0.3, alt: 1000, fuel: 200, role: "anchor", trimmable: true },
      { name: "V", mach: 0.4, alt: 1000, fuel: 200, role: "validation", trimmable: true },
      { name: "B", mach: 0.5, alt: 1000, fuel: 200, role: "breakpoint", trimmable: null },
    ],
  },
  margin_out: {
    cases: {
      A: { loops: { pitch_att: { status: "ok" }, pitch_rate: { status: "warn" } } },
      V: { loops: { pitch_att: { status: "fail" } } },
    },
  },
  proposed_actions: [
    { id: "a1", verdict: "gain_interp_valley", case: "V", loop: "pitch_att",
      action: { type: "promote", to: "breakpoint" }, evidence: {} },
    { id: "a2", verdict: "structural_limit", case: "V", loop: "roll_att",
      action: { type: "escalate" }, evidence: {} },
  ],
  gain_export: {
    tables: { "pitch.kp": { kind: "poly", axis: "mach", segments: [] } },
    tables_resampled: {
      "pitch.kp": { axes: { mach: [0.3, 0.5] }, data: [-8, -2], extrapolate: "clip" },
    },
    constants: { "yaw.k_rate": 0.4 },
  },
};

test("buildConfig — 채운 것만 덮어쓰고 수치 목록을 파싱한다", () => {
  const cfg = buildConfig({
    mode: "auto", budgetPoints: "60", budgetIters: "3",
    nMach: "4", altsText: "0, 3000", fuelsText: "",
  });
  assert.deepEqual(cfg, {
    mode: "auto", budget_points: 60, budget_iters: 3, n_mach: 4, alts: [0, 3000],
  });
});

test("buildConfig — 잘못된 수치 목록은 던진다", () => {
  assert.throws(() => buildConfig({ mode: "gated", altsText: "abc" }));
});

test("worstStatus — fail > warn > na > ok", () => {
  assert.equal(worstStatus({ a: { status: "ok" }, b: { status: "warn" } }), "warn");
  assert.equal(worstStatus({ a: { status: "warn" }, b: { status: "fail" } }), "fail");
  assert.equal(worstStatus({}), null);
  assert.ok(statusRank("fail") > statusRank("ok"));
});

test("pointRows — 점과 검증 판정을 이름으로 결합한다", () => {
  const rows = pointRows(RESULT);
  assert.equal(rows.length, 3);
  const v = rows.find((r) => r.name === "V");
  assert.equal(v.role, "validation");
  assert.equal(v.status, "fail");
  const b = rows.find((r) => r.name === "B");
  assert.equal(b.status, null); // 마진맵에 없는 점 — 미판정으로 남긴다
});

test("actionCards — 승인 가능/에스컬레이션 분리, supersede 제외", () => {
  const withSuperseded = {
    ...RESULT,
    proposed_actions: [
      ...RESULT.proposed_actions,
      { id: "a3", verdict: "simple_deficit", case: "V", loop: "x",
        action: { type: "add_validation" }, superseded_by: "V→anchor" },
    ],
  };
  const cards = actionCards(withSuperseded);
  assert.deepEqual(cards.approvable.map((a) => a.id), ["a1"]); // a3은 supersede — 제외
  assert.deepEqual(cards.escalations.map((a) => a.id), ["a2"]);
});

test("adoptStorePayload — 재샘플 테이블을 기존 스토어 계약으로 낸다", () => {
  const p = adoptStorePayload(RESULT);
  assert.equal(p.scheduleOff, false);
  assert.deepEqual(Object.keys(p.tables), ["pitch.kp"]);
  assert.deepEqual(p.tables["pitch.kp"].axes.mach, [0.3, 0.5]);
  // 반출이 비면 스케줄 없음 신호
  const empty = adoptStorePayload({ gain_export: { tables_resampled: {} } });
  assert.equal(empty.tables, null);
  assert.equal(empty.scheduleOff, true);
});

test("adoptStorePayload — 상수 자리를 버리지 않는다 (검증한 형상 = 채택한 형상)", () => {
  const p = adoptStorePayload(RESULT);
  assert.deepEqual(p.constants, { "yaw.k_rate": 0.4 });
  // 전 자리가 상수로 접혀도 상수는 살아 있어야 한다 — 그때가 가장 위험하다
  const allConst = adoptStorePayload({
    gain_export: { tables_resampled: {}, constants: { "pitch.kp": -2, "roll.kp": 1 } },
  });
  assert.equal(allConst.tables, null);
  assert.equal(allConst.scheduleOff, true);
  assert.deepEqual(allConst.constants, { "pitch.kp": -2, "roll.kp": 1 });
  // 반출이 아예 없으면 빈 객체 (undefined 접근 금지)
  assert.deepEqual(adoptStorePayload({}).constants, {});
});

test("statusCounts — 미판정을 통과로 세지 않는다", () => {
  // status null은 "판정을 못 했다"이지 "합격"이 아니다 — 한 칸으로 뭉치면
  // 트림 불가·판정 불가 점이 ok 개수에 섞여 실행이 실제보다 건강해 보인다
  // A는 pitch_att ok + pitch_rate warn → 점 판정은 최악값 warn (worstStatus 규약)
  const c = statusCounts(pointRows(RESULT));
  assert.deepEqual(c, { ok: 0, warn: 1, fail: 1, na: 0, unjudged: 1 });
  assert.deepEqual(statusCounts(undefined),
    { ok: 0, warn: 0, fail: 0, na: 0, unjudged: 0 });
});

test("verdictLegend — 기준 수치를 결과에서 읽어 문장에 박는다", () => {
  const lines = verdictLegend({
    pm_min_deg: 45, gm_min_db: 6, gm_good_db: 8, zeta_min: 0.3, zeta_good: 0.5,
  });
  assert.deepEqual(lines.map((l) => l.key), ["ok", "warn", "fail", "na"]);
  const ok = lines.find((l) => l.key === "ok").text;
  const warn = lines.find((l) => l.key === "warn").text;
  // ok는 **목표선**(gm_good), warn은 합격선~목표선 구간을 말해야 한다.
  // 여기가 어긋나면 화면이 warn을 "곧 실패"로 오해하게 설명한다
  assert.match(ok, /GM ≥ 8 dB/);
  assert.match(warn, /GM 6~8 dB/);
  assert.match(lines.find((l) => l.key === "fail").text, /GM < 6 dB/);
  // 기준을 바꾸면 문장도 따라가야 한다 — 기본값을 웹에 다시 적으면 안 되는 이유
  const strict = verdictLegend({ pm_min_deg: 50, gm_min_db: 8, gm_good_db: 12 });
  assert.match(strict.find((l) => l.key === "ok").text, /PM ≥ 50° · GM ≥ 12 dB/);
});
