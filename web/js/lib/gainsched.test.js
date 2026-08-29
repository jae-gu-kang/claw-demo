// 게인 스케줄 자리 선택 — 격자 조립·선택 반영·스토어 계약 (자리 정본은 엔진)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  alignTables, appliedTables, defaultSelection, fixedGains, schedSummary, slotRows,
  storePayload, toggleSlot, zeroTables,
} from "./gainsched.js";
import { valueAt } from "./gainsync.js";

const tab = (v) => ({ axes: { mach: [0.2, 0.6] }, data: [v * 2, v], extrapolate: "clip" });

const on = (name, group, key, design) => ({
  name, group, key, available: true, scheduled: true, design,
  table: tab(design), unit: "-", param: key,
});
const off = (name, group, key, design, param = key) => ({
  name, group, key, available: true, scheduled: false, design,
  table: tab(design), unit: "-", param,
});
const no = (name, group, key) => ({
  name, group, key, available: false, reason: "이 축은 rate 입력이 없다",
});

const CAT = {
  axis: "mach", filter_tau: 0.5,
  default: ["pitch.kp", "pitch.ki"],
  slots: [
    on("pitch.kp", "pitch", "kp", -2.0),
    on("pitch.ki", "pitch", "ki", -0.5),
    off("pitch.k_rate", "pitch", "k_rate", 0.4),
    off("yaw.ki", "yaw", "ki", 0.0),
    off("alt.k_rate", "alt", "k_rate", -0.008, "k_hdot"),
    off("speed.kp", "speed", "kp", 0.15, "kp_spd"),
    no("speed.k_rate", "speed", "k_rate"),
  ],
};

test("격자는 그룹별 3열 — 불가 자리도 칸을 차지한다", () => {
  const rows = slotRows(CAT);
  assert.deepEqual(rows.map((r) => r.group), ["pitch", "yaw", "alt", "speed"]);
  assert.equal(rows[0].label, "피치");
  // 없는 조합은 null — 열이 어긋나면 어느 게인을 켜는지 알 수 없게 된다
  assert.deepEqual(rows[1].cells.map((c) => c && c.name), [null, "yaw.ki", null]);
  const speed = rows[3].cells;
  assert.equal(speed[0].name, "speed.kp");
  assert.equal(speed[2].available, false);
  assert.deepEqual(slotRows(null), []);
});

test("처음 선택은 서버가 켜져 있다고 한 자리", () => {
  assert.deepEqual(defaultSelection(CAT), ["pitch.kp", "pitch.ki"]);
  assert.deepEqual(defaultSelection({}), []);
});

test("토글은 켜고 끄고, 불가 자리는 무시한다", () => {
  const one = toggleSlot(CAT, ["pitch.kp"], "yaw.ki");
  assert.deepEqual(one, ["pitch.kp", "yaw.ki"]);
  assert.deepEqual(toggleSlot(CAT, one, "pitch.kp"), ["yaw.ki"]);
  assert.deepEqual(toggleSlot(CAT, ["pitch.kp"], "speed.k_rate"), ["pitch.kp"]);
  assert.deepEqual(toggleSlot(CAT, ["pitch.kp"], "없는.자리"), ["pitch.kp"]);
});

test("적용 테이블은 고른 자리만 — 카탈로그 순서 유지", () => {
  const t = appliedTables(CAT, ["alt.k_rate", "pitch.kp"]);
  assert.deepEqual(Object.keys(t), ["pitch.kp", "alt.k_rate"]);
  assert.deepEqual(t["pitch.kp"], CAT.slots[0].table);
  // 불가 자리를 우겨 넣어도 안 실린다 — 서버가 422로 거부할 형상이다
  assert.deepEqual(Object.keys(appliedTables(CAT, ["speed.k_rate"])), []);
});

test("끈 자리는 설계 상수로 굳는다 — 무엇이 되는지 알려 준다", () => {
  const fixed = fixedGains(CAT, ["pitch.kp", "pitch.ki"]);
  assert.deepEqual(fixed.map((f) => f.name),
    ["pitch.k_rate", "yaw.ki", "alt.k_rate", "speed.kp"]);
  // AP 축은 설계 파라미터 이름이 다르다 (alt.k_rate = k_hdot)
  assert.equal(fixed[2].design, -0.008);
  assert.equal(fixed[2].param, "k_hdot");
});

test("설계값이 0인 자리를 켜면 표가 전부 0 — 편집 전엔 효과가 없다", () => {
  assert.deepEqual(zeroTables(CAT, ["pitch.kp", "yaw.ki"]), ["yaw.ki"]);
  assert.deepEqual(zeroTables(CAT, ["pitch.kp"]), []);
});

test("요약은 켠 자리 수와 고정 자리 수", () => {
  assert.equal(schedSummary(CAT, ["pitch.kp", "pitch.ki"]),
    "6자리 중 2개 스케줄 · 4개 설계점 고정");
  assert.equal(schedSummary(CAT, []), "스케줄 없음 — 6자리 전부 설계점 고정");
  assert.equal(schedSummary(null, []), "");
});

test("전부 끔은 '편집 없음'과 다른 신호다", () => {
  // 빈 dict를 보내면 서버가 422, 아무것도 안 보내면 설계 기본 6자리로 되돌아간다.
  // 그 둘 어느 쪽도 "스케줄 없는 형상"이 아니라 별도 신호가 필요하다
  const some = storePayload(CAT, ["pitch.kp"]);
  assert.deepEqual(Object.keys(some.tables), ["pitch.kp"]);
  assert.equal(some.scheduleOff, false);

  const none = storePayload(CAT, []);
  assert.equal(none.tables, null);
  assert.equal(none.scheduleOff, true);

  // 불가 자리만 골라도 결과는 '전부 끔'이다 — 빈 dict가 새어 나가면 안 된다
  assert.deepEqual(storePayload(CAT, ["speed.k_rate"]),
    { tables: null, scheduleOff: true });
});

// ── 축 정렬 (자동 설계 확정본은 자리마다 breakpoint가 다르다) ──

test("합집합 축 정렬은 조회 함수를 보존한다 — 표시를 위해 값이 왜곡되지 않는다", () => {
  const tables = {
    a: { axes: { mach: [0.2, 0.6] }, data: [4, 2], extrapolate: "clip" },
    b: { axes: { mach: [0.2, 0.4, 0.6] }, data: [1, 5, 3], extrapolate: "clip" },
  };
  const out = alignTables(tables, "mach");
  assert.equal(out.aligned, true);
  assert.deepEqual(out.axis, [0.2, 0.4, 0.6]);
  // a는 0.4가 새로 생기지만 그 값은 원래 구간의 보간값이라 함수가 그대로다
  assert.deepEqual(out.tables.a.data, [4, 3, 2]);
  assert.deepEqual(out.tables.b.data, [1, 5, 3]); // b는 이미 합집합과 같다
  for (const name of ["a", "b"]) {
    for (const m of [0.2, 0.3, 0.4, 0.5, 0.6, 0.05, 9.9]) {
      assert.equal(valueAt(out.tables[name], "mach", m),
        valueAt(tables[name], "mach", m), `${name} @M${m}`);
    }
  }
});

test("이미 축이 같으면 그대로 둔다 (원본 참조 유지 — 셀 편집 경로가 끊기지 않는다)", () => {
  const tables = {
    a: { axes: { mach: [0.2, 0.6] }, data: [4, 2], extrapolate: "clip" },
    b: { axes: { mach: [0.2, 0.6] }, data: [1, 3], extrapolate: "clip" },
  };
  const out = alignTables(tables, "mach");
  assert.equal(out.aligned, false);
  assert.equal(out.tables, tables);
  assert.deepEqual(out.axis, [0.2, 0.6]);
});

test("축이 없는 표가 섞이면 null — 호출자가 사유를 보고한다", () => {
  assert.equal(alignTables({ a: { axes: { alt: [0, 1] }, data: [1, 2] } }, "mach"), null);
  assert.deepEqual(alignTables({}, "mach"), { tables: {}, axis: [], aligned: false });
});
