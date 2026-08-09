// PI 개루프 스펙 편집 로직 검증 — 마진 맵 다중 루프 폼의 계약
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { AXIS_NAMES, DEFAULT_LOOPS, validateLoops } from "./loops.js";

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
