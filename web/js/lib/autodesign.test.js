/** autodesign 순수 로직 검증 — 설정 페이로드, 점·판정 결합, 처방 그룹, 게인 채택. */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  actionCards,
  adoptStorePayload,
  buildConfig,
  pointRows,
  statusRank,
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
