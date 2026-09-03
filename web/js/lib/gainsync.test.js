// 상수 ↔ 스케줄 테이블 동기화 — 블록도 폼과 게인 탭이 같은 값을 쓰는지
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  constantOf, designCoord, designPointValue, designValue, foldToConstant, fullConstants,
  lockedParams, scasKwargs, seedTable, selectedSlots, slotIndex, valueAt, withConstant,
} from "./gainsync.js";

// 설계점 = 인덱스 1 (스케일 1). 인덱스 0은 저마하 스케일 4배 자리.
const tab = (v) => ({ axes: { mach: [0.2, 0.6] }, data: [v * 4, v], extrapolate: "clip" });

const slot = (name, group, key, design, block, param = key, scheduled = false) => ({
  name, group, key, available: true, scheduled, design,
  table: tab(design), unit: "-", desc: "", param, block,
});

const CAT = {
  axis: "mach", filter_tau: 0.5, design_index: 1,
  default: ["pitch.kp"],
  slots: [
    slot("pitch.kp", "pitch", "kp", -2.0, "scas", "kp", true),
    slot("yaw.kp", "yaw", "kp", 0.5, "scas"),
    slot("yaw.ki", "yaw", "ki", 0.0, "scas"),
    slot("alt.k_rate", "alt", "k_rate", -0.008, "autopilot", "k_hdot"),
    slot("speed.kp", "speed", "kp", 0.15, "autopilot", "kp_spd"),
    { name: "speed.k_rate", group: "speed", key: "k_rate", available: false, reason: "rate 없음" },
  ],
};
const S = (n) => slotIndex(CAT).get(n);

// 서버 카탈로그는 SCAS 축 kwargs 전량을 함께 준다 (게인 자리 밖의 washout_tau·클램프 포함)
const CATD = { ...CAT, scas_design: {
  pitch: { kp: -2.0, ki: -0.5, k_rate: 0.4, washout_tau: 0.0, out_lo: -0.35, out_hi: 0.35 },
  roll: { kp: 1.0, ki: 0.1, k_rate: -0.2, washout_tau: 0.0, out_lo: -0.35, out_hi: 0.35 },
  yaw: { kp: 0.5, ki: 0.0, k_rate: 0.8, washout_tau: 2.0, out_lo: -0.35, out_hi: 0.35 },
} };

test("자리 목록은 켤 수 있는 자리만 — 구조상 불가 자리는 값이 없다", () => {
  const idx = slotIndex(CAT);
  assert.equal(idx.size, 5);
  assert.equal(idx.has("speed.k_rate"), false);
});

test("상수는 스토어 값 우선, 없으면 카탈로그 설계값", () => {
  assert.equal(constantOf(S("yaw.kp"), {}), 0.5);
  assert.equal(constantOf(S("yaw.kp"), { scas: { yaw: { kp: 0.9 } } }), 0.9);
  assert.equal(constantOf(S("alt.k_rate"), {}), -0.008);
  // AP는 자리 이름이 아니라 파라미터 이름으로 산다 (alt.k_rate = k_hdot)
  assert.equal(constantOf(S("alt.k_rate"), { autopilot: { k_hdot: -0.02 } }), -0.02);
  // 0은 유효한 값이다 — ?? 가 아니라 typeof로 걸러야 한다
  assert.equal(constantOf(S("yaw.ki"), { scas: { yaw: { ki: 0 } } }), 0);
});

test("상수 편집은 전체 kwargs를 유지한 새 객체 — 원본 불변", () => {
  const before = { scas: { yaw: { kp: 0.5, ki: 0.0 } }, autopilot: {} };
  const after = withConstant(CAT, S("yaw.kp"), 0.9, before);
  assert.equal(after.scas.yaw.kp, 0.9);
  assert.equal(before.scas.yaw.kp, 0.5, "원본이 바뀌었다");
  // 같은 축의 다른 게인은 살아 있어야 한다 (부분 dict를 보내면 서버가 0으로 채운다)
  assert.equal(after.scas.yaw.ki, 0.0);
  // 다른 축·AP 자리도 설계값으로 채워져 나온다 — 전체 kwargs 계약
  assert.equal(after.scas.pitch.kp, -2.0);
  assert.equal(after.autopilot.k_hdot, -0.008);
});

test("AP 상수 편집은 파라미터 이름 자리에 들어간다", () => {
  const after = withConstant(CAT, S("alt.k_rate"), -0.02, {});
  assert.equal(after.autopilot.k_hdot, -0.02);
  assert.equal("alt.k_rate" in after.autopilot, false);
});

test("스케줄 대상이 아닌 파라미터는 덧대기에서 살아남는다", () => {
  const full = fullConstants(CATD, { scas: { yaw: { washout_tau: 3.0 } } });
  assert.equal(full.scas.yaw.washout_tau, 3.0, "카탈로그가 모르는 값이 지워졌다");
  assert.equal(full.scas.yaw.kp, 0.5);
});

test("SCAS 상수 편집이 워시아웃·클램프를 떨구지 않는다 — 게인 자리만 채우면 안 된다", () => {
  // 블록도에서 아무것도 안 고친 상태에서 게인 탭이 요축 kp만 바꾼 경우
  const after = withConstant(CATD, S("yaw.kp"), 0.9, {});
  assert.equal(after.scas.yaw.kp, 0.9);
  assert.equal(after.scas.yaw.washout_tau, 2.0, "워시아웃이 사라졌다 (서버가 0으로 채운다)");
  assert.equal(after.scas.yaw.out_hi, 0.35, "출력 클램프가 사라졌다");
  assert.equal(after.scas.pitch.out_lo, -0.35);
});

test("SCAS kwargs는 설계값 위에 편집본 — 편집이 없어도 0이 아니다", () => {
  assert.deepEqual(scasKwargs(CATD, null), CATD.scas_design);
  const merged = scasKwargs(CATD, { yaw: { kp: 0.9 } });
  assert.equal(merged.yaw.kp, 0.9);
  assert.equal(merged.yaw.washout_tau, 2.0, "안 고친 값이 사라졌다");
  assert.equal(merged.pitch.kp, -2.0, "안 고친 축이 사라졌다");
  // 카탈로그가 없으면 스토어 값만, 그것도 없으면 주입 없음
  assert.deepEqual(scasKwargs(null, { yaw: { kp: 0.9 } }), { yaw: { kp: 0.9 } });
  assert.equal(scasKwargs(null, null), null);
});

test("켜진 자리는 gainTables 키 집합 — 미적용이면 서버 기본", () => {
  assert.deepEqual(selectedSlots(CAT, null, false), ["pitch.kp"]);
  assert.deepEqual(selectedSlots(CAT, { "yaw.kp": {}, "roll.ki": {} }, false),
    ["yaw.kp", "roll.ki"]);
  // 전부 끔은 빈 dict로 표현할 수 없어 별도 신호로 온다
  assert.deepEqual(selectedSlots(CAT, null, true), []);
});

test("잠긴 파라미터 = 스케줄이 덮고 있는 자리 (블록·그룹별)", () => {
  const sel = ["pitch.kp", "alt.k_rate"];
  assert.deepEqual([...lockedParams(CAT, sel, "scas", "pitch").keys()], ["kp"]);
  assert.deepEqual([...lockedParams(CAT, sel, "scas", "yaw").keys()], []);
  // AP는 kwargs가 한 벌이라 그룹 구분 없이 모은다
  assert.deepEqual([...lockedParams(CAT, sel, "autopilot").keys()], ["k_hdot"]);
  assert.deepEqual([...lockedParams(CAT, [], "scas", "pitch").keys()], []);
});

test("켜기 시드는 현재 상수 비율 — 설계점에서 상수와 일치", () => {
  const t = seedTable(CAT, S("yaw.kp"), 0.9);
  assert.equal(designPointValue(t, CAT.design_index), 0.9);
  assert.deepEqual(t.data, [3.6, 0.9]); // 스케일 형상(4:1) 보존
  assert.equal(t.extrapolate, "clip");
});

test("설계값 0인 자리는 비율을 못 재므로 상수 평탄표", () => {
  const t = seedTable(CAT, S("yaw.ki"), 0.3);
  assert.deepEqual(t.data, [0.3, 0.3]);
});

test("이미 맞는 표를 다시 심어도 그대로 — 켜고 끄기 반복에 누적되지 않는다", () => {
  const s = S("yaw.kp");
  const once = seedTable(CAT, s, 0.9);
  const twice = seedTable(CAT, { ...s, table: once }, 0.9);
  assert.deepEqual(twice.data, once.data);
});

test("끄기는 편집된 표의 설계점 값으로 굳는다 — 옛 설계 상수로 되돌아가지 않는다", () => {
  const edited = { "yaw.kp": { axes: { mach: [0.2, 0.6] }, data: [5.0, 1.25], extrapolate: "clip" } };
  assert.equal(foldToConstant(CAT, S("yaw.kp"), edited), 1.25);
  // 표가 없으면(켠 적 없음) 설계 상수 그대로
  assert.equal(foldToConstant(CAT, S("yaw.kp"), {}), 0.5);
});

test("켜기 → 끄기 왕복이 상수를 보존한다", () => {
  const s = S("alt.k_rate");
  const seeded = seedTable(CAT, s, -0.02);
  assert.equal(foldToConstant(CAT, s, { "alt.k_rate": seeded }), -0.02);
});

// ── 설계점을 **좌표**로 읽기 (자동 설계 확정본은 축 격자가 서버 제안과 다르다) ──

test("설계점 좌표는 제안 표의 design_index 위치 축 값", () => {
  assert.equal(designCoord(CAT), 0.6);
  assert.equal(designCoord(null), null);
  assert.equal(designCoord({ axis: "mach", slots: [] }), null);
});

test("valueAt은 구간 선형 보간 + 외삽 clip (엔진 Table과 같은 규칙)", () => {
  const t = { axes: { mach: [0.2, 0.6, 1.0] }, data: [4, 2, 0], extrapolate: "clip" };
  assert.equal(valueAt(t, "mach", 0.2), 4);
  assert.equal(valueAt(t, "mach", 0.6), 2);
  assert.equal(valueAt(t, "mach", 0.4), 3); // 구간 중점
  assert.equal(valueAt(t, "mach", 0.05), 4); // 하한 밖 — clip
  assert.equal(valueAt(t, "mach", 9.9), 0); // 상한 밖 — clip
  assert.equal(valueAt({ axes: {}, data: [] }, "mach", 0.5), null);
});

test("설계점 값은 축 격자가 달라도 같은 좌표에서 읽힌다", () => {
  // 자동 설계 확정본 — 축이 4점이고 서버 제안(2점)과 완전히 다르다.
  // 인덱스(design_index=1)로 읽으면 M0.4 칸(=3)이 설계점으로 둔갑한다
  const auto = { axes: { mach: [0.2, 0.4, 0.6, 0.8] }, data: [4, 3, 2, 1], extrapolate: "clip" };
  assert.equal(designValue(CAT, auto), 2); // M0.6의 값
  assert.equal(designPointValue(auto, CAT.design_index), 3); // 옛 인덱스 방식은 틀린다
  // 서버 제안 표(축 2점)에서는 둘이 같은 답을 낸다 — 회귀 없음
  const proposed = S("pitch.kp").table;
  assert.equal(designValue(CAT, proposed), designPointValue(proposed, CAT.design_index));
});

test("끄기는 축이 다른 확정본에서도 설계점 좌표 값으로 굳는다", () => {
  const auto = {
    "yaw.kp": { axes: { mach: [0.3, 0.6, 0.9] }, data: [9, 1.25, 0.5], extrapolate: "clip" },
  };
  assert.equal(foldToConstant(CAT, S("yaw.kp"), auto), 1.25);
});

test("설계점 좌표는 한 번 굳히면 표가 갈려도 흔들리지 않는다", () => {
  // 게인 탭이 확정본을 되읽으면 slot.table이 갈린다 — 그 뒤에도 기준은 그대로여야 한다
  const swapped = {
    ...CAT,
    slots: [{ ...CAT.slots[0], table: { axes: { mach: [0.9, 1.2] }, data: [1, 2] } }],
  };
  assert.equal(designCoord({ ...swapped, design_coord: 0.6 }), 0.6);
  assert.equal(designCoord(swapped), 1.2, "굳히지 않으면 갈아낀 표를 읽는다");
});
