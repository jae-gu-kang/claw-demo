// PI 개루프 스펙 편집 로직 검증 — 마진 맵 다중 루프 폼의 계약
import { test } from "node:test";
import assert from "node:assert/strict";

import { AXIS_NAMES, DEFAULT_LOOPS, validateLoops } from "./loops.js";

test("AXIS_NAMES: 엔진 linearize 상태·입력 이름 스냅샷 (수동 사본 — 단방향 보호)", () => {
  // 정본은 engine/claw/trim/linearize.py — 엔진 rename 시 여기도 갱신할 것.
  // 서버가 422로 재검증하므로 낡아도 기능은 깨지지 않고 사전검증만 무뎌진다.
  assert.deepEqual(AXIS_NAMES.lon, { states: ["u", "w", "q", "theta"], inputs: ["de", "thr"] });
  assert.deepEqual(AXIS_NAMES.lat, { states: ["v", "p", "r", "phi"], inputs: ["da", "dr"] });
});

test("DEFAULT_LOOPS: 3축 레이트 루프 프리셋 — 전부 유효 + 기존 pitch_q 유지", () => {
  const r = validateLoops(DEFAULT_LOOPS);
  assert.ok(!r.errors, JSON.stringify(r.errors));
  assert.equal(r.loops.length, 3);
  // 기존 단일 루프 폼의 기본값(피치레이트 δe→q, kp 0.5·ki 0.8)과 호환 유지
  assert.deepEqual(r.loops[0],
    { name: "pitch_q", axis: "lon", x_out: "q", u_in: "de", kp: 0.5, ki: 0.8, sign: -1 });
  assert.deepEqual(r.loops.map((l) => [l.axis, l.x_out, l.u_in]),
    [["lon", "q", "de"], ["lat", "p", "da"], ["lat", "r", "dr"]]);
  assert.equal(new Set(r.loops.map((l) => l.name)).size, 3);
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

test("validateLoops: 수치 파싱 함정 — 빈 문자열·비수치·비유한 거부 (Number('')===0)", () => {
  assert.ok(validateLoops([row({ kp: "" })]).errors);
  assert.ok(validateLoops([row({ ki: "abc" })]).errors);
  assert.ok(validateLoops([row({ sign: "1e999" })]).errors);
  // 오류에 어느 루프인지 표시 (여러 행일 때 위치 특정)
  const r = validateLoops([row(), row({ name: "roll_p", kp: "x" })]);
  assert.ok(r.errors.some((e) => e.includes("roll_p")));
});
