// 탑재 C 패널 로직 — 요청 조립·파일 선택·제외 안내 (생성 자체는 엔진 소관)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  AP_KEY, ENTRY, excludedSpecs, flightRequest, pickFile, summarize,
} from "./flightcode.js";

const AP_SPEC = { key: AP_KEY, values: { kp_alt: 0.004, ki_alt: 0.0008 } };
const ACT_SPEC = { key: "actuator/SecondOrderActuator", values: { wn: 30.0 } };
const NAV_SPEC = { key: "nav/ErrorModel", values: { seed: 0 } };

const TABLES = {
  "pitch.kp": { axes: { mach: [0.2, 0.8] }, data: [-2.0, -1.0], extrapolate: "clip" },
};

const FILES = [
  { name: "fcl.h", role: "진입점", lines: 34 },
  { name: "fcl_types.h", role: "자료형", lines: 118 },
  { name: "fcl.c", role: "조립부", lines: 97 },
  { name: "fcl_sched.c", role: "서브시스템", lines: 54 },
];

test("오토파일럿 편집값이 요청에 실린다", () => {
  const req = flightRequest([AP_SPEC], null);
  assert.equal(req.control_hz, 100);
  assert.deepEqual(req.autopilot, { kp_alt: 0.004, ki_alt: 0.0008 });
  assert.ok(!("gain_tables" in req));
});

test("스펙 사본을 넘긴다 — 요청을 고쳐도 폼 값이 흔들리지 않는다", () => {
  const req = flightRequest([AP_SPEC], null);
  req.autopilot.kp_alt = 999;
  assert.equal(AP_SPEC.values.kp_alt, 0.004);
});

test("제어법칙이 아닌 블록만 있으면 autopilot을 안 보낸다 — 기본 형상이 나온다", () => {
  const req = flightRequest([ACT_SPEC], null);
  assert.ok(!("autopilot" in req));
});

test("게인 테이블은 구조를 바꾸므로 반드시 실어 보낸다", () => {
  const req = flightRequest([AP_SPEC], TABLES);
  assert.deepEqual(Object.keys(req.gain_tables), ["pitch.kp"]);
});

test("빈 테이블 dict는 생략한다 — 서버에서 '스케줄 없음'과 혼동된다", () => {
  const req = flightRequest([AP_SPEC], {});
  assert.ok(!("gain_tables" in req));
});

test("제어 주기를 바꾸면 요청에 반영된다 — dt는 형상의 일부다", () => {
  assert.equal(flightRequest([], null, { controlHz: 200 }).control_hz, 200);
});

test("스펙이 없거나 null이어도 터지지 않는다", () => {
  assert.deepEqual(flightRequest(undefined, undefined), { control_hz: 100 });
});

test("탑재 C에 안 들어가는 블록을 알려 준다", () => {
  const out = excludedSpecs([AP_SPEC, ACT_SPEC, NAV_SPEC]);
  assert.deepEqual(out.map((x) => x.key),
    ["actuator/SecondOrderActuator", "nav/ErrorModel"]);
  assert.match(out[0].why, /플랜트/);
  assert.equal(excludedSpecs([AP_SPEC]).length, 0);
});

test("고른 파일이 사라지면 진입점으로 떨어진다", () => {
  // 스케줄을 끄면 fcl_sched.c가 통째로 없어진다 — 빈 화면이 되면 안 된다
  const without = FILES.filter((f) => f.name !== "fcl_sched.c");
  assert.equal(pickFile(without, "fcl_sched.c").name, ENTRY("fcl"));
  assert.equal(pickFile(FILES, "fcl_sched.c").name, "fcl_sched.c");
  assert.equal(pickFile(FILES, null).name, "fcl.h");
  assert.equal(pickFile([], "fcl.h"), null);
});

test("진입점조차 없으면 첫 파일 — 산출물 이름이 달라도 빈 화면은 아니다", () => {
  const other = [{ name: "scas_yaw.c", role: "조립부", lines: 36 }];
  assert.equal(pickFile(other, "fcl.h").name, "scas_yaw.c");
});

test("요약은 파일 수와 총 줄 수", () => {
  assert.deepEqual(summarize(FILES), { count: 4, lines: 303 });
  assert.deepEqual(summarize(null), { count: 0, lines: 0 });
});
